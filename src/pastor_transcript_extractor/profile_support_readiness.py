"""Bounded readiness checks; historical acceptance artifacts remain immutable."""
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
import json
from . import profile_analysis_support_execution as x
from . import profile_support_budget as budget
from .profile_support_validation import file_hash

VERSION='profile-support-readiness-v1'


def code_identity():
    return {m.__name__:file_hash(m.__file__) for m in (x,x.core,x.requests,x.provider,x.correction,x.diagnostics,x.streaming,x.supervised,x.supervised.check.demo,budget)}|{__name__:file_hash(__file__)}


def prepare(prior_acceptance,objective,base_dir):
    prior=Path(prior_acceptance).resolve();objective=Path(objective).resolve()
    ref,authorization=budget.authorize_readiness(base_dir,objective,prior/'allowance.json');root=Path(ref['path']).parent
    work=json.loads((root/'work-plan.json').read_text())
    if work['objective']!=authorization['objective'] or work['starting_conservative_usd']!=authorization['starting_conservative_usd']:raise ValueError('Frozen work plan baseline differs')
    old=json.loads((prior/'plan.json').read_text());results=json.loads((prior/'whole-profile/results.json').read_text())
    blocked=[r for r in results['results'] if r.get('correction_blocked') and not any('correction_of' in json.loads(Path(q['receipt']).read_text())['request']['source_identity'] for q in r.get('rounds',[]))]
    if len(blocked)!=1:raise ValueError('Expected exactly one demonstrated unattempted capacity correction')
    row=blocked[0];task=next(t for t in old['tasks'] if t['claim_id']==row['claim_id']);item=next(i for i in old['plan']['items'] if i['claim_id']==row['claim_id']);spec=x.requests.RequestSpec(**task['request'])
    receipt=x._cached(spec,x._store(dict(budget=dict(spend_root=authorization['spend_root'])),spec))
    checked=x._row(item,spec,receipt,x.requests.ReceiptStore(Path(row['receipt']).parent.parent),cached=True)
    policy=x.correction.policy(spec,headroom=True)
    # Preflight the complete saved answer and diagnostics before any send; this
    # freezes expanded capacity without changing the original source request.
    revised=x.correction.request(spec,receipt['response']['output'],checked['validation_errors'],policy)
    plan={**old['plan'],'items':[item], 'selection':dict(mode='correction_capacity_readiness',assembled_total=len(old['plan']['items']))}
    packet=dict(version=VERSION,plan=plan,tasks=[dict(claim_id=item['claim_id'],request=asdict(spec),token_account=spec.preflight(),correction=policy)],profile_input=old['profile_input'],acceptance_authorization=ref,
        lineage=dict(prior_acceptance=str(prior),initial_receipt=dict(path=row['receipt'],sha256=file_hash(row['receipt'])),prior_results_sha256=file_hash(prior/'whole-profile/results.json')),
        preview_correction=dict(request=asdict(revised),token_account=revised.preflight()),code_identity=code_identity(),
        budget=dict(max_usd='.50',reserved_usd=policy['reserved_usd'],maximum_paid_attempts=max(t['runtime_identity'].get('stream_recovery',{}).get('maximum_attempts',1) for t in policy['allowed_tiers']),spend_root=authorization['spend_root'],cumulative_ceiling_usd=authorization['cumulative_ceiling_usd']))
    packet['input_fingerprint']=x.digest(packet);out=root/'capacity'/packet['input_fingerprint'];x.Store(out).write_immutable('input.json',packet)
    return dict(status='PREPARED_NO_EXECUTION',input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],initial_request_unchanged=True,original_input_cap=spec.runtime_identity['input_cap'],correction_input_cap=revised.runtime_identity['input_cap'],regression_inputs=str(root/'regression-inputs.json'),generation_calls=0)


def run(path,*,approve_input,check_only=False,transport=None,progress=None):
    path=Path(path);p=json.loads(path.read_text())
    if p['input_fingerprint']!=x.digest({k:v for k,v in p.items() if k!='input_fingerprint'}) or approve_input!=p['input_fingerprint']:raise ValueError('Exact frozen readiness approval required')
    if p['code_identity']!=code_identity():raise ValueError('Readiness implementation changed after freeze')
    if Decimal(p['budget']['reserved_usd'])>Decimal('.50'):raise ValueError('Readiness batch exceeds fifty cents')
    budget.ceiling(p)
    if file_hash(p['profile_input']['path'])!=p['profile_input']['sha256']:raise ValueError('Readiness profile changed')
    current=x.core.build_plan(x.core.read_record(p['profile_input']['path']));current={i['claim_id']:i for i in current['items']}
    if any(current.get(i['claim_id'])!=i for i in p['plan']['items']):raise ValueError('Readiness source/evidence changed')
    ref=p['lineage']['initial_receipt']
    if file_hash(ref['path'])!=ref['sha256']:raise ValueError('Readiness initial receipt changed')
    if check_only:return dict(status='CHECKED_NO_EXECUTION',budget=p['budget'],generation_calls=0)
    if transport is None and not x.provider.credential_present():raise ValueError('DEEPINFRA_API_KEY required')
    return x.recipe(p,path.parent,transport or x.provider.transport,progress=progress)
