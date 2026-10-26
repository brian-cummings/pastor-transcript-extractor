"""Freeze the existing five windows under the explicit context contract; no expansion."""
from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal,InvalidOperation
import json
import os
from pathlib import Path

from . import learning_demo as demo
from . import learning_demo_five_windows as five
from . import learning_demo_model_fit as fit
from . import source_context as context
from . import binding_retry
from . import deepinfra_requests as hosted
from . import evidence_requests as requests
from .pastor_evidence import EvidenceArtifactStore,SourceWindow,digest

VERSION='learning-demo-source-context-v1'
PRIOR='e833b447eac9d341bb5c2e5191f35ff0743e64e141929c778e111e6b951eb658'


def directory(base_dir,fingerprint):
    root=demo.build_paths(base_dir).evaluation/'learning-demo-source-context'/fingerprint
    if root.resolve().is_relative_to(Path(__file__).parents[2].resolve()): raise ValueError('Artifacts must be outside repository')
    return root


def identity():
    return {**demo.code_identity(),**{m.__name__.rsplit('.',1)[-1]:demo.file_hash(Path(m.__file__))
        for m in (context,binding_retry,five,fit,hosted)},'source_context_trial':demo.file_hash(Path(__file__)),
        **{m.__name__.rsplit('.',1)[-1]:demo.file_hash(Path(m.__file__)) for m in (
            context.fields,context.review,context.thinking,context.diagnostics,five.feedback,five.correction)}}


def build(prior,result,contract_packet):
    """Pure construction from checked frozen sources; old answers are not runtime inputs."""
    cases=[]
    for case in prior['cases']:
        old=requests.RequestSpec(**case['request']);window=SourceWindow(**case['window'])
        state=demo._source_state(window)
        expected=dict(texts=state['texts'],block_mapping=state['block_mapping'],
            source_identity={k:v for k,v in case['window'].items() if k!='blocks'},target_scope='declared_blocks_only')
        if requests.wire(json.loads(old.body['messages'][1]['content']))!=requests.wire(expected):
            raise ValueError('Saved source message differs from the complete frozen window')
        body=deepcopy(old.body)
        body['messages']=[dict(role='system',content=contract_packet['reader_prompt']+'\nOutput schema: '+requests.wire(context.schema())),
                          deepcopy(old.body['messages'][1])]
        body['response_format']['json_schema']['schema']=context.schema()
        spec=replace(old,body=body,version=requests.DEEPINFRA_BINDING_VERSION,
            namespace=hosted.BINDING_NAMESPACE,runtime_identity=hosted.BINDING_POLICY)
        context.validate_request(spec)
        cases.append(dict(case_id=case['case_id'],window=deepcopy(case['window']),request=asdict(spec),token_account=spec.preflight()))
    n=len(cases);flash=4*n;typesafe=2*n
    reserved=flash*hosted.reserved_usd(requests.DEEPINFRA_BINDING_VERSION)+typesafe*requests.reservation('source_verification')
    account=result['accounting']
    if account['cumulative_paid_attempts']+flash+typesafe>66:
        raise ValueError('Prepared requests exceed cumulative 66 paid attempts')
    if Decimal(account['cumulative_known_list_price_usage_usd'])+reserved>Decimal('2'):
        raise ValueError('Prepared reservation exceeds cumulative $2 ceiling')
    return dict(schema_version=VERSION,cases=cases,schema=context.schema(),code_identity=identity(),
        contract_fingerprint=contract_packet['contract_fingerprint'],published_model_metadata=prior['published_model_metadata'],
        policy=dict(source_context_version=context.VERSION,binding_retries=1,
            initial_prompt=cases[0]['request']['body']['messages'][0]['content'],review_template=context.REVIEW_TEMPLATE,
            binding_retry_template=binding_retry.TEMPLATE,verifier_fields=list(context.FIELDS),
            pass_at_least=context.fields.PASS,fail_at_most=context.fields.FAIL,max_reviews_per_window=1,
            binding_retries_per_stage=1,manual_repairs=0,fallbacks=0,production_admission=False),
        selection=deepcopy(prior['selection']),
        reuse_audit=dict(source='Reuse the same five complete frozen windows and source messages, in their existing order',
            observations='New explicit abstention schema and reader prompt; saved old-schema answers are not compatible runtime inputs',
            verification='Old qualification/polarity meanings retained; complete new request includes context sufficiency and new bindings; no compatible complete receipt',
            historical_exposure='All five windows were reviewed previously; this is not blinded accuracy validation'),
        budget=dict(maximum_attempts=flash+typesafe,maximum_paid_attempts=flash+typesafe,flash_attempts=flash,
            typesafe_attempts=typesafe,reserved_usd=str(reserved),max_usd='1.02',maximum_claims_per_window=2,
            maximum_abstentions_per_window=2,maximum_reviews=n,maximum_binding_retries=2*n,
            cumulative_maximum_attempts=account['cumulative_attempts']+flash+typesafe,
            cumulative_maximum_paid_attempts=account['cumulative_paid_attempts']+flash+typesafe,
            cumulative_paid_attempt_ceiling=66,cumulative_usd_ceiling='2',transport_retries=0),
        history=dict(prior_attempts=account['cumulative_attempts'],prior_local_attempts=account['cumulative_local_attempts'],
            prior_paid_attempts=account['cumulative_paid_attempts'],prior_known_list_price_usage_usd=account['cumulative_known_list_price_usage_usd']),
        limitation='Same five previously exposed windows under a new reader/context contract. Feasibility only; scores do not establish accuracy, coverage, calibration or production admission.')


def prepare(prior_input,base_dir=None,*,check_only=False):
    path=Path(prior_input).resolve()
    if path!=(five.directory(base_dir,PRIOR)/'input.json').resolve(): raise ValueError('Requires the completed five-window binding-retry input')
    prior=json.loads(path.read_text());root=path.parent/'execution';result=json.loads((root/'results.json').read_text())
    if prior['input_fingerprint']!=PRIOR or digest({k:v for k,v in prior.items() if k!='input_fingerprint'})!=PRIOR:
        raise ValueError('Historical input identity changed')
    if (result['input_fingerprint']!=PRIOR or result['completed_windows']!=5 or result['processed_windows']!=5
        or result['accounting']['unknown_usage_attempts']!=0 or result['accounting']['cumulative_attempts']!=60
        or result['accounting']['cumulative_paid_attempts']!=32 or any(c['halt'] for c in result['cases'])):
        raise ValueError('Prior batch is not the completed, accounted five-window result')
    if five.accounting(root,prior)!=result['accounting']:
        raise ValueError('Prior batch accounting differs from preserved attempts and receipts')
    for filename,sha in prior['history']['preserved_files'].items():
        if demo.file_hash(Path(filename))!=sha: raise ValueError('Historical evidence changed')
    current=identity()
    for name in ('pastor_evidence','theological_binding','binding_evidence','learning_demo_contracts',
                 'learning_demo_field_check','learning_demo_uncertainty','reading_diagnostics','deepinfra_requests'):
        if prior['code_identity'][name]!=current[name]: raise ValueError('Existing evidence or model policy changed')
    source_path=Path(prior['history']['six_window_input'])
    if source_path.resolve()!=(fit.directory(base_dir,five.SIX)/'input.json').resolve(): raise ValueError('Source lineage changed')
    sources=json.loads(source_path.read_text())
    if sources['input_fingerprint']!=five.SIX or digest({k:v for k,v in sources.items() if k!='input_fingerprint'})!=five.SIX:
        raise ValueError('Frozen source packet changed')
    fit.verify_sources(sources,base_dir)
    expected=fit.select_cases(sources)[1:]
    windows={w['id']:w for w in sources['windows']}
    if ([c['case_id'] for c in prior['cases']]!=expected or len(expected)!=5
        or any(c['window']!=windows[c['case_id']] for c in prior['cases'])):
        raise ValueError('Exact five-window selection or geometry changed')
    if hosted.public_model_metadata(hosted.FLASH_MODEL)!=prior['published_model_metadata']:
        raise ValueError('Flash deployment or published prices changed')
    contract_packet=context.contract_packet()
    if not check_only: context.export(base_dir)
    packet=build(prior,result,contract_packet)
    files=[path,source_path,*sorted(p for p in root.rglob('*.json') if p.name!='source-context-authorization.json')]
    reusable={case['case_id']:five.compatible_receipts(requests.RequestSpec(**case['request']),
        [*prior['history']['preserved_files'],*files]) for case in packet['cases']}
    if any(reusable.values()): raise ValueError('Compatible saved reader receipt found; resolve reuse before new execution')
    packet['reuse_audit']['compatible_reader_receipts']=reusable
    packet['history'].update(prior_input=str(path),six_window_input=str(source_path),
        preserved_files={**prior['history']['preserved_files'],**{str(p):demo.file_hash(p) for p in files}})
    packet['input_fingerprint']=digest(packet);out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        (out/'preparation.md').write_text('# Source-context five-window check\n\n'+packet['limitation']+
            '\n\nSame Flash 1017 model, reasoning disabled. TypeSafe checks qualifications, polarity and context sufficiency '
            'for every substantive claim before and after one semantic correction. One binding retry per Flash stage. '
            'Explicit abstentions remain audit records. No manual answers or review labels enter requests. '
            'Maximum 30 new paid attempts; reservation $'+packet['budget']['reserved_usd']+', ceiling $1.02. '
            'Cumulative maximum 62 paid attempts and reserved plus prior list-price usage below $2.\n\n```sh\n'+command(out,packet,base_dir)+'\n```\n')
    return packet,out


def command(out,packet,base_dir):
    return (f'pte analysis learning-demo model-fit source-context-run --base-dir {demo.build_paths(base_dir).root} '
        f'--input {out/"input.json"} --experimental --approve-input {packet["input_fingerprint"]} '
        '--max-usd 1.02 --confirm-prices --json')


def run(input_path,base_dir=None,*,experimental=False,approve_input=None,max_usd='1.02',confirm_prices=False,check_only=False,progress=None):
    path=Path(input_path);packet=json.loads(path.read_text());fp=packet['input_fingerprint']
    if digest({k:v for k,v in packet.items() if k!='input_fingerprint'})!=fp or path.resolve()!=(directory(base_dir,fp)/'input.json').resolve():
        raise ValueError('Frozen input identity or location changed')
    expected,_=prepare(packet['history']['prior_input'],base_dir,check_only=True)
    if expected!=packet: raise ValueError('Source, contract, implementation, metadata or budget changed after freeze')
    try: cap=Decimal(max_usd)
    except InvalidOperation as error: raise ValueError('Invalid dollar ceiling') from error
    if not cap.is_finite() or not Decimal(packet['budget']['reserved_usd'])<=cap<=Decimal(packet['budget']['max_usd']):
        raise ValueError('Reserve the complete plan within $1.02')
    if check_only: return dict(status='PREPARED_NO_EXECUTION',budget=packet['budget'],generation_calls=0,paid_calls=0)
    if not experimental or approve_input!=fp or not confirm_prices:
        raise ValueError('Use --experimental --approve-input exact fingerprint --confirm-prices')
    root=path.parent/'execution'
    if not (root/'results.json').exists() and (not hosted.credential_present() or not os.environ.get('TYPESAFE_API_KEY','').strip()):
        raise ValueError('Both API credentials required; no attempts started')
    marker=Path(packet['history']['prior_input']).parent/'execution/source-context-authorization.json'
    EvidenceArtifactStore(marker.parent).write_immutable(marker.name,dict(input_fingerprint=fp))
    EvidenceArtifactStore(root).write_immutable('authorization.json',dict(input_fingerprint=fp,max_usd=str(cap),maximum_attempts=packet['budget']['maximum_attempts'],confirm_prices=True))
    result=five.run_recipe(packet,root,hosted.transport,requests.typesafe_transport,progress=progress)
    return result | dict(results=str(root/'results.json'),review_packet=str(root/'source-review-packet.json'))
