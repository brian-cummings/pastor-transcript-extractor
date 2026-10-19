"""Explicitly authorized continuation after a local proof-resolution crash.

Replay verified responses, never resubmit a paid request. Only the unsent tail
can cross the network boundary, within the original total request ceiling.
"""
from __future__ import annotations
from pathlib import Path

from pastor_transcript_extractor import typesafe_selection_packet as spec
from pastor_transcript_extractor import typesafe_selection_execution as execution
from pastor_transcript_extractor import typesafe_selection_recovery as recovery
from pastor_transcript_extractor import typesafe_window_review as review
from pastor_transcript_extractor import typesafe_window_bridge as bridge
from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal


def verified_repair(packet):
    repair = trace.read(spec.HERE/'execution-repair-v1.json',True)
    if (repair['status'] != 'AUTHORIZED' or repair['input_fingerprint'] != packet['content_fingerprint']
            or repair['decision_owner'] != 'Brian' or repair['bounds'] != packet['bounds']
            or repair['scope'] != 'replay_completed_receipts_then_send_only_unsent_tail'
            or repair['retry_completed_or_uncertain_requests'] is not False):
        raise ValueError('Proof repair continuation authority differs')
    for name, expected in repair['implementation_files'].items():
        if trace.digest(name) != expected: raise ValueError('Proof repair implementation changed')
    return repair


def check_repair(base_dir=None):
    packet,path = recovery.frozen_input(base_dir)
    spec.require_authorization(packet,packet['content_fingerprint'])
    repair = verified_repair(packet)
    selected,_ = review.selected_windows(base_dir)
    out = build_paths(base_dir).evaluation/spec.VERSION/packet['content_fingerprint']/'attempt-1'
    snapshot = recovery.replay(packet,selected,out)
    if snapshot['original_provider_requests'] != repair['completed_requests'] or snapshot['original_input_tokens'] != repair['observed_input_tokens']:
        raise ValueError('Stopped receipt prefix differs from repair authority')
    for name,expected in repair['attempt_files'].items():
        if trace.digest(name) != expected:raise ValueError('Authorized stopped receipt changed')
    if (out/'resume-proof-fix-lock.json').exists():raise ValueError('Continuation already attempted; no automatic retry')
    return dict(status='PROOF_REPAIR_READY_NO_INFERENCE',content_fingerprint=packet['content_fingerprint'],
        provider_requests=0,completed_requests=repair['completed_requests']),path


def resume(approved, base_dir, *, transport, clock):
    packet, _ = recovery.frozen_input(base_dir)
    spec.require_authorization(packet,approved)
    repair = verified_repair(packet)
    selected,_ = review.selected_windows(base_dir)
    out = build_paths(base_dir).evaluation/spec.VERSION/approved/'attempt-1'
    # Validate every sealed completed wire/cache/response, source proof and token
    # before reserving any new send. A missing/uncertain response rejects resume.
    snapshot = recovery.replay(packet,selected,out)
    if (snapshot['original_provider_requests'] != repair['completed_requests']
            or snapshot['original_input_tokens'] != repair['observed_input_tokens']):
        raise ValueError('Stopped receipt prefix differs from repair authority')
    for name,expected in repair['attempt_files'].items():
        if trace.digest(name) != expected: raise ValueError('Authorized stopped receipt changed')
    for row in packet['requests']:
        first=row['request']
        source_row=next(r for r in selected['cases'] if r.get('context_fingerprint') == first['scope']['context_fingerprint']
            and r['anchor']['content_fingerprint'] == first['scope']['anchor_fingerprint'])
        execution.resolve_source_proof(selected,source_row)
    execution.write_once(out/'resume-proof-fix-lock.json',dict(input_fingerprint=approved,repair_fingerprint=repair['content_fingerprint']))
    return continue_rows(packet,selected,out,snapshot['original_provider_requests'],transport=transport,clock=clock)


def continue_rows(packet,selected,out,completed,*,transport,clock):
    """Single continuation; completed is a verified, fully receipted prefix."""
    index=0; tokens=0; new=0; rows=[]; started=clock(); bounds=packet['bounds']
    approved=packet['content_fingerprint']
    # Conservatively reserve a full timeout for each earlier completed call.
    # The continuation gets only the remainder of the original active-time cap.
    remaining_seconds=bounds['run_seconds_max']-completed*bounds['request_timeout_seconds']
    if remaining_seconds<=0:raise ValueError('No conservative run-time allowance remains')

    def assess(request,cache):
        nonlocal index,tokens,new
        dispatch=bridge.dispatch_plan(request,cache)
        answers={k:v['answer'] for k,v in dispatch['cached_answers'].items()}
        questions=dispatch['missing_questions']
        if not questions:return answers
        index+=1
        if index>bounds['provider_requests_max'] or clock()-started>=remaining_seconds:
            raise ValueError('Original request/time ceiling reached')
        body=spec.wire(request,questions)
        if index<=completed:
            reservation=trace.read(out/f'{index:02d}-reservation.json',True)
            response=trace.read(out/f'{index:02d}-response.json',True)
            if (reservation['wire']!=body or reservation['request_fingerprint']!=request['content_fingerprint']
                    or response['request_fingerprint']!=request['content_fingerprint']):
                raise ValueError('Completed request differs; never resubmit')
            receipt=response['raw']
        else:
            execution.write_once(out/f'{index:02d}-reservation.json',dict(input_fingerprint=approved,
                request_fingerprint=request['content_fingerprint'],wire=body,reserved_input_tokens=spec.TOKENS_PER_REQUEST))
            new+=1
            receipt=transport(body,packet['endpoint'],min(bounds['request_timeout_seconds'],remaining_seconds-(clock()-started)))
            execution.write_once(out/f'{index:02d}-response.json',dict(request_fingerprint=request['content_fingerprint'],raw=receipt))
        raw=execution.checked_response(receipt,questions)
        tokens+=raw['usage']['input_tokens']
        if tokens>bounds['reserved_total_input_tokens']:raise ValueError('Original token ceiling exceeded')
        for key,answer in raw['answers'].items():
            answers[key]=answer
            leaf=bridge.cached_leaf(request,key,answer,dict(input_fingerprint=approved,receipt=f'{index:02d}-response.json'))
            cache[leaf['leaf_key']]=leaf
        if index<=completed:
            if trace.read(out/f'{index:02d}-leaves.json',True)['leaves']!=cache:raise ValueError('Completed leaf differs')
        else:execution.write_once(out/f'{index:02d}-leaves.json',dict(leaves=cache))
        return answers

    try:
        for row in packet['requests']:
            first=row['request'];cache={v['leaf_key']:v for v in row['first_dispatch']['cached_answers'].values()}
            raw=assess(first,cache);target=first;deferred=[]
            if first['phase']!='direct_points':
                target,deferred=bridge.refine(first,raw)
                raw=assess(target,cache) if target else None
            context=selected['contexts'][first['scope']['context_fingerprint']]
            source_row=next(r for r in selected['cases'] if r.get('context_fingerprint')==context['content_fingerprint']
                and r['anchor']['content_fingerprint']==first['scope']['anchor_fingerprint'])
            records,invalid=bridge.decode_points(target,raw,context,source_row['anchor'],execution.resolve_source_proof(selected,source_row)) if target else ([],{})
            rows.append(dict(request_fingerprint=first['content_fingerprint'],nominations=records,withheld_families=deferred,
                invalid_families=invalid,diagnostic_slots=row['diagnostic_slots'],usable_evidence=False))
        if index<completed or clock()-started>remaining_seconds:raise ValueError('Incomplete receipt replay or elapsed ceiling')
        result=dict(status='EXECUTED_SOURCE_AUDIT_PENDING',input_fingerprint=approved,provider_requests=index,
            new_provider_requests=new,replayed_provider_responses=completed,actual_input_tokens=tokens,rows=rows,
            structural_deferrals=packet['structural_deferrals'],source_audit_complete=False,nomination_feasibility=None,
            measurement_requests=0,admission_requests=0,usable_evidence=False)
        execution.write_once(out/'results-v1.json',result)
        return seal(result),out/'results-v1.json'
    except Exception as error:
        execution.write_once(out/'resume-stopped-v1.json',dict(status='STOPPED_NO_RETRY',input_fingerprint=approved,
            error_type=type(error).__name__,reserved_total_requests=index,new_reserved_requests=new,observed_input_tokens=tokens,
            partial_rows=rows,uncertain_sends_possible=True,usable_evidence=False))
        raise
