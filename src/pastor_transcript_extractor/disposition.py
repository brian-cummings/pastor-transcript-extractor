from __future__ import annotations

from typing import Any


ACCEPTED_SERMON = "accepted_sermon"
REVIEW_REQUIRED = "review_required"
REJECTED_NO_SERMON = "rejected_no_sermon"
REJECTED_AMBIGUOUS_SPEAKERS = "rejected_ambiguous_speakers"


def _has_effective_window(sermon_window: object) -> bool:
    if not isinstance(sermon_window, dict):
        return False
    start = sermon_window.get("start_seconds")
    end = sermon_window.get("end_seconds")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)):
        return float(end) > float(start)
    included = sermon_window.get("included_segment_indexes")
    return isinstance(included, list) and any(isinstance(index, int) for index in included)


def build_final_disposition(
    classification: object,
    sermon_window: object,
    *,
    guest_speaker_suspected: bool = False,
    ambiguous_speakers: bool = False,
    recording_verification: object = None,
) -> dict[str, Any]:
    """Derive the user-facing outcome without discarding diagnostic candidates."""
    classification_dict = classification if isinstance(classification, dict) else {}
    confidence = str(classification_dict.get("confidence_tier", "unknown"))
    retained = classification_dict.get("retained_segment_indexes")
    diagnostic_candidate_present = isinstance(retained, list) and bool(retained)
    has_window = _has_effective_window(sermon_window)
    window_source = sermon_window.get("source") if isinstance(sermon_window, dict) else None
    manual_override = window_source == "override"
    verification = (
        recording_verification if isinstance(recording_verification, dict) else {}
    )
    verified_outcome = verification.get("predicted_outcome")
    verification_decision = verification.get("decision")

    if ambiguous_speakers:
        status = REJECTED_AMBIGUOUS_SPEAKERS
        reasons = ["multiple_sustained_speakers_cannot_be_attributed_to_target_pastor"]
    elif verified_outcome == "no_sermon":
        status = (
            REJECTED_AMBIGUOUS_SPEAKERS
            if verification_decision == "multi_speaker_or_student_program"
            else REJECTED_NO_SERMON
        )
        reasons = [f"recording_verifier_{verification_decision}"]
    elif guest_speaker_suspected:
        status = REVIEW_REQUIRED
        reasons = ["guest_speaker_suspected"]
        if manual_override and has_window:
            reasons.append("manual_override_applies_to_content_boundary_only")
    elif manual_override and has_window:
        status = ACCEPTED_SERMON
        reasons = ["manual_content_boundary_override_is_authoritative"]
    elif verified_outcome == "sermon" and has_window:
        status = ACCEPTED_SERMON
        reasons = ["recording_verifier_confirmed_worship_service_sermon"]
    elif not has_window and diagnostic_candidate_present:
        status = REVIEW_REQUIRED
        reasons = ["low_confidence_candidate_not_promoted"]
    elif not has_window:
        status = REJECTED_NO_SERMON
        reasons = ["no_effective_sermon_window"]
    elif not classification_dict:
        status = ACCEPTED_SERMON
        reasons = ["legacy_rule_window_present"]
    elif confidence == "high":
        status = ACCEPTED_SERMON
        reasons = ["high_confidence_effective_sermon_window"]
    else:
        status = REVIEW_REQUIRED
        reasons = [f"{confidence}_confidence_requires_review"]

    return {
        "schema_version": 1,
        "policy_version": "final_disposition_v1",
        "status": status,
        "reason_codes": reasons,
        "confidence_tier": confidence,
        "effective_window_present": has_window,
        "diagnostic_candidate_present": diagnostic_candidate_present,
        "guest_speaker_suspected": guest_speaker_suspected,
        "manual_content_override_present": manual_override,
        "recording_verifier_policy_version": verification.get("policy_version"),
        "recording_verifier_decision": verification_decision,
        "recording_verifier_outcome": verified_outcome,
    }
