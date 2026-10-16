"""Read the final bounded A1 decision without replaying a closed panel."""
from pastor_transcript_extractor import g3_atomic_admission as a1
from pastor_transcript_extractor import g3_atomic_admission_review as design

HERE = design.HERE
DECISION = HERE / 'acceptance-decision-a1.json'


def accepted_decision():
    if not DECISION.exists():
        return None
    decision = a1.v4.sealed(DECISION)
    audit_path = HERE / 'source-audit-a1.json'
    report = a1.v4.sealed(audit_path)
    if (decision['audit_fingerprint'] != report['content_fingerprint']
            or decision['audit_sha256'] != a1.file_hash(audit_path)
            or decision['input_fingerprint'] != report['input_fingerprint']
            or decision['result_fingerprint'] != report['result_fingerprint']
            or decision['status'] != 'PASS' or decision['closed'] is not True
            or decision['scope'] != 'bounded_reviewed_atomic_local_development_panel_only'
            or decision['further_panel_replay_authorized'] is not False
            or decision['semantic_experiments_authorized'] is not False
            or decision['v4_decisions'] != dict(raw_semantic='FAIL', containment='HOLD')
            or report['recommendation'] != 'PASS' or report['unsupported_admitted'] != 0
            or report['unresolved_admitted'] != 0 or report['admitted'] != 4 or report['quarantined'] != 20):
        raise ValueError('Invalid final bounded A1 decision binding')
    return decision
