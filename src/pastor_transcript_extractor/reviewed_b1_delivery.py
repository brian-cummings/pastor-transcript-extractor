"""Frozen B1 qualification and conditional delivery under one explicit approval."""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
import json
import os
from pathlib import Path

from . import profile_section as section
from . import profile_a3_delivery as a3
from . import profile_analysis_support_execution as support
from . import response_presence_diagnostic as diagnostic
from . import response_growth_binding as producer
from .pastor_evidence import EvidenceArtifactStore as Store, digest

VERSION = 'reviewed-b1-delivery-v1'
PROPOSAL = '081b27e5c8e45b642cc3898fd4e2d8f0da2cdffdebed85e5f0a98409688d8a51'
OID = 'b660eea4d08f39d631d2be493201b9c3b0051085620cc279206a5181e957dbd2'
WINDOW = 'v3973b68-70'
ORIGINAL = '96c12deba773703cb64b940d06075aded54fee180b13418a5caff84cc30c6c15'
PRESENCE = 'b4ab64f16f7a8518b5d48ec20484c29f45f91f82da2657017cccf1f570033c54'
AUTHORITY = 'Explicitly reviewed B1 local described response only; no full-binding or general admission.'


def load(path):
    packet = json.loads(Path(path).read_text())
    if packet['fingerprint'] != PROPOSAL or digest({k:v for k,v in packet.items() if k!='fingerprint'}) != PROPOSAL:
        raise ValueError('Exact approved B1 proposal required')
    for ref in packet['evidence']:
        if diagnostic.reference(ref['path']) != ref:
            raise ValueError('B1 historical evidence changed')
    frozen = diagnostic.checked_json(packet['proposed_presence']['packet'])
    spec = support.requests.RequestSpec(**frozen['request'])
    plan_path = Path(packet['evidence'][0]['path'])
    p = json.loads(plan_path.read_text())
    inp, source, original, _ = section.dimension_input(p, plan_path.parent, WINDOW)
    result = section.read_dimension_result(p, plan_path.parent, WINDOW)
    row = next(r for r in result['findings'] if r['observation_id']==OID)
    clarified = producer.presence_diagnostic_request(original)
    key = OID+':requested_response_present'
    expected = replace(clarified,body={**clarified.body,'questions':{key:producer.presence_question(1)}},
        version='response-growth-reviewed-case-presence-v1',namespace='response-growth-reviewed-case-presence-v1',
        source_identity={**original.source_identity,'contract':producer.PRESENCE_CONTRACT,
            'original_dimension_request':original.fingerprint,
            'authority':'presence_constituent_only_no_automatic_release','reviewed_observation_id':OID})
    if (original.fingerprint != ORIGINAL or spec.fingerprint != PRESENCE or spec != expected
            or spec.preflight() != frozen['preflight']
            or spec.body['state']['items'][1]['id'] != OID
            or row['checks']['requested_response']['probability'] < .90
            or not row['checks']['requested_response']['resolved']
            or row['value'] != packet['candidate']['value']):
        raise ValueError('B1 source/candidate/question/model/correctness compatibility failed')
    if support.requests.request_reservation(spec)>Decimal('.01') or Decimal('.01')+Decimal('.03')>Decimal('.04'):
        raise ValueError('B1 full-sequence reservation exceeds approved cap')
    root = Path(p['base_dir'])/'evaluation'/VERSION/PROPOSAL
    prior_root = Path(p['base_dir'])/'evaluation'/a3.VERSION/a3.PRESENCE_REQUEST/'approved-support'
    prior = json.loads((prior_root/'REVIEW.json').read_text())
    for key in ('delivery','document','section','receipt','approval'):
        ref=prior[key]
        if diagnostic.reference(ref['path'])!=ref:raise ValueError('Delivered A3 evidence changed')
    baseline=diagnostic.checked_json(prior['approval'])
    for ref in baseline['preserved_files']:
        if diagnostic.reference(ref['path'])!=ref:raise ValueError('Preserved A3 preparation changed')
    return dict(packet=packet,p=p,plan_path=plan_path,source=source,original=original,
        historical_result=result,historical_row=row,spec=spec,root=root)


class PresenceLedger:
    def check(self, attempts, phase):
        if attempts or phase!='source_verification':
            raise ValueError('B1 presence: one physical attempt, zero retries')
        if support.requests.reservation('source_verification')>Decimal('.01'):
            raise ValueError('B1 presence reservation exceeds $0.01')


def obtain(spec, store, *, cap, maximum_attempts, transport):
    """Reuse the durable executor; an interrupted request is terminal."""
    if spec.phase=='source_verification' and spec.fingerprint!=PRESENCE:
        raise ValueError('Only the approved B1 presence fingerprint may execute')
    if support.requests.request_reservation(spec)>Decimal(cap):
        raise ValueError('Request exceeds frozen stage cap')
    failure = None
    try:
        receipt = support._cached(spec, store)
        if receipt is None and not store.attempts():
            ledger = (PresenceLedger() if spec.phase=='source_verification' else
                support.provider.OneRequestLedger(cap,spec.version))
            support.requests.execute(spec,ledger,store,transport)
    except Exception as error:
        if not store.attempts():
            raise
        failure = str(error)
    usage = support.supervised.check.demo.usage_account(store)
    if usage['paid_attempts']>maximum_attempts or Decimal(usage['reserved_usd'])>Decimal(cap):
        raise ValueError('Physical attempt or reservation ceiling exceeded')
    try:receipt = support._cached(spec,store)
    except (ValueError,OSError):receipt = None
    uncertain = usage['unknown_usage_attempts']>usage.get('reserved_cancelled_usage_attempts',0)
    return receipt,dict(usage=usage,failure=failure,unresolved_usage=uncertain)


def presence_result(spec, store):
    receipt = support._cached(spec,store)
    if receipt is None or receipt['halt']:
        raise ValueError('B1 presence receipt missing or halted')
    support.requests.validate_response(spec,receipt['response'])
    answer = producer.contract.judgments(receipt['response'],spec)[OID]['requested_response_present']
    return receipt,answer


def composition(path):
    data = load(path);spec=data['spec'];root=data['root']
    store = support.requests.ReceiptStore(Path(data['p']['base_dir'])/'evaluation/qualified-observations'/spec.fingerprint/'execution')
    receipt,answer = presence_result(spec,store)
    usage = support.supervised.check.demo.usage_account(store)
    if not answer['resolved'] or answer['probability']<.90 or usage['unknown_usage_attempts']:
        raise ValueError('B1 presence must pass with resolved usage before composition')
    old = data['historical_row'];historical=data['historical_result']
    row = dict(observation_id=OID,field='requested_response',value=old['value'],eligible=True,
        version=VERSION,authority=AUTHORITY,
        checks=dict(requested_response=old['checks']['requested_response'],requested_response_present=answer),
        constituents=dict(correctness=dict(receipt=historical['receipt'],request=ORIGINAL,
            contract=producer.DIMENSION_VERIFICATION_VERSION,answer=old['checks']['requested_response']),
            presence=dict(receipt=diagnostic.reference(store.root/'receipts'/(PRESENCE+'.json')),
                request=PRESENCE,contract=producer.PRESENCE_CONTRACT,answer=answer)),
        composition_rule='Separate .90 gates in conjunction; no synthetic combined model receipt.',
        historical_presence=old['checks']['requested_response_present'],historical_result_unchanged=True)
    return dict(version=VERSION,proposal=diagnostic.reference(path),row=row,
        original_input=diagnostic.reference(data['plan_path'].parent/'dimensions'/WINDOW/'input.json'))


def proof(record,window,oid):
    marker = record['reviewed_case_compositions'][oid]
    saved = diagnostic.checked_json(marker)
    if oid!=OID or window.id!=WINDOW or saved!=composition(saved['proposal']['path']):
        raise ValueError('Reviewed B1 composition changed or outside approved scope')
    observations=[o for o in record['machine_observations'] if {r['window_id'] for r in o['source_refs']}=={WINDOW}]
    original=producer.dimension_verification(window,observations)
    if asdict(original)!=diagnostic.checked_json(saved['original_input'])['request']:
        raise ValueError('B1 exact source/candidate/scope differs')
    refs=[marker,saved['proposal'],saved['original_input']]+[c['receipt'] for c in saved['row']['constituents'].values()]
    return deepcopy(saved['row']),{r['path']:r['sha256'] for r in refs}


def assemble(data,path):
    p=data['p'];root=data['root']
    a3root=Path(p['base_dir'])/'evaluation'/a3.VERSION/a3.PRESENCE_REQUEST
    record=support.core.read_record(a3root/'assembled-profile.json')
    frozen=json.loads((a3root/'support-plan.json').read_text())
    if support.core.build_plan(record)!=frozen['plan']:
        raise ValueError('Existing A3 evidence changed')
    composed=composition(path);Store(root).write_immutable('composition.json',composed)
    observation=next(o for o in record['machine_observations'] if o['id']==OID)
    record['reviewed_case_compositions']={OID:diagnostic.reference(root/'composition.json')}
    record['claims'].append(section.dimension_claim(observation,composed['row']))
    record['reader']['claims']=record['claims'];record['reader']['portrait']['entries']=record['claims']
    if 'response_conditions_dimension' in record:
        record['historical_response_conditions_dimension']=record.pop('response_conditions_dimension')
    record['reviewed_case_sample']=dict(version=VERSION,profile_id=318,
        meaning='Two explicitly reviewed local response descriptions; selected exposed evidence, no general admission.',
        cases=[dict(observation_id=a3.OID,window=a3.WINDOW,video_id=4589,composition=record['reviewed_dimension_composition']),
            dict(observation_id=OID,window=WINDOW,video_id=3973,composition=record['reviewed_case_compositions'][OID])],
        selected_opportunities='Original six development and four confirmation windows remain frozen; no exhaustive point enumeration.',
        missingness='Other withheld/absent source points remain unknown; two examples are not a sample response rate.',
        pastor_score=None,occurrence_rate=None,benchmark_comparison='unavailable',
        historical_diagnostic='FAILED_IMMUTABLE',general_reliability='not_validated')
    Store(root).write_immutable('assembled-profile.json',record)
    plan=support.core.build_plan(record)
    if any(i['case'] is None for i in plan['items']):
        raise ValueError('Reviewed assembly failed: '+str([i['gap'] for i in plan['items'] if i['gap']]))
    return record,plan


def save_result(data,path,status,accounting,**extra):
    root=data['root'];calls=sum(a['usage']['paid_attempts'] for a in accounting.values())
    cost=sum((Decimal(a['usage']['known_list_price_usage_usd']) for a in accounting.values()),Decimal(0))
    retained=sum((Decimal(a['usage']['reserved_usd']) for a in accounting.values()),Decimal(0))
    if calls>3 or retained>Decimal('.04'):raise ValueError('B1 approved total ceiling exceeded')
    result=dict(version=VERSION,status=status,proposal=diagnostic.reference(path),
        accounting=accounting,paid_attempts=calls,known_list_price_usage_usd=str(cost),
        retained_reservations_usd=str(retained),cap_usd='0.04',corrections=0,
        original_diagnostic='FAILED_IMMUTABLE',general_reliability='not_validated',
        production_admission='not_admitted',next_action='Review the saved result; no successor or new call is authorized.',**extra)
    Store(root).write_immutable('result.json',result)
    (root/'RESULT.md').write_text('# Reviewed B1 delivery result\n\n'+status+'\n\n'
        +json.dumps(result,indent=2)+'\n')
    return result


def verify_saved(data,result):
    """Offline replay checks receipts/accounting and dependency-safe presentation."""
    root=data['root'];spend=Path(data['p']['base_dir'])/'evaluation/qualified-observations'
    specs={'presence':data['spec']}
    if 'support' in result['accounting']:
        frozen=json.loads((root/'support-plan.json').read_text())
        task=next(t for t in frozen['tasks'] if t['claim_id']=='section-dimension-requested_response-'+OID)
        specs['support']=support.requests.RequestSpec(**task['request'])
    for stage,accounting in result['accounting'].items():
        spec=specs[stage];store=support.requests.ReceiptStore(spend/spec.fingerprint/'execution')
        if support.supervised.check.demo.usage_account(store)!=accounting['usage']:
            raise ValueError('B1 saved accounting changed')
        if (store.root/'receipts'/(spec.fingerprint+'.json')).exists():support._cached(spec,store)
    if (root/'document-input.json').exists():
        record=support.core.read_record(root/'assembled-profile.json')
        frozen=json.loads((root/'support-plan.json').read_text());rows=json.loads((root/'support-results.json').read_text())['results']
        if support.core.build_plan(record)!=frozen['plan']:raise ValueError('B1 assembled support case changed')
        for task in frozen['tasks']:
            item=next(i for i in frozen['plan']['items'] if i['claim_id']==task['claim_id'])
            spec=support.make_request(item['case'],whole_statement=True)
            if asdict(spec)!=task['request']:raise ValueError('B1 support request changed')
            store=support.requests.ReceiptStore(spend/spec.fingerprint/'execution')
            receipt=support._cached(spec,store) if (store.root/'receipts'/(spec.fingerprint+'.json')).exists() else None
            checked=(support._row(item,spec,receipt,store,cached=item['claim_id']!='section-dimension-requested_response-'+OID) if receipt else
                dict(claim_id=item['claim_id'],status='component_failure',judgment=None,receipt=None,failure='No support receipt'))
            if item['claim_id']=='section-dimension-requested_response-'+OID and result['accounting']['support']['unresolved_usage']:
                checked.update(status='component_failure',judgment=None,failure='Unresolved support usage; stop')
            if checked!=next(r for r in rows if r['claim_id']==item['claim_id']):
                raise ValueError('B1 support result differs from its saved receipt')
        document=support.core.document_input(frozen['plan'],rows)
        saved=json.loads((root/'document-input.json').read_text())
        if document['entries']!=saved['entries'] or document['ready_claim_ids']!=saved['ready_claim_ids']:
            raise ValueError('B1 document differs from support results')
    return result


def run(path,approve_packet,approve_case,*,presence_transport=None,support_transport=None,check_only=False):
    if approve_packet!=PROPOSAL or approve_case!=OID:
        raise ValueError('Exact B1 proposal and case approval required')
    data=load(path);root=data['root'];p=data['p'];spec=data['spec']
    if check_only:return dict(status='CHECKED_NO_CALLS',presence_fingerprint=spec.fingerprint,total_cap_usd='0.04')
    with support.requests.ReceiptStore(root).exclusive():
        authorization=dict(proposal=diagnostic.reference(path),approved_packet=PROPOSAL,approved_case=OID,
            executor=diagnostic.reference(__file__),total_cap_usd='0.04',presence_cap_usd='0.01',support_cap_usd='0.03',
            maximum_physical_attempts=3,maximum_presence_attempts=1,maximum_support_attempts=2,corrections=0,
            disclosure='Approved frozen candidate/source/evidence to TypeSafe, and conditionally Qwen via DeepInfra.')
        if (root/'result.json').exists():
            if diagnostic.checked_json(diagnostic.reference(root/'authorization.json'))!=authorization:
                raise ValueError('B1 execution authorization changed')
            return verify_saved(data,json.loads((root/'result.json').read_text()))
        spend=Path(p['base_dir'])/'evaluation/qualified-observations'
        store=support.requests.ReceiptStore(spend/spec.fingerprint/'execution')
        if presence_transport is None and not os.environ.get('TYPESAFE_API_KEY') and not store.attempts():
            raise ValueError('TypeSafe credential absent; no attempt made')
        Store(root).write_immutable('authorization.json',authorization)
        receipt,usage=obtain(spec,store,cap='.01',maximum_attempts=1,
            transport=presence_transport or support.requests.typesafe_transport)
        accounting=dict(presence=usage);Store(root).write_immutable('presence-accounting.json',usage)
        if receipt is None or receipt['halt'] or usage['unresolved_usage']:
            return save_result(data,path,'STOPPED_PRESENCE',accounting,reason='Missing/failed presence receipt or unresolved usage')
        try:_,answer=presence_result(spec,store)
        except (ValueError,KeyError,TypeError) as error:
            return save_result(data,path,'STOPPED_PRESENCE',accounting,reason='Invalid presence answer: '+str(error))
        Store(root).write_immutable('presence-answer.json',answer)
        if not answer['resolved'] or answer['probability']<.90:
            return save_result(data,path,'STOPPED_PRESENCE',accounting,presence=answer,reason='Presence below .90; no support call')
        record,plan=assemble(data,path);rows=[];tasks=[]
        for item in plan['items']:
            candidate=support.make_request(item['case'],whole_statement=True)
            tasks.append(dict(claim_id=item['claim_id'],request=asdict(candidate),fingerprint=candidate.fingerprint,
                token_account=candidate.preflight(),reserved_usd=str(support.requests.request_reservation(candidate))))
        pending=next(t for t in tasks if t['claim_id']=='section-dimension-requested_response-'+OID)
        candidate=support.requests.RequestSpec(**pending['request'])
        if (candidate.body['model']!='Qwen/Qwen3.8-27B'
                or support.requests.request_reservation(candidate)>Decimal('.03')
                or candidate.preflight()['stream_recovery']['maximum_attempts']>2):
            return save_result(data,path,'STOPPED_SUPPORT_PREFLIGHT',accounting,reason='Complete support request exceeds approved cap/attempts')
        Store(root).write_immutable('support-plan.json',dict(plan=plan,tasks=tasks,corrections=0))
        for task in tasks:
            if task is pending:continue
            prior=support.requests.RequestSpec(**task['request'])
            target=support.requests.ReceiptStore(spend/prior.fingerprint/'execution')
            cached=support._cached(prior,target)
            if cached is None or cached['halt']:raise ValueError('A3 support must remain an exact reusable success')
            item=next(i for i in plan['items'] if i['claim_id']==task['claim_id'])
            checked=support._row(item,prior,cached,target,cached=True)
            if support.core.document_input({**plan,'items':[item]},[checked])['ready_claim_ids']!=[item['claim_id']]:
                raise ValueError('Existing A3 support no longer qualifies')
        for task in tasks:
            candidate=support.requests.RequestSpec(**task['request']);target=support.requests.ReceiptStore(spend/candidate.fingerprint/'execution')
            if task is pending:
                if support_transport is None and not support.provider.credential_present() and not target.attempts():
                    return save_result(data,path,'STOPPED_SUPPORT_PREFLIGHT',accounting,reason='DeepInfra credential absent')
                receipt,usage=obtain(candidate,target,cap='.03',maximum_attempts=2,
                    transport=support_transport or support.provider.transport)
                accounting['support']=usage
            else:
                receipt=support._cached(candidate,target)
                if receipt is None or receipt['halt']:raise ValueError('Prior A3 support must reuse its exact successful receipt')
            item=next(i for i in plan['items'] if i['claim_id']==task['claim_id'])
            row=(support._row(item,candidate,receipt,target,cached=task is not pending) if receipt else
                dict(claim_id=item['claim_id'],status='component_failure',judgment=None,receipt=None,failure='No support receipt'))
            if task is pending and accounting['support']['unresolved_usage']:
                row.update(status='component_failure',judgment=None,failure='Unresolved support usage; stop')
            rows.append(row)
        Store(root).write_immutable('support-results.json',dict(results=rows,accounting=accounting))
        document=support.core.document_input(plan,rows)
        presentation={**p,'limitation':'Two deliberately selected, explicitly reviewed local examples in different recordings. The original broader diagnostic remains FAILED; general reliability and original confirmation acceptance are not established.',
            'unknowns':['No audience uptake, frequency, comparative emphasis, causal relation between the examples or complete theology is established.',
                'Other withheld opportunities and full structured-condition bindings remain unknown.']}
        section.write_document(presentation,root,record,document)
        delivered={'section-dimension-requested_response-'+OID,'section-dimension-requested_response-'+a3.OID}<=set(document['ready_claim_ids'])
        return save_result(data,path,'DELIVERED_TWO_REVIEWED_CASES' if delivered else 'STOPPED_SUPPORT',accounting,
            presence=answer,draft=str(root/'draft-section.md'),document_input=str(root/'document-input.json'),
            ready_claim_ids=document['ready_claim_ids'],two_finding_delivery_milestone=delivered,
            original_confirmation_acceptance='Unchanged; not established by this reviewed pilot')
