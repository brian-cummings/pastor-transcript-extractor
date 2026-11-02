"""Separate authorization for the original unexecuted A3; never resume the suite."""
from decimal import Decimal
import json
import os
from pathlib import Path

from . import response_presence_diagnostic as diagnostic
from . import response_presence_execution as execution
from . import evidence_requests as requests
from .pastor_evidence import EvidenceArtifactStore as Store, digest

VERSION = 'response-presence-a3-addendum-v1'
BOUNDARY = 'One original A3 presence request; $0.01 cap; zero retries; no integration or promotion.'


def build(parent):
    packet, root = execution.locate(parent)
    prior = execution.report(parent)
    batch = packet['batches'][2]
    if (prior['status'] != 'STOPPED' or batch['window'] not in prior['not_run']
            or [r['label'] for r in batch['expectations']] != ['A3']):
        raise ValueError('Requires stopped parent with original A3 unexecuted')
    spec = requests.RequestSpec(**batch['request'])
    if (spec.fingerprint != batch['fingerprint'] or spec.preflight() != batch['preflight']
            or requests.request_reservation(spec) != Decimal(batch['reserved_usd'])
            or not Decimal('0') < Decimal(batch['reserved_usd']) <= Decimal('.01')):
        raise ValueError('Original A3 request/preflight/reservation changed or exceeds $0.01')
    proposal = dict(version=VERSION, base_dir=packet['base_dir'],
        parent=diagnostic.reference(parent),
        historical_assessment=diagnostic.reference(root/'assessment.json'),
        implementation=[diagnostic.reference(__file__), diagnostic.reference(execution.__file__),
            diagnostic.reference(requests.__file__)],
        batch=batch, budget=dict(external_ceiling_usd='0.01',
            maximum_physical_attempts=1, retries=0, automatic_expansion=False),
        authority=BOUNDARY, product_status=packet['product_status'])
    proposal['fingerprint'] = digest(proposal)
    return proposal


def prepare(parent):
    proposal = build(parent)
    path = Path(parent).resolve().parent/'a3-addendum'/'proposal.json'
    Store(path.parent).write_immutable(path.name, proposal)
    return dict(packet=str(path), fingerprint=proposal['fingerprint'], provider_calls=0)


def locate(path):
    path = Path(path).resolve()
    proposal = json.loads(path.read_text())
    if proposal != build(proposal['parent']['path']):
        raise ValueError('A3 addendum or lineage changed')
    expected = Path(proposal['parent']['path']).resolve().parent/'a3-addendum'/'proposal.json'
    if path != expected:
        raise ValueError('A3 must use its single canonical addendum store')
    return proposal, path.parent/'execution'


class Ledger:
    def check(self, attempts, phase):
        if attempts or phase != 'source_verification':
            raise ValueError('A3 one-attempt ceiling; no retries')


def assessment(proposal, root):
    # Reuse exact wire/normalized receipt and charge reconstruction, without
    # importing the original suite's five-row completion policy.
    packet = dict(batches=[proposal['batch']], fingerprint=proposal['fingerprint'],
        budget=proposal['budget'], no_call_controls=[], authority=BOUNDARY,
        product_status=proposal['product_status'])
    attempts = requests.ReceiptStore(root/'requests').attempts()
    if len(attempts) > 1:
        raise ValueError('A3 physical attempt inventory exceeds one')
    result = execution.assessment(packet, root)
    result['version'] = VERSION
    result['status'] = ('STOPPED' if result['failure'] else
        ('PASS' if len(result['rows']) == 1 and len(attempts) == 1 else 'PENDING'))
    result['original_suite_status'] = 'FAILED_IMMUTABLE'
    result['next_action'] = 'Review this case only; no integration, promotion or further inference.'
    return result


def authorization(path, proposal):
    return dict(packet=diagnostic.reference(path), approved_packet=proposal['fingerprint'],
        executor=diagnostic.reference(__file__), boundary=BOUNDARY)


def save(path, proposal, root):
    result = assessment(proposal, root)
    Store(root).write_immutable('assessment.json', result)
    text = ('# A3 presence diagnostic result\n\n'+result['status']+'\n\n'
        + 'Presence: '+str(result['rows'][0]['presence_probability'] if result['rows'] else 'unknown')
        + '; required >= .90.\n\n'+(result['failure'] or 'Single-case diagnostic success only.')
        + '\n\n'+BOUNDARY+' Original suite remains FAILED; two-finding product requirement remains unmet.\n\n'
        + 'Costs (invoices unreconciled): '+json.dumps(result['costs'])+'\n\n'
        + '```bash\npte analysis profile-support presence-a3-result --packet '+str(path)+'\n```\n')
    review = root/'assessment.md'
    if review.exists():
        if review.read_text() != text:
            raise ValueError('Immutable A3 review changed')
    else:
        review.write_text(text)
    return result


def report(path):
    proposal, root = locate(path)
    if json.loads((root/'authorization.json').read_text()) != authorization(path, proposal):
        raise ValueError('A3 authorization changed')
    saved = json.loads((root/'assessment.json').read_text())
    if saved != assessment(proposal, root):
        raise ValueError('A3 assessment differs from saved receipts')
    return saved


def run(path, approve_packet, *, check_only=False, transport=None):
    proposal, root = locate(path)
    if approve_packet != proposal['fingerprint']:
        raise ValueError('Exact A3 addendum approval required')
    if check_only:
        return dict(status='CHECKED_NO_CALLS', budget=proposal['budget'])
    with requests.ReceiptStore(root).exclusive():
        if (root/'assessment.json').exists():
            return report(path)
        if transport is None and not os.environ.get('TYPESAFE_API_KEY'):
            raise ValueError('Required TypeSafe credential absent; no attempt made')
        Store(root).write_immutable('authorization.json', authorization(path, proposal))
        store = requests.ReceiptStore(root/'requests')
        # An interrupted physical attempt is terminal, including missing receipts.
        if not store.attempts():
            try:
                requests.execute(requests.RequestSpec(**proposal['batch']['request']),
                    Ledger(), store, transport or requests.typesafe_transport)
            except Exception:
                if not store.attempts():
                    raise
        return save(path, proposal, root)
