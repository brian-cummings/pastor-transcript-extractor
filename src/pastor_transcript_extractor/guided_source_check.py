"""One full-schema source reading with a derived vocabulary guide and conditional verifier."""
from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal,InvalidOperation
import json
import os
from pathlib import Path
from httpx import HTTPError

from . import source_enum_check as enum_check
from . import source_context as context
from . import source_context_trial as trial
from . import learning_demo as demo
from . import learning_demo_model_fit as fit
from . import learning_demo_feedback as feedback
from . import evidence_requests as requests
from . import deepinfra_requests as hosted
from . import binding_retry
from . import binding_feedback
from .pastor_evidence import SourceWindow,EvidenceArtifactStore,digest

VERSION='guided-full-source-check-v1'
PRIOR='e98578cb5bc750b495f71eda70be18bd94676e6901ee808af81a833e002fb087'
BOUND_STOP='785e333bac45989b32e5cde03adaf540bf4ff5445f78e8d4c1bdd755e6aeda44'
FEEDBACK_STOP='a56ac6f5bce123a1799991b6c16ce76514cf706dc9109dabad974fe86d377633'
CASE='P318-R281-application'
LIMITATION='One previously exposed source window; full schema plus generated vocabulary guide and lower output cap. Not an isolated ablation, independent accuracy benchmark or production admission.'


def identity():
    modules=(enum_check,context,requests,hosted,feedback,context.diagnostics,context.fields,fit,binding_retry,binding_feedback)
    return {**demo.code_identity(),**{m.__name__.rsplit('.',1)[-1]:demo.file_hash(Path(m.__file__)) for m in modules},
        'guided_source_check':demo.file_hash(Path(__file__))}


def source_request(case):
    old=requests.RequestSpec(**case['request']);body=deepcopy(old.body)
    shape=context.schema();guide=enum_check.field_guide(shape)
    body['messages']=[dict(role='system',content=context.contract_packet()['reader_prompt']+
        '\nField/type/vocabulary guide (derived mechanically from the schema):\n'+'\n'.join(guide)),
        deepcopy(old.body['messages'][1])]
    body['response_format']['json_schema']['schema']=shape
    body['max_tokens']=8192
    spec=replace(old,body=body,namespace=hosted.GUIDED_NAMESPACE,version=requests.DEEPINFRA_GUIDED_VERSION,
        runtime_identity=hosted.GUIDED_POLICY)
    context.validate_request(spec);spec.preflight()
    return spec


def directory(base_dir,fp):
    root=demo.build_paths(base_dir).evaluation/'guided-full-source-check'/fp
    if root.resolve().is_relative_to(Path(__file__).parents[2].resolve()): raise ValueError('Artifacts must be outside repository')
    return root


def prepare(prior_input,base_dir=None,*,check_only=False):
    path=Path(prior_input).resolve()
    if path==(directory(base_dir,FEEDBACK_STOP)/'input.json').resolve():
        return prepare_binding_correction(path,base_dir,check_only=check_only,enriched=True)
    if path==(directory(base_dir,BOUND_STOP)/'input.json').resolve():
        return prepare_binding_correction(path,base_dir,check_only=check_only)
    if path!=(enum_check.directory(base_dir,PRIOR)/'input.json').resolve(): raise ValueError('Requires the completed synthetic nested-field PASS')
    prior=json.loads(path.read_text());root=path.parent/'execution';result=json.loads((root/'results.json').read_text())
    if prior['input_fingerprint']!=PRIOR or digest({k:v for k,v in prior.items() if k!='input_fingerprint'})!=PRIOR:
        raise ValueError('Synthetic input changed')
    if (result['input_fingerprint']!=PRIOR or result['status']!='PASS' or result['halt'] is not None
        or result['accounting']['attempts']!=1 or result['accounting']['unknown_usage_attempts']!=0
        or result['accounting']['cumulative_paid_attempts']!=39 or prior['schema']!=enum_check.schema()):
        raise ValueError('Synthetic result is not the completed one-call PASS')
    usage=demo.usage_account(requests.ReceiptStore(root))
    if any(result['accounting'].get(k)!=v for k,v in usage.items()): raise ValueError('Synthetic accounting differs from receipts')
    old=requests.RequestSpec(**prior['request'])
    receipt=json.loads((root/'receipts'/f'{old.fingerprint}.json').read_text())
    if receipt['request']!=asdict(old) or receipt['halt'] or receipt['response_digest']!=digest(receipt['response']):
        raise ValueError('Synthetic receipt changed')
    requests.validate_response(old,receipt['response'])
    if enum_check.assess(receipt['response']['output'])!=result['assessment']: raise ValueError('Synthetic assessment changed')
    source_path=Path(prior['history']['prior_input'])
    if source_path.resolve()!=(trial.directory(base_dir,enum_check.PRIOR)/'input.json').resolve(): raise ValueError('Source lineage changed')
    sources=json.loads(source_path.read_text())
    if sources['input_fingerprint']!=enum_check.PRIOR or digest({k:v for k,v in sources.items() if k!='input_fingerprint'})!=enum_check.PRIOR:
        raise ValueError('Source input changed')
    ancestor_path=Path(sources['history']['six_window_input']);ancestor=json.loads(ancestor_path.read_text())
    if ancestor['input_fingerprint']!=trial.five.SIX or digest({k:v for k,v in ancestor.items() if k!='input_fingerprint'})!=trial.five.SIX:
        raise ValueError('Original six-window input changed')
    fit.verify_sources(ancestor,base_dir)
    case=next(c for c in sources['cases'] if c['case_id']==CASE)
    if case['window']!=next(w for w in ancestor['windows'] if w['id']==CASE): raise ValueError('Source geometry changed')
    state=demo._source_state(SourceWindow(**case['window']))
    expected=dict(texts=state['texts'],block_mapping=state['block_mapping'],
        source_identity={k:v for k,v in case['window'].items() if k!='blocks'},target_scope='declared_blocks_only')
    if json.loads(case['request']['body']['messages'][1]['content'])!=expected: raise ValueError('Complete source message changed')
    metadata=hosted.public_model_metadata(hosted.FLASH_MODEL)
    if metadata!=sources['published_model_metadata']: raise ValueError('Pinned model deployment or prices changed')
    spec=source_request(case);account=result['accounting']
    reserve=hosted.reserved_usd(spec.version)+requests.reservation('source_verification')
    if account['cumulative_paid_attempts']+2>66 or Decimal(account['cumulative_known_list_price_usage_usd'])+reserve>2:
        raise ValueError('Cumulative budget exceeded')
    files=[path,source_path,ancestor_path,*sorted(p for p in root.rglob('*.json') if p.name!='guided-source-authorization.json')]
    packet=dict(version=VERSION,request=asdict(spec),schema=context.schema(),window=deepcopy(case['window']),
        field_guide=enum_check.field_guide(context.schema()),token_account=spec.preflight(),code_identity=identity(),
        published_model_metadata=metadata,policy=dict(retries=0,semantic_corrections=0,maximum_source_calls=1,
            verifier_fields=list(context.FIELDS),verifier_when='Only after schema and binding pass with substantive observations',
            production_admission=False),
        budget=dict(maximum_attempts=2,maximum_paid_attempts=2,max_usd='0.02',reserved_usd=str(reserve),
            cumulative_maximum_paid_attempts=account['cumulative_paid_attempts']+2),
        history=dict(prior_input=str(path),prior_attempts=account['cumulative_attempts'],
            prior_local_attempts=prior['history']['prior_local_attempts']+usage['local_attempts'],
            prior_paid_attempts=account['cumulative_paid_attempts'],prior_known_list_price_usage_usd=account['cumulative_known_list_price_usage_usd'],
            preserved_files={str(p):demo.file_hash(p) for p in files}),limitation=LIMITATION)
    packet['input_fingerprint']=digest(packet);out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        (out/'preparation.md').write_text('# One guided full-schema source check\n\n'+LIMITATION+
            '\n\nReuse the frozen P318-R281 source without expansion. One Flash 1017 reading, reasoning disabled, '
            'full unchanged schema plus generated vocabulary guide, 8,192 output tokens. TypeSafe follows only '
            'after schema and binding pass. No retry or correction. Reservation $'+str(reserve)+', ceiling $0.02.\n\n```sh\n'+command(out,packet,base_dir)+'\n```\n')
    return packet,out


def prepare_binding_correction(path,base_dir=None,*,check_only=False,enriched=False):
    """One separately authorized correction of an already-paid, bound-stop answer."""
    path=Path(path);prior=json.loads(path.read_text());root=path.parent/'execution'
    result=json.loads((root/'results.json').read_text())
    expected_fp=FEEDBACK_STOP if enriched else BOUND_STOP
    if prior['input_fingerprint']!=expected_fp or digest({k:v for k,v in prior.items() if k!='input_fingerprint'})!=expected_fp:
        raise ValueError('Binding-stop input identity changed')
    if (result['input_fingerprint']!=expected_fp or result['status']!='FAIL(component)' or result['halt'] is not None
        or result['verification'] is not None or result['accounting']['attempts']!=1
        or result['accounting']['unknown_usage_attempts']!=0 or result['accounting']['cumulative_paid_attempts']!=(41 if enriched else 40)):
        raise ValueError('Requires the completed one-call mechanical binding stop')
    current,_=prepare(prior['history']['prior_input'],base_dir,check_only=True)
    if any(current[k]!=prior[k] for k in ('request','window','schema','field_guide','published_model_metadata')):
        raise ValueError('Source, guide, schema or model changed since the saved answer')
    for filename,sha in prior['history']['preserved_files'].items():
        if demo.file_hash(Path(filename))!=sha: raise ValueError('Preserved history changed')
    old=requests.RequestSpec(**prior['request']);store=requests.ReceiptStore(root/'initial')
    receipt=json.loads((store.root/'receipts'/f'{old.fingerprint}.json').read_text())
    if receipt['request']!=asdict(old) or receipt['halt'] or receipt['response_digest']!=digest(receipt['response']):
        raise ValueError('Saved reader receipt changed')
    requests.validate_response(old,receipt['response'])
    usage=demo.usage_account(store)
    account_fields=('attempts','local_attempts','paid_attempts','openai_calls','known_input_tokens',
        'known_output_tokens','unknown_usage_attempts','reserved_usd','known_list_price_usage_usd','known_provider_estimated_usage_usd')
    if any(result['accounting'].get(k)!=usage[k] for k in account_fields): raise ValueError('Saved attempt accounting differs')
    checked=context.inspect(receipt['response']['output'],SourceWindow(**prior['window']),model=hosted.FLASH_MODEL,
        prompt_digest=digest(old.body['messages']),raw_response_ref='initial/receipts/'+old.fingerprint+'.json')
    if checked!=result['validation'] or not checked['errors'] or context.diagnostics.shape_errors(checked['reading'],context.schema()):
        raise ValueError('Saved answer is not a schema-valid binding failure')
    errors=binding_feedback.enrich(checked['errors'],checked['reading'],SourceWindow(**prior['window'])) if enriched else checked['errors']
    base=replace(old,body={**deepcopy(old.body),'messages':deepcopy(old.body['messages'][:2])}) if enriched else old
    corrected=binding_retry.retry_request(base,receipt['response'],errors,contextual=True)
    if enriched:
        corrected=replace(corrected,source_identity={**corrected.source_identity,'binding_retry_of':old.fingerprint})
    packet=deepcopy(current);packet.pop('input_fingerprint',None)
    packet.update(request=asdict(corrected),token_account=corrected.preflight(),original_output=receipt['response']['output'],
        original_request_fingerprint=old.fingerprint,original_errors=checked['errors'],
        continuation_from=str(path),code_identity=identity())
    packet['policy'].update(binding_correction=True,binding_ids=context.inventory(checked['reading']),
        saved_response_reuse='Previous paid response is supplied verbatim; original source prefix and producer receipt preserved')
    if enriched:
        packet['binding_feedback']=errors
        packet['policy'].update(feedback_version=binding_feedback.VERSION,
            feedback_scope='All literal occurrences and saved node IDs/roles; no selected occurrence, node or semantic repair')
    account=result['accounting']
    packet['history'].update(prior_input=str(path),prior_attempts=account['cumulative_attempts'],
        prior_local_attempts=account['cumulative_local_attempts'],prior_paid_attempts=account['cumulative_paid_attempts'],
        prior_known_list_price_usage_usd=account['cumulative_known_list_price_usage_usd'])
    files=[path,*sorted(p for p in root.rglob('*.json') if p.name!='guided-source-authorization.json')]
    packet['history']['preserved_files'].update({str(p):demo.file_hash(p) for p in files})
    packet['budget']['cumulative_maximum_paid_attempts']=account['cumulative_paid_attempts']+2
    if packet['budget']['cumulative_maximum_paid_attempts']>66 or Decimal(account['cumulative_known_list_price_usage_usd'])+Decimal(packet['budget']['reserved_usd'])>2:
        raise ValueError('Cumulative correction budget exceeded')
    packet['input_fingerprint']=digest(packet);out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        (out/'preparation.md').write_text('# One guided binding correction\n\nReuse the complete saved answer and '
            'exact mechanical errors. One Flash 1017 replacement under the same source, schema, guide, decoding and output cap; '
            'preserve binding IDs. TypeSafe follows only after binding passes. No further retry or semantic correction. '
            'Maximum two new calls, reservation $0.017498112 under $0.02. Original answer is not regenerated or repaired by code.\n\n```sh\n'+command(out,packet,base_dir)+'\n```\n')
    return packet,out


def command(out,packet,base_dir):
    return (f'pte analysis learning-demo model-fit guided-source-run --base-dir {demo.build_paths(base_dir).root} '
        f'--input {out/"input.json"} --experimental --approve-input {packet["input_fingerprint"]} --max-usd 0.02 --confirm-prices --json')


def run_recipe(packet,root,flash_transport,verifier_transport,*,progress=None):
    root=Path(root);artifacts=requests.ReceiptStore(root)
    if (root/'results.json').exists():
        saved=json.loads((root/'results.json').read_text())
        if saved['input_fingerprint']!=packet['input_fingerprint']: raise ValueError('Foreign guided result')
        return saved
    checked=judgment=None;halt=None
    try:
        spec=requests.RequestSpec(**packet['request']);window=SourceWindow(**packet['window'])
        if progress: progress(CASE+(': one binding correction from saved answer; no further retry' if packet.get('policy',{}).get('binding_correction') else ': full-schema guided Flash reading; one attempt; no retry'))
        response=requests.execute(spec,hosted.OneRequestLedger('0.02',spec.version),requests.ReceiptStore(root/'initial'),flash_transport)
        checked=context.inspect(response['output'],window,model=hosted.FLASH_MODEL,
            prompt_digest=digest(spec.body['messages']),raw_response_ref='initial/receipts/'+spec.fingerprint+'.json')
        if not checked['errors'] and packet.get('policy',{}).get('binding_correction'):
            if set(context.inventory(checked['reading']))!=set(packet['policy']['binding_ids']):
                checked['errors'].append(dict(path='$.claims',code='identity',message='Binding correction changed identity/coverage'))
                checked['observations']=[];checked['abstentions']=[]
        artifacts.write_immutable('reading-validation.json',checked)
        if not checked['errors'] and checked['observations']:
            verify,candidates=context.verification(window,checked['observations'])
            artifacts.write_immutable('verifier-request.json',asdict(verify))
            if progress: progress(CASE+': TypeSafe qualifications, polarity and context check; no correction')
            response=requests.execute(verify,requests.BudgetLedger(max_attempts=1,max_usd='0.003'),
                requests.ReceiptStore(root/'verification'),verifier_transport)
            judgment=feedback.judgments(response,verify,candidates)
            artifacts.write_immutable('verifier-judgments.json',judgment)
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: halt=str(error)
    accounting={}
    accounts=[demo.usage_account(requests.ReceiptStore(root/name)) for name in ('initial','verification')]
    for key in ('attempts','local_attempts','paid_attempts','openai_calls','known_input_tokens','known_output_tokens','unknown_usage_attempts'):
        accounting[key]=sum(a[key] for a in accounts)
    for key in ('reserved_usd','known_list_price_usage_usd','known_provider_estimated_usage_usd'):
        accounting[key]=str(sum((Decimal(a.get(key,'0')) for a in accounts),Decimal(0)))
    accounting.update(cumulative_attempts=packet['history']['prior_attempts']+accounting['attempts'],
        cumulative_local_attempts=packet['history']['prior_local_attempts']+accounting['local_attempts'],
        cumulative_paid_attempts=packet['history']['prior_paid_attempts']+accounting['paid_attempts'],
        cumulative_known_list_price_usage_usd=str(Decimal(packet['history']['prior_known_list_price_usage_usd'])+Decimal(accounting['known_list_price_usage_usd'])),
        runtime_repairs=0,runtime_approvals=0,reference_inputs=0)
    failed=halt or checked is None or checked['errors']
    result=dict(input_fingerprint=packet['input_fingerprint'],window_id=packet['window']['id'],
        status='FAIL(component)' if failed else 'INCONCLUSIVE',contract_fit='FAIL(component)' if checked is None or checked['errors'] else 'PASS',
        halt=halt,validation=checked,verification=judgment,
        context_eligibility=context.eligibility(checked,judgment) if checked is not None else None,
        accounting=accounting,production_admission=False,limitation=LIMITATION,
        next_step='Review the saved reading against the complete source; no automatic retry or workflow advancement')
    artifacts.write_immutable('source-review-packet.json',dict(source=demo._source_state(SourceWindow(**packet['window'])),
        reading=checked['reading'] if checked else None,verification=judgment,production_admission=False))
    artifacts.write_immutable('results.json',result);demo._write_report(root.parent,result)
    return result


def run(input_path,base_dir=None,*,experimental=False,approve_input=None,max_usd='0.02',confirm_prices=False,check_only=False,progress=None):
    path=Path(input_path);packet=json.loads(path.read_text());fp=packet['input_fingerprint']
    if digest({k:v for k,v in packet.items() if k!='input_fingerprint'})!=fp or path.resolve()!=(directory(base_dir,fp)/'input.json').resolve():
        raise ValueError('Frozen input identity or location changed')
    expected,_=prepare(packet['history']['prior_input'],base_dir,check_only=True)
    if expected!=packet: raise ValueError('Frozen source, schema, guide, model, code or budget changed')
    try: cap=Decimal(max_usd)
    except InvalidOperation as error: raise ValueError('Invalid ceiling') from error
    if not cap.is_finite() or not Decimal(packet['budget']['reserved_usd'])<=cap<=Decimal('0.02'):
        raise ValueError('Reserve both requests within $0.02')
    if check_only: return dict(status='PREPARED_NO_EXECUTION',budget=packet['budget'],generation_calls=0,paid_calls=0)
    if not experimental or approve_input!=fp or not confirm_prices: raise ValueError('Use --experimental --approve-input exact fingerprint --confirm-prices')
    root=path.parent/'execution'
    if not (root/'results.json').exists() and (not hosted.credential_present() or not os.environ.get('TYPESAFE_API_KEY','').strip()):
        raise ValueError('Both provider credentials required; no attempt started')
    marker=Path(packet['history']['prior_input']).parent/'execution'
    EvidenceArtifactStore(marker).write_immutable('guided-source-authorization.json',dict(input_fingerprint=fp))
    EvidenceArtifactStore(root).write_immutable('authorization.json',dict(input_fingerprint=fp,max_usd=str(cap)))
    result=run_recipe(packet,root,hosted.transport,requests.typesafe_transport,progress=progress)
    return {k:v for k,v in result.items() if k not in ('validation','verification')}|dict(results=str(root/'results.json'))
