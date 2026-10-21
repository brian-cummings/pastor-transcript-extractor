"""Exhaustive cache-only diagnostics; never repairs or recompiles model answers.

The original compiler/runner remain pinned. Available literal occurrences are
reported for diagnosis only; they never replace a model's invalid occurrence index.
"""
from collections import Counter
import html
import json
import re

from pastor_transcript_extractor import connected_binding_development as dev
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.profile_presentation import STYLE

VERSION='connected-binding-rejection-diagnostics-v1'


def inspect_payload(payload,texts):
    try:model=dev.contract.Extraction.model_validate(payload)
    except ValueError as error:return dict(schema_error=str(error),raw_frames=0,raw_propositions=0,quotes=[],frames=[],propositions=[])
    raw=model.model_dump();quotes=[]
    def walk(obj,path=''):
        if isinstance(obj,dict):
            if set(obj)=={'source_field','text','occurrence_index'}:
                matches=[m.start() for m in re.finditer('(?='+re.escape(obj['text'])+')',texts[obj['source_field']])]
                try:located=dev.contract.locate(obj,texts);error=None
                except ValueError:located=None;error='text_not_present' if not matches else 'occurrence_index_out_of_range'
                quotes.append(dict(path=path,quote=obj,exact_text_occurrences=len(matches),available_starts=matches,validated_span=located,error=error))
            else:
                for k,v in obj.items():walk(v,path+'.'+k if path else k)
        elif isinstance(obj,list):
            for i,v in enumerate(obj):walk(v,path+'['+str(i)+']')
    walk(raw)
    bypath={q['path']:q for q in quotes};byid={f['frame_id']:f for f in raw['frames']};frames=[]
    for i,f in enumerate(raw['frames']):
        errors=[];q=bypath[f'frames[{i}].span']
        if q['error']:errors.append('invalid_literal_span')
        if f['voice']!='unresolved' and not f['evidence']:errors.append('missing_attribution_evidence')
        if f['voice']!='unresolved' and (not f['speaker'] or f['speaker'].strip().lower() in {'unknown','unresolved'}):errors.append('speaker_unresolved_placeholder')
        if f['span']['source_field']!='target_text':errors.append('context_supplied_frame')
        if f['occurrence']=='projected' and f['parent_frame_id'] is None:errors.append('projected_without_outer_frame')
        if f['voice']=='preacher' and f['occurrence']=='projected':errors.append('projected_preacher_voice')
        if f['parent_frame_id'] is not None:
            parent=byid.get(f['parent_frame_id'])
            if parent is None:errors.append('missing_parent_frame')
            else:
                # Check whether ANY literal occurrences can fit, without selecting
                # or substituting an occurrence. This detects impossible parentage
                # even when the requested index is invalid.
                parent_starts=[m.start() for m in re.finditer('(?='+re.escape(parent['span']['text'])+')',texts[parent['span']['source_field']])]
                if q['available_starts'] and parent_starts and (f['span']['source_field']!=parent['span']['source_field'] or not any(p<=s and s+len(f['span']['text'])<=p+len(parent['span']['text']) for s in q['available_starts'] for p in parent_starts)):
                    errors.append('no_literal_child_occurrence_fits_parent')
        seen={f['frame_id']};parent=f['parent_frame_id']
        while parent in byid:
            if parent in seen:errors.append('cyclic_parent_frame');break
            seen.add(parent);parent=byid[parent]['parent_frame_id']
        frames.append(dict(frame_id=f['frame_id'],parent_frame_id=f['parent_frame_id'],span=q,errors=errors,raw_frame=f))
    if len(byid)!=len(raw['frames']):
        for f in frames:f['errors'].append('duplicate_frame_identity')
    frame_errors={f['frame_id']:f['errors'] for f in frames}
    propositions=[]
    for i,p in enumerate(raw['propositions']):
        errors=[];q=bypath[f'propositions[{i}].span']
        if q['error']:errors.append('invalid_literal_span')
        if p['span']['source_field']!='target_text':errors.append('context_supplied_proposition')
        if p['frame_id'] not in byid:errors.append('missing_speech_frame')
        elif frame_errors[p['frame_id']]:errors.append('invalid_speech_frame_dependency')
        for name in ('adoption','polarity','expression','epistemic_status'):
            value=p[name].get('status',p[name].get('value'))
            if value not in {'undetermined','unresolved'} and not p[name]['evidence']:errors.append('missing_'+name+'_evidence')
        if p['adoption']['status']=='adopted' and p['adoption']['basis'] not in {'explicit_endorsement','discourse_use'}:errors.append('adopted_with_incompatible_basis')
        if not any(s.strip() for s in p['unknowns']):errors.append('blank_unknowns')
        propositions.append(dict(local_id=p['local_id'],span=q,errors=errors,raw_proposition=p))
    return dict(schema_error=None,raw_frames=len(frames),raw_propositions=len(propositions),quotes=quotes,frames=frames,propositions=propositions)


def build(base_dir=None):
    result,folder,_=dev.cached(base_dir);cases=[]
    for c in result['cases']:
        record=dev.review.read(dev.directory(base_dir)/'cache'/f"{c['request_fingerprint']}.json")
        try:payload=json.loads(json.loads(record['raw_envelope'])['message']['content']);diagnostics=inspect_payload(payload,c['texts'])
        except (ValueError,KeyError,TypeError) as error:diagnostics=dict(schema_error=str(error),raw_frames=0,raw_propositions=0,quotes=[],frames=[],propositions=[])
        cases.append(dict(case_id=c['case_id'],sermon_title=c['sermon_title'],texts=c['texts'],request_fingerprint=c['request_fingerprint'],original_passage_rejection=c['compile_error'],**diagnostics))
    summary=dict(raw_frames=sum(c['raw_frames'] for c in cases),raw_propositions=sum(c['raw_propositions'] for c in cases),compiled_bindings=sum(bool(g['binding']) for c in result['cases'] for g in c['generated']),literal_errors=dict(Counter(q['error'] for c in cases for q in c['quotes'] if q['error'])),frame_errors=dict(Counter(error for c in cases for f in c['frames'] for error in f['errors'])),proposition_errors=dict(Counter(error for c in cases for p in c['propositions'] for error in p['errors'])))
    return seal(dict(version=VERSION,generated_fingerprint=result['content_fingerprint'],summary=summary,cases=cases,provider_requests=0,metadata_reads=0,raw_responses_changed=False,compiled_records_changed=False,semantic_policy_changed=False,limit='Diagnostic findings overlap; counts are not independent errors, model accuracy, or repaired bindings. Text presence is distinct from a valid requested occurrence. Placeholder speakers/blank unknowns are diagnostic findings, not new admission rules.')),folder


def markdown(report):
    lines=['# Connected extraction: complete rejection diagnostics','','No new generation or metadata calls. Original responses, compiler and generated records are unchanged.','','Summary: '+json.dumps(report['summary'])+'.','',report['limit'],'']
    for c in report['cases']:
        lines+=['## '+c['case_id']+' · '+c['sermon_title'],'','Original passage rejection: '+str(c['original_passage_rejection']),'','[Original request and raw response](../../cache/'+c['request_fingerprint']+'.json)','',f"Raw output: {c['raw_frames']} frames; {c['raw_propositions']} proposition records.",'']
        for group,idfield in (('frames','frame_id'),('propositions','local_id')):
            lines+=['### '+group,'','| Record | Requested index | Exact occurrences | Literal lookup | Other diagnostics |','|---|---|---|---|---|']
            for row in c[group]:
                q=row['span'];lines+=['| '+row[idfield]+' | '+str(q['quote']['occurrence_index'])+' | '+str(q['exact_text_occurrences'])+' | '+(q['error'] or 'valid')+' | '+', '.join(row['errors'])+' |']
            for row in c[group]:
                lines+=['','#### '+row[idfield],'','Model-proposed text (unverified where lookup fails):','','> '+row['span']['quote']['text'].replace('\n','\n> '),'','```json',json.dumps(row,ensure_ascii=False,indent=2),'```','']
        for field,text in c['texts'].items():lines+=['### Supplied '+field,'','> '+text.replace('\n','\n> '),'']
    return '\n'.join(lines)


def render(report):
    e=lambda s:html.escape(str(s),quote=True);parts=[]
    for c in report['cases']:
        parts+=['<section class="panel"><h2>'+e(c['case_id']+' · '+c['sermon_title'])+'</h2><p>'+e(c['original_passage_rejection'])+'</p><p>'+e(str(c['raw_frames']))+' raw frames · '+e(str(c['raw_propositions']))+' raw propositions · <a href="../../cache/'+e(c['request_fingerprint'])+'.json">Original raw response</a></p>']
        for group,idfield in (('frames','frame_id'),('propositions','local_id')):
            parts+=['<h3>'+e(group)+'</h3>']
            for row in c[group]:
                q=row['span'];parts+=['<article><h4>'+e(row[idfield])+'</h4><p><strong>Model-proposed text; not an accepted source quote:</strong></p><blockquote>'+e(q['quote']['text'])+'</blockquote><p>Requested occurrence '+str(q['quote']['occurrence_index'])+' · literal occurrences '+str(q['exact_text_occurrences'])+' · '+e(q['error'] or 'exact lookup valid')+'</p><p>'+e(', '.join(row['errors']))+'</p><details><summary>Complete raw record and diagnostic detail</summary><pre>'+e(json.dumps(row,ensure_ascii=False,indent=2))+'</pre></details></article>']
        for field,text in c['texts'].items():parts+=['<details><summary>Supplied '+e(field)+'</summary><div class="source">'+e(text)+'</div></details>']
        parts+=['</section>']
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Connected extraction rejection diagnostics</title><style>'+STYLE+'article{border-top:1px solid var(--line);padding:12px 0}blockquote{white-space:pre-wrap}</style></head><body><main><h1>What caused the connected extraction rejection?</h1><p>All independent failures are shown without repairing or admitting any answer. No new model or metadata calls.</p><p>'+e(report['limit'])+'</p><pre>'+e(json.dumps(report['summary'],indent=2))+'</pre><p><a href="index.html">Semantic review</a> · <a href="diagnostics-v1.md">Markdown</a> · <a href="diagnostics-v1.json">JSON</a></p>'+''.join(parts)+'</main></body></html>'


def prepare(base_dir=None):
    report,folder=build(base_dir)
    dev.review.save(folder/'diagnostics-v1.json',report)
    (folder/'diagnostics-v1.md').write_text(markdown(report))
    (folder/'diagnostics-v1.html').write_text(render(report))
    return report,folder/'diagnostics-v1.html'
