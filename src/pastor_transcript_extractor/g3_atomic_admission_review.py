"""Read-only consistency check for an authored proposal, not an A1 admission gate.

Only the unchanged V4 gate is replayed. No A1 policy/witness acceptance, item
construction, semantic inference, provider execution or artifact writes exist here.
"""
from __future__ import annotations

from pastor_transcript_extractor import evidence_supply_boundary_v4_audit as audit
from pastor_transcript_extractor.sermon_g3_feasibility_review import ACTS, questions

ROOT = audit.panel.old.frozen.ROOT
HERE = ROOT / 'docs/review-proposals/g3-atomic-admission-v1'
PROPOSAL = HERE / 'proposal-a1.json'
POSITIVE_CONTROLS = {
    'B4-R018': ('G3_current_preacher_act', ['challenge', 'invitation']),
    'B4-R053': ('G3_reported_local_act', ['reassurance', 'challenge']),
}
PINNED_FILES = {
    'docs/review-proposals/evidence-supply-boundary-v4/' + name for name in (
        'source-audit-v4.json', 'source-review-v4.json', 'source-review-acceptance-v4.json',
        'acceptance-decision-v4.json', 'input-v4.json', 'execution-authorization-v4.json')
} | {
    'src/pastor_transcript_extractor/' + name for name in (
        'evidence_boundary_admission.py', 'evidence_supply_boundary_v4.py',
        'sermon_g3_feasibility_review.py', 'sermon_g3_feasibility_revision.py')
}


def validate_design(proposal, report):
    """Check authored evidence exhibits and assessment coverage, not admit items.

    Semantic completeness remains an authored source judgment. The hard-coded two
    controls prevent this verifier from implying new authority through a generic
    delete-boundary-reason algorithm.
    """
    decision = audit.accepted_decision(report)
    if (not decision or proposal['parent_input_fingerprint'] != report['input_fingerprint']
            or proposal['parent_audit_fingerprint'] != report['content_fingerprint']
            or proposal['parent_decision_fingerprint'] != decision['content_fingerprint']
            or proposal['accepted_v4_decisions'] != dict(raw_semantic='FAIL', containment='HOLD')):
        raise ValueError('Proposal/accepted V4 evidence binding changed')
    if (proposal['status'] != 'PROPOSAL_ONLY'
            or proposal['authorization'] != dict(review_proposal=True, implementation=False,
                provider_calls=False, new_semantic_run=False, claim_review_acceptance=False,
                discovery_collection_projection=False)
            or proposal['selected_probability_threshold'] != .80
            or proposal['shared_boundary_question'] != questions()['boundary']
            or proposal['proposed_policy_version'] != 'g3-atomic-admission-a1'
            or proposal['proposed_item_version'] != 'reviewed-atomic-local-evidence-a1'
            or proposal['proposed_witness_version'] != 'receipt-bound-atomic-act-sufficiency-a1'
            or not proposal['guardrails'] or not all(v is True for v in proposal['guardrails'].values())):
        raise ValueError('Proposal scope, versions or frozen semantics changed')
    if set(proposal['pins']) != PINNED_FILES:
        raise ValueError('Missing pinned evidence/guard/question identity')
    for name, digest in proposal['pins'].items():
        if audit.panel.old.frozen.v1.file_hash(ROOT / name) != digest:
            raise ValueError('Pinned evidence/guard/question changed')
    if [r['case_id'] for r in proposal['records']] != [r['case_id'] for r in report['records']]:
        raise ValueError('Missing, duplicate or reordered design case')
    for row, original in zip(proposal['records'], report['records'], strict=True):
        boundary = next({k: f[k] for k in ('decision', 'raw_choice', 'selected_probability', 'confidence')}
                        for f in original['fields'] if f['field'] == 'boundary')
        if (row['measurement_fingerprint'] != original['measurement_fingerprint']
                or row['capability'] != original['capability']
                or row['original_admission'] != original['admission'] or row['original_boundary'] != boundary):
            raise ValueError('Original V4 measurements or quarantines changed')
        residual = [x for x in original['admission']['reasons']
                    if not (original['capability'] == 'G3' and x == 'raw_boundary_not_sufficient')]
        if row['unchanged_blockers'] != residual:
            raise ValueError('Non-boundary blocker lost')
        if row['case_id'] not in POSITIVE_CONTROLS:
            expected = 'G2_existing_admission_unchanged' if original['admission']['item'] else 'remains_blocked'
            if (row['proposed_disposition'] != expected or row['claim_sufficiency_exhibit'] is not None
                    or row['proposed_acts'] or row['proposed_namespace'] is not None):
                raise ValueError('Unsupported expansion beyond authored controls')
            if expected == 'remains_blocked' and not residual:
                raise ValueError('Blocked case lacks an unchanged reason')
            continue
        namespace, acts = POSITIVE_CONTROLS[row['case_id']]
        witness = row['claim_sufficiency_exhibit']
        case = original['frozen_case']
        measured = {f['field']: f for f in original['fields']}
        observed = {act for act in ACTS if measured[act]['decision'] == 'observed'}
        if (residual or original['admission']['reasons'] != ['raw_boundary_not_sufficient']
                or row['proposed_disposition'] != 'eligible_only_after_separate_policy_and_claim_review_acceptance'
                or row['proposed_namespace'] != namespace or row['proposed_acts'] != acts
                or set(acts) != observed or not observed <= set(original['witness_facts']['supported_acts'])
                or any(measured[k]['selected_probability'] < .80 for k in (*acts, 'voice', 'addressee', 'adoption'))
                or witness['status'] != 'PROPOSED_NOT_ADMISSION_AUTHORITY' or witness['scope'] != 'atomic_act_only'
                or witness['exact_utterance'] != case['candidate']['act_target']
                or witness['source_envelope'] != case['source_envelope']
                or witness['source_support'] != original['source_excerpt']
                or witness['provenance'] != {k: original['witness_facts'][k] for k in ('origin', 'voice', 'addressee', 'adoption')}
                or not all(witness[k] is True for k in ('complete_for_each_exported_act',
                    'no_omitted_act_or_qualifier_required', 'context_used_only_for_identity_stance_and_interpretation'))
                or witness['circumstance_claim'] is not None or not witness['rationale']):
            raise ValueError('Claim-scoped control exhibit changed or unsupported')
    future = proposal['future_validation']
    if (future['status'] != 'NOT_AUTHORIZED' or future['provider_requests'] != 0
            or future['mode'] != 'prospective_policy_replay_of_existing_receipts_only'
            or future['cases'] != 24 or future['receipts'] != 37
            or future['positive_controls'] != list(POSITIVE_CONTROLS)):
        raise ValueError('Prospective validation scope changed')


def verify(base_dir=None):
    report = audit.verify(base_dir)  # Only the existing frozen V4 admission/consumer.
    proposal = audit.gate.sealed(PROPOSAL)
    validate_design(proposal, report)
    return proposal
