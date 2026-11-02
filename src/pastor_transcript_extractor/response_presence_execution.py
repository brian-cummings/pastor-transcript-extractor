"""Execute only an explicitly approved frozen presence diagnostic; never admit it."""
from dataclasses import asdict
from decimal import Decimal
import json
import os
from pathlib import Path

from . import evidence_requests as requests
from . import learning_demo_contracts as contracts
from . import response_presence_diagnostic as diagnostic
from .pastor_evidence import EvidenceArtifactStore as Store, digest

VERSION = 'response-presence-diagnostic-execution-v1'


class FrozenLedger:
    def __init__(self, packet):
        self.allowed = {b['fingerprint']: Decimal(b['reserved_usd']) for b in packet['batches']}
        self.ceiling = Decimal(packet['budget']['external_ceiling_usd'])

    def check(self, attempts, phase):
        if phase != 'source_verification' or len(attempts) >= 3:
            raise ValueError('Frozen presence attempt ceiling reached')
        if len({a['request_fingerprint'] for a in attempts}) != len(attempts):
            raise ValueError('Duplicate physical attempt; no retries')
        for attempt in attempts:
            if (attempt['request_fingerprint'] not in self.allowed
                    or Decimal(attempt['reserved_usd']) != self.allowed[attempt['request_fingerprint']]):
                raise ValueError('Attempt differs from frozen diagnostic')
        # Reserve the entire approved sequence, even when stopping early.
        if sum(self.allowed.values(), Decimal(0)) > min(self.ceiling, Decimal('.50')):
            raise ValueError('Frozen diagnostic exceeds dollar ceiling')


def locate(path):
    packet = diagnostic.report(path)
    root = Path(path).resolve().parent/'execution'
    expected = Path(packet['base_dir']).resolve()/'evaluation'/diagnostic.VERSION/packet['fingerprint']
    if root.parent != expected:
        raise ValueError('Execution artifacts must remain in the configured base and frozen packet directory')
    return packet, root


def evaluate(batch, response):
    spec = requests.RequestSpec(**batch['request'])
    requests.validate_response(spec, response)
    judgments = contracts.judgments(response, spec)
    rows = []
    for expected in batch['expectations']:
        answer = judgments[expected['observation_id']]['requested_response_present']
        rows.append(dict(window=batch['window'], **expected,
            presence_probability=answer['probability'],
            passed=answer['resolved'] == expected['presence_at_least_090'],
            receipt_fingerprint=spec.fingerprint))
    return rows


def assessment(packet, root):
    store = requests.ReceiptStore(root/'requests')
    attempts = store.attempts(); rows = []; receipts = []; failure = None
    allowed = {b['fingerprint']: b['reserved_usd'] for b in packet['batches']}
    if len(attempts) > 3 or len({a['request_fingerprint'] for a in attempts}) != len(attempts):
        raise ValueError('Frozen physical attempt inventory differs')
    for attempt in attempts:
        if (attempt['request_fingerprint'] not in allowed
                or attempt['reserved_usd'] != allowed[attempt['request_fingerprint']]
                or attempt['namespace'] != packet['batches'][0]['request']['namespace']
                or attempt['phase'] != 'source_verification'):
            raise ValueError('Foreign diagnostic attempt')
    charges = Decimal(0); retained = Decimal(0)
    for batch in packet['batches']:
        spec = requests.RequestSpec(**batch['request'])
        attempted = next((a for a in attempts if a['request_fingerprint'] == spec.fingerprint), None)
        if attempted is None:
            continue
        retained += Decimal(attempted['reserved_usd'])
        path = store.root/'receipts'/f'{spec.fingerprint}.json'
        if not path.exists():
            failure = 'Attempt has no receipt; uncertain spend, no retry or continuation'
            continue
        ref = diagnostic.reference(path); receipt = diagnostic.checked_json(ref); receipts.append(ref)
        if receipt['request'] != asdict(spec) or receipt['token_account'] != spec.preflight():
            raise ValueError('Presence receipt request/account changed')
        if receipt['response_digest'] != digest(receipt['response']):
            raise ValueError('Presence receipt response changed')
        wire_path = store.root/'wire-responses'/f'{spec.fingerprint}.json'
        if receipt['wire_response_digest'] is not None:
            wire = json.loads(wire_path.read_text())
            if digest(wire) != receipt['wire_response_digest']:
                raise ValueError('Presence wire response changed')
            if not receipt['halt'] and requests.decode_response(spec, requests.WireResponse(**wire)) != receipt['response']:
                raise ValueError('Presence wire/normalized answer mismatch')
        if receipt['halt']:
            failure = 'Provider/validation halt: '+receipt['halt']
            continue
        usage = receipt['response']['usage']
        charges += Decimal(usage['input_tokens'])*Decimal(requests.PHASES[spec.phase][5])/Decimal(1000000)
        charges += Decimal(usage['output_tokens'])*Decimal(requests.PHASES[spec.phase][6])/Decimal(1000000)
        try:
            rows.extend(evaluate(batch, receipt['response']))
        except (ValueError, KeyError, TypeError) as error:
            failure = 'Invalid presence answer: '+str(error)
    if any(not r['passed'] for r in rows):
        failure = 'Presence acceptance failed; stop without another variant'
    complete = len(rows) == 5 and len(attempts) == 3
    return dict(version=VERSION, packet_fingerprint=packet['fingerprint'],
        status='STOPPED' if failure else ('PASS' if complete else 'PENDING'),
        failure=failure, rows=rows, receipts=receipts, physical_attempts=len(attempts),
        not_run=[b['window'] for b in packet['batches']
            if not any(a['request_fingerprint'] == b['fingerprint'] for a in attempts)],
        no_call_controls=packet['no_call_controls'],
        costs=dict(usage_based_usd=str(charges), retained_attempt_reservations_usd=str(retained),
            ceiling_usd=packet['budget']['external_ceiling_usd'], invoices_reconciled=False),
        product_status=packet['product_status'], authority=packet['authority'],
        next_action=('Assess a separately approved constituent-integration proposal; do not admit results.'
            if complete and not failure else 'Review the saved failing question/state/answer; no further inference or producer revision is authorized.'))


def markdown(result, path):
    lines = ['# Presence diagnostic result', '', result['status'], '',
        '| Case | Window | Presence | Expected | Result |',
        '| --- | --- | --- | --- | --- |']
    for row in result['rows']:
        lines.append(f"| {row['label']} | {row['window']} | {row['presence_probability']} | "
            + ('>= .90' if row['presence_at_least_090'] else '< .90')
            + (' | PASS |' if row['passed'] else ' | FAIL |'))
    lines += ['', result['failure'] or 'All five presence expectations passed.', '',
        f"Physical attempts: {result['physical_attempts']}; retries: 0. Usage-based cost: ${result['costs']['usage_based_usd']} (invoices unreconciled). "
        + f"Retained attempt reservations: ${result['costs']['retained_attempt_reservations_usd']}; ceiling $0.50.", '',
        'Not run: '+(', '.join(result['not_run']) or 'none')+'. Incomplete-context A5 retained zero requests and zero findings.', '',
        result['product_status'], '', result['authority'], '', result['next_action'], '',
        'Acceptance progress: '+('presence regression acceptance passed; product acceptance remains unmet.' if result['status'] == 'PASS'
            else 'presence regression acceptance failed; no product progress established. The contract ambiguity is corrected, but its causal effect on the failed case remains unproven.'), '',
        'Offline result inspection:', '', '```bash',
        f'pte analysis profile-support presence-diagnostic-result --packet {path}', '```', '']
    return '\n'.join(lines)


def save_result(packet, root, path):
    result = assessment(packet, root)
    Store(root).write_immutable('assessment.json', result)
    text = markdown(result, path); review = root/'assessment.md'
    try:
        with review.open('x') as stream:
            stream.write(text)
    except FileExistsError:
        if review.read_text() != text:
            raise ValueError('Immutable diagnostic result review changed')
    return result


def run(path, approve_packet, *, check_only=False, transport=None):
    packet, root = locate(path)
    if approve_packet != packet['fingerprint']:
        raise ValueError('Exact frozen packet approval required')
    ledger = FrozenLedger(packet); ledger.check([], 'source_verification')
    for batch in packet['batches']:
        spec = requests.RequestSpec(**batch['request'])
        if spec.fingerprint != batch['fingerprint'] or spec.preflight() != batch['preflight']:
            raise ValueError('Approved request/preflight changed')
    if check_only:
        return dict(status='CHECKED_NO_CALLS', packet_fingerprint=packet['fingerprint'], budget=packet['budget'])
    if transport is None and not os.environ.get('TYPESAFE_API_KEY'):
        raise ValueError('Required TypeSafe credential absent; no attempt made')
    with requests.ReceiptStore(root).exclusive():
        if (root/'assessment.json').exists():
            return report(path)
        Store(root).write_immutable('authorization.json', dict(packet=diagnostic.reference(path),
            approved_packet=approve_packet, executor=diagnostic.reference(__file__),
            boundary='Three frozen presence-only requests, zero retries, $0.50 ceiling; stop at first failure.'))
        # Reconcile earlier attempts before sending anything. A failed or lost
        # request ends the run permanently, even if the process was interrupted.
        prior = assessment(packet, root)
        if prior['status'] == 'STOPPED':
            return save_result(packet, root, path)
        store = requests.ReceiptStore(root/'requests')
        for batch in packet['batches']:
            try:
                requests.execute(requests.RequestSpec(**batch['request']), ledger, store,
                    transport or requests.typesafe_transport)
            except Exception:
                # Executor saved its durable reservation/receipt. Never repeat
                # a transport failure or advance to another request after it.
                if not store.attempts():
                    raise
                return save_result(packet, root, path)
            current = assessment(packet, root)
            if current['status'] == 'STOPPED':
                break
        return save_result(packet, root, path)


def report(path):
    packet, root = locate(path)
    authorization = json.loads((root/'authorization.json').read_text())
    if authorization['packet'] != diagnostic.reference(path) or authorization['approved_packet'] != packet['fingerprint']:
        raise ValueError('Execution authorization lineage changed')
    if authorization['executor'] != diagnostic.reference(__file__):
        raise ValueError('Execution implementation changed')
    saved = json.loads((root/'assessment.json').read_text())
    if saved != assessment(packet, root):
        raise ValueError('Diagnostic assessment differs from saved receipts')
    return saved
