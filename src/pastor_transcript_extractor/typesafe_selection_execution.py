"""One-attempt nomination transport. Uncertain sends are never resubmitted."""
from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

from pastor_transcript_extractor import typesafe_selection_packet as spec
from pastor_transcript_extractor import typesafe_window_bridge as bridge
from pastor_transcript_extractor import typesafe_window_review as review
from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.sermon_g2_feasibility_revision import validate_answers
from pastor_transcript_extractor.config import build_paths


def write_once(path, value):
    """Durable immutable evidence before proceeding to the next external action."""
    with path.open('x') as handle:
        json.dump(seal(value), handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n'); handle.flush(); os.fsync(handle.fileno())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Provider redirect rejected')


def send(body, endpoint, timeout):
    key = os.environ.get('TYPESAFE_API_KEY')
    if not key:
        raise ValueError('TYPESAFE_API_KEY unavailable; no send')
    # No SDK default retries, long-context header, redirect, fallback or model alias.
    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(endpoint, data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+key}, method='POST')
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read(8_000_001)
        if len(raw) > 8_000_000:
            raise ValueError('Provider response size exceeded')
        return dict(status=response.status, body_utf8=raw.decode('utf-8'))


def checked_response(receipt, questions):
    if receipt['status'] != 200:
        raise ValueError('Unexpected HTTP status')
    raw = json.loads(receipt['body_utf8'])
    if raw['model'] != spec.MODEL:
        raise ValueError('Resolved model differs')
    count = raw['usage']['input_tokens']
    if type(count) is not int or not 0 < count <= spec.TOKENS_PER_REQUEST:
        raise ValueError('Invalid/missing input token accounting')
    output = raw['usage']['output_tokens']
    if type(output) is not int or output < 0:
        raise ValueError('Invalid/missing output token accounting')
    validate_answers(raw['answers'], questions)
    for key, answer in raw['answers'].items():
        if answer.get('type') != 'choice' or answer['probabilities'][answer['choice']] < max(answer['probabilities'].values()):
            raise ValueError('Incompatible Choice answer')
    return raw


def resolve_source_proof(selected, source_row):
    """Bindings contain proof IDs; resolve and verify the original sealed object."""
    expected = source_row['preparation_binding']['source_proof']
    matches = [row['proof'] for row in selected['sources'].values()
        if row['proof']['content_fingerprint'] == expected]
    if len(matches) != 1 or seal(matches[0]) != matches[0] or matches[0]['source_fingerprint'] != source_row['anchor']['source_fingerprint']:
        raise ValueError('Unresolved or foreign sealed source proof')
    return matches[0]


def execute(approved, base_dir=None, *, transport=send, clock=time.monotonic):
    repair_path = spec.HERE/'execution-repair-v1.json'
    if repair_path.exists() and approved == '19a1137161528d5c4eec95242148f05abb155b2fe710d2a0d59846cceabaa8a2':
        from pastor_transcript_extractor.typesafe_selection_resume import resume
        return resume(approved, base_dir, transport=transport, clock=clock)
    packet, _ = spec.verify(base_dir)
    authority = spec.require_authorization(packet, approved)
    selected, _ = review.selected_windows(base_dir)
    out = build_paths(base_dir).evaluation / spec.VERSION / approved / 'attempt-1'
    out.mkdir(parents=True, exist_ok=True)
    # Persistent lock survives crashes: never risk a duplicate billable send.
    write_once(out/'attempt-lock.json', dict(input_fingerprint=approved, authority=authority['content_fingerprint']))
    started = clock(); attempts = 0; tokens = 0; rows = []
    bounds = packet['bounds']

    def assess(request, cache):
        nonlocal attempts, tokens
        dispatch = bridge.dispatch_plan(request, cache)
        answers = {k: entry['answer'] for k, entry in dispatch['cached_answers'].items()}
        questions = dispatch['missing_questions']
        if not questions:
            return answers
        if attempts >= bounds['provider_requests_max'] or clock()-started >= bounds['run_seconds_max']:
            raise ValueError('Attempt request/time ceiling reached')
        # Reserve the maximum charge before the network boundary. An HTTP error
        # or interruption leaves this reservation outstanding, and stops the run.
        attempts += 1
        body = spec.wire(request, questions)
        write_once(out/f'{attempts:02d}-reservation.json', dict(input_fingerprint=approved,
            request_fingerprint=request['content_fingerprint'], wire=body,
            reserved_input_tokens=spec.TOKENS_PER_REQUEST))
        response = transport(body, packet['endpoint'], min(bounds['request_timeout_seconds'], bounds['run_seconds_max']-(clock()-started)))
        write_once(out/f'{attempts:02d}-response.json', dict(request_fingerprint=request['content_fingerprint'], raw=response))
        raw = checked_response(response, questions)
        tokens += raw['usage']['input_tokens']
        if tokens > bounds['reserved_total_input_tokens']:
            raise ValueError('Aggregate input token ceiling exceeded')
        for key, answer in raw['answers'].items():
            answers[key] = answer
            leaf = bridge.cached_leaf(request, key, answer, dict(input_fingerprint=approved, receipt=f'{attempts:02d}-response.json'))
            cache[leaf['leaf_key']] = leaf
        write_once(out/f'{attempts:02d}-leaves.json', dict(leaves=cache))
        return answers

    try:
        for row in packet['requests']:
            first = row['request']
            cache = {v['leaf_key']: v for v in row['first_dispatch']['cached_answers'].values()}
            raw = assess(first, cache)
            target = first; deferred = []
            if first['phase'] != 'direct_points':
                target, deferred = bridge.refine(first, raw)
                raw = assess(target, cache) if target else None
            context = selected['contexts'][first['scope']['context_fingerprint']]
            source_row = next(r for r in selected['cases'] if r.get('context_fingerprint') == context['content_fingerprint']
                and r['anchor']['content_fingerprint'] == first['scope']['anchor_fingerprint'])
            records, invalid = bridge.decode_points(target, raw, context, source_row['anchor'], resolve_source_proof(selected, source_row)) if target else ([], {})
            rows.append(dict(request_fingerprint=first['content_fingerprint'], nominations=records,
                withheld_families=deferred, invalid_families=invalid, diagnostic_slots=row['diagnostic_slots'], usable_evidence=False))
        if clock()-started > bounds['run_seconds_max']:
            raise ValueError('Run time ceiling exceeded')
        result = dict(status='EXECUTED_SOURCE_AUDIT_PENDING', input_fingerprint=approved,
            provider_requests=attempts, actual_input_tokens=tokens, rows=rows,
            structural_deferrals=packet['structural_deferrals'], source_audit_complete=False,
            nomination_feasibility=None, measurement_requests=0, admission_requests=0, usable_evidence=False)
        write_once(out/'results-v1.json', result)
        return seal(result), out/'results-v1.json'
    except Exception as error:
        # Exception messages can contain provider-controlled content. Preserve only
        # exception type; response bodies already have their own immutable receipt.
        write_once(out/'stopped-v1.json', dict(status='STOPPED_NO_RETRY', input_fingerprint=approved,
            error_type=type(error).__name__, reserved_requests=attempts,
            observed_input_tokens=tokens, partial_rows=rows, uncertain_sends_possible=True, usable_evidence=False))
        raise
