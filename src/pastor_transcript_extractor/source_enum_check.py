"""One synthetic nested-field diagnostic; never resumes source extraction."""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal,InvalidOperation
import json
from pathlib import Path
from httpx import HTTPError

from . import evidence_requests as requests
from . import deepinfra_requests as hosted
from . import learning_demo as demo
from . import learning_demo_five_windows as five
from . import learning_demo_contracts as contract
from . import reading_diagnostics as diagnostics
from . import source_context
from .pastor_evidence import EvidenceArtifactStore,digest

VERSION='source-nested-enum-check-v1'
PRIOR='7b59af856f778ac62e4dd676c52f7083b1822b1bdd1abe65f524582954051337'
SOURCE='Gardeners, please water the seedlings.'
LIMITATION='One synthetic guided request with a reduced schema. Not an isolated ablation, root-cause proof, source accuracy check or production admission.'


def field_guide(schema,path='$'):
    """Derive field types and allowed values from the authoritative schema."""
    typ=schema['type'];lines=[path+': '+typ+(' = '+requests.wire(schema['enum']) if 'enum' in schema else '')]
    if typ=='object':
        for key,value in schema['properties'].items(): lines.extend(field_guide(value,path+'.'+key))
    elif typ=='array': lines.extend(field_guide(schema['items'],path+'[]'))
    return lines


def schema():
    original=source_context.schema()['properties']['claims']['items']['properties']
    act=original['address_acts']['items']['properties']
    return contract.obj(claims=contract.array(contract.obj(
        address_acts=contract.array(contract.obj(addressee=deepcopy(act['addressee']),adoption=deepcopy(act['adoption'])),1),
        adoption=deepcopy(original['adoption'])),1))


def request():
    shape=schema()
    prompt=('This is a synthetic field-contract check. Return compact JSON under the supplied strict schema. '
        'Produce exactly one claim with exactly one address act. The speaker is speaking directly in their own voice '
        'to the current listeners, not quoting or reporting someone else. Copy the complete supplied utterance '
        'verbatim for required evidence; give a nonempty source-based rationale. '
        'Each field has its own type and vocabulary; do not use a sibling field\'s type or enum.\n'
        'Field/type/vocabulary guide (derived mechanically from the schema):\n'+'\n'.join(field_guide(shape)))
    body=dict(model=hosted.FLASH_MODEL,messages=[dict(role='system',content=prompt),
        dict(role='user',content=requests.wire(dict(synthetic=True,utterance=SOURCE)))],
        max_tokens=1024,temperature=0,top_p=1,stream=False,n=1,reasoning_effort='none',
        response_format=dict(type='json_schema',json_schema=dict(name='qualified_source_reading',strict=True,schema=shape)))
    return requests.RequestSpec('source_reading',body,dict(synthetic=True,version=VERSION),namespace=hosted.ENUM_NAMESPACE,
        version=requests.DEEPINFRA_ENUM_VERSION,runtime_identity=hosted.ENUM_POLICY)


def assess(output):
    try: value=contract.strict_json(output)
    except ValueError as error: return dict(status='FAIL(component)',errors=[str(error)])
    errors=diagnostics.shape_errors(value,schema())
    if errors: return dict(status='FAIL(component)',errors=errors)
    if len(value['claims'])!=1 or len(value['claims'][0]['address_acts'])!=1:
        return dict(status='FAIL(component)',errors=['Expected exactly one synthetic claim and one address act'])
    row=value['claims'][0];act=row['address_acts'][0];quote=dict(source_field='target_text',text=SOURCE)
    checks=dict(address_adoption=act['adoption']=='own_or_adopted',
        direct_addressee=act['addressee']['kind']=='direct_current_listener',
        claim_adoption=row['adoption']['status']=='own_assertion' and row['adoption']['basis']=='own_speech',
        address_evidence=act['addressee']['evidence']==[quote],claim_evidence=row['adoption']['evidence']==[quote],
        rationale=bool(row['adoption']['rationale'].strip()))
    return dict(status='PASS' if all(checks.values()) else 'FAIL(component)',checks=checks,errors=[])


def identity():
    modules=(requests,hosted,source_context,contract,diagnostics)
    return {m.__name__.rsplit('.',1)[-1]:demo.file_hash(Path(m.__file__)) for m in modules}|{'source_enum_check':demo.file_hash(Path(__file__))}


def directory(base_dir,fp):
    root=demo.build_paths(base_dir).evaluation/'deepinfra-nested-enum-check'/fp
    if root.resolve().is_relative_to(Path(__file__).parents[2].resolve()): raise ValueError('Artifacts must be outside repository')
    return root


def prepare(prior_input,base_dir=None,*,check_only=False):
    from .source_context_trial import directory as source_directory
    path=Path(prior_input).resolve()
    if path!=(source_directory(base_dir,PRIOR)/'input.json').resolve(): raise ValueError('Requires the completed whitespace-stall source-context input')
    prior=json.loads(path.read_text());root=path.parent/'execution';result=json.loads((root/'results.json').read_text())
    if prior['input_fingerprint']!=PRIOR or digest({k:v for k,v in prior.items() if k!='input_fingerprint'})!=PRIOR:
        raise ValueError('Prior input changed')
    if (result['input_fingerprint']!=PRIOR or result['processed_windows']!=2 or result['completed_windows']!=1
        or result['accounting']['unknown_usage_attempts']!=0 or result['accounting']['cumulative_paid_attempts']!=38
        or result['cases'][1]['halt']!="Incomplete DeepInfra response (finish_reason='length'); no repair/retry"
        or five.accounting(root,prior)!=result['accounting']): raise ValueError('Prior result is not the accounted output-length stop')
    metadata=hosted.public_model_metadata(hosted.FLASH_MODEL)
    if metadata!=prior['published_model_metadata']: raise ValueError('Pinned model deployment or prices changed')
    spec=request();account=result['accounting'];reserve=hosted.reserved_usd(spec.version)
    if account['cumulative_paid_attempts']+1>66 or Decimal(account['cumulative_known_list_price_usage_usd'])+reserve>2:
        raise ValueError('Cumulative experiment budget exceeded')
    files=[path,*sorted(p for p in root.rglob('*.json') if p.name!='nested-enum-authorization.json')]
    packet=dict(version=VERSION,request=asdict(spec),schema=schema(),field_guide=field_guide(schema()),
        token_account=spec.preflight(),code_identity=identity(),published_model_metadata=metadata,
        policy=dict(synthetic_only=True,retries=0,source_calls=0,production_admission=False),
        budget=dict(maximum_attempts=1,maximum_paid_attempts=1,max_usd='0.003',reserved_usd=str(reserve),
            cumulative_maximum_paid_attempts=account['cumulative_paid_attempts']+1),
        history=dict(prior_input=str(path),prior_attempts=account['cumulative_attempts'],
            prior_local_attempts=account['cumulative_local_attempts'],prior_paid_attempts=account['cumulative_paid_attempts'],
            prior_known_list_price_usage_usd=account['cumulative_known_list_price_usage_usd'],
            preserved_files={str(p):demo.file_hash(p) for p in files}),limitation=LIMITATION)
    packet['input_fingerprint']=digest(packet);out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        (out/'preparation.md').write_text('# Synthetic nested adoption-field check\n\n'+LIMITATION+
            '\n\nOne Flash 1017 request, reasoning disabled, 1,024 output tokens, no retry. '
            'The nested address-act adoption string and claim adoption object reuse their existing schemas and enum meanings. '
            'No pastor source text, saved extraction answers, verifier or admission is used. '
            'Automatic provider caching only; no requested TTL or paid retention.\n\n```sh\n'+command(out,packet,base_dir)+'\n```\n')
    return packet,out


def command(out,packet,base_dir):
    return (f'pte analysis learning-demo model-fit deepinfra-enum-run --base-dir {demo.build_paths(base_dir).root} '
        f'--input {out/"input.json"} --experimental --approve-input {packet["input_fingerprint"]} --max-usd 0.003 --confirm-prices --json')


def run_recipe(packet,root,transport):
    root=Path(root);store=requests.ReceiptStore(root)
    if (root/'results.json').exists():
        saved=json.loads((root/'results.json').read_text())
        if saved['input_fingerprint']!=packet['input_fingerprint']: raise ValueError('Foreign synthetic result')
        return saved
    halt=None;assessment=None
    try:
        spec=requests.RequestSpec(**packet['request'])
        response=requests.execute(spec,hosted.OneRequestLedger('0.003',spec.version),store,transport)
        assessment=assess(response['output'])
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: halt=str(error)
    usage=demo.usage_account(store);history=packet['history']
    usage.update(cumulative_attempts=history['prior_attempts']+usage['attempts'],
        cumulative_paid_attempts=history['prior_paid_attempts']+usage['paid_attempts'],
        cumulative_known_list_price_usage_usd=str(Decimal(history['prior_known_list_price_usage_usd'])+Decimal(usage['known_list_price_usage_usd'])))
    result=dict(input_fingerprint=packet['input_fingerprint'],status=assessment['status'] if assessment and not halt else 'FAIL(component)',
        halt=halt,assessment=assessment,accounting=usage,production_admission=False,limitation=LIMITATION,
        next_step='Review this synthetic result; no automatic source retry or workflow advancement')
    store.write_immutable('results.json',result);demo._write_report(root.parent,result)
    return result


def run(input_path,base_dir=None,*,experimental=False,approve_input=None,max_usd='0.003',confirm_prices=False,check_only=False,progress=None):
    path=Path(input_path);packet=json.loads(path.read_text());fp=packet['input_fingerprint']
    if digest({k:v for k,v in packet.items() if k!='input_fingerprint'})!=fp or path.resolve()!=(directory(base_dir,fp)/'input.json').resolve():
        raise ValueError('Frozen input identity or location changed')
    expected,_=prepare(packet['history']['prior_input'],base_dir,check_only=True)
    if expected!=packet: raise ValueError('Frozen contract, model, code, history or budget changed')
    try: cap=Decimal(max_usd)
    except InvalidOperation as error: raise ValueError('Invalid ceiling') from error
    if not cap.is_finite() or not Decimal(packet['budget']['reserved_usd'])<=cap<=Decimal('0.003'):
        raise ValueError('Reserve the request within $0.003')
    if check_only: return dict(status='PREPARED_NO_EXECUTION',budget=packet['budget'],generation_calls=0,paid_calls=0)
    if not experimental or approve_input!=fp or not confirm_prices: raise ValueError('Use --experimental --approve-input exact fingerprint --confirm-prices')
    root=path.parent/'execution'
    if not (root/'results.json').exists() and not hosted.credential_present(): raise ValueError('DEEPINFRA_API_KEY required; no attempt started')
    marker=Path(packet['history']['prior_input']).parent/'execution'
    EvidenceArtifactStore(marker).write_immutable('nested-enum-authorization.json',dict(input_fingerprint=fp))
    EvidenceArtifactStore(root).write_immutable('authorization.json',dict(input_fingerprint=fp,max_usd=str(cap)))
    if progress:
        progress('Reusing saved synthetic result; no generation call' if (root/'results.json').exists() else
            'One synthetic nested adoption-field check; Flash 1017; reasoning disabled; 1,024 output tokens; no retry')
    return run_recipe(packet,root,hosted.transport)|dict(results=str(root/'results.json'))
