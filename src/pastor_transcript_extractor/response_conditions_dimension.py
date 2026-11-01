"""Sample-scoped response/conditions contract over the existing section workflow."""
from dataclasses import asdict
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

from . import profile_section as section
from .pastor_evidence import EvidenceArtifactStore as Store, digest
from .profile_support_validation import file_hash

VERSION = 'response-conditions-dimension-v1'
SELECTION = 'response-conditions-confirmation-coordinate-hash-v1'


def select_confirmation(sermons):
    """Choose four disjoint three-block windows without inspecting any answers/text."""
    candidates = []
    development = {(v, b) for v, first, last in section.WINDOWS for b in range(first, last+1)}
    for source in sorted(sermons, key=lambda s: s['video_id']):
        vid = source['video_id']; eligible = set(source['eligible_block_ids'])
        for first in sorted(eligible):
            ids = tuple(range(first, first+3))
            if not set(ids) <= eligible or any((vid, b) in development for b in ids):
                continue
            candidates.append(dict(video_id=vid, first=first, last=first+2,
                rank=digest(dict(rule=SELECTION, video_id=vid, first=first))))
    selected = []; used = set()
    # One per recording first, then one additional hash-ranked window.
    for vid in sorted({c['video_id'] for c in candidates}) + [None]:
        for c in sorted(candidates, key=lambda c: c['rank']):
            if vid is not None and c['video_id'] != vid:
                continue
            keys = {(c['video_id'], b) for b in range(c['first'], c['last']+1)}
            if used & keys:
                continue
            selected.append(c); used.update(keys); break
    if len(selected) != 4:
        raise ValueError('Four disjoint confirmation windows unavailable')
    return selected


def freeze_confirmation(base_dir, objective, predecessor):
    """Freeze coordinates before producer revision; disclose conservative exposure."""
    inv = section.inventory(base_dir)
    chosen = select_confirmation(inv['sermons'])
    prior = json.loads(Path(predecessor).read_text())
    known = {t['id'] for t in prior['tasks']}
    for c in chosen:
        c['id'] = f"v{c['video_id']}b{c['first']}-{c['last']}"
        c['exposure'] = dict(exact_window_in_predecessor=c['id'] in known,
            recording_previously_reviewed=True, untouched=False,
            block_exposure='Not established as unseen; conservatively treated as exposed existing material.',
            independent_selection='Coordinates and eligibility only; no generated answers or source meaning used.')
    packet = dict(version=VERSION, selection_rule=SELECTION,
        objective=dict(path=str(Path(objective).resolve()), sha256=file_hash(objective)),
        predecessor=dict(path=str(Path(predecessor).resolve()), sha256=file_hash(predecessor)),
        inventory_fingerprint=inv['content_fingerprint'], confirmation=chosen,
        development=[list(w) for w in section.WINDOWS],
        sources=[{k:s[k] for k in ('video_id','source_path','source_sha256')} for s in inv['sermons']],
        producer_before_revision=file_hash(section.producer.__file__),
        meaning='Specific requested or described local responses with all attached meaning-changing restrictions, voice, adoption and polarity. No uptake or ministry-level trait.',
        representation='Set of qualified local response records; numeric pastor score is null.',
        opportunities='Each frozen window is an inspection opportunity; at most two producer-selected complete points per window. Not exhaustive response enumeration.',
        aggregation='Retain source-ordered local values, group by recording/window and disclose missingness. No occurrence rate, scalar, probability average or distance.',
        missingness='Separate no proposed response, unresolved/incorrect proposal, source failure, support withholding and not inspected. Unknown is not zero.',
        abstention='Require unchanged independent correctness and specific-presence checks at .90 plus ordinary support for readable release; complete-binding admission remains separate.',
        confirmation_policy='Freeze implementation before opening confirmation outputs; evaluate unchanged; no tuning against confirmation.',
        limits='Additional independently selected windows in already exposed recordings; not untouched material, population validation or production admission.',
        budgets=dict(provider_usd='5', maximum_batch_usd='.50', semantic_revisions=3,
            assistant_tokens=200000, maximum_helpers=2, maximum_tokens_per_helper=20000))
    packet['fingerprint'] = digest(packet)
    root = Path(base_dir)/'evaluation'/VERSION/'confirmation-freeze'/packet['fingerprint']
    Store(root).write_immutable('freeze.json', packet)
    (root/'freeze.md').write_text('# Frozen confirmation selection\n\n'+packet['limits']+'\n\n'+
        '\n'.join('- '+c['id']+' — previously exposed recording; unseen-block status unproven.' for c in chosen)+'\n')
    return dict(freeze=str(root/'freeze.json'), fingerprint=packet['fingerprint'],
        windows=[c['id'] for c in chosen], provider_calls=0)


def read_freeze(path):
    value=json.loads(Path(path).read_text())
    if value['fingerprint']!=digest({k:v for k,v in value.items() if k!='fingerprint'}):
        raise ValueError('Confirmation freeze changed')
    for ref in [value['objective'],value['predecessor']]:
        if file_hash(ref['path'])!=ref['sha256']:
            raise ValueError('Frozen authority or predecessor changed')
    return value


def authorize(base_dir, freeze_path):
    """Activate exactly the new user-authorized $5, preserving all old receipts."""
    import os
    freeze=read_freeze(freeze_path); x=section.x
    spend=x.build_paths(base_dir).evaluation/'qualified-observations'
    root=Path(base_dir)/'evaluation'/VERSION/freeze['fingerprint']
    active=spend/'active-profile-support-allowance.json'
    with x.supervised.cumulative_history(dict(budget=dict(spend_root=str(spend))),root/'baseline') as history:
        dest=root/'allowance.json'
        if dest.exists():
            auth=json.loads(dest.read_text())
        else:
            previous=json.loads(active.read_text())['authorization']
            start=x.supervised.BASELINE_SPEND+sum((c for _,c in history),Decimal(0))
            auth=dict(version=section.allowance.VERSION_V3,objective=freeze['objective'],
                confirmation_freeze=dict(path=str(Path(freeze_path).resolve()),sha256=file_hash(freeze_path)),
                supersedes=previous,starting_conservative_usd=str(start),additional_usd='5',
                cumulative_ceiling_usd=str(start+5),maximum_batch_usd='.50',spend_root=str(spend),
                snapshot=[dict(account=a,conservative_usd=str(c)) for a,c in history])
            Store(root).write_immutable('allowance.json',auth)
        ref=dict(path=str(dest),sha256=file_hash(dest))
        if json.loads(active.read_text())['authorization'] not in (auth['supersedes'],ref):
            raise ValueError('Another allowance is active')
        temporary=active.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(authorization=ref,supersedes=auth['supersedes']),indent=2))
        os.replace(temporary,active)
    return ref,auth


def validate_plan(p):
    goal=p['response_conditions_goal'];freeze=read_freeze(goal['freeze']['path'])
    if file_hash(goal['freeze']['path'])!=goal['freeze']['sha256']:
        raise ValueError('Confirmation selection changed')
    if goal['module_sha256']!=file_hash(__file__):
        raise ValueError('Dimension implementation changed after freeze')
    coordinates=(freeze['development'] if goal['phase']=='development' else
        [[c['video_id'],c['first'],c['last']] for c in freeze['confirmation']])
    if goal['phase'] not in ('development','confirmation'):
        raise ValueError('Unknown evaluation phase')
    if goal['phase']=='confirmation':
        ref=goal['implementation_freeze']
        if file_hash(ref['path'])!=ref['sha256']:
            raise ValueError('Implementation freeze changed')
        locked=json.loads(Path(ref['path']).read_text())
        if locked['code_identity']!=p['code_identity'] or locked['module_sha256']!=file_hash(__file__):
            raise ValueError('Implementation must stay unchanged for confirmation')
    return coordinates


def prepare(base_dir, freeze_path, *, implementation_freeze=None):
    freeze=read_freeze(freeze_path);inv=section.inventory(base_dir)
    if inv['content_fingerprint']!=freeze['inventory_fingerprint']:
        raise ValueError('Frozen source inventory changed')
    phase='confirmation' if implementation_freeze else 'development'
    if implementation_freeze:
        locked=json.loads(Path(implementation_freeze).read_text())
        if locked['code_identity']!=section.identity() or locked['module_sha256']!=file_hash(__file__):
            raise ValueError('Implementation changed after confirmation lock')
    ref,auth=authorize(base_dir,freeze_path)
    coordinates=freeze['development'] if phase=='development' else [[c['video_id'],c['first'],c['last']] for c in freeze['confirmation']]
    tasks=[];x=section.x;producer=section.producer
    correction_reserve=x.provider.reserved_usd(x.requests.DEEPINFRA_BINDING_FEEDBACK_VERSION+'-stream-v1')
    for window in section.windows(inv,coordinates):
        spec=producer.local_enum_transport(x.provider.streaming_request(producer.request(window,
            unit_ranges=True,condition_attachments=True,response_conditions=True)))
        spec=producer.reasoning_request(spec)
        reserved=x.requests.request_reservation(spec)+correction_reserve+x.requests.reservation('source_verification')
        if reserved>Decimal('.50'):raise ValueError('Source batch exceeds fifty cents')
        tasks.append(dict(id=window.id,window=asdict(window),request=asdict(spec),
            reserved_usd=str(reserved),maximum_paid_attempts=5))
    goal=dict(freeze=dict(path=str(Path(freeze_path).resolve()),sha256=file_hash(freeze_path)),
        phase=phase,module_sha256=file_hash(__file__),semantic_revision=1,
        documented_failure='Existing response strings omit immediately explained response content and restrictions retained elsewhere in the binding. Correctness question and .90 gates unchanged.')
    if implementation_freeze:
        goal['implementation_freeze']=dict(path=str(Path(implementation_freeze).resolve()),sha256=file_hash(implementation_freeze))
    limit=f"{len(tasks)} {phase} windows in three previously exposed recordings; independently coordinate-selected confirmation is not untouched material. Local selected points only; no frequency, ministry-wide trait, benchmark distance or production admission."
    p=dict(version=section.VERSION,base_dir=str(Path(base_dir).resolve()),profile=inv['selected_profile'],
        inventory_fingerprint=inv['content_fingerprint'],source_identity=[{k:s[k] for k in ('video_id','title','url','source_path','source_sha256','gate')} for s in inv['sermons']],
        coverage={**inv['coverage'],'selected_windows':len(tasks),'selection_role':phase},tasks=tasks,
        acceptance_authorization=ref,budget=dict(spend_root=auth['spend_root'],cumulative_ceiling_usd=auth['cumulative_ceiling_usd'],
            starting_conservative_usd=auth['starting_conservative_usd'],additional_usd='5',maximum_batch_usd='.50',
            support_reservation_usd='1.25',maximum_sequence_reservation_usd=str(sum((Decimal(t['reserved_usd']) for t in tasks),Decimal('1.25')))),
        policy=dict(semantic_iterations=3,mechanical_corrections=1,semantic_retries=0,maximum_source_windows=len(tasks),automatic_expansion=False,production_admission='not_admitted'),
        source_feedback_headroom=dict(maximum_input_cap=131072,maximum_corrections=1,maximum_correction_reservation_usd=str(correction_reserve)),
        dimension_contract=producer.DIMENSION_VERIFICATION_VERSION,response_conditions_goal=goal,
        limitation=limit,unknowns=['Unrecovered points within selected windows and responses elsewhere',
            'Ministry-wide frequency, stability, listener uptake and benchmark comparison'],code_identity=section.identity())
    p['input_fingerprint']=digest(p)
    dest=Path(base_dir)/'evaluation'/VERSION/freeze['fingerprint']/phase/p['input_fingerprint']
    Store(dest).write_immutable('plan.json',p)
    return dict(plan=str(dest/'plan.json'),input_fingerprint=p['input_fingerprint'],phase=phase,
        source_batches=[{k:t[k] for k in ('id','reserved_usd','maximum_paid_attempts')} for t in tasks],provider_calls=0)


def lock_implementation(plan):
    p,root=section.load(plan)
    if p['response_conditions_goal']['phase']!='development':raise ValueError('Lock development implementation only')
    value=dict(version=VERSION,code_identity=section.identity(),module_sha256=file_hash(__file__),
        development_plan=dict(path=str(Path(plan).resolve()),sha256=file_hash(plan)),
        confirmation_freeze=p['response_conditions_goal']['freeze'],
        policy='No semantic changes after this lock; confirmation outputs reviewed unchanged.')
    Store(root).write_immutable('implementation-freeze.json',value)
    return dict(implementation_freeze=str(root/'implementation-freeze.json'),provider_calls=0)


def sample_record(p,root,record):
    """Literal union of qualified descriptions, never a scalar or reclassification."""
    by_id={o['id']:o for o in record['machine_observations']}; findings=[];opportunities=[]
    for t in p['tasks']:
        result=json.loads((root/'sources'/t['id']/'result.json').read_text())
        ids=[o['id'] for o in result['observations']]
        opportunities.append(dict(window_id=t['id'],video_id=t['window']['video_id'],
            source_sha256=t['window']['source_sha256'],selection_role=p['response_conditions_goal']['phase'],
            inspection_state=result['status'],recovery_state=result['source_status'],observation_ids=ids,
            absence_proven=False))
    for row in record['dimension_findings']:
        if row['field']!='requested_response':continue
        o=by_id[row['observation_id']];wid=o['source_refs'][0]['window_id']
        findings.append(dict(observation_id=o['id'],requested_response=row['value'],
            eligibility='qualified' if row['eligible'] else 'withheld',
            qualification_scope='Exact self-contained requested_response only; other binding fields are proposals.',
            source_refs=deepcopy(o['source_refs']),proof_refs=record['dimension_packets'][wid],
            gate_diagnostics=row['checks'],verification_request=row['verification_request']))
    eligible=[r['observation_id'] for r in findings if r['eligibility']=='qualified']
    return dict(contract=VERSION,meaning='Specific requested or described response with its attached meaning-changing restrictions and speech status.',
        sample=dict(profile_id=p['profile']['id'],membership_fingerprint=p['profile']['membership_fingerprint'],
            selection_role=p['response_conditions_goal']['phase'],window_ids=[t['id'] for t in p['tasks']],
            selection_freeze=p['response_conditions_goal']['freeze'],scope=p['limitation']),
        opportunities=opportunities,findings=findings,
        aggregation=dict(rule='literal_source_union',eligible_finding_ids=eligible,score=None,
            comparison_status='abstain',reason='Local descriptions are not a validated comparable pastor scale.',
            denominator=None,opportunity_unit='Frozen window inspection; two-point cap is not exhaustive enumeration.',
            probability_is_score=False),
        missingness=dict(unassessed='No completed source result',withheld='Proposed response not qualified; not source absence',
            saturated='Additional unrecovered points; no exhaustive denominator',unknown_is_zero=False),
        production_admission='not_admitted')
