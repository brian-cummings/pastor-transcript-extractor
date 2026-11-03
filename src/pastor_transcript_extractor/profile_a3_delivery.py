"""Offline, explicitly reviewed A3 composition through ordinary section support.

This is one-case delivery authority, never general dimension admission. Missing
support is reported, not purchased, fabricated or replaced with authored prose.
"""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from . import response_presence_a3 as a3
from . import response_presence_diagnostic as diagnostic
from . import response_growth_binding as producer
from . import profile_section as section
from . import profile_analysis_support_execution as support
from .pastor_evidence import EvidenceArtifactStore as Store, SourceWindow, digest

VERSION = 'reviewed-a3-section-delivery-v1'
OID = diagnostic.TARGETS['A3']
WINDOW = diagnostic.WINDOWS[2]
CORRECTNESS_REQUEST = '24269465619cba3bbe08136e8f1638682df6b3c0b13dff8ed93c03cac27d5ff4'
PRESENCE_REQUEST = '2280d26f5afd4b8c7a6940de38fc845eb80624e774617d7859f67867c786c37a'
AUTHORITY = 'Explicitly reviewed A3 local response only; no complete-binding or general automatic admission.'
LIMIT = ('One deliberately selected, individually reviewed A3 example in recording 4589. '
    'The broader presence diagnostic remains FAILED; the two-finding product requirement remains unmet. '
    'No recurrence, general reliability, complete theology or actual listener uptake is established.')


def composition(path):
    proposal, _ = a3.locate(path)
    result = a3.report(path)
    batch = proposal['batch']
    if batch['window'] != WINDOW or result['status'] != 'PASS':
        raise ValueError('Only the completed passing A3 case is authorized')
    refs = batch['evidence']
    original_input = next(r for r in refs if '/dimensions/' in r['path'] and r['path'].endswith('/input.json'))
    old = diagnostic.checked_json(original_input)
    original = support.requests.RequestSpec(**old['request'])
    expected = producer.presence_diagnostic_request(original)
    if (original.fingerprint != CORRECTNESS_REQUEST or expected.fingerprint != PRESENCE_REQUEST
            or asdict(expected) != batch['request']):
        raise ValueError('Presence candidate/source/context/model or question differs')
    original_result = next(r for r in refs if '/dimensions/' in r['path'] and r['path'].endswith('/result.json'))
    historical = diagnostic.checked_json(original_result)
    ref = historical['receipt']
    receipt = support._cached(original, support.requests.ReceiptStore(Path(ref['path']).parent.parent))
    if receipt is None or receipt['halt'] or diagnostic.reference(ref['path']) != ref:
        raise ValueError('Historical correctness receipt incomplete or changed')
    judgments = producer.contract.judgments(receipt['response'], original)[OID]
    presence = result['rows'][0]
    if (len(original.body['state']['items']) != 1 or original.body['state']['items'][0]['id'] != OID
            or presence['observation_id'] != OID or not judgments['requested_response']['resolved']
            or judgments['requested_response']['probability'] < .90
            or not presence['passed'] or presence['presence_probability'] < .90):
        raise ValueError('Exact A3 correctness and presence must each meet .90')
    value = original.body['state']['items'][0]['response_growth']['requested_response']
    constituents = dict(correctness=dict(receipt=ref, request=original.fingerprint,
        contract=original.version, answer=judgments['requested_response']),
        presence=dict(receipt=result['receipts'][0], request=expected.fingerprint,
            contract=producer.PRESENCE_CONTRACT,
            answer=dict(probability=presence['presence_probability'], resolved=presence['passed'])))
    row = dict(observation_id=OID, field='requested_response', value=value, eligible=True,
        checks=dict(requested_response=judgments['requested_response'],
            requested_response_present=constituents['presence']['answer']),
        version=VERSION, authority=AUTHORITY, constituents=constituents,
        composition_rule='Conjunction of separately versioned .90 gates; no averaging or synthetic model receipt.',
        historical_presence=judgments['requested_response_present'], historical_result_unchanged=True)
    return dict(version=VERSION, a3_packet=diagnostic.reference(path),
        original_input=original_input, original_result=original_result,
        row=row, authority=AUTHORITY, threshold=.90,
        source_state_digest=digest(original.body['state']), model=original.body['model'])


def proof(record, window, oid):
    marker = record['reviewed_dimension_composition']
    saved = diagnostic.checked_json(marker)
    rebuilt = composition(saved['a3_packet']['path'])
    if saved != rebuilt or oid != OID or window.id != WINDOW:
        raise ValueError('Reviewed composition is restricted to exact A3')
    observations = [o for o in record['machine_observations']
        if {r['window_id'] for r in o['source_refs']} == {window.id}]
    original = producer.dimension_verification(window, observations)
    packet = diagnostic.checked_json(saved['original_input'])
    if asdict(original) != packet['request']:
        raise ValueError('Reviewed A3 source/candidate/scope differs from historical correctness')
    refs = [marker, saved['a3_packet'], saved['original_input'], saved['original_result']]
    refs += [c['receipt'] for c in saved['row']['constituents'].values()]
    return deepcopy(saved['row']), {r['path']:r['sha256'] for r in refs}


def deliver(path, approve_case):
    if approve_case != OID:
        raise ValueError('Explicit approval of exact A3 case required')
    composed = composition(path)
    proposal, _ = a3.locate(path)
    parent = diagnostic.checked_json(proposal['parent'])
    source_ref = next(r for r in proposal['batch']['evidence'] if '/sources/' in r['path'])
    original_root = Path(source_ref['path']).parent.parent.parent
    plan_ref = next(r for r in parent['historical_plans'] if Path(r['path']).parent == original_root)
    p = diagnostic.checked_json(plan_ref)
    # Rebuild and validate the historical support plan, including individual
    # machine source/verification and dimension proofs, before reusing any row.
    original_record = support.core.read_record(original_root/'assembled-profile.json')
    frozen = json.loads((original_root/'support-plan.json').read_text())
    if (diagnostic.file_hash(original_root/'assembled-profile.json') != frozen['profile_sha256']
            or support.core.build_plan(original_record) != frozen['plan']):
        raise ValueError('Historical assembled record/support evidence changed')
    root = Path(p['base_dir'])/'evaluation'/VERSION/proposal['batch']['fingerprint']
    Store(root).write_immutable('composition.json', composed)
    record = deepcopy(original_record)
    observation = next(o for o in record['machine_observations'] if o['id'] == OID)
    if [c['id'] for c in record['claims']] != ['section-dimension-growth-'+OID]:
        raise ValueError('Expected only the historical A3 growth claim')
    record['reviewed_dimension_composition'] = diagnostic.reference(root/'composition.json')
    claim = section.dimension_claim(observation, composed['row'])
    record['claims'].append(claim)
    record['reader']['claims'] = record['claims']
    record['reader']['portrait']['entries'] = record['claims']
    Store(root).write_immutable('assembled-profile.json', record)
    plan = support.core.build_plan(record)
    rows = []; tasks = []; gaps = []
    spend = Path(p['base_dir'])/'evaluation'/'qualified-observations'
    for item in plan['items']:
        if item['case'] is None:
            raise ValueError('Case-specific assembly failed: '+str(item['gap']))
        spec = support.make_request(item['case'], whole_statement=True)
        store = support.requests.ReceiptStore(spend/spec.fingerprint/'execution')
        receipt = support._cached(spec, store)
        tasks.append(dict(claim_id=item['claim_id'], request=asdict(spec),
            fingerprint=spec.fingerprint, token_account=spec.preflight(),
            reserved_usd=str(support.requests.request_reservation(spec))))
        if receipt is not None:
            rows.append(support._row(item, spec, receipt, store, cached=True))
        else:
            gap = dict(blocked_statement=item['statement'],
                inspected_reuse=['Historical correctness .91 and growth .96',
                    'Separate A3 presence .96', 'Reconstructed historical support plan: growth only',
                    'Exact whole-statement support receipt '+str(store.root)],
                missing_information='No saved whole-statement support judgment for this exact candidate, composite authority and source context.',
                responsible_producer='Existing penultimate profile analysis-support stage',
                smallest_change='Separately authorize one frozen ordinary support assessment; no extraction, correctness or presence rerun.',
                acceptance='Existing whole-statement support and qualification/assertion-force checks pass for unchanged candidate; final presentation preserves it verbatim.',
                authorization_boundary='No paid calls authorized by this delivery pilot; no automatic execution or corrections.',
                request_fingerprint=spec.fingerprint, reserved_usd=str(support.requests.request_reservation(spec)))
            gaps.append(gap)
            rows.append(dict(claim_id=item['claim_id'], status='not_run', judgment=None,
                receipt=None, cache_reuse=False, failure=gap['missing_information']))
    Store(root).write_immutable('support-plan.json', dict(plan=plan,tasks=tasks,paid_calls_authorized=False))
    Store(root).write_immutable('support-results.json',dict(results=rows,new_provider_calls=0))
    document = support.core.document_input(plan, rows)
    pilot_plan = {**p, 'limitation':LIMIT, 'unknowns':[
        'One reviewed local example only; no second independently qualified substantive finding.',
        'Actual listener response, recurrence, frequency, complete conditions and wider theology remain unknown.',
        'Broader requested-or-described-response reliability remains unvalidated.']}
    section.write_document(pilot_plan, root, record, document)
    ready = 'section-dimension-requested_response-'+OID in document['ready_claim_ids']
    result = dict(version=VERSION,status='DELIVERED_CASE_ONLY' if ready else 'BLOCKED_MISSING_ANALYSIS_SUPPORT',
        root=str(root),draft=str(root/'draft-section.md'),document_input=str(root/'document-input.json'),
        compatibility='Exact source, candidate, scope and model; separate correctness/presence contracts and receipts retained.',
        ready_claim_ids=document['ready_claim_ids'],gaps=gaps,new_provider_calls=0,new_provider_cost_usd='0',
        acceptance='Requested response, gradual growth and attached qualifications delivered unchanged through ordinary support and final presentation.' if ready else 'Substantive response delivery unproven; growth-only partial output is not the requested milestone.',
        original_suite_status='FAILED_IMMUTABLE',two_finding_requirement='UNMET',production_admission='not_admitted',
        authorization='Brian explicitly authorized this case-specific composition and delivery; no general admission or paid calls.',
        command=f'pte analysis profile-support section-reviewed-delivery --a3-packet {Path(path).resolve()} --approve-case {OID}',
        next_action='Review the delivered case only; no automatic expansion.' if ready else 'Decide separately whether to authorize the exact missing whole-statement support assessment; no second-finding work follows automatically.')
    Store(root).write_immutable('delivery.json',result)
    (root/'ACCEPTANCE.md').write_text('# A3 delivery pilot\n\n'+result['status']+'\n\n'
        +result['acceptance']+'\n\n'+result['compatibility']+'\n\n'
        +'Zero new provider calls / $0. Original diagnostic FAILED; two-finding requirement UNMET.\n\n'
        +'## Exact blocking gaps\n\n'+json.dumps(gaps,indent=2)+'\n\n'
        +'## Reproduce offline\n\n```bash\n'+result['command']+'\n```\n')
    return result
