"""Read-only presentation of existing segment evidence; no new inference."""
from __future__ import annotations
import html
import json
from pathlib import Path
from urllib.parse import urlsplit

from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.profile_analysis import resolve_profile_sermon_scope,profile_membership_fingerprint
from pastor_transcript_extractor.sermon_topic_projection import assess_topic_profile_projection
from pastor_transcript_extractor.sermon_topics import resolve_topic_analysis_artifact,resolve_topic_block_context
from pastor_transcript_extractor.sermon_semantic_dimensions import SEMANTIC_DIMENSIONS
from pastor_transcript_extractor import sermon_salvation_relationships as salvation
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal

VERSION='segment-profile-view-v1'
POINTER=trace.ROOT/'docs/review-proposals/segment-cache-inventory-v1/review-v1.json'


def load(base_dir=None):
    pointer=trace.read(POINTER,True)
    # Resolve through the configured base rather than silently using another database.
    paths=build_paths(base_dir)
    path=paths.evaluation/'segment-cache-inventory-v1'/pointer['inventory_fingerprint']/'inventory-v1.json'
    if trace.digest(path)!=pointer['inventory_sha256']:raise ValueError('Reviewed inventory changed')
    inventory=trace.read(path,True)
    if inventory['content_fingerprint']!=pointer['inventory_fingerprint']:raise ValueError('Foreign inventory')
    database=Database(paths.database,readonly=True)
    selected=inventory['selected_profile'];scope=resolve_profile_sermon_scope(database,selected['id'])
    if profile_membership_fingerprint(database,scope)!=selected['membership_fingerprint']:
        raise ValueError('Reviewed profile membership changed; refresh the inventory')
    sources={}
    for sermon in inventory['sermons']:
        path=Path(sermon['source_path'])
        if trace.digest(path)!=sermon['source_sha256']:raise ValueError('Inventoried source changed')
        gate=assess_topic_profile_projection(database,database.get_video_by_id(sermon['video_id']))
        if not gate.eligible or gate.profile_id!=selected['id'] or gate.input_fingerprint!=sermon['gate']['input_fingerprint']:
            raise ValueError('Source eligibility or ownership changed')
        sources[sermon['video_id']]=trace.read(path)
    return inventory,sources


def build_view(inventory,sources):
    if seal(inventory)!=inventory:raise ValueError('Invalid inventory seal')
    sermons=[]
    for sermon in inventory['sermons']:
        classification=sources[sermon['video_id']]['classification']
        analysis=resolve_topic_analysis_artifact(classification)
        by_id={b['block_id']:b for b in analysis['blocks']}
        eligible=set(sermon['eligible_block_ids'])
        treatment={b['block_id']:b['probabilities'] for b in sermon['treatment']}
        examples=[]
        for example in sermon['topic_examples']:
            block=by_id[example['block_id']]
            if block['block_id'] not in eligible or resolve_topic_block_context(block)['target_text']!=example['full_target_text']:
                raise ValueError('Inventoried representative segment differs')
            examples.append(dict(**example,treatment=treatment.get(block['block_id']),
                watch_url=source_url(sermon['url'],block['start_seconds'])))
        salvation_blocks=[]
        for saved in sermon['salvation']:
            block=by_id[saved['block_id']]
            if block['block_id'] not in eligible:raise ValueError('Ineligible salvation evidence')
            # Display measured positive and below-threshold states separately.
            measured=[dict(leaf=k,label=k.replace('_',' '),probability=v,threshold=salvation.SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[k],
                state='observed' if any(o['relationship']==k for o in saved['observations']) else 'measured_below_threshold') for k,v in saved['probabilities'].items()]
            salvation_blocks.append(dict(block_id=block['block_id'],start_seconds=block['start_seconds'],end_seconds=block['end_seconds'],
                full_target_text=resolve_topic_block_context(block)['target_text'],measured=measured,
                watch_url=source_url(sermon['url'],block['start_seconds'])))
        sermons.append(dict(video_id=sermon['video_id'],title=sermon['title'],url=source_url(sermon['url'],0),
            eligible_blocks=sermon['eligible_blocks'],salvation_measured_blocks=sermon['salvation_measured_blocks'],
            topics=examples,salvation_blocks=salvation_blocks))
    return seal(dict(version=VERSION,status='READ_ONLY_EXISTING_SEGMENT_EVIDENCE_VIEW',
        inventory_fingerprint=inventory['content_fingerprint'],profile=inventory['selected_profile'],coverage=inventory['coverage'],sermons=sermons,
        gaps=inventory['gaps'],provider_requests=0,database_writes=0,new_measurements=False,new_profile_scores=False,
        quote_extraction=False,source_audit_of_all_raw_judgments=False))


def source_url(value,seconds):
    url=urlsplit(value)
    if url.scheme!='https' or url.hostname not in ('youtube.com','www.youtube.com','youtu.be'):
        raise ValueError('Unsupported recording link')
    return value+('&' if '?' in value else '?')+'t='+str(max(0,int(seconds)))


def timestamp(value):
    seconds=int(value);return f'{seconds//60}:{seconds%60:02d}'


def render(view):
    e=lambda value:html.escape(str(value),quote=True)
    parts=[]
    for sermon in view['sermons']:
        cards=[]
        for example in sermon['topics']:
            treatment=example['treatment']
            treatment_text=' · '.join(f'{k.replace("_"," ")}: {treatment[k]:.0%}' for k in SEMANTIC_DIMENSIONS) if treatment else 'Not measured for this segment.'
            metric=example['existing_sermon_measurement']['developed_emphasis_probability']
            cards.append(f'''<article class="topic"><div class="cardtop"><h3>{e(example['label'])}</h3><span class="metric">{metric:.3f}</span></div>
<p class="sub">Existing sermon mean of P(topic is at least supporting). Describes attention, not belief.</p>
<details><summary>Read supporting segment · {timestamp(example['start_seconds'])}–{timestamp(example['end_seconds'])}</summary>
<p><a href="{e(example['watch_url'])}" target="_blank" rel="noopener noreferrer">Open recording at segment</a> · Block {e(example['block_id'])}</p>
<div class="source">{e(example['full_target_text'])}</div><p class="sub">Cached treatment probabilities for this segment: {e(treatment_text)}</p></details></article>''')
        observations=[]
        for block in sermon['salvation_blocks']:
            positive=[m for m in block['measured'] if m['state']=='observed']
            label=', '.join(m['label'] for m in positive) if positive else 'No approved leaf reached its threshold'
            all_values=''.join(f"<tr><td>{e(m['label'])}</td><td>{m['probability']:.2f}</td><td>{m['threshold']:.2f}</td><td>{e(m['state'].replace('_',' '))}</td></tr>" for m in block['measured'])
            observations.append(f'''<details class="salblock"><summary>{timestamp(block['start_seconds'])} · {e(label)}</summary>
<p><a href="{e(block['watch_url'])}" target="_blank" rel="noopener noreferrer">Open recording</a> · Block {block['block_id']}</p><div class="source">{e(block['full_target_text'])}</div>
<div class="tablewrap"><table><thead><tr><th>Local observation</th><th>Probability</th><th>Frozen threshold</th><th>State</th></tr></thead><tbody>{all_values}</tbody></table></div></details>''')
        parts.append(f'''<section class="sermon" data-video="{sermon['video_id']}"><div class="sectionhead"><div><span class="eyebrow">RECORDING {sermon['video_id']}</span><h2>{e(sermon['title'])}</h2></div><a href="{e(sermon['url'])}" target="_blank" rel="noopener noreferrer">Recording ↗</a></div>
<p class="sub">{sermon['eligible_blocks']} eligible topic/treatment blocks · {sermon['salvation_measured_blocks']} routed salvation blocks</p>
<div class="topics">{''.join(cards)}</div><details class="salvation"><summary>Inspect salvation observations · {sermon['salvation_measured_blocks']} measured segments</summary>
<p>These are local cached judgments. Unrouted segments are unmeasured. Below threshold means no positive observation, not doctrinal denial. The three unresolved leaves remain unavailable.</p>{''.join(observations)}</details></section>''')
    filters=''.join(f'<button type="button" data-filter="{s["video_id"]}">{e(short_title(s["title"]))}</button>' for s in view['sermons'])
    gaps=''.join(f'<li>{e(g)}</li>' for g in view['gaps'])
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Segment evidence · profile 318</title><style>
:root{color-scheme:light;--ink:#182c32;--soft:#53676b;--line:#d6e0df;--accent:#14675e}*{box-sizing:border-box}body{margin:0;background:#f2f5f3;color:var(--ink);font:16px/1.6 system-ui,sans-serif}main{max-width:1160px;margin:0 auto;padding:44px 24px 70px}h1{font:500 clamp(32px,5vw,52px)/1.15 Georgia,serif;margin:12px 0 18px}h2{font:500 25px/1.3 Georgia,serif;margin:6px 0}h3{font-size:17px;margin:0}.eyebrow{font-size:12px;letter-spacing:.12em;color:var(--accent);font-weight:700}.lead{max-width:850px;font-size:18px}.sub{color:var(--soft);font-size:13px}.badge{display:inline-block;border:1px solid var(--line);border-radius:20px;padding:4px 12px;font-size:12px;background:white}.stats{display:flex;flex-wrap:wrap;gap:14px;margin:25px 0}.stat{background:white;border:1px solid var(--line);border-radius:12px;padding:14px 22px;min-width:170px}.stat strong{font-size:28px;display:block}.notice{border-left:4px solid var(--accent);padding:12px 18px;background:#e7eeea;max-width:940px}nav{display:flex;gap:8px;flex-wrap:wrap;margin:30px 0}button{font:inherit;font-size:14px;border:1px solid var(--line);border-radius:20px;background:white;padding:7px 15px;cursor:pointer}button[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:white}button:focus-visible,summary:focus-visible{outline:3px solid #bb8d3e;outline-offset:4px}.sermon{background:white;border:1px solid var(--line);border-radius:16px;padding:26px;margin:22px 0}.sectionhead{display:flex;align-items:start;gap:24px;justify-content:space-between}.sectionhead a{white-space:nowrap}a{color:var(--accent)}.topics{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:22px 0}.topic{border:1px solid var(--line);border-radius:12px;padding:18px}.cardtop{display:flex;gap:12px;justify-content:space-between}.metric{color:var(--accent);font-variant-numeric:tabular-nums;font-weight:600}.source{white-space:pre-wrap;border-left:2px solid var(--line);padding:12px 16px;margin:15px 0;background:#f8faf8;font:16px/1.65 Georgia,serif;overflow-wrap:anywhere}summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:14px}details[open]>summary{margin-bottom:12px}.salvation,.salblock{border-top:1px solid var(--line);padding:16px 0}.salblock summary{color:var(--ink)}.tablewrap{overflow-x:auto}table{border-collapse:collapse;font-size:13px;width:100%}td,th{text-align:left;padding:8px;border-bottom:1px solid var(--line)}footer{font-size:13px;color:var(--soft);padding-top:25px;border-top:1px solid var(--line)}[hidden]{display:none!important}@media(max-width:760px){.topics{grid-template-columns:1fr}.sermon{padding:18px}.sectionhead{display:block}.stat{min-width:125px}main{padding:28px 16px}}
</style></head><body><main><span class="eyebrow">PASTOR TRANSCRIPT EXTRACTOR · EVIDENCE PREVIEW</span><h1>What these sermons discuss</h1>
<span class="badge">Reviewed profile '''+str(view['profile']['id'])+''' · name not yet labeled</span><span class="badge">Read-only · existing observations</span>
<p class="lead">Explore a three-sermon sample through its topics, rhetorical treatment and local salvation observations. Open any supporting segment to read the source or jump to the recording.</p>
<div class="stats"><div class="stat"><strong>'''+str(len(view['sermons']))+'''</strong>recordings</div><div class="stat"><strong>'''+str(view['coverage']['eligible_topic_blocks'])+'''</strong>topic/treatment blocks</div><div class="stat"><strong>'''+str(view['coverage']['salvation_measured_blocks'])+'''</strong>routed salvation blocks</div></div>
<p class="notice">This shows attention and local observations in these recordings. It does not yet establish an overall theological position, independent recurrence, or a comparison score. Recording titles are metadata; the reviewed profile currently has no display label.</p>
<nav aria-label="Filter recordings"><button type="button" data-filter="all" aria-pressed="true">All recordings</button>'''+filters+'''</nav>'''+''.join(parts)+'''
<section class="sermon"><h2>What remains unknown</h2><ul>'''+gaps+'''</ul><h3>Illustrative quotations come later</h3><p>After a point is supported, configured Ollama may select a verbatim excerpt from its strongest minute, with the minute either side only for necessary continuation, qualifications or attribution. No quotation has been extracted here.</p></section>
<footer>No new model calls, database writes, measurements or profile scores. Existing source observations retain their original scope. Inventory: '''+e(view['inventory_fingerprint'])+'''</footer></main>
<script>document.querySelectorAll('button[data-filter]').forEach(button=>{button.setAttribute('aria-pressed',button.dataset.filter==='all'?'true':'false');button.addEventListener('click',()=>{document.querySelectorAll('button[data-filter]').forEach(b=>b.setAttribute('aria-pressed',b===button?'true':'false'));document.querySelectorAll('.sermon[data-video]').forEach(section=>section.hidden=button.dataset.filter!=='all'&&section.dataset.video!==button.dataset.filter);});});</script></body></html>'''


def short_title(title):
    for marker in (', Pastor',', by Pastor',' by John',' - By'):
        title=title.split(marker)[0]
    return title.strip('"')


def prepare(base_dir=None):
    inventory,sources=load(base_dir);view=build_view(inventory,sources)
    report=seal(dict(version=VERSION,view=view,renderer_sha256=trace.digest(__file__),provider_requests=0,database_writes=0))
    out=build_paths(base_dir).evaluation/VERSION/report['content_fingerprint'];out.mkdir(parents=True,exist_ok=True)
    for name,raw in [('view-v1.json',json.dumps(report,ensure_ascii=False,indent=2)+'\n'),('index.html',render(view))]:
        path=out/name
        if path.exists() and path.read_text()!=raw:raise ValueError('Immutable view differs')
        path.write_text(raw)
    return report,out/'index.html'
