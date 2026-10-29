"""Mechanical feedback for profile support; never authors semantic repairs."""
from . import evidence_requests as requests
from . import profile_analysis_support as core
from . import reading_diagnostics as diagnostics

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


def policy(spec):
    return dict(version=VERSION,maximum_corrections=1,template=TEMPLATE,
        reserved_usd=str(requests.request_reservation(spec)),
        overflow='Stop without truncation or a larger request tier',
        eligible='Complete, accounted responses failing JSON/schema/literal contract validation only')


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
    if frozen!=policy(spec):raise ValueError('Frozen contract correction policy differs')
    if spec.source_identity.get('contract_correction_policy')!=VERSION or spec.source_identity.get('correction_of'):
        raise ValueError('Only one newly frozen profile contract correction permitted')
    return requests.corrective_request(spec,output,errors,frozen['template'])
