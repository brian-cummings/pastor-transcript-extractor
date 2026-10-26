"""Bounded model-authored binding reconstruction, followed by semantic checks."""
from copy import deepcopy
from dataclasses import asdict,replace
from pathlib import Path
from httpx import HTTPError

from . import evidence_requests as requests
from . import deepinfra_requests as hosted
from . import reading_diagnostics as diagnostics
from . import learning_demo_contracts as contract
from . import learning_demo_correction as correction
from . import learning_demo_field_check as fields
from . import learning_demo_feedback as feedback
from . import learning_demo_uncertainty as review
from .pastor_evidence import SourceWindow,digest

VERSION='binding-retry-policy-v1'
TEMPLATE='''Your answer passed JSON/schema parsing but failed the shared source-binding checks.
Return one complete replacement answer under the same schema, using the original
complete source. Fix the field-path errors listed below, including all supporting
literal evidence nodes and references needed by any findings you retain.
Do not delete a supported qualification, change a proposition or substitute an easier
claim simply to pass validation. Preserve existing unique binding IDs and the same
source-grounded meanings, voices, adoption, polarity, conditions and qualifications.
If the source does not support a finding, leave it unresolved. Code will not invent
evidence, normalize quotations or choose an arbitrary occurrence for you.
This feedback is mechanical, not a theological correction or semantic approval.
Return JSON only. One binding retry is permitted; no further repair follows.
Binding errors:
'''


def import_receipt(store,seed):
    """Import compatible evidence as a cache entry, never as a newly billed attempt."""
    receipt=seed['receipt'];key=requests.RequestSpec(**receipt['request']).fingerprint
    if receipt.get('halt') or receipt['response_digest']!=digest(receipt['response']): raise ValueError('Invalid seed receipt')
    store.write_immutable('receipts/'+key+'.json',receipt)
    if seed.get('wire') is not None: store.write_immutable('wire-responses/'+key+'.json',seed['wire'])
    store.write_immutable('reuse-'+key+'.json',dict(origin=seed['path'],receipt_digest=digest(receipt)))


def read(spec,window,schema,store,transport,*,response_prefix='',progress=None,seed=None):
    """At most two sends; invalid JSON/schema, status or transport never retries."""
    if spec.version!=requests.DEEPINFRA_BINDING_VERSION:
        raise ValueError('Automatic binding retry requires a newly frozen request policy')
    ledger=hosted.BindingRetryLedger();attempts=[];original_ids=None
    for index in range(2):
        reused=seed is not None and index==0
        if reused:
            old=requests.RequestSpec(**seed['receipt']['request'])
            if old.body!=spec.body: raise ValueError('Seed producer/source body differs')
            if progress: progress('Reusing saved Flash response; no generation call')
            import_receipt(store,seed);response=seed['receipt']['response']
        else: response=requests.execute(spec,ledger,store,transport)
        checked=diagnostics.inspect(response['output'],schema,window,model=spec.body['model'],
            prompt_digest=digest(spec.body['messages']),raw_response_ref=(seed['raw_response_ref'] if reused else response_prefix+'receipts/'+spec.fingerprint+'.json'))
        reading=checked['reading']
        schema_valid=reading is not None and not diagnostics.shape_errors(reading,schema)
        if index==0 and schema_valid:
            ids=[c['binding_id'] for c in reading['claims']]
            if len(ids)==len(set(ids)): original_ids=set(ids)
        if index==1 and schema_valid and original_ids is not None:
            if {c['binding_id'] for c in reading['claims']}!=original_ids:
                checked['errors'].append(dict(path='$.claims',code='identity',message='Binding retry changed unique claim identity/coverage'))
                checked['observations']=[]
        record=dict(request_fingerprint=old.fingerprint if reused else spec.fingerprint,reused=reused,**checked)
        store.write_immutable(f'binding-validation/attempt-{index+1}.json',record);attempts.append(record)
        eligible=schema_valid and checked['errors'] and all(e['path']!='$.status' for e in checked['errors'])
        if not eligible or index==1: break
        if progress: progress('Binding failed; requesting one replacement with exact validation errors')
        content=response['output'] if isinstance(response['output'],str) else requests.wire(response['output'])
        task=(spec.body['messages'][-1]['content']+'\n\n') if len(spec.body['messages'])>2 else ''
        retry=replace(spec,body={**deepcopy(spec.body),'messages':deepcopy(spec.body['messages'][:2])+[
            dict(role='assistant',content=content),dict(role='user',content=task+TEMPLATE+requests.wire(checked['errors']))]},
            source_identity={**spec.source_identity,'binding_retry_of':spec.fingerprint,
                'failed_output_digest':digest(content),'binding_errors_digest':digest(checked['errors'])})
        retry.preflight()  # Never truncate a transcript or feedback to make it fit.
        store.write_immutable('binding-retry-request.json',asdict(retry));spec=retry
    store.write_immutable('binding-result.json',dict(final_request_fingerprint=attempts[-1]['request_fingerprint'],
        retries=len(attempts)-1,validation=checked))
    return dict(response=response,spec=spec,validation=checked,attempts=attempts,retries=len(attempts)-1)


def run_case(packet,case,root,flash_transport,typesafe_transport,*,progress=None):
    """Same TypeSafe loop; each Flash stage owns one separate binding retry."""
    root=Path(root);artifacts=requests.ReceiptStore(root)
    case_fp=digest(dict(parent=packet['input_fingerprint'],case_id=case['case_id']))
    initial=before=revision=None;halt=None;initial_retries=0;initial_attempts=[]
    try:
        base=requests.RequestSpec(**case['request']);window=SourceWindow(**case['window'])
        if progress: progress(case['case_id']+': initial Flash reading with one binding retry available')
        initial_read=read(base,window,packet['schema'],requests.ReceiptStore(root/'initial'),flash_transport,
            response_prefix='initial/',progress=progress,seed=case.get('seeds',{}).get('initial'))
        initial=initial_read['validation'];initial_retries=initial_read['retries'];initial_attempts=initial_read['attempts']
        artifacts.write_immutable('initial-validation.json',initial)
        if not initial['errors'] and initial['observations']:
            verify,candidates=fields.verification(window,initial['observations'])
            artifacts.write_immutable('before-request.json',asdict(verify))
            if progress: progress(case['case_id']+': TypeSafe initial check (binding passed)')
            if 'before' in case.get('seeds',{}):
                if case['seeds']['before']['receipt']['request']!=asdict(verify): raise ValueError('Seed verifier request differs')
                import_receipt(requests.ReceiptStore(root/'before'),case['seeds']['before'])
                if progress: progress(case['case_id']+': reusing saved TypeSafe initial verdict')
            response=requests.execute(verify,requests.BudgetLedger(max_attempts=1,max_usd='0.003'),
                requests.ReceiptStore(root/'before'),typesafe_transport)
            before=feedback.judgments(response,verify,candidates);artifacts.write_immutable('before-judgments.json',before)
            scores=review.review_scores(verify,before)
            if any(s['review_requested'] for s in scores):
                # Start the semantic review from the original source prefix and final
                # valid answer; earlier invalid attempts remain durable receipts.
                spec=correction.corrective_request(dict(request=asdict(base),correction=dict(template=review.TEMPLATE)),
                    initial_read['response']['output'],scores)
                artifacts.write_immutable('revision-input.json',dict(request=asdict(spec),scores=scores))
                if progress: progress(case['case_id']+': Flash semantic re-review with one binding retry available')
                rebuilt=read(spec,window,packet['schema'],requests.ReceiptStore(root/'revision/review'),flash_transport,
                    response_prefix='revision/review/',progress=progress,seed=case.get('seeds',{}).get('review'))
                mechanical=rebuilt['validation'];after=None;diff=[];comparisons=[]
                revision=dict(mechanical=mechanical,after=None,changed_fields=diff,field_comparisons=comparisons,
                    halt=None,binding_retries=rebuilt['retries'],binding_attempts=rebuilt['attempts'])
                if not mechanical['errors']:
                    diff.extend(review.changes(initial_read['response']['output'],mechanical['reading']))
                    verify,candidates=fields.verification(window,mechanical['observations'])
                    artifacts.write_immutable('after-request.json',asdict(verify))
                    if progress: progress(case['case_id']+': TypeSafe recheck (binding passed)')
                    if 'after' in case.get('seeds',{}):
                        if case['seeds']['after']['receipt']['request']!=asdict(verify): raise ValueError('Seed recheck request differs')
                        import_receipt(requests.ReceiptStore(root/'revision/after'),case['seeds']['after'])
                        if progress: progress(case['case_id']+': reusing saved TypeSafe recheck')
                    response=requests.execute(verify,requests.BudgetLedger(max_attempts=1,max_usd='0.003'),
                        requests.ReceiptStore(root/'revision/after'),typesafe_transport)
                    after=feedback.judgments(response,verify,candidates);revision['after']=after
                    prior={(s['binding_id'],s['field']):s['probability_correct'] for s in scores}
                    for item in verify.body['state']['items']:
                        for field in fields.FIELDS:
                            p=after['findings'][item['id']][field]['probability'];key=(item['binding']['binding_id'],field)
                            comparisons.append(dict(binding_id=key[0],field=field,previous_probability_correct=prior[key],
                                probability_correct=p,outcome='PASS' if p>=fields.PASS else 'FAIL' if p<=fields.FAIL else 'INCONCLUSIVE'))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: halt=str(error)
    failed=halt or (initial is not None and initial['errors']) or (revision is not None and revision['mechanical']['errors'])
    if progress and failed and halt is None:
        progress(case['case_id']+': TypeSafe stage skipped because binding/schema did not pass within its limit')
    result=dict(case_id=case['case_id'],case_fingerprint=case_fp,status='FAIL(component)' if failed else 'INCONCLUSIVE',
        halt=halt,initial=initial,before=before,revision=revision,initial_binding_retries=initial_retries,
        initial_binding_attempts=initial_attempts,binding_stage_attempts={
            'initial':len(requests.ReceiptStore(root/'initial').attempts()),
            'review':len(requests.ReceiptStore(root/'revision/review').attempts())},production_admission=False)
    artifacts.write_immutable('results.json',result)
    return result
