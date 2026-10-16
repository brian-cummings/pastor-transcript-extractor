"""Fingerprint-bound, provider-free A1 policy replay of existing V4 receipts.

No provider construction, inference, retry, automatic attestation or V4 mutation.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from pastor_transcript_extractor import g3_atomic_admission as a1
from pastor_transcript_extractor import g3_atomic_admission_review as design

v4 = a1.v4
audit = design.audit
HERE = design.HERE
ROOT = design.ROOT
INPUT = HERE / 'input-a1.json'
AUTHORIZATION = HERE / 'implementation-replay-authorization-a1.json'
TRUST_ROOT = HERE / 'replay-trust-root-a1.json'
AUDIT = HERE / 'source-audit-a1.json'


def context(base_dir=None):
    # This checks all 40 original runtime hashes, 37 receipts and V4 source audit,
    # then replays the unchanged V4 gate. No new semantic classification occurs.
    historical = audit.verify(base_dir)
    proposal = v4.sealed(design.PROPOSAL)
    design.validate_design(proposal, historical)
    root = v4.sealed(TRUST_ROOT)  # Authored source-controlled trust root, not receipt metadata.
    packet, auth = v4.sealed(INPUT), v4.sealed(AUTHORIZATION)
    if (root['authorization_sha256'] != a1.file_hash(AUTHORIZATION)
            or root['input_sha256'] != a1.file_hash(INPUT)
            or root['runner_sha256'] != a1.file_hash(Path(__file__))
            or packet['version'] != 'atomic-policy-replay-input-a1'
            or auth['input_fingerprint'] != packet['content_fingerprint']
            or auth['input_sha256'] != a1.file_hash(INPUT)
            or auth['runner_sha256'] != a1.file_hash(Path(__file__))
            or auth['proposal_fingerprint'] != proposal['content_fingerprint']
            or auth['cases'] != 24 or auth['sealed_receipts'] != 37
            or auth['runtime_directory'] != str(output_directory(base_dir))
            or packet['historical_audit_fingerprint'] != historical['content_fingerprint']
            or packet['v4_input_fingerprint'] != historical['input_fingerprint']
            or packet['original_runtime_hashes'] != historical['runtime_file_hashes']
            or packet['expected_original_quarantines'] != 22
            or packet['critical_raw_fields'] != historical['critical_raw_fields']
            or packet['provider_requests'] != 0):
        raise ValueError('Missing or stale bounded A1 replay authority')
    for name, digest in packet['pins'].items():
        if a1.file_hash(ROOT / name) != digest:
            raise ValueError('A1 replay pinned evidence/code changed')
    if set(packet['pins']) != design.PINNED_FILES | {'src/pastor_transcript_extractor/g3_atomic_admission.py',
            'docs/review-proposals/g3-atomic-admission-v1/proposal-a1.json'}:
        raise ValueError('A1 replay pin inventory incomplete')
    if packet['expected_cases'] != [dict(case_id=r['case_id'], measurement_fingerprint=r['measurement_fingerprint'])
                                    for r in historical['records']]:
        raise ValueError('Replay case/measurement inventory changed')
    v4packet = json.loads(audit.panel.INPUT.read_text())
    policy = a1.PolicyAuthority.load(HERE / 'policy-a1.json', AUTHORIZATION, root['authorization_sha256'])
    source = v4.ReviewAuthority.load(audit.REVIEW, audit.ACCEPTANCE, historical['review_acceptance_file_sha256'])
    p = policy.check(v4packet, source)
    claims = a1.ClaimAuthority.load(HERE / 'claim-review-a1.json', HERE / 'claim-review-acceptance-a1.json',
                                   auth['claim_review_acceptance_sha256'], p)
    if (packet['policy_fingerprint'] != p['content_fingerprint']
            or packet['claim_review_fingerprint'] != json.loads(claims.review_json)['content_fingerprint']):
        raise ValueError('Replay policy/claim witness identity mismatch')
    boundary = a1.Boundary(v4packet, source, policy, claims)
    decision = audit.execution.authorization(v4packet, base_dir)
    _, receipts = audit.execution.read_cache(v4packet, audit.panel.output_directory(base_dir), decision)
    # Source-controlled expectations are authored separately from actual guard output.
    expected = packet['expected_admissions']
    if set(expected) != {'B4-R003', 'B4-R004-explicit-gloss', 'B4-R018', 'B4-R053'}:
        raise ValueError('Expected positive namespaces changed')
    for row in historical['records']:
        key = row['case_id']
        if row['capability'] == 'G2' and row['admission']['item']:
            if expected[key] != row['admission']['item']:
                raise ValueError('G2 expectations changed')
    return packet, historical, boundary, receipts


def output_directory(base_dir=None):
    from pastor_transcript_extractor.config import build_paths
    return build_paths(base_dir).root / 'evaluation/g3-atomic-admission-a1'


def run(approval, base_dir=None):
    packet, historical, boundary, receipts = context(base_dir)
    if approval != packet['content_fingerprint']:
        raise ValueError('Exact --approve-packet A1 fingerprint required')
    rows, wires, unsupported, missing = [], [], [], []
    for original in historical['records']:
        case_id = original['case_id']
        case = next(c for c in boundary.base.packet['cases'] if c['case_id'] == case_id)
        m = boundary.base.measure(case_id, [receipts[k] for k in case['request_keys']])
        if m.fingerprint != original['measurement_fingerprint']:
            raise ValueError('Replay raw measurement changed')
        verdict = boundary.admit(m)
        item = json.loads(verdict.item.document_json) if verdict.item else None
        expected = packet['expected_admissions'].get(case_id)
        if item:
            wire = boundary.export(verdict.item)
            # Real serialized ingress and re-admission before consumption.
            boundary.deserialize(wire)
            wires.append(wire)
            checked = item if original['capability'] == 'G2' else {
                k: item[k] for k in ('namespace', 'positive_facts', 'utterance', 'source_voice',
                                     'conditions_and_limits', 'evidence_scope', 'circumstance_claim')}
            if expected != checked or any(item[k] is not None for k in ('circumstance_claim', 'pastor_projection', 'quality_score')):
                unsupported.append(case_id)
        elif expected is not None:
            missing.append(case_id)
        rows.append(dict(case_id=case_id, measurement_fingerprint=m.fingerprint,
                         original_v4_admission=original['admission'],
                         disposition='admitted_local_only' if item else 'quarantined',
                         reasons=list(verdict.reasons), item=item))
    consumer = boundary.consume_local(wires)
    if consumer['items'] != [r['item'] for r in rows if r['item']]:
        raise ValueError('Consumer/export mismatch')
    # Reject any critical case that was admitted, independently of expected items.
    critical = {r['case_id'] for r in historical['critical_raw_fields']}
    unsafe_critical = [r['case_id'] for r in rows if r['item'] and r['case_id'] in critical]
    unsupported = sorted(set(unsupported + unsafe_critical))
    verdict = 'FAIL' if unsupported else 'HOLD' if missing else 'PASS'
    result = dict(version='atomic-policy-replay-result-a1', input_fingerprint=packet['content_fingerprint'],
        policy_fingerprint=json.loads(boundary.policy_authority.policy_json)['content_fingerprint'],
        authorization_sha256=boundary.policy_authority.authorization_sha256,
        historical_audit_fingerprint=historical['content_fingerprint'], provider_requests=0, cases=24, sealed_receipts=37,
        raw_semantics='UNCHANGED_V4_FAIL', v4_containment='UNCHANGED_HOLD',
        admitted=sum(r['item'] is not None for r in rows), quarantined=sum(r['item'] is None for r in rows),
        by_namespace=dict(Counter(r['item']['namespace'] for r in rows if r['item'])),
        unsupported_or_unresolved_admissions=unsupported, missing_positive_controls=missing,
        provisional_containment_recommendation=verdict, independent_source_audit='PENDING', final_brian_decision=None,
        records=rows, local_consumer=consumer)
    result['content_fingerprint'] = v4.old.frozen.fp(result)
    return result


def execute(approval, base_dir=None):
    result = run(approval, base_dir)
    directory = output_directory(base_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = audit.execution.safe_child(directory, 'results-a1.json')
    if path.exists():
        if v4.sealed(path) != result:
            raise ValueError('Existing A1 result differs; preserve it for review')
    else:
        audit.execution.atomic_json(path, result)
    return result


def verify_audit(base_dir=None):
    report = v4.sealed(AUDIT)
    packet = v4.sealed(INPUT)
    result = v4.sealed(output_directory(base_dir) / 'results-a1.json')
    actual = run(packet['content_fingerprint'], base_dir)
    if (result != actual or report['result_fingerprint'] != result['content_fingerprint']
            or report['result_sha256'] != a1.file_hash(output_directory(base_dir) / 'results-a1.json')
            or report['records'] != result['records']
            or report['recommendation'] != result['provisional_containment_recommendation']
            or report['final_brian_decision'] is not None
            or report['v4_decisions'] != dict(raw_semantic='FAIL', containment='HOLD')):
        raise ValueError('A1 authored source audit/replay binding changed')
    emitted = {r['case_id']: r['item'] for r in result['records'] if r['item']}
    if set(report['emitted_field_reviews']) != set(emitted):
        raise ValueError('Missing emitted-item source review')
    for case_id, item in emitted.items():
        fields = report['emitted_field_reviews'][case_id]
        if set(fields) != set(item):
            raise ValueError('Every emitted field needs review')
        if any(f['value'] != item[k] or f['judgment'] != 'supported_within_declared_scope'
               or not f['rationale'] for k, f in fields.items()):
            raise ValueError('Unsupported or missing emitted-field review')
    return report
