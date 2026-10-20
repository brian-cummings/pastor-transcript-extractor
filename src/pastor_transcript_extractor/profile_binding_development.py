"""Bounded three-passage automatic binding run and post-output semantic review.

References never enter provider state. Model raw responses, source-only candidates,
structural failures and post-output comparisons remain distinct inspectable layers.
"""
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import html
import json
from pathlib import Path

from pastor_transcript_extractor import automatic_proposition_binding as auto
from pastor_transcript_extractor import profile_proposition_review as reference
from pastor_transcript_extractor.binding_evidence import context_digest, text_digest, validate_span
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor import evidence_pipeline_trace as trace

VERSION=auto.VERSION
FIELDS=('proposition','voice_speaker','occurrence','adoption','polarity','expression','conditions_exceptions','qualifications_relations','address_invitation','scope','expressed_uncertainty','evidence_provenance')
OUTCOMES={'agreement','acceptable_alternative','omission','unsupported_inference','attribution_adoption_error','evidence_binding_error','other_failure','correctly_unresolved'}


def save(path,value):
    value=seal(value);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)
    return value


def read(path):
    value=json.loads(path.read_text())
    if seal(value)!=value:raise ValueError('Invalid development artifact seal')
    return value


def directory(base_dir=None):
    path=build_paths(base_dir).evaluation/VERSION
    if path.resolve().is_relative_to(trace.ROOT):raise ValueError('Generated development artifacts belong under the app base outside the repository')
    return path


@contextmanager
def exclusive(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e:raise ValueError('This bounded development run is already active') from e
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def panel(base_dir=None):
    reviewed=reference.load(base_dir)
    sources=[]
    for case in reviewed['cases']:
        texts=case['texts'];units=auto.source_units(texts)
        sources.append(dict(case_id=case['case_id'],sermon_title=case['sermon_title'],video_id=case['video_id'],block_id=case['block_id'],
            source_sha256=case['source_sha256'],start_seconds=case['start_seconds'],end_seconds=case['end_seconds'],watch_url=case['watch_url'],
            texts=texts,context_diagnostics=case['context_diagnostics'],units=units))
    # The source-reviewed report is loaded for exact identity and later comparison;
    # only this source envelope and code-owned units can enter a model request.
    if [c['video_id'] for c in sources]!=[4589,3973,281] or len(sources)!=3:
        raise ValueError('Only the three supplied development passages are authorized')
    return seal(dict(version=VERSION,model=auto.MODEL,min_probability=auto.MIN_PROBABILITY,sources=sources,
        source_inventory_fingerprint=reviewed['source_inventory_fingerprint'],membership_fingerprint=reviewed['membership_fingerprint'],
        reference_fingerprint=reviewed['content_fingerprint'],reference_visible_to_generation=False,
        generator_sha256=trace.digest(auto.__file__),
        reused_evidence='Existing exact targets/context, source/membership identity and generic/G2/G3 structures. Reviewed G2/G3 judgments are comparison references, not generation inputs; no compatible generated bindings from this new request policy are assumed.')),reviewed


def discovery_request(source):
    return dict(model=auto.MODEL,state=dict(target_text=source['texts']['target_text'],leading_context=source['texts']['leading_context'],trailing_context=source['texts']['trailing_context'],
        context_diagnostics=source['context_diagnostics'],source_candidates={u['candidate_id']:u for u in source['units']}),questions=auto.discovery_questions(source['units']))


def binding_request(source,units):
    questions={};candidates={}
    for unit in units:
        key=unit['candidate_id'];pool=auto.evidence_pool(source['texts'],source['units'],unit)
        candidates[key]=dict(span=unit['span'],evidence_pool=pool)
        for name,q in auto.field_questions(source['texts'],unit,pool).items():
            q=deepcopy(q);q['instructions']['task']='For state.candidates["'+key+'"] only: '+q['instructions']['task'].replace('candidate.span','state.candidates["'+key+'"].span')
            questions[key+'__'+name]=q
    return dict(model=auto.MODEL,state=dict(**source['texts'],context_diagnostics=source['context_diagnostics'],candidates=candidates),questions=questions)


def validate_request(request):
    # Keep this bounded transport input independent of reference prose/decisions.
    if set(request)!= {'model','state','questions'} or request['model']!=auto.MODEL:raise ValueError('Request policy differs')
    if set(request['state']) not in ({'target_text','leading_context','trailing_context','context_diagnostics','source_candidates'}, {'target_text','leading_context','trailing_context','context_diagnostics','candidates'}):
        raise ValueError('Foreign/reference fields in generation state')
    if len(json.dumps(request,ensure_ascii=False))>240000:raise ValueError('Bounded request size exceeded')


def execute(base_dir=None,*,provider_factory=None):
    spec,reviewed=panel(base_dir);root=directory(base_dir);run=root/'runs'/spec['content_fingerprint']
    if provider_factory is None:
        # Reuse only the existing SDK transport, not the closed G1 experiment,
        # discovery, predicate menu, cached interpretations or measurement policy.
        from pastor_transcript_extractor.sermon_g1_feasibility_review import Provider
        provider_factory=Provider
    invocation=dict(provider_requests=0,cache_hits=0,input_tokens=0,output_tokens=0)
    provider=None
    with exclusive(root/'execution.lock'):
        ledger_path=root/'request-ledger-v1.json'
        ledger=read(ledger_path) if ledger_path.exists() else dict(version=VERSION,attempts=[])
        def call(request):
            nonlocal provider,ledger
            validate_request(request);fingerprint=seal(request)['content_fingerprint'];cache=root/'cache'/f'{fingerprint}.json'
            if cache.exists():
                record=read(cache)
                if record['request']!=request:raise ValueError('Cached request identity differs')
                invocation['cache_hits']+=1
                return record
            if any(a['fingerprint']==fingerprint for a in ledger['attempts']):
                raise ValueError('A request was attempted without a reusable response; no automatic ambiguous retry')
            if len(ledger['attempts'])>=3+3*((auto.MAX_BINDINGS+auto.BATCH_SIZE-1)//auto.BATCH_SIZE):
                raise ValueError('Development request ceiling reached')
            if provider is None:provider=provider_factory()
            ledger['attempts'].append(dict(fingerprint=fingerprint,status='started',model=auto.MODEL))
            ledger=save(ledger_path,ledger);invocation['provider_requests']+=1
            try:
                raw=provider.assess(request['state'],request['questions'])
                auto.choices(raw,request['questions'])
                if raw['resolved_model']!=auto.MODEL:raise ValueError('Provider resolved a different model')
                record=save(cache,dict(request=request,response=raw,request_fingerprint=fingerprint))
                ledger['attempts'][-1]['status']='response_cached'
                ledger=save(ledger_path,ledger)
                for field in ('input_tokens','output_tokens'):invocation[field]+=raw.get('usage',{}).get(field) or 0
                return record
            except Exception as e:
                ledger['attempts'][-1].update(status='failed_or_ambiguous',error_type=type(e).__name__);save(ledger_path,ledger)
                raise
        cases=[];used=[]
        try:
            for source in spec['sources']:
                discovery=call(discovery_request(source));used.append(discovery)
                decisions,uncertain=auto.choices(discovery['response'],discovery['request']['questions'])
                included=[u for u in source['units'] if decisions[u['candidate_id']]=='include']
                if len(included)>auto.MAX_BINDINGS:raise ValueError('Generated-binding ceiling exceeded; no silent truncation')
                generated=[]
                for start in range(0,len(included),auto.BATCH_SIZE):
                    units=included[start:start+auto.BATCH_SIZE];response=call(binding_request(source,units));used.append(response)
                    for unit in units:
                        key=unit['candidate_id'];prefix=key+'__'
                        inventory={k.removeprefix(prefix):v for k,v in response['request']['questions'].items() if k.startswith(prefix)}
                        raw=dict(answers={k.removeprefix(prefix):v for k,v in response['response']['answers'].items() if k.startswith(prefix)})
                        d,unknown=auto.choices(raw,inventory);pool=response['request']['state']['candidates'][key]['evidence_pool']
                        provenance={k:deepcopy(source[k]) for k in ('case_id','video_id','block_id','source_sha256','start_seconds','end_seconds','watch_url','context_diagnostics')}
                        provenance.update(target_sha256=text_digest(source['texts']['target_text']),texts_sha256=context_digest(source['texts']),source_inventory_fingerprint=spec['source_inventory_fingerprint'],membership_fingerprint=spec['membership_fingerprint'],request_fingerprint=response['request_fingerprint'],model=auto.MODEL,development_only=True)
                        try:binding=auto.compose(source['texts'],unit,pool,d,provenance);error=None
                        except (ValueError,KeyError,TypeError) as e:binding=None;error=str(e)
                        generated.append(dict(candidate_id=key,source_span=unit['span'],decisions=d,uncertain_fields=unknown,binding=binding,compile_error=error,request_fingerprint=response['request_fingerprint']))
                cases.append(dict(**source,discovery_decisions=decisions,discovery_uncertain=uncertain,discovery_request_fingerprint=discovery['request_fingerprint'],generated=generated))
        finally:
            if provider is not None:provider.close()
        unique_used={r['request_fingerprint']:r for r in used}
        usage={name:sum(r['response'].get('usage',{}).get(name) or 0 for r in unique_used.values()) for name in ('input_tokens','output_tokens')}
        result_value=dict(version=VERSION,panel=spec,cases=cases,request_fingerprints=[r['request_fingerprint'] for r in used],
            unique_request_count=len(unique_used),usage=usage,cost='Not available from this provider response; token usage reported without an invented price.',
            accepted_observations=False,profile_projection=False,assurance_interpretation_changed=False,reference_changed=False,
            reference_visible_to_generation=False,database_writes=0,
            candidate_scope='Code-owned source units and typed choices on these three passages only; no claim of general discovery coverage.',
            scope_limit='Development references, not a benchmark/ground-truth corpus; no general accuracy/precision/recall or production-readiness claim.')
        path=run/'generated-v1.json'
        if path.exists():
            result=read(path)
            if result!=seal(result_value):raise ValueError('Immutable generated run differs')
        else:result=save(path,result_value)
        save(run/'invocation-v1.json',dict(version=VERSION,**invocation))
    return result,run,reviewed


def cached(base_dir=None):
    spec,reviewed=panel(base_dir);run=directory(base_dir)/'runs'/spec['content_fingerprint'];result=read(run/'generated-v1.json')
    if result['panel']!=spec:raise ValueError('Cached development panel differs')
    for key in result['request_fingerprints']:
        record=read(directory(base_dir)/'cache'/f'{key}.json')
        if seal(record['request'])['content_fingerprint']!=key:raise ValueError('Response/request linkage differs')
        validate_request(record['request'])
    return result,run,reviewed


def validate_comparison(comparison,result,reviewed):
    if comparison['generated_fingerprint']!=result['content_fingerprint'] or comparison['reference_fingerprint']!=reviewed['content_fingerprint']:
        raise ValueError('Semantic comparison is for a different generated run/reference')
    refs={r['binding']['binding_id']:(c,r['binding']) for c in reviewed['cases'] for r in c['readings']}
    if len(comparison['readings'])!=10 or {r['reference_id'] for r in comparison['readings']}!=set(refs):raise ValueError('Compare exactly the ten reviewed readings')
    generated={c['case_id']+'-auto-'+r['candidate_id']:(c,r) for c in result['cases'] for r in c['generated']}
    for row in comparison['readings']:
        case,_=refs[row['reference_id']]
        if set(row['fields'])!=set(FIELDS):raise ValueError('Every comparison needs all fields')
        for key in row['generated_ids']:
            if key not in generated or generated[key][0]['case_id']!=case['case_id']:raise ValueError('Comparison maps foreign candidate')
        for field in row['fields'].values():
            if field['outcome'] not in OUTCOMES or not field['finding'].strip():raise ValueError('Unknown or unexplained semantic comparison outcome')
            for s in field['evidence']:validate_span(s,case['texts'])
            if field['outcome'] in {'unsupported_inference','attribution_adoption_error','evidence_binding_error','other_failure'} and not field['evidence']:
                raise ValueError('Material discrepancy needs exact source evidence')
        if not row['correctly_unresolved'] or not row['summary']:raise ValueError('Comparison must preserve unknowns and explain outcome')
    if set(comparison['extra_generated']) != set(generated)-{key for row in comparison['readings'] for key in row['generated_ids']}:
        raise ValueError('Every unmapped generated candidate needs an explicit review')
    for extra in comparison['extra_generated'].values():
        if extra['outcome'] not in OUTCOMES or not extra['finding']:raise ValueError('Unexplained extra candidate')
    if not comparison['decision']['recommendation'] or comparison['decision']['answer'] not in {'yes','no'}:raise ValueError('Concrete decision/recommendation missing')
    return comparison


def report(base_dir=None,*,run_model=False,provider_factory=None):
    result,run,reviewed=execute(base_dir,provider_factory=provider_factory) if run_model else cached(base_dir)
    path=run/'semantic-review-v1.json';comparison=validate_comparison(read(path),result,reviewed) if path.exists() else None
    counts={field:dict(Counter(row['fields'][field]['outcome'] for row in comparison['readings'])) for field in FIELDS} if comparison else {}
    output=seal(dict(version=VERSION,status='DEVELOPMENT_RUN_COMPARED' if comparison else 'GENERATED_AWAITING_CODEX_SEMANTIC_COMPARISON',
        generated=result,invocation=read(run/'invocation-v1.json'),reference=reviewed,comparison=comparison,field_outcomes=counts,
        reviewed_readings=10,generated_candidates=sum(len(c['generated']) for c in result['cases']),
        structurally_valid_candidates=sum(bool(g['binding']) for c in result['cases'] for g in c['generated']),
        human_acceptance='Not automatic; generated records remain development candidates.',run_directory=str(run)))
    save(run/'review-v1.json',output)
    (run/'review-v1.md').write_text(markdown(output))
    (run/'index.html').write_text(render(output))
    return output,run/'index.html'


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
        for row in comparison['readings']:
            lines+=['','## '+row['reference_id'],'',row['summary'],'','Generated candidates: '+', '.join(row['generated_ids']),'','| Field | Outcome | Semantic comparison |','|---|---|---|']
            for field,finding in row['fields'].items():lines+=['| '+field.replace('_',' ')+' | '+finding['outcome'].replace('_',' ')+' | '+finding['finding'].replace('|','/')+' |']
            lines+=['','Correctly unresolved: '+row['correctly_unresolved'],'']
    for c in generated['cases']:
        lines+=['','## Generated: '+c['sermon_title'],'','[Watch source]('+c['watch_url']+')','']
        for g in c['generated']:
            key=c['case_id']+'-auto-'+g['candidate_id'];lines+=['### '+key,'','> '+g['source_span']['text'],'','```json',json.dumps(g,ensure_ascii=False,indent=2),'```','']
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
        parts.append('<section class="panel"><h2>Across these ten development readings</h2><div class="tablewrap"><table><thead><tr><th>Field</th><th>Outcomes · ten readings per field</th></tr></thead><tbody>'+''.join('<tr><th>'+e(k.replace('_',' '))+'</th><td>'+e(', '.join(n.replace('_',' ')+': '+str(v) for n,v in counts.items()))+'</td></tr>' for k,counts in output['field_outcomes'].items())+'</tbody></table></div><p>These counts describe this development run. They are not general accuracy, precision, recall or production readiness.</p></section>')
        for row in comparison['readings']:
            c,ref=refs[row['reference_id']];b=ref['binding']
            table=''.join('<tr><th>'+e(field.replace('_',' '))+'</th><td>'+e(f['outcome'].replace('_',' '))+'</td><td>'+e(f['finding'])+evidence(f['evidence'],c['case_id'])+'</td></tr>' for field,f in row['fields'].items())
            parts.append('<section class="panel" id="review-'+e(row['reference_id'])+'"><h2>'+e(b['title'])+'</h2><p class="note">'+e(row['summary'])+'</p><p><strong>Reviewed reference:</strong> '+e(b['proposition']['reading'])+'</p>'+evidence([b['proposition']['span']],c['case_id'])+'<p><strong>Automation generated:</strong> '+(', '.join('<a href="#'+e(key)+'">'+e(key)+'</a>' for key in row['generated_ids']) or 'No matched generated candidate')+'</p><div class="tablewrap"><table><thead><tr><th>Field</th><th>Outcome</th><th>Semantic finding and exact source</th></tr></thead><tbody>'+table+'</tbody></table></div><p><strong>Correctly left unresolved:</strong> '+e(row['correctly_unresolved'])+'</p><details><summary>Unchanged reviewed record and assurance interpretation</summary><pre>'+e(json.dumps(ref,ensure_ascii=False,indent=2))+'</pre></details></section>')
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
