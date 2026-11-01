"""Bounded section adapter over shared source bindings, profile support and handoff."""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
import json
import re
from . import response_growth_binding as producer
from . import profile_analysis_support_execution as x
from . import profile_support_budget as allowance
from . import segment_cache_inventory, sermon_topics
from . import profile_section_measurements as measurements
from .pastor_evidence import SourceWindow, EvidenceArtifactStore as Store, digest
from .profile_support_validation import file_hash

VERSION = 'profile-section-v1'
WINDOWS = ((281,122,124), (3973,68,70), (3973,74,78), (3973,88,97),
           (4589,43,48), (4589,49,51))
LIMIT = ('Six selected development windows in three exposed recordings; not a representative '
    'sample, exhaustive theology, frequency estimate or independent generalization. '
    'Invitations do not establish audience uptake. Quarantined legacy leaves remain quarantined.')
UNKNOWN = ['Completeness outside the six windows and unrecovered points within them',
    'Frequency, dominance, comparative priority, causal effects and ministry-wide stability',
    'Actual listener response or saving state; a complete doctrine of perseverance or loss',
    'Admitted repentance/obedience measurements and independent holdout generalization']


def identity():
    return {m.__name__:file_hash(m.__file__) for m in (producer, producer.source_context,
        producer.contract, producer.reading_diagnostics, producer.evidence, x, x.core, x.requests,
        x.provider, x.correction, x.streaming, x.supervised, allowance,measurements,
        measurements.profile_description,measurements.force)} | {__name__:file_hash(__file__)}


def inventory(base_dir):
    return segment_cache_inventory.build(base_dir, profile_id=318, video_ids=(281,3973,4589))


def windows(inv):
    sources = {s['video_id']:s for s in inv['sermons']}
    result = []
    for vid, first, last in WINDOWS:
        s = sources[vid]
        if file_hash(s['source_path']) != s['source_sha256']:
            raise ValueError('Frozen source changed')
        raw = json.loads(Path(s['source_path']).read_text())
        analysis = sermon_topics.resolve_topic_analysis_artifact(raw['classification'])
        blocks = {b['block_id']:b for b in analysis['blocks']}
        ids = list(range(first,last+1))
        if not set(ids) <= set(s['eligible_block_ids']):
            raise ValueError('Frozen window includes an ineligible block')
        selected = tuple(dict(block_id=k, target_text=sermon_topics.resolve_topic_block_context(blocks[k])['target_text'],
            **{f:blocks[k][f] for f in ('start_seconds','end_seconds','segment_indexes')}) for k in ids)
        result.append(SourceWindow(f'v{vid}b{first}-{last}',318,vid,s['source_sha256'],first,
            selected,'selected_gap_and_contrast'))
    return result


def prepare(base_dir, objective, previous_allowance):
    base_dir = Path(base_dir).resolve()
    ref, auth = allowance.authorize_readiness(base_dir, objective, previous_allowance)
    inv = inventory(base_dir)
    root = x.build_paths(base_dir).evaluation / VERSION / digest(auth['objective'])
    tasks = []
    for window in windows(inv):
        spec = producer.request(window)
        reserved = 2*x.requests.request_reservation(spec)+x.requests.reservation('source_verification')
        if reserved > Decimal('.50'):
            raise ValueError('Source batch exceeds fifty cents')
        tasks.append(dict(id=window.id, window=asdict(window), request=asdict(spec),
            reserved_usd=str(reserved), maximum_paid_attempts=3))
    # Fixed upper bound for support: at most twelve local points plus one membership
    # interpretation. Each is prepared and partitioned below fifty cents after binding.
    support_reserve = Decimal('1.25')
    maximum = sum((Decimal(t['reserved_usd']) for t in tasks), support_reserve)
    if maximum > Decimal(auth['additional_usd']):
        raise ValueError('Frozen complete sequence exceeds additional allowance')
    packet = dict(version=VERSION, base_dir=str(base_dir), profile=inv['selected_profile'],
        inventory_fingerprint=inv['content_fingerprint'], source_identity=[{k:s[k] for k in
            ('video_id','title','url','source_path','source_sha256','gate')} for s in inv['sermons']],
        coverage=inv['coverage'], tasks=tasks, acceptance_authorization=ref,
        budget=dict(spend_root=auth['spend_root'], cumulative_ceiling_usd=auth['cumulative_ceiling_usd'],
            starting_conservative_usd=auth['starting_conservative_usd'], additional_usd='3',
            maximum_batch_usd='.50', maximum_sequence_reservation_usd=str(maximum),
            support_reservation_usd=str(support_reserve)),
        policy=dict(semantic_iterations=2, mechanical_corrections=1, semantic_retries=0,
            maximum_source_windows=6, automatic_expansion=False, production_admission='not_admitted'),
        limitation=LIMIT, unknowns=UNKNOWN, code_identity=identity())
    packet['input_fingerprint'] = digest(packet)
    # Keep earlier freezes intact when a focused implementation fix changes code.
    root = root/'freezes'/packet['input_fingerprint']
    Store(root).write_immutable('plan.json', packet)
    (root/'plan.md').write_text('# Bounded automatic section\n\n'+LIMIT+'\n\n'+
        json.dumps(dict(budget=packet['budget'], source_batches=[{k:t[k] for k in
            ('id','reserved_usd','maximum_paid_attempts')} for t in tasks]),indent=2)+'\n')
    return dict(plan=str(root/'plan.json'), input_fingerprint=packet['input_fingerprint'],
        budget=packet['budget'], source_batches=[t['id'] for t in tasks], paid_calls=0)


def load(path):
    path = Path(path); p = json.loads(path.read_text())
    if p['input_fingerprint'] != digest({k:v for k,v in p.items() if k!='input_fingerprint'}):
        raise ValueError('Section freeze differs')
    if p['code_identity'] != identity():
        raise ValueError('Section implementation changed after freeze')
    if p.get('transport_recovery'):
        lineage=p['transport_recovery'];ref=lineage['original_plan']
        if file_hash(ref['path'])!=ref['sha256']:
            raise ValueError('Original recovery plan changed')
        for lost in lineage['preserved_lost_attempts']:
            ref=lost['attempt']
            if file_hash(ref['path'])!=ref['sha256']:
                raise ValueError('Original lost attempt changed')
            if (Path(ref['path']).parent.parent/'receipts'/Path(ref['path']).name).exists():
                raise ValueError('Original response recovered; resolve compatible reuse before execution')
    if p.get('streaming_recovery'):
        for ref in p['streaming_recovery']['preserved_files']:
            if file_hash(ref['path'])!=ref['sha256']:
                raise ValueError('Streaming predecessor changed')
    if p.get('local_enum_transport'):
        for ref in p['local_enum_transport']['preserved_files']:
            if file_hash(ref['path'])!=ref['sha256']:
                raise ValueError('Local-enum predecessor changed')
    if p.get('source_correction_headroom'):
        ref=p['source_correction_headroom']['predecessor']
        if file_hash(ref['path'])!=ref['sha256']:raise ValueError('Headroom predecessor changed')
    if p.get('continuation'):
        ref=p['continuation']['predecessor']
        if file_hash(ref['path'])!=ref['sha256']:raise ValueError('Continuation predecessor changed')
    allowance.ceiling(p)
    inv = inventory(Path(p['base_dir']))
    if (inv['content_fingerprint'] != p['inventory_fingerprint'] or
        digest([asdict(w) for w in windows(inv)]) != digest([t['window'] for t in p['tasks']])):
        raise ValueError('Membership, inventory or complete source windows changed')
    return p, path.parent


def prepare_recovery(path):
    """User-authorized transport recovery; no new allowance or semantic variant."""
    path=Path(path);prior=json.loads(path.read_text())
    if prior['input_fingerprint']!=digest({k:v for k,v in prior.items() if k!='input_fingerprint'}):
        raise ValueError('Original freeze differs')
    if prior.get('transport_recovery'):
        raise ValueError('Only one recovery of this interrupted freeze is permitted')
    limit=allowance.ceiling(prior)
    inv=inventory(Path(prior['base_dir']))
    if inv['content_fingerprint']!=prior['inventory_fingerprint'] or digest([asdict(w) for w in windows(inv)])!=digest([t['window'] for t in prior['tasks']]):
        raise ValueError('Original source/membership differs')
    packet=deepcopy(prior);packet.pop('input_fingerprint');lost=[]
    for task in packet['tasks']:
        original=x.requests.RequestSpec(**task['request']);store=x._store(prior,original)
        if store.attempts() and not (store.root/'receipts'/f'{original.fingerprint}.json').exists():
            if len(store.attempts())!=1:
                raise ValueError('Recovery requires exactly one preserved interrupted attempt')
            attempt=store.root/'attempts'/f'{original.fingerprint}.json'
            revised=replace(original,source_identity={**original.source_identity,
                'transport_recovery_of':original.fingerprint,
                'original_attempt_sha256':file_hash(attempt)})
            revised.preflight()
            task['request']=asdict(revised)
            lost.append(dict(batch=task['id'],request_fingerprint=original.fingerprint,
                attempt=dict(path=str(attempt),sha256=file_hash(attempt)),
                retained_reservation_usd=str(x.requests.request_reservation(original))))
    if len(lost)!=1:
        raise ValueError('Recovery requires one demonstrated lost source request')
    packet['transport_recovery']=dict(original_plan=dict(path=str(path.resolve()),sha256=file_hash(path)),
        preserved_lost_attempts=lost,maximum_recoveries=1,semantic_changes=False,
        authorization='Brian approved this and future runs for this goal within the existing budget; original unknown usage remains fully reserved.')
    packet['code_identity']=identity()
    # The original starting ledger and $3 allowance remain unchanged.
    current=ledger(prior,path.parent)
    if current+Decimal(packet['budget']['maximum_sequence_reservation_usd'])>=limit:
        raise ValueError('Full recovery sequence exceeds remaining authorized allowance')
    packet['input_fingerprint']=digest(packet)
    out=path.parent/'recovery'/packet['input_fingerprint']
    Store(out).write_immutable('plan.json',packet)
    return dict(plan=str(out/'plan.json'),input_fingerprint=packet['input_fingerprint'],
        retained_lost_attempts=lost,current_conservative_usd=str(current),
        remaining_credit_usd=str(limit-current),maximum_sequence_reservation_usd=packet['budget']['maximum_sequence_reservation_usd'],paid_calls=0)


def prepare_streaming_recovery(path):
    """Use existing cancellation/recovery for the demonstrated source whitespace loop."""
    path=Path(path);prior=json.loads(path.read_text())
    if prior['input_fingerprint']!=digest({k:v for k,v in prior.items() if k!='input_fingerprint'}) or prior.get('streaming_recovery'):
        raise ValueError('Requires unchanged predecessor without a prior streaming recovery')
    limit=allowance.ceiling(prior);inv=inventory(Path(prior['base_dir']))
    if inv['content_fingerprint']!=prior['inventory_fingerprint'] or digest([asdict(w) for w in windows(inv)])!=digest([t['window'] for t in prior['tasks']]):
        raise ValueError('Frozen source/membership changed')
    packet=deepcopy(prior);packet.pop('input_fingerprint');refs=[dict(path=str(path.resolve()),sha256=file_hash(path))];demonstrated=[]
    for task in packet['tasks']:
        old=x.requests.RequestSpec(**task['request']);store=x._store(prior,old)
        receipt=x._cached(old,store)
        if receipt is not None:
            wire=store.root/'wire-responses'/f'{old.fingerprint}.json'
            raw=json.loads(json.loads(wire.read_text())['text']);choice=raw['choices'][0];content=choice['message'].get('content','')
            if choice['finish_reason']!='length' or len(content)-len(content.rstrip())<256:
                raise ValueError('Only the demonstrated length/whitespace failure permits this transport change')
            demonstrated.append(old.fingerprint)
            refs.extend(dict(path=str(f),sha256=file_hash(f)) for f in (wire,store.root/'receipts'/f'{old.fingerprint}.json'))
        spec=x.provider.streaming_request(old)
        task.update(request=asdict(spec),reserved_usd=str(2*x.requests.request_reservation(spec)+x.requests.reservation('source_verification')),maximum_paid_attempts=5)
        if Decimal(task['reserved_usd'])>Decimal('.50'):
            raise ValueError('Streaming source batch exceeds fifty cents')
    if len(demonstrated)!=1:
        raise ValueError('Exactly one accounted whitespace failure is required')
    maximum=sum((Decimal(t['reserved_usd']) for t in packet['tasks']),Decimal(packet['budget']['support_reservation_usd']))
    current=ledger(prior,path.parent)
    if current+maximum>=limit:
        raise ValueError('Full streaming sequence exceeds existing allowance')
    packet['budget']['maximum_sequence_reservation_usd']=str(maximum)
    packet['streaming_recovery']=dict(preserved_files=refs,demonstrated_requests=demonstrated,
        semantics_unchanged=True,maximum_whitespace_retries=1,model_switch=False)
    packet['code_identity']=identity();packet['input_fingerprint']=digest(packet)
    out=path.parent/'streaming'/packet['input_fingerprint'];Store(out).write_immutable('plan.json',packet)
    return dict(plan=str(out/'plan.json'),input_fingerprint=packet['input_fingerprint'],current_conservative_usd=str(current),
        maximum_sequence_reservation_usd=str(maximum),remaining_credit_usd=str(limit-current),source_batch_reservation_usd=packet['tasks'][0]['reserved_usd'],paid_calls=0)


def prepare_local_enum_transport(path):
    """Second and final implementation iteration; unchanged local semantic contract."""
    path=Path(path);prior=json.loads(path.read_text())
    if prior['input_fingerprint']!=digest({k:v for k,v in prior.items() if k!='input_fingerprint'}) or prior.get('local_enum_transport'):
        raise ValueError('Requires unchanged predecessor without another local-enum iteration')
    if not prior.get('streaming_recovery'):raise ValueError('Requires the demonstrated bounded streaming failure')
    limit=allowance.ceiling(prior);inv=inventory(Path(prior['base_dir']))
    if inv['content_fingerprint']!=prior['inventory_fingerprint'] or digest([asdict(w) for w in windows(inv)])!=digest([t['window'] for t in prior['tasks']]):
        raise ValueError('Source/membership changed')
    packet=deepcopy(prior);packet.pop('input_fingerprint');refs=[dict(path=str(path.resolve()),sha256=file_hash(path))];failures=[]
    for task in packet['tasks']:
        old=x.requests.RequestSpec(**task['request']);store=x._store(prior,old);receipt=x._cached(old,store)
        if receipt:
            if 'whitespace loop' not in (receipt['halt'] or ''):raise ValueError('Requires a demonstrated whitespace failure')
            f=store.root/'receipts'/f'{old.fingerprint}.json';refs.append(dict(path=str(f),sha256=file_hash(f)));failures.append(old.fingerprint)
        spec=producer.local_enum_transport(old)
        task['request']=asdict(spec)
        task['reserved_usd']=str(2*x.requests.request_reservation(spec)+x.requests.reservation('source_verification'))
    if len(failures)!=1:raise ValueError('Exactly one exhausted source request required')
    maximum=sum((Decimal(t['reserved_usd']) for t in packet['tasks']),Decimal(packet['budget']['support_reservation_usd']))
    current=ledger(prior,path.parent)
    if current+maximum>=limit:raise ValueError('Complete final iteration exceeds remaining allowance')
    packet['local_enum_transport']=dict(version=producer.LOCAL_ENUM_TRANSPORT,implementation_iteration=2,
        preserved_files=refs,local_schema_unchanged=True,model_unchanged=True,no_further_variants=True)
    packet['budget']['maximum_sequence_reservation_usd']=str(maximum)
    packet['code_identity']=identity();packet['input_fingerprint']=digest(packet)
    out=path.parent/'local-enums'/packet['input_fingerprint'];Store(out).write_immutable('plan.json',packet)
    return dict(plan=str(out/'plan.json'),input_fingerprint=packet['input_fingerprint'],iteration=2,
        current_conservative_usd=str(current),remaining_credit_usd=str(limit-current),maximum_sequence_reservation_usd=str(maximum),paid_calls=0)


def source_correction(spec,output,errors,*,headroom=False,feedback_headroom=False):
    revised=x.requests.corrective_request(spec,output,errors,producer.reading_diagnostics.CORRECTION,validate=not headroom)
    if spec.version.removesuffix('-stream-v1')in (x.requests.DEEPINFRA_BINDING_REASONING_VERSION,x.requests.DEEPINFRA_BINDING_REASONING_TEXT_VERSION):
        revised.preflight();return revised
    if headroom:
        tiers=[(None,None),(x.requests.DEEPINFRA_BINDING_HEADROOM_VERSION,x.provider.BINDING_HEADROOM_POLICY)]
        if feedback_headroom:tiers.append((x.requests.DEEPINFRA_BINDING_FEEDBACK_VERSION,x.provider.BINDING_FEEDBACK_POLICY))
        for version,policy in tiers:
            try:
                candidate=(revised if version is None else x.provider.streaming_request(
                    replace(revised,version=version,namespace=version,runtime_identity=policy)))
                candidate.preflight()
                return candidate
            except ValueError as error:
                if 'input exceeds reservation' not in str(error):raise
                failure=error
        raise failure

    return revised


def prepare_source_headroom(path):
    """Predeclare complete mechanical feedback capacity; never alter a source answer."""
    path=Path(path);prior=json.loads(path.read_text())
    if prior['input_fingerprint']!=digest({k:v for k,v in prior.items() if k!='input_fingerprint'}) or prior.get('source_correction_headroom'):
        raise ValueError('Requires unchanged predecessor without prior headroom expansion')
    if not prior.get('local_enum_transport'):raise ValueError('Headroom applies only to the final source iteration')
    limit=allowance.ceiling(prior);packet=deepcopy(prior);packet.pop('input_fingerprint');demonstrated=[]
    version=x.requests.DEEPINFRA_BINDING_HEADROOM_VERSION+'-stream-v1'
    correction_reserve=x.provider.reserved_usd(version)
    for task in packet['tasks']:
        spec=x.requests.RequestSpec(**task['request']);store=x._store(prior,spec);receipt=x._cached(spec,store)
        if receipt and not receipt['halt']:
            rpath=store.root/'receipts'/f'{spec.fingerprint}.json'
            checked=producer.inspect(receipt['response']['output'],SourceWindow(**task['window']),spec,rpath)
            if checked['errors']:
                fixed=source_correction(spec,receipt['response']['output'],checked['errors'],headroom=True)
                if fixed.runtime_identity['input_cap']>spec.runtime_identity['input_cap']:
                    demonstrated.append(dict(receipt=str(rpath),sha256=file_hash(rpath),complete_feedback_bound=fixed.preflight()['request_upper_bound']))
        task['reserved_usd']=str(x.requests.request_reservation(spec)+correction_reserve+x.requests.reservation('source_verification'))
        if Decimal(task['reserved_usd'])>Decimal('.50'):raise ValueError('Source headroom batch exceeds fifty cents')
    if len(demonstrated)!=1:raise ValueError('Exactly one demonstrated feedback overflow required')
    maximum=sum((Decimal(t['reserved_usd']) for t in packet['tasks']),Decimal(packet['budget']['support_reservation_usd']))
    current=ledger(prior,path.parent)
    if current+maximum>=limit:raise ValueError('Full headroom reservation exceeds remaining allowance')
    packet['source_correction_headroom']=dict(predecessor=dict(path=str(path.resolve()),sha256=file_hash(path)),demonstrated=demonstrated,
        maximum_corrections=1,maximum_input_cap=65536,maximum_correction_reservation_usd=str(correction_reserve))
    packet['budget']['maximum_sequence_reservation_usd']=str(maximum)
    packet['code_identity']=identity();packet['input_fingerprint']=digest(packet)
    out=path.parent/'headroom'/packet['input_fingerprint'];Store(out).write_immutable('plan.json',packet)
    # Exact completed source results are reused with their original receipt paths.
    for task in packet['tasks']:
        result=path.parent/'sources'/task['id']/'result.json'
        if result.exists():Store(out/'sources'/task['id']).write_immutable('result.json',json.loads(result.read_text()))
    return dict(plan=str(out/'plan.json'),input_fingerprint=packet['input_fingerprint'],demonstrated=demonstrated,
        maximum_sequence_reservation_usd=str(maximum),remaining_credit_usd=str(limit-current),paid_calls=0)


def ledger(p, root):
    with x.supervised.cumulative_history(p, root/'ledger') as history:
        return x.supervised.BASELINE_SPEND + sum((c for _,c in history), Decimal(0))


def reconcile_completed_wire(packet,spec):
    """Append a decoder correction for a complete wire; never resend or edit history."""
    store=x._store(packet,spec);cached=x._cached(spec,store)
    if not cached or cached['halt']!='DeepInfra emitted reasoning despite frozen disabled policy; no retry':return None
    if spec.runtime_identity.get('reasoning_effort') not in ('high',):return None
    original=store.root/'receipts'/f'{spec.fingerprint}.json'
    wire=store.root/'wire-responses'/f'{spec.fingerprint}.json'
    response=x.requests.decode_response(spec,x.requests.WireResponse(**json.loads(wire.read_text())))
    x.requests.validate_response(spec,response)
    revised={**cached,'response':response,'response_digest':digest(response),'halt':None,
        'reconciliation':dict(original_receipt=dict(path=str(original),sha256=file_hash(original)),
            complete_wire=dict(path=str(wire),sha256=file_hash(wire)),provider_calls=0,
            basis='Declared reasoning-enabled request completed; decoder incorrectly applied disabled-reasoning guard. Original reservation and receipt retained.')}
    dest=store.root/'reconciliations'/f'{spec.fingerprint}.json'
    Store(dest.parent).write_immutable(dest.name,revised)
    return dict(path=str(dest),sha256=file_hash(dest))


def prepare_continuation(path, source_windows=(), *,source_reasoning=False,logical_condition_scopes=False,reuse_materialized=False,literal_materialized=False,field_local_criteria=False,dimension_checks=False):
    """Freeze another authorized bounded step without replacing the allowance."""
    path=Path(path);prior=json.loads(path.read_text())
    if prior['input_fingerprint']!=digest({k:v for k,v in prior.items() if k!='input_fingerprint'}):
        raise ValueError('Continuation predecessor differs')
    inv=inventory(Path(prior['base_dir']))
    if inv['content_fingerprint']!=prior['inventory_fingerprint']:
        raise ValueError('Continuation inventory changed')
    selected=set(source_windows)
    if source_reasoning and not selected:raise ValueError('Source reasoning requires selected fixed windows')
    if logical_condition_scopes and not selected:raise ValueError('Condition attachment contract requires selected fixed windows')
    if not selected<=set(t['id'] for t in prior['tasks']):raise ValueError('Unknown fixed source window')
    packet=deepcopy(prior);packet.pop('input_fingerprint')
    packet.setdefault('completed_wire_reuse',{})
    correction_reserve=x.provider.reserved_usd(x.requests.DEEPINFRA_BINDING_FEEDBACK_VERSION+'-stream-v1')
    for task in packet['tasks']:
        if task['id'] in selected:
            spec=producer.local_enum_transport(x.provider.streaming_request(producer.request(SourceWindow(**task['window']),unit_ranges=True,
                condition_attachments=logical_condition_scopes)))
            if source_reasoning:spec=producer.reasoning_request(spec)
            task['request']=asdict(spec)
        else:spec=x.requests.RequestSpec(**task['request'])
        reconciled=reconcile_completed_wire(prior,spec)
        if reconciled:packet['completed_wire_reuse'][spec.fingerprint]=reconciled
        task['reserved_usd']=str(x.requests.request_reservation(spec)+correction_reserve+24*x.requests.reservation('source_verification'))
        task['maximum_paid_attempts']=28
        if Decimal(task['reserved_usd'])>Decimal('.50'):raise ValueError('Continuation batch exceeds fifty cents')
    current=ledger(prior,path.parent);limit=allowance.ceiling(prior)
    packet['policy'].update(semantic_iterations='until_original_allowance_or_goal',automatic_expansion=False)
    packet['field_isolated_verification']=producer.FIELD_VERIFICATION_VERSION
    if field_local_criteria:packet['field_criteria_contract']=producer.FIELD_LOCAL_CRITERIA
    packet['source_feedback_headroom']=dict(maximum_input_cap=131072,maximum_corrections=1,
        maximum_correction_reservation_usd=str(correction_reserve))
    packet['continuation']=dict(predecessor=dict(path=str(path.resolve()),sha256=file_hash(path)),
        authorization='User removed iteration ceiling and approved this and future runs within the original goal budget.',
        refreshed_source_windows=sorted(selected),source_reasoning_effort='high' if source_reasoning else None,
        condition_attachment_contract=producer.CONDITION_ATTACHMENT_VERSION if logical_condition_scopes else None,
        verification_version=packet.get('field_criteria_contract',producer.VERIFICATION_VERSION),
        current_conservative_usd=str(current),remaining_credit_usd=str(limit-current))
    packet['budget']['maximum_sequence_reservation_usd']=str(sum((Decimal(t['reserved_usd']) for t in packet['tasks']),Decimal(packet['budget']['support_reservation_usd'])))
    if reuse_materialized or literal_materialized or prior.get('materialized_inputs'):
        sources={s['video_id']:json.loads(Path(s['source_path']).read_text()) for s in packet['source_identity']}
        data=measurements.build(inv,sources,[t['window'] for t in packet['tasks']])
        dest=Path(packet['base_dir'])/'evaluation'/VERSION/'materialized'/data['fingerprint']/'inputs.json'
        Store(dest.parent).write_immutable(dest.name,data)
        packet['materialized_inputs']=dict(path=str(dest),sha256=file_hash(dest),version=measurements.VERSION)
    if literal_materialized:packet['materialized_composition']=measurements.LITERAL_VERSION
    if dimension_checks:packet['dimension_contract']=producer.DIMENSION_VERIFICATION_VERSION
    if current>=limit:raise ValueError('Original goal allowance exhausted')
    packet['code_identity']=identity();packet['input_fingerprint']=digest(packet)
    out=Path(packet['base_dir'])/'evaluation'/VERSION/'continuations'/packet['input_fingerprint']
    Store(out).write_immutable('plan.json',packet)
    return dict(plan=str(out/'plan.json'),input_fingerprint=packet['input_fingerprint'],
        current_conservative_usd=str(current),remaining_credit_usd=str(limit-current),paid_calls=0,
        policy='Each complete batch must fit the remaining original allowance before execution.')


def materialized_inputs(p):
    ref=p['materialized_inputs']
    if file_hash(ref['path'])!=ref['sha256']:raise ValueError('Materialized section inputs changed')
    data=json.loads(Path(ref['path']).read_text())
    if data['version']!=measurements.VERSION or data['fingerprint']!=digest({k:v for k,v in data.items() if k!='fingerprint'}):
        raise ValueError('Materialized analysis contract differs')
    return data


def prepare_dimensions(path):
    p,root=load(path)
    if p.get('dimension_contract')!=producer.DIMENSION_VERIFICATION_VERSION:raise ValueError('Dimension contract must be frozen explicitly')
    inputs=[]
    for task in p['tasks']:
        parent=root/'sources'/task['id']/'result.json';result=verified_source_result(p,root,task)
        spec=producer.dimension_verification(SourceWindow(**task['window']),result['observations'])
        reserve=x.requests.request_reservation(spec) if spec else Decimal(0)
        if reserve>Decimal('.50'):raise ValueError('Dimension batch exceeds fifty cents')
        packet=dict(version=producer.DIMENSION_VERIFICATION_VERSION,source_result=dict(path=str(parent),sha256=file_hash(parent)),
            request=asdict(spec) if spec else None,reserved_usd=str(reserve),maximum_paid_attempts=1,
            authority='Individual proposed dimension values only; no full-binding or legacy admission.')
        packet['fingerprint']=digest(packet);dest=root/'dimensions'/task['id']/'input.json'
        Store(dest.parent).write_immutable(dest.name,packet);inputs.append(str(dest))
    return dict(inputs=inputs,provider_calls=0,maximum_paid_attempts=sum(bool(json.loads(Path(f).read_text())['request']) for f in inputs))


def verified_source_result(p,root,task):
    """Rebuild original machine proposals and judgments before new dimension checks."""
    result=json.loads((root/'sources'/task['id']/'result.json').read_text());window=SourceWindow(**task['window'])
    spec=x.requests.RequestSpec(**task['request']);checked=None
    if not 1<=len(result['rounds'])<=2:raise ValueError('Source round inventory differs')
    for n,round_ in enumerate(result['rounds']):
        ref=Path(round_['receipt']);receipt=json.loads(ref.read_text())
        cached=x._cached(spec,x._store(p,spec))
        if cached and cached['halt'] and spec.fingerprint in p.get('completed_wire_reuse',{}):
            saved=p['completed_wire_reuse'][spec.fingerprint]
            if Path(saved['path'])!=ref or file_hash(ref)!=saved['sha256']:raise ValueError('Source reconciliation differs')
            cached=json.loads(ref.read_text())
            for parent in cached['reconciliation'].values():
                if isinstance(parent,dict) and 'path' in parent and file_hash(parent['path'])!=parent['sha256']:
                    raise ValueError('Source reconciliation parent changed')
            wire=json.loads(Path(cached['reconciliation']['complete_wire']['path']).read_text())
            if x.requests.decode_response(spec,x.requests.WireResponse(**wire))!=cached['response']:raise ValueError('Source reconciliation output differs')
        if cached!=receipt:raise ValueError('Dimension source must retain its original cached machine receipt')
        if receipt['request']!=asdict(spec) or receipt['halt'] or receipt['response_digest']!=digest(receipt['response']):
            raise ValueError('Original machine source receipt differs')
        x.requests.validate_response(spec,receipt['response'])
        checked=producer.inspect(receipt['response']['output'],window,spec,ref)
        if checked['errors']!=round_['errors']:raise ValueError('Original source findings differ')
        if n==0 and checked['errors']:
            spec=source_correction(spec,receipt['response']['output'],checked['errors'],
                headroom=bool(p.get('source_correction_headroom')),feedback_headroom=bool(p.get('source_feedback_headroom')))
    rows=[]
    if not checked['errors'] and checked['observations']:
        ref=Path(result['verification_receipt']);saved=json.loads(ref.read_text())
        if saved.get('version')==producer.FIELD_VERIFICATION_VERSION:rows,_=load_field_bundle(ref,window,checked)
        else:
            verifier=producer.verification(window,checked['observations'])
            receipt=x._cached(verifier,x.requests.ReceiptStore(ref.parent.parent))
            if receipt is None or receipt['halt']:raise ValueError('Original source verification incomplete')
            rows=producer.qualify(checked,receipt['response'],verifier)
    if rows!=result['observations']:raise ValueError('Original machine source proposals or judgments changed')
    return result


def dimension_input(p,root,batch):
    task=next(t for t in p['tasks'] if t['id']==batch);out=root/'dimensions'/batch
    packet=json.loads((out/'input.json').read_text());parent=packet['source_result']
    if packet['fingerprint']!=digest({k:v for k,v in packet.items() if k!='fingerprint'}) or file_hash(parent['path'])!=parent['sha256']:
        raise ValueError('Dimension input or source changed')
    if Path(parent['path'])!=root/'sources'/batch/'result.json':raise ValueError('Foreign dimension source parent')
    source=verified_source_result(p,root,task)
    spec=producer.dimension_verification(SourceWindow(**task['window']),source['observations'])
    if (asdict(spec) if spec else None)!=packet['request']:raise ValueError('Dimension request differs from source proposals')
    return packet,source,spec,out


def run_dimensions(path,batch,approve_input,*,transport=None):
    p,root=load(path)
    if approve_input!=p['input_fingerprint']:raise ValueError('Exact frozen input approval required')
    packet,source,spec,out=dimension_input(p,root,batch)
    if (out/'result.json').exists():return read_dimension_result(p,root,batch)
    if ledger(p,root)+Decimal(packet['reserved_usd'])>=allowance.ceiling(p):raise ValueError('Complete dimension batch exceeds allowance')
    findings=[];ref=None
    if spec:
        receipt,path=obtain(p,spec,transport or x.requests.typesafe_transport)
        findings=producer.dimension_findings(source['observations'],receipt['response'],spec)
        ref=dict(path=str(path),sha256=file_hash(path))
    result=dict(version=producer.DIMENSION_VERIFICATION_VERSION,input_fingerprint=packet['fingerprint'],receipt=ref,
        findings=findings,eligible=sum(row['eligible'] for row in findings),production_admission='not_admitted')
    Store(out).write_immutable('result.json',result)
    return read_dimension_result(p,root,batch)


def read_dimension_result(p,root,batch):
    packet,source,spec,out=dimension_input(p,root,batch);result=json.loads((out/'result.json').read_text())
    if result['input_fingerprint']!=packet['fingerprint']:raise ValueError('Dimension result lineage differs')
    findings=[]
    if spec:
        ref=result['receipt']
        if file_hash(ref['path'])!=ref['sha256']:raise ValueError('Dimension receipt changed')
        receipt=x._cached(spec,x._store(p,spec))
        if receipt is None or receipt['halt']:raise ValueError('Dimension receipt incomplete')
        findings=producer.dimension_findings(source['observations'],receipt['response'],spec)
    if findings!=result['findings'] or sum(row['eligible'] for row in findings)!=result['eligible']:
        raise ValueError('Dimension findings changed')
    return result


def dimension_proof(record,window,oid,field):
    """A dimension receipt grants no authority to the other proposed binding fields."""
    refs=record['dimension_packets'][window.id];files={}
    for ref in refs.values():
        if file_hash(ref['path'])!=ref['sha256']:raise ValueError('Dimension proof changed')
        files[ref['path']]=ref['sha256']
    packet=json.loads(Path(refs['input']['path']).read_text());result=json.loads(Path(refs['result']['path']).read_text())
    if packet['fingerprint']!=digest({k:v for k,v in packet.items() if k!='fingerprint'}) or result['input_fingerprint']!=packet['fingerprint']:
        raise ValueError('Dimension proof lineage differs')
    parent=packet['source_result']
    if file_hash(parent['path'])!=parent['sha256']:raise ValueError('Dimension source parent changed')
    files[parent['path']]=parent['sha256']
    observations=[o for o in record['machine_observations'] if {r['window_id'] for r in o['source_refs']}=={window.id}]
    spec=producer.dimension_verification(window,observations)
    if packet['request']!=asdict(spec):raise ValueError('Dimension proof request differs')
    ref=result['receipt']
    if file_hash(ref['path'])!=ref['sha256']:raise ValueError('Dimension receipt changed')
    receipt=x._cached(spec,x.requests.ReceiptStore(Path(ref['path']).parent.parent))
    if receipt is None or receipt['halt']:raise ValueError('Dimension receipt incomplete')
    findings=producer.dimension_findings(observations,receipt['response'],spec)
    if findings!=result['findings']:raise ValueError('Dimension proof values changed')
    row=next(r for r in findings if r['observation_id']==oid and r['field']==field)
    if not row['eligible']:raise ValueError('Dimension is unresolved or below threshold')
    files[ref['path']]=ref['sha256'];return row,files


def attach_dimensions(p,root,record):
    """Expose exact individually qualified values; retain complete-binding holds."""
    record['dimension_packets']={};findings=[]
    for task in p['tasks']:
        result=read_dimension_result(p,root,task['id']);out=root/'dimensions'/task['id']
        record['dimension_packets'][task['id']]={k:dict(path=str(out/name),sha256=file_hash(out/name))
            for k,name in [('input','input.json'),('result','result.json')]}
        findings.extend(result['findings'])
    record['dimension_findings']=findings;by_id={o['id']:o for o in record['machine_observations']};seen=set();added=[]
    for row in findings:
        if not row['eligible']:continue
        o=by_id[row['observation_id']];vid=o['source_refs'][0]['video_id'];key=(vid,row['field'])
        if key in seen:continue  # One source-ordered example per recording and dimension; all results remain available.
        seen.add(key)
        wording=('At this selected point, spiritual growth is discussed as a process over time.' if row['value']=='gradual_growth' else
            'At this selected point, spiritual growth is discussed as immediate perfection.') if row['field']=='growth' else (
            'The response requested or described at this selected point is: '+row['value'])
        c=dict(id='section-dimension-'+row['field']+'-'+o['id'],wording=wording,
            machine_observation_ids=[o['id']],dimension_field=row['field'],evidence_ids=[],upstream_claim_ids=[],
            scope=dict(video_ids=[vid],meaning='Only this individually qualified discussion dimension in the selected source point.'),
            assertion_force='local_observation',analytical_basis=row,
            assertion_contract=dict(version=measurements.force.VERSION,declared_force='local_observation',allowed_forces=['local_observation']),
            limits=[row['authority'],'No actual listener response, unconditional progress, complete conditions or adopted theology is established.'])
        check_strength(c);record['claims'].append(c);added.append(c)
    if any(c['dimension_field']=='growth' for c in added):
        record['analysis_unknowns']=[u if u!='Gradual versus immediate change' else 'Growth timing outside the individually qualified source points' for u in record.get('analysis_unknowns',[])]
    record.setdefault('analysis_unknowns',[]).append('How reassurance and challenge relate to the individually qualified response/growth findings')
    # This is a declared membership interpretation, conditional on both parent
    # claims passing ordinary support. It is not an explanatory theological edge.
    receiving=next((c for c in record['claims'] if c['id']=='section-measured-reception'),None)
    growth=next((c for c in added if c['dimension_field']=='growth' and c['analytical_basis']['value']=='gradual_growth'),None)
    if receiving and growth:
        wording=('The selected sample includes discussion of faith, belief or trust as a receiving response alongside spiritual growth over time. '
            'Their co-presence does not establish a causal sequence, their relative emphasis, or a complete account of how receiving and growth relate.')
        h=dict(id='section-receiving-growth-membership',conclusion=wording,premise_ids=[receiving['id'],growth['id']],
            inference_type='selected_relationship_membership',scope_video_ids=sorted(set(receiving['scope']['video_ids']+growth['scope']['video_ids'])),
            warrant='The receiving-response finding is backed by admitted local measurements; the timing finding has its own eligible source-dimension receipt. Conditional on both parent claims passing support, their presence warrants only selected-sample membership, not a doctrinal or causal relation.',
            alternatives=['The deliberately selected passages may concern different situations; selection may exaggerate apparent thematic proximity.'],
            counterevidence_ids=[],defeaters=['An unsupported parent defeats this interpretation. No qualified adopted counterposition is available; absence of one does not establish consistency.'])
        record['hypotheses'].append(h)
        record['claims'].append(dict(id=h['id'],wording=wording,evidence_ids=receiving['evidence_ids'],
            observation_input_ids=receiving.get('observation_input_ids',[]),machine_observation_ids=growth['machine_observation_ids'],dimension_field='growth',
            upstream_claim_ids=h['premise_ids'],scope=dict(video_ids=h['scope_video_ids'],meaning=LIMIT),assertion_force='sample_membership',
            assertion_contract=dict(version=measurements.force.VERSION,declared_force='sample_membership',allowed_forces=['local_observation','sample_membership']),
            analytical_basis=h,limits=h['defeaters'],alternative=h['alternatives']))
    record['reader']['claims']=record['claims'];record['reader']['portrait']['entries']=record['claims']


def prepare_analysis(path):
    p,root=load(path);data=materialized_inputs(p)
    literal=p.get('materialized_composition')==measurements.LITERAL_VERSION
    spec=measurements.request(data) if not literal and any(o['state']=='observed' for o in data['observations']) else None
    correction=x.correction.policy(spec,headroom=True) if spec else None
    reserve=x.requests.request_reservation(spec)+Decimal(correction['reserved_usd']) if spec else Decimal(0)
    if reserve>Decimal('.50') or ledger(p,root)+reserve>=allowance.ceiling(p):raise ValueError('Complete analysis draft batch exceeds allowance')
    packet=dict(version=measurements.VERSION,request=asdict(spec) if spec else None,correction=correction,
        inputs=p['materialized_inputs'],reserved_usd=str(reserve),maximum_corrections=1,
        composition=p.get('materialized_composition'))
    packet['fingerprint']=digest(packet);out=root/'analysis'
    Store(out).write_immutable('input.json',packet)
    return dict(input=str(out/'input.json'),reserved_usd=str(reserve),materialized_observations=len(data['observations']),
        positive_observations=sum(o['state']=='observed' for o in data['observations']),provider_calls=0)


def run_analysis(path,approve_input,*,transport=None):
    p,root=load(path)
    if approve_input!=p['input_fingerprint']:raise ValueError('Exact frozen input approval required')
    out=root/'analysis';packet=json.loads((out/'input.json').read_text());data=materialized_inputs(p)
    if packet['fingerprint']!=digest({k:v for k,v in packet.items() if k!='fingerprint'}):raise ValueError('Analysis input changed')
    if packet['inputs']!=p['materialized_inputs']:raise ValueError('Analysis measurements differ')
    if (out/'results.json').exists():return read_analysis(p,root)
    if ledger(p,root)+Decimal(packet['reserved_usd'])>=allowance.ceiling(p):raise ValueError('Complete analysis batch exceeds allowance')
    rounds=[];value=dict(hypotheses=[],clauses=[],unknowns=['No admitted positive relationship inputs.']);errors=[]
    if packet.get('composition')==measurements.LITERAL_VERSION:
        value,errors=measurements.inspect(measurements.literal_reading(data),data,literal=True)
    if packet['request']:
        spec=x.requests.RequestSpec(**packet['request'])
        if asdict(measurements.request(data))!=packet['request']:raise ValueError('Analysis request differs from frozen measurements')
        for n in range(2):
            receipt,ref=obtain(p,spec,transport or x.provider.transport)
            value,errors=measurements.inspect(receipt['response']['output'],data)
            rounds.append(dict(receipt=dict(path=str(ref),sha256=file_hash(ref)),errors=errors))
            if not errors or n==1:break
            spec=x.correction.request(spec,receipt['response']['output'],errors,packet['correction'])
    result=dict(version=measurements.VERSION,status='FAIL(component)' if errors else 'COMPLETE',
        input_fingerprint=packet['fingerprint'],rounds=rounds,reading=value,errors=errors)
    Store(out).write_immutable('results.json',result)
    return read_analysis(p,root)


def read_analysis(p,root):
    packet=json.loads((root/'analysis/input.json').read_text());result=json.loads((root/'analysis/results.json').read_text())
    data=materialized_inputs(p);spec=measurements.request(data) if packet['request'] else None
    if packet.get('composition')!=p.get('materialized_composition'):raise ValueError('Analysis composition changed')
    if packet['fingerprint']!=digest({k:v for k,v in packet.items() if k!='fingerprint'}):raise ValueError('Analysis freeze differs')
    if result['input_fingerprint']!=packet['fingerprint'] or (asdict(spec) if spec else None)!=packet['request']:
        raise ValueError('Analysis lineage differs')
    if packet['inputs']!=p['materialized_inputs'] or bool(spec)!=bool(result['rounds']):
        raise ValueError('Analysis receipt inventory differs')
    value=dict(hypotheses=[],clauses=[],unknowns=['No admitted positive relationship inputs.']);errors=[]
    if packet.get('composition')==measurements.LITERAL_VERSION:
        value,errors=measurements.inspect(measurements.literal_reading(data),data,literal=True)
    for n,round_ in enumerate(result['rounds']):
        ref=round_['receipt']
        if n>1 or file_hash(ref['path'])!=ref['sha256']:raise ValueError('Analysis receipt changed')
        receipt=x._cached(spec,x._store(p,spec))
        if receipt is None or receipt['halt']:raise ValueError('Analysis receipt incomplete')
        value,errors=measurements.inspect(receipt['response']['output'],data)
        if errors!=round_['errors']:raise ValueError('Analysis mechanical findings differ')
        if errors and n==0:spec=x.correction.request(spec,receipt['response']['output'],errors,packet['correction'])
    if value!=result['reading'] or errors!=result['errors']:raise ValueError('Analysis output changed')
    return result


def obtain(p, spec, transport):
    """Existing shared accounting namespace; failed/unreceipted work cannot resend."""
    target = x._store(p, spec)
    with x.supervised.cumulative_history(p, target.root) as history:
        spent = x.supervised.BASELINE_SPEND + sum((c for _,c in history),Decimal(0))
        cached = x._cached(spec,target)
        if cached and cached['halt'] and spec.fingerprint in p.get('completed_wire_reuse',{}):
            ref=p['completed_wire_reuse'][spec.fingerprint]
            if file_hash(ref['path'])!=ref['sha256']:raise ValueError('Reconciled receipt changed')
            revised=json.loads(Path(ref['path']).read_text())
            for parent in revised['reconciliation'].values():
                if isinstance(parent,dict) and 'path' in parent and file_hash(parent['path'])!=parent['sha256']:
                    raise ValueError('Reconciled parent changed')
            wire=json.loads(Path(revised['reconciliation']['complete_wire']['path']).read_text())
            if (revised['request']!=asdict(spec) or revised['halt'] or revised['response_digest']!=digest(revised['response'])
                or x.requests.decode_response(spec,x.requests.WireResponse(**wire))!=revised['response']):
                raise ValueError('Reconciled complete response differs')
            return revised,Path(ref['path'])
        if cached is None:
            if spent+x.requests.request_reservation(spec) >= allowance.ceiling(p):
                raise ValueError('Goal allowance exhausted')
            paid = x.requests.request_provider(spec)=='DeepInfra'
            guard = (x.provider.OneRequestLedger(str(x.requests.request_reservation(spec)),spec.version)
                if paid else x.requests.BudgetLedger(max_attempts=1))
            x.requests.execute(spec,guard,target,transport)
            cached = x._cached(spec,target)
        if cached is None or cached['halt'] or cached['response'] is None:
            raise ValueError('Incomplete or unknown usage; stop without retry')
    return cached, target.root/'receipts'/f'{spec.fingerprint}.json'


def run_source(path, batch, approve_input, *, check_only=False, transport=None):
    p, root = load(path)
    if approve_input != p['input_fingerprint']:
        raise ValueError('Exact frozen input approval required')
    task = next(t for t in p['tasks'] if t['id']==batch)
    for previous in p['tasks'][:p['tasks'].index(task)]:
        if not (root/'sources'/previous['id']/'result.json').exists():
            raise ValueError('Preceding source batch incomplete; no advancement after unknown usage')
    out = root/'sources'/batch
    if (out/'result.json').exists():
        return json.loads((out/'result.json').read_text())
    if check_only:
        return dict(status='CHECKED_NO_EXECUTION',batch=batch,reserved_usd=task['reserved_usd'])
    if ledger(p, root)+Decimal(task['reserved_usd']) >= allowance.ceiling(p):
        raise ValueError('Complete source batch reservation exceeds goal allowance')
    window = SourceWindow(**task['window']); spec = x.requests.RequestSpec(**task['request'])
    send = transport or x.provider.transport
    raw, receipt = obtain(p,spec,send)
    checked = producer.inspect(raw['response']['output'],window,spec,receipt)
    rounds = [dict(receipt=str(receipt),errors=checked['errors'])]
    if checked['errors']:
        corrected = source_correction(spec,raw['response']['output'],checked['errors'],headroom=bool(p.get('source_correction_headroom')),
            feedback_headroom=bool(p.get('source_feedback_headroom')))
        # Corrective context must fit its original frozen policy, never truncate.
        raw, receipt = obtain(p,corrected,send)
        spec = corrected
        checked = producer.inspect(raw['response']['output'],window,spec,receipt)
        rounds.append(dict(receipt=str(receipt),errors=checked['errors']))
    rows = []; verification = None
    if not checked['errors']:
        verifier = producer.verification(window,checked['observations'],field_local=p.get('field_criteria_contract')==producer.FIELD_LOCAL_CRITERIA)
        if verifier:
            if p.get('field_isolated_verification')==producer.FIELD_VERIFICATION_VERSION:
                rows,vpath=verify_fields(p,out,window,checked,transport or x.requests.typesafe_transport)
            else:
                answer, vpath = obtain(p,verifier,transport or x.requests.typesafe_transport)
                rows = producer.qualify(checked,answer['response'],verifier)
            verification = str(vpath)
    result = dict(batch=batch,status='FAIL(component)' if checked['errors'] else 'COMPLETE',
        observations=rows, rounds=rounds, abstentions=checked.get('abstentions',[]),
        source_status=(checked.get('reading') or {}).get('status'), verification_receipt=verification,
        eligible=sum(r['section_eligibility']['eligible'] for r in rows),
        production_admission='not_admitted')
    Store(out).write_immutable('result.json',result)
    return result


def verify_fields(p,out,window,checked,transport):
    local=p.get('field_criteria_contract')==producer.FIELD_LOCAL_CRITERIA
    full=producer.verification(window,checked['observations'],field_local=local)
    cached=x._cached(full,x._store(p,full));reused={};ref=None
    if cached and not cached['halt']:
        reused=producer.reused_answers(cached['response'],full,producer.verification_parts(window,checked['observations'],field_local=local))
        path=x._store(p,full).root/'receipts'/f'{full.fingerprint}.json'
        ref=dict(path=str(path),sha256=file_hash(path))
    parts=producer.verification_parts(window,checked['observations'],reused,field_local=local)
    receipts={}
    for field,spec in parts.items():
        _,path=obtain(p,spec,transport)
        receipts[field]=dict(path=str(path),sha256=file_hash(path))
    bundle=dict(version=producer.FIELD_VERIFICATION_VERSION,window_digest=digest(asdict(window)),
        canonical_contract_request=asdict(full),reused_from=ref,reused_keys=sorted(reused),parts=receipts,
        compatibility='Exact source, bound proposals, field questions, criteria and Jev model. Compatible resolved fields and any identical model-visible inputs are reused, including uncertainty. Other fields receive isolated proposal views. No old answers enter model inputs.')
    bundle['fingerprint']=digest(bundle)
    path=out/'verification-bundle.json';Store(out).write_immutable(path.name,bundle)
    rows,_=load_field_bundle(path,window,checked)
    return rows,path


def load_field_bundle(path,window,checked):
    bundle=json.loads(Path(path).read_text());files={str(path):file_hash(path)}
    if (bundle['version']!=producer.FIELD_VERIFICATION_VERSION or bundle['window_digest']!=digest(asdict(window))
        or bundle['fingerprint']!=digest({k:v for k,v in bundle.items() if k!='fingerprint'})):
        raise ValueError('Field verification bundle differs')
    criteria=bundle['canonical_contract_request']['source_identity'].get('field_criteria_contract')
    local=criteria if criteria in (producer.FIELD_LOCAL_CRITERIA_V1,producer.FIELD_LOCAL_CRITERIA) else False
    full=producer.verification(window,checked['observations'],field_local=local)
    if bundle['canonical_contract_request']!=asdict(full):raise ValueError('Canonical field contract differs')
    def response(ref,spec):
        if file_hash(ref['path'])!=ref['sha256']:raise ValueError('Field receipt changed')
        raw=x._cached(spec,x.requests.ReceiptStore(Path(ref['path']).parent.parent))
        if raw is None or raw['halt']:raise ValueError('Field receipt incomplete')
        x.requests.validate_response(spec,raw['response'])
        files[ref['path']]=ref['sha256'];return raw['response']
    reused=producer.reused_answers(response(bundle['reused_from'],full),full,producer.verification_parts(window,checked['observations'],field_local=local)) if bundle['reused_from'] else {}
    if sorted(reused)!=bundle['reused_keys']:raise ValueError('Reused field inventory differs')
    parts=producer.verification_parts(window,checked['observations'],reused,field_local=local)
    if set(parts)!=set(bundle['parts']):raise ValueError('Field-part inventory differs')
    answers={field:response(bundle['parts'][field],spec) for field,spec in parts.items()}
    return producer.qualify_parts(checked,full,parts,answers,reused),files


def check_strength(claim):
    """Producer assertion-force contract, independent of model approval.

    Producers explicitly declare claim force; this is a structural gate, not an
    NLP claim detector. The unchanged historical main-question case is regression
    material with comparative_priority force and no warrant.
    """
    force = claim.get('assertion_force')
    if claim.get('assertion_contract'):
        contract=claim['assertion_contract']
        if contract['declared_force']!=force or force not in contract['allowed_forces']:
            raise ValueError('Generated claim force lacks supplied authority')
    if force not in ('local_observation','sample_membership','comparative_priority','dominance','frequency','causal'):
        raise ValueError('Explicit assertion force required')
    if force in ('comparative_priority','dominance','frequency','causal') and not claim.get('strength_warrant'):
        raise ValueError('Claim strength lacks explicit warrant')
    if re.search(r'\b(main question|dominant|predominant|most important|primarily|more often|causes)\b',claim['wording'],re.I) and not claim.get('strength_warrant'):
        raise ValueError('Comparative/causal wording requires an explicit strength warrant')


def assemble_record(p, results):
    """No transcript interpretation here: copy qualified upstream local statements."""
    observations = []
    for result in results:
        observations.extend(result['observations'])
    eligible = [o for o in observations if o['section_eligibility']['eligible']]
    claims = []
    for o in eligible:
        cid = 'section-'+o['id']
        claims.append(dict(id=cid,wording=o['response_growth']['reader_statement'],
            evidence_ids=[], machine_observation_ids=[o['id']], upstream_claim_ids=[],
            scope=dict(video_ids=sorted({r['video_id'] for r in o['source_refs']}),meaning='Selected complete source window only. '+LIMIT),
            assertion_force='local_observation', analytical_basis=producer.VERSION))
    facets = {f:[o['id'] for o in eligible if f in o['response_growth']['facets']] for f in producer.FACETS}
    hypotheses = []
    if all(facets[f] for f in ('personal_response','gradual_growth','reassurance','challenge')):
        premises = sorted(set(i for f in ('personal_response','gradual_growth','reassurance','challenge') for i in facets[f]))
        # Membership, not an explanatory relation or a claim about relative weight.
        conclusion = ('The selected examples include personal response, reassurance and challenge, '
            'alongside teaching about gradual growth. Their presence together supports reading '
            'the invitations with the attached growth qualifications; it does not establish '
            'their relative emphasis or a complete account of salvation.')
        h = dict(id='section-sample-connection', conclusion=conclusion,premise_ids=premises,
            inference_type='selected_example_membership',scope_video_ids=sorted({r['video_id'] for o in eligible if o['id'] in premises for r in o['source_refs']}),
            warrant='Each named facet is verified in an eligible upstream local binding. Co-presence warrants retaining them together; no causal or doctrinal reconciliation is inferred.',
            alternatives=['Selection may exaggerate how closely these themes are connected elsewhere.'],
            counterevidence_ids=[o['id'] for o in observations if o['binding']['adoption']['status'] in ('rejected','reported_not_adopted')],
            defeaters=['An erroneous upstream facet or lost qualification defeats this connection.'])
        hypotheses.append(h)
        claims.append(dict(id=h['id'],wording=h['conclusion'],evidence_ids=[],
            machine_observation_ids=premises, upstream_claim_ids=['section-'+i for i in premises],
            scope=dict(video_ids=h['scope_video_ids'],meaning=LIMIT),assertion_force='sample_membership',
            analytical_basis=h['warrant'],limits=h['defeaters'],alternative=h['alternatives']))
    for c in claims:
        check_strength(c)
    return dict(version=VERSION,profile=p['profile'],inventory_fingerprint=p['inventory_fingerprint'],
        source_identity=p['source_identity'],observations=[],machine_observations=observations,
        machine_windows={t['id']:t['window'] for t in p['tasks']},claims=claims,
        reader=dict(claims=claims,portrait=dict(entries=claims),synthesis_rule='Verified local examples and explicit selected-example membership only.'),
        coverage=p['coverage'],hypotheses=hypotheses,
        gaps=[dict(id='coverage',withheld='Complete profile characterization',cause=LIMIT,remedy='Independent holdout and broader separately authorized evidence')]+
            [dict(id='unknown-'+str(i),withheld=v,cause='Not established by selected evidence',remedy='Retain unknown') for i,v in enumerate(UNKNOWN)],
        production_admission='not_admitted')


def machine_case(record, claim):
    """Shared analysis-support seam: verify saved producer receipts, never repair them."""
    check_strength(claim)
    by_id = {o['id']:o for o in record['machine_observations']}
    sources = {}; bound = []; files = {};dimensions=[];dimension_field=claim.get('dimension_field')
    if dimension_field is not None and dimension_field not in ('growth','requested_response'):raise ValueError('Unknown source dimension')
    for oid in claim['machine_observation_ids']:
        o = by_id[oid]
        if (not dimension_field and not o['section_eligibility']['eligible']) or o['origin']!='machine_generated' or o['production_admission']!='not_admitted':
            raise ValueError('Machine binding is not eligible experimental evidence')
        source_ids = {r['window_id'] for r in o['source_refs']}
        if len(source_ids)!=1:
            raise ValueError('Binding needs exactly one complete source window')
        wid = next(iter(source_ids)); w = SourceWindow(**record['machine_windows'][wid])
        if w.video_id not in record['profile']['effective_member_video_ids']:
            raise ValueError('Machine binding outside declared membership')
        source = next(s for s in record['source_identity'] if s['video_id']==w.video_id)
        if not source['gate']['eligible'] or w.source_sha256!=source['source_sha256'] or file_hash(source['source_path'])!=w.source_sha256:
            raise ValueError('Machine source identity changed')
        raw = json.loads(Path(source['source_path']).read_text())
        blocks = {b['block_id']:b for b in sermon_topics.resolve_topic_analysis_artifact(raw['classification'])['blocks']}
        for block in w.blocks:
            actual = blocks[block['block_id']]
            if (block['target_text']!=sermon_topics.resolve_topic_block_context(actual)['target_text'] or
                any(block[k]!=actual[k] for k in ('start_seconds','end_seconds','segment_indexes'))):
                raise ValueError('Machine window geometry changed')
        ref = Path(o['raw_response_ref']); receipt = json.loads(ref.read_text()); spec=x.requests.RequestSpec(**receipt['request'])
        for parent in receipt.get('reconciliation',{}).values():
            if isinstance(parent,dict) and 'path' in parent:
                if file_hash(parent['path'])!=parent['sha256']:raise ValueError('Machine reconciliation parent changed')
                files[parent['path']]=parent['sha256']
        if receipt['halt'] or receipt['response_digest']!=digest(receipt['response']):
            raise ValueError('Machine producer receipt changed')
        x.requests.validate_response(spec,receipt['response'])
        checked = producer.inspect(receipt['response']['output'],w,spec,ref)
        rebuilt = next(r for r in checked['observations'] if r['id']==oid)
        # Verify original Jev answers and every retained binding/extension field.
        vref=Path(o['verification_receipt']); vr=json.loads(vref.read_text())
        if vr.get('version')==producer.FIELD_VERIFICATION_VERSION:
            verified,field_files=load_field_bundle(vref,w,checked);files.update(field_files)
        else:
            verifier=producer.verification(w,checked['observations'])
            if vr['request']!=asdict(verifier) or vr['halt'] or vr['response_digest']!=digest(vr['response']):
                raise ValueError('Machine verification receipt changed')
            verified=producer.qualify(checked,vr['response'],verifier)
        rebuilt=next(r for r in verified if r['id']==oid)
        rebuilt['verification_receipt']=str(vref)
        if rebuilt!=o:
            raise ValueError('Machine binding or eligibility changed')
        if dimension_field:
            finding,dimension_files=dimension_proof(record,w,oid,dimension_field);files.update(dimension_files);dimensions.append(finding)
        texts=w.target()[0]
        sources[wid]=dict(window=json.loads(json.dumps(asdict(w))),texts=texts,
            fields=x.core._inventory(w,texts),context_sha256=x.core.context_digest(texts))
        bound.append(dict(id=oid,qualified_dimension=finding,authority=finding['authority'],source_refs=o['source_refs']) if dimension_field else deepcopy(o))
        files.update({str(ref):file_hash(ref),str(vref):file_hash(vref),source['source_path']:w.source_sha256})
    passages=[dict(passage_id=k,video_id=s['window']['video_id'],fields={f:[dict(id=u['id'],text=u['text']) for u in units] for f,units in s['fields'].items()}) for k,s in sources.items()]
    hypotheses=[h for h in record.get('hypotheses',[]) if h['id']==claim['id']]
    state=dict(candidate=dict(id=claim['id'],statement=claim['wording'],scope=claim['scope'],
        declared_caveats={k:claim[k] for k in ('limits','alternative') if k in claim},analytical_basis=claim['analytical_basis']),
        sample=dict(profile_id=record['profile']['id'],video_ids=record['profile']['effective_member_video_ids'],coverage=record['coverage']),
        bound_observations=bound,passages=passages,measurement_ledger=dict(rows=[],contracts=[],meaning='Qualified machine bindings; not legacy leaf measurements'),
        upstream_points=[],stored_aggregates=[],upstream_aggregate_claims=hypotheses,
        aggregation_contract=record['reader']['synthesis_rule'])
    if dimension_field:
        state['qualified_dimensions']=dimensions
        state['measurement_ledger']['meaning']='Only the named independently qualified dimensions are evidence; the complete source bindings remain withheld.'
    if claim.get('assertion_contract'):state['candidate']['assertion_contract']=deepcopy(claim['assertion_contract'])
    if claim['evidence_ids']:
        reader=x.core.EvidenceReader(record)
        measured=x.core._case(record,claim,reader,{c['id']:c for c in record['claims']},{})
        if set(sources)&set(measured['sources']):raise ValueError('Mixed evidence passage identities collide')
        sources.update(measured['sources']);files.update(reader.files)
        state['passages']+=measured['state']['passages'];state['measurement_ledger']=measured['state']['measurement_ledger']
        state['upstream_aggregate_claims']=measured['state']['upstream_aggregate_claims']+hypotheses
        input_ids=measured['input_ids']
    else:input_ids={}
    return dict(state=state,sources=sources,input_ids=input_ids,dependencies=claim['upstream_claim_ids'],
        identity=dict(profile_id=record['profile']['id'],membership_fingerprint=record['profile']['membership_fingerprint'],inventory_fingerprint=record['inventory_fingerprint']),source_files=files)


def prepare_support(path):
    p, root = load(path); results=[]
    for t in p['tasks']:
        result=json.loads((root/'sources'/t['id']/'result.json').read_text())
        for o in result['observations']:
            o['verification_receipt']=result['verification_receipt']
        results.append(result)
    record=assemble_record(p,results)
    if p.get('materialized_inputs'):
        data=materialized_inputs(p);draft=read_analysis(p,root)
        record['observations']=data['observations']
        record['materialized_analysis']=dict(inputs=p['materialized_inputs'],
            generation=dict(path=str(root/'analysis/results.json'),sha256=file_hash(root/'analysis/results.json')),
            authority=data['authority'],block_states=data['block_states'])
        if not draft['errors']:
            for claim in measurements.claims(draft['reading'],data):
                try:check_strength(claim)
                except ValueError as error:
                    record['gaps'].append(dict(id='withheld-'+claim['id'],withheld=claim['wording'],
                        cause=str(error),remedy='Retain original unsupported candidate; no semantic rewrite or retry.'))
                    continue
                record['claims'].append(claim)
            record['hypotheses'].extend(draft['reading']['hypotheses'])
            record['analysis_unknowns']=draft['reading']['unknowns']
        else:record['gaps'].append(dict(id='materialized-draft',withheld='Measured relationship analysis',
            cause='Bounded analysis draft failed its mechanical contract',remedy='Retain unknown'))
        record['reader']['claims']=record['claims'];record['reader']['portrait']['entries']=record['claims']
        record['reader']['synthesis_rule']+=' Admitted materialized relationships retain their exact local meanings; no adoption, polarity or condition is inferred from them.'
    if p.get('dimension_contract'):attach_dimensions(p,root,record)
    Store(root).write_immutable('assembled-profile.json',record)
    plan=x.core.build_plan(record); tasks=[]
    for item in plan['items']:
        if item['case'] is None:
            continue
        spec=x.make_request(item['case'],whole_statement=True)
        tasks.append(dict(claim_id=item['claim_id'],request=asdict(spec),token_account=spec.preflight(),correction=x.correction.policy(spec,headroom=True)))
    total=sum((x.requests.request_reservation(x.requests.RequestSpec(**t['request']))+Decimal(t['correction']['reserved_usd']) for t in tasks),Decimal(0))
    if total>Decimal(p['budget']['support_reservation_usd']):
        raise ValueError('Support exceeds frozen sequence reservation; no expansion')
    batches=[]; group=[];cost=Decimal(0)
    for task in tasks:
        amount=x.requests.request_reservation(x.requests.RequestSpec(**task['request']))+Decimal(task['correction']['reserved_usd'])
        if amount>Decimal('.50'):
            raise ValueError('Single support case exceeds batch cap')
        if group and cost+amount>Decimal('.50'):
            batches.append((group,cost));group=[];cost=Decimal(0)
        group.append(task);cost+=amount
    if group or not tasks:batches.append((group,cost))
    inputs=[]
    for i,(group,cost) in enumerate(batches):
        ids={t['claim_id'] for t in group}
        selection={**plan,'items':[item for item in plan['items'] if item['claim_id'] in ids]}
        packet=dict(version=x.core.VERSION,plan=selection,tasks=group,acceptance_authorization=p['acceptance_authorization'],
            budget={**p['budget'], 'max_usd':'.50','reserved_usd':str(cost),
                'maximum_paid_attempts':sum(2*t['token_account'].get('stream_recovery',{}).get('maximum_attempts',1) for t in group)})
        packet['input_fingerprint']=digest(packet)
        dest=root/'support'/f'{i+1:02d}'/'input.json'
        Store(dest.parent).write_immutable(dest.name,packet)
        inputs.append(str(dest))
    Store(root).write_immutable('support-plan.json',dict(plan=plan,inputs=inputs,profile_sha256=file_hash(root/'assembled-profile.json')))
    return dict(inputs=inputs,claims=len(plan['items']),eligible_bindings=sum(r['eligible'] for r in results),reserved_usd=str(total))


def run_support(path, batch, approve_input, *,check_only=False,transport=None):
    p,root=load(path)
    if approve_input!=p['input_fingerprint']:raise ValueError('Exact frozen approval required')
    frozen=json.loads((root/'support-plan.json').read_text())
    record=x.core.read_record(root/'assembled-profile.json')
    if file_hash(root/'assembled-profile.json')!=frozen['profile_sha256'] or x.core.build_plan(record)!=frozen['plan']:
        raise ValueError('Assembled evidence or plan changed')
    input_path=Path(frozen['inputs'][int(batch)-1]);packet=json.loads(input_path.read_text())
    if packet['input_fingerprint']!=digest({k:v for k,v in packet.items() if k!='input_fingerprint'}):
        raise ValueError('Support packet changed')
    if check_only:return dict(status='CHECKED_NO_EXECUTION',budget=packet['budget'])
    return x.recipe(packet,input_path.parent,transport or x.provider.transport)


def render(path):
    p,root=load(path);frozen=json.loads((root/'support-plan.json').read_text());rows=[]
    for name in frozen['inputs']:
        rows.extend(json.loads((Path(name).parent/'results.json').read_text())['results'])
    document=x.core.document_input(frozen['plan'],rows)
    record=x.core.read_record(root/'assembled-profile.json')
    document['section_trace']={c['id']:dict(evidence_ids=list(dict.fromkeys(c.get('machine_observation_ids',[])+c['evidence_ids'])),
        premise_ids=c['upstream_claim_ids'],scope=c['scope'],assertion_force=c['assertion_force'],
        interpretation=next((h for h in record['hypotheses'] if h['id']==c['id']),None),
        analytical_basis=c['analytical_basis'],assertion_contract=c.get('assertion_contract'),
        evidence_kind=('mixed_qualified_dimension_and_measurements' if c['evidence_ids'] else 'qualified_source_dimension') if c.get('dimension_field') else 'qualified_machine_binding' if 'machine_observation_ids' in c else 'admitted_local_relationship') for c in record['claims']}
    document['unknowns']=list(dict.fromkeys(p['unknowns']+record.get('analysis_unknowns',[])+
        (['Voiced speaker, preacher adoption, polarity and attached conditions are not supplied by local relationship measurements.'] if record.get('materialized_analysis') else [])))
    document['limitation']=LIMIT
    if record.get('materialized_analysis'):document['materialized_analysis']=record['materialized_analysis']
    if record.get('dimension_packets'):document['dimension_packets']=record['dimension_packets']
    Store(root).write_immutable('document-input.json',document)
    lines=['# Salvation, personal response and spiritual growth','',LIMIT,'']
    if record.get('materialized_analysis'):
        lines.extend(['Relationship findings describe what is discussed in these selected passages. They do not by themselves establish which reported views the preacher adopts or how every condition applies.',''])
    sources={t['id']:t['window'] for t in p['tasks']}
    obs={o['id']:o for o in record['machine_observations']}
    measured={o['id']:o for o in record['observations']}
    for entry in document['entries']:
        if entry['support_status']!='supported':continue
        links=[]
        for oid in document['section_trace'][entry['claim_id']]['evidence_ids']:
            if oid in measured:
                o=measured[oid]
                link=f"[Recording {o['video_id']}, block {o['block_id']}]({o['watch_url']})"
                if link not in links:links.append(link)
                continue
            window=sources[obs[oid]['source_refs'][0]['window_id']]
            source=next(s for s in p['source_identity'] if s['video_id']==window['video_id'])
            url=source['url']+('&' if '?' in source['url'] else '?')+'t='+str(int(window['blocks'][0]['start_seconds']))
            link=f"[Recording {window['video_id']}, blocks {window['blocks'][0]['block_id']}–{window['blocks'][-1]['block_id']}]({url})"
            if link not in links:links.append(link)
        lines.extend([entry['statement']+' '+'; '.join(links), '',f"Trace: `{entry['claim_id']}`",''])
    if not document['ready_claim_ids']:
        lines.extend(['No substantive paragraph passed all upstream and analysis-support gates.',''])
    lines.extend(['## Limits and unknowns','']+['- '+u for u in document['unknowns']]+['','## Withheld clauses',''])
    lines += [f"- {e['statement']} ({e['support_status']})" for e in document['entries'] if e['support_status']!='supported']
    (root/'draft-section.md').write_text('\n'.join(lines)+'\n')
    (root/'analysis-support.md').write_text(x.core.render_handoff(document))
    spent=ledger(p,root);start=Decimal(p['budget']['starting_conservative_usd'])
    report=dict(draft=str(root/'draft-section.md'),document_input=str(root/'document-input.json'),
        model_supported=len(document['ready_claim_ids']),clauses=len(document['entries']),
        eligible_upstream=sum(o['section_eligibility']['eligible'] for o in obs.values()),
        upstream_total=len(obs),starting_conservative_usd=str(start),cumulative_conservative_usd=str(spent),
        reused_materialized_observations=len(measured),qualified_dimensions=sum(r['eligible'] for r in record.get('dimension_findings',[])),
        new_conservative_usd=str(spent-start),remaining_credit_usd=str(allowance.ceiling(p)-spent),
        semantic_acceptance='Pending separate source review of original outputs',production_admission='not_admitted')
    Store(root).write_immutable('delivery.json',report)
    return report


def failure_handoff(path):
    """Close an unknown-usage stop without another provider call or evidence repair.

    This historical/report path verifies the original frozen requests and sources,
    rather than requiring the reporting implementation to equal the execution freeze.
    It cannot prepare or execute new requests.
    """
    path=Path(path);p=json.loads(path.read_text());root=path.parent
    if p['input_fingerprint']!=digest({k:v for k,v in p.items() if k!='input_fingerprint'}):
        raise ValueError('Section freeze differs')
    saved=root/'failure'/'assessment.json'
    if saved.exists():
        report=json.loads(saved.read_text())
        if report['input_fingerprint']!=p['input_fingerprint']:
            raise ValueError('Foreign failure assessment')
        return report
    limit=allowance.ceiling(p)
    inv=inventory(Path(p['base_dir']))
    if inv['content_fingerprint']!=p['inventory_fingerprint'] or digest([asdict(w) for w in windows(inv)])!=digest([t['window'] for t in p['tasks']]):
        raise ValueError('Frozen membership/source identity changed')
    attempts=[]
    for task in p['tasks']:
        spec=x.requests.RequestSpec(**task['request']);spec.preflight()
        store=x._store(p,spec)
        for attempt in store.attempts():
            if attempt['request_fingerprint']!=spec.fingerprint:
                raise ValueError('Foreign source attempt')
            receipt=store.root/'receipts'/f'{spec.fingerprint}.json'
            if receipt.exists():
                x._cached(spec,store)
            account=x.supervised.check.demo.usage_account(store)
            attempts.append(dict(batch=task['id'],request_fingerprint=spec.fingerprint,
                attempt_path=str(store.root/'attempts'/f'{spec.fingerprint}.json'),
                receipt_path=str(receipt),receipt_present=receipt.exists(),accounting=account))
    uncertain=[a for a in attempts if a['accounting']['unknown_usage_attempts']]
    if not uncertain:
        raise ValueError('Failure handoff requires a demonstrated unknown-usage stop')
    if any((root/'sources'/t['id']/'result.json').exists() for t in p['tasks']):
        raise ValueError('Completed source results require ordinary assembly; do not discard evidence')
    out=root/'failure'
    # Include preserved predecessor attempts once, without copying or relabeling
    # their receipts. A goal's conservative charge includes every physical send.
    history={a['request_fingerprint']:a for a in attempts}
    predecessors=[]
    for lost in p.get('transport_recovery',{}).get('preserved_lost_attempts',[]):
        ref=lost['attempt']
        if file_hash(ref['path'])!=ref['sha256']:raise ValueError('Lost attempt changed')
        predecessors.append(Path(ref['path']).parent.parent)
    for ref in p.get('streaming_recovery',{}).get('preserved_files',[]):
        if file_hash(ref['path'])!=ref['sha256']:raise ValueError('Streaming predecessor changed')
        if Path(ref['path']).parent.name=='receipts':predecessors.append(Path(ref['path']).parent.parent)
    for directory in predecessors:
        store=x.requests.ReceiptStore(directory)
        for attempt in store.attempts():
            key=attempt['request_fingerprint'];receipt=directory/'receipts'/f'{key}.json'
            if receipt.exists():
                raw=json.loads(receipt.read_text());x._cached(x.requests.RequestSpec(**raw['request']),store)
            history[key]=dict(request_fingerprint=key,attempt_path=str(directory/'attempts'/f'{key}.json'),
                receipt_path=str(receipt),receipt_present=receipt.exists(),accounting=x.supervised.check.demo.usage_account(store))
    all_attempts=list(history.values())
    halt_reasons=[json.loads(Path(a['receipt_path']).read_text()).get('halt') for a in all_attempts if a['receipt_present']]
    record=assemble_record(p,[])
    gap=dict(id='source-transport-unknown-usage',withheld='A substantive account of salvation, requested personal response, spiritual growth and reassurance/challenge in this sample',
        cause='The frozen source request has a durable paid attempt but no complete usage-bearing receipt. All subsequent paid work is stopped.',
        inspected_reuse=['Completed evidence-reuse audit: three compatible materialized sources, nine existing salvation meanings; three quarantined meanings unchanged.',
            'Saved machine bindings retain partial/unverified authority and do not supply complete compatible response/growth evidence.',
            'Frozen source request cache: attempt present, complete receipt absent. No replacement output or manual source reading is runtime evidence.'],
        missing_information='A complete accounted response and qualified upstream observations for the frozen windows.',
        responsible_producer='Shared DeepInfra source transport/receipt boundary before response_growth_binding and Jev qualification',
        remedy='Reconcile the original request usage/termination before proposing a separately authorized frozen recovery. No retry, next window, model switch or successor experiment in this delivery.',
        acceptance='Original attempt usage reconciled; any separately authorized recovery has durable accounting and passes unchanged literal/field gates.',
        authorization_boundary='Current unknown-usage stop remains in force; no additional paid execution.')
    if any('whitespace loop' in (reason or '') for reason in halt_reasons):
        gap.update(cause='The unchanged Flash source request repeatedly entered a JSON whitespace loop. Existing streaming cancellation closed both connections and its one recovery was exhausted; no complete source binding exists.',
            missing_information='A valid complete source-binding response under the frozen structured-output contract.',
            responsible_producer='DeepInfra Flash constrained source generation / strict-schema compatibility before upstream binding qualification',
            remedy='Investigate the demonstrated provider/schema incompatibility using the preserved partial outputs. Any change to the upstream model role requires Brian’s separate decision. No further paid variant or successor experiment in this delivery.')
    record['gaps'].insert(0,gap)
    plan=x.core.build_plan(record)
    document=x.core.document_input(plan,[])
    document.update(section_trace={},unknowns=p['unknowns'],limitation=LIMIT,
        delivery_status='FAILED_UPSTREAM_TRANSPORT',unresolved_section_requirements=[
            'How the selected sample presents salvation', 'What personal response is requested or described',
            'How conditions and qualifications distinguish growth from immediate perfection',
            'How supported reassurance and challenge relate within the selected sample'],
        source_execution=all_attempts)
    Store(out).write_immutable('assembled-profile.json',record)
    Store(out).write_immutable('document-input.json',document)
    Store(out).write_immutable('clause-trace.json',dict(clauses=[],reason='No clause is released without qualified upstream evidence and analysis support.'))
    draft=('# Salvation, personal response and spiritual growth\n\n'
        'Analysis unavailable for this bounded delivery. The first source check ended without '
        'a complete response or known usage. No substantive paragraph is released.\n\n'
        'The prepared sample comprises recordings 281, 3973 and 4589. How it presents salvation, '
        'personal response, growth and reassurance/challenge remains unresolved in this delivery. '
        'This is a collection failure, not evidence that those subjects are absent.\n')
    (out/'draft-section.md').write_text(draft)
    (out/'analysis-support.md').write_text(x.core.render_handoff(document))
    spent=ledger(p,root);start=Decimal(p['budget']['starting_conservative_usd'])
    assessment=dict(status='FAILED_BOUNDED_DELIVERY',plan=str(path),input_fingerprint=p['input_fingerprint'],
        implementation_at_freeze=p['code_identity'],report_implementation=identity(),
        draft=str(out/'draft-section.md'),document_input=str(out/'document-input.json'),clause_trace=str(out/'clause-trace.json'),
        source_execution=all_attempts,blocked_statement=gap,
        assessment=dict(mechanical='Live source transport failed before a complete response; prior 70 focused offline tests passed.',
            model_approval='Not obtained; no source binding, Jev judgment or Qwen support result exists.',
            claim_fidelity='Not assessable: zero generated/released substantive clauses.',
            retained_qualifications='Not assessable: no qualified observations generated.',
            omissions='The entire requested substantive section is withheld; prior full-source omission findings remain unresolved.',
            contrary_evidence='No adopted stance or refutation is inferred. Frozen contrasts were not assessed by this execution.',
            usefulness='Failure handoff and blocker are inspectable; the requested useful analysis section was not delivered.',
            coverage=f"One source window attempted in {sum(a['accounting']['paid_attempts'] for a in all_attempts)} physical sends; no completed windows. Five other frozen windows and downstream stages were not run.",
            semantic_acceptance='FAIL: substantive deliverable unavailable; no accuracy or generalization claim.'),
        costs=dict(actual_invoice_usd=None,provider_estimated_usd=None,known_usage_usd=None,
            unknown_usage_attempts=sum(a['accounting']['unknown_usage_attempts'] for a in all_attempts),
            known_list_price_usage_usd=str(sum((Decimal(a['accounting']['known_list_price_usage_usd']) for a in all_attempts),Decimal(0))),
            partial_provider_estimated_usd=str(sum((Decimal(a['accounting'].get('known_provider_estimated_usage_usd','0')) for a in all_attempts),Decimal(0))),
            physical_paid_attempts=sum(a['accounting']['paid_attempts'] for a in all_attempts),
            starting_conservative_usd=str(start),new_conservative_usd=str(spent-start),
            cumulative_conservative_usd=str(spent),remaining_goal_credit_usd=str(limit-spent)),
        production_admission='not_admitted',next_step=gap['remedy'],paid_execution_stopped=True)
    Store(out).write_immutable('assessment.json',assessment)
    (out/'assessment.md').write_text('# Bounded section delivery failed at source transport\n\n'+
        '\n\n'.join(f'**{k.replace("_"," ")}:** {v}' for k,v in assessment['assessment'].items())+
        '\n\n## Costs\n\n'+json.dumps(assessment['costs'],indent=2)+
        '\n\nActual provider billing is unknown; the complete lost-request reservation remains charged. No retries or successor checks ran.\n\n## Smallest responsible blocker\n\n'+
        gap['cause']+' '+gap['remedy']+'\n')
    return assessment
