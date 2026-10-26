"""One reviewed source window, two claims, explicit thinking and bounded timeout."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from decimal import Decimal
from pathlib import Path

from httpx import HTTPError

from . import learning_demo as demo
from . import learning_demo_contracts as contract
from . import evidence_requests as requests
from . import ollama_conformance as conformance
from .pastor_evidence import EvidenceArtifactStore, SourceWindow, compile_machine_binding, digest

VERSION=requests.THINKING_CHECK_NAMESPACE
PRIOR='44be6c3265a426ef9197e94cfa66830a5ed9cb9ac7af3fc712978335b0f4efca'
CASE='P318-R3973-theology'
PROMPT=contract.READ_PROMPT.replace('up to twelve complete','up to two complete')+'''
The evidence_nodes array must contain a node whose node_id equals proposition.node_id and whose span equals proposition.span exactly. All relation, qualification and address references must point to defined nodes. Review these links before returning the answer.
This is a two-claim diagnostic, not an exhaustive window inventory. Preserve complete qualified meanings. Report saturation if more supported material remains; do not combine unrelated claims to evade the cap.
'''


def schema():
    value=deepcopy(contract.READ_SCHEMA)
    value['properties']['claims']['maxItems']=2
    return value


def directory(base_dir,fingerprint):
    path=demo.build_paths(base_dir).evaluation/'learning-demo-thinking-check'/fingerprint
    if path.resolve().is_relative_to(Path(__file__).parents[2].resolve()):
        raise ValueError('Generated artifacts must be outside repository')
    return path


def prepare(prior_input,base_dir=None,*,check_only=False):
    from . import learning_demo_model_fit as fit
    prior_input=Path(prior_input).resolve()
    if prior_input!=(fit.directory(base_dir,PRIOR)/'input.json').resolve():
        raise ValueError('Thinking check requires the reviewed stopped runtime-repeat input')
    prior=json.loads(prior_input.read_text())
    if prior['input_fingerprint']!=PRIOR or digest({k:v for k,v in prior.items() if k!='input_fingerprint'})!=PRIOR:
        raise ValueError('Prior input identity changed')
    for path,sha in prior['history']['preserved_files'].items():
        if demo.file_hash(Path(path))!=sha: raise ValueError('Historical evidence changed')
    store=requests.ReceiptStore(prior_input.parent/'execution')
    result=json.loads((store.root/'results.json').read_text())
    if (result['input_fingerprint']!=PRIOR or result['halt']!='timed out' or len(store.attempts())!=2
        or result['diagnostics']['schema_valid_responses']!=1 or result['diagnostics']['literal_bound_claims']!=0):
        raise ValueError('Prior run is not the reviewed two-attempt timeout and binding failure')
    if prior['contracts']!=dict(version=contract.VERSION,schemas=contract.SCHEMAS,
                               prompts=contract.PROMPTS,required_checks=contract.CHECK_MEANINGS):
        raise ValueError('Underlying source contract changed')
    fit.verify_sources(prior,base_dir)
    for name in ('pastor_evidence','theological_binding','binding_evidence'):
        if prior['code_identity'][name]!=demo.code_identity()[name]:
            raise ValueError('Literal binding semantics changed')
    runtime=requests.ollama_runtime_identity(model='qwen3.5:9b')
    previous={k:v for k,v in prior['generation_runtime'].items() if k!='server_version'}
    if runtime!=previous: raise ValueError('Thinking check requires the same installed Qwen model')
    version=conformance.server_version(runtime['base_url'])
    if version!='0.40.11': raise ValueError('Thinking check requires the reviewed Ollama 0.40.11 runtime')
    runtime={**runtime,'thinking':True,'server_version':version,
             'local_request_policy':requests.THINKING_CHECK_POLICY}
    row=next(row for row in prior['source_requests'] if row['case_id']==CASE)
    old=requests.RequestSpec(**row['request'])
    body=deepcopy(old.body)
    body.update(think=True,format=schema(),messages=[
        dict(role='system',content=PROMPT+'\nOutput schema: '+requests.wire(schema())),
        deepcopy(old.body['messages'][1])])
    body['options']['num_predict']=requests.THINKING_CHECK_POLICY['output_cap']
    body['options']['num_ctx']=requests.ollama_context_for(body,runtime['num_ctx'])
    request=replace(old,body=body,runtime_identity=runtime,namespace=VERSION,version=requests.THINKING_CHECK_VERSION)
    account=request.preflight()
    files=[prior_input,*sorted(p for p in store.root.rglob('*.json') if p.name!='thinking-check-authorization.json')]
    preserved={**prior['history']['preserved_files'],**{str(p):demo.file_hash(p) for p in files}}
    packet=dict(schema_version=VERSION,code_identity={**demo.code_identity(),
            'learning_demo_thinking_check':demo.file_hash(Path(__file__)),
            'ollama_conformance':demo.file_hash(Path(conformance.__file__))},
        history=dict(prior_input=str(prior_input),preserved_files=preserved,prior_attempts=27,
            prior_source_attempts=23,prior_synthetic_attempts=4),
        window=next(w for w in prior['windows'] if w['id']==CASE),request=asdict(request),
        token_account=account,schema=schema(),prompt=PROMPT,
        budget=dict(maximum_attempts=1,maximum_paid_attempts=0,max_usd='0',maximum_claims=2,
            output_cap=4096,cumulative_maximum_attempts=28,retries=0,fallbacks=0),
        changes=['one previously reviewed complete window','two-claim cap','explicit node-reference instruction',
                 'thinking enabled','4096 reported output tokens','input/output-budget timeout'],
        limitation='Feasibility diagnostic on a reviewed window, not an independent accuracy benchmark or isolated thinking ablation',
        production_admission=False)
    packet['input_fingerprint']=digest(packet)
    out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        command=f'pte analysis learning-demo model-fit thinking-run --base-dir {demo.build_paths(base_dir).root} --input {out / "input.json"} --experimental --approve-input {packet["input_fingerprint"]} --json'
        (out/'preparation.md').write_text('# One-window thinking diagnostic\n\n'+packet['limitation']+
            f'.\n\nOne local request; maximum two complete claims. Thinking enabled; reported output cap 4096. '
            f'Frozen timeout: {account["execution_policy"]["timeout_seconds"]} seconds. '
            'Prior 27 local attempts preserved; cumulative maximum 28. No retries, paid calls, manual output repairs or admission. '
            'Thinking is retained in raw receipts and is not claim evidence.\n\n```sh\n'+command+'\n```\n')
    return packet,out


def verify(input_path,base_dir):
    value=json.loads(Path(input_path).read_text())
    if (value['schema_version']!=VERSION or digest({k:v for k,v in value.items() if k!='input_fingerprint'})!=value['input_fingerprint']
        or Path(input_path).resolve()!=(directory(base_dir,value['input_fingerprint'])/'input.json').resolve()):
        raise ValueError('Thinking input identity/location differs')
    expected,_=prepare(value['history']['prior_input'],base_dir,check_only=True)
    if value!=expected: raise ValueError('Thinking input source, runtime, code or budget changed after freeze')
    marker=Path(value['history']['prior_input']).parent/'execution/thinking-check-authorization.json'
    if marker.exists() and json.loads(marker.read_text())!={'input_fingerprint':value['input_fingerprint']}:
        raise ValueError('One thinking check already assigned to another input')
    return value,marker


def run_recipe(packet,store,transport,*,ledger=None):
    path=store.root/'results.json'
    if path.exists():
        saved=json.loads(path.read_text())
        if saved['input_fingerprint']!=packet['input_fingerprint']: raise ValueError('Foreign thinking result')
        return saved
    spec=requests.RequestSpec(**packet['request'])
    failures=[];observations=[];reading=None;halt=None;thinking_emitted=None
    try:
        response=requests.execute(spec,ledger or requests.BudgetLedger(max_attempts=1,max_usd='0'),store,transport)
        raw=response.get('raw',{})
        message=(raw.get('choices',[{}])[0].get('message',{}) if requests.request_provider(spec)=='DeepInfra'
                 else raw.get('message',{}))
        thinking_emitted=bool(message.get('thinking') or message.get('reasoning_content'))
        reading=contract.validate_shape(contract.strict_json(response['output']),packet['schema'])
        if (reading['status']=='none' and reading['claims']) or (reading['status']=='proposed' and not reading['claims']):
            raise ValueError('Inconsistent reading status')
        window=SourceWindow(**{**packet['window'],'blocks':tuple(packet['window']['blocks']),
            'excluded_neighbors':tuple(packet['window']['excluded_neighbors'])})
        ids=set()
        for claim in reading['claims']:
            try:
                if claim['binding_id'] in ids: raise ValueError('Duplicate claim identity')
                ids.add(claim['binding_id'])
                observations.append(compile_machine_binding(window,claim,model=spec.body['model'],
                    prompt_digest=digest(dict(system=spec.body['messages'][0]['content'],schema=packet['schema'])),
                    raw_response_ref='receipts/'+spec.fingerprint+'.json',locate_quotes=True))
            except (ValueError,KeyError,TypeError) as error:
                failures.append(dict(component='literal_binding',binding_id=claim.get('binding_id'),reason=str(error)))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:
        halt=str(error)
    account=demo.usage_account(store)
    history=packet.get('history',{})
    prior=history.get('prior_attempts',27)
    account.update(prior_attempts=prior,prior_source_attempts=history.get('prior_source_attempts',23),prior_synthetic_attempts=4,
        cumulative_attempts=prior+account['attempts'],
        cumulative_local_attempts=history.get('prior_local_attempts',prior)+account['local_attempts'],
        cumulative_paid_attempts=history.get('prior_paid_attempts',0)+account['paid_attempts'])
    if 'prior_known_list_price_usage_usd' in history:
        account['prior_known_list_price_usage_usd']=history['prior_known_list_price_usage_usd']
        account['cumulative_known_list_price_usage_usd']=str(Decimal(history['prior_known_list_price_usage_usd'])+Decimal(account['known_list_price_usage_usd']))
    fit='FAIL(component)' if halt or failures else ('PASS' if observations else 'INCONCLUSIVE')
    result=dict(input_fingerprint=packet['input_fingerprint'],status='FAIL(component)' if fit=='FAIL(component)' else 'INCONCLUSIVE',
        contract_fit=fit,semantic_outcome='INCONCLUSIVE: requires independent review of saved source/output',
        window_id=packet['window']['id'],accounting=account,halt=halt,failures=failures,
        proposed_claims=len(reading['claims']) if reading else 0,literal_bound_claims=len(observations),
        reading=reading,observations=observations,thinking_emitted=thinking_emitted,
        execution_policy=spec.preflight()['execution_policy'],production_admission=False,
        limitation=packet['limitation'],next_step='Review saved output against source; no retry or automatic advancement')
    store.write_immutable('results.json',result)
    demo._write_report(store.root.parent,result)
    return result


def run(input_path,base_dir=None,*,experimental=False,approve_input=None,check_only=False,progress=None):
    packet,marker=verify(input_path,base_dir)
    if check_only: return dict(status='PREPARED_NO_EXECUTION',budget=packet['budget'],token_account=packet['token_account'],model_calls=0)
    if not experimental or approve_input!=packet['input_fingerprint']:
        raise ValueError('Use --experimental --approve-input exact thinking input fingerprint')
    EvidenceArtifactStore(marker.parent).write_immutable(marker.name,dict(input_fingerprint=approve_input))
    spec=requests.RequestSpec(**packet['request'])
    if progress: progress(f'One source window: {CASE}; thinking enabled; timeout {spec.preflight()["execution_policy"]["timeout_seconds"]}s; no retries')
    def send(request):
        if conformance.server_version(request.runtime_identity['base_url'])!=request.runtime_identity['server_version']:
            raise ValueError('Server version changed before send')
        return requests.ollama_transport(request)
    store=requests.ReceiptStore(Path(input_path).parent/'execution')
    result=run_recipe(packet,store,send)
    return {k:v for k,v in result.items() if k not in ('reading','observations')} | dict(results=str(store.root/'results.json'))
