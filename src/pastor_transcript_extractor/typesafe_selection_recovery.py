"""Read-only receipt replay. No transport, credentials, retries or resume mode."""
from __future__ import annotations
import hashlib
import json
import subprocess
from decimal import Decimal
from pathlib import Path

from pastor_transcript_extractor import typesafe_selection_packet as spec
from pastor_transcript_extractor import typesafe_selection_execution as decoding
from pastor_transcript_extractor import typesafe_window_bridge as bridge
from pastor_transcript_extractor import typesafe_window_review as review
from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths

ARCHIVE = '92a97d1'
VERSION = 'typesafe-position-selection-recovery-v1'
CHANGED = {'src/pastor_transcript_extractor/typesafe_selection_execution.py',
    'src/pastor_transcript_extractor/commands/analysis/structure.py', 'tests/test_typesafe_selection_packet.py'}


def frozen_input(base_dir=None):
    pointer = trace.read(spec.MANIFEST, True)
    path = build_paths(base_dir).evaluation/pointer['relative_path']
    if trace.digest(path) != pointer['sha256']:
        raise ValueError('Frozen input file changed')
    packet = trace.read(path, True)
    if packet['content_fingerprint'] != pointer['input_fingerprint'] or packet['runtime'] != spec.runtime():
        raise ValueError('Frozen identity/runtime differs')
    for name, expected in packet['implementation_files'].items():
        if trace.digest(name) == expected: continue
        relative = Path(name).relative_to(trace.ROOT).as_posix()
        if relative not in CHANGED: raise ValueError('Unrecognized frozen implementation change')
        raw = subprocess.run(['git', 'show', ARCHIVE+':'+relative], cwd=trace.ROOT, check=True, capture_output=True).stdout
        if hashlib.sha256(raw).hexdigest() != expected: raise ValueError('Archived implementation differs')
    plan, _ = spec.verify_bridge(base_dir)
    if packet['bridge_fingerprint'] != plan['content_fingerprint'] or trace.digest(packet['bridge_path']) != packet['bridge_sha256']:
        raise ValueError('Frozen bridge binding differs')
    return packet, path


def replay(packet, selected, attempt):
    """Verify exact paid wires and derive missing local decode results only."""
    stopped = trace.read(attempt/'stopped-v1.json', True)
    lock = trace.read(attempt/'attempt-lock.json', True)
    if stopped['input_fingerprint'] != packet['content_fingerprint'] or lock['input_fingerprint'] != packet['content_fingerprint']:
        raise ValueError('Foreign stopped attempt')
    n = stopped['reserved_requests']
    if type(n) is not int or not 0 <= n <= packet['bounds']['provider_requests_max']:
        raise ValueError('Invalid attempt count')
    inputs = {str(p):trace.digest(p) for p in sorted(attempt.glob('*.json'))}
    if any((attempt/f'{i:02d}-reservation.json').exists() for i in range(n+1,31)):
        raise ValueError('Unaccounted reservation')
    count = 0; tokens = 0; rows = []

    def assess(request, cache):
        nonlocal count, tokens
        dispatch = bridge.dispatch_plan(request, cache)
        answers = {k:v['answer'] for k,v in dispatch['cached_answers'].items()}
        if not dispatch['requests_needed']: return answers
        if count >= n: return None
        i = count+1
        reservation = trace.read(attempt/f'{i:02d}-reservation.json',True)
        receipt = trace.read(attempt/f'{i:02d}-response.json',True)
        if (reservation['input_fingerprint'] != packet['content_fingerprint'] or reservation['request_fingerprint'] != request['content_fingerprint']
                or receipt['request_fingerprint'] != request['content_fingerprint']
                or reservation['wire'] != spec.wire(request,dispatch['missing_questions'])
                or reservation['reserved_input_tokens'] != spec.TOKENS_PER_REQUEST):
            raise ValueError('Receipt/request/wire differs')
        raw = decoding.checked_response(receipt['raw'], dispatch['missing_questions'])
        for key,answer in raw['answers'].items():
            answers[key] = answer
            leaf = bridge.cached_leaf(request,key,answer,dict(input_fingerprint=packet['content_fingerprint'],receipt=f'{i:02d}-response.json'))
            cache[leaf['leaf_key']] = leaf
        leaves = trace.read(attempt/f'{i:02d}-leaves.json',True)
        if leaves['leaves'] != cache: raise ValueError('Receipt/cache leaf mismatch')
        count += 1; tokens += raw['usage']['input_tokens']
        return answers

    for row in packet['requests']:
        first = row['request']; cache = {v['leaf_key']:v for v in row['first_dispatch']['cached_answers'].values()}
        raw = assess(first,cache); target=first; deferred=[]
        if raw is None:
            rows.append(dict(diagnostic_slots=row['diagnostic_slots'],status='NOT_EXECUTED',nominations=[],usable_evidence=False)); continue
        if first['phase'] != 'direct_points':
            target,deferred = bridge.refine(first,raw)
            raw = assess(target,cache) if target else None
            if target and raw is None:
                rows.append(dict(diagnostic_slots=row['diagnostic_slots'],status='REFINEMENT_NOT_EXECUTED',nominations=[],usable_evidence=False)); continue
        context = selected['contexts'][first['scope']['context_fingerprint']]
        source_row = next(r for r in selected['cases'] if r.get('context_fingerprint') == context['content_fingerprint']
            and r['anchor']['content_fingerprint'] == first['scope']['anchor_fingerprint'])
        records, invalid = bridge.decode_points(target,raw,context,source_row['anchor'],decoding.resolve_source_proof(selected,source_row)) if target else ([],{})
        rows.append(dict(diagnostic_slots=row['diagnostic_slots'],request_fingerprint=first['content_fingerprint'],
            status='RECEIPTS_DECODED',nominations=records,withheld_families=deferred,invalid_families=invalid,usable_evidence=False))
    if count != n or tokens != stopped['observed_input_tokens']: raise ValueError('Stopped accounting mismatch')
    # The completed prefix must be reproduced exactly; only the failed local
    # decode and unexecuted tail can add information to the historical stop.
    old = stopped['partial_rows']
    for previous, current in zip(old,rows,strict=False):
        if {k:current[k] for k in previous} != previous: raise ValueError('Previously decoded row differs')
    if len(old) > len(rows): raise ValueError('Invalid completed prefix')
    return seal(dict(version=VERSION,status='PARTIAL_EXECUTION_RECOVERED_NO_INFERENCE',
        input_fingerprint=packet['content_fingerprint'],attempt_files=inputs,rows=rows,
        completed_contexts=sum(r['status']=='RECEIPTS_DECODED' for r in rows),
        unexecuted_contexts=sum(r['status']=='NOT_EXECUTED' for r in rows),
        nominations_recovered=sum(len(r['nominations']) for r in rows),
        original_provider_requests=count,original_input_tokens=tokens,
        original_list_price_usd=str(Decimal(tokens)*Decimal('0.042')/1_000_000),
        new_provider_requests=0,structural_deferrals=packet['structural_deferrals'],
        source_audit_complete=False,nomination_feasibility=None,usable_evidence=False,
        execution_resume_authorized=False,original_stop_preserved=True))

