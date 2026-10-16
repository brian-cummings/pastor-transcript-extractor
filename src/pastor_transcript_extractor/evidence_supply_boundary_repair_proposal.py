"""Read-only verification of the V4 proposal, not a runtime admission policy.

Boolean necessary-condition exhibits are design assertions. No candidate admission,
request builder, provider or consumer calls this module as an evidence guard.
"""
from __future__ import annotations

import json

from pastor_transcript_extractor import evidence_supply_boundary_audit as audit

HERE = audit.panel.frozen.ROOT / 'docs/review-proposals/evidence-supply-boundary-v4'


def load_sealed(path):
    value = json.loads(path.read_text())
    if value['content_fingerprint'] != audit.panel.frozen.fp({k: v for k, v in value.items() if k != 'content_fingerprint'}):
        raise ValueError('Proposal artifact fingerprint mismatch')
    return value


def check_specification(spec):
    """Check finite design witnesses, without implementing a candidate guard."""
    required = {key for requirements in spec['routes'].values() for key in requirements}
    if set(spec['prerequisite_definitions']) != required or set(spec['route_output_limits']) != set(spec['routes']):
        raise ValueError('Undefined prerequisite or route output scope')
    ids = set()
    for example in spec['examples']:
        if example['test_id'] in ids:
            raise ValueError('Duplicate specification witness')
        ids.add(example['test_id'])
        requirements = spec['routes'][example['route']]
        if set(example['conditions']) != set(requirements):
            raise ValueError('Missing/extra specification prerequisite')
        # This is the proposed conjunction's truth table, not production admission.
        conjunction = all(example['conditions'][key] is True for key in requirements)
        expected = 'eligible_for_reviewed_local_namespace_only' if conjunction else 'quarantine'
        if example['expected_admission'] != expected:
            raise ValueError('Specification witness contradicts necessary conditions')
    for route, requirements in spec['routes'].items():
        if len(requirements) != len(set(requirements)):
            raise ValueError('Duplicate prerequisite')
        rows = [e for e in spec['examples'] if e['route'] == route]
        if not any(all(e['conditions'][key] is True for key in requirements) for e in rows):
            raise ValueError('Vacuous all-deny design')
        for key in requirements:
            if not any(e['conditions'][key] is False and all(e['conditions'][other] is True for other in requirements if other != key) for e in rows):
                raise ValueError('Missing single-prerequisite denial test')
    for rid in ('R021', 'R080', 'R053', 'R078', 'R111', 'R114', 'R076'):
        row = next((e for e in spec['examples'] if e['test_id'] == 'critical-' + rid), None)
        if row is None or row['expected_admission'] != 'quarantine' or row['parent_case_id'] != 'B3-' + rid:
            raise ValueError('Critical mechanism lacks a denial witness')
    return len(spec['examples'])


def verify():
    panel = audit.panel
    frozen = panel.frozen
    packet = json.loads(panel.INPUT.read_text())
    panel.validate_packet(packet)
    parent = load_sealed(audit.AUDIT)
    decision = audit.accepted_decision(parent)
    if not decision or decision['repair_implementation_authorized'] or decision['provider_calls_authorized']:
        raise ValueError('Proposal requires accepted FAIL and proposal-only authority')
    manifest = load_sealed(HERE / 'proposal-v4.json')
    if (manifest['parent_input_fingerprint'] != packet['content_fingerprint']
            or manifest['parent_audit_fingerprint'] != parent['content_fingerprint']):
        raise ValueError('Proposal parent lineage changed')
    for root, inventory in ((frozen.ROOT, manifest['pins']), (HERE, manifest['artifacts'])):
        for name, digest in inventory.items():
            path = (root / name).resolve()
            if not path.is_relative_to(root.resolve()) or frozen.v1.file_hash(path) != digest:
                raise ValueError('Pinned proposal artifact changed')
    authorization = manifest['authorization']
    if authorization != dict(proposal=True, production_repairs=False, provider_calls=False, discovery=False, collection=False, projection_scoring=False):
        raise ValueError('Proposal exceeds authorized scope')
    contexts = load_sealed(HERE / 'context-exhibits-v4.json')
    checks = load_sealed(HERE / 'check-design-v4.json')
    spec = load_sealed(HERE / 'invariant-spec-v4.json')
    cases = {c['case_id']: c for c in packet['cases']}
    if [r['parent_case_id'] for r in contexts['rows']] != list(cases):
        raise ValueError('Context exhibits omit or duplicate a historical geometry')
    sources = {v: json.loads((frozen.HERE / 'sources' / f'{v}.json').read_text())['text'] for v in packet['source_ids']}
    for row in contexts['rows']:
        case = cases[row['parent_case_id']]
        span = row['source_envelope']
        if (row['exact_roles_unchanged'] != case['candidate']['endpoints']
                or row['video_id'] != case['video_id']
                or sources[row['video_id']][span['start']:span['end']] != span['text']
                or span['end'] - span['start'] > contexts['maximum_envelope_characters']):
            raise ValueError('Context is not a bounded exact-source exhibit')
        if any(s and not span['start'] <= s['start'] < s['end'] <= span['end'] for s in row['exact_roles_unchanged'].values()):
            raise ValueError('Envelope omits an exact role')
    if checks['parent_input_fingerprint'] != packet['content_fingerprint'] or checks['frozen_V3_unchanged'] is not True:
        raise ValueError('Forward checks lost frozen lineage')
    if len(checks['rows']) != 6 or len({c['check_id'] for c in checks['rows']}) != 6:
        raise ValueError('Forward check inventory changed')
    for check in checks['rows']:
        source = sources[cases[check['parent_case_id']]['video_id']]
        for span in check['endpoints'].values():
            if span and source[span['start']:span['end']] != span['text']:
                raise ValueError('Forward endpoint differs from frozen source')
    assertions = check_specification(spec)
    if manifest['semantic_revalidation']['maximum_new_requests'] != 33 + 1 + 1 + 2:
        raise ValueError('Proposed revalidation accounting changed')
    return dict(manifest=manifest, context_exhibits=len(contexts['rows']), forward_checks=len(checks['rows']), specification_assertions=assertions)
