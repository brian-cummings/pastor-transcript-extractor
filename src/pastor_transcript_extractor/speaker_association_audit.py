from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from pastor_transcript_extractor.disposition import ACCEPTED_SERMON, REVIEW_REQUIRED
from pastor_transcript_extractor.media_artifacts import MediaVerificationCache
from pastor_transcript_extractor.speaker_pair_eligibility import (
    assess_automatic_speaker_observation,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
    select_transcript_grounded_spans,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    SHADOW_ASSOCIATION_VERSION,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.models import SpeakerObservation, utc_now


ASSOCIATION_AUDIT_VERSION = "speaker_association_coverage_v1"
SHADOW_ARTIFACT_KIND = "speaker_profile_shadow_association"
SUCCESSFUL_ATTEMPT_OUTCOMES = frozenset(
    {
        "proposed_match",
        "no_match",
        "ambiguous",
        "insufficient_evidence",
        "conflicting_attribution",
    }
)
STRUCTURAL_GAP_REASONS = frozenset(
    {
        "extraction_unavailable",
        "extraction_artifact_unreadable",
        "extraction_artifact_malformed",
        "disposition_missing_or_malformed",
        "sermon_window_invalid",
        "observation_unavailable",
        "observation_not_current_extraction",
        "observation_window_mismatch",
    }
)


@dataclass(frozen=True, slots=True)
class AssociationAuditResult:
    report_path: Path
    payload: dict[str, Any]

    @property
    def unaccounted_count(self) -> int:
        return int(self.payload["counts"]["unaccounted"])

    @property
    def invalid_artifact_count(self) -> int:
        return int(self.payload["counts"]["invalid_association_artifacts"])

    @property
    def ok(self) -> bool:
        return self.unaccounted_count == 0 and self.invalid_artifact_count == 0


def audit_speaker_association_coverage(
    database: Database,
    *,
    association_root: Path,
    output_root: Path,
    verification_cache: MediaVerificationCache | None = None,
    required_policy_sha256: str | None = None,
    required_model_fingerprint: str | None = None,
) -> AssociationAuditResult:
    """Account for every latest extraction without performing acoustic analysis."""
    attempts_by_observation, invalid_attempt_count = _load_shadow_attempts(
        association_root
    )
    cases: list[dict[str, Any]] = []
    for video in database.list_videos():
        extraction = database.get_latest_extraction_result_for_video(video.id)
        if extraction is None:
            continue
        base = {
            "video_id": video.id,
            "youtube_video_id": video.youtube_video_id,
            "title": video.title,
            "extraction_result_id": extraction.id,
            "extraction_artifact_path": extraction.proposed_json_path,
        }
        status, disposition_reason = _read_content_disposition(
            extraction.proposed_json_path
        )
        if status is None:
            cases.append(
                {
                    **base,
                    "content_status": None,
                    "coverage_state": "unaccounted",
                    "accounted": False,
                    "reason_code": disposition_reason,
                    "observation_id": None,
                    "observation_fingerprint": None,
                    "effective_profile_ids": [],
                    "association_attempts": [],
                }
            )
            continue
        if status == REVIEW_REQUIRED or status.startswith("rejected_"):
            cases.append(
                {
                    **base,
                    "content_status": status,
                    "coverage_state": "content_terminal",
                    "accounted": True,
                    "reason_code": (
                        "content_review_required"
                        if status == REVIEW_REQUIRED
                        else "content_rejected"
                    ),
                    "observation_id": None,
                    "observation_fingerprint": None,
                    "effective_profile_ids": [],
                    "association_attempts": [],
                }
            )
            continue
        if status != ACCEPTED_SERMON:
            cases.append(
                {
                    **base,
                    "content_status": status,
                    "coverage_state": "unaccounted",
                    "accounted": False,
                    "reason_code": "unsupported_content_status",
                    "observation_id": None,
                    "observation_fingerprint": None,
                    "effective_profile_ids": [],
                    "association_attempts": [],
                }
            )
            continue

        eligibility = assess_automatic_speaker_observation(
            database,
            video.id,
            verification_cache=verification_cache,
        )
        observation = (
            eligibility.observation
            or database.get_latest_speaker_observation_for_video(video.id)
        )
        if eligibility.reason_code in STRUCTURAL_GAP_REASONS or observation is None:
            cases.append(
                {
                    **base,
                    "content_status": status,
                    "coverage_state": "unaccounted",
                    "accounted": False,
                    "reason_code": eligibility.reason_code,
                    "observation_id": observation.id if observation else None,
                    "observation_fingerprint": (
                        observation.input_fingerprint if observation else None
                    ),
                    "effective_profile_ids": [],
                    "association_attempts": [],
                }
            )
            continue

        memberships = sorted(
            {
                database.resolve_speaker_profile_id(profile_id)
                for profile_id in database.list_effective_profile_ids_for_observation(
                    observation.id
                )
            }
        )
        all_attempts = [
            attempt
            for attempt in attempts_by_observation.get(
                observation.input_fingerprint, ()
            )
            if attempt["observation_id"] == observation.id
        ]
        attempts = [
            attempt
            for attempt in all_attempts
            if (
                attempt.get("association_version")
                == SHADOW_ASSOCIATION_VERSION
            )
            and (
                isinstance(attempt.get("span_selection"), dict)
                and attempt["span_selection"].get("version")
                == TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION
            )
            and (
                required_policy_sha256 is None
                or (
                    isinstance(attempt.get("policy"), dict)
                    and attempt["policy"].get("artifact_sha256")
                    == required_policy_sha256
                )
            )
            and (
                required_model_fingerprint is None
                or attempt.get("model_fingerprint")
                == required_model_fingerprint
            )
        ]
        common = {
            **base,
            "content_status": status,
            "observation_id": observation.id,
            "observation_fingerprint": observation.input_fingerprint,
            "effective_profile_ids": memberships,
            "association_attempts": attempts,
        }
        if memberships:
            cases.append(
                {
                    **common,
                    "coverage_state": "associated",
                    "accounted": True,
                    "reason_code": "effective_profile_membership",
                }
            )
            continue
        if not _has_transcript_grounded_spans(
            extraction.proposed_json_path,
            observation,
        ):
            cases.append(
                {
                    **common,
                    "coverage_state": "blocked",
                    "accounted": True,
                    "reason_code": "speech_grounded_spans_unavailable",
                }
            )
            continue
        if all_attempts and not attempts:
            cases.append(
                {
                    **common,
                    "coverage_state": "unaccounted",
                    "accounted": False,
                    "reason_code": "association_attempt_stale",
                    "stale_association_attempts": all_attempts,
                }
            )
            continue
        successful_attempts = [
            attempt
            for attempt in attempts
            if attempt["outcome"] in SUCCESSFUL_ATTEMPT_OUTCOMES
        ]
        if successful_attempts:
            cases.append(
                {
                    **common,
                    "coverage_state": "evaluated",
                    "accounted": True,
                    "reason_code": "versioned_association_attempt",
                }
            )
            continue
        if attempts:
            cases.append(
                {
                    **common,
                    "coverage_state": "unaccounted",
                    "accounted": False,
                    "reason_code": "association_attempt_requires_retry",
                }
            )
            continue

        review_action = database.get_effective_observation_review_action(
            observation.id
        )
        if review_action not in {None, "qualified_single_speaker"}:
            cases.append(
                {
                    **common,
                    "coverage_state": "blocked",
                    "accounted": True,
                    "reason_code": f"reviewed_{review_action}",
                }
            )
            continue
        if eligibility.reason_code != "eligible":
            cases.append(
                {
                    **common,
                    "coverage_state": "blocked",
                    "accounted": True,
                    "reason_code": eligibility.reason_code,
                }
            )
            continue
        cases.append(
            {
                **common,
                "coverage_state": "unaccounted",
                "accounted": False,
                "reason_code": "association_attempt_missing",
            }
        )

    state_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    for case in cases:
        state = str(case["coverage_state"])
        reason = str(case["reason_code"])
        state_counts[state] = state_counts.get(state, 0) + 1
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    unaccounted = sum(case["accounted"] is False for case in cases)
    stable_payload = {
        "schema_version": 1,
        "audit_version": ASSOCIATION_AUDIT_VERSION,
        "artifact_kind": "speaker_association_coverage_audit",
        "association_root": str(association_root.expanduser().resolve()),
        "required_policy_sha256": required_policy_sha256,
        "required_model_fingerprint": required_model_fingerprint,
        "required_association_version": SHADOW_ASSOCIATION_VERSION,
        "required_span_selection_version": (
            TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION
        ),
        "counts": {
            "extractions": len(cases),
            "accounted": len(cases) - unaccounted,
            "unaccounted": unaccounted,
            "invalid_association_artifacts": invalid_attempt_count,
        },
        "coverage_state_counts": dict(sorted(state_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "cases": cases,
    }
    audit_fingerprint = _sha256_json(stable_payload)
    output = output_root.expanduser().resolve()
    destination = output / f"association-audit-v1-{audit_fingerprint}.json"
    if destination.exists():
        loaded = json.loads(destination.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"Association audit is not a JSON object: {destination}")
        return AssociationAuditResult(destination, loaded)
    payload = {
        **stable_payload,
        "audit_fingerprint": audit_fingerprint,
        "created_at": utc_now().isoformat(),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return AssociationAuditResult(destination, payload)


def _read_content_disposition(
    proposed_json_path: str | None,
) -> tuple[str | None, str]:
    if not proposed_json_path:
        return None, "extraction_artifact_path_missing"
    try:
        payload = json.loads(
            Path(proposed_json_path).expanduser().read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "extraction_artifact_unreadable"
    if not isinstance(payload, dict):
        return None, "extraction_artifact_malformed"
    disposition = payload.get("final_disposition")
    if not isinstance(disposition, dict):
        return None, "disposition_missing_or_malformed"
    status = disposition.get("status")
    if not isinstance(status, str) or not status.strip():
        return None, "disposition_missing_or_malformed"
    return status, "content_disposition_available"


def _load_shadow_attempts(
    association_root: Path,
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    attempts: dict[str, list[dict[str, Any]]] = {}
    invalid = 0
    root = association_root.expanduser().resolve()
    if not root.exists():
        return attempts, invalid
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            invalid += 1
            continue
        if not isinstance(payload, dict) or payload.get(
            "artifact_kind"
        ) != SHADOW_ARTIFACT_KIND:
            invalid += 1
            continue
        candidate = payload.get("candidate")
        result_sha256 = payload.get("result_sha256")
        if (
            not isinstance(candidate, dict)
            or not isinstance(candidate.get("observation_id"), int)
            or not isinstance(candidate.get("input_fingerprint"), str)
            or not isinstance(payload.get("outcome"), str)
            or not isinstance(result_sha256, str)
        ):
            invalid += 1
            continue
        unhashed = dict(payload)
        unhashed.pop("result_sha256", None)
        if _sha256_json(unhashed) != result_sha256:
            invalid += 1
            continue
        fingerprint = str(candidate["input_fingerprint"])
        attempts.setdefault(fingerprint, []).append(
            {
                "artifact_path": str(path),
                "observation_id": int(candidate["observation_id"]),
                "observation_fingerprint": fingerprint,
                "input_fingerprint": payload.get("input_fingerprint"),
                "outcome": str(payload["outcome"]),
                "reason": payload.get("reason"),
                "proposed_profile_id": payload.get("proposed_profile_id"),
                "model_fingerprint": payload.get("model_fingerprint"),
                "policy": payload.get("policy"),
                "association_version": payload.get("association_version"),
                "span_selection": payload.get("span_selection"),
                "result_sha256": result_sha256,
            }
        )
    return attempts, invalid


def _has_transcript_grounded_spans(
    proposed_json_path: str | None,
    observation: SpeakerObservation,
) -> bool:
    if not proposed_json_path:
        return False
    try:
        payload = json.loads(
            Path(proposed_json_path).expanduser().read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and bool(
        select_transcript_grounded_spans(payload, observation)
    )


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
