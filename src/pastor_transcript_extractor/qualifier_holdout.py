"""Fixed neutral holdout for the frozen independent qualifier contract.

Expected roles and evidence markers are evaluation-only, never model inputs.
"""
from copy import deepcopy
from dataclasses import asdict
import json
from . import reference_field_validation as existing
from . import qualification_verification as qualifiers
from . import source_passages

VERSION='qualifier-transfer-holdout-v1'
SAVED_QWEN_COMPARISON='2ea817b2445b19590758427495fd0528a4c7e16afcc666ffb26c8e978e0f575a'
TEMPLATE='dc5946c16f201b83ff8d949528f22a8c67d4dd539e1936a4784693376fdaa6d4'


def cases():
    def card(source,point,concession=False,uncertainty=False,markers=None,family=''):
        return dict(source=source,proposition=dict(reading=point),expected_roles=dict(concession=concession,expressed_uncertainty=uncertainty),markers=markers or {},family=family)
    rows=[
        card("The bowl is chipped. That hasn't stopped it from holding water.",'The bowl holds water despite being chipped.',concession=True,markers={'concession':'The bowl is chipped.'},family='indirect_concession'),
        card("Don't rely on my recollection: I think the rehearsal began at six.",'The rehearsal began at six, according to an uncertain recollection.',uncertainty=True,markers={'expressed_uncertainty':"Don't rely on my recollection"},family='source_self_doubt'),
        card('The clerk read the note: "To the best of my knowledge, the parcel arrived." She did not say whether she agreed.','The note says the parcel arrived, limited to its author\'s knowledge.',uncertainty=True,markers={'expressed_uncertainty':'To the best of my knowledge'},family='reported_hedge'),
        card('The courier will depart only after the pass is signed.','The courier will depart only after the pass is signed.',family='prerequisite_condition'),
        card('Even though rain is falling, we will start the walk. The oven is off.','The oven is off.',family='unrelated_nearby_concession'),
        card('I cannot remember where my keys are. The driver said, "The bridge reopened at noon."','The bridge reopened at noon.',family='other_voice_other_topic_uncertainty'),
        card('The repaired seam looks rough. Even so, I think it will hold; I have not tested it.','The seam will likely hold despite its rough appearance, but this is untested.',concession=True,uncertainty=True,markers={'concession':'seam looks rough','expressed_uncertainty':'I think'},family='cooccurring_roles'),
        card('The engineer said, "There is no doubt that the pump is running." I am merely quoting her.','The engineer states with certainty that the pump is running.',family='negated_uncertainty'),
        card('It is not true that the cracked lens still works. It no longer focuses.','The cracked lens no longer focuses.',family='negated_concession'),
        card('The announcer said, "Mara told me, \'I might have misread the timetable; the train is due at four.\'" The announcer did not endorse the estimate.','Mara estimates that the train is due at four but may have misread the timetable.',uncertainty=True,markers={'expressed_uncertainty':'might have misread the timetable'},family='nested_quotation'),
        card('The room is small, but it accommodates the entire group.','The room accommodates the group despite being small.',concession=True,markers={'concession':'The room is small'},family='direct_concession'),
        card('[Recording starts mid-sentence.] ...but whether she... [inaudible].','Ada believes the reservoir is safe.',concession=None,uncertainty=None,family='unrecoverable_target'),
    ]
    return sorted(rows,key=lambda c:existing.digest(dict(source=c['source'],proposition=c['proposition'])))


def trial_body(template_body):
    """Retain the frozen system question verbatim; change only test state/schema."""
    rows=cases();state={};windows={};index={};properties={}
    for n,case in enumerate(rows):
        key='q'+str(n);text=case['source']
        window=existing.evidence.SourceWindow(key,0,0,existing.digest(text),0,(dict(block_id=0,target_text=text,start_seconds=0,end_seconds=60,segment_indexes=[0]),),'synthetic_holdout')
        state[key]=qualifiers.selection_item(window,case['proposition']);windows[key]=json.loads(existing.requests.wire(asdict(window)))
        index[key]=dict(expected_roles=case['expected_roles'],markers=case['markers'],family=case['family'])
        ids=[u['id'] for u in state[key]['source']['units']]
        ranges=dict(type=['array','null'],items=dict(type='object',properties=dict(start_unit=dict(type='string',enum=ids),end_unit=dict(type='string',enum=ids)),required=['start_unit','end_unit'],additionalProperties=False),maxItems=8)
        properties[key]=dict(type='object',properties={role:deepcopy(ranges) for role in ('concession','expressed_uncertainty')},required=['concession','expressed_uncertainty'],additionalProperties=False)
    body=deepcopy(template_body);body['messages'][1]['content']=existing.requests.wire(state)
    body['response_format']['json_schema']['schema']=dict(type='object',properties=properties,required=list(properties),additionalProperties=False)
    return body,dict(state=state,windows=windows,audit_index=index)


def assess(spec,trial,response):
    existing.requests.validate_response(spec,response);output=existing.requests.strict_json(response['output'])
    if not isinstance(output,dict) or set(output)!=set(trial['state']):raise ValueError('Holdout answer inventory differs')
    rows=[]
    for key,item in trial['state'].items():
        catalog=qualifiers.compile_atomic_selection(existing.evidence.SourceWindow(**trial['windows'][key]),item['proposition'],output[key]);audit=trial['audit_index'][key];decisions=[]
        for role,expected in audit['expected_roles'].items():
            prediction=None if role in catalog['unresolved_roles'] else any(n['kind']==role for n in catalog['nodes'])
            marker=audit['markers'].get(role)
            covered=None if not marker else any(marker in n['span']['text'] for n in catalog['nodes'] if n['kind']==role)
            outcome='CORRECT' if prediction is expected else 'WITHHELD' if prediction is None else 'WRONG'
            if prediction is True and marker and not covered:outcome='WRONG'
            decisions.append(dict(role=role,expected=expected,prediction=prediction,evidence_marker_covered=covered,outcome=outcome))
        outcome='WRONG' if any(d['outcome']=='WRONG' for d in decisions) else 'WITHHELD' if any(d['outcome']=='WITHHELD' for d in decisions) else 'CORRECT'
        rows.append(dict(key=key,family=audit['family'],decisions=decisions,outcome=outcome,catalog=catalog))
    decisions=[d for r in rows for d in r['decisions']]
    summary=dict(cases=len(rows),cases_correct=sum(r['outcome']=='CORRECT' for r in rows),cases_wrong=sum(r['outcome']=='WRONG' for r in rows),cases_withheld=sum(r['outcome']=='WITHHELD' for r in rows),roles=len(decisions),roles_correct=sum(d['outcome']=='CORRECT' for d in decisions),roles_wrong=sum(d['outcome']=='WRONG' for d in decisions),roles_withheld=sum(d['outcome']=='WITHHELD' for d in decisions),roles_abstained=sum(d['prediction'] is None for d in decisions),evidence_errors=sum(d['prediction'] is True and d['evidence_marker_covered'] is False for d in decisions),false_positive=sum(d['expected'] is False and d['prediction'] is True for d in decisions),false_negative=sum(d['expected'] is True and d['prediction'] is False for d in decisions),missed_required_abstention=sum(d['expected'] is None and d['prediction'] is not None for d in decisions))
    summary.update(total=summary['cases'],correct=summary['cases_correct'],wrong=summary['cases_wrong'],withheld=summary['cases_withheld'])
    summary['by_reference']={name:dict(total=sum(d['expected'] is expected for d in decisions),correct=sum(d['expected'] is expected and d['outcome']=='CORRECT' for d in decisions),withheld=sum(d['expected'] is expected and d['prediction'] is None for d in decisions)) for name,expected in [('positive',True),('negative',False),('unrecoverable',None)]}
    return dict(rows=rows,summary=summary,production_admission=False)


PAIRS={'qwen':('qualifier-holdout-qwen35-v1','qualifier-holdout-qwen38-v1'),
       'flash':('qualifier-holdout-qwen38-v1','qualifier-holdout-flash1017-v1')}


def selection(base_dir=None,*,check_only=False):
    template_path=existing.directory(base_dir,TEMPLATE)/'input.json';template=existing.integration.polarity.trial.frozen(template_path)
    if template.get('qualifier_decision_version')!=qualifiers.ATOMIC_VERSION:raise ValueError('Frozen qualifier question contract version differs')
    body,trial=trial_body(template['request']['body']);body.pop('model')
    packet=dict(version=VERSION,body_without_model=body,trial=trial,reference_authority='Predeclared Codex-authored neutral controls; not independently human-adjudicated pastor judgments',template=dict(path=str(template_path),sha256=existing.check.demo.file_hash(template_path),prompt_digest=existing.digest(body['messages'][0])),policy=dict(retries=0,tuning_after_results=False,production_admission=False))
    packet['input_fingerprint']=existing.digest(packet)
    out=existing.check.demo.build_paths(base_dir).evaluation/VERSION/packet['input_fingerprint']
    if not check_only:existing.Store(out).write_immutable('selection.json',packet)
    return packet,out


def saved_qwen_run(base_dir,spec,selected):
    """Reuse the pinned comparison's exact constituent, preserving its original spend."""
    parent=existing.directory(base_dir,SAVED_QWEN_COMPARISON)
    path=parent/'input.json'
    if not path.exists():return None
    original=existing.integration.polarity.trial.frozen(path)
    if original['selection']!=selected:raise ValueError('Saved holdout selection differs')
    matches=[r for r in original['runs'] if r['request']==asdict(spec)]
    if len(matches)!=1:raise ValueError('Saved holdout request differs')
    comparison_path=parent/'comparison.json';comparison=json.loads(comparison_path.read_text())
    if comparison['input_fingerprint']!=original['input_fingerprint']:raise ValueError('Foreign saved comparison')
    fingerprint=existing.digest(dict(pair=original['input_fingerprint'],request=spec.fingerprint))
    child=parent.parent/fingerprint;result_path=child/'execution/results.json'
    record=next(r for r in comparison['runs'] if r['model']==spec.body['model'])
    input_path=child/'input.json';prior=json.loads(input_path.read_text());result=json.loads(result_path.read_text())
    receipt_path=child/'execution/receipts'/f'{spec.fingerprint}.json'
    wire_path=child/'execution/wire-responses'/f'{spec.fingerprint}.json'
    receipt=json.loads(receipt_path.read_text());wire=json.loads(wire_path.read_text())
    if (prior['input_fingerprint']!=fingerprint or prior['request']!=asdict(spec) or prior['native_trial']!=selected['trial']
        or result['input_fingerprint']!=fingerprint or record['result']!=result or record['results']!=str(result_path)
        or result['halt'] or result['contract_fit']!='PASS' or result['production_admission']):
        raise ValueError('Saved holdout result provenance differs')
    if (receipt['request']!=asdict(spec) or receipt['halt'] or receipt['token_account']!=spec.preflight()
        or receipt['response_digest']!=existing.digest(receipt['response']) or receipt['wire_response_digest']!=existing.digest(wire)
        or existing.requests.decode_response(spec,existing.requests.WireResponse(**wire))!=receipt['response']):
        raise ValueError('Saved holdout receipt differs')
    rebuilt=assess(spec,prior['native_trial'],receipt['response'])
    # JSON key ordering may reorder q10/q2; match case rows by their stable keys.
    def canonical(value):return dict(value,rows=sorted(value['rows'],key=lambda row:row['key']))
    if canonical(rebuilt)!=canonical(result['assessment']):raise ValueError('Saved holdout assessment differs')
    usage=existing.check.demo.usage_account(existing.requests.ReceiptStore(child/'execution'))
    if any(result['accounting'].get(k)!=v for k,v in usage.items()):raise ValueError('Saved holdout accounting differs')
    return dict(record=record,preserved_files={str(p):existing.check.demo.file_hash(p) for p in (path,comparison_path,input_path,result_path,receipt_path,wire_path)})


def validate_reuse(reuse):
    if any(existing.check.demo.file_hash(existing.Path(p))!=sha for p,sha in reuse['preserved_files'].items()):
        raise ValueError('Saved holdout reuse changed after freeze')
    return dict(reuse['record'],cache_reuse=True,elapsed_seconds=None,original_elapsed_seconds=reuse['record']['elapsed_seconds'])


def prepare(base_dir=None,*,pair,check_only=False):
    from dataclasses import asdict
    from . import deepinfra_requests as hosted
    if pair not in PAIRS:raise ValueError('Use pair qwen or flash')
    selected,selected_dir=selection(base_dir,check_only=check_only);runs=[]
    for version in PAIRS[pair]:
        policy=hosted.policy_for(version);body=dict(deepcopy(selected['body_without_model']),model=policy['model'])
        spec=existing.requests.RequestSpec('source_reading',body,dict(selection_fingerprint=selected['input_fingerprint'],contract=qualifiers.ATOMIC_VERSION),namespace=version,version=version,runtime_identity=deepcopy(policy))
        metadata=hosted.public_model_metadata(policy['model'])
        if 'structured-output' not in metadata['capabilities'] or metadata['context']<policy['input_cap']+policy['output_cap']:raise ValueError('Selected model lacks required schema/context metadata')
        if (existing.Decimal(metadata['input_cents_per_token'])*10000>existing.Decimal(policy['input_usd_per_million']) or existing.Decimal(metadata['output_cents_per_token'])*10000>existing.Decimal(policy['output_usd_per_million'])):raise ValueError('Model price exceeds frozen non-promotional reservation')
        run=dict(request=asdict(spec),token_account=spec.preflight(),model_metadata=metadata)
        if pair=='flash' and version=='qualifier-holdout-qwen38-v1':
            reuse=saved_qwen_run(base_dir,spec,selected)
            if reuse is not None:run['reuse']=reuse
        runs.append(run)
    common=[{k:v for k,v in r['request']['body'].items() if k!='model'} for r in runs]
    if common[0]!=common[1]:raise ValueError('Paired requests differ beyond model selection')
    reserve=sum((hosted.reserved_usd(r['request']['version']) for r in runs if 'reuse' not in r),existing.Decimal(0))
    packet=dict(version=VERSION,pair=pair,selection=selected,runs=runs,budget=dict(max_usd='.06',maximum_paid_attempts=sum('reuse' not in r for r in runs),reserved_usd=str(reserve),spend_root=str(existing.check.demo.build_paths(base_dir).evaluation/'qualified-observations'),cumulative_ceiling_usd='1'),
        policy=dict(reasoning_effort='none',retries=0,automatic_expansion=False,production_admission=False),common_body_digest=existing.digest(common[0]),
        code_identity={m.__name__:existing.check.demo.file_hash(existing.Path(m.__file__)) for m in (existing,existing.requests,hosted,existing.integration,qualifiers,source_passages)},adapter_sha256=existing.check.demo.file_hash(existing.Path(__file__)))
    packet['input_fingerprint']=existing.digest(packet);out=existing.directory(base_dir,packet['input_fingerprint'])
    if not check_only:existing.Store(out).write_immutable('input.json',packet)
    return packet,out


def run_recipe(packet,parent,transport,*,progress=None):
    from time import monotonic
    from . import deepinfra_requests as hosted
    parent=existing.Path(parent)
    if (parent/'comparison.json').exists():
        saved=json.loads((parent/'comparison.json').read_text())
        if saved['input_fingerprint']!=packet['input_fingerprint']:raise ValueError('Foreign comparison result')
        return saved
    # Reserve all new planned requests against the shared cumulative ceiling before any send.
    with existing.integration.cumulative_history(packet,parent/'preflight') as history:
        prior=existing.integration.BASELINE_SPEND+sum((v for _,v in history),existing.Decimal(0))
        if prior+existing.Decimal(packet['budget']['reserved_usd'])>=1:raise ValueError('Both requests must fit under cumulative $1 ceiling')
    results=[]
    for run in packet['runs']:
        if 'reuse' in run:
            result=validate_reuse(run['reuse'])
            if progress:progress('Reusing saved '+result['model']+': exact frozen request and receipt; no new call')
            results.append(result)
            continue
        spec=existing.requests.RequestSpec(**run['request']);fingerprint=existing.digest(dict(pair=packet['input_fingerprint'],request=spec.fingerprint))
        out=parent.parent/fingerprint
        child=dict(input_fingerprint=fingerprint,request=run['request'],native_trial=packet['selection']['trial'],baseline=dict(selection_fingerprint=packet['selection']['input_fingerprint']),budget=dict(packet['budget'],maximum_paid_attempts=1,max_usd=hosted.policy_for(spec.version)['maximum_usd'],reserved_usd=str(hosted.reserved_usd(spec.version))),policy=dict(packet['policy'],model=spec.body['model']),limitation='Fixed neutral holdout: identical prompt, input, schema and instant decoding across two models. References are evaluation-only; no post-result tuning or admission.')
        if progress:progress('Starting '+spec.body['model']+': same frozen 12 cases, thinking disabled, one attempt')
        existing.Store(out).write_immutable('input.json',child);cached=(out/'execution/results.json').exists();started=monotonic()
        result=existing.qwen_recipe(child,out/'execution',transport,assessor=lambda c,r:assess(existing.requests.RequestSpec(**c['request']),c['native_trial'],r))
        if progress:progress('Completed '+spec.body['model']+': '+result['status'])
        results.append(dict(model=spec.body['model'],result=result,results=str(out/'execution/results.json'),elapsed_seconds=None if cached else round(monotonic()-started,3),cache_reuse=cached))
    failed=any(r['result']['contract_fit']!='PASS' or (r['result']['assessment'] or {}).get('summary',{}).get('wrong',0) for r in results)
    withheld=any((r['result']['assessment'] or {}).get('summary',{}).get('withheld',0) for r in results)
    report=dict(input_fingerprint=packet['input_fingerprint'],selection_fingerprint=packet['selection']['input_fingerprint'],status='FAIL(component)' if failed else 'INCONCLUSIVE',bounded_control_fit='FAIL(component)' if failed else 'INCONCLUSIVE' if withheld else 'PASS',runs=results,production_admission=False,
        limitation='One fixed synthetic holdout, one batch per model. Reference role labels are Codex authored, not independent human accuracy evidence. Timing is one client wall-clock observation, not throughput or latency statistics. Unknown usage remains reserved. No tuning, retries or automatic advancement.',next_step='Review every held-out error and abstention; preserve this as validation rather than tuning and relabeling a rerun.')
    existing.Store(parent).write_immutable('comparison.json',report)
    (parent/'report.md').write_text('# Frozen two-model qualifier holdout\n\n'+report['limitation']+'\n\n'+json.dumps([dict(model=r['model'],contract_fit=r['result']['contract_fit'],summary=(r['result']['assessment'] or {}).get('summary'),accounting=r['result']['accounting'],elapsed_seconds=r['elapsed_seconds']) for r in results],indent=2)+'\n')
    return report


def run(input_path,base_dir=None,*,experimental=False,approve_input=None,max_usd='.06',confirm_prices=False,check_only=False):
    from . import deepinfra_requests as hosted
    path=existing.Path(input_path);packet=existing.integration.polarity.trial.frozen(path);expected,out=prepare(base_dir,pair=packet['pair'],check_only=True)
    if packet!=expected or path.resolve()!=(out/'input.json').resolve():raise ValueError('Frozen selection, model pair, prompts, pricing or code differs')
    try:cap=existing.Decimal(max_usd)
    except existing.InvalidOperation as error:raise ValueError('Invalid comparison ceiling') from error
    if not cap.is_finite() or not existing.Decimal(packet['budget']['reserved_usd'])<=cap<=existing.Decimal('.06'):raise ValueError('Reserve both calls within $0.06')
    if check_only:return dict(status='PREPARED_NO_EXECUTION',paid_calls=0,budget=packet['budget'])
    if not experimental or approve_input!=packet['input_fingerprint'] or not confirm_prices:raise ValueError('Exact frozen approval, --experimental and --confirm-prices required')
    if not (out/'comparison.json').exists() and not hosted.credential_present():raise ValueError('DEEPINFRA_API_KEY required; no attempts started')
    existing.Store(out).write_immutable('authorization.json',dict(input_fingerprint=packet['input_fingerprint'],max_usd=str(cap),cumulative_max_usd='1'))
    import sys
    return run_recipe(packet,out,hosted.transport,progress=lambda message:print(message,file=sys.stderr,flush=True))|dict(comparison=str(out/'comparison.json'))
