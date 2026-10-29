"""Frozen whole-profile acceptance batches over the existing execution adapter.

No new inference semantics, source selection, model, or production authority.
"""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
import json
from . import profile_analysis_support_execution as x
from . import profile_support_budget as guard
from .profile_support_validation import file_hash,source_packet

VERSION='profile-support-acceptance-v1'
CRITERIA=dict(
    contract='Every attempted answer must meet the unchanged schema and literal/source checks; unknowns and failures remain visible.',
    semantic='Review all statements against their complete supplied sources: proposition, attribution, actual/projected voice, adoption, polarity, conditions, qualifications, scope, comparative strength and counterevidence. Any consequential unsupported assertion blocks whole-profile acceptance.',
    omissions='Separately read the full declared three-sermon sample, not just selected citations. Record consequential topics, exceptions and contrary examples absent from the profile, or explicitly identify unread/unavailable source coverage. Omission safety is unproven without adequate reverse coverage.',
    document='Evaluate proportionate emphasis, illustrative versus recurring claims, uncertainty, dependency propagation and usefulness of the complete handoff. No silent candidate rewrites.',
    holdout='After freezing changes, inspect an existing untouched second profile with compatible observations and source context if available and affordable. No tuning on holdout results.',
    decision='Distinguish contract PASS, reviewed semantic findings, sample coverage, representativeness and production admission. A passed bounded sample is insufficient for production readiness.',
    review_authority='Assistant source review and automated judgments are not independent human validation. Review references never enter runtime requests.',
    iteration='At most two demonstrated-gap implementation iterations; no model switches, confidence tuning, new collection, classification or automatic successor experiment.')


def code_identity():
    return {m.__name__:file_hash(m.__file__) for m in (x,x.core,x.requests,x.provider,x.correction,x.diagnostics,x.streaming,x.supervised,x.supervised.check.demo,guard)}|{__name__:file_hash(__file__)}


def partition(plan,seed_ids,taskmap,cap=Decimal('.45')):
    """Prerequisite closure first; remaining tasks in stable dependency order."""
    items={i['claim_id']:i for i in plan['items']};closure=set();ordered=[];visiting=set()
    def visit(cid):
        if cid in closure:return
        if cid in visiting:raise ValueError('Cyclic profile dependency')
        visiting.add(cid)
        for dep in (items[cid]['case'] or {}).get('dependencies',[]):visit(dep)
        visiting.remove(cid);closure.add(cid);ordered.append(cid)
    for cid in sorted(seed_ids):visit(cid)
    prerequisites=[cid for cid in ordered if cid not in seed_ids and cid in taskmap]
    for cid in sorted(items):visit(cid)
    remaining=[cid for cid in ordered if cid not in seed_ids and cid not in prerequisites and cid in taskmap]
    groups=[]
    for prefix,ids in [('prerequisites',prerequisites),('remaining',remaining)]:
        current=[];cost=Decimal(0);index=1
        for cid in ids:
            task=taskmap[cid];amount=x.requests.request_reservation(x.requests.RequestSpec(**task['request']))+Decimal(task['correction']['reserved_usd'])
            if amount>cap:raise ValueError('Single acceptance case exceeds batch ceiling')
            if current and cost+amount>cap:
                groups.append(dict(id=f'{prefix}-{index:02d}',claim_ids=current,reserved_usd=str(cost)));index+=1;current=[];cost=Decimal(0)
            current.append(cid);cost+=amount
        if current:groups.append(dict(id=f'{prefix}-{index:02d}',claim_ids=current,reserved_usd=str(cost)))
    return groups


def prepare(seed_run,objective,base_dir):
    seed_run=Path(seed_run).resolve();seed=source_packet(seed_run);objective=Path(objective).resolve()
    profile=Path(seed['profile_input']['path']);record=x.core.read_record(profile);plan=x.core.build_plan(record)
    if file_hash(profile)!=seed['profile_input']['sha256']:raise ValueError('Seed profile changed')
    prior={i['claim_id']:i for i in seed['plan']['items']};tasks=[]
    for item in plan['items']:
        if item['claim_id'] in prior and item['case']!=prior[item['claim_id']]['case']:raise ValueError('Seed case changed')
        if item['case'] is None:continue
        spec=x.make_request(item['case']);tasks.append(dict(claim_id=item['claim_id'],request=asdict(spec),token_account=spec.preflight(),correction=x.correction.policy(spec)))
    taskmap={t['claim_id']:t for t in tasks}
    for task in seed['tasks']:
        if task['request']!=taskmap[task['claim_id']]['request']:raise ValueError('Seed request changed; no paid cache replacement authorized')
        spec=x.requests.RequestSpec(**task['request']);receipt=x._cached(spec,x._store(seed,spec))
        if receipt is None or receipt['halt']:raise ValueError('Seed receipt unavailable')
    objective_ref=dict(path=str(objective),sha256=file_hash(objective))
    # One immutable allowance per user goal, even when preparation is repeated
    # after spending. Repreparation must never mint another $2 credit.
    root=x.build_paths(base_dir).evaluation/VERSION/x.digest(objective_ref)
    if (root/'allowance.json').exists():
        authorization=json.loads((root/'allowance.json').read_text())
        if authorization['objective']!=objective_ref or authorization['spend_root']!=seed['budget']['spend_root']:raise ValueError('Existing goal allowance differs')
        starting=Decimal(authorization['starting_conservative_usd'])
    else:
        with x.supervised.cumulative_history(seed,seed_run/'allowance-snapshot') as history:
            starting=x.supervised.BASELINE_SPEND+sum((cost for _,cost in history),Decimal(0))
            snapshot=[dict(account=account,conservative_usd=str(cost)) for account,cost in history]
        authorization=dict(version=guard.VERSION,starting_conservative_usd=str(starting),additional_usd='2',cumulative_ceiling_usd=str(starting+2),spend_root=seed['budget']['spend_root'],objective=objective_ref,snapshot=snapshot)
        x.Store(root).write_immutable('allowance.json',authorization)
    packet=dict(version=VERSION,profile_input=seed['profile_input'],plan=plan,tasks=tasks,seed_run=str(seed_run),seed_input_sha256=file_hash(seed_run/'input.json'),seed_results_sha256=file_hash(seed_run/'results.json'),criteria=CRITERIA,batches=partition(plan,set(prior),taskmap),code_identity=code_identity(),acceptance_authorization=dict(path=str(root/'allowance.json'),sha256=file_hash(root/'allowance.json')))
    packet['input_fingerprint']=x.digest(packet);x.Store(root).write_immutable('plan.json',packet)
    (root/'acceptance-plan.md').write_text('# Frozen whole-profile acceptance plan\n\n'+json.dumps(dict(criteria=CRITERIA,batches=packet['batches'],allowance={k:v for k,v in authorization.items() if k!='snapshot'}),indent=2)+'\n\nNo paid calls at preparation. Exact seed requests are retained; no reference answers enter runtime.\n')
    return dict(status='FROZEN_NO_EXECUTION',plan=str(root/'plan.json'),plan_fingerprint=packet['input_fingerprint'],statements=len(plan['items']),seed_cases=len(prior),batches=packet['batches'],starting_conservative_usd=str(starting),additional_usd='2',cumulative_ceiling_usd=str(starting+2))


def load(path):
    path=Path(path);p=json.loads(path.read_text())
    if p['input_fingerprint']!=x.digest({k:v for k,v in p.items() if k!='input_fingerprint'}):raise ValueError('Acceptance plan digest differs')
    if p['code_identity']!=code_identity():raise ValueError('Acceptance implementation changed after freeze')
    if file_hash(p['profile_input']['path'])!=p['profile_input']['sha256']:raise ValueError('Acceptance profile changed')
    if x.core.build_plan(x.core.read_record(p['profile_input']['path']))!=p['plan']:raise ValueError('Acceptance evidence changed')
    seed=Path(p['seed_run'])
    if file_hash(seed/'input.json')!=p['seed_input_sha256'] or file_hash(seed/'results.json')!=p['seed_results_sha256']:raise ValueError('Acceptance seed changed')
    return p,path.parent


def run(path,batch_id,*,approve_plan,transport=None,progress=None,check_only=False):
    p,root=load(path)
    if approve_plan!=p['input_fingerprint']:raise ValueError('Exact acceptance plan approval required')
    batch=next((b for b in p['batches'] if b['id']==batch_id),None)
    if batch is None:raise ValueError('Unknown frozen batch')
    authorization=json.loads(Path(p['acceptance_authorization']['path']).read_text());ids=set(batch['claim_ids']);plan=deepcopy(p['plan']);plan['items']=[i for i in plan['items'] if i['claim_id'] in ids];plan['selection']=dict(mode='whole_profile_acceptance_batch',assembled_total=len(p['plan']['items']),batch=batch_id)
    packet=dict(version=x.core.VERSION,plan=plan,tasks=[t for t in p['tasks'] if t['claim_id'] in ids],acceptance_authorization=p['acceptance_authorization'],acceptance_plan_fingerprint=p['input_fingerprint'],budget=dict(max_usd='.45',reserved_usd=batch['reserved_usd'],maximum_paid_attempts=sum(2*t['token_account']['stream_recovery']['maximum_attempts'] for t in p['tasks'] if t['claim_id'] in ids),spend_root=authorization['spend_root'],cumulative_ceiling_usd=authorization['cumulative_ceiling_usd']))
    guard.ceiling(packet);packet['input_fingerprint']=x.digest(packet);out=root/'batches'/batch_id
    if check_only:return dict(status='CHECKED_NO_EXECUTION',batch=batch,budget=packet['budget'])
    if transport is None and not x.provider.credential_present():raise ValueError('DEEPINFRA_API_KEY required')
    x.Store(out).write_immutable('input.json',packet)
    return x.recipe(packet,out,transport or x.provider.transport,progress=progress)


def assemble(path):
    p,root=load(path);rows={r['claim_id']:r for r in json.loads((Path(p['seed_run'])/'results.json').read_text())['results']}
    for batch in p['batches']:
        path=root/'batches'/batch['id']/'results.json'
        if not path.exists():raise ValueError('Batch not completed: '+batch['id'])
        report=json.loads(path.read_text())
        for row in report['results']:
            if row['claim_id'] in rows:raise ValueError('Duplicate acceptance claim')
            rows[row['claim_id']]=row
    taskmap={t['claim_id']:t for t in p['tasks']};items={i['claim_id']:i for i in p['plan']['items']}
    for cid,row in rows.items():
        if row.get('receipt'):
            receipt=json.loads(Path(row['receipt']).read_text());spec=x.requests.RequestSpec(**receipt['request']);base=x.requests.RequestSpec(**taskmap[cid]['request']);target=x.requests.ReceiptStore(Path(row['receipt']).parent.parent)
            if spec!=base:
                initial=x._cached(base,x._store(dict(budget=dict(spend_root=json.loads(Path(p['acceptance_authorization']['path']).read_text())['spend_root'])),base))
                checked=x._row(items[cid],base,initial,target,cached=True)
                if spec!=x.correction.request(base,initial['response']['output'],checked['validation_errors'],taskmap[cid]['correction']):raise ValueError('Foreign correction in assembly')
            verified=x._row(items[cid],spec,x._cached(spec,target),target,cached=True)
            if verified['judgment']!=row.get('judgment') or verified['status']!=row['status']:raise ValueError('Saved acceptance result differs')
    ordered=[]
    for item in p['plan']['items']:
        cid=item['claim_id']
        if cid not in rows:
            if item['gap'] is None:raise ValueError('Missing acceptance case: '+cid)
            rows[cid]=dict(claim_id=cid,status='unresolved',judgment=None,receipt=None)
        ordered.append(rows[cid])
    doc=x.core.document_input(p['plan'],ordered);out=root/'whole-profile';x.Store(out).write_immutable('document-input.json',doc);(out/'analysis-support.md').write_text(x.core.render_handoff(doc))
    report=dict(status='INCONCLUSIVE',execution_status='ASSEMBLED_WITHOUT_GENERATION',plan_fingerprint=p['input_fingerprint'],coverage=doc['coverage'],results=ordered,production_admission='not_admitted')
    x.Store(out).write_immutable('results.json',report)
    return dict(status=report['status'],coverage=doc['coverage'],document_input=str(out/'document-input.json'),generation_calls=0)
