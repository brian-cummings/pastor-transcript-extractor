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
STOPPED='44f9c346c738da535f729cdac43c559cea14306b5e07f3f4b0ec276dfc4735f3'


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
        body['messages']=[dict(role='system',content=contract_packet['reader_prompt']),
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
            schema_transport_version=context.SCHEMA_TRANSPORT_VERSION,
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
    if path==(directory(base_dir,STOPPED)/'input.json').resolve():
        return prepare_continuation(path,base_dir,check_only=check_only)
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


def prepare_continuation(path,base_dir=None,*,check_only=False):
    """Resume only the demonstrated unsent retry; import all three completed calls."""
    path=Path(path);prior=json.loads(path.read_text());root=path.parent/'execution'
    result=json.loads((root/'results.json').read_text())
    if prior['input_fingerprint']!=STOPPED or digest({k:v for k,v in prior.items() if k!='input_fingerprint'})!=STOPPED:
        raise ValueError('Stopped input identity changed')
    if (result['input_fingerprint']!=STOPPED or result['processed_windows']!=1 or result['completed_windows']!=0
        or result['cases'][0]['halt']!='DeepInfra input exceeds reservation; no truncation'
        or result['accounting']['attempts']!=3 or result['accounting']['unknown_usage_attempts']!=0
        or result['accounting']['cumulative_paid_attempts']!=35 or five.accounting(root,prior)!=result['accounting']):
        raise ValueError('Continuation requires the accounted three-call request-fit stop')
    packet,_=prepare(prior['history']['prior_input'],base_dir,check_only=True)
    if (prior['schema']!=context.schema() or prior['policy']['review_template']!=context.REVIEW_TEMPLATE
        or prior['policy']['binding_retry_template']!=binding_retry.TEMPLATE
        or prior['policy']['verifier_fields']!=list(context.FIELDS)
        or prior['published_model_metadata']!=packet['published_model_metadata']):
        raise ValueError('Stopped semantic/model policy differs')
    for name in ('pastor_evidence','theological_binding','binding_evidence','learning_demo_contracts',
                 'learning_demo_field_check','learning_demo_uncertainty','reading_diagnostics','deepinfra_requests'):
        if prior['code_identity'][name]!=packet['code_identity'][name]: raise ValueError('Stopped evidence semantics changed')
    for filename,sha in prior['history']['preserved_files'].items():
        if demo.file_hash(Path(filename))!=sha: raise ValueError('Stopped history changed')
    if len(prior['cases'])!=5: raise ValueError('Stopped case inventory changed')
    for old,new in zip(prior['cases'],packet['cases'],strict=True):
        if old['case_id']!=new['case_id'] or old['window']!=new['window'] or context.without_duplicate_schema(old['request']['body'])!=new['request']['body']:
            raise ValueError('Continuation changes more than duplicated schema transport')
    case=packet['cases'][0];case_root=root/case['case_id']
    saved=json.loads((case_root/'results.json').read_text())
    if saved['initial']['errors'] or not saved['initial']['observations'] or saved['before'] is None:
        raise ValueError('Initial stages are not reusable')
    seeds=dict(initial=five.load_seed(case_root/'initial',saved['initial']),before=five.load_seed(case_root/'before'),
        review=five.load_seed(case_root/'revision/review'))
    for name in ('initial','review'): seeds[name]['body_compatibility']=context.SCHEMA_TRANSPORT_VERSION
    seeds['review']['raw_response_ref']='revision/review/receipts/'+requests.RequestSpec(**seeds['review']['receipt']['request']).fingerprint+'.json'
    window=SourceWindow(**case['window']);old_initial=requests.RequestSpec(**seeds['initial']['receipt']['request'])
    if asdict(old_initial)!=prior['cases'][0]['request']: raise ValueError('Initial receipt producer differs')
    checked=context.inspect(seeds['initial']['receipt']['response']['output'],window,model=hosted.FLASH_MODEL,
        prompt_digest=digest(old_initial.body['messages']),raw_response_ref=seeds['initial']['raw_response_ref'])
    if checked!=saved['initial']: raise ValueError('Saved initial validation differs')
    verify,candidates=context.verification(window,checked['observations'])
    if asdict(verify)!=seeds['before']['receipt']['request']: raise ValueError('Verifier receipt is not exactly compatible')
    verdict=five.feedback.judgments(seeds['before']['receipt']['response'],verify,candidates)
    def ordered_verdict(value):
        return {**value,'feedback':sorted(value['feedback'],key=lambda row:(row['binding_id'],row['field']))}
    if ordered_verdict(verdict)!=ordered_verdict(saved['before']): raise ValueError('Saved verifier verdict differs')
    scores=context.review_scores(verify,verdict)
    spec=five.correction.corrective_request(dict(request=case['request'],correction=dict(template=context.REVIEW_TEMPLATE)),
        seeds['initial']['receipt']['response']['output'],scores)
    old_review=requests.RequestSpec(**seeds['review']['receipt']['request'])
    if context.without_duplicate_schema(old_review.body)!=spec.body: raise ValueError('Saved revision task differs')
    review_check=context.inspect(seeds['review']['receipt']['response']['output'],window,model=hosted.FLASH_MODEL,
        prompt_digest=digest(old_review.body['messages']),raw_response_ref=seeds['review']['raw_response_ref'])
    stored=json.loads((case_root/'revision/review/binding-validation/attempt-1.json').read_text())
    if any(stored.get(k)!=review_check[k] for k in review_check): raise ValueError('Saved revision validation differs')
    if not review_check['errors']: raise ValueError('No pending binding retry')
    pending=binding_retry.retry_request(spec,seeds['review']['receipt']['response'],review_check['errors'],contextual=True)
    packet['continuation_preflight']=dict(request=asdict(pending),token_account=pending.preflight())
    case['seeds']=seeds
    # First case needs its unsent binding retry and one verifier recheck; other
    # four retain the original full per-case allowance. Imported calls cost zero.
    flash=17;typesafe=9;reserved=flash*hosted.reserved_usd(requests.DEEPINFRA_BINDING_VERSION)+typesafe*requests.reservation('source_verification')
    account=result['accounting']
    packet['budget'].update(maximum_attempts=26,maximum_paid_attempts=26,flash_attempts=flash,typesafe_attempts=typesafe,
        reserved_usd=str(reserved),cumulative_maximum_attempts=account['cumulative_attempts']+26,
        cumulative_maximum_paid_attempts=account['cumulative_paid_attempts']+26)
    if packet['budget']['cumulative_maximum_paid_attempts']>66 or Decimal(account['cumulative_known_list_price_usage_usd'])+reserved>2:
        raise ValueError('Continuation exceeds cumulative attempt or dollar ceiling')
    files=[path,*sorted(p for p in root.rglob('*.json') if p.name!='source-context-authorization.json')]
    packet['history'].update(prior_input=str(path),prior_attempts=account['cumulative_attempts'],
        prior_local_attempts=account['cumulative_local_attempts'],prior_paid_attempts=account['cumulative_paid_attempts'],
        prior_known_list_price_usage_usd=account['cumulative_known_list_price_usage_usd'])
    packet['history']['preserved_files'].update({str(p):demo.file_hash(p) for p in files})
    packet['reuse_audit']['continuation']='Import original initial/review responses and exact TypeSafe receipt without rebilling; preserve original producer provenance. Only exact schema-text deduplication is compatible.'
    packet['continuation_from']=str(path)
    packet.pop('input_fingerprint',None);packet['input_fingerprint']=digest(packet)
    out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        context.export(base_dir)
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        (out/'preparation.md').write_text('# Request-fit continuation\n\nReuse all three completed calls from the stopped first case. '
            'First new call is its binding retry, followed by TypeSafe recheck. Remaining four sources are unchanged. '
            'Strict schema is retained once in response_format; only duplicated system schema text is removed. '
            'No source, model, threshold, evidence or answer changes by code. Maximum 26 new paid calls; reservation $'+str(reserved)+
            ', ceiling $1.02; cumulative maximum 61 paid calls and reserved plus prior usage below $2.\n\n```sh\n'+command(out,packet,base_dir)+'\n```\n')
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
