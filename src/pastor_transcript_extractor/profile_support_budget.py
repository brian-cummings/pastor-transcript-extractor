"""Explicit goal allowance; historical packets retain their original dollar guard."""
from decimal import Decimal
import json
from pathlib import Path
from .profile_support_validation import file_hash

VERSION='profile-support-additional-allowance-v1'
VERSION_V2='profile-support-additional-allowance-v2'
VERSION_V3='profile-support-response-conditions-allowance-v3'


def ceiling(packet):
    ref=packet.get('acceptance_authorization')
    if ref is None:return Decimal('1')
    path=Path(ref['path'])
    if file_hash(path)!=ref['sha256']:raise ValueError('Acceptance allowance changed')
    authorization=json.loads(path.read_text());start=Decimal(authorization['starting_conservative_usd']);extra=Decimal(authorization['additional_usd'])
    maximum=Decimal(5) if authorization['version']==VERSION_V3 else Decimal(3) if authorization['version']==VERSION_V2 else Decimal(2)
    if (authorization['version'] not in (VERSION,VERSION_V2,VERSION_V3) or not start.is_finite() or start<0
        or not extra.is_finite() or not 0<extra<=maximum
        or authorization['spend_root']!=packet['budget']['spend_root']
        or file_hash(authorization['objective']['path'])!=authorization['objective']['sha256']):raise ValueError('Invalid goal allowance authorization')
    active=Path(authorization['spend_root'])/'active-profile-support-allowance.json'
    if active.exists():
        if json.loads(active.read_text())['authorization']!=ref:raise ValueError('Goal allowance superseded; historical receipts remain readable')
    elif authorization['version'] in (VERSION_V2,VERSION_V3):raise ValueError('New goal allowance is not active')
    limit=start+extra
    if Decimal(packet['budget']['cumulative_ceiling_usd'])!=limit:raise ValueError('Goal ceiling differs from authorization')
    return limit


def authorize_readiness(base_dir,objective,previous):
    """Activate this user-authorized $3 goal once; supersede unused prior credit."""
    from . import profile_analysis_support_execution as x
    from .pastor_evidence import digest,EvidenceArtifactStore as Store
    import os
    objective=Path(objective).resolve();previous=Path(previous).resolve()
    objective_ref=dict(path=str(objective),sha256=file_hash(objective));prior_ref=dict(path=str(previous),sha256=file_hash(previous))
    prior=json.loads(previous.read_text());spend_root=Path(prior['spend_root'])
    if spend_root.resolve()!=(x.build_paths(base_dir).evaluation/'qualified-observations').resolve():raise ValueError('Allowance spend root differs')
    root=x.build_paths(base_dir).evaluation/'profile-support-readiness-v1'/digest(objective_ref)
    active=spend_root/'active-profile-support-allowance.json'
    with x.supervised.cumulative_history(dict(budget=dict(spend_root=str(spend_root))),root/'baseline') as history:
        if (root/'allowance.json').exists():
            value=json.loads((root/'allowance.json').read_text())
            if value['objective']!=objective_ref or value['supersedes']!=prior_ref:raise ValueError('Existing readiness allowance differs')
        else:
            if active.exists() and json.loads(active.read_text())['authorization']!=prior_ref:raise ValueError('Another active goal must be explicitly superseded')
            starting=x.supervised.BASELINE_SPEND+sum((cost for _,cost in history),Decimal(0))
            value=dict(version=VERSION_V2,objective=objective_ref,supersedes=prior_ref,starting_conservative_usd=str(starting),additional_usd='3',cumulative_ceiling_usd=str(starting+3),maximum_batch_usd='.50',spend_root=str(spend_root),snapshot=[dict(account=a,conservative_usd=str(c)) for a,c in history])
            Store(root).write_immutable('allowance.json',value)
        ref=dict(path=str(root/'allowance.json'),sha256=file_hash(root/'allowance.json'))
        if active.exists() and json.loads(active.read_text())['authorization'] not in (prior_ref,ref):raise ValueError('Readiness allowance is no longer active')
        temporary=active.with_suffix('.tmp');temporary.write_text(json.dumps(dict(authorization=ref,supersedes=prior_ref),indent=2));os.replace(temporary,active)
    return ref,value
