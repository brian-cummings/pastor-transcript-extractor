"""Read-only proposal review. No retrieval implementation or execution route."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'docs/review-proposals/collector-retrieval-design-v1'


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sealed(path):
    value = json.loads(path.read_text())
    body = {k: v for k, v in value.items() if k != 'content_fingerprint'}
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    if value.get('content_fingerprint') != fingerprint:
        raise ValueError('Proposal fingerprint changed: ' + path.name)
    return value


def validate(plan, decision):
    authority = dict(proposal_preparation=True, repair_implementation=False, dataset_execution=False,
        local_encoder_execution=False, provider_calls=False, source_selection=False,
        reference_changes=False, collection=False, projection_scoring=False)
    if (plan['status'] != 'PROPOSAL_ONLY' or plan['authorization'] != authority
            or decision['authorized'] != authority or plan['decision_fingerprint'] != decision['content_fingerprint']):
        raise ValueError('Proposal-only authorization changed')
    if decision['accepted']['Fresh_V3'] != 'scoped_FAIL' or decision['accepted']['G1_assurance'] != 'HOLD':
        raise ValueError('Accepted V3 decision changed')
    b = plan['budget']
    if (b['G2_emissions_max_per_N'] != 8 or b['G3_emissions_max_per_N'] != 2
            or sum(b['G2_lanes'].values()) != 8 or b['source_candidate_ceiling'] != 12000
            or b['total_candidate_ceiling'] != 20000 or b['max_frame_chars'] != 6000
            or b['max_envelope_chars'] != 6000 or b['G1_source_ceiling'] != 200):
        raise ValueError('Frozen candidate/request ceilings changed')
    if (plan['retrieval_model']['installed_or_executed'] is not False
            or plan['confirmation']['new_sources_selected_now'] is not False):
        raise ValueError('Proposal falsely claims execution/selection')


def verify():
    decision = sealed(HERE / 'decision-v1.json')
    plan = sealed(HERE / 'proposal-v1.json')
    validate(plan, decision)
    manifest = sealed(HERE / 'packet-v1.json')
    for name, digest in {**plan['pins'], **manifest['files']}.items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or file_hash(path) != digest:
            raise ValueError('Pinned design/baseline changed: ' + name)
    triage = sealed(HERE / 'g3-diagnostic-analysis-v1.json')
    review_path = ROOT / 'docs/review-proposals/fresh-discovery-readiness-v3/source-review-v3.json'
    review = json.loads(review_path.read_text())
    missed = {x['reference_id'] for x in review['case_reviews'] if x['route'].startswith('G3') and x['candidate_id'] is None}
    rows = triage['rows']
    if (len(rows) != 27 or {r['reference_id'] for r in rows} != missed
            or any(r['new_reference'] is not None or r['historical_score'] != 'MISS_UNCHANGED' for r in rows)):
        raise ValueError('G3 diagnostic ledger changed frozen misses')
    return plan, manifest
