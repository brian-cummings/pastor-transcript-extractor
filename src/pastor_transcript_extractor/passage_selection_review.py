"""One source-based semantic reconsideration of saved ranges, then the same verifier."""
from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal,InvalidOperation
import json
import os
from pathlib import Path
from httpx import HTTPError
from . import passage_selection_check as selection

requests=selection.requests
demo=selection.demo
hosted=selection.hosted
EvidenceArtifactStore=selection.EvidenceArtifactStore
digest=selection.digest
VERSION='source-passage-reconsideration-v1'
PRIOR='88849149271eee207cda2002f113d6d4b6c49d75f1c731d04a03304e08c32c05'
TEMPLATE='''Reconsider the saved source-passage selections against the COMPLETE original source units. The feedback below contains verifier probabilities and assessment criteria, not error explanations or expected corrections. Low confidence is not proof of error. Preserve a correct selection; revise only where source evidence warrants it, or explicitly abstain if no adequate passage expresses the unchanged candidate. Do not optimize for higher scores, change a candidate, supply a new claim, or drop an item. Keep complete sentences regardless of length and preserve necessary attribution, conditions and continuation. The copied selected spans and clearly unselected neighbors are provided for inspection; unselected context must be deliberately selected if needed. Return one complete ID-only replacement under the original schema for every original item ID. No human source-review conclusions are included. This is the single semantic reconsideration; there is no semantic loop after it. Feedback:\n'''


def review_request(spec,output,feedback,evidence):
    content=output if isinstance(output,str) else requests.wire(output)
    return replace(spec,body=dict(deepcopy(spec.body),messages=deepcopy(spec.body['messages'][:2])+[
        dict(role='assistant',content=content),dict(role='user',content=TEMPLATE+requests.wire(dict(criteria=selection.CRITERIA,feedback=feedback,selected_evidence=evidence)))]),
        source_identity=dict(spec.source_identity,reconsideration_version=VERSION,saved_output_digest=digest(content),feedback_digest=digest(feedback)))


def directory(base_dir,fp):
    root=demo.build_paths(base_dir).evaluation/'source-passage-review'/fp
    if root.resolve().is_relative_to(Path(__file__).parents[2].resolve()): raise ValueError('Artifacts must be outside repository')
    return root


def prepare(base_dir=None,*,check_only=False):
    path=selection.directory(base_dir,PRIOR)/'input.json';old=selection.prior.previous.trial.frozen(path);root=path.parent/'execution'
    result=json.loads((root/'results.json').read_text());checked=json.loads((root/'range-validation.json').read_text())
    if result['input_fingerprint']!=PRIOR or result['halt'] or checked['errors'] or result['accounting']['unknown_usage_attempts']:
        raise ValueError('Requires completed, mechanically valid source selections and known accounting')
    files=dict(old['history']['preserved_files'])
    for name,sha in files.items():
        if demo.file_hash(Path(name))!=sha: raise ValueError('Historical evidence changed')
    spec=requests.RequestSpec(**old['request']);source_ref=root/'selection/receipts'/f'{spec.fingerprint}.json'
    receipt=json.loads(source_ref.read_text())
    verify=requests.RequestSpec(**json.loads((root/'verifier-request.json').read_text()));verify_ref=root/'verification/receipts'/f'{verify.fingerprint}.json'
    judgment=json.loads(verify_ref.read_text())
    for original,record in ((spec,receipt),(verify,judgment)):
        if record['request']!=asdict(original) or record['halt'] or record['response_digest']!=digest(record['response']): raise ValueError('Saved receipt changed')
        requests.validate_response(original,record['response'])
    windows={sid:selection.SourceWindow(**w) for sid,w in old['windows'].items()}
    if selection.inspect(receipt['response']['output'],old['state'],windows)!=checked: raise ValueError('Saved literal selections changed')
    if selection.verification(old['state'],checked['reading'])!=verify: raise ValueError('Saved verifier contract differs')
    if set(judgment['response']['output'])!={r['item_id']+':'+r['field'] for r in result['verifier_scores']}: raise ValueError('Saved verifier coverage changed')
    if any(judgment['response']['output'][r['item_id']+':'+r['field']]['noul']!=r['probability_correct'] for r in result['verifier_scores']): raise ValueError('Saved feedback differs from receipt')
    accounts=[demo.usage_account(requests.ReceiptStore(root/phase)) for phase in ('selection','verification')]
    account=result['accounting']
    for key in ('attempts','local_attempts','paid_attempts','openai_calls','known_input_tokens','known_output_tokens','unknown_usage_attempts'):
        if sum(a[key] for a in accounts)!=account[key]: raise ValueError('Historical accounting changed')
    for key in ('reserved_usd','known_list_price_usage_usd'):
        if sum((Decimal(a[key]) for a in accounts),Decimal(0))!=Decimal(account[key]): raise ValueError('Historical cost changed')
    for key in ('attempts','local_attempts','paid_attempts'):
        if old['history']['prior_accounting']['cumulative_'+key]+account[key]!=account['cumulative_'+key]: raise ValueError('Historical cumulative count changed')
    if Decimal(old['history']['prior_accounting']['cumulative_known_list_price_usage_usd'])+Decimal(account['known_list_price_usage_usd'])!=Decimal(account['cumulative_known_list_price_usage_usd']): raise ValueError('Historical cumulative cost changed')
    if len(old['state']['items'])!=6 or len(result['verifier_scores'])!=18: raise ValueError('Requires six saved candidates and eighteen checks')
    feedback=[dict(item_id=r['item_id'],field=r['field'],probability_correct=r['probability_correct']) for r in result['verifier_scores']]
    evidence=[dict(item_id=i['item_id'],evidence=deepcopy(i['evidence'])) for i in verify.body['state']['items']]
    revised=review_request(spec,receipt['response']['output'],feedback,evidence);fit=revised.preflight()
    refs=[path,root/'results.json',root/'range-validation.json',root/'verifier-request.json',source_ref,verify_ref]
    files.update({str(ref):demo.file_hash(ref) for ref in refs})
    packet=dict(version=VERSION,state=deepcopy(old['state']),windows=deepcopy(old['windows']),request=asdict(revised),
        before=checked['reading'],before_scores=result['verifier_scores'],candidate_index=old['candidate_index'],coverage=old['coverage'],
        verifier_seed=dict(path=str(verify_ref),receipt=deepcopy(judgment)),
        token_account=fit,schema=selection.schema(),verifier_criteria=selection.CRITERIA,
        policy=dict(semantic_reconsiderations=1,mechanical_retries=1,verifier_rechecks=1,automatic_advancement=False,production_admission=False,reference_feedback=False),
        budget=dict(max_usd='.04',reserved_usd=str(2*hosted.reserved_usd(revised.version)+requests.reservation('source_verification')),maximum_paid_attempts=3,cumulative_attempts_reporting_only=True),
        history=dict(prior_input=str(path),prior_accounting=account,preserved_files=files),
        code_identity={m.__name__.rsplit('.',1)[-1]:demo.file_hash(Path(m.__file__)) for m in (selection,selection.passages,selection.context,requests,hosted,selection.binding_retry)},
        adapter_sha256=demo.file_hash(Path(__file__)),limitation='One exposed six-candidate reconsideration. Feedback is uncertainty, not error evidence. Source review must assess actual corrections and preservation of correct content; score increases alone do not establish either.')
    packet['input_fingerprint']=digest(packet);out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        (out/'preparation.md').write_text('# One passage reconsideration and recheck\n\nSame six candidate readings and three source windows. Reuse the completed selections and eighteen verifier scores; do not repeat initial extraction or initial verification. Flash 1017 receives full source, prior ID selections, copied selected text and uncertainty/criteria; no human expected corrections or review conclusions. One semantic revision, at most one mechanical correction, then the identical TypeSafe assessment criteria and thresholds. No automatic next experiment or production admission.\n\nReservation $'+packet['budget']['reserved_usd']+' under $0.04. Requests stop on fit/transport failure without truncation or extra calls. Cumulative accounting is reporting only. Preserve all prior receipts.\n')
    return packet,out


def run_recipe(packet,root,flash_transport,verifier_transport,*,progress=None):
    root=Path(root);store=EvidenceArtifactStore(root)
    if (root/'results.json').exists():
        saved=json.loads((root/'results.json').read_text())
        if saved['input_fingerprint']!=packet['input_fingerprint']: raise ValueError('Foreign review result')
        return saved
    revised=selection.run_recipe(packet,root/'reconsideration',flash_transport,verifier_transport,progress=progress,verifier_seed=packet.get('verifier_seed'))
    checked_path=root/'reconsideration/range-validation.json';changes=[]
    if checked_path.exists():
        checked=json.loads(checked_path.read_text())
        if not checked['errors']:
            old={r['item_id']:r for r in packet['before']['selections']}
            changes=[dict(item_id=r['item_id'],changed=r!=old[r['item_id']],before=old[r['item_id']],after=r) for r in checked['reading']['selections']]
    previous={(r['item_id'],r['field']):r['probability_correct'] for r in packet['before_scores']}
    comparisons=[dict(**row,previous_probability_correct=previous[(row['item_id'],row['field'])]) for row in revised['verifier_scores']]
    result=dict(revised,range_changes=changes,field_comparisons=comparisons,limitation=packet['limitation'],
        next_step='Review original and revised passages against full source, including preservation of correct content. Stop; no further semantic retry or expansion.')
    store.write_immutable('results.json',result);demo._write_report(root.parent,result);return result


def run(input_path,base_dir=None,*,experimental=False,approve_input=None,max_usd='.04',confirm_prices=False,check_only=False,progress=None):
    path=Path(input_path);packet=selection.prior.previous.trial.frozen(path);fp=packet['input_fingerprint']
    if path.resolve()!=(directory(base_dir,fp)/'input.json').resolve(): raise ValueError('Frozen location differs')
    expected,_=prepare(base_dir,check_only=True)
    if packet!=expected: raise ValueError('Frozen sources, feedback, models, code or budget changed')
    try: cap=Decimal(max_usd)
    except InvalidOperation as error: raise ValueError('Invalid ceiling') from error
    if not cap.is_finite() or not Decimal(packet['budget']['reserved_usd'])<=cap<=Decimal('.04'): raise ValueError('Reserve bounded review and recheck within $0.04')
    if check_only: return dict(status='PREPARED_NO_EXECUTION',budget=packet['budget'],generation_calls=0,paid_calls=0)
    if not experimental or approve_input!=fp or not confirm_prices: raise ValueError('Use exact frozen approval, --experimental and --confirm-prices')
    root=path.parent/'execution'
    if not (root/'results.json').exists() and (not hosted.credential_present() or not os.environ.get('TYPESAFE_API_KEY','').strip()): raise ValueError('Both provider credentials required; no attempts started')
    EvidenceArtifactStore(Path(packet['history']['prior_input']).parent/'execution').write_immutable('passage-review-authorization.json',dict(input_fingerprint=fp))
    EvidenceArtifactStore(root).write_immutable('authorization.json',dict(input_fingerprint=fp,max_usd=str(cap)))
    return run_recipe(packet,root,hosted.transport,requests.typesafe_transport,progress=progress)|dict(results=str(root/'results.json'))
