"""Readable development discrepancies; no model requests or binding decisions."""
import html
import json
from pastor_transcript_extractor import profile_proposition_review as reference


def markdown(output):
    generated=output['generated'];comparison=output['comparison'];lines=['# Automatic proposition binding: development review','',output['status'],'',
        'Three supplied passages; ten reviewed development references. References were excluded from generation. No generated record is an accepted observation or profile position.','',
        f"Generated candidates: {output['generated_candidates']}; structurally valid: {output['structurally_valid_candidates']}.",
        f"Provider requests this invocation: {output['invocation']['provider_requests']}; cache hits: {output['invocation']['cache_hits']}; unique requests represented: {generated['unique_request_count']}.",
        'Token usage: '+json.dumps(generated['usage'])+'. '+generated['cost'],'']
    if comparison:
        lines+=['## Decision','',comparison['decision']['answer'].upper()+': '+comparison['decision']['finding'],'',comparison['decision']['recommendation'],'',
            '## Field outcomes across these ten readings','', '| Field | Dispositions (10 readings per field) |','|---|---|']
        for field,counts in output['field_outcomes'].items():lines+=['| '+field.replace('_',' ')+' | '+', '.join(k.replace('_',' ')+': '+str(v) for k,v in counts.items())+' |']
        lines+=['','Content recovery: '+json.dumps(output['development_summary'])+'. Fully faithful means all reviewed field groups are satisfied; literal validity alone does not qualify.','']
        for row in comparison['readings']:
            case_id=next(c['case_id'] for c in output['reference']['cases'] if any(r['binding']['binding_id']==row['reference_id'] for r in c['readings']))
            lines+=['','## '+row['reference_id'],'',row['summary'],'','Generated candidates: '+', '.join('['+key+'](index.html#'+key+')' for key in row['generated_ids']),'','| Field | Outcome | Semantic comparison | Exact source evidence |','|---|---|---|---|']
            for field,finding in row['fields'].items():
                citations='<br>'.join('['+s['source_field']+' '+str(s['start'])+'–'+str(s['end'])+'](index.html#'+case_id+'-'+s['source_field']+'): “'+s['text'].replace('\n',' ').replace('|','/')+'”' for s in finding['evidence'])
                lines+=['| '+field.replace('_',' ')+' | '+finding['outcome'].replace('_',' ')+' | '+finding['finding'].replace('|','/')+' | '+citations+' |']
            lines+=['','Correctly unresolved: '+row['correctly_unresolved'],'']
    for c in generated['cases']:
        lines+=['','## Generated: '+c['sermon_title'],'','[Watch source]('+c['watch_url']+')','']
        for g in c['generated']:
            key=c['case_id']+'-auto-'+g['candidate_id'];lines+=['### '+key,'','> '+g['source_span']['text'],'','<details><summary>Complete generated fields, raw selected choices and diagnostics</summary>','','```json',json.dumps(g,ensure_ascii=False,indent=2),'```','','</details>','']
    lines+=['## Reproduce','','```bash','pte analysis profile-binding-development --json','pte analysis profile-binding-development --check-only --json','```','','Use --run only to execute/resume the bounded run; compatible requests reuse caches. No broader sample, collection, production activation, automatic acceptance, assurance changes, profile projection or comparison/scoring.','']
    return '\n'.join(lines)


def render(output):
    from pastor_transcript_extractor.profile_presentation import STYLE
    e=lambda v:html.escape(str(v),quote=True)
    generated=output['generated'];comparison=output['comparison'];cases={c['case_id']:c for c in generated['cases']}
    refs={r['binding']['binding_id']:(c,r) for c in output['reference']['cases'] for r in c['readings']}
    def evidence(spans,case_id):
        return ''.join('<blockquote>'+e(s['text'])+'<div class="muted"><a href="#'+e(case_id+'-'+s['source_field'])+'">'+e(s['source_field'])+'</a> · '+str(s['start'])+'–'+str(s['end'])+'</div></blockquote>' for s in spans)
    parts=[]
    if comparison:
        decision=comparison['decision'];parts.append('<section class="panel"><h2>Does this justify separate broader validation?</h2><p class="assessment">'+e(decision['answer'].upper())+' · '+e(decision['finding'])+'</p><p>'+e(decision['recommendation'])+'</p></section>')
        glance=''.join('<tr><th><a href="#review-'+e(row['reference_id'])+'">'+e(refs[row['reference_id']][1]['binding']['title'])+'</a></th><td>'+e(row['content_recovery'])+'</td><td>'+e(row['summary'])+'</td></tr>' for row in comparison['readings'])
        parts.append('<section class="panel"><h2>At a glance</h2><p>'+e(json.dumps(output['development_summary']))+'. “Located” means related proposition content was generated, not that all binding fields were faithful.</p><div class="tablewrap"><table><thead><tr><th>Reviewed reading</th><th>Content recovery</th><th>Material finding</th></tr></thead><tbody>'+glance+'</tbody></table></div></section>')
        parts.append('<section class="panel"><h2>Across these ten development readings</h2><div class="tablewrap"><table><thead><tr><th>Field</th><th>Outcomes · ten readings per field</th></tr></thead><tbody>'+''.join('<tr><th>'+e(k.replace('_',' '))+'</th><td>'+e(', '.join(n.replace('_',' ')+': '+str(v) for n,v in counts.items()))+'</td></tr>' for k,counts in output['field_outcomes'].items())+'</tbody></table></div><p>These counts describe this development run. They are not general accuracy, precision, recall or production readiness.</p></section>')
        for row in comparison['readings']:
            c,ref=refs[row['reference_id']];b=ref['binding']
            table=''.join('<tr><th>'+e(field.replace('_',' '))+'</th><td>'+e(f['outcome'].replace('_',' '))+'</td><td>'+e(f['finding'])+evidence(f['evidence'],c['case_id'])+'</td></tr>' for field,f in row['fields'].items())
            parts.append('<section class="panel" id="review-'+e(row['reference_id'])+'"><h2>'+e(b['title'])+'</h2><p class="note">'+e(row['summary'])+'</p><p><strong>Reviewed reference:</strong> '+e(b['proposition']['reading'])+'</p>'+evidence([b['proposition']['span']],c['case_id'])+'<p><strong>Automation generated:</strong> '+(', '.join('<a href="#'+e(key)+'">'+e(key)+'</a>' for key in row['generated_ids']) or 'No matched generated candidate')+'</p><details><summary>Inspect all twelve fields and exact discrepancy evidence</summary><div class="tablewrap"><table><thead><tr><th>Field</th><th>Outcome</th><th>Semantic finding and exact source</th></tr></thead><tbody>'+table+'</tbody></table></div></details><p><strong>Correctly left unresolved:</strong> '+e(row['correctly_unresolved'])+'</p><details><summary>Unchanged reviewed record and assurance interpretation</summary><pre>'+e(json.dumps(ref,ensure_ascii=False,indent=2))+'</pre></details></section>')
    else:parts.append('<p class="note">Generation complete; the post-output semantic comparison has not yet been authored. No performance conclusion is available.</p>')
    for c in generated['cases']:
        items=[]
        for g in c['generated']:
            key=c['case_id']+'-auto-'+g['candidate_id'];binding=g['binding'];summary=[]
            if binding:
                for label,text,spans in reference.fields(binding):summary.append('<tr><th>'+e(label)+'</th><td>'+e(text)+'</td><td>'+evidence(spans,c['case_id'])+'</td></tr>')
            extra=comparison['extra_generated'].get(key) if comparison else None
            back=' '.join('<a href="#review-'+e(r['reference_id'])+'">'+e(r['reference_id'])+' comparison</a>' for r in comparison['readings'] if key in r['generated_ids']) if comparison else ''
            items.append('<article id="'+e(key)+'"><h3>'+e(key)+'</h3>'+evidence([g['source_span']],c['case_id'])+'<p>'+back+'</p>'+('<p class="note">Extra candidate · '+e(extra['outcome'].replace('_',' '))+': '+e(extra['finding'])+'</p>' if extra else '')+('<p class="note">Structural rejection: '+e(g['compile_error'])+'</p>' if not binding else '<details><summary>Generated fields and exact evidence</summary><div class="tablewrap"><table><thead><tr><th>Field</th><th>Generated interpretation</th><th>Exact evidence</th></tr></thead><tbody>'+''.join(summary)+'</tbody></table></div></details>')+'<details class="technical"><summary>Raw selected choices, abstentions and generic record</summary><pre>'+e(json.dumps(g,ensure_ascii=False,indent=2))+'</pre></details></article>')
        targets=''.join('<details id="'+e(c['case_id']+'-'+field)+'"><summary>'+e(field.replace('_',' '))+'</summary><div class="source">'+e(text)+'</div><p>'+(' · '.join('<a href="#review-'+e(r['reference_id'])+'">'+e(r['reference_id'])+'</a>' for r in comparison['readings'] if refs[r['reference_id']][0]['case_id']==c['case_id']) if comparison else '')+'</p></details>' for field,text in c['texts'].items())
        parts.append('<section class="panel"><h2>Generated · '+e(c['sermon_title'])+'</h2><p><a href="'+e(c['watch_url'])+'">Watch passage</a></p>'+''.join(items)+'<h3>Full target and existing bounded context</h3>'+targets+'<details class="technical"><summary>Source candidates, discovery choices and context diagnostics</summary><pre>'+e(json.dumps({k:v for k,v in c.items() if k not in ('generated','texts')},ensure_ascii=False,indent=2))+'</pre></details></section>')
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Automatic proposition binding · Development review</title><style>'+STYLE+'td{min-width:160px}blockquote{border-left:2px solid var(--line);padding:8px 12px;margin:12px 0}article{border-top:1px solid var(--line);margin-top:20px}</style></head><body><main><span class="eyebrow">BOUNDED DEVELOPMENT RUN · THREE SUPPLIED PASSAGES</span><h1>Can PTE bind these propositions automatically?</h1><p>Ten reviewed development references. No reference answers were supplied to generation; no generated candidate is accepted or projected into the pastor profile.</p><p>'+e(str(output['generated_candidates']))+' generated candidates · '+e(str(output['structurally_valid_candidates']))+' structurally valid. '+e(str(generated['unique_request_count']))+' unique requests represented; this invocation: '+e(json.dumps(output['invocation']))+'. Tokens: '+e(json.dumps(generated['usage']))+'. '+e(generated['cost'])+'</p><p><a href="review-v1.md">Readable Markdown</a> · <a href="review-v1.json">Complete results and comparison</a></p>'+''.join(parts)+'<footer>Development comparison only. References and existing assurance interpretation unchanged. No broader collection, production activation, automatic acceptance, profile projection, ranking/scoring or quote execution.</footer></main><script>function reveal(){let el=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(!el)return;for(let p=el;p;p=p.parentElement)if(p.tagName==="DETAILS")p.open=true;el.scrollIntoView();}addEventListener("hashchange",reveal);addEventListener("load",reveal);</script></body></html>'
