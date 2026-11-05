"""Bounded dimension admission using existing producers, checks and receipts.

One canonical ledger; frozen batches only; no semantic retries. Evaluation-only
mutations cannot become runtime observations. Historical artifacts stay immutable.
"""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import json
import os
from pathlib import Path

from . import profile_section as section
from . import profile_a3_delivery as a3
from . import response_presence_diagnostic as diagnostic
from . import reviewed_b1_delivery as b1
from . import response_growth_binding as producer
from . import profile_analysis_support_execution as support
from .pastor_evidence import EvidenceArtifactStore as Store, digest

VERSION = 'reader-claim-admission-v1'
VALIDATION = ('v281b89-91', 'v3973b63-65')


def save(path, value):
    temporary = Path(path).with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2)+'\n')
    os.replace(temporary, path)


def checked(path):
    value = json.loads(Path(path).read_text())
    if value['fingerprint'] != digest({k:v for k,v in value.items() if k!='fingerprint'}):
        raise ValueError('Admission freeze changed')
    return value


def seal(value):
    return {**value, 'fingerprint':digest(value)}


def identity():
    return [diagnostic.reference(p) for p in (__file__, producer.__file__)]


def prepare(base_dir, objective, audit_path):
    root = Path(base_dir).resolve()/'evaluation'/VERSION
    root.mkdir(parents=True, exist_ok=True)
    with support.requests.ReceiptStore(root).exclusive():
        dest = root/'plan.json'
        if dest.exists():
            packet = load(dest)
            if packet['objective'] != diagnostic.reference(objective):
                raise ValueError('Cannot reset the cumulative goal allowance')
            return dict(plan=str(dest), fingerprint=packet['fingerprint'], provider_calls=0)
        audit = json.loads(Path(audit_path).read_text())
        development, validation = [Path(p) for p in audit['historical_cli_plans']]
        p = json.loads(development.read_text())
        confirm = json.loads(validation.read_text())
        # Only coordinates/metadata and hashes are inspected for validation here.
        selected = [t for t in confirm['tasks'] if t['id'] in VALIDATION]
        if tuple(t['id'] for t in selected) != VALIDATION:
            raise ValueError('Frozen additional validation coordinates unavailable')
        validation_refs = []
        for t in selected:
            if not next(s for s in confirm['source_identity'] if s['video_id']==t['window']['video_id'])['gate']['eligible']:
                raise ValueError('Validation source ineligible')
            validation_refs.append(dict(window=t['id'], window_metadata=t['window'],
                artifacts=[diagnostic.reference(validation.parent/d/t['id']/name)
                    for d,name in [('sources','result.json'),('dimensions','input.json'),('dimensions','result.json')]]))
        batches = []
        for label, wid, oid, action, eligible in [
            ('A3', a3.WINDOW, a3.OID, True, True),
            ('B1', b1.WINDOW, b1.OID, True, True),
            ('worldly-yielding', 'v3973b88-97', diagnostic.ADJACENT, True, False),
            ('background', 'v3973b74-78', diagnostic.BACKGROUND, False, False),
        ]:
            inp, source, original, out = section.dimension_input(p, development.parent, wid)
            result = section.read_dimension_result(p, development.parent, wid)
            row = next(r for r in result['findings'] if r['observation_id']==oid and r['field']=='requested_response')
            spec = producer.action_grounding_request(original, [oid])
            batches.append(task(label, wid, spec, out, source,
                dict(observation_id=oid, action=action, eligible=eligible), row))
        # Same source/candidate context; authored substitutions remain evaluation only.
        original = support.requests.RequestSpec(**json.loads((development.parent/'dimensions'/a3.WINDOW/'input.json').read_text())['request'])
        controls = {
            'unsupported-action':'The preacher asks listeners to donate all their savings to the church before they can pray.',
            'attribution-loss':'The listeners report that they have already kept their feet in the soil, kept breathing the air of prayer, and reckoned themselves dead to sin. The passage records their actual response.',
            'qualification-loss':'The preacher promises that every listener will grow unconditionally, regardless of whether they keep their feet in the soil.',
        }
        for label, value in controls.items():
            spec = producer.action_grounding_request(original, [a3.OID], evaluation_candidates={a3.OID:value})
            batches.append(task(label, a3.WINDOW, spec, development.parent/'dimensions'/a3.WINDOW,
                None, dict(observation_id=a3.OID, action=None, eligible=False), None))
        # Reconstruct the incomplete-context case without creating a request.
        _, source, spec, out = section.dimension_input(confirm, validation.parent, 'v3973b53-55')
        if spec is not None or source['observations']:
            raise ValueError('Incomplete-context abstention changed')
        prior = Path(base_dir)/'evaluation'/a3.VERSION/a3.PRESENCE_REQUEST
        preserved = [diagnostic.reference(f) for f in sorted(prior.rglob('*'))
            if f.is_file() and f.suffix in ('.json','.md')]
        if not preserved:
            raise ValueError('Delivered A3 baseline missing')
        packet = seal(dict(version=VERSION, base_dir=str(Path(base_dir).resolve()),
            objective=diagnostic.reference(objective), audit=diagnostic.reference(audit_path),
            development_plan=diagnostic.reference(development), validation_plan=diagnostic.reference(validation),
            implementation=identity(), semantic_revision=1, batches=batches,
            incomplete_context=dict(window='v3973b53-55', source=diagnostic.reference(out.parent.parent/'sources'/'v3973b53-55'/'result.json'), requests=0),
            validation=dict(coordinates=validation_refs,
                exposure='Previously used confirmation material in exposed recordings; historical outcomes exist. Not untouched. No new validation judgments opened before implementation lock.',
                selection='Fixed coordinates in method document, selected using eligibility and metadata; no generated outcome filtering.',
                acceptance='No unsupported release; preserved actor, role, polarity, scope and meaning-changing qualifications; justified abstention; at least one eligible description across the two windows. No case replacement or tuning.'),
            preserved_a3=preserved,
            method_document=diagnostic.reference(Path(__file__).parents[2]/'docs'/'READER_CLAIM_ADMISSION.md'),
            budget=dict(usd='3', attempts=30, maximum_batch_usd='.50', final_usd='.75', final_attempts=6,
                retries=0, automatic_expansion=False),
            acceptance='Two useful source-faithful automatically generated findings in different windows, ordinary support/document delivery, negative controls rejected, final frozen validation passes. Tests/provider approval alone are insufficient.'))
        Store(root).write_immutable('plan.json', packet)
        Store(root).write_immutable('ledger.json', dict(objective=packet['objective'], entries=[], stopped=None))
        (root/'PLAN.md').write_text('# Reader-claim admission freeze\n\n'+packet['acceptance']+'\n\n'+
            packet['validation']['exposure']+'\n\n'+json.dumps(dict(batches=[dict(id=t['id'],
                reserved_usd=t['reserved_usd'], hypothesis=t['hypothesis'], expected=t['expected'],
                stop=t['stop']) for t in batches], budget=packet['budget'], validation=packet['validation']),indent=2)+'\n')
        return dict(plan=str(dest), fingerprint=packet['fingerprint'], provider_calls=0,
            development_batches=[dict(id=t['id'],reserved_usd=t['reserved_usd']) for t in batches],
            validation_coordinates=list(VALIDATION))


def task(label, wid, spec, out, source, expected, old_row):
    reserve = support.requests.request_reservation(spec)
    if reserve > Decimal('.50'):
        raise ValueError('Batch exceeds fifty cents')
    return dict(id=label, window=wid, request=asdict(spec), fingerprint=spec.fingerprint,
        preflight=spec.preflight(), reserved_usd=str(reserve), maximum_attempts=1,
        historical_input=diagnostic.reference(out/'input.json'),
        historical_result=diagnostic.reference(out/'result.json'),
        historical_row=old_row, expected=expected,
        evaluation_only=spec.source_identity['evaluation_only'],
        hypothesis=('Source-grounded actor/action/role plus unchanged correctness rejects the edited claim.'
            if spec.source_identity['evaluation_only'] else
            'The source-grounded action relation recognizes the described human act or rejects background, without overriding existing correctness uncertainty.'),
        stop='Stop paid execution on unexpected admission/action result or invalid/missing receipt. Inspect exact saved evidence; no semantic retries.')


def load(path):
    packet = checked(path)
    root = Path(packet['base_dir'])/'evaluation'/VERSION
    if Path(path).resolve() != root/'plan.json' or packet['version'] != VERSION:
        raise ValueError('Use the single canonical goal packet')
    for ref in [packet['objective'], packet['audit'], packet['development_plan'], packet['validation_plan'],
                packet['method_document'], *packet['preserved_a3'], *packet['implementation']]:
        diagnostic.checked_json(ref) if Path(ref['path']).suffix=='.json' else verify_ref(ref)
    if packet['implementation'] != identity():
        raise ValueError('Admission implementation changed after freeze')
    return packet


def verify_ref(ref):
    if diagnostic.reference(ref['path']) != ref:
        raise ValueError('Frozen evidence changed: '+ref['path'])


class OneAttempt:
    def check(self, attempts, phase):
        if attempts or phase != 'source_verification':
            raise ValueError('One attempt, zero retries')


def reserve(root, packet, batch, *, final=False):
    """Persist full worst-case allocation before transport; never refund uncertainty."""
    ledger = json.loads((root/'ledger.json').read_text())
    if ledger['objective'] != packet['objective'] or ledger['stopped']:
        raise ValueError('Cumulative ledger stopped or authority changed')
    if any(e['id']==batch['id'] for e in ledger['entries']):
        raise ValueError('Batch already reserved; inspect saved result, never retry')
    amount = Decimal(batch['reserved_usd'])
    attempts = sum(e['maximum_attempts'] for e in ledger['entries'])+batch['maximum_attempts']
    cost = sum((Decimal(e['reserved_usd']) for e in ledger['entries']),Decimal(0))+amount
    if amount>Decimal('.50') or cost>Decimal('3' if final else '2.25') or attempts>(30 if final else 24):
        raise ValueError('Cumulative budget/final reserve exhausted')
    ledger['entries'].append(dict(id=batch['id'],fingerprint=batch['fingerprint'],
        reserved_usd=str(amount),maximum_attempts=batch['maximum_attempts'],phase='final' if final else 'development',status='RESERVED'))
    save(root/'ledger.json',ledger)


def assess(batch, receipt):
    spec = support.requests.RequestSpec(**batch['request'])
    if receipt['request'] != asdict(spec) or receipt['halt']:
        raise ValueError('Admission receipt missing or halted')
    judgments = producer.contract.judgments(receipt['response'],spec)
    oid = batch['expected']['observation_id']
    current = judgments[oid]
    correctness = current['requested_response'] if batch['evaluation_only'] else batch['historical_row']['checks']['requested_response']
    action = current['source_grounded_action']
    eligible = correctness['resolved'] and action['resolved']
    expected = batch['expected']
    passed = eligible==expected['eligible'] and (expected['action'] is None or action['resolved']==expected['action'])
    return dict(observation_id=oid, field='requested_response',
        value=next(i for i in spec.body['state']['items'] if i['id']==oid)['response_growth']['requested_response'],
        eligible=eligible, checks=dict(requested_response=correctness,source_grounded_action=action),
        version=VERSION, verification_request=spec.fingerprint, evaluation_only=batch['evaluation_only'],
        authority='Exact local response dimension only; no full binding, production admission, quotation or benchmark authority.',
        passed=passed)


def saved_result(root, batch):
    """Strictly offline; a missing result raises instead of entering execution."""
    result_path = root/'batches'/batch['id']/'result.json'
    result = json.loads(result_path.read_text())
    store = support.requests.ReceiptStore(result_path.parent/'execution')
    if result['usage']!=support.supervised.check.demo.usage_account(store):
        raise ValueError('Saved admission accounting changed')
    if result.get('finding'):
        spec = support.requests.RequestSpec(**batch['request'])
        receipt = support._cached(spec,store)
        if assess(batch,receipt)!=result['finding']:
            raise ValueError('Saved admission decision changed')
    return result


def run(path, batch_id, *, transport=None, check_only=False):
    packet = load(path); root = Path(path).parent
    batch = next(t for t in packet['batches'] if t['id']==batch_id)
    for ref in (batch['historical_input'], batch['historical_result']):
        diagnostic.checked_json(ref)
    spec = support.requests.RequestSpec(**batch['request'])
    if spec.fingerprint != batch['fingerprint'] or spec.preflight()!=batch['preflight']:
        raise ValueError('Frozen admission request changed')
    if check_only:
        return dict(status='CHECKED_NO_CALLS',id=batch_id,reserved_usd=batch['reserved_usd'])
    with support.requests.ReceiptStore(root).exclusive():
        result_path = root/'batches'/batch_id/'result.json'
        store = support.requests.ReceiptStore(root/'batches'/batch_id/'execution')
        if result_path.exists():
            return saved_result(root,batch)
        if transport is None and not os.environ.get('TYPESAFE_API_KEY'):
            raise ValueError('TypeSafe credential absent; no attempt made')
        prior = packet['batches'][:packet['batches'].index(batch)]
        if any(not (root/'batches'/t['id']/'result.json').exists() for t in prior):
            raise ValueError('Frozen development order required')
        reserve(root,packet,batch)
        failure = None; receipt = None; finding = None
        try:
            support.requests.execute(spec,OneAttempt(),store,transport or support.requests.typesafe_transport)
            receipt = support._cached(spec,store)
            finding = assess(batch,receipt)
        except Exception as error:
            failure = str(error)
        usage = support.supervised.check.demo.usage_account(store)
        passed = finding is not None and finding['passed'] and not failure and usage['unknown_usage_attempts']==0
        result = dict(version=VERSION,id=batch_id,status='PASS' if passed else 'STOPPED',
            finding=finding, failure=failure,usage=usage,
            receipt=diagnostic.reference(store.root/'receipts'/(spec.fingerprint+'.json')) if receipt else None,
            progress=dict(criterion_advanced='Admission discrimination on the frozen exposed case' if passed else None,
                new_evidence=finding or failure,
                next_action='Next frozen case only' if passed else 'Stop paid execution; inspect saved questions, input, answer and decision before proposing any repair.'),
            evaluation_only=batch['evaluation_only'])
        Store(result_path.parent).write_immutable('result.json',result)
        ledger = json.loads((root/'ledger.json').read_text())
        entry = next(e for e in ledger['entries'] if e['id']==batch_id)
        entry.update(status=result['status'],usage=usage,result=diagnostic.reference(result_path))
        if not passed:
            ledger['stopped'] = dict(batch=batch_id,reason='Frozen acceptance failed; no successor authorized without demonstrated defect and falsifiable repair.')
        save(root/'ledger.json',ledger)
        (result_path.parent/'RESULT.md').write_text('# Admission batch '+batch_id+'\n\n'+json.dumps(result,indent=2)+'\n')
        return result


def report(path):
    packet = load(path); root=Path(path).parent
    ledger=json.loads((root/'ledger.json').read_text())
    results=[saved_result(root,t)
        for t in packet['batches'] if (root/'batches'/t['id']/'result.json').exists()]
    known=sum((Decimal(r['usage']['known_list_price_usage_usd']) for r in results),Decimal(0))
    reserved=sum((Decimal(e['reserved_usd']) for e in ledger['entries']),Decimal(0))
    value=dict(version=VERSION,status='STOPPED' if ledger['stopped'] else 'DEVELOPMENT_PENDING',
        acceptance=False,blocker=ledger['stopped'],
        completed_batches=[dict(id=r['id'],status=r['status'],finding=r['finding']) for r in results],
        costs=dict(known_list_price_usd=str(known),conservative_reserved_usd=str(reserved),
            physical_paid_attempts=sum(r['usage']['paid_attempts'] for r in results),
            maximum_allocated_attempts=sum(e['maximum_attempts'] for e in ledger['entries']),
            unknown_usage_attempts=sum(r['usage']['unknown_usage_attempts'] for r in results),
            ceiling_usd='3',ceiling_attempts=30,invoice_usd=None),
        validation=packet['validation'], fidelity='Requires separate source review; model agreement is insufficient.',
        usefulness='Two-finding delivery not yet established.',coverage='Exposed selected windows only; no population rate or benchmark.',
        assistant_usage='Primary agent only; goal meter across turns, no specified token ceiling. Exact aggregate accounting before this goal is unavailable; reserve at least 10% of work for verification and handoff.',
        inspection_command=f'pte analysis profile-support section-admission-report --plan {path}')
    save(root/'REPORT.json',value)
    (root/'REPORT.md').write_text('# Reader-claim admission result\n\n'+value['status']+'\n\n'+json.dumps(value,indent=2)+'\n')
    return value
