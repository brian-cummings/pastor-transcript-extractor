"""Frozen synthetic whole-statement checks over the production support client.

Reference judgments are read only by report(), after execution; never by requests.
"""
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
import json
from . import profile_support_readiness as readiness
from . import profile_analysis_support_execution as x

VERSION='profile-support-whole-statement-regression-v1'


def case(row):
    if set(row)!={'id','candidate','scope','source'}:raise ValueError('Runtime regression row must contain no reference judgments')
    texts=dict(target_text=row['source'],leading_context='',trailing_context='')
    window=x.core.evidence.SourceWindow(row['id'],0,0,x.digest(texts),1,
        (dict(block_id=1,target_text=row['source'],start_seconds=0,end_seconds=60,segment_indexes=[0]),),'synthetic_support_regression')
    source=dict(window=json.loads(json.dumps(asdict(window))),texts=texts,fields=x.core._inventory(window,texts),context_sha256=x.core.context_digest(texts))
    candidate=dict(id=row['id'],statement=row['candidate'],scope=dict(meaning=row['scope']),declared_caveats={})
    state=dict(candidate=candidate,sample=dict(profile_id=0,video_ids=[0],coverage='Synthetic excerpt only'),
        measurement_ledger=dict(rows=[],contracts=[],meaning='No measured frequency, ranking or audience outcomes.'),
        passages=[dict(passage_id=row['id'],fields={k:[dict(id=u['id'],text=u['text']) for u in v] for k,v in source['fields'].items()})],
        bound_observations=[],upstream_points=[],stored_aggregates=[],upstream_aggregate_claims=[],aggregation_contract='No aggregation supplied')
    return dict(state=state,sources={row['id']:source},dependencies=[],input_ids={},identity=dict(profile_id=0))


def prepare(root):
    root=Path(root);ref=root/'allowance.json';authorization=json.loads(ref.read_text())
    runtime=root/'regression-inputs.json';rows=json.loads(runtime.read_text())
    if len(rows)!=12 or len({r['id'] for r in rows})!=12:raise ValueError('Expected twelve pre-frozen distinct regression cases')
    batches=[]
    for start in range(0,len(rows),3):
        items=[];tasks=[]
        for row in rows[start:start+3]:
            c=case(row);spec=x.make_request(c,whole_statement=True)
            items.append(dict(claim_id=row['id'],statement=row['candidate'],scope=c['state']['candidate']['scope'],declared_caveats={},case=c,gap=None))
            tasks.append(dict(claim_id=row['id'],request=asdict(spec),token_account=spec.preflight(),correction=x.correction.policy(spec,headroom=True)))
        reserve=sum((x.requests.request_reservation(x.requests.RequestSpec(**t['request']))+Decimal(t['correction']['reserved_usd']) for t in tasks),Decimal(0))
        if reserve>Decimal('.50'):raise ValueError('Regression batch reservation exceeds fifty cents')
        packet=dict(version=VERSION,plan=dict(profile=dict(id=0),items=items,known_gaps=[],selection=dict(mode='frozen_synthetic_regression',assembled_total=12)),tasks=tasks,
            acceptance_authorization=dict(path=str(ref),sha256=readiness.file_hash(ref)),
            runtime_input=dict(path=str(runtime),sha256=readiness.file_hash(runtime)),
            code_identity=readiness.code_identity()|{__name__:readiness.file_hash(__file__)},
            budget=dict(max_usd='.50',reserved_usd=str(reserve),maximum_paid_attempts=sum(t['token_account'].get('stream_recovery',{}).get('maximum_attempts',1)+max(v['runtime_identity'].get('stream_recovery',{}).get('maximum_attempts',1) for v in t['correction']['allowed_tiers']) for t in tasks),spend_root=authorization['spend_root'],cumulative_ceiling_usd=authorization['cumulative_ceiling_usd']))
        packet['input_fingerprint']=x.digest(packet);out=root/'regression'/packet['input_fingerprint'];x.Store(out).write_immutable('input.json',packet)
        batches.append(dict(input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],ids=[r['claim_id'] for r in items],budget=packet['budget']))
    manifest=dict(version=VERSION,batches=batches,runtime_input=dict(path=str(runtime),sha256=readiness.file_hash(runtime)),reference_policy='Evaluation only; never a runtime request input',generation_calls=0)
    x.Store(root).write_immutable('regression-plan.json',manifest)
    return manifest


def run(path,approve_input,*,check_only=False,transport=None,progress=None):
    path=Path(path);packet=json.loads(path.read_text())
    if packet['input_fingerprint']!=x.digest({k:v for k,v in packet.items() if k!='input_fingerprint'}) or approve_input!=packet['input_fingerprint']:raise ValueError('Exact regression approval required')
    if packet['code_identity']!=readiness.code_identity()|{__name__:readiness.file_hash(__file__)}:raise ValueError('Regression implementation changed after freeze')
    if readiness.file_hash(packet['runtime_input']['path'])!=packet['runtime_input']['sha256']:raise ValueError('Frozen regression inputs changed')
    x.budget_guard.ceiling(packet)
    if Decimal(packet['budget']['reserved_usd'])>Decimal('.50'):raise ValueError('Regression batch ceiling exceeded')
    if check_only:return dict(status='CHECKED_NO_EXECUTION',budget=packet['budget'])
    return x.recipe(packet,path.parent,transport or x.provider.transport,progress=progress)


def report(root):
    root=Path(root);plan=json.loads((root/'regression-plan.json').read_text());references={r['id']:r['expected'] for r in json.loads((root/'regression-references.json').read_text())}
    rows=[]
    for batch in plan['batches']:
        out=Path(batch['input']).parent
        if not (out/'results.json').exists():raise ValueError('All frozen regression batches must finish before assessment')
        results=json.loads((out/'results.json').read_text());doc=json.loads((out/'document-input.json').read_text())
        if results['input_fingerprint']!=batch['input_fingerprint']:raise ValueError('Foreign regression result')
        for entry in doc['entries']:
            status=entry['support_status'];expected=references[entry['claim_id']]
            matched=(status!='supported' and status not in ('component_failure','not_run')) if expected=='not_supported_without_qualification' else status==expected
            rows.append(dict(id=entry['claim_id'],expected=expected,actual=status,matched=matched,judgment=entry['judgment'],receipt=entry['receipt']))
    result=dict(status='PASS' if all(r['matched'] for r in rows) else 'FAIL(component)',checks=rows,matched=sum(r['matched'] for r in rows),total=len(rows),limitation='Frozen synthetic diagnostic, not whole-profile accuracy or independent human validation')
    x.Store(root).write_immutable('regression-report.json',result)
    return result
