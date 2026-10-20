"""Bounded three-passage automatic binding run and post-output semantic review.

References never enter provider state. Model raw responses, source-only candidates,
structural failures and post-output comparisons remain distinct inspectable layers.
"""
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
from pathlib import Path

from pastor_transcript_extractor import automatic_proposition_binding as auto
from pastor_transcript_extractor import profile_proposition_review as reference
from pastor_transcript_extractor.binding_evidence import context_digest, text_digest, validate_span
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor.profile_binding_development_presentation import markdown, render

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
        generator_sha256=trace.digest(auto.__file__),runner_sha256=trace.digest(__file__),generic_compiler_sha256=trace.digest(auto.generic.__file__),
        reused_evidence='Existing exact targets/context, source/membership identity and generic/G2/G3 structures. Reviewed G2/G3 judgments are comparison references, not generation inputs; no compatible generated bindings from this new request policy are assumed.')),reviewed


def discovery_request(source):
    return dict(model=auto.MODEL,state=dict(target_text=source['texts']['target_text'],leading_context=source['texts']['leading_context'],trailing_context=source['texts']['trailing_context'],
        context_diagnostics=source['context_diagnostics'],source_candidates={u['candidate_id']:u for u in source['units']}),questions=auto.discovery_questions(source['units']))


def binding_request(source,units,*,stage='frame',frames=None):
    questions={};candidates={}
    for unit in units:
        key=unit['candidate_id'];pool=auto.evidence_pool(source['texts'],source['units'],unit)
        candidates[key]=dict(span=unit['span'],speech_layer=unit.get('speech_layer','unmarked'),outer_frame=unit.get('outer_frame'),evidence_pool=pool)
        if stage=='interpretation':
            if frames is None or key not in frames:raise ValueError('Interpretation requires prior frame choices')
            candidates[key]['frame_selection']=frames[key]
        for name,q in auto.field_questions(source['texts'],unit,pool,stage=stage).items():
            q=deepcopy(q);q['instructions']['task']='For state.candidates["'+key+'"] only: '+q['instructions']['task'].replace('candidate.span','state.candidates["'+key+'"].span').replace('candidate.frame_selection','state.candidates["'+key+'"].frame_selection')
            questions[key+'__'+name]=q
    return dict(model=auto.MODEL,state=dict(**source['texts'],context_diagnostics=source['context_diagnostics'],candidates=candidates),questions=questions)


def validate_request(request):
    # Keep this bounded transport input independent of reference prose/decisions.
    if set(request)!= {'model','state','questions'} or request['model']!=auto.MODEL:raise ValueError('Request policy differs')
    if set(request['state']) not in ({'target_text','leading_context','trailing_context','context_diagnostics','source_candidates'}, {'target_text','leading_context','trailing_context','context_diagnostics','candidates'}):
        raise ValueError('Foreign/reference fields in generation state')
    if len(json.dumps(request,ensure_ascii=False))>240000:raise ValueError('Bounded request size exceeded')


def frame_choices(response,units):
    decisions,unknown=auto.choices(response['response'],response['request']['questions'])
    frames={u['candidate_id']:dict(decisions={k.removeprefix(u['candidate_id']+'__'):v for k,v in decisions.items() if k.startswith(u['candidate_id']+'__')},
        uncertain_fields=[k.removeprefix(u['candidate_id']+'__') for k in unknown if k.startswith(u['candidate_id']+'__')]) for u in units}
    for key,frame in frames.items():
        pool=response['request']['state']['candidates'][key]['evidence_pool']
        if frame['decisions']['voice_evidence'] not in pool or frame['decisions']['speaker']=='unresolved':
            frame['decisions']['voice']='unresolved'
            if 'voice' not in frame['uncertain_fields']:frame['uncertain_fields'].append('voice')
    return frames


def compile_response(source,unit,response,spec,frame_response):
    key=unit['candidate_id'];prefix=key+'__'
    inventory={k.removeprefix(prefix):v for k,v in response['request']['questions'].items() if k.startswith(prefix)}
    raw=dict(answers={k.removeprefix(prefix):v for k,v in response['response']['answers'].items() if k.startswith(prefix)})
    d,unknown=auto.choices(raw,inventory);pool=response['request']['state']['candidates'][key]['evidence_pool']
    prior=frame_choices(frame_response,[unit])[key]
    if response['request']['state']['candidates'][key]['frame_selection']!=prior:raise ValueError('Interpretation/frame linkage differs')
    d.update(prior['decisions']);unknown=prior['uncertain_fields']+unknown
    provenance={k:deepcopy(source[k]) for k in ('case_id','video_id','block_id','source_sha256','start_seconds','end_seconds','watch_url','context_diagnostics')}
    provenance.update(target_sha256=text_digest(source['texts']['target_text']),texts_sha256=context_digest(source['texts']),source_inventory_fingerprint=spec['source_inventory_fingerprint'],membership_fingerprint=spec['membership_fingerprint'],request_fingerprint=response['request_fingerprint'],frame_request_fingerprint=frame_response['request_fingerprint'],model=auto.MODEL,development_only=True)
    try:binding=auto.compose(source['texts'],unit,pool,d,provenance);error=None
    except (ValueError,KeyError,TypeError) as e:binding=None;error=str(e)
    return dict(candidate_id=key,source_span=unit['span'],decisions=d,uncertain_fields=unknown,binding=binding,compile_error=error,request_fingerprint=response['request_fingerprint'],frame_request_fingerprint=frame_response['request_fingerprint'])


def prepare(base_dir=None):
    """Read-only source/request preflight; no provider, cache mutation or validation."""
    spec,_=panel(base_dir)
    for source in spec['sources']:
        validate_request(discovery_request(source))
        for start in range(0,len(source['units']),auto.BATCH_SIZE):
            units=source['units'][start:start+auto.BATCH_SIZE]
            validate_request(binding_request(source,units))
            frames={u['candidate_id']:dict(decisions={name:'unresolved' for name in auto.FRAME_FIELDS},uncertain_fields=sorted(auto.FRAME_FIELDS)) for u in units}
            validate_request(binding_request(source,units,stage='interpretation',frames=frames))
    return dict(status='V2_PREPARED_NOT_EXECUTED',version=VERSION,panel_fingerprint=spec['content_fingerprint'],
        passages=[dict(case_id=s['case_id'],candidates=len(s['units'])) for s in spec['sources']],
        max_provider_requests=3+2*3*((auto.MAX_BINDINGS+auto.BATCH_SIZE-1)//auto.BATCH_SIZE),
        min_probability=auto.MIN_PROBABILITY,provider_requests=0,writes=0,
        stages=['relevance_and_boundary','speech_frame','dependent_interpretation'],
        command='pte analysis profile-binding-development --run --json',
        prior_result='V1 remains preserved under automatic-generic-proposition-binding-dev-v1; no V2 semantic results yet.')


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
            if len(ledger['attempts'])>=3+2*3*((auto.MAX_BINDINGS+auto.BATCH_SIZE-1)//auto.BATCH_SIZE):
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
                included=auto.included_units(source['units'],decisions)
                if len(included)>auto.MAX_BINDINGS:raise ValueError('Generated-binding ceiling exceeded; no silent truncation')
                generated=[]
                for start in range(0,len(included),auto.BATCH_SIZE):
                    units=included[start:start+auto.BATCH_SIZE]
                    frame=call(binding_request(source,units));used.append(frame)
                    response=call(binding_request(source,units,stage='interpretation',frames=frame_choices(frame,units)));used.append(response)
                    for unit in units:
                        generated.append(compile_response(source,unit,response,spec,frame))
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
    represented=[];unique={}
    def response_for(request):
        key=seal(request)['content_fingerprint'];record=read(directory(base_dir)/'cache'/f'{key}.json')
        if record['request']!=request or record['request_fingerprint']!=key:raise ValueError('Response/request linkage differs')
        validate_request(record['request']);represented.append(key);unique[key]=record
        return record
    if len(result['cases'])!=len(spec['sources']):raise ValueError('Generated source coverage differs')
    for source,case in zip(spec['sources'],result['cases']):
        if any(case[k]!=v for k,v in source.items()):raise ValueError('Generated source differs')
        discovery=response_for(discovery_request(source))
        decisions,uncertain=auto.choices(discovery['response'],discovery['request']['questions'])
        if decisions!=case['discovery_decisions'] or uncertain!=case['discovery_uncertain']:raise ValueError('Discovery decisions differ from raw response')
        included=auto.included_units(source['units'],decisions);expected=[]
        for start in range(0,len(included),auto.BATCH_SIZE):
            units=included[start:start+auto.BATCH_SIZE]
            frame=response_for(binding_request(source,units))
            response=response_for(binding_request(source,units,stage='interpretation',frames=frame_choices(frame,units)))
            expected.extend(compile_response(source,unit,response,spec,frame) for unit in units)
        if expected!=case['generated']:raise ValueError('Generated bindings differ from cached source decisions')
    if represented!=result['request_fingerprints'] or len(unique)!=result['unique_request_count']:raise ValueError('Request coverage differs')
    usage={name:sum(r['response'].get('usage',{}).get(name) or 0 for r in unique.values()) for name in ('input_tokens','output_tokens')}
    if usage!=result['usage']:raise ValueError('Usage differs from cached responses')
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
        if row['content_recovery'] not in {'located','partial','missing'}:raise ValueError('Content recovery must be explicit')
        if row['fully_faithful'] and any(f['outcome'] not in {'agreement','acceptable_alternative','correctly_unresolved'} for f in row['fields'].values()):raise ValueError('A material discrepancy cannot be called fully faithful')
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
    summary=dict(Counter(row['content_recovery'] for row in comparison['readings'])) if comparison else {}
    if comparison:summary['fully_faithful']=sum(row['fully_faithful'] for row in comparison['readings'])
    from pastor_transcript_extractor import profile_binding_development_presentation as presentation
    output=seal(dict(version=VERSION,development_summary=summary,renderer_sha256=trace.digest(presentation.__file__),status='DEVELOPMENT_RUN_COMPARED' if comparison else 'GENERATED_AWAITING_CODEX_SEMANTIC_COMPARISON',
        generated=result,invocation=read(run/'invocation-v1.json'),reference=reviewed,comparison=comparison,field_outcomes=counts,
        reviewed_readings=10,generated_candidates=sum(len(c['generated']) for c in result['cases']),
        structurally_valid_candidates=sum(bool(g['binding']) for c in result['cases'] for g in c['generated']),
        human_acceptance='Not automatic; generated records remain development candidates.',run_directory=str(run)))
    save(run/'review-v1.json',output)
    (run/'review-v1.md').write_text(markdown(output))
    (run/'index.html').write_text(render(output))
    return output,run/'index.html'
