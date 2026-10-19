"""Offline nomination execution packet. Preparation and verification never infer."""
from __future__ import annotations

import json
import platform
import sys
import subprocess
import hashlib
from decimal import Decimal
from pathlib import Path

from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor import typesafe_window_bridge as bridge
from pastor_transcript_extractor import typesafe_window_review as review
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths

VERSION = 'typesafe-position-selection-v1'
HERE = trace.ROOT / 'docs/review-proposals/typesafe-position-selection-v1'
MANIFEST = HERE / 'preparation-manifest-v1.json'
DECISION = HERE / 'execution-decision-v1.json'
MODEL = 'jev-1.13.0'
# Reserve the service's whole default context; these are not tokenizer estimates.
TOKENS_PER_REQUEST = 65_536
PRICE_PER_MILLION = '0.042'


def wire(request, questions=None):
    if seal(request) != request or request['model'] != MODEL:
        raise ValueError('Request identity/model changed')
    return dict(model=MODEL, state=request['state'], questions=request['questions'] if questions is None else questions)


def wire_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode())


def refinement_envelope(first):
    """Bound any legal second-pass payload without selecting a source endpoint.

    Each endpoint can choose any page independently. All pages are enumerated,
    but never materialized as semantic candidates or sent as extra requests.
    """
    questions = {}
    for key, question in first['questions'].items():
        variants = []
        for page in first['state']['boundary_pages']:
            candidate = dict(type='choice', instructions=bridge._task(key.split('_', 1)[0], key.split('_', 1)[1], 'point'),
                criteria={**{f'p{i}': None for i in range(page['first'], page['last'] + 1)}, **bridge.SENTINELS})
            variants.append(candidate)
        questions[key] = max(variants, key=wire_bytes)
    return wire_bytes(wire(first, questions))


def runtime():
    return dict(python=sys.version, implementation=platform.python_implementation(),
                system=platform.system(), machine=platform.machine(), transport='stdlib urllib HTTPS; no SDK retries')


def make_packet(plan, plan_path):
    if seal(plan) != plan or plan['provider_requests'] or plan['execution_authorized']:
        raise ValueError('Unsealed/non-preparation bridge input')
    bounds = plan['usage_bounds']
    if (bounds['unique_context_requests'] != 15 or bounds['family_bindings'] != 16
            or bounds['G2_bindings'] != 6 or bounds['G3_bindings'] != 10
            or bounds['selection_requests_max'] > 30 or bounds['measurement_requests_prepared']):
        raise ValueError('Fixed nomination inventory differs')
    rows = []
    for item in plan['plans']:
        request = item['request']
        dispatch = item['dispatch']
        if seal(request) != request or bridge.dispatch_plan(request, {
                entry['leaf_key']: entry for entry in dispatch['cached_answers'].values()}) != dispatch:
            raise ValueError('Invalid request/cache plan')
        first = wire(request, dispatch['missing_questions'])
        rows.append(dict(request_fingerprint=request['content_fingerprint'], request=request,
            diagnostic_slots=item['diagnostic_slots'], first_dispatch=dispatch,
            first_wire=first if dispatch['requests_needed'] else None,
            first_wire_bytes=wire_bytes(first) if dispatch['requests_needed'] else 0,
            refinement_wire_bytes_upper_bound=refinement_envelope(request) if request['phase'] != 'direct_points' else 0))
    if (len(rows) != 15 or len({r['request_fingerprint'] for r in rows}) != 15
            or sum(len(r['request']['questions']) for r in rows) != 44
            or sum(len(r['request']['metadata']['families']) for r in rows) != 16):
        raise ValueError('Actual nomination inventory differs')
    maximum = bounds['selection_requests_max']
    pins = [Path(__file__), Path(bridge.__file__), trace.ROOT/'src/pastor_transcript_extractor/typesafe_selection_execution.py',
            trace.ROOT/'src/pastor_transcript_extractor/commands/analysis/structure.py',
            trace.ROOT/'tests/test_typesafe_selection_packet.py']
    return seal(dict(version=VERSION, status='PREPARED_EXECUTION_UNAUTHORIZED',
        bridge_fingerprint=plan['content_fingerprint'], bridge_path=str(plan_path), bridge_sha256=trace.digest(plan_path),
        runtime=runtime(), model=MODEL, endpoint='https://api.typesafe.ai/v1/systemone',
        implementation_files={str(p): trace.digest(p) for p in pins}, requests=rows,
        structural_deferrals=plan['structural_deferrals'],
        bounds=dict(contexts=15, family_bindings=16, provider_requests_max=maximum,
            first_pass_questions=44, second_pass_questions_max=44, nominations_max=16,
            retries=0, context_expansions=0, request_timeout_seconds=45, run_seconds_max=1800,
            active_review_minutes_max=240, reserved_input_tokens_per_request=TOKENS_PER_REQUEST,
            reserved_total_input_tokens=maximum*TOKENS_PER_REQUEST,
            list_price_usd_per_million_input_tokens=PRICE_PER_MILLION,
            list_price_usd_ceiling=str(Decimal(maximum*TOKENS_PER_REQUEST)*Decimal(PRICE_PER_MILLION)/1_000_000),
            output_charge_usd=0, provider_request_context_tokens=64000, provider_question_context_tokens=32000,
            long_context=False, measurement_requests=0, admission_requests=0),
        accounting=dict(method='Reserve full documented provider per-request context before every send; reconcile reported integer input_tokens. No long-context header. HTTP/token errors stop without retry.',
            local_tokenizer=None, exact_token_count_known=False,
            context_fit='Not locally proven. Provider default context enforcement is authoritative; overflow stops the attempt without splitting or changing a question.',
            initial_wire_bytes_total=sum(r['first_wire_bytes'] for r in rows),
            initial_wire_bytes_max=max(r['first_wire_bytes'] for r in rows),
            refinement_wire_bytes_max=max(r['refinement_wire_bytes_upper_bound'] for r in rows),
            price_source='https://docs.typesafe.ai/models', api_source='https://docs.typesafe.ai/api', checked_date='2026-10-19'),
        audit_policy=dict(scope='All nominations, all withheld/invalid families, page/point inconsistencies and all 2 structural deferrals; supplied context plus full canonical source.',
            tests=['literal exactness/order/center intersection', 'complete minimal P1 act or directed Bible explanation pair',
                'conditions, qualifications and dependencies', 'source voice, recipient and reported/current scope',
                'earliest eligible object and neighboring-act leakage', 'sentinels, missing context and saturation/unenumerated opportunities'],
            prospective_oracle='Existing frozen source references are diagnostic only. The earliest eligible object may differ; no old focal recovery score transfers. Source audit verifies every returned object and examines omissions independently.',
            decision='Nomination-feasibility diagnostic recommendation only; no numerical recall/containment PASS. Report valid, unsupported, incomplete and unresolved nominations separately by G2/current-G3/reported-G3; preserve denominators and uncertainty.',
            review_budget_exhaustion='HOLD; preserve unaudited items, no usable evidence'),
        provider_requests=0, execution_authorized=False, usable_evidence=False,
        prohibited=['measurement/admission', 'Ollama', 'new retrieval/classification', 'prompt/model/threshold changes',
            'retry or automatic context expansion', 'automatic provenance', 'collection', 'projection/scoring']))



def verify_bridge(base_dir=None):
    """Check historical bridge bytes, allowing only the archived CLI adapter.

    The new flags extend the adapter; requests and source/membership inputs must
    still match byte for byte. This does not authorize archived execution.
    """
    review.selected_windows(base_dir)
    pointer = trace.read(review.MANIFEST, True)
    path = build_paths(base_dir).evaluation / pointer['relative_path']
    if trace.digest(path) != pointer['sha256']:
        raise ValueError('Historical bridge file changed')
    plan = trace.read(path, True)
    if plan['content_fingerprint'] != pointer['input_fingerprint']:
        raise ValueError('Historical bridge identity changed')
    for name, expected in {**plan['implementation_files'], **plan['cache_files']}.items():
        if trace.digest(name) == expected:
            continue
        relative = Path(name).relative_to(trace.ROOT).as_posix()
        if relative != review.CLI_PATH:
            raise ValueError('Historical bridge dependency changed: '+name)
        raw = subprocess.run(['git', 'show', '0f03d2f:'+relative], cwd=trace.ROOT, check=True, capture_output=True).stdout
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Archived bridge CLI differs')
    if trace.digest(plan['selected_preparation_path']) != plan['selected_preparation_sha256'] or plan['provider_requests'] or plan['execution_authorized']:
        raise ValueError('Historical bridge source/scope changed')
    return plan, path


def prepare(base_dir=None):
    plan, path = verify_bridge(base_dir)
    packet = make_packet(plan, path)
    out = build_paths(base_dir).evaluation / VERSION / packet['content_fingerprint'] / 'input-v1.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(packet, ensure_ascii=False, indent=2)+'\n'
    if out.exists() and out.read_text() != raw:
        raise ValueError('Immutable selection input differs')
    out.write_text(raw)
    return packet, out


def verify(base_dir=None):
    plan, _ = verify_bridge(base_dir)
    pointer = trace.read(MANIFEST, True)
    path = build_paths(base_dir).evaluation / pointer['relative_path']
    if trace.digest(path) != pointer['sha256']:
        raise ValueError('Selection packet file changed')
    packet = trace.read(path, True)
    if packet['content_fingerprint'] != pointer['input_fingerprint'] or packet['bridge_fingerprint'] != plan['content_fingerprint']:
        raise ValueError('Selection identity changed')
    if packet['runtime'] != runtime():
        raise ValueError('Locked runtime differs')
    for name, expected in packet['implementation_files'].items():
        if trace.digest(name) != expected:
            raise ValueError('Selection implementation changed: '+name)
    if make_packet(plan, packet['bridge_path']) != packet:
        raise ValueError('Selection packet derivation changed')
    return packet, path


def require_authorization(packet, approved, decision_path=DECISION):
    if approved != packet['content_fingerprint']:
        raise ValueError('Exact --approve-input fingerprint required')
    decision = trace.read(decision_path, True)
    if (decision['status'] != 'AUTHORIZED' or decision.get('decision_owner') != 'Brian'
            or decision.get('provider_execution') is not True or decision['input_fingerprint'] != approved
            or decision['scope'] != 'one_nomination_only_attempt' or decision['bounds'] != packet['bounds']):
        raise ValueError('Nomination execution remains unauthorized; no provider client opened')
    return decision
