"""Fixed remaining-five source validation with the frozen uncertainty-review loop."""
from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal,InvalidOperation
import json
import os
from pathlib import Path
from httpx import HTTPError

from . import learning_demo as demo
from . import learning_demo_uncertainty as review
from . import learning_demo_field_check as fields
from . import learning_demo_feedback as feedback
from . import learning_demo_correction as correction
from . import learning_demo_model_fit as fit
from . import reading_diagnostics as diagnostics
from . import deepinfra_requests as hosted
from . import evidence_requests as requests
from .pastor_evidence import EvidenceArtifactStore,SourceWindow,digest

VERSION='learning-demo-remaining-five-v1'
PRIOR='371b63c2f0af50190dd3f5406210f7b6e96b3f75c510f16cb01638aa63ac1014'
DEVELOPMENT='P318-R3973-theology'
SIX='44be6c3265a426ef9197e94cfa66830a5ed9cb9ac7af3fc712978335b0f4efca'


def directory(base_dir,fingerprint):
    path=demo.build_paths(base_dir).evaluation/'learning-demo-remaining-five'/fingerprint
    if path.resolve().is_relative_to(Path(__file__).parents[2].resolve()): raise ValueError('Artifacts must be outside repository')
    return path


def compatible_receipts(spec,files):
    matches=[]
    for filename in files:
        if '/receipts/' not in str(filename): continue
        saved=json.loads(Path(filename).read_text());producer=saved.get('request',{})
        if (not saved.get('halt') and producer.get('phase')==spec.phase and producer.get('body')==spec.body
            and producer.get('source_identity')==spec.source_identity
            and {k:v for k,v in producer.get('runtime_identity',{}).items() if k!='maximum_usd'}==
                {k:v for k,v in spec.runtime_identity.items() if k!='maximum_usd'}):
            matches.append(str(filename))
    return matches


def prepare(prior_input,base_dir=None,*,check_only=False):
    path=Path(prior_input).resolve()
    if path!=(review.directory(base_dir,PRIOR)/'input.json').resolve(): raise ValueError('Requires the closed uncertainty-review experiment')
    prior=json.loads(path.read_text())
    if prior['input_fingerprint']!=PRIOR or digest({k:v for k,v in prior.items() if k!='input_fingerprint'})!=PRIOR:
        raise ValueError('Prior input changed')
    expected,_=review.prepare(prior['history']['prior_input'],base_dir,check_only=True)
    if expected!=prior: raise ValueError('Prior source, policies, implementation or metadata changed')
    old_store=requests.ReceiptStore(path.parent/'execution/review')
    result=json.loads((path.parent/'execution/results.json').read_text())
    if (result['input_fingerprint']!=PRIOR or result['status']!='FAIL(component)' or result['halt'] is not None
        or not result['mechanical']['errors'] or result['after'] is not None
        or result['accounting']['attempts']!=1 or result['accounting']['unknown_usage_attempts']!=0
        or result['accounting']['cumulative_attempts']!=35 or len(old_store.attempts())!=1):
        raise ValueError('Prior experiment is not the reviewed one-response mechanical stop')
    old=requests.RequestSpec(**prior['request'])
    receipt=json.loads((old_store.root/'receipts'/f'{old.fingerprint}.json').read_text())
    if receipt['request']!=prior['request'] or receipt['response_digest']!=digest(receipt['response']) or receipt['halt']:
        raise ValueError('Prior review receipt changed')
    checked=diagnostics.inspect(receipt['response']['output'],prior['schema'],SourceWindow(**prior['window']),
        model=hosted.FLASH_MODEL,prompt_digest=digest(old.body['messages']),
        raw_response_ref='review/receipts/'+old.fingerprint+'.json')
    if checked!=result['mechanical']: raise ValueError('Prior mechanical findings no longer match preserved response')
    ancestor=prior;ancestor_path=path
    while 'source_requests' not in ancestor:
        ancestor_path=Path(ancestor['history']['prior_input']);ancestor=json.loads(ancestor_path.read_text())
    if ancestor['input_fingerprint']!=SIX or ancestor_path.resolve()!=(fit.directory(base_dir,SIX)/'input.json').resolve():
        raise ValueError('Frozen six-window lineage changed')
    fit.verify_sources(ancestor,base_dir)
    cases=ancestor['selection']['cases']
    if cases!=fit.select_cases(ancestor) or cases[0]!=DEVELOPMENT or len(cases)!=6:
        raise ValueError('Frozen source selection changed')
    windows={w['id']:w for w in ancestor['windows']};source_requests={s['case_id']:s for s in ancestor['source_requests']}
    base=replace(old,body={**deepcopy(old.body),'messages':deepcopy(old.body['messages'][:2])})
    prepared=[];reuse_matches={}
    for case in cases[1:]:
        source=requests.RequestSpec(**source_requests[case]['request'])
        spec=replace(base,body={**deepcopy(base.body),'messages':[
            deepcopy(base.body['messages'][0]),deepcopy(source.body['messages'][1])]},source_identity=deepcopy(source.source_identity))
        state=json.loads(spec.body['messages'][1]['content'])
        expected_state=demo._source_state(SourceWindow(**windows[case]))
        if state!=dict(texts=expected_state['texts'],block_mapping=expected_state['block_mapping'],
            source_identity={k:v for k,v in windows[case].items() if k!='blocks'},target_scope='declared_blocks_only'):
            raise ValueError('Source request no longer matches complete frozen window')
        prepared.append(dict(case_id=case,window=windows[case],request=asdict(spec),token_account=spec.preflight()))
        matches=compatible_receipts(spec,prior['history']['preserved_files'])
        reuse_matches[case]=matches
        if matches: raise ValueError('Compatible Flash constituent found for '+case+'; resolve reuse before any new execution')
    files=[path,*sorted(p for p in (path.parent/'execution').rglob('*.json') if p.name!='remaining-five-authorization.json')]
    reservation=10*(hosted.reserved_usd(base.version)+requests.reservation('source_verification'))
    identities={**demo.code_identity(),**{name:demo.file_hash(Path(module.__file__)) for name,module in (
        ('learning_demo_uncertainty',review),('learning_demo_field_check',fields),('learning_demo_feedback',feedback),
        ('learning_demo_correction',correction),('learning_demo_model_fit',fit),('reading_diagnostics',diagnostics),
        ('deepinfra_requests',hosted))},'learning_demo_five_windows':demo.file_hash(Path(__file__))}
    packet=dict(schema_version=VERSION,cases=prepared,schema=prior['schema'],code_identity=identities,
        published_model_metadata=prior['published_model_metadata'],
        policy=dict(initial_prompt=base.body['messages'][0]['content'],review_template=review.TEMPLATE,
            verifier_fields=list(fields.FIELDS),pass_at_least=fields.PASS,fail_at_most=fields.FAIL,
            review_trigger='Any checked field below 0.90; uncertainty is not proof of error',
            initial_failure='Complete schema/binding failure ends that case; continue only fixed remaining cases',
            execution_failure='Any transport, provider, length, unknown-spend or dynamic-fit halt ends the batch',
            max_reviews_per_window=1,manual_repairs=0,fallbacks=0,production_admission=False),
        selection=dict(cases=cases[1:],excluded_development_case=DEVELOPMENT,profiles=[318,130],windows=5,
            independent_controls=2,policy='Original six-window order minus development window; no result-dependent selection'),
        reuse_audit=dict(source='Exact existing six-window source messages, blocks, geometry, membership and lineage',
            observations='Historical Gemma/Qwen outputs are model/policy-incompatible with this frozen Flash reader; not runtime inputs',
            historical_exposure='These windows appeared in prior local-model trials; remaining cases are not pristine unseen or blinded holdouts',
            compatible_flash_receipts=reuse_matches),
        budget=dict(maximum_attempts=20,maximum_paid_attempts=20,flash_attempts=10,typesafe_attempts=10,
            reserved_usd=str(reservation),max_usd='0.52',maximum_claims_per_window=2,retries=0,
            maximum_reviews=5,cumulative_maximum_attempts=55),
        history=dict(prior_input=str(path),six_window_input=str(ancestor_path),prior_attempts=35,
            prior_local_attempts=28,prior_paid_attempts=7,
            prior_known_list_price_usage_usd=result['accounting']['cumulative_known_list_price_usage_usd'],
            preserved_files={**prior['history']['preserved_files'],**{str(p):demo.file_hash(p) for p in files}}),
        limitation='Fixed remaining-five feasibility validation, not blinded accuracy, threshold calibration, full semantic verification, pastor comparison or production admission.')
    packet['input_fingerprint']=digest(packet);out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        (out/'preparation.md').write_text('# Remaining five windows with TypeSafe correction loop\n\n'+packet['limitation']+
            '\n\nInitial Flash reading, unchanged qualification/polarity TypeSafe checks, one Flash source re-review when any field is below 0.90, then identical TypeSafe recheck. '
            'Prompts, model settings, schema, thresholds and all complete source blocks stay fixed. '
            'Complete initial binding failures end that case without repair; execution/uncertain-spend halts end the entire batch. '
            'All before/after answers and failures are retained. No source-review labels or historical readings enter inference. '
            'These cases were exposed in prior local trials, so they are not a pristine holdout. '
            f'Maximum 20 paid attempts (10 Flash, 10 TypeSafe); full uncached reservation ${reservation}, ceiling $0.52. '
            'Actual use may be lower due to stops or no-review decisions. Both API keys required.\n\nCases:\n\n'+
            '\n'.join('- '+c for c in cases[1:])+'\n\n```sh\n'+command(out,packet,base_dir)+'\n```\n')
    return packet,out


def command(out,packet,base_dir):
    return (f'pte analysis learning-demo model-fit remaining-five-run --base-dir {demo.build_paths(base_dir).root} '
        f'--input {out / "input.json"} --experimental --approve-input {packet["input_fingerprint"]} --max-usd 0.52 --confirm-prices --json')


def run_case(packet,case,root,flash_transport,typesafe_transport,*,progress=None):
    root=Path(root);artifacts=EvidenceArtifactStore(root)
    case_fp=digest(dict(parent=packet['input_fingerprint'],case_id=case['case_id']))
    if (root/'results.json').exists():
        saved=json.loads((root/'results.json').read_text())
        if saved['case_fingerprint']!=case_fp: raise ValueError('Foreign case result')
        return saved
    initial=before=revision=None;halt=None
    try:
        spec=requests.RequestSpec(**case['request']);window=SourceWindow(**case['window'])
        if progress: progress(case['case_id']+': initial Flash reading')
        response=requests.execute(spec,hosted.OneRequestLedger('0.06',spec.version),requests.ReceiptStore(root/'initial'),flash_transport)
        initial=diagnostics.inspect(response['output'],packet['schema'],window,model=hosted.FLASH_MODEL,
            prompt_digest=digest(spec.body['messages']),raw_response_ref='initial/receipts/'+spec.fingerprint+'.json')
        artifacts.write_immutable('initial-validation.json',initial)
        if not initial['errors'] and initial['observations']:
            verify,candidates=fields.verification(window,initial['observations'])
            artifacts.write_immutable('before-request.json',asdict(verify))
            if progress: progress(case['case_id']+': TypeSafe initial check')
            verdict=requests.execute(verify,requests.BudgetLedger(max_attempts=1,max_usd='0.003'),requests.ReceiptStore(root/'before'),typesafe_transport)
            before=feedback.judgments(verdict,verify,candidates);artifacts.write_immutable('before-judgments.json',before)
            scores=review.review_scores(verify,before)
            if any(s['review_requested'] for s in scores):
                revised=correction.corrective_request(dict(request=asdict(spec),correction=dict(template=review.TEMPLATE)),response['output'],scores)
                recipe=dict(input_fingerprint=case_fp,request=asdict(revised),window=case['window'],schema=packet['schema'],
                    original_output=response['output'],scores=scores,limitation=packet['limitation'],
                    history=dict(prior_attempts=0,prior_local_attempts=0,prior_paid_attempts=0,prior_known_list_price_usage_usd='0'))
                artifacts.write_immutable('revision-input.json',recipe)
                revision=review.run_recipe(recipe,root/'revision',flash_transport,typesafe_transport,
                    progress=(lambda message:progress(case['case_id']+': '+message)) if progress else None)
                halt=revision['halt']
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: halt=str(error)
    mechanical_failure=initial is not None and bool(initial['errors'])
    if revision is not None and revision['mechanical'] is not None:
        mechanical_failure=mechanical_failure or bool(revision['mechanical']['errors'])
    result=dict(case_id=case['case_id'],case_fingerprint=case_fp,
        status='FAIL(component)' if halt or mechanical_failure else 'INCONCLUSIVE',halt=halt,
        initial=initial,before=before,revision=revision,production_admission=False)
    artifacts.write_immutable('results.json',result)
    return result


def accounting(root,packet):
    accounts=[]
    for case in packet['cases']:
        base=Path(root)/case['case_id']
        for name in ('initial','before','revision/review','revision/after'):
            accounts.append(demo.usage_account(requests.ReceiptStore(base/name)))
    value={k:sum(a[k] for a in accounts) for k in ('attempts','local_attempts','paid_attempts','openai_calls','known_input_tokens','known_output_tokens','unknown_usage_attempts')}
    for key in ('reserved_usd','known_list_price_usage_usd','known_provider_estimated_usage_usd'):
        value[key]=str(sum((Decimal(a.get(key,'0')) for a in accounts),Decimal(0)))
    history=packet['history'];value.update(prior_attempts=history['prior_attempts'],
        cumulative_attempts=history['prior_attempts']+value['attempts'],
        cumulative_local_attempts=history['prior_local_attempts']+value['local_attempts'],
        cumulative_paid_attempts=history['prior_paid_attempts']+value['paid_attempts'],
        cumulative_known_list_price_usage_usd=str(Decimal(history['prior_known_list_price_usage_usd'])+Decimal(value['known_list_price_usage_usd'])),
        runtime_repairs=0,runtime_approvals=0,reference_inputs=0)
    return value


def run_recipe(packet,root,flash_transport,typesafe_transport,*,progress=None):
    root=Path(root);artifacts=EvidenceArtifactStore(root)
    if (root/'results.json').exists():
        saved=json.loads((root/'results.json').read_text())
        if saved['input_fingerprint']!=packet['input_fingerprint']: raise ValueError('Foreign five-window result')
        return saved
    results=[]
    for case in packet['cases']:
        outcome=run_case(packet,case,root/case['case_id'],flash_transport,typesafe_transport,progress=progress)
        results.append(outcome)
        if outcome['halt'] is not None: break
    account=accounting(root,packet)
    case_summaries=[];review_cases=[]
    for case,outcome in zip(packet['cases'],results,strict=False):
        original=outcome['initial'];revised=outcome['revision'];before=outcome['before']
        reading=original['reading'] if original else None
        case_summaries.append(dict(case_id=case['case_id'],profile_id=case['window']['profile_id'],
            video_id=case['window']['video_id'],stratum=case['window']['stratum'],status=outcome['status'],
            halt=outcome['halt'],initial_errors=original['errors'] if original else [],
            initial_proposed_claims=len(reading['claims']) if isinstance(reading,dict) and isinstance(reading.get('claims'),list) else 0,
            initial_literal_bound_claims=len(original['observations']) if original else 0,
            abstention=bool(original and not original['errors'] and not original['observations']),
            review_attempted=revised is not None,review_errors=(revised['mechanical']['errors'] if revised and revised['mechanical'] else []),
            changed_fields=revised['changed_fields'] if revised else [],field_comparisons=revised['field_comparisons'] if revised else [],
            initial_findings=before['findings'] if before else {}))
        review_cases.append(dict(case_id=case['case_id'],source=demo._source_state(SourceWindow(**case['window'])),
            original=original['reading'] if original else None,
            revised=(revised['mechanical']['reading'] if revised and revised['mechanical'] else None),
            review_required=['errors corrected','correct content damaged','unsupported new content','retained errors','abstentions'],
            outcome=outcome['status']))
    artifacts.write_immutable('source-review-packet.json',dict(input_fingerprint=packet['input_fingerprint'],cases=review_cases,
        semantic_audit='PENDING; no accuracy counts inferred from model scores'))
    component_fail=any(c['status']=='FAIL(component)' for c in results)
    result=dict(input_fingerprint=packet['input_fingerprint'],status='FAIL(component)' if component_fail else 'INCONCLUSIVE',
        completed_windows=sum(c['halt'] is None for c in results),processed_windows=len(results),
        planned_windows=len(packet['cases']),cases=case_summaries,accounting=account,
        semantic_outcome='INCONCLUSIVE: source review of correction AND preservation required',
        accuracy_counts=dict(errors_corrected=None,correct_content_damaged=None,unsupported_new_content=None),
        production_admission=False,limitation=packet['limitation'],
        next_step='Review saved source-review-packet.json and all failures; no retry, variant or expansion')
    artifacts.write_immutable('results.json',result);demo._write_report(root.parent,result)
    return result


def run(input_path,base_dir=None,*,experimental=False,approve_input=None,max_usd='0.52',confirm_prices=False,check_only=False,progress=None):
    path=Path(input_path);packet=json.loads(path.read_text());fp=packet['input_fingerprint']
    if digest({k:v for k,v in packet.items() if k!='input_fingerprint'})!=fp or path.resolve()!=(directory(base_dir,fp)/'input.json').resolve():
        raise ValueError('Frozen identity or location changed')
    expected,_=prepare(packet['history']['prior_input'],base_dir,check_only=True)
    if expected!=packet: raise ValueError('Source, implementation, metadata or budget changed after freeze')
    try: cap=Decimal(max_usd)
    except InvalidOperation as error: raise ValueError('Invalid dollar ceiling') from error
    if not cap.is_finite() or not Decimal(packet['budget']['reserved_usd'])<=cap<=Decimal('0.52'):
        raise ValueError('Reserve full twenty-attempt plan within $0.52')
    if check_only: return dict(status='PREPARED_NO_EXECUTION',budget=packet['budget'],selection=packet['selection'],metadata_requests=1,generation_calls=0,paid_calls=0)
    if not experimental or approve_input!=fp or not confirm_prices: raise ValueError('Use --experimental --approve-input exact fingerprint --confirm-prices')
    root=path.parent/'execution'
    if not (root/'results.json').exists() and (not hosted.credential_present() or not os.environ.get('TYPESAFE_API_KEY','').strip()):
        raise ValueError('Both TYPESAFE_API_KEY and DEEPINFRA_API_KEY required; no attempts started')
    marker=Path(packet['history']['prior_input']).parent/'execution/remaining-five-authorization.json'
    EvidenceArtifactStore(marker.parent).write_immutable(marker.name,dict(input_fingerprint=fp))
    EvidenceArtifactStore(root).write_immutable('authorization.json',dict(input_fingerprint=fp,max_usd=str(cap),maximum_attempts=20,confirm_prices=True))
    result=run_recipe(packet,root,hosted.transport,requests.typesafe_transport,progress=progress)
    return result | dict(results=str(root/'results.json'),review_packet=str(root/'source-review-packet.json'))
