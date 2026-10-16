"""Fixed V4 packet materialization and receipt interpretation. No paid runner."""
from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

from pastor_transcript_extractor import evidence_supply_boundary_repair_proposal as proposal
from pastor_transcript_extractor import evidence_boundary_admission as admission

old = proposal.audit.panel
HERE = proposal.HERE
INPUT = HERE / 'input-v4.json'


def build_packet():
    proposal.verify()
    authority = proposal.load_sealed(HERE / 'implementation-authorization-v4.json')
    original = json.loads(old.INPUT.read_text())
    design = proposal.load_sealed(HERE / 'proposal-v4.json')
    if (authority['proposal_fingerprint'] != design['content_fingerprint']
            or authority['proposal_sha256'] != old.frozen.v1.file_hash(HERE / 'proposal-v4.json')
            or authority['implementation_authorized'] is not True
            or authority['provider_calls_authorized'] is not False
            or authority['semantic_execution_authorized'] is not False):
        raise ValueError('Requires proposal-bound implementation-only authorization')
    contexts = proposal.load_sealed(HERE / 'context-exhibits-v4.json')['rows']
    corrections = proposal.load_sealed(HERE / 'check-design-v4.json')['rows']
    source_files = {str(v): dict(path=str((old.frozen.HERE / 'sources' / f'{v}.json').relative_to(old.frozen.ROOT)),
                               sha256=old.frozen.v1.file_hash(old.frozen.HERE / 'sources' / f'{v}.json')) for v in original['source_ids']}
    sources = {int(v): json.loads((old.frozen.ROOT / info['path']).read_text()) for v, info in source_files.items()}
    contexts = {c['parent_case_id']: c['source_envelope'] for c in contexts}
    cases, requests = [], []

    def add(case_id, parent, roles, comparisons):
        materialized = admission.materialize(sources[parent['video_id']], parent['capability'], roles, contexts[parent['case_id']])
        case = dict(case_id=case_id, parent_case_id=parent['case_id'], video_id=parent['video_id'], capability=parent['capability'],
                    candidate=materialized['candidate'], source_envelope=materialized['source_envelope'],
                    comparisons=comparisons, request_keys=[])
        for shape in materialized['shapes']:
            request = dict(version='boundary-request-v4', case_id=case_id, capability=case['capability'], model=old.frozen.MODEL,
                           phase=shape['phase'], state=shape['state'], questions=shape['questions'], question_version=shape['question_version'])
            request['request_key'] = old.frozen.fp(request)
            wire = dict(model=request['model'], state=request['state'], questions={k: dict(type='choice', **v) for k, v in request['questions'].items()})
            if len(admission.canonical(wire).encode()) > 60000:
                raise ValueError('Prepared request exceeds fixed byte guard')
            requests.append(request)
            case['request_keys'].append(request['request_key'])
        cases.append(case)

    shared = {'B4-R004-ambiguity-control', 'B4-R073-gated-withholding', 'B4-R077-fragment-control'}
    parents = {c['case_id']: c for c in original['cases']}
    for parent in original['cases']:
        comparisons = [dict(check_id='historical-' + parent['case_id'], scope='historical_V3_geometry_diagnostic', expected=parent['expected'])]
        comparisons += [dict(check_id=c['check_id'], scope='proposed_forward_check', expected=c['proposed_expected'])
                        for c in corrections if c['parent_case_id'] == parent['case_id'] and c['check_id'] in shared]
        add(parent['case_id'].replace('B3-', 'B4-'), parent, parent['candidate']['endpoints'], comparisons)
    for correction in corrections:
        if correction['check_id'] not in shared:
            add(correction['check_id'], parents[correction['parent_case_id']], correction['endpoints'],
                [dict(check_id=correction['check_id'], scope='proposed_forward_check', expected=correction['proposed_expected'])])
    if len(cases) != 24 or len(requests) != 37:
        raise ValueError('Fixed V4 panel inventory changed')
    pins = dict(original['input_hashes'])
    for path in [old.INPUT, Path(__file__), Path(admission.__file__), HERE / 'implementation-authorization-v4.json',
                 HERE / 'proposal-v4.json', HERE / 'context-exhibits-v4.json', HERE / 'check-design-v4.json', HERE / 'CRITERIA-v4.md',
                 HERE / 'source-oracle-v4.json']:
        pins[str(path.relative_to(old.frozen.ROOT))] = old.frozen.v1.file_hash(path)
    packet = dict(version='semantic-boundary-panel-v4', status='PREPARED_NOT_AUTHORIZED_FOR_EXECUTION',
                  parent_v3_fingerprint=original['content_fingerprint'], proposal_fingerprint=design['content_fingerprint'],
                  model=old.frozen.MODEL, source_files=source_files, input_hashes=pins, cases=cases, requests=requests,
                  budget=dict(maximum_attempts=37, maximum_input_tokens=37*64000,
                              maximum_list_price_usd=str(Decimal(37*64000)*Decimal('0.000000042')),
                              input_usd_per_million='0.042', output_usd_per_million='0', pricing_checked_on='2026-10-15',
                              price_source='https://docs.typesafe.ai/models', automatic_retries=0, long_context=False),
                  authorization=dict(implementation=True, packet_preparation=True, provider_calls=False, semantic_execution=False,
                                     automatic_attestation=False, discovery=False, collection=False, projection_scoring=False),
                  review_authority='No accepted V4 receipt-bound review exists. Prepared source oracle is not export authority.',
                  provider_requests_during_preparation=0)
    packet['content_fingerprint'] = old.frozen.fp(packet)
    return packet


def validate_packet(packet, reproduce=False):
    if packet.get('content_fingerprint') != old.frozen.fp({k: v for k, v in packet.items() if k != 'content_fingerprint'}):
        raise ValueError('V4 packet fingerprint mismatch')
    if packet.get('version') != 'semantic-boundary-panel-v4' or packet['model'] != old.frozen.MODEL:
        raise ValueError('Unknown V4 schema/model')
    for name, digest in packet['input_hashes'].items():
        path = (old.frozen.ROOT / name).resolve()
        if not path.is_relative_to(old.frozen.ROOT.resolve()) or old.frozen.v1.file_hash(path) != digest:
            raise ValueError('Pinned V4 input/code/source changed: ' + name)
    sources = {}
    for video_id, info in packet['source_files'].items():
        path = (old.frozen.ROOT / info['path']).resolve()
        if not path.is_relative_to(old.frozen.ROOT.resolve()) or old.frozen.v1.file_hash(path) != info['sha256']:
            raise ValueError('V4 snapshot identity changed')
        sources[int(video_id)] = json.loads(path.read_text())
    if len(packet['cases']) != 24 or len({c['case_id'] for c in packet['cases']}) != 24 or len(packet['requests']) != 37:
        raise ValueError('V4 panel count/identity drift')
    expected_requests = []
    for case in packet['cases']:
        rebuilt = admission.materialize(sources[case['video_id']], case['capability'], case['candidate']['endpoints'], case['source_envelope'])
        if case['candidate'] != rebuilt['candidate'] or case['source_envelope'] != rebuilt['source_envelope']:
            raise ValueError('V4 phase/role envelope changed')
        actual = [r for r in packet['requests'] if r['case_id'] == case['case_id']]
        if len(actual) != len(rebuilt['shapes']) or [r['request_key'] for r in actual] != case['request_keys']:
            raise ValueError('V4 phase inventory mismatch')
        for request, shape in zip(actual, rebuilt['shapes'], strict=True):
            if (request['version'] != 'boundary-request-v4' or request['model'] != packet['model'] or request['capability'] != case['capability']
                    or any(request[k] != shape[k] for k in ('phase', 'state', 'questions', 'question_version'))
                    or request['request_key'] != old.frozen.fp({k: v for k, v in request.items() if k != 'request_key'})):
                raise ValueError('V4 state/question/target/phase identity changed')
        expected_requests.extend(actual)
    if expected_requests != packet['requests'] or len({r['request_key'] for r in expected_requests}) != 37:
        raise ValueError('Duplicate/foreign V4 request')
    if packet['authorization'] != dict(implementation=True, packet_preparation=True, provider_calls=False, semantic_execution=False,
                                       automatic_attestation=False, discovery=False, collection=False, projection_scoring=False):
        raise ValueError('V4 execution/downstream authorization changed')
    if packet['budget']['maximum_attempts'] != 37 or packet['budget']['maximum_input_tokens'] != 2368000 or Decimal(packet['budget']['maximum_list_price_usd']) != Decimal('0.099456') or packet['budget']['automatic_retries'] != 0 or packet['budget']['long_context'] is not False:
        raise ValueError('V4 budget changed')
    if reproduce and build_packet() != packet:
        raise ValueError('V4 input no longer reproduces')


def interpret_receipts(packet, receipts, authority=None):
    """Actual V4 G2/G3 result path. All local exports pass the same boundary.

    No provider or file writes. Incomplete inventory is a technical failure.
    This is not permission to execute the pending semantic experiment.
    """
    boundary = admission.Boundary(packet, authority)
    keys = [r['request_key'] for r in receipts]
    if len(keys) != len(set(keys)) or set(keys) != {r['request_key'] for r in packet['requests']}:
        raise ValueError('Incomplete or duplicate V4 receipt inventory')
    by_key = dict(zip(keys, receipts, strict=True))
    observations, wires = [], []
    for case in packet['cases']:
        measurement = boundary.measure(case['case_id'], [by_key[k] for k in case['request_keys']])
        verdict = boundary.admit(measurement)
        comparisons = [dict(check_id=c['check_id'], scope=c['scope'], differences=[dict(field=k, expected=v, actual=measurement.document['decisions'].get(k)) for k, v in c['expected'].items() if measurement.document['decisions'].get(k) not in v]) for c in case['comparisons']]
        observations.append(dict(case_id=case['case_id'], raw_measurement=measurement.document,
                                 quarantine_reasons=list(verdict.reasons), comparisons=comparisons,
                                 admission='admitted_local_only' if verdict.item else 'quarantined'))
        if verdict.item:
            wires.append(boundary.export(verdict.item))
    return dict(version='semantic-boundary-results-v4', input_fingerprint=packet['content_fingerprint'],
                observations=observations, local_evidence=boundary.consume_local(wires),
                raw_semantic_verdict='pending_full_source_audit', containment_verdict='pending_full_source_audit_and_Brian_decision',
                discovery_readiness=None, collection=None, pastor_projection=None, quality_score=None)


def output_directory(base_dir=None):
    # Reuse the configured external base restriction, never the old result folder.
    directory = (old.output_directory(base_dir).parent / 'evidence-supply-boundary-v4').resolve()
    if directory.is_relative_to(old.frozen.ROOT.resolve()):
        raise ValueError('V4 runtime artifacts must stay outside the repository')
    return directory


def write_packet():
    packet = build_packet()
    validate_packet(packet)
    INPUT.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + '\n')
    return packet
