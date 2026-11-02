"""Provider-free preparation of Astra's fixed, exposed presence diagnostic.

No execution or evidence composition is authorized by this module. Requests are
frozen separately from historical dimension receipts and cannot release findings.
"""
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path

from . import evidence_requests as requests
from . import response_growth_binding as producer
from .pastor_evidence import EvidenceArtifactStore as Store, SourceWindow, digest
from .profile_support_validation import file_hash

VERSION = 'response-presence-diagnostic-preparation-v1'
WINDOWS = ('v3973b74-78', 'v3973b88-97', 'v4589b43-48', 'v3973b53-55')
BACKGROUND = '7c0742ac71636f662941f8f65f5c60a64781f58119e94c07998562eb8b146967'
ADJACENT = 'c1f74334f746ece660235eb8eb8d24849a731d2020fdc3909268670470ba8f09'
TARGETS = {
    'A1': '0b385b8515a2bac8daaec16185d757c05497e17c8b6be94096dc8432e5928f97',
    'A2': '5b83c015cc2246866492701732d63c9c1f5f02d436ae99494479e257d79b48d0',
    'A3': 'cc2cd80a51f7f6ec2aff12bb29dbbbe991e445fca248ccd8368675371879c9d7',
    'A4': BACKGROUND, 'A5': None,
}


def reference(path):
    return dict(path=str(Path(path).resolve()), sha256=file_hash(path))


def checked_json(ref):
    if file_hash(ref['path']) != ref['sha256']:
        raise ValueError('Diagnostic evidence changed: '+ref['path'])
    return json.loads(Path(ref['path']).read_text())


def build(base_dir, audit):
    """Reconstruct all four historical requests before freezing any comparison."""
    audit_ref = reference(audit)
    data = checked_json(audit_ref)
    if data['version'] != 'verifier-contract-audit-v1':
        raise ValueError('Requires Astra verifier-contract-audit-v1')
    if {c['id']: c['observation_id'] for c in data['cases']} != TARGETS:
        raise ValueError('Diagnostic case inventory differs')
    if tuple(w['window'] for w in data['windows']) != WINDOWS:
        raise ValueError('Diagnostic must retain the four audited windows')
    plans = [reference(p) for p in data['historical_cli_plans']]
    tasks = {}
    for ref in plans:
        plan = checked_json(ref)
        if plan['input_fingerprint'] != digest({k: v for k, v in plan.items() if k != 'input_fingerprint'}):
            raise ValueError('Historical plan fingerprint differs')
        tasks.update({t['id']: t for t in plan['tasks']})
    batches = []; observations = set(); controls = []
    for row in data['windows']:
        files = {r['path']: checked_json(r) for r in row['artifacts']}
        def artifact(suffix):
            return next(v for p, v in files.items() if p.endswith(suffix))
        window = SourceWindow(**tasks[row['window']]['window'])
        source = artifact('/sources/'+row['window']+'/result.json')
        old_input = artifact('/dimensions/'+row['window']+'/input.json')
        old_result = artifact('/dimensions/'+row['window']+'/result.json')
        if old_input['fingerprint'] != digest({k: v for k, v in old_input.items() if k != 'fingerprint'}):
            raise ValueError('Historical input fingerprint differs')
        if old_result['input_fingerprint'] != old_input['fingerprint']:
            raise ValueError('Historical result lineage differs')
        original = producer.dimension_verification(window, source['observations'])
        if (asdict(original) if original else None) != old_input['request']:
            raise ValueError('Historical request reconstruction differs')
        if original is None:
            if source['observations'] or old_result['findings'] or old_result['receipt'] is not None:
                raise ValueError('Incomplete-context no-call control differs')
            controls.append(dict(window=row['window'], request=None, provider_calls=0,
                observations=0, findings=0, evidence=row['artifacts']))
            continue
        receipt = checked_json(old_result['receipt'])
        if receipt['request'] != asdict(original) or receipt['halt']:
            raise ValueError('Historical receipt request differs')
        if receipt['response_digest'] != digest(receipt['response']):
            raise ValueError('Historical response digest differs')
        requests.validate_response(original, receipt['response'])
        findings = producer.dimension_findings(source['observations'], receipt['response'], original)
        if findings != old_result['findings'] or findings != row['findings']:
            raise ValueError('Historical release decisions differ')
        revised = producer.presence_diagnostic_request(original)
        expectations = []
        for item in original.body['state']['items']:
            oid = item['id']; observations.add(oid)
            expectations.append(dict(observation_id=oid, presence_at_least_090=oid != BACKGROUND,
                old_checks={r['field']: r['checks'] for r in findings if r['observation_id'] == oid},
                label=next((k for k, v in TARGETS.items() if v == oid), 'adjacent_worldly_yielding')))
        batches.append(dict(window=row['window'], request=asdict(revised),
            fingerprint=revised.fingerprint, preflight=revised.preflight(),
            reserved_usd=str(requests.request_reservation(revised)), expectations=expectations,
            evidence=row['artifacts'], original_dimension_request=original.fingerprint))
    if observations != {v for v in TARGETS.values() if v} | {ADJACENT} or len(batches) != 3 or len(controls) != 1:
        raise ValueError('Expected exactly five observations, three requests and one no-call control')
    total = sum((Decimal(b['reserved_usd']) for b in batches), Decimal(0))
    if total > Decimal('.50'):
        raise ValueError('Worst-case reservation exceeds $0.50; stop without expansion')
    packet = dict(version=VERSION, contract=producer.PRESENCE_CONTRACT,
        base_dir=str(Path(base_dir).resolve()), audit=audit_ref, historical_plans=plans,
        implementation=[reference(producer.__file__), reference(__file__), reference(requests.__file__)],
        batches=batches, no_call_controls=controls,
        offline_checks=dict(historical_requests_reconstructed_exactly=4,
            historical_release_decisions_preserved=4, frozen_observations=5,
            original_artifact_hashes_verified=sum(len(w['artifacts']) for w in data['windows']),
            no_call_control_preserved=True, state_and_model_unchanged=True),
        budget=dict(external_ceiling_usd='0.50', worst_case_reserved_usd=str(total),
            maximum_physical_attempts=3, retries=0, automatic_expansion=False),
        status='PREPARED_NOT_AUTHORIZED', provider_calls=0, charge_usd='0',
        acceptance='All A1-A3 and adjacent worldly-yielding presence >= .90; A4 presence < .90; A5 no request. Any failure stops the sequence, no next variant.',
        authority='Presence-only exposed development diagnostic; no dimension eligibility, production admission, benchmark validation or historical evidence mutation.',
        integration_gap='Existing dimension proof reconstructs whole requests. No adapter is authorized here. Any later constituent composition must prove source, candidate meaning, question, model and policy compatibility and retain separate receipt lineage.',
        product_status='UNMET: A1 correctness .86 and A2 .89 remain withheld; at most A3 could newly qualify. Recording/example cap unchanged.',
        execution_boundary='Explicit approval of this exact packet required before any provider call. Preparation/reporting commands never execute requests.',
        assistant_usage='No helper agents; no token ceiling specified. Exact prior aggregate metering unavailable; scope bounded to this correction and four saved windows.')
    packet['fingerprint'] = digest(packet)
    return packet


def markdown(packet, path):
    return ('# Frozen presence diagnostic proposal\n\n'
        + packet['status']+' — **0 provider calls / $0 new charge.**\n\n'
        + 'Three presence-only requests, five unchanged candidates; one provider-free incomplete-context control. '
        + 'Source/candidate state and model are unchanged. Correctness and growth are not repurchased.\n\n'
        + 'Engineering acceptance: all four historical requests reconstruct exactly, saved release decisions match, '
        + 'all audited artifact hashes verify, and the no-call control remains intact. '
        + 'This removes the contradictory criteria; it does not establish that the ambiguity caused the low scores.\n\n'
        + f"Worst-case reservation: **${packet['budget']['worst_case_reserved_usd']}**; total ceiling $0.50; maximum three physical attempts; zero retries.\n\n"
        + '## Acceptance and stop\n\n'+packet['acceptance']+'\n\n'
        + packet['authority']+'\n\n'+packet['product_status']+'\n\n'
        + '## Integration gap and authorization\n\n'+packet['integration_gap']+'\n\n'
        + packet['execution_boundary']+'\n\n'
        + 'Recommendation: approve only the exact frozen diagnostic below, preserving all stated limits; stop and review saved answers on any failure. '
        + 'No producer revision or automatic successor is proposed.\n\n'
        + '## Offline inspection\n\n```bash\n'
        + f'pte analysis profile-support presence-diagnostic-report --packet {path}\n```\n\n'
        + f"Packet fingerprint: `{packet['fingerprint']}`.\n\n"
        + packet['assistant_usage']+'\n')


def prepare(base_dir, audit):
    packet = build(base_dir, audit)
    root = Path(base_dir)/'evaluation'/VERSION/packet['fingerprint']
    store = Store(root)
    store.write_immutable('proposal.json', packet)
    review = root/'proposal.md'
    text = markdown(packet, root/'proposal.json')
    try:
        with review.open('x') as stream:
            stream.write(text)
    except FileExistsError:
        if review.read_text() != text:
            raise ValueError('Immutable diagnostic review differs')
    return dict(packet=str(root/'proposal.json'), review=str(root/'proposal.md'),
        fingerprint=packet['fingerprint'], status=packet['status'], budget=packet['budget'], provider_calls=0)


def report(path):
    packet = json.loads(Path(path).read_text())
    if packet != build(packet['base_dir'], packet['audit']['path']):
        raise ValueError('Frozen diagnostic or its evidence/implementation changed; no execution')
    return packet
