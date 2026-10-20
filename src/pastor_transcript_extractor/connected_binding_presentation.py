"""Human review of connected extraction, including literal/structural rejections."""
import html
import json

from pastor_transcript_extractor import profile_proposition_review as reference
from pastor_transcript_extractor.profile_presentation import STYLE


def markdown(output):
    r=output['generated'];comp=output['comparison']
    lines=['# Connected passage binding review','',output['status'],'','Same three supplied passages; reviewed answers excluded from generation. No accepted observation or profile projection.','',f"Generated records: {output['generated_candidates']}; structurally valid: {output['structurally_valid_candidates']}; passage rejections: {len(output['passage_rejections'])}.",'','Recorded initial execution: '+json.dumps(output['invocation'])+'. Token receipt: '+json.dumps(r['usage'])+'.', '','Model: '+r['panel']['backend']['model']+'; installed digest: '+r['backend_pin']['model_digest']+'.','']
    if comp:
        lines+=['## Decision','',comp['decision']['answer'].upper()+': '+comp['decision'].get('finding',''),'',comp['decision']['recommendation'],'']
        for row in comp['readings']:
            lines+=['## '+row['reference_id'],'',row['summary'],'','Correctly unresolved: '+row['correctly_unresolved'],'','| Field | Outcome | Comparison |','|---|---|---|']
            for name,f in row['fields'].items():lines+=['| '+name+' | '+f['outcome']+' | '+f['finding'].replace('|','/')+' |']
    else:lines+=['Semantic comparison is pending Codex inspection. Literal/structural validity is not a quality verdict.','']
    for c in r['cases']:
        lines+=['## '+c['sermon_title'],'','[Watch source]('+c['watch_url']+') · [Original request and raw response](../../cache/'+c['request_fingerprint']+'.json)','']
        if c['compile_error']:lines+=['Passage rejected: '+c['compile_error'],'']
        for g in c['generated']:
            key=c['case_id']+'-auto-'+g['candidate_id'];lines+=['### '+key,'']
            if g['binding']:
                for label,text,spans in reference.fields(g['binding']):
                    lines+=['**'+label+':** '+text]+['> '+s['text'].replace('\n','\n> ')+' ('+s['source_field']+' '+str(s['start'])+'–'+str(s['end'])+')' for s in spans]+['']
            else:lines+=['Rejected: '+g['compile_error'],'']
            lines+=['<details><summary>Raw proposed record and compilation</summary>','','```json',json.dumps(g,ensure_ascii=False,indent=2),'```','','</details>','']
        lines+=['### Speech frames and source','', '```json',json.dumps(c['frames'],ensure_ascii=False,indent=2),'```','']
        for field,text in c['texts'].items():lines+=['#### '+field,'','> '+text.replace('\n','\n> '),'']
    lines+=['## Review commands','','```bash','pte analysis profile-connected-binding --json','pte analysis profile-connected-binding --check-only --json','```','','No new provider call is needed for review. No collection, production activation, assurance change, measurement, ranking, stability claim or quotation execution.','']
    return '\n'.join(lines)


def render(output):
    e=lambda x:html.escape(str(x),quote=True)
    r=output['generated'];comp=output['comparison'];parts=[]
    def evidence(spans,cid):
        return ''.join('<blockquote>'+e(s['text'])+'<div><a href="#'+e(cid+'-'+s['source_field'])+'">'+e(s['source_field'])+' '+str(s['start'])+'–'+str(s['end'])+'</a></div></blockquote>' for s in spans)
    refs={x['binding']['binding_id']:(c,x) for c in output['reference']['cases'] for x in c['readings']}
    if comp:
        parts+=['<section class="panel"><h2>Review decision</h2><p>'+e(comp['decision']['answer'].upper()+': '+comp['decision'].get('finding',''))+'</p><p>'+e(comp['decision']['recommendation'])+'</p></section>']
        glance=''.join('<tr><th><a href="#review-'+e(row['reference_id'])+'">'+e(refs[row['reference_id']][1]['binding']['title'])+'</a></th><td>'+e(row['content_recovery'])+'</td><td>'+e(row['summary'])+'</td></tr>' for row in comp['readings'])
        parts+=['<section class="panel"><h2>At a glance</h2><p>Located content is distinct from faithful binding across all reviewed fields.</p><table>'+glance+'</table></section>']
        for row in comp['readings']:
            c,ref=refs[row['reference_id']]
            fields=''.join('<tr><th>'+e(name.replace('_',' '))+'</th><td>'+e(f['outcome'].replace('_',' '))+'</td><td>'+e(f['finding'])+evidence(f['evidence'],c['case_id'])+'</td></tr>' for name,f in row['fields'].items())
            parts+=['<section class="panel" id="review-'+e(row['reference_id'])+'"><h2>'+e(ref['binding']['title'])+'</h2><p>'+e(row['summary'])+'</p>'+evidence([ref['binding']['proposition']['span']],c['case_id'])+'<p>Generated: '+(' · '.join('<a href="#'+e(key)+'">'+e(key)+'</a>' for key in row['generated_ids']) or 'None matched')+'</p><details><summary>All twelve field comparisons and exact evidence</summary><table>'+fields+'</table></details><p>Correctly unresolved: '+e(row['correctly_unresolved'])+'</p></section>']
    else:parts+=['<section class="panel"><h2>Awaiting semantic comparison</h2><p>Codex must inspect the actual output against the unchanged ten readings and source. Literal/structural validity is not a quality verdict.</p></section>']
    for c in r['cases']:
        cid=c['case_id'];section=['<section class="panel"><h2>'+e(c['sermon_title'])+'</h2><p><a href="'+e(c['watch_url'])+'">Watch passage</a> · <a href="../../cache/'+e(c['request_fingerprint'])+'.json">Original request and raw response</a></p>']
        if c['compile_error']:section+=['<p class="note">Passage rejected: '+e(c['compile_error'])+'</p>']
        for g in c['generated']:
            key=cid+'-auto-'+g['candidate_id'];section+=['<article id="'+e(key)+'"><h3>'+e(key)+'</h3>']
            if g['binding']:
                b=g['binding'];section+=['<p>'+e(b['proposition']['reading'])+'</p>'+evidence([b['proposition']['span']],cid)]
                fields=''.join('<tr><th>'+e(label)+'</th><td>'+e(text)+evidence(spans,cid)+'</td></tr>' for label,text,spans in reference.fields(b))
                section+=['<details><summary>Bound fields, unknowns and exact evidence</summary><table>'+fields+'</table></details>']
            else:section+=['<p class="note">Record rejected: '+e(g['compile_error'])+'</p>']
            if comp:
                extra=comp['extra_generated'].get(key)
                if extra:section+=['<p>'+e(extra['outcome']+': '+extra['finding'])+'</p>']
                section+=['<p>'+' · '.join('<a href="#review-'+e(row['reference_id'])+'">'+e(row['reference_id'])+' comparison</a>' for row in comp['readings'] if key in row['generated_ids'])+'</p>']
            section+=['<details class="technical"><summary>Original proposed record and compilation</summary><pre>'+e(json.dumps(g,ensure_ascii=False,indent=2))+'</pre></details></article>']
        section+=['<details><summary>Connected speech frames and passage unknowns</summary><pre>'+e(json.dumps(dict(frames=c['frames'],unknowns=c['passage_unknowns']),ensure_ascii=False,indent=2))+'</pre></details>']
        for field,text in c['texts'].items():section+=['<details id="'+e(cid+'-'+field)+'"><summary>'+e(field.replace('_',' '))+'</summary><div class="source">'+e(text)+'</div><p>'+(' · '.join('<a href="#review-'+e(row['reference_id'])+'">'+e(row['reference_id'])+'</a>' for row in comp['readings'] if refs[row['reference_id']][0]['case_id']==cid) if comp else '')+'</p></details>']
        parts+=section+['</section>']
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Connected passage binding review</title><style>'+STYLE+'blockquote{border-left:2px solid var(--line);padding:8px 12px}article{border-top:1px solid var(--line);margin-top:20px}table{display:block;overflow-x:auto}</style></head><body><main><span class="eyebrow">BOUNDED DEVELOPMENT · THREE SUPPLIED PASSAGES</span><h1>Connected passage binding</h1><p>'+e(output['status'])+'</p><p>'+e(str(output['generated_candidates']))+' proposed records · '+e(str(output['structurally_valid_candidates']))+' structurally valid · '+e(str(len(output['passage_rejections'])))+' passage rejections.</p><p>Model: '+e(r['panel']['backend']['model'])+' · initial generation requests: '+e(output['invocation']['provider_requests'])+' · initial cache hits: '+e(output['invocation']['cache_hits'])+' · tokens: '+e(json.dumps(r['usage']))+'. No reference answers entered generation; no record is accepted or projected.</p><p><a href="review-v1.md">Readable Markdown</a> · <a href="review-v1.json">Complete JSON</a></p>'+''.join(parts)+'<footer>No broader collection, measurement admission, assurance change, production activation, profile projection, ranking or quotation execution.</footer></main><script>function reveal(){let el=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(!el)return;for(let p=el;p;p=p.parentElement)if(p.tagName==="DETAILS")p.open=true;el.scrollIntoView();}addEventListener("hashchange",reveal);addEventListener("load",reveal);</script></body></html>'
