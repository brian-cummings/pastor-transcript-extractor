"""One paid source request, explicitly prepared; no automatic execution or fallback."""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
import json
from pathlib import Path

from . import learning_demo as demo
from . import learning_demo_thinking_check as thinking
from . import deepinfra_requests as provider
from .evidence_requests import RequestSpec, ReceiptStore, DEEPINFRA_VERSION, DEEPINFRA_EXPANDED_VERSION
from .pastor_evidence import EvidenceArtifactStore, digest

PRIOR='da1357da33ed6e695989b1f82c7a64bf8dae17925c70adde29ad052bc6d6e308'
VERSION=provider.NAMESPACE
EXPANDED_PRIOR='583b37a73580f24e234c57a1233effe71f3d60403eeb9d0e1bad97870f424c1e'
SOURCES=dict(model='https://deepinfra.com/deepseek-ai/DeepSeek-V4-Pro-0813',
    api='https://docs.deepinfra.com/chat/overview',schema='https://docs.deepinfra.com/chat/structured-outputs',
    reasoning='https://docs.deepinfra.com/chat/reasoning',privacy='https://docs.deepinfra.com/account/data-privacy')


def directory(base_dir,fingerprint,*,expanded=False):
    path=demo.build_paths(base_dir).evaluation/('learning-demo-deepinfra-expanded' if expanded else 'learning-demo-deepinfra-fit')/fingerprint
    if path.resolve().is_relative_to(Path(__file__).parents[2].resolve()):
        raise ValueError('Generated artifacts must be outside repository')
    return path


def prepare(prior_input,base_dir=None,*,check_only=False,expanded_output=False):
    if expanded_output: return prepare_expanded(prior_input,base_dir,check_only=check_only)
    prior_input=Path(prior_input).resolve()
    if prior_input!=(thinking.directory(base_dir,PRIOR)/'input.json').resolve():
        raise ValueError('DeepInfra preparation requires the preserved one-window thinking diagnostic')
    prior=json.loads(prior_input.read_text())
    if prior['input_fingerprint']!=PRIOR or digest({k:v for k,v in prior.items() if k!='input_fingerprint'})!=PRIOR:
        raise ValueError('Prior diagnostic input identity changed')
    for path,sha in prior['history']['preserved_files'].items():
        if demo.file_hash(Path(path))!=sha: raise ValueError('Historical evidence changed')
    old_store=ReceiptStore(prior_input.parent/'execution')
    result=json.loads((old_store.root/'results.json').read_text())
    if (result['input_fingerprint']!=PRIOR or result['accounting']['attempts']!=1
        or len(old_store.attempts())!=1 or result['accounting']['paid_attempts']!=0
        or result['halt']!="Incomplete Ollama response (done=True, done_reason='length'); no repair/retry"):
        raise ValueError('Prior diagnostic is not the reviewed one-attempt output-limit stop')
    from .learning_demo_model_fit import verify_sources
    original=json.loads(Path(prior['history']['prior_input']).read_text())
    verify_sources(original,base_dir)
    for name in ('pastor_evidence','theological_binding','binding_evidence'):
        if prior['code_identity'][name]!=demo.code_identity()[name]:
            raise ValueError('Shared literal evidence semantics changed')
    if prior['schema']!=thinking.schema() or prior['prompt']!=thinking.PROMPT:
        raise ValueError('Prepared source prompt or qualified-claim schema changed')
    body=dict(model=provider.MODEL,messages=deepcopy(prior['request']['body']['messages']),
        response_format=dict(type='json_schema',json_schema=dict(name='qualified_source_reading',strict=True,schema=prior['schema'])),
        max_tokens=provider.OUTPUT_CAP,temperature=0,top_p=1,n=1,stream=False,reasoning_effort='medium')
    request=RequestSpec('source_reading',body,prior['request']['source_identity'],
        namespace=VERSION,version=DEEPINFRA_VERSION,runtime_identity=provider.POLICY)
    account=request.preflight()
    files=[prior_input,*sorted(p for p in old_store.root.rglob('*.json') if p.name!='deepinfra-fit-authorization.json')]
    packet=dict(schema_version=VERSION,code_identity={**demo.code_identity(),
            'learning_demo_thinking_check':demo.file_hash(Path(thinking.__file__)),
            'deepinfra_requests':demo.file_hash(Path(provider.__file__)),
            'learning_demo_deepinfra_fit':demo.file_hash(Path(__file__))},
        history=dict(prior_input=str(prior_input),prior_attempts=28,prior_source_attempts=24,prior_synthetic_attempts=4,
            preserved_files={**prior['history']['preserved_files'],**{str(p):demo.file_hash(p) for p in files}}),
        window=prior['window'],schema=prior['schema'],prompt=prior['prompt'],request=asdict(request),token_account=account,
        provider_docs=dict(checked_on='2026-10-25',urls=SOURCES,
            capability_status='Documented API/schema/reasoning; exact request/model combination unvalidated until execution'),
        budget=dict(maximum_attempts=1,maximum_paid_attempts=1,max_usd=provider.MAX_USD,
            reserved_usd=str(provider.reserved_usd()),cumulative_maximum_attempts=29,
            input_cap=provider.INPUT_CAP,output_cap=provider.OUTPUT_CAP,maximum_claims=2,retries=0,fallbacks=0),
        credentials=dict(environment_variable='DEEPINFRA_API_KEY',transport='HTTPS bearer token; SSH not used'),
        limitation='One reviewed source window; no independent accuracy benchmark, verifier call, full workflow, parallel execution or admission',
        production_admission=False)
    packet['input_fingerprint']=digest(packet)
    out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        command=f'pte analysis learning-demo model-fit deepinfra-run --base-dir {demo.build_paths(base_dir).root} --input {out / "input.json"} --experimental --approve-input {packet["input_fingerprint"]} --max-usd 0.25 --confirm-prices --json'
        (out/'preparation.md').write_text('# DeepInfra one-window preparation\n\n'
            f'{provider.MODEL}; medium reasoning, strict JSON schema, two complete claims. '
            f'Input cap {provider.INPUT_CAP}, output cap {provider.OUTPUT_CAP}, uncached price '
            f'${provider.INPUT_PRICE}/${provider.OUTPUT_PRICE} per million input/output tokens. '
            f'Worst-case reservation ${provider.reserved_usd()}, hard ceiling $0.25, one paid attempt. '
            'Reasoning is billed as output. No retries, fallback, manual output repair or production admission. '
            '28 prior local attempts preserved. Hosted model name is pinned; weight identity cannot be verified locally.\n\n'
            'Set DEEPINFRA_API_KEY in your shell; never paste it into chat or an input manifest. '
            'No OpenAI account/key or SSH access is needed. Preparation/preflight make no provider calls.\n\n'
            'Brian separately executes:\n\n```sh\n'+command+'\n```\n')
    return packet,out


def prepare_expanded(prior_input,base_dir=None,*,check_only=False):
    prior_input=Path(prior_input).resolve()
    if prior_input!=(directory(base_dir,EXPANDED_PRIOR)/'input.json').resolve():
        raise ValueError('Expanded output requires the reviewed DeepInfra length-stop input')
    prior=json.loads(prior_input.read_text())
    if prior['input_fingerprint']!=EXPANDED_PRIOR or digest({k:v for k,v in prior.items() if k!='input_fingerprint'})!=EXPANDED_PRIOR:
        raise ValueError('Prior DeepInfra identity changed')
    for path,sha in prior['history']['preserved_files'].items():
        if demo.file_hash(Path(path))!=sha: raise ValueError('Historical evidence changed')
    store=ReceiptStore(prior_input.parent/'execution')
    result=json.loads((store.root/'results.json').read_text())
    if (result['input_fingerprint']!=EXPANDED_PRIOR or len(store.attempts())!=1
        or result['accounting']['paid_attempts']!=1 or result['accounting']['unknown_usage_attempts']!=0
        or result['accounting']['known_output_tokens']!=16384
        or result['halt']!="Incomplete DeepInfra response (finish_reason='length'); no repair/retry"):
        raise ValueError('Prior request is not the reviewed known-usage DeepInfra length stop')
    # Recheck original sources and unchanged qualified observation semantics.
    original_thinking=json.loads(Path(prior['history']['prior_input']).read_text())
    from .learning_demo_model_fit import verify_sources
    verify_sources(json.loads(Path(original_thinking['history']['prior_input']).read_text()),base_dir)
    for name in ('pastor_evidence','theological_binding','binding_evidence','learning_demo_contracts'):
        if prior['code_identity'][name]!=demo.code_identity()[name]: raise ValueError('Source contract semantics changed')
    metadata=provider.public_model_metadata()
    if (metadata['model']!=provider.MODEL or metadata['native_output_schema_maximum']<65536
        or Decimal(metadata['input_cents_per_token'])*10000!=Decimal(provider.INPUT_PRICE)
        or Decimal(metadata['output_cents_per_token'])*10000!=Decimal(provider.OUTPUT_PRICE)):
        raise ValueError('Published DeepInfra model output capability or prices differ')
    old=RequestSpec(**prior['request'])
    body={**deepcopy(old.body),'max_tokens':65536}
    request=replace(old,body=body,namespace=provider.EXPANDED_NAMESPACE,version=DEEPINFRA_EXPANDED_VERSION,
        runtime_identity=provider.EXPANDED_POLICY)
    account=request.preflight()
    files=[prior_input,*sorted(p for p in store.root.rglob('*.json') if p.name!='expanded-output-authorization.json')]
    packet={**deepcopy(prior),'schema_version':provider.EXPANDED_NAMESPACE,
        'expanded_from':str(prior_input),'published_model_metadata':metadata,
        'code_identity':{**demo.code_identity(),'learning_demo_thinking_check':demo.file_hash(Path(thinking.__file__)),
            'deepinfra_requests':demo.file_hash(Path(provider.__file__)),'learning_demo_deepinfra_fit':demo.file_hash(Path(__file__))},
        'request':asdict(request),'token_account':account,
        'history':dict(prior_input=str(prior_input),prior_attempts=29,prior_local_attempts=28,prior_paid_attempts=1,
            prior_source_attempts=25,prior_synthetic_attempts=4,
            prior_known_list_price_usage_usd=result['accounting']['known_list_price_usage_usd'],
            preserved_files={**prior['history']['preserved_files'],**{str(p):demo.file_hash(p) for p in files}}),
        'budget':dict(maximum_attempts=1,maximum_paid_attempts=1,max_usd=provider.MAX_USD,
            reserved_usd=str(provider.reserved_usd(request.version)),cumulative_maximum_attempts=30,
            input_cap=49152,output_cap=65536,maximum_claims=2,retries=0,fallbacks=0),
        'limitation':'One generous-output request, not literally unbounded. Public native output schema permits this cap; hosted chat support remains unvalidated. No automatic budget reduction, retry or admission.'}
    packet.pop('input_fingerprint')
    packet['input_fingerprint']=digest(packet)
    out=directory(base_dir,packet['input_fingerprint'],expanded=True)
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        command=f'pte analysis learning-demo model-fit deepinfra-run --base-dir {demo.build_paths(base_dir).root} --input {out / "input.json"} --experimental --approve-input {packet["input_fingerprint"]} --max-usd 0.25 --confirm-prices --json'
        (out/'preparation.md').write_text('# Generous-output DeepInfra check\n\nSame source, two-claim schema, medium reasoning and model. '
            f'Output allowance 65,536 tokens; input reservation 49,152; new request reservation ${account["reserved_usd"]}, '
            f'new request ceiling $0.25. Previous paid usage ${result["accounting"]["known_list_price_usage_usd"]} remains separately recorded. '
            f'HTTP inactivity timeout {account["timeout_seconds"]}s. Not literally unbounded. '
            'One new paid attempt; cumulative maximum 30 (28 local, two paid). No retries or automatic lower-budget runs. '
            'Review completion and accuracy before deciding whether to reduce budgets.\n\n```sh\n'+command+'\n```\n')
    return packet,out


def verify(input_path,base_dir):
    packet=json.loads(Path(input_path).read_text())
    fingerprint=packet['input_fingerprint']
    expanded='expanded_from' in packet
    if (packet['schema_version']!=(provider.EXPANDED_NAMESPACE if expanded else VERSION) or digest({k:v for k,v in packet.items() if k!='input_fingerprint'})!=fingerprint
        or Path(input_path).resolve()!=(directory(base_dir,fingerprint,expanded=expanded)/'input.json').resolve()):
        raise ValueError('DeepInfra input identity or location differs')
    expected,_=prepare(packet['history']['prior_input'],base_dir,check_only=True,expanded_output=expanded)
    if expected!=packet: raise ValueError('DeepInfra source, implementation, model, prices or budget changed after freeze')
    marker=Path(packet['history']['prior_input']).parent/'execution'/('expanded-output-authorization.json' if expanded else 'deepinfra-fit-authorization.json')
    if marker.exists() and json.loads(marker.read_text())!={'input_fingerprint':fingerprint}:
        raise ValueError('One DeepInfra attempt already assigned to another input')
    return packet,marker


def run(input_path,base_dir=None,*,experimental=False,approve_input=None,max_usd='0.25',confirm_prices=False,check_only=False,progress=None):
    packet,marker=verify(input_path,base_dir)
    if check_only:
        return dict(status='PREPARED_NO_EXECUTION',input_fingerprint=packet['input_fingerprint'],
            budget=packet['budget'],token_account=packet['token_account'],
            provider_calls=int('expanded_from' in packet),metadata_requests=int('expanded_from' in packet),
            generation_calls=0,paid_calls=0,
            credential_configured=provider.credential_present())
    if not experimental or approve_input!=packet['input_fingerprint'] or not confirm_prices:
        raise ValueError('Use --experimental --approve-input exact fingerprint --confirm-prices')
    ledger=provider.OneRequestLedger(max_usd,packet['request']['version'])
    # Validate authorization, budget and credentials before creating an attempt.
    ledger.check([],'source_reading')
    store=ReceiptStore(Path(input_path).parent/'execution')
    if not (store.root/'results.json').exists() and not provider.credential_present():
        raise ValueError('Set DEEPINFRA_API_KEY; no attempts started')
    EvidenceArtifactStore(marker.parent).write_immutable(marker.name,dict(input_fingerprint=approve_input))
    store.write_immutable('authorization.json',dict(input_fingerprint=approve_input,max_usd=str(Decimal(max_usd)),
        confirm_prices=True,maximum_attempts=1,production_admission=False))
    if progress: progress(f'DeepInfra source window 1/1: {packet["window"]["id"]}; {provider.MODEL}; medium reasoning; one attempt; no retries')
    result=thinking.run_recipe(packet,store,provider.transport,ledger=ledger)
    return {k:v for k,v in result.items() if k not in ('reading','observations')} | dict(results=str(store.root/'results.json'))
