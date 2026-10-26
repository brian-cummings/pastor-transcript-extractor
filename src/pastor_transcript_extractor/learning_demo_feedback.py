"""Frozen verifier-feedback diagnostic on an existing answer; no new extraction batch."""
from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal,InvalidOperation
import json
import os
from pathlib import Path
from httpx import HTTPError

from . import learning_demo as demo
from . import learning_demo_contracts as contract
from . import learning_demo_correction as correction
from . import reading_diagnostics as diagnostics
from . import evidence_requests as requests
from . import deepinfra_requests as hosted
from .pastor_evidence import EvidenceArtifactStore,SourceWindow,digest,REQUIRED_CHECKS

VERSION='learning-demo-verifier-feedback-v1'
PRIOR='37c64e52e9a3886d5c9282bcca25ccdb7c924293f2c2d092d033876ad262d7c0'
PASS=.90
FAIL=.10
EVIDENCE_FIELDS=('conditions','qualifications','polarity','voice','adoption')
TEMPLATE='''Return a complete replacement answer under the original source-reading schema.
The attached TypeSafe probabilities are proposed judgments, not authoritative repairs.
Re-read the original complete source for each flagged field. Preserve binding IDs and
the same underlying points, including all source conditions, qualifications, attribution
and proposition-relative polarity. Do not substitute unrelated easier claims, invent
evidence, or change meanings just to satisfy a check. Source references below identify
whole source blocks selected by relevance judgments, not proven error explanations.
If no passage was selected, inspect the complete source. Return JSON only.
Verifier feedback:
'''


def directory(base_dir,fingerprint):
    path=demo.build_paths(base_dir).evaluation/'learning-demo-verifier-feedback'/fingerprint
    if path.resolve().is_relative_to(Path(__file__).parents[2].resolve()):
        raise ValueError('Generated artifacts must be outside repository')
    return path


def verification(window,observations,*,original=None,candidates=False):
    state=dict(source=demo._source_state(window),items=[dict(id=o['id'],binding=o['binding']) for o in observations])
    if original is not None:
        state['original_items']=[dict(binding_id=o['binding']['binding_id'],binding=o['binding']) for o in original]
    spec=contract.verification_request('source_verification',state,observations,
        dict(window=window.id,items_digest=digest(state['items']),stage='after' if original is not None else 'before'),source=True)
    questions=deepcopy(spec.body['questions']);candidate_map={}
    if candidates:
        _,mapping=window.target()
        # Source ranges/hash are sufficient for selection; keep large caption-index
        # arrays in the frozen window rather than repeating them in every question.
        mapping=[{k:block[k] for k in ('block_id','start','end','target_sha256')} for block in mapping]
        state['source_passages']=mapping
        for i,o in enumerate(observations):
            for field in EVIDENCE_FIELDS:
                for block in mapping:
                    key=f'passage-{i}-{field}-{block["block_id"]}'
                    candidate_map[key]=dict(item_id=o['id'],field=field,source_ref=block)
                    questions[key]=dict(type='noul',instructions=dict(item_id=o['id'],field=field,
                        check=contract.CHECK_MEANINGS[field],source_passage=block,
                        instruction='Regardless of whether this check passes, does this complete source block materially bear on evaluating the named field of the named item? Inspect its exact start/end range in source.texts.target_text. Do not assume there is an error.'),
                        criteria={'true':'The block supplies relevant evidence for this field, including an applicable qualification or attribution.',
                                  'false':'The block does not bear on the field or relevance cannot be resolved.'})
    if original is not None:
        for o in observations:
            key=o['id']+':repair_scope'
            questions[key]=dict(type='noul',instructions=dict(item_id=o['id'],
                instruction='Compare this item with original_items using binding_id, treating original_items as fallible proposals, not evidence. Does the new item preserve the same underlying point while correcting it from the complete source, rather than replace it with an unrelated claim or erase a difficult part?'),
                criteria={'true':'Same point, faithfully corrected with source qualifications and attribution.',
                          'false':'Unrelated substitution, erased point, unsupported change, or unresolved continuity.'})
    spec=replace(spec,body={**spec.body,'state':state,'questions':questions},namespace=VERSION,version=VERSION)
    spec.preflight()
    return spec,candidate_map


def judgments(response,spec,candidate_map):
    answers=response['output']
    if set(answers)!=set(spec.body['questions']): raise ValueError('Verifier answer inventory mismatch')
    core={k:v for k,v in answers.items() if k not in candidate_map}
    findings=contract.judgments({**response,'output':core},replace(spec,body={**spec.body,'questions':{k:v for k,v in spec.body['questions'].items() if k not in candidate_map}}))
    selected={}
    for key,record in candidate_map.items():
        answer=answers[key];p=answer.get('noul')
        if answer.get('type')!='noul' or type(p) not in (int,float) or not 0<=p<=1:
            raise ValueError('Invalid passage relevance probability')
        if p>=PASS: selected.setdefault(record['item_id']+':'+record['field'],[]).append(dict(
            **record['source_ref'],relevance_probability=p))
    feedback=[]
    for identity,fields in findings.items():
        for field,finding in fields.items():
            if not finding['resolved']:
                feedback.append(dict(item_id=identity,field=field,probability=finding['probability'],
                    binding_id=next(item['binding']['binding_id'] for item in spec.body['state']['items'] if item['id']==identity),
                    outcome='FAIL' if finding['probability']<=FAIL else 'INCONCLUSIVE',
                    criterion=contract.CHECK_MEANINGS.get(field,'Repair must preserve the same source-grounded point'),
                    source_refs=selected.get(identity+':'+field,[]),
                    source_fallback='Use complete original source when no passage is selected'))
    return dict(findings=findings,feedback=feedback,selected_passages=selected)


def budget():
    verifier=requests.reservation('source_verification')
    generator=hosted.reserved_usd(requests.DEEPINFRA_CORRECTION_VERSION)
    return dict(maximum_attempts=3,maximum_paid_attempts=3,typesafe_attempts=2,flash_attempts=1,
        max_usd='0.10',reserved_usd=str(2*verifier+generator),verifier_reservation_usd=str(verifier),
        flash_reservation_usd=str(generator),corrections=1,transport_retries=0,fallbacks=0,
        cumulative_maximum_attempts=35)


def prepare(prior_input,base_dir=None,*,check_only=False):
    prior_input=Path(prior_input).resolve()
    if prior_input!=(correction.directory(base_dir,PRIOR)/'input.json').resolve():
        raise ValueError('Requires the reviewed Flash mechanical PASS')
    prior=json.loads(prior_input.read_text())
    if prior['input_fingerprint']!=PRIOR or digest({k:v for k,v in prior.items() if k!='input_fingerprint'})!=PRIOR:
        raise ValueError('Prior input identity changed')
    for path,sha in prior['history']['preserved_files'].items():
        if demo.file_hash(Path(path))!=sha: raise ValueError('Historical evidence changed')
    store=requests.ReceiptStore(prior_input.parent/'execution');result=json.loads((store.root/'results.json').read_text())
    if (result['input_fingerprint']!=PRIOR or result['contract_fit']!='PASS' or result['halt'] is not None
        or result['literal_bound_claims']!=2 or len(store.attempts())!=1 or result['accounting']['unknown_usage_attempts']!=0
        or result['accounting']['cumulative_attempts']!=32):
        raise ValueError('Prior result is not the reviewed one-attempt two-claim mechanical PASS')
    for name in ('pastor_evidence','theological_binding','binding_evidence','learning_demo_contracts'):
        if prior['code_identity'][name]!=demo.code_identity()[name]: raise ValueError('Shared evidence semantics changed')
    ancestor=prior
    while 'source_requests' not in ancestor: ancestor=json.loads(Path(ancestor['history']['prior_input']).read_text())
    from .learning_demo_model_fit import verify_sources
    verify_sources(ancestor,base_dir)
    window=SourceWindow(**prior['window']);spec=requests.RequestSpec(**prior['request'])
    receipt=json.loads((store.root/'receipts'/f'{spec.fingerprint}.json').read_text())
    if receipt['request']!=prior['request'] or receipt['response_digest']!=digest(receipt['response']) or receipt['halt']:
        raise ValueError('Prior request/response receipt changed')
    checked=diagnostics.inspect(receipt['response']['output'],prior['schema'],window,model=hosted.FLASH_MODEL,
        prompt_digest=digest(spec.body['messages']),raw_response_ref='receipts/'+spec.fingerprint+'.json')
    if checked['errors'] or checked['reading']!=result['reading'] or checked['observations']!=result['observations']:
        raise ValueError('Saved observations no longer match the shared compiler')
    verify,candidates=verification(window,result['observations'],candidates=True)
    metadata=hosted.public_model_metadata(hosted.FLASH_MODEL)
    if metadata!=prior['published_model_metadata']: raise ValueError('Frozen Flash deployment/prices changed')
    files=[prior_input,*sorted(p for p in store.root.rglob('*.json') if p.name!='feedback-authorization.json')]
    packet=dict(schema_version=VERSION,window=prior['window'],schema=prior['schema'],request=prior['request'],
        original_output=receipt['response']['output'],observations=result['observations'],
        before_request=asdict(verify),candidate_map=candidates,correction=dict(template=TEMPLATE),
        token_accounts=dict(before=verify.preflight(),flash_initial=spec.preflight(),
            dynamic_policy='Preflight complete correction and recheck before each send; never truncate or add batches'),
        published_model_metadata=metadata,budget=budget(),
        policy=dict(pass_at_least=PASS,fail_at_most=FAIL,uncertainty='Withhold; correction only for a confident failure',
            checks=list(REQUIRED_CHECKS),evidence_fields=list(EVIDENCE_FIELDS),
            after='Same independent checks plus repair_scope; no new evidence admission',
            known_case_audit='Evaluate original b2 qualifications and polarity detection only after responses; never sent as expected answers',
            no_manual_reference_inputs=True),
        code_identity={**demo.code_identity(),'learning_demo_feedback':demo.file_hash(Path(__file__)),
            'learning_demo_correction':demo.file_hash(Path(correction.__file__)),
            'reading_diagnostics':demo.file_hash(Path(diagnostics.__file__)),
            'deepinfra_requests':demo.file_hash(Path(hosted.__file__))},
        provider_docs=dict(api='https://docs.typesafe.ai/api/system-one',questions='https://docs.typesafe.ai/primitives/noul',
            cookbook='https://docs.typesafe.ai/cookbooks/citation_check',pricing='https://docs.typesafe.ai/models',
            model='jev-1.13.0',input_usd_per_million='0.042',output_usd_per_million='0',
            limitation='Retain existing pinned Jev model and thresholds; this reviewed case cannot calibrate general accuracy'),
        history=dict(prior_input=str(prior_input),prior_attempts=32,prior_local_attempts=28,prior_paid_attempts=4,
            prior_source_attempts=28,prior_synthetic_attempts=4,
            prior_known_list_price_usage_usd=result['accounting']['cumulative_known_list_price_usage_usd'],
            preserved_files={**prior['history']['preserved_files'],**{str(p):demo.file_hash(p) for p in files}}),
        limitation='One known-error window, not blinded validation or proof of independent verifier accuracy. No semantic repair is authored by code, no production admission or further experiment.',
        production_admission=False)
    packet['input_fingerprint']=digest(packet);out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        (out/'preparation.md').write_text('# TypeSafe feedback diagnostic\n\n'+packet['limitation']+
            '\n\nReuse saved Flash answer; one TypeSafe check; at most one Flash correction; one TypeSafe recheck. '
            'No generation if the first check passes everything or finds only uncertainty. '
            'A finding at or below 0.10 permits correction; 0.90 is the existing pass threshold. '
            'All ten checks must pass after correction; known-case detection is reported separately. '
            'Block relevance selects references, not generated explanations. Expected errors and manual source review are not model inputs. '
            'Both TYPESAFE_API_KEY and DEEPINFRA_API_KEY are needed. '
            f'Full-list maximum reservation ${packet["budget"]["reserved_usd"]}, ceiling $0.10.\n\n```sh\n'+command(out,packet,base_dir)+'\n```\n')
    return packet,out


def command(out,packet,base_dir):
    return (f'pte analysis learning-demo model-fit feedback-run --base-dir {demo.build_paths(base_dir).root} '
        f'--input {out / "input.json"} --experimental --approve-input {packet["input_fingerprint"]} '
        '--max-usd 0.10 --confirm-prices --json')


def run_recipe(packet,root,typesafe_transport,flash_transport,*,progress=None):
    root=Path(root);saved=root/'results.json'
    if saved.exists():
        result=json.loads(saved.read_text())
        if result['input_fingerprint']!=packet['input_fingerprint']: raise ValueError('Foreign feedback result')
        return result
    stores={key:requests.ReceiptStore(root/key) for key in ('before','correction','after')}
    before=after=mechanical=None;halt=None;corrected=[]
    try:
        spec=requests.RequestSpec(**packet['before_request'])
        if progress: progress('TypeSafe 1/2: original saved answer; field checks and passage relevance')
        response=requests.execute(spec,requests.BudgetLedger(max_attempts=1),stores['before'],typesafe_transport)
        before=judgments(response,spec,packet['candidate_map'])
        stores['before'].write_immutable('judgments.json',before)
        if any(f['outcome']=='FAIL' for f in before['feedback']):
            spec=correction.corrective_request(packet,packet['original_output'],before['feedback'])
            stores['correction'].write_immutable('request.json',asdict(spec))
            if progress: progress('Flash 1/1: one correction from proposed verifier feedback; no retry')
            response=requests.execute(spec,hosted.OneRequestLedger('0.10',spec.version),stores['correction'],flash_transport)
            window=SourceWindow(**packet['window'])
            mechanical=diagnostics.inspect(response['output'],packet['schema'],window,model=hosted.FLASH_MODEL,
                prompt_digest=digest(spec.body['messages']),raw_response_ref='correction/receipts/'+spec.fingerprint+'.json')
            stores['correction'].write_immutable('validation.json',mechanical)
            if not mechanical['errors']:
                corrected=mechanical['observations']
                if {r['binding']['binding_id'] for r in corrected}!={r['binding']['binding_id'] for r in packet['observations']}:
                    raise ValueError('Correction changed claim identity/coverage; no acceptance or retry')
                verify,_=verification(window,corrected,original=packet['observations'])
                stores['after'].write_immutable('request.json',asdict(verify))
                if progress: progress('TypeSafe 2/2: corrected answer; same checks plus repair continuity')
                response=requests.execute(verify,requests.BudgetLedger(max_attempts=1),stores['after'],typesafe_transport)
                after=judgments(response,verify,{})
                stores['after'].write_immutable('judgments.json',after)
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: halt=str(error)
    accounts={key:demo.usage_account(store) for key,store in stores.items()}
    account={key:sum(a[key] for a in accounts.values()) for key in (
        'attempts','local_attempts','paid_attempts','openai_calls','known_input_tokens','known_output_tokens','unknown_usage_attempts')}
    for key in ('reserved_usd','known_list_price_usage_usd','known_provider_estimated_usage_usd'):
        account[key]=str(sum((Decimal(a.get(key,'0')) for a in accounts.values()),Decimal(0)))
    history=packet['history'];account.update(prior_attempts=history['prior_attempts'],
        cumulative_attempts=history['prior_attempts']+account['attempts'],
        cumulative_local_attempts=history['prior_local_attempts']+account['local_attempts'],
        cumulative_paid_attempts=history['prior_paid_attempts']+account['paid_attempts'],
        cumulative_known_list_price_usage_usd=str(Decimal(history['prior_known_list_price_usage_usd'])+Decimal(account['known_list_price_usage_usd'])),
        runtime_repairs=0,runtime_approvals=0,reference_inputs=0)
    # Evaluation-only known-error audit, never a model input or correction gate.
    original_id=next((o['id'] for o in packet['observations'] if o['binding']['binding_id']=='b2'),None)
    detection={field:(before['findings'].get(original_id,{}).get(field,{}).get('probability') if before else None)
        for field in ('qualifications','polarity')}
    detected=all(p is not None and p<=FAIL for p in detection.values())
    final_pass=after is not None and not after['feedback'] and not halt
    definite_miss=any(p is not None and p>=PASS for p in detection.values())
    definite_failure=halt or (mechanical is not None and mechanical['errors']) or definite_miss or (
        after is not None and any(f['outcome']=='FAIL' for f in after['feedback']))
    status='FAIL(component)' if definite_failure else 'PASS' if detected and final_pass else 'INCONCLUSIVE'
    result=dict(input_fingerprint=packet['input_fingerprint'],status=status,accounting=account,stage_accounting=accounts,
        halt=halt,before=before,mechanical=mechanical,after=after,
        known_error_audit=dict(probabilities_correct=detection,both_confidently_detected=detected),
        feedback_usefulness='PASS on this case' if status=='PASS' else 'Not demonstrated',
        observations=corrected,semantic_outcome='Independent source review of the correction remains required',
        production_admission=False,limitation=packet['limitation'],
        next_step='Review original judgments, selected source references and correction against source; no further retry or expansion')
    EvidenceArtifactStore(root).write_immutable('results.json',result);demo._write_report(root.parent,result)
    return result


def run(input_path,base_dir=None,*,experimental=False,approve_input=None,max_usd='0.10',confirm_prices=False,check_only=False,progress=None):
    path=Path(input_path);packet=json.loads(path.read_text());fingerprint=packet['input_fingerprint']
    if digest({k:v for k,v in packet.items() if k!='input_fingerprint'})!=fingerprint or path.resolve()!=(directory(base_dir,fingerprint)/'input.json').resolve():
        raise ValueError('Frozen input identity or location changed')
    expected,_=prepare(packet['history']['prior_input'],base_dir,check_only=True)
    if expected!=packet: raise ValueError('Source, implementation, provider metadata or budget changed after freeze')
    try: ceiling=Decimal(max_usd)
    except InvalidOperation as error: raise ValueError('Invalid dollar ceiling') from error
    if not ceiling.is_finite() or not Decimal(packet['budget']['reserved_usd'])<=ceiling<=Decimal('0.10'):
        raise ValueError('Reserve all three requests within at most $0.10')
    if check_only:
        return dict(status='PREPARED_NO_EXECUTION',input_fingerprint=fingerprint,budget=packet['budget'],metadata_requests=1,generation_calls=0,paid_calls=0)
    if not experimental or approve_input!=fingerprint or not confirm_prices:
        raise ValueError('Use --experimental --approve-input exact fingerprint --confirm-prices')
    root=path.parent/'execution'
    if not (root/'results.json').exists() and (not hosted.credential_present() or not os.environ.get('TYPESAFE_API_KEY','').strip()):
        raise ValueError('Both TYPESAFE_API_KEY and DEEPINFRA_API_KEY required; no attempts started')
    marker=Path(packet['history']['prior_input']).parent/'execution/feedback-authorization.json'
    EvidenceArtifactStore(marker.parent).write_immutable(marker.name,dict(input_fingerprint=fingerprint))
    EvidenceArtifactStore(root).write_immutable('authorization.json',dict(input_fingerprint=fingerprint,max_usd=str(ceiling),
        maximum_attempts=3,confirm_prices=True,production_admission=False))
    result=run_recipe(packet,root,requests.typesafe_transport,hosted.transport,progress=progress)
    return {k:v for k,v in result.items() if k not in ('before','after','mechanical','observations','stage_accounting')} | dict(results=str(root/'results.json'))
