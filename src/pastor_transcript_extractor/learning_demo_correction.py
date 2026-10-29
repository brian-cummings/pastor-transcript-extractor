"""One frozen source request and at most one model-authored corrective response."""
from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal
import json
from pathlib import Path
from httpx import HTTPError

from . import learning_demo as demo
from . import learning_demo_deepinfra_direct as direct
from . import learning_demo_thinking_check as thinking
from . import reading_diagnostics as diagnostics
from . import deepinfra_requests as provider
from . import evidence_requests as requests
from .pastor_evidence import EvidenceArtifactStore,SourceWindow,digest

PRIOR='a0947eb365c5ba0d13b01747075756f47882ec0ce1827c9a9bbd252284144c7c'
VERSION=provider.CORRECTION_NAMESPACE


def directory(base_dir,fingerprint):
    path=demo.build_paths(base_dir).evaluation/'learning-demo-deepinfra-correction'/fingerprint
    if path.resolve().is_relative_to(Path(__file__).parents[2].resolve()):
        raise ValueError('Generated artifacts must be outside repository')
    return path


def prepare(prior_input,base_dir=None,*,check_only=False):
    prior_input=Path(prior_input).resolve()
    if prior_input!=(direct.directory(base_dir,PRIOR)/'input.json').resolve():
        raise ValueError('Requires the reviewed Flash 1017 direct binding failure')
    prior=json.loads(prior_input.read_text())
    if prior['input_fingerprint']!=PRIOR or digest({k:v for k,v in prior.items() if k!='input_fingerprint'})!=PRIOR:
        raise ValueError('Prior input identity changed')
    for path,sha in prior['history']['preserved_files'].items():
        if demo.file_hash(Path(path))!=sha: raise ValueError('Historical evidence changed')
    old_store=requests.ReceiptStore(prior_input.parent/'execution')
    result=json.loads((old_store.root/'results.json').read_text())
    if (result['input_fingerprint']!=PRIOR or result['halt'] is not None or result['literal_bound_claims']!=0
        or len(result['failures'])!=2 or len(old_store.attempts())!=1
        or result['accounting']['paid_attempts']!=1 or result['accounting']['unknown_usage_attempts']!=0
        or result['accounting']['cumulative_attempts']!=31):
        raise ValueError('Prior result is not the reviewed complete Flash contract failure')
    for name in ('pastor_evidence','theological_binding','binding_evidence','learning_demo_contracts'):
        if prior['code_identity'][name]!=demo.code_identity()[name]: raise ValueError('Evidence/compiler semantics changed')
    ancestor=prior
    while 'source_requests' not in ancestor:
        ancestor=json.loads(Path(ancestor['history']['prior_input']).read_text())
    from .learning_demo_model_fit import verify_sources
    verify_sources(ancestor,base_dir)
    metadata=provider.public_model_metadata(provider.FLASH_MODEL);policy=provider.CORRECTION_POLICY
    if (metadata['model']!=policy['model'] or metadata['native_output_schema_maximum']<policy['output_cap']
        or metadata['context']<policy['input_cap']+policy['output_cap']
        or not {'can-disable-reasoning','structured-output'}<=set(metadata['capabilities'])
        or Decimal(metadata['input_cents_per_token'])*10000!=Decimal(policy['input_usd_per_million'])
        or Decimal(metadata['output_cents_per_token'])*10000!=Decimal(policy['output_usd_per_million'])):
        raise ValueError('Published model capability or full-list price differs')
    old=requests.RequestSpec(**prior['request']);prompt=thinking.PROMPT+diagnostics.PROMPT
    body=deepcopy(old.body)
    body['messages'][0]['content']=prompt+'\nOutput schema: '+requests.wire(prior['schema'])
    spec=replace(old,body=body,namespace=VERSION,version=requests.DEEPINFRA_CORRECTION_VERSION,runtime_identity=policy)
    account=spec.preflight();provider.CorrectionLedger().check([],'source_reading')
    files=[prior_input,*sorted(p for p in old_store.root.rglob('*.json') if p.name!='corrective-authorization.json')]
    identities={**demo.code_identity(),'learning_demo_correction':demo.file_hash(Path(__file__)),
        **{name:demo.file_hash(Path(module.__file__)) for name,module in (
        ('reading_diagnostics',diagnostics),
        ('deepinfra_requests',provider),('learning_demo_thinking_check',thinking))}}
    packet=dict(schema_version=VERSION,request=asdict(spec),schema=deepcopy(prior['schema']),prompt=prompt,
        window=deepcopy(prior['window']),token_account=account,published_model_metadata=metadata,code_identity=identities,
        correction=dict(version=diagnostics.VERSION,template=diagnostics.CORRECTION,
            construction='append unchanged assistant output and user template plus canonical diagnostic JSON to original two messages',
            eligible_failures=['json','schema','literal_binding'],maximum_corrections=1,
            noneligible='transport, timeout, uncertain spend, length, refusal, model mismatch, reasoning violation, empty valid inventory',
            overflow='Stop without truncation if feedback request exceeds frozen input cap',
            cache='Exact response cache replays receipts; provider prefix cache is best effort, never assumed for budget'),
        budget=dict(maximum_attempts=2,maximum_paid_attempts=2,retries=1,fallbacks=0,max_usd='0.10',
            reserved_usd=str(2*provider.reserved_usd(spec.version)),input_cap=policy['input_cap'],output_cap=policy['output_cap'],
            maximum_claims=2,cumulative_maximum_attempts=33),
        history=dict(prior_input=str(prior_input),prior_attempts=31,prior_local_attempts=28,prior_paid_attempts=3,
            prior_source_attempts=27,prior_synthetic_attempts=4,
            prior_known_list_price_usage_usd=result['accounting']['cumulative_known_list_price_usage_usd'],
            preserved_files={**prior['history']['preserved_files'],**{str(p):demo.file_hash(p) for p in files}}),
        limitation='One reviewed source window; a corrective generation is model authored. Mechanical PASS requires independent semantic review; no accuracy benchmark, verification, expansion or production admission.',
        production_admission=False)
    packet['input_fingerprint']=digest(packet);out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        (out/'preparation.md').write_text('# Bounded Flash contract correction\n\n'+packet['limitation']+
            '\n\nSame complete P318-R3973-theology source; updated generic compiler instructions; strict two-claim schema. '
            'Flash 1017, reasoning disabled. At most two paid generations, $0.098304 full-list reservation under $0.10. '
            'Only complete source-reading schema/binding failures permit one correction; transport/length failures stop. '
            'Initial messages remain an identical prefix in the correction. All outputs, diagnostics and receipts are immutable. '
            'No manual answer repair, verifier call, fallback, third attempt or production admission.\n\n'+
            '```sh\n'+command(out,packet,base_dir)+'\n```\n')
    return packet,out


def command(out,packet,base_dir):
    return (f'pte analysis learning-demo model-fit corrective-run --base-dir {demo.build_paths(base_dir).root} '
        f'--input {out / "input.json"} --experimental --approve-input {packet["input_fingerprint"]} '
        '--max-usd 0.10 --confirm-prices --json')


def corrective_request(packet,output,errors):
    return requests.corrective_request(requests.RequestSpec(**packet['request']),output,errors,packet['correction']['template'])


def run_recipe(packet,store,transport,*,ledger=None,progress=None):
    if (store.root/'results.json').exists():
        result=json.loads((store.root/'results.json').read_text())
        if result['input_fingerprint']!=packet['input_fingerprint']: raise ValueError('Foreign corrective result')
        return result
    ledger=ledger or provider.CorrectionLedger();spec=requests.RequestSpec(**packet['request'])
    window=SourceWindow(**packet['window']);rounds=[];halt=None;checked=dict(reading=None,errors=[],observations=[])
    try:
        for index in range(2):
            if progress: progress(f'Flash 1017 source window 1/1; attempt {index+1}/2; reasoning=none'+(' (correction)' if index else ''))
            response=requests.execute(spec,ledger,store,transport)
            checked=diagnostics.inspect(response['output'],packet['schema'],window,model=spec.body['model'],
                prompt_digest=digest(spec.body['messages']),raw_response_ref='receipts/'+spec.fingerprint+'.json')
            detail=dict(attempt=index+1,request_fingerprint=spec.fingerprint,**checked)
            store.write_immutable(f'validation/attempt-{index+1}.json',detail);rounds.append(detail)
            if not checked['errors'] or index==1: break
            spec=corrective_request(packet,response['output'],checked['errors'])
            store.write_immutable('correction-request.json',asdict(spec))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: halt=str(error)
    account=demo.usage_account(store);history=packet['history']
    account.update(prior_attempts=history['prior_attempts'],prior_source_attempts=history['prior_source_attempts'],
        prior_synthetic_attempts=history['prior_synthetic_attempts'],
        cumulative_attempts=history['prior_attempts']+account['attempts'],
        cumulative_local_attempts=history['prior_local_attempts']+account['local_attempts'],
        cumulative_paid_attempts=history['prior_paid_attempts']+account['paid_attempts'],
        prior_known_list_price_usage_usd=history['prior_known_list_price_usage_usd'],
        cumulative_known_list_price_usage_usd=str(Decimal(history['prior_known_list_price_usage_usd'])+Decimal(account['known_list_price_usage_usd'])))
    fit='FAIL(component)' if halt or checked['errors'] else 'PASS' if checked['observations'] else 'INCONCLUSIVE'
    reading=checked['reading']
    result=dict(input_fingerprint=packet['input_fingerprint'],status='FAIL(component)' if fit=='FAIL(component)' else 'INCONCLUSIVE',
        contract_fit=fit,semantic_outcome='INCONCLUSIVE: requires independent review of saved source/output',
        model=provider.FLASH_MODEL,window_id=window.id,accounting=account,halt=halt,rounds=rounds,
        failures=checked['errors'],reading=reading,observations=checked['observations'] if not halt and not checked['errors'] else [],
        proposed_claims=len(reading['claims']) if isinstance(reading,dict) and isinstance(reading.get('claims'),list) else 0,
        literal_bound_claims=len(checked['observations']) if not halt and not checked['errors'] else 0,
        production_admission=False,limitation=packet['limitation'],
        next_step='Review saved output against source; no further retry or workflow advancement')
    store.write_immutable('results.json',result);demo._write_report(store.root.parent,result)
    return result


def run(input_path,base_dir=None,*,experimental=False,approve_input=None,max_usd='0.10',confirm_prices=False,check_only=False,progress=None):
    path=Path(input_path);packet=json.loads(path.read_text());fingerprint=packet['input_fingerprint']
    if digest({k:v for k,v in packet.items() if k!='input_fingerprint'})!=fingerprint or path.resolve()!=(directory(base_dir,fingerprint)/'input.json').resolve():
        raise ValueError('Frozen input identity or location changed')
    expected,_=prepare(packet['history']['prior_input'],base_dir,check_only=True)
    if expected!=packet: raise ValueError('Source, implementation, metadata or budget changed after freeze')
    ledger=provider.CorrectionLedger(max_usd);ledger.check([],'source_reading')
    if check_only:
        return dict(status='PREPARED_NO_EXECUTION',input_fingerprint=fingerprint,budget=packet['budget'],
            token_account=packet['token_account'],metadata_requests=1,generation_calls=0,paid_calls=0)
    if not experimental or approve_input!=fingerprint or not confirm_prices:
        raise ValueError('Use --experimental --approve-input exact fingerprint --confirm-prices')
    store=requests.ReceiptStore(path.parent/'execution')
    if not (store.root/'results.json').exists() and not provider.credential_present(): raise ValueError('Set DEEPINFRA_API_KEY; no attempts started')
    marker=Path(packet['history']['prior_input']).parent/'execution/corrective-authorization.json'
    EvidenceArtifactStore(marker.parent).write_immutable(marker.name,dict(input_fingerprint=fingerprint))
    store.write_immutable('authorization.json',dict(input_fingerprint=fingerprint,max_usd=str(Decimal(max_usd)),
        confirm_prices=True,maximum_attempts=2,production_admission=False))
    result=run_recipe(packet,store,provider.transport,ledger=ledger,progress=progress)
    return {k:v for k,v in result.items() if k not in ('rounds','reading','observations')} | dict(results=str(store.root/'results.json'))
