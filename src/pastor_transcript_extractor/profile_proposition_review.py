"""Review the same ten source readings through generic binding + a narrow adapter."""
from copy import deepcopy
import html
import json
from pathlib import Path

from pastor_transcript_extractor import profile_binding_pilot as pilot
from pastor_transcript_extractor import theological_binding as generic
from pastor_transcript_extractor.assurance_binding_adapter import interpret
from pastor_transcript_extractor.binding_evidence import context_digest, text_digest
from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.segment_profile_view import timestamp

VERSION = 'profile-proposition-source-review-v1'
READINGS_PATH = Path(__file__).with_name('data') / 'profile-proposition-source-readings-v1.json'
FINDINGS = [
    'The mercy-versus-works prayer and God’s completion of a good work survive as distinct propositions without being forced into an assurance predicate.',
    'In The Shaking, saving desire despite known works, Paul’s honesty example, the lukewarm warning and the criticism of neutrality retain their different speakers and uses.',
    'Paul’s confession and Jesus’ warning are affirmatively used in the surrounding teaching. Adoption is supported by that discourse, not by quotation alone; a literal ranking of sinners and a salvation-loss mechanism remain unestablished.',
    'The American Experiment offers forgiveness and a place in heaven as invited confidence language. The projected declarations remain distinct from the preacher’s actual invitation and from an actual listener response.',
]
LIMITATIONS = [
    dict(id='automation',title='Source-reviewed bindings, not an automatic binder',
         meaning='The ten records are authored interpretations. Literal checks cannot establish semantic accuracy, automatic recall or general theological coverage.',
         remedy='Review these concrete records first; any future automatic binding/validation needs separate authorization.'),
    dict(id='qualifications',title='A concession is retained without widening conditions',
         meaning='The saving-desire “anyway” is an attached G2 qualification node with a reviewed explanation. The warning’s “because” uses G2 reason_supports_claim. No new concession ontology or necessary/sufficient salvation rule is introduced.',
         remedy='For cross-case qualification queries, separately define only the relation semantics actually needed; the present exact attachment remains usable for inspection.'),
    dict(id='positives',title='Positive conditions, exceptions and uncertainty are not demonstrated by this sample',
         meaning='The reusable structure retains these fields and focused authored controls exercise them, but none of the ten readings supplies an unambiguous positive bound salvation condition/exception or explicit theological uncertainty.',
         remedy='Leave these sample fields empty/not stated; do not infer unconditional doctrine, certainty, or validated detection from them.'),
    dict(id='mapping',title='Narrow assurance interpretation remains conservative',
         meaning='All ten original G1 records are unchanged. A generic adopted warning or offered confession does not establish adoption of a normalized assurance-loss/retention/knowability predicate. Narrow no-match and unresolved states do not erase the source proposition.',
         remedy='Use the separate reviewed mapping only where a subject-specific predicate is supported; no vocabulary expansion is needed merely to retain theology.'),
    dict(id='scope',title='Reports, projected responses and local use do not establish actual hearer status',
         meaning='“Actual” describes speech presented as occurring in the sermon/report; it does not verify historical quotation. Projected “I” belongs to an invited listener. External reference accuracy, listener uptake, production admission and pastor-wide tendencies remain unestablished.',
         remedy='Keep these limits visible; do not project these three passages into pastor-wide positions or initiate collection.'),
]


def build(baseline, authored):
    if authored['version'] != 'profile-proposition-source-readings-v1' or authored['baseline_report_fingerprint'] != baseline['content_fingerprint']:
        raise ValueError('The completed source-review baseline changed')
    original = [r for c in baseline['cases'] for r in c['readings']]
    by_id = {r['binding_id']:r for r in authored['readings']}
    if len(original) != 10 or len(by_id) != 10 or len(authored['readings']) != 10 or set(by_id) != {r['id'] for r in original}:
        raise ValueError('Retain exactly the ten completed source-reviewed readings')
    cases = []
    for case in baseline['cases']:
        result = {key:deepcopy(value) for key,value in case.items() if key != 'readings'}
        readings = []
        for old in case['readings']:
            provenance = {key:deepcopy(case[key]) for key in ('case_id','video_id','block_id','source_sha256','start_seconds','end_seconds','watch_url','context_diagnostics')}
            provenance.update(source_inventory_fingerprint=baseline['source_inventory_fingerprint'], membership_fingerprint=baseline['membership_fingerprint'],
                target_sha256=text_digest(case['texts']['target_text']), texts_sha256=context_digest(case['texts']),
                baseline_report_fingerprint=baseline['content_fingerprint'], reviewed_source_input_sha256=authored['baseline_input_sha256'])
            binding = generic.bind(case['texts'], by_id[old['id']], provenance)
            assurance = interpret(binding, case['texts'], old)
            if assurance['g1_record'] != old['g1_record']:
                raise ValueError('Existing G1 interpretation changed')
            readings.append(dict(binding=binding,assurance_interpretation=assurance,
                original_g1_record_unchanged=True, reviewed_subject_mapping={key:deepcopy(old[key]) for key in ('authored_decisions','phrase_pools','field_review','additional_binding_evidence','withheld_conclusions')}))
        result['readings'] = readings
        cases.append(result)
    return seal(dict(version=VERSION,status='GENERIC_BINDING_AND_SUBJECT_INTERPRETATION_SEPARATED_PROPOSALS_READY_FOR_REVIEW',
        cases=cases, findings=FINDINGS, limitations=LIMITATIONS,
        source_inventory_fingerprint=baseline['source_inventory_fingerprint'],membership_fingerprint=baseline['membership_fingerprint'],
        baseline_report_fingerprint=baseline['content_fingerprint'], original_g1_records_unchanged=True,
        reused_structures=dict(G1='Literal claim/evidence coordinates, separate attribution/adoption, condition/exception, scope and expressed uncertainty; frozen subject interpretation retained by adapter.',
            G2='EvidenceNode roles, source-grounded DevelopmentRelation endpoints and existing reason_supports_claim/addresses_alternative meanings. A concession uses a qualification node and exact attachment, not an expanded qualifies_claim meaning.',
            G3='AddressAct invitation and addressee distinctions link the outer invitation to the offered response. No circumstance admission, production act classification or posture measurement.'),
        deliberately_added='Utterance occurrence (actual/projected/unresolved) is orthogonal to source voice and surface expression; no doctrine ontology or rhetorical-question classifier is added.',
        provider_requests=0,database_writes=0,automatic_binding=False,new_measurements=False,new_discovery=False,
        broader_collection=False,profile_projection=False,benchmark_comparison=False,new_scoring=False,quote_execution=False,
        semantic_validation='Authored source-reviewed proposals; structural checks are not independent semantic validation',human_acceptance='pending'))


def load(base_dir=None):
    authored = json.loads(READINGS_PATH.read_text())
    if authored['baseline_input_path'] != str(pilot.READINGS_PATH.relative_to(trace.ROOT)) or authored['baseline_input_sha256'] != trace.digest(pilot.READINGS_PATH):
        raise ValueError('Frozen ten-reading source input changed')
    for path,digest in authored['reused_contracts'].items():
        if trace.digest(trace.ROOT/path) != digest:
            raise ValueError('A reused G2/G3 source contract changed')
    return build(pilot.load(base_dir), authored)


def fields(binding):
    p=binding
    out=[('What is expressed',p['proposition']['reading'],[p['proposition']['span']]),
         ('Who voices it',p['voice']['speaker']+' · '+p['voice']['kind'].replace('_',' ')+' · '+p['voice']['occurrence']+'. '+p['voice']['rationale'],p['voice']['evidence']),
         ('Preacher’s use',p['adoption']['status'].replace('_',' ')+' · '+p['adoption']['rationale'],p['adoption']['evidence']),
         ('Polarity',p['polarity']['value']+'. '+p['polarity']['rationale'],p['polarity']['evidence']),
         ('Surface expression',p['expression']['value']+'. '+p['expression']['rationale'],p['expression']['evidence']),
         ('Conditions / exceptions','; '.join(c['kind']+': '+c['rationale'] for c in p['conditions']) or 'None bound to this proposition in this target. This does not establish unconditional doctrine.',[c['span'] for c in p['conditions']]),
         ('Scope',p['scope']['reading'],p['scope']['evidence']),
         ('Expressed uncertainty',p['epistemic_status']['value'].replace('_',' ')+'. '+p['epistemic_status']['rationale'],p['epistemic_status']['evidence'])]
    nodes={n['node_id']:n for n in p['evidence_nodes']}
    for qualification in p['qualifications']:
        out.append(('Qualification',qualification['reading'],[nodes[qualification['node_id']]['span']]))
    for relation in p['development_relations']:
        out.append(('Development link',relation['kind'].replace('_',' ')+': '+relation['rationale'],relation['evidence']))
    for act in p['address_acts']:
        out.append(('Address act',act['type']+' to '+act['addressee']['kind'].replace('_',' ')+'. '+act['rationale'],act['link_evidence']))
    return out


def markdown(report):
    lines=['# What these passages teach', '', 'Ten source-reviewed readings through reusable proposition binding and a separate assurance interpretation. Proposed readings; Brian’s acceptance pending.', '',
        'The generic reading preserves what is said even when it does not match an assurance predicate. All ten original G1 records are unchanged. No automatic binding or profile-wide positions are produced.', '']
    lines += ['- '+s for s in report['findings']]
    lines += ['', '## At a glance', '', '| Reading | Speaker / occurrence | Preacher’s use | Assurance mapping |', '|---|---|---|---|']
    for c in report['cases']:
        for r in c['readings']:
            p=r['binding'];lines.append('| ['+p['title']+'](index.html#'+p['binding_id']+') | '+p['voice']['speaker']+' / '+p['voice']['occurrence']+' | '+p['adoption']['status'].replace('_',' ')+' | '+r['assurance_interpretation']['mapping_status']+' |')
    for c in report['cases']:
        lines += ['', '## '+c['sermon_title'], '', '[Watch '+timestamp(c['start_seconds'])+'–'+timestamp(c['end_seconds'])+']('+c['watch_url']+')', '']
        for r in c['readings']:
            p=r['binding'];lines += ['### '+p['title'], '', p['proposition']['reading'], '', '| Field | Source-reviewed meaning | Exact evidence |', '|---|---|---|']
            for label,reading,spans in fields(p):
                evidence='<br>'.join('“'+s['text'].replace('\n',' ').replace('|','/')+'” ('+s['source_field']+', '+str(s['start'])+'–'+str(s['end'])+')' for s in spans)
                lines.append('| '+label+' | '+reading.replace('|','/')+' | '+evidence+' |')
            lines += ['', '**Unknown / withheld:**', '']+['- '+s for s in p['unknowns']]
            lines += ['', '**Separate assurance interpretation:** '+r['assurance_interpretation']['mapping_status']+'. Original G1 record unchanged; a narrow non-match does not erase the proposition.', '', '<details><summary>Generic binding and unchanged subject interpretation</summary>', '', '```json', json.dumps(r,ensure_ascii=False,indent=2), '```', '', '</details>', '']
        lines += ['<details><summary>Complete target and existing bounded context</summary>', '']
        for field,text in c['texts'].items():lines += ['**'+field.replace('_',' ')+'**', '', '> '+text.replace('\n','\n> '), '']
        lines += ['Context may resolve references; it cannot supply missing target assertions. Context truncation diagnostics remain in JSON.', '', '</details>', '']
    lines += ['## Reuse and limits', '']
    lines += [key+': '+value+'\n' for key,value in report['reused_structures'].items()]
    lines += [report['deliberately_added'], '']
    for limit in report['limitations']:lines += ['### '+limit['title'], '', limit['meaning'], '', 'Smallest next remedy: '+limit['remedy'], '']
    lines += ['## Run and review', '', '```bash', 'pte analysis profile-proposition-review --json', 'pte analysis profile-proposition-review --check-only --json', '```', '',
        'The second command verifies sources and literal coordinates without writing. No providers, new measurements, collection, automatic discovery, pastor-wide projection, comparison/scoring or Ollama quotation execution.', '']
    return '\n'.join(lines)


def render(report):
    from pastor_transcript_extractor.profile_presentation import STYLE
    e=lambda s:html.escape(str(s),quote=True)
    def evidence(spans,case_id):
        return ''.join('<blockquote>'+e(s['text'])+'<div class="muted"><a href="#'+e(case_id+'-'+s['source_field'])+'">'+e(s['source_field'].replace('_',' '))+'</a> · characters '+str(s['start'])+'–'+str(s['end'])+'</div></blockquote>' for s in spans)
    glance=[];sections=[]
    for c in report['cases']:
        articles=[]
        for r in c['readings']:
            p=r['binding'];assurance=r['assurance_interpretation']
            glance.append('<tr><th><a href="#'+e(p['binding_id'])+'">'+e(p['title'])+'</a></th><td>'+e(p['voice']['speaker'])+' · '+e(p['voice']['occurrence'])+'</td><td>'+e(p['adoption']['status'].replace('_',' '))+'</td><td>'+e(assurance['mapping_status'].replace('_',' '))+'</td></tr>')
            table=''.join('<tr><th>'+e(label)+'</th><td>'+e(reading)+'</td><td>'+evidence(spans,c['case_id'])+'</td></tr>' for label,reading,spans in fields(p))
            articles.append('<article id="'+e(p['binding_id'])+'"><h3>'+e(p['title'])+'</h3><p class="note">'+e(p['proposition']['reading'])+'</p><p>'+e(p['voice']['speaker'])+' · '+e(p['voice']['occurrence'])+' speech · '+e(p['adoption']['status'].replace('_',' '))+'</p><details><summary>Inspect the reading and its exact supporting evidence</summary><div class="tablewrap"><table><thead><tr><th>Field</th><th>Source-reviewed meaning</th><th>Exact evidence</th></tr></thead><tbody>'+table+'</tbody></table></div></details><p><strong>Unknown or withheld</strong></p><ul>'+''.join('<li>'+e(s)+'</li>' for s in p['unknowns'])+'</ul><details class="technical"><summary>Separate assurance interpretation · '+e(assurance['mapping_status'].replace('_',' '))+' · original G1 unchanged</summary><p>A narrow non-match or unresolved predicate does not mean no theology, denial or no assertion. Generic adoption concerns the exact locally used proposition; the narrower interpretation retains its separately reviewed target and meanings.</p><pre>'+e(json.dumps(assurance,ensure_ascii=False,indent=2))+'</pre></details><details class="technical"><summary>Generic record, provenance and reviewed subject mapping</summary><pre>'+e(json.dumps(r,ensure_ascii=False,indent=2))+'</pre></details></article>')
        source=''.join('<details id="'+e(c['case_id']+'-'+field)+'"><summary>'+e(field.replace('_',' ').capitalize())+'</summary><div class="source">'+e(text)+'</div><p>Back to readings: '+', '.join('<a href="#'+e(r['binding']['binding_id'])+'">'+e(r['binding']['title'])+'</a>' for r in c['readings'])+'</p></details>' for field,text in c['texts'].items())
        sections.append('<section class="panel" id="'+e(c['case_id'])+'"><h2>'+e(c['sermon_title'])+'</h2><p><a href="'+e(c['watch_url'])+'" target="_blank" rel="noopener noreferrer">Watch '+e(timestamp(c['start_seconds'])+'–'+timestamp(c['end_seconds']))+'</a></p>'+''.join(articles)+'<h3>Complete supplied passage and context</h3>'+source+'<p class="muted">Only target evidence supplies assertions and semantic links. Context resolves references; original truncation remains disclosed.</p><details class="technical"><summary>Source identity and context diagnostics</summary><pre>'+e(json.dumps({k:v for k,v in c.items() if k not in ('readings','texts')},ensure_ascii=False,indent=2))+'</pre></details></section>')
    limits=''.join('<article id="limit-'+e(v['id'])+'"><h3>'+e(v['title'])+'</h3><p>'+e(v['meaning'])+'</p><p><strong>Smallest next remedy:</strong> '+e(v['remedy'])+'</p></article>' for v in report['limitations'])
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>What these passages teach · Proposition review</title><style>'+STYLE+'blockquote{margin:10px 0;padding:8px 12px;border-left:2px solid var(--line);font-family:Georgia,serif}article{border-top:1px solid var(--line);margin-top:24px;padding-top:12px}td{min-width:180px}</style></head><body><main><span class="eyebrow">PASTOR TRANSCRIPT EXTRACTOR · SOURCE-REVIEWED PROPOSITIONS</span><h1>What these passages teach</h1><p class="assessment">Ten readings. Three supplied passages. Theology preserved independently of an assurance predicate match.</p><p class="note">Proposed source-reviewed interpretations for Brian’s review. All ten original G1 records are unchanged. These are local readings, not automatic results or pastor-wide positions.</p><ul>'+''.join('<li>'+e(s)+'</li>' for s in report['findings'])+'</ul><p><a href="readings-v1.md">Readable Markdown</a> · <a href="readings-v1.json">Complete bindings and provenance</a></p><section class="panel"><h2>At a glance</h2><div class="tablewrap"><table><thead><tr><th>Reading</th><th>Speaker / occurrence</th><th>Preacher’s use</th><th>Assurance mapping</th></tr></thead><tbody>'+''.join(glance)+'</tbody></table></div></section><nav>'+''.join('<a href="#'+e(c['case_id'])+'">'+e(c['sermon_title'])+'</a> ' for c in report['cases'])+'<a href="#limits">Reuse and limits</a></nav>'+''.join(sections)+'<section class="panel" id="limits"><h2>What changed, what remains unresolved</h2>'+''.join('<p><strong>'+e(k)+':</strong> '+e(v)+'</p>' for k,v in report['reused_structures'].items())+'<p>'+e(report['deliberately_added'])+'</p>'+limits+'</section><footer>No provider/model calls, new measurements, broader collection, automatic discovery, profile projection, comparison/scoring or Ollama quotation execution. Exact excerpts are evidence citations for source review.</footer></main><script>function reveal(){let id;try{id=decodeURIComponent(location.hash.slice(1));}catch{return;}let el=document.getElementById(id);if(!el)return;let p=el;while(p){if(p.tagName==="DETAILS")p.open=true;p=p.parentElement;}el.scrollIntoView();}window.addEventListener("hashchange",reveal);window.addEventListener("load",reveal);</script></body></html>')


def prepare(base_dir=None):
    report=load(base_dir)
    from pastor_transcript_extractor import assurance_binding_adapter, binding_evidence, profile_presentation
    authored=json.loads(READINGS_PATH.read_text())
    original=json.loads(pilot.READINGS_PATH.read_text())
    paths=[Path(__file__),READINGS_PATH,pilot.READINGS_PATH,Path(generic.__file__),Path(assurance_binding_adapter.__file__),Path(binding_evidence.__file__),Path(pilot.__file__),Path(profile_presentation.__file__)]
    paths += [trace.ROOT/original[k+'_path'] for k in ('contract','composer')]
    paths += [trace.ROOT/path for path in authored['reused_contracts']]
    manifest=seal(dict(version=VERSION,report=report,implementation_files={str(p):trace.digest(p) for p in paths},provider_requests=0,database_writes=0))
    out=build_paths(base_dir).evaluation/VERSION/manifest['content_fingerprint']
    out.mkdir(parents=True,exist_ok=True)
    for name,text in {'index.html':render(report),'readings-v1.md':markdown(report),'readings-v1.json':json.dumps(manifest,ensure_ascii=False,indent=2)+'\n'}.items():
        path=out/name
        if path.exists() and path.read_text()!=text:raise ValueError('Immutable proposition review differs')
        path.write_text(text)
    return report,out/'index.html'
