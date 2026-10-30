"""Mechanical feedback for profile support; never authors semantic repairs."""
from . import evidence_requests as requests
from . import profile_analysis_support as core
from . import reading_diagnostics as diagnostics
from . import deepinfra_requests as provider
from dataclasses import replace
from decimal import Decimal

VERSION='profile-support-contract-correction-v1'
TEMPLATE='''Return one complete replacement JSON answer to the original profile-support task.
The previous answer failed the mechanical checks listed below. Use the original
complete context and the same schema. Include judgment, evidence, qualifications
and reason. Select only supplied citation IDs. A supported or contradicted answer
needs nonempty source evidence; unresolved may have none. Every qualification
needs source evidence and an explicit preservation status. already_preserved needs
a literal excerpt from the supplied statement, scope or declared_caveats.
Do not delete a necessary qualification, change the candidate or invent evidence
to pass validation. Preserve scope, attribution, adoption, polarity, conditions and
uncertainty. Feedback is not source evidence or a request to change the judgment.
No code-authored correction or semantic approval is supplied. If the source cannot
support a determination, return unresolved under the complete schema.
Return JSON only. This is the single permitted contract correction.
Validation diagnostics:
'''


def policy(spec,*,headroom=False):
    result=dict(version=VERSION,maximum_corrections=1,template=TEMPLATE,
        reserved_usd=str(requests.request_reservation(spec)),
        overflow='Stop without truncation or a larger request tier',
        eligible='Complete, accounted responses failing JSON/schema/literal contract validation only')
    if not headroom:return result
    tiers=[dict(version=spec.version,namespace=spec.namespace,runtime_identity=spec.runtime_identity)]
    for version,runtime in provider.ANALYSIS_SUPPORT_POLICIES.items():
        if runtime['input_cap']<=spec.runtime_identity['input_cap']:continue
        candidate=replace(spec,version=version,namespace=version,runtime_identity=runtime)
        candidate=provider.streaming_request(candidate,whitespace_threshold=spec.runtime_identity.get('stream_recovery',{}).get('whitespace_threshold',256))
        tiers.append(dict(version=candidate.version,namespace=candidate.namespace,runtime_identity=candidate.runtime_identity))
    result.update(version='profile-support-contract-correction-v2',allowed_tiers=tiers,
        reserved_usd=str(max(provider.reserved_usd(t['version']) for t in tiers)),
        overflow='Try only predeclared tiers; stop without truncation if complete feedback exceeds all frozen tiers')
    return result


def inspect(case,output,schema):
    try:value=requests.strict_json(output)
    except ValueError as error:
        return None,[dict(path='$',code='json',message=str(error))]
    errors=diagnostics.shape_errors(value,schema)
    if errors:return None,errors
    try:return core.validate_answer_v2(case,value),[]
    except (ValueError,KeyError,TypeError) as error:
        path='$.evidence' if value['judgment']!='unresolved' and not value['evidence'] else '$'
        return None,[dict(path=path,code='binding',message=str(error))]


def request(spec,output,errors,frozen):
    headroom=frozen.get('version')=='profile-support-contract-correction-v2'
    if frozen!=policy(spec,headroom=headroom):raise ValueError('Frozen contract correction policy differs')
    if spec.source_identity.get('contract_correction_policy')!=VERSION or spec.source_identity.get('correction_of'):
        raise ValueError('Only one newly frozen profile contract correction permitted')
    revised=requests.corrective_request(spec,output,errors,frozen['template'],validate=not headroom)
    if not headroom:return revised
    for tier in frozen['allowed_tiers']:
        candidate=replace(revised,**tier)
        try:candidate.preflight()
        except ValueError as error:
            if 'input exceeds reservation' in str(error) or 'timeout exceeds bounded policy' in str(error):continue
            raise
        if requests.request_reservation(candidate)>Decimal(frozen['reserved_usd']):raise ValueError('Correction exceeds frozen reservation')
        return candidate
    raise ValueError('Complete corrective feedback exceeds all frozen tiers; no truncation')
