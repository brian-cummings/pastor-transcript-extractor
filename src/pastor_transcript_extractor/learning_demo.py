"""Bounded V3 preparation/orchestration adapter over the shared evidence services.

No source references, authored pastor readings or evaluation answers enter generation.
The CLI defaults to offline preparation; execution needs a separately bound decision.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys

from .config import build_paths
from .pastor_evidence import (EvidenceArtifactStore, EvidencePolicy, EvidenceView, SampleSpec,
    SourceWindow, compile_machine_binding, digest)
from .binding_evidence import context_digest, text_digest
from .evidence_requests import (BudgetLedger, PHASES, ReceiptStore, RequestSpec, execute,
    openai_transport, typesafe_transport, reservation)
from . import learning_demo_contracts as contract
from .pastor_fingerprint import ROOTS, build_fingerprint, topic_measurements
from .pastor_similarity import compare_fingerprints, ComparisonSpec
from .profile_explanatory_descriptions import generated_hypotheses
from .profile_presentation import generated_narrative

VERSION='learning-demo-v3-preparation-v1'
SCOPE={318:(3973,281,4589),130:(1037,350,4430)}
WIDER_TOPICS=('human_nature_identity','relationships_family_interpersonal','suffering_adversity_death',
    'ethics_moral_conduct','compassion_generosity_service','vocation_stewardship_daily_life',
    'society_public_life','church_worship_community')


def file_hash(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local_tokenizer(base_dir):
    """Reuse only the pinned installed tokenizer files, never the closed run controller."""
    base=build_paths(base_dir).evaluation/'context-extraction-probe-v1'
    lock_path=Path(__file__).parents[2]/'docs/review-proposals/context-extraction-probe-v1/runtime-lock-v1.json'
    lock=json.loads(lock_path.read_text())
    for name, expected in lock['files'].items():
        if file_hash(base/name)!=expected: raise ValueError('Pinned local tokenizer/cache differs: '+name)
    if sys.version.split()[0]!=lock['python']: raise ValueError('Pinned tokenizer Python differs')
    sys.dont_write_bytecode=True
    runtime=str(base/'runtime')
    if runtime not in sys.path: sys.path.insert(0,runtime)
    old_cache=os.environ.get('TIKTOKEN_CACHE_DIR')
    os.environ['TIKTOKEN_CACHE_DIR']=str(base/'tokenizer-cache')
    try:
        import tiktoken
        if tiktoken.__version__!='0.12.0' or not Path(tiktoken.__file__).is_relative_to(base/'runtime'):
            raise ValueError('Foreign tokenizer')
        encoding=tiktoken.get_encoding('o200k_base')
    finally:
        if old_cache is None: os.environ.pop('TIKTOKEN_CACHE_DIR',None)
        else: os.environ['TIKTOKEN_CACHE_DIR']=old_cache
    return encoding,dict(lock_path=str(lock_path),lock_sha256=file_hash(lock_path),
                         runtime_root=str(base),encoding='o200k_base',version='0.12.0')


def independent_control(video_id,eligible_ids):
    return min(eligible_ids,key=lambda block_id:text_digest(f'pte-learning-v3-control-v1|{video_id}|{block_id}'))


def select_anchors(video_id,blocks,eligible_ids,treatment):
    """Reserve the score-independent control before looking at detector scores."""
    control=independent_control(video_id,eligible_ids)
    used={control}; result={}
    sem={row['block_id']:row['probabilities'] for row in treatment}
    for slot in ('theology','wider_worldview','application'):
        def score(block):
            if slot=='wider_worldview': return max(block['scores'][key]['score'] for key in WIDER_TOPICS)
            return sem[block['block_id']]['doctrinal_argument' if slot=='theology' else 'practical_application']
        candidates=[b for b in blocks if b['block_id'] in eligible_ids and b['block_id'] not in used
                    and (slot=='wider_worldview' or b['block_id'] in sem)]
        chosen=min(candidates,key=lambda b:(-score(b),b['start_seconds'],b['block_id']))['block_id']
        result[slot]=chosen;used.add(chosen)
    result['independent_control']=control
    return result


def source_window(case,analysis,eligible):
    from .sermon_topics import resolve_topic_block_context
    blocks=sorted(analysis['blocks'],key=lambda b:(b['start_seconds'],b['block_id']))
    index=next(i for i,b in enumerate(blocks) if b['block_id']==case['anchor_block_id'])
    neighbors=blocks[max(0,index-1):index+2]
    included=[b for b in neighbors if b['block_id'] in eligible]
    if [b['block_id'] for b in included]!=case['target_block_ids']:
        raise ValueError('Frozen actual adjacent target geometry changed')
    excluded=[b['block_id'] for b in neighbors if b['block_id'] not in eligible]
    if excluded!=case['excluded_immediate_neighbors']: raise ValueError('Excluded neighbor state changed')
    saved=[]
    for block,expected in zip(included,case['blocks'],strict=True):
        context=resolve_topic_block_context(block)
        if (text_digest(context['target_text'])!=expected['target_sha256'] or context_digest(context)!=expected['context_sha256']
            or any(block[k]!=expected[k] for k in ('start_seconds','end_seconds','block_id'))):
            raise ValueError('Frozen source/context/bounds changed')
        saved.append(dict(block_id=block['block_id'],target_text=context['target_text'],
            start_seconds=block['start_seconds'],end_seconds=block['end_seconds'],
            segment_indexes=block['segment_indexes'],context=context,
            context_identity=block['context_identity']))
    return SourceWindow(case['case_id'],case['profile_id'],case['video_id'],case['source_sha256'],
        case['anchor_block_id'],tuple(saved),case['stratum'],tuple(excluded),analysis['context_policy_version'])


def code_identity():
    names=('pastor_evidence','pastor_fingerprint','pastor_similarity','evidence_requests','learning_demo',
           'learning_demo_contracts','profile_evidence_supply','profile_explanatory_descriptions',
           'profile_presentation','binding_evidence','theological_binding','segment_cache_inventory',
           'sermon_topics','sermon_topic_profile_analysis','sermon_topic_projection','profile_analysis')
    return {name:file_hash(Path(__file__).with_name(name+'.py')) for name in names}


def _run_directory(base_dir,fingerprint):
    root=build_paths(base_dir).evaluation/'learning-demo-v3'
    repository=Path(__file__).parents[2].resolve()
    if root.resolve().is_relative_to(repository): raise ValueError('Generated artifacts must be outside repository')
    return root/fingerprint


def prepare(proposal_path,base_dir=None,*,check_only=False,encoding=None,tokenizer_identity=None):
    from . import segment_cache_inventory
    from .profile_evidence_supply import read_sample
    from .sermon_topics import resolve_topic_analysis_artifact
    from .sermon_topic_profile_analysis import _projection_measurements
    proposal_path=Path(proposal_path).resolve()
    proposal=json.loads(proposal_path.read_text())
    if proposal['schema_version']!='pte-demonstration-proposal-v3' or {
        int(k):tuple(v) for k,v in proposal['scope'].items()}!=SCOPE:
        raise ValueError('Only the authorized V3 preparation scope is allowed')
    for name,expected in proposal['document_hashes'].items():
        if file_hash(proposal_path.parent/name)!=expected: raise ValueError('Proposal companion changed: '+name)
    for key in ('source_audit','prior_v2'):
        if file_hash(proposal[key]['path'])!=proposal[key]['sha256']: raise ValueError('Proposal lineage changed')
    expected_phases=[dict(phase=k,provider=v[0],model=v[1],maximum_attempts=v[2],
        input_reservation_per_attempt=v[3],output_cap_per_attempt=v[4],
        input_usd_per_million=v[5],output_usd_per_million=v[6],
        list_price_reservation_usd=str(reservation(k)*v[2])) for k,v in PHASES.items()]
    for actual,expected in zip(proposal['provider_proposal']['phases'],expected_phases,strict=True):
        if any(str(actual[k])!=str(v) for k,v in expected.items()): raise ValueError('V3 request/model/budget contract differs')
    if encoding is None: encoding,tokenizer_identity=local_tokenizer(base_dir)
    samples=[]; windows=[]; measurements=[]; reuse=[]; source_refs=[]; requests=[]
    cases=proposal['source_panel']['cases']
    if len(cases)!=24 or len({c['case_id'] for c in cases})!=24 or Counter(c['stratum'] for c in cases)!=dict(detector_selected=18,independent_control=6):
        raise ValueError('Exactly 24 windows / six independent controls required')
    for profile_id,video_ids in SCOPE.items():
        inventory=segment_cache_inventory.build(base_dir,profile_id=profile_id,video_ids=video_ids)
        sample=SampleSpec(profile_id,video_ids,inventory['selected_profile']['membership_fingerprint'],
                          tuple(s['run_id'] for s in inventory['sermons']))
        # Reuse the existing bounded cache reader; independently inspects all registered
        # full, individual/refinement and saved composed identities, without writes.
        inventory,sources,checks=read_sample(sample,base_dir)
        samples.append(asdict(sample));reuse.extend(checks)
        for sermon in inventory['sermons']:
            vid=sermon['video_id']; analysis=resolve_topic_analysis_artifact(sources[vid]['classification'])
            selected=[c for c in cases if c['video_id']==vid and c['profile_id']==profile_id]
            if len(selected)!=4: raise ValueError('Frozen per-recording window count changed')
            anchors=select_anchors(vid,analysis['blocks'],set(sermon['eligible_block_ids']),sermon['treatment'])
            for case in selected:
                if case['source_path']!=sermon['source_path'] or case['source_sha256']!=sermon['source_sha256']:
                    raise ValueError('Canonical source snapshot changed')
                if anchors[case['slot']]!=case['anchor_block_id']: raise ValueError('Frozen selector result changed')
                window=source_window(case,analysis,set(sermon['eligible_block_ids']))
                texts,mapping=window.target()
                state=dict(texts=texts,block_mapping=mapping,target_scope='declared_blocks_only',
                           source_identity=asdict(window))
                # Keep saved diagnostics but do not duplicate source text in state.
                state['source_identity']={k:v for k,v in asdict(window).items() if k!='blocks'}
                request=contract.generation_request('source_reading',state,
                    dict(source_sha256=window.source_sha256,target_digest=digest(texts),
                         coordinate_policy='unicode-block-reversible-v1',builder=window.builder_identity))
                account=request.preflight(encoding)
                requests.append(dict(case_id=case['case_id'],request=asdict(request),fingerprint=request.fingerprint,token_account=account))
                windows.append(asdict(window))
            source=dict(video_id=vid,profile_id=profile_id,path=sermon['source_path'],sha256=sermon['source_sha256'],
                run_id=sermon['run_id'],membership_fingerprint=sample.membership_fingerprint,
                eligible_block_ids=sermon['eligible_block_ids'],eligible_seconds=analysis['sermon_projection']['eligible_sermon_seconds'])
            source_refs.append(source)
            meaning_contract=dict(question_pack_version=analysis['question_pack_version'],
                question_pack_digest=analysis['question_pack_digest'],model=analysis['requested_model_id'],
                projection_policy=analysis['sermon_projection']['policy_version'])
            adapted=list(topic_measurements(vid,_projection_measurements(analysis['sermon_projection']),meaning_contract,[source]))
            for row in adapted:
                row.update(eligible_duration=source['eligible_seconds'],measured_duration=source['eligible_seconds'])
            measurements.extend(adapted)
    counts=Counter((w['video_id'],b['block_id']) for w in windows for b in w['blocks'])
    packet=dict(schema_version=VERSION,proposal=dict(path=str(proposal_path),sha256=file_hash(proposal_path)),
        code_identity=code_identity(),samples=samples,windows=windows,source_refs=source_refs,
        measurements=measurements,reusable_constituents=reuse,source_requests=requests,
        tokenizer=tokenizer_identity,contracts=dict(version=contract.VERSION,schemas=contract.SCHEMAS,
            prompts=contract.PROMPTS,required_checks=contract.CHECK_MEANINGS),
        downstream_batch_plan=dict(source_verification='one per window, <=12 claims, ten independent checks each',
            alignment_and_interpretation='one per recording, <=48 assignments and <=2 hypotheses, all-profile qualified claim index',
            narratives_and_pair_report='one per profile and one pair report, <=12 clauses each',
            downstream_verification='six alignment/hypothesis batches and three narrative batches',
            overflow='stop with explicit fit failure, no truncation, repair or new batches'),
        budget=dict(phases=expected_phases,maximum_attempts=66,total_ceiling_usd='2.00',source_ceiling_usd='1.50',
            downstream_ceiling_usd='.50',reserved_usd=str(sum(reservation(k)*v[2] for k,v in PHASES.items())),
            retries=0,fallbacks=0,prices_as_of=proposal['provider_proposal']['prices_checked_on']),
        coverage=dict(windows=24,strata=dict(Counter(w['stratum'] for w in windows)),unique_blocks=len(counts),
            duplicated_blocks=[dict(video_id=v,block_id=b,windows=n) for (v,b),n in sorted(counts.items()) if n>1],
            limit='window coverage, not whole-sermon discovery recall'),
        acceptance=proposal['v2_acceptance_criteria_preserved'],verification_bias=proposal['verification_bias'],
        human_limits=proposal['human_limits'],operations=dict(provider_calls=0,model_calls=0,database_writes=0,
            actual_comparisons=0,production_admission_changed=False),execution_authorized=False,
        prerequisites=['Separate Brian M5 decision bound to this input fingerprint',
            'Current account/model access and dated price attestation within frozen caps',
            'Both credentials present; provider-free preflight cannot establish account access',
            'All dynamically expanded batches pass frozen per-question/request preflight; otherwise stop'])
    packet['input_fingerprint']=digest(packet)
    out=_run_directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        render_preparation(packet,out)
    return packet,out


def render_preparation(packet,out):
    text='# V3 provider-free preparation\n\n'+f"Input: `{packet['input_fingerprint']}`.\n\n"+\
        '24 frozen windows; 18 detector-selected and six independent controls. No model/provider calls, actual comparisons or production admission.\n\n'+\
        'Budget: 66 maximum paid attempts; $1.657552896 reserved at proposal prices; $2 ceiling. Prices/access remain execution prerequisites.\n\n'+\
        'Existing V8/P1 and Scripture commands remain separate. New `pte analysis learning-demo prepare`, `run` and `report` adapt shared services.\n\n'+\
        'M5 is separately authorized. Run input must match the immutable fingerprint and code/source hashes; no runtime repair or routine approval.\n\n'+\
        '\n'.join('- '+s for s in packet['prerequisites'])+'\n'
    base=out.parents[2]
    preflight=f'pte analysis learning-demo run --base-dir {base} --input {out / "input.json"} --check-only --json'
    execution=f'pte analysis learning-demo run --base-dir {base} --input {out / "input.json"} --experimental --approve-input {packet["input_fingerprint"]} --max-usd 2.00 --confirm-proposal-prices --json'
    reporting=f'pte analysis learning-demo report --base-dir {base} --run-dir {out} --json'
    text+='\nProvider-free preflight:\n\n```sh\n'+preflight+'\n```\n\nSeparately authorized M5 only (not executed):\n\n```sh\n'+execution+'\n```\n\nReport:\n\n```sh\n'+reporting+'\n```\n'
    path=out/'preparation.md'
    if path.exists() and path.read_text()!=text: raise ValueError('Immutable preparation report changed')
    path.write_text(text)


def verify_input(input_path,base_dir=None):
    packet=json.loads(Path(input_path).read_text())
    if packet['input_fingerprint']!=digest({k:v for k,v in packet.items() if k!='input_fingerprint'}):
        raise ValueError('Input fingerprint differs')
    if Path(input_path).resolve()!=(_run_directory(base_dir,packet['input_fingerprint'])/'input.json').resolve():
        raise ValueError('Input must be in the configured immutable application run directory')
    if packet['code_identity']!=code_identity(): raise ValueError('Implementation changed after freeze')
    if file_hash(packet['proposal']['path'])!=packet['proposal']['sha256']: raise ValueError('Proposal changed')
    for source in packet['source_refs']:
        if file_hash(source['path'])!=source['sha256']: raise ValueError('Frozen source changed')
    from .profile_evidence_supply import read_sample
    for raw in packet['samples']:
        sample=SampleSpec(**{**raw,'video_ids':tuple(raw['video_ids']),'input_run_ids':tuple(raw['input_run_ids'])})
        inventory,_,_=read_sample(sample,base_dir)
        if tuple(s['run_id'] for s in inventory['sermons'])!=sample.input_run_ids:
            raise ValueError('Frozen run lineage changed')
    encoding,identity=local_tokenizer(base_dir)
    if identity!=packet['tokenizer']: raise ValueError('Tokenizer identity changed')
    for raw in packet['source_requests']:
        request=RequestSpec(**raw['request'])
        if request.fingerprint!=raw['fingerprint'] or request.preflight(encoding)!=raw['token_account']:
            raise ValueError('Serialized source request changed')
    return packet,encoding


def _checks_pass(checks):
    return set(checks)=={'meaning','scope','warrant'} and all(
        v.get('resolved') and .9<=v.get('probability',-1)<=1 for v in checks.values())


def _source_state(window):
    texts,mapping=window.target()
    return dict(texts=texts,block_mapping=mapping,window_id=window.id,video_id=window.video_id)


def _entry_scope(row):
    return sorted({r['video_id'] for r in row['source_refs']})


def _compact_binding(binding):
    # Lossless span interning removes repeated literal text, never qualifications.
    literals={}; literal_ids={}
    def intern(value):
        if isinstance(value,dict):
            if {'source_field','start','end','text'} <= set(value):
                fingerprint=digest(value)
                key=literal_ids.setdefault(fingerprint,'s'+str(len(literal_ids)))
                literals[key]=value
                return dict(literal_span_id=key)
            return {k:intern(v) for k,v in value.items() if k!='rationale'}
        if isinstance(value,list): return [intern(v) for v in value]
        return value
    fields=('proposition','voice','adoption','polarity','expression','epistemic_status','conditions',
            'scope','evidence_nodes','development_relations','qualifications','address_acts','unknowns')
    compact=intern({k:binding[k] for k in fields})
    return dict(fields=compact,literal_spans=literals)


def _entries(fingerprints,observations,hypotheses):
    entries={row['id']:dict(scope_video_ids=_entry_scope(row),binding=_compact_binding(row['binding']),source_refs=[
                 {k:ref[k] for k in ('video_id','block_id','target_sha256','local_start','local_end')}
                 for ref in row['source_refs']])
             for row in observations}
    for fp in fingerprints:
        for key,row in fp['claim_frames'].items():
            if row['state'] not in ([1,0],[0,1]): continue
            entries[key]=dict(scope_video_ids=sorted({r['video_id'] for state in ('A','D') for r in row[state]}),
                meaning=row['meaning'],state=row['state'],premise_ids=row['evidence_ids'])
    for row in hypotheses:
        entries[row['id']]=dict(scope_video_ids=row['scope_video_ids'],hypothesis=row)
    return entries


def _comparison_entry(value,scope):
    metrics={};premises=set()
    for op,metric in value.items():
        if not op.endswith('_metrics'): continue
        summary={k:v for k,v in metric.items() if k not in ('feature_contributions','exclusions')}
        contributions=[]
        for row in metric['feature_contributions']:
            contribution={k:v for k,v in row.items() if k not in ('left_sources','right_sources')}
            for side in ('left_sources','right_sources'):
                evidence=row[side]
                premises.update(evidence.get('evidence_ids',[]))
                if 'contract' in evidence:
                    contribution[side]=dict(contract=evidence['contract'],estimand=evidence['estimand'],
                        recordings=evidence['recordings'])
            contributions.append(contribution)
        summary['feature_contributions']=contributions
        summary['exclusions']=[dict(id=r['id'],reason=r['reason']) for r in metric['exclusions']]
        metrics[op]=summary
    return dict(scope_video_ids=scope,comparison=metrics,premise_ids=sorted(premises))


def dependency_entries(entries, ids):
    selected=set(ids)
    while True:
        expanded=selected | {p for key in selected & set(entries)
            for p in entries[key].get('premise_ids', entries[key].get('hypothesis',{}).get('premise_ids',[]))}
        if expanded==selected: break
        selected=expanded
    return {key:entries[key] for key in sorted(selected & set(entries))}


def usage_account(store):
    attempts=store.attempts(); known_input=0;known_output=0;known_cost=Decimal(0);unknown=0
    for attempt in attempts:
        path=store.root/'receipts'/(attempt['request_fingerprint']+'.json')
        if not path.exists(): unknown+=1;continue
        receipt=json.loads(path.read_text()); usage=receipt['response'].get('usage',{})
        if type(usage.get('input_tokens')) is not int or type(usage.get('output_tokens')) is not int:
            unknown+=1;continue
        i,o=usage['input_tokens'],usage['output_tokens'];known_input+=i;known_output+=o
        phase=PHASES[attempt['phase']]
        known_cost+=(Decimal(i)*Decimal(phase[5])+Decimal(o)*Decimal(phase[6]))/Decimal(1000000)
    return dict(attempts=len(attempts),reserved_usd=str(sum((Decimal(a['reserved_usd']) for a in attempts),Decimal(0))),
        known_input_tokens=known_input,known_output_tokens=known_output,known_list_price_usage_usd=str(known_cost),
        unknown_usage_attempts=unknown,runtime_repairs=0,runtime_approvals=0,reference_inputs=0)


def execute_pipeline(packet,store,transport,*,encoding):
    """One automatic recipe. Tests inject only synthetic model boundary responses.

    This function contains no human references, fixed fingerprints or pastor warrants.
    Production uses the same evidence/fingerprint/comparison kernels under its policy.
    """
    ledger=BudgetLedger();observations=[];reading_outputs=[];failures=[]
    windows={w['id']:SourceWindow(**{**w,'blocks':tuple(w['blocks']),
        'excluded_neighbors':tuple(w['excluded_neighbors'])}) for w in packet['windows']}
    def send(request):
        return execute(request,ledger,store,transport,encoding=encoding)
    for serialized in packet['source_requests']:
        request=RequestSpec(**serialized['request']);window=windows[serialized['case_id']]
        response=send(request)
        try: reading=contract.generated_output('source_reading',response)
        except (ValueError,KeyError,TypeError) as error:
            failures.append(dict(component='reading_schema',window_id=window.id,reason=str(error)));continue
        reading_outputs.append(dict(window_id=window.id,output=reading))
        if (reading['status']=='none' and reading['claims']) or (reading['status']=='proposed' and not reading['claims']):
            failures.append(dict(component='reading_schema',window_id=window.id,reason='inconsistent_status'));continue
        proposed=[]
        for claim in reading['claims']:
            try:
                envelope=compile_machine_binding(window,claim,model=request.body['model'],
                    prompt_digest=digest(contract.READ_PROMPT),raw_response_ref='receipts/'+request.fingerprint+'.json')
                proposed.append(envelope)
            except (ValueError,KeyError,TypeError) as error:
                failures.append(dict(component='literal_binding',window_id=window.id,
                                     binding_id=claim.get('binding_id'),reason=str(error)))
        if len({r['id'] for r in proposed})!=len(proposed):
            failures.append(dict(component='reading_schema',window_id=window.id,reason='duplicate_claim_ids'))
            proposed=list({r['id']:r for r in proposed}.values())
        state=dict(source=_source_state(window),items=[dict(id=r['id'],binding=r['binding']) for r in proposed])
        verify=contract.verification_request('source_verification',state,proposed,
            dict(source_request=request.fingerprint),source=True)
        findings=contract.judgments(send(verify),verify) if verify else {}
        for row in proposed:
            row['field_judgments']=findings.get(row['id'],{})
            ok,reason=EvidencePolicy().permits(row)
            row['experimental_eligibility']='supported' if ok else 'withheld'
            row['withheld_reason']=reason
            observations.append(row)
    raw_observations=json.loads(json.dumps(observations))
    supported={r['id']:r for r in observations if EvidencePolicy().permits(r)[0]}
    assignment_outputs=[];hypotheses=[];hypothesis_checks={}; relation_measurements=[]
    source_index={r['id']:dict(id=r['id'],proposition=r['binding']['proposition']['reading'],
        voice={k:r['binding']['voice'][k] for k in ('kind','speaker','occurrence')},
        adoption={k:r['binding']['adoption'][k] for k in ('status','basis')},polarity=r['binding']['polarity']['value'],
        conditions=[dict(kind=c['kind'],text=c['span']['text']) for c in r['binding']['conditions']],
        scope=r['binding']['scope']['reading'],
        supported=r['id'] in supported) for r in observations}
    for source in packet['source_refs']:
        vid=source['video_id']
        target_rows=[r for r in observations if any(ref['video_id']==vid for ref in r['source_refs'])]
        if not target_rows: continue
        state=dict(items=[dict(id=r['id'],binding=r['binding'],supported=r['id'] in supported) for r in target_rows],
            sources=[_source_state(w) for w in windows.values() if w.video_id==vid],
            qualified_claim_index=list(source_index.values()),dimension_roots=list(ROOTS))
        request=contract.generation_request('alignment_and_interpretation',state,
            dict(recording=vid,source_readings=digest(source_index),dimension_policy='hierarchy-unique-feature-v1'))
        generated=contract.generated_output(request.phase,send(request))
        assignments=generated['assignments']
        target_ids={r['id'] for r in target_rows}
        if len({r['observation_id'] for r in assignments})!=len(assignments) or {r['observation_id'] for r in assignments}!=target_ids:
            failures.append(dict(component='alignment',video_id=vid,reason='missing_or_foreign_assignment')); continue
        proposals=[dict(r,id=r['observation_id']) for r in assignments]+generated['hypotheses']+generated['relation_assessments']
        if len({p['id'] for p in proposals})!=len(proposals):
            raise ValueError('Duplicate downstream item IDs; no repairs')
        verify_state=dict(source_state={k:v for k,v in state.items() if k!='qualified_claim_index'},items=proposals)
        external={key for h in generated['hypotheses'] for key in h['premise_ids']+h['counterevidence_ids']} - target_ids
        verify_state['external_premises']=[dict(id=r['id'],binding=r['binding']) for r in observations if r['id'] in external]
        verify=contract.verification_request('downstream_verification',verify_state,proposals,
            dict(generation_request=request.fingerprint))
        findings=contract.judgments(send(verify),verify) if verify else {}
        assignment_outputs.append(dict(video_id=vid,first=generated,field_judgments=findings))
        for assignment in assignments:
            row=next(r for r in target_rows if r['id']==assignment['observation_id'])
            checks=findings.get(row['id'],{})
            row['alignment']=dict(meaning=assignment['meaning'],paths=assignment['paths'],
                resolved=assignment['resolved'] and _checks_pass(checks),
                probability=min((v['probability'] for v in checks.values()),default=0),
                evidence=assignment['evidence'],field_judgments=checks)
            if not set(assignment['evidence']) <= target_ids or not assignment['evidence']:
                row['alignment']['resolved']=False
        hypotheses.extend(generated['hypotheses']);hypothesis_checks.update(findings)
        by_id={r['id']:r for r in target_rows}
        from .pastor_fingerprint import qualified_key
        for relation in generated['relation_assessments']:
            from .theological_binding import RELATIONS, ADOPTION
            if (relation['kind'] not in RELATIONS or relation['source_voice'] not in ('preacher','quoted_or_reported','unresolved')
                or relation['adoption'] not in ADOPTION or not relation['scope']):
                raise ValueError('Unsupported relation meaning/attribution')
            ends=[by_id.get(relation[k]) for k in ('from_id','to_id')]
            if (not _checks_pass(findings.get(relation['id'],{})) or any(r is None or
                r['id'] not in supported or not r.get('alignment',{}).get('resolved') for r in ends)
                or not relation['evidence_ids'] or not set(relation['evidence_ids'])<=target_ids):
                continue
            meaning=dict(from_frame=qualified_key(ends[0]['alignment']['meaning']),
                to_frame=qualified_key(ends[1]['alignment']['meaning']),kind=relation['kind'],
                source_voice=relation['source_voice'],adoption=relation['adoption'],scope=relation['scope'])
            relation_measurements.append(dict(id='relation:'+digest(meaning),operator='relation',
                estimand='explicitly_assessed_matched_endpoint_presence',contract=contract.VERSION,
                video_id=vid,value=int(relation['present']),numerator=int(relation['present']),denominator=1,
                assessed=True,unit='qualified_endpoint_pair',exposure=dict(video_id=vid,windows=[w.id for w in windows.values() if w.video_id==vid]),
                paths=relation['paths'],source_refs=[ref for r in ends for ref in r['source_refs']],meaning=meaning,
                field_judgments=findings[relation['id']]))
    measurements=packet['measurements']+relation_measurements
    samples=[SampleSpec(**{**s,'video_ids':tuple(s['video_ids']),'input_run_ids':tuple(s['input_run_ids'])}) for s in packet['samples']]
    def build(samples,rows,values):
        return [build_fingerprint(sample,EvidenceView(tuple(r for r in rows if any(
            ref['video_id'] in sample.video_ids for ref in r['source_refs']))),
            measurements=[v for v in values if v['video_id'] in sample.video_ids]) for sample in samples]
    fingerprints=build(samples,observations,measurements)
    comparisons={path:compare_fingerprints(*fingerprints,ComparisonSpec(path=path))
                 for path in sorted(set().union(*(fp['dimension_views'] for fp in fingerprints)))}
    # Hypotheses require source verification AND verified automatic meaning/assignment.
    eligible={r['id']:r for r in observations if r['id'] in supported and r.get('alignment',{}).get('resolved')}
    interpreted=generated_hypotheses(hypotheses,eligible,hypothesis_checks)
    entries=_entries(fingerprints,list(eligible.values()),interpreted['accepted'])
    narratives=[]
    scopes=[list(sample.video_ids) for sample in samples]+[sorted(v for s in samples for v in s.video_ids)]
    for number,scope in enumerate(scopes):
        local={key:value for key,value in entries.items() if set(value['scope_video_ids'])<=set(scope)}
        if number==2:
            for path,value in comparisons.items():
                local['comparison:'+path]=_comparison_entry(value,scope)
        state=dict(entries=local,scope_video_ids=scope,kind='pair' if number==2 else 'profile')
        request=contract.generation_request('narratives_and_pair_report',state,dict(entries_digest=digest(local)))
        proposal=contract.generated_output(request.phase,send(request))
        if len({r['id'] for r in proposal['clauses']})!=len(proposal['clauses']): raise ValueError('Duplicate clause IDs')
        verify=contract.verification_request('downstream_verification',dict(entries=dependency_entries(local,{key for clause in proposal['clauses'] for key in clause['entry_ids']}),items=proposal['clauses']),
            proposal['clauses'],dict(generation_request=request.fingerprint))
        findings=contract.judgments(send(verify),verify) if verify else {}
        narratives.append(dict(scope_video_ids=scope,entries=local,field_judgments=findings,
            **generated_narrative(proposal,local,findings)))
    omissions=[]
    for sample in samples:
        for video_id in sample.video_ids:
            reduced=[replace(s,video_ids=tuple(v for v in s.video_ids if v!=video_id)) if s==sample else s for s in samples]
            remaining=[r for r in observations if all(ref['video_id']!=video_id for ref in r['source_refs'])]
            remaining_values=[v for v in measurements if v['video_id']!=video_id]
            rebuilt=build(reduced,remaining,remaining_values)
            eligible_remaining={r['id']:r for r in remaining if r['id'] in eligible}
            hypo=generated_hypotheses(hypotheses,eligible_remaining,hypothesis_checks,omitted_video_id=video_id)
            view_entries=_entries(rebuilt,list(eligible_remaining.values()),hypo['accepted'])
            omission_narratives=[]
            for narrative in narratives:
                # Pair clauses depend on frozen numerical masks; recomputation produces
                # new comparison entries, so old pair prose is withheld without a call.
                scoped={key:entry for key,entry in view_entries.items()
                        if set(entry['scope_video_ids'])<=set(narrative['scope_video_ids'])}
                omission_narratives.append(generated_narrative(narrative['first'],scoped,
                    narrative['field_judgments'],omitted_video_id=video_id))
            omissions.append(dict(omitted_video_id=video_id,fingerprints=rebuilt,hypotheses=hypo,
                comparisons={path:compare_fingerprints(*rebuilt,ComparisonSpec(path=path)) for path in comparisons},
                narratives=omission_narratives))
    attempts=store.attempts()
    result=dict(schema_version='learning-demo-run-v1',input_fingerprint=packet['input_fingerprint'],
        status='FAIL(component)' if failures else 'INCONCLUSIVE',
        decision_reason='Structural/component failures require source audit' if failures else 'Independent semantic/reference audit pending; offline success cannot establish PASS',
        raw_readings=reading_outputs,raw_observations=raw_observations,observations=observations,
        assignments=assignment_outputs,fingerprints=fingerprints,comparisons=comparisons,
        hypotheses=interpreted,narratives=narratives,omission_views=omissions,failures=failures,
        accounting=usage_account(store),
        evaluation=dict(status='PENDING_BLINDED_SOURCE_AUDIT',family_coverage='reference-dependent; no completeness claim',
            verification_bias='not estimable without blinded reference matches',human_effort=dict(
                reference_preparation_minutes=None,evaluation_minutes=None,brian_minutes=None,
                runtime_intervention_minutes=0,release_validation_minutes=None),
            source_strata=dict(Counter(w.stratum for w in windows.values()))))
    store.write_immutable('results.json',result)
    return result


def require_execution(packet,approve_input,experimental,max_usd,confirm_proposal_prices):
    if approve_input!=packet['input_fingerprint'] or experimental is not True:
        raise ValueError('Separate M5 decision requires --experimental and --approve-input exact fingerprint')
    if Decimal(str(max_usd))!=Decimal('2.00') or confirm_proposal_prices is not True:
        raise ValueError('Confirm unchanged proposal prices and exact $2 ceiling before M5')
    return dict(schema_version='learning-demo-execution-decision-v1',input_fingerprint=approve_input,
        decision='explicit_cli_M5_execution',experimental=True,max_attempts=66,max_usd='2.00',
        proposal_prices_confirmed=True,retries=0,production_admission=False)


def run(input_path,base_dir=None,*,approve_input=None,experimental=False,max_usd='2.00',
        confirm_proposal_prices=False,check_only=False):
    # No transport, credential checks or attempt files during provider-free preflight.
    packet,encoding=verify_input(input_path,base_dir)
    if check_only:
        return dict(status='PREPARED_NO_EXECUTION',input_fingerprint=packet['input_fingerprint'],
                    provider_calls=0,budget=packet['budget'],prerequisites=packet['prerequisites'])
    decision=require_execution(packet,approve_input,experimental,max_usd,confirm_proposal_prices)
    if not all(os.environ.get(name) for name in ('OPENAI_API_KEY','TYPESAFE_API_KEY')):
        raise ValueError('Both provider credentials required; no attempts started')
    store=ReceiptStore(Path(input_path).parent/'execution')
    store.write_immutable('authorization.json',decision)
    def transport(spec):
        return (openai_transport if PHASES[spec.phase][0]=='OpenAI' else typesafe_transport)(spec)
    try:
        return execute_pipeline(packet,store,transport,encoding=encoding)
    except (ValueError,OSError,KeyError,TypeError) as error:
        # Technical failures are not semantic source insufficiency; never purchase a repair.
        failure=dict(status='FAIL(component)',component='execution_or_contract_fit',reason=str(error),
            input_fingerprint=packet['input_fingerprint'],attempts=len(store.attempts()),
            production_admission=False,next_step='Inspect preserved receipts; no retry, variant or added batches')
        store.write_immutable('stopped-'+digest(failure)+'.json',failure)
        return failure


def source_stratum_report(observations,profile_ids=()):
    groups=defaultdict(lambda:dict(raw=set(),supported=set(),aligned=set(),anchor_origin=set(),families=defaultdict(set)))
    for profile_id in profile_ids:
        for stratum in ('detector_selected','independent_control'): groups[(profile_id,stratum)]
    for row in observations:
        for ref in row['source_refs']:
            group=groups[(ref.get('profile_id'),ref['stratum'])]
            # Profiles supplied separately in report(); canonical source occurrence key
            # counts window overlap without pretending repeated readings are independent.
            key=digest({k:ref[k] for k in ('video_id','block_id','target_sha256','local_start','local_end')})
            group['raw'].add(key)
            if ref['block_id']==ref['anchor_block_id']: group['anchor_origin'].add(key)
            if EvidencePolicy().permits(row)[0]: group['supported'].add(key)
            if row.get('alignment',{}).get('resolved'):
                group['aligned'].add(key)
                for path in row['alignment']['paths']:
                    group['families'][path].add(key)
    return [dict(profile_id=p,stratum=s,**{k:len(v) for k,v in g.items() if k!='families'},
        families={k:len(v) for k,v in sorted(g['families'].items())},
        limit='literal occurrence counts; source-reference recall/accuracy and control-only new-content audit pending')
        for (p,s),g in sorted(groups.items(),key=str)]


def _interval(n,d):
    if not d: return None
    import math
    z=1.959963984540054;p=n/d;den=1+z*z/d
    mid=(p+z*z/(2*d))/den
    spread=z*math.sqrt(p*(1-p)/d+z*z/(4*d*d))/den
    return [max(0,mid-spread),min(1,mid+spread)]


def verification_bias(reference_rows,matches,accepted_ids):
    """Offline audit only: complexity/family tags come from blinded references.

    matches are audited all-field correspondences, never the generator's own labels.
    Multiple windows matching one reference do not enlarge the reference denominator.
    """
    accepted_ids=set(accepted_ids)
    correct=defaultdict(set)
    incorrect=set();false_accepted=set()
    for row in matches:
        if row['correct']: correct[row['reference_id']].add(row['observation_id'])
        else:
            incorrect.add(row['observation_id'])
            if row['observation_id'] in accepted_ids: false_accepted.add(row['observation_id'])
    groups=defaultdict(set); refs={r['id']:r for r in reference_rows if r['adjudicable']}
    if len(refs)!=sum(bool(r['adjudicable']) for r in reference_rows): raise ValueError('Duplicate reference IDs')
    for key,row in refs.items():
        groups[('pooled','all')].add(key)
        for field in ('profile','stratum','theological_family'):
            groups[(field,str(row[field]))].add(key)
        for tag in ('conditional_qualified','indirect','multi_sentence','biblical_interpretation_dependent','nuanced_contested'):
            groups[('complexity',tag if tag in row['complexity_tags'] else 'other:'+tag)].add(key)
        for tag in row['complexity_tags']:
            groups[('profile_stratum_family_complexity',f"{row['profile']}|{row['stratum']}|{row['theological_family']}|{tag}")].add(key)
    rows=[]
    for (kind,label),ids in sorted(groups.items()):
        generated={key for key in ids if correct[key]}
        retained={key for key in generated if correct[key] & accepted_ids}
        r,g,k=len(ids),len(generated),len(retained)
        rows.append(dict(group_type=kind,group=label,reference_adjudicable=r,correct_generated=g,correct_retained=k,
            generator_recall=g/r if r else None,correct_retention=k/g if g else None,
            false_rejection=1-k/g if g else None,final_correct_coverage=k/r if r else None,
            retention_interval=_interval(k,g),recall_interval=_interval(g,r),
            powered=g>=5,verifier_yield_fail=g>=5 and k/g<.60,
            uncovered_family=kind=='theological_family' and r>0 and k==0))
    gaps=[]
    by_group={(r['group_type'],r['group']):r for r in rows}
    for (kind,label),row in by_group.items():
        if kind!='complexity' or label.startswith('other:'): continue
        other=by_group.get(('complexity','other:'+label))
        if not other or row['correct_retention'] is None or other['correct_retention'] is None: continue
        gap=other['correct_retention']-row['correct_retention']
        gaps.append(dict(group=label,retention_gap=gap,powered=row['powered'] and other['powered'],
                         selective_loss_concern=gap>.20,causal_bias_established=False))
    return dict(groups=rows,gaps=gaps,incorrect_generated=len(incorrect),erroneously_accepted=len(false_accepted),
        accepted_observations=len(accepted_ids),semantic_accuracy=(len(accepted_ids-false_accepted)/len(accepted_ids))
            if accepted_ids and accepted_ids <= false_accepted | {x for values in correct.values() for x in values} else None,
        dependence_warning='Nonexclusive reference groups and overlapping source windows are dependent; intervals are descriptive.')


def decide_outcome(checks,*,audit_complete=False):
    failed=[r['component'] for r in checks if r.get('adequate_evidence') and r.get('passed') is False]
    if failed: return dict(status='FAIL(component)',components=failed)
    if not audit_complete or not checks or any(r.get('passed') is not True or not r.get('adequate_evidence') for r in checks):
        return dict(status='INCONCLUSIVE',reason='Incomplete or insufficient independent source/reference evidence')
    required={'grounding','semantic_fidelity','discovery','verification_yield','alignment','theological_content',
              'interpretation','narrative','usefulness','sample_dependence','effort','budget','mathematics','verification_bias'}
    if {r['component'] for r in checks}!=required:
        return dict(status='INCONCLUSIVE',reason='Missing required acceptance components')
    return dict(status='PASS',components=sorted(required))


def report(run_dir,*,audit=None,base_dir=None):
    run_dir=Path(run_dir)
    packet=json.loads((run_dir/'input.json').read_text())
    if run_dir.resolve()!=_run_directory(base_dir,packet['input_fingerprint']).resolve():
        raise ValueError('Report directory must be under configured application base')
    result_path=run_dir/'execution/results.json'
    if not result_path.exists():
        execution=ReceiptStore(run_dir/'execution')
        if execution.root.exists() and execution.attempts():
            stops=sorted(execution.root.glob('stopped-*.json'))
            return dict(status='FAIL(component)',component='execution_incomplete',
                accounting=usage_account(execution),stops=[json.loads(p.read_text()) for p in stops],
                input_fingerprint=packet['input_fingerprint'],semantic_outcome='NOT_EVALUATED')
        return dict(status='PREPARED_NO_EXECUTION',input_fingerprint=packet['input_fingerprint'],
            coverage=packet['coverage'],budget=packet['budget'],provider_calls=0,
            prerequisites=packet['prerequisites'],semantic_outcome='NOT_EVALUATED')
    result=json.loads(result_path.read_text())
    profile_by_video={v:s['profile_id'] for s in packet['samples'] for v in s['video_ids']}
    rows=json.loads(json.dumps(result['observations']))
    for row in rows:
        for ref in row['source_refs']: ref['profile_id']=profile_by_video[ref['video_id']]
    value=dict(input_fingerprint=packet['input_fingerprint'],outcome=dict(status=result['status'],reason=result['decision_reason']),
        accounting=result['accounting'],source_strata=source_stratum_report(rows,[s['profile_id'] for s in packet['samples']]),
        human_effort=result['evaluation']['human_effort'],source_coverage=packet['coverage'],
        semantic_audit='PENDING',verification_bias=None)
    if audit is not None:
        if audit['input_fingerprint']!=packet['input_fingerprint']: raise ValueError('Foreign audit')
        value['verification_bias']=verification_bias(audit['references'],audit['matches'],
            [r['id'] for r in rows if EvidencePolicy().permits(r)[0]])
        value['outcome']=decide_outcome(audit['component_checks'],audit_complete=audit['complete'])
        value['semantic_audit']='COMPLETE' if audit['complete'] else 'INCOMPLETE'
        value['human_effort']=audit['human_effort']
        effort=audit['human_effort']
        total=sum(effort.get(k,0) or 0 for k in ('reference_preparation_minutes','evaluation_minutes','brian_minutes','release_validation_minutes'))
        if effort.get('runtime_intervention_minutes',0)>0 or total>360 or effort.get('brian_minutes',0)>20:
            value['outcome']=dict(status='FAIL(component)',components=['effort'])
        if result['failures']:
            value['outcome']=dict(status='FAIL(component)',components=sorted({r['component'] for r in result['failures']}))
        if any(r['verifier_yield_fail'] for r in value['verification_bias']['groups']):
            value['outcome']=dict(status='FAIL(component)',components=['verification_yield'])
    from .analysis_artifact_cache import write_json_markdown
    destination=run_dir/'reports'/digest(value)/'report.json'
    write_json_markdown(destination,value,'# V3 demonstration report\n\n'+
        json.dumps(value,indent=2,ensure_ascii=False)+'\n')
    return value
