"""Read-only replacement-architecture proposal verifier, never a collector."""
from __future__ import annotations
from pastor_transcript_extractor import collector_retrieval_design as old

HERE=old.ROOT/'docs/review-proposals/context-evidence-architecture-v1'
AUTHORITY=dict(architecture_proposal=True,read_only_proposal_verifier=True,
    replacement_implementation=False,context_materialization=False,extractor_execution=False,
    encoder_execution=False,provider_calls=False,fresh_source_selection=False,
    measurement_admission_changes=False,collection=False,projection_scoring=False)


def validate(plan,decision,experiment):
    if (decision['status']!='DESIGN_ONLY_AUTHORIZED' or decision['authorized']!=AUTHORITY
            or decision['accepted']!={'collector_retrieval_V1_1':'DEVELOPMENT_FAIL','G1':'HOLD'}
            or decision['closure']!='CLOSED_NO_FURTHER_DEVELOPMENT_OR_EXECUTION'
            or plan['status']!='PROPOSAL_ONLY' or plan['authorization']!=AUTHORITY
            or plan['decision_fingerprint']!=decision['content_fingerprint']):
        raise ValueError('Design-only authority/closed collector decision changed')
    if (plan['recommendation']!='bounded_context_then_untrusted_extraction_then_frozen_measurement_and_admission'
            or plan['measurement_threshold']!=.80 or plan['context_chars_max']!=6000
            or plan['extractor_selected_now'] is not False
            or plan['new_review_authority_accepted_now'] is not False):
        raise ValueError('Unestablished extractor/admission authority or contract change')
    cases=experiment['cases'];categories={k:sum(c['kind']==k for c in cases) for k in ('adequate','clipped','control')}
    if (experiment['status']!='DESIGN_NOT_MATERIALIZED' or categories!={'adequate':12,'clipped':6,'control':6}
            or len({c['case_id'] for c in cases})!=24
            or any(c.get('source_context') is not None or c.get('gold_targets') is not None for c in cases)
            or experiment['context_materialized_count']!=0 or experiment['provider_requests_made']!=0):
        raise ValueError('Proposed experiment scope/materialization changed')
    routes={r:sum(c['kind']=='adequate' and c['route']==r for c in cases) for r in ('G2','G3_current','G3_reported')}
    if routes!={'G2':4,'G3_current':4,'G3_reported':4}:
        raise ValueError('Route-specific anti-vacuity slate changed')
    bounds=experiment['proposed_limits']
    if (bounds!=dict(requests_max=24,input_tokens_per_request_max=16384,total_input_tokens_max=393216,
                    total_output_tokens_per_request_max=2048,total_output_tokens_max=49152,
                    nominations_per_context_max=4,nominations_total_max=96,active_review_minutes_max=480,automatic_retries=0,
                    automatic_expansions=0,price_ceiling_usd='5.00',model_count=1,prompt_variants=1)
            or any(experiment[k] is not False for k in ('execution_authorized','implementation_authorized','Jev_execution_authorized'))):
        raise ValueError('Prospective bounds or execution hold changed')


def verify():
    decision=old.sealed(HERE/'decision-v1.json');plan=old.sealed(HERE/'proposal-v1.json')
    experiment=old.sealed(HERE/'experiment-v1.json');manifest=old.sealed(HERE/'packet-v1.json')
    validate(plan,decision,experiment)
    if (manifest['proposal_fingerprint']!=plan['content_fingerprint']
            or manifest['experiment_fingerprint']!=experiment['content_fingerprint']):
        raise ValueError('Proposal packet binding changed')
    for name,digest in {**plan['pins'],**manifest['files']}.items():
        path=(old.ROOT/name).resolve()
        if not path.is_relative_to(old.ROOT) or old.file_hash(path)!=digest:
            raise ValueError('Architecture proposal/baseline pin changed: '+name)
    return plan,experiment,manifest
