from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pastor_transcript_extractor.config import AppPaths, build_video_artifact_paths
from pastor_transcript_extractor.identity_attribution import AttributionResult
from pastor_transcript_extractor.models import (
    ExtractionResult,
    Pastor,
    SpeakerNameClaim,
    SpeakerObservation,
    SpeakerProfile,
    Video,
    utc_now,
)
from pastor_transcript_extractor.storage import Database


SPEAKER_EVIDENCE_VERSION = "speaker_evidence_v1"
SPEAKER_REGISTRY_POLICY_VERSION = "speaker_registry_shadow_v1"

_HONORIFICS = {"pastor", "elder", "dr", "pr"}
_OUTCOME_ORDER = (
    "explicit_guest_attribution",
    "explicit_target_attribution",
    "metadata_target_match",
    "metadata_non_target_match",
    "spoken_introduction_target",
    "spoken_introduction_guest",
    "conflicting_attribution",
    "no_attribution_evidence",
)


@dataclass(frozen=True, slots=True)
class NeutralSpeakerEvidence:
    configured_profile: SpeakerProfile
    observation: SpeakerObservation | None
    claims: tuple[SpeakerNameClaim, ...]
    artifact_path: Path
    artifact_content_sha256: str
    compatibility_outcomes: tuple[str, ...]


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_person(value: str) -> str:
    tokens = re.findall(r"[a-z]+", value.lower())
    while tokens and tokens[0] in _HONORIFICS:
        tokens.pop(0)
    return " ".join(tokens)


def _valid_sermon_window(payload: dict[str, Any]) -> tuple[float, float] | None:
    window = payload.get("sermon_window")
    if not isinstance(window, dict):
        return None
    start = window.get("start_seconds")
    end = window.get("end_seconds")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    if float(end) <= float(start):
        return None
    return float(start), float(end)


def neutral_claim_payloads(attribution: AttributionResult) -> tuple[dict[str, Any], ...]:
    claims: list[dict[str, Any]] = []
    for observation in attribution.observations:
        explicit = observation.get("explicit_speaker_attribution") is True
        claims.append(
            {
                "display_name": str(observation["person_name"]),
                "normalized_name": str(observation["normalized_person_name"]),
                "claim_kind": "explicit_speaker_attribution" if explicit else "name_mention",
                "channel": str(observation["channel"]),
                "explicit_speaker_attribution": explicit,
                "correlation_group_id": str(observation["correlation_group_id"]),
                "provenance": observation["provenance"],
            }
        )
    return tuple(claims)


def project_target_attribution_outcomes(
    claims: Iterable[dict[str, Any] | SpeakerNameClaim],
    *,
    target_name: str,
) -> tuple[str, ...]:
    """Project identity-neutral claims into the legacy target-centered shadow vocabulary."""
    target = _normalized_person(target_name)
    normalized: list[dict[str, Any]] = []
    for claim in claims:
        if isinstance(claim, SpeakerNameClaim):
            normalized.append(
                {
                    "normalized_name": claim.normalized_name,
                    "channel": claim.channel,
                    "explicit": claim.explicit_speaker_attribution,
                }
            )
        else:
            normalized.append(
                {
                    "normalized_name": str(claim["normalized_name"]),
                    "channel": str(claim["channel"]),
                    "explicit": claim.get("explicit_speaker_attribution") is True,
                }
            )

    target_claims = [claim for claim in normalized if claim["normalized_name"] == target]
    other_claims = [claim for claim in normalized if claim["normalized_name"] != target]
    outcomes: set[str] = set()
    if any(claim["channel"] == "metadata" for claim in target_claims):
        outcomes.add("metadata_target_match")
    if any(claim["channel"] == "metadata" for claim in other_claims):
        outcomes.add("metadata_non_target_match")
    if any(claim["channel"] == "spoken" for claim in target_claims):
        outcomes.add("spoken_introduction_target")
    if any(claim["channel"] == "spoken" for claim in other_claims):
        outcomes.add("spoken_introduction_guest")
    if any(claim["explicit"] for claim in target_claims):
        outcomes.add("explicit_target_attribution")
    if any(claim["explicit"] for claim in other_claims):
        outcomes.add("explicit_guest_attribution")
    if (
        any(claim["explicit"] for claim in target_claims)
        and any(claim["explicit"] for claim in other_claims)
    ):
        outcomes.add("conflicting_attribution")
    if not normalized:
        outcomes.add("no_attribution_evidence")
    return tuple(outcome for outcome in _OUTCOME_ORDER if outcome in outcomes)


def ensure_configured_pastor_profile(database: Database, pastor: Pastor) -> SpeakerProfile:
    profile = database.ensure_speaker_profile(
        stable_key=f"configured-pastor:{pastor.slug}",
        display_label=pastor.display_name,
        lifecycle_state="unprofiled",
        created_reason="configured_requested_identity",
    )
    bound_profile_id = database.ensure_pastor_speaker_binding(pastor.id, profile.id)
    if bound_profile_id != profile.id:
        raise ValueError(f"Pastor {pastor.id} is already bound to a different speaker profile")
    return profile


def persist_neutral_speaker_evidence(
    database: Database,
    app_paths: AppPaths,
    *,
    video: Video,
    pastor: Pastor,
    extraction_result: ExtractionResult,
    proposed_payload: dict[str, Any],
    attribution: AttributionResult,
) -> NeutralSpeakerEvidence:
    configured_profile = ensure_configured_pastor_profile(database, pastor)
    window = _valid_sermon_window(proposed_payload)
    claim_payloads = neutral_claim_payloads(attribution)
    compatibility_outcomes = project_target_attribution_outcomes(
        claim_payloads,
        target_name=pastor.display_name,
    )
    content = {
        "schema_version": 1,
        "extractor_version": SPEAKER_EVIDENCE_VERSION,
        "registry_policy_version": SPEAKER_REGISTRY_POLICY_VERSION,
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "extraction_result_id": extraction_result.id,
        "configured_requested_identity": {
            "pastor_id": pastor.id,
            "speaker_profile_stable_key": configured_profile.stable_key,
            "semantics": "query_identity_not_observation_membership",
        },
        "observation": (
            {
                "role": "principal_speaker_candidate",
                "multiplicity_state": "unknown",
                "start_seconds": window[0],
                "end_seconds": window[1],
            }
            if window is not None
            else None
        ),
        "name_claims": list(claim_payloads),
        "compatibility_projection": {
            "target_name": pastor.display_name,
            "attribution_outcomes": list(compatibility_outcomes),
        },
        "safety_contract": {
            "automatic_profile_creation_from_observation": False,
            "automatic_observation_attachment": False,
            "automatic_name_attachment": False,
            "acoustic_features_present": False,
        },
    }
    content_sha256 = _sha256(content)
    video_paths = build_video_artifact_paths(app_paths, pastor.slug, video.youtube_video_id)
    artifact_path = video_paths.identity / f"speaker-evidence-v1-{content_sha256[:12]}.json"
    if not artifact_path.exists():
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps({**content, "content_sha256": content_sha256, "created_at": utc_now().isoformat()}, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    observation: SpeakerObservation | None = None
    if window is not None:
        observation_fingerprint = _sha256(
            {
                "extractor_version": SPEAKER_EVIDENCE_VERSION,
                "video_id": video.id,
                "extraction_result_id": extraction_result.id,
                "role": "principal_speaker_candidate",
                "multiplicity_state": "unknown",
                "start_seconds": window[0],
                "end_seconds": window[1],
                "artifact_content_sha256": content_sha256,
            }
        )
        observation = database.add_speaker_observation(
            video_id=video.id,
            extraction_result_id=extraction_result.id,
            role="principal_speaker_candidate",
            multiplicity_state="unknown",
            start_seconds=window[0],
            end_seconds=window[1],
            artifact_path=str(artifact_path),
            content_sha256=content_sha256,
            extractor_version=SPEAKER_EVIDENCE_VERSION,
            input_fingerprint=observation_fingerprint,
        )

    persisted_claims: list[SpeakerNameClaim] = []
    for claim in claim_payloads:
        observation_id = observation.id if observation is not None and claim["explicit_speaker_attribution"] else None
        claim_fingerprint = _sha256(
            {
                "extractor_version": SPEAKER_EVIDENCE_VERSION,
                "video_id": video.id,
                "observation_fingerprint": observation.input_fingerprint if observation_id is not None else None,
                "claim": claim,
                "artifact_content_sha256": content_sha256,
            }
        )
        persisted_claims.append(
            database.add_speaker_name_claim(
                video_id=video.id,
                observation_id=observation_id,
                display_name=str(claim["display_name"]),
                normalized_name=str(claim["normalized_name"]),
                claim_kind=str(claim["claim_kind"]),
                channel=str(claim["channel"]),
                explicit_speaker_attribution=bool(claim["explicit_speaker_attribution"]),
                correlation_group_id=str(claim["correlation_group_id"]),
                provenance_json=_canonical_json(claim["provenance"]),
                artifact_path=str(artifact_path),
                claim_fingerprint=claim_fingerprint,
                extractor_version=SPEAKER_EVIDENCE_VERSION,
            )
        )
    return NeutralSpeakerEvidence(
        configured_profile=configured_profile,
        observation=observation,
        claims=tuple(persisted_claims),
        artifact_path=artifact_path,
        artifact_content_sha256=content_sha256,
        compatibility_outcomes=compatibility_outcomes,
    )


def create_profile(
    database: Database,
    *,
    display_label: str | None,
    created_reason: str,
    stable_key: str | None = None,
) -> SpeakerProfile:
    return database.ensure_speaker_profile(
        stable_key=stable_key or f"speaker:{uuid.uuid4()}",
        display_label=display_label,
        lifecycle_state="active",
        created_reason=created_reason,
    )


def record_observation_review(
    database: Database,
    *,
    profile_id: int,
    observation_id: int,
    attach: bool,
    reviewer: str,
    reason: str,
    review_event_key: str,
) -> int:
    if database.get_speaker_profile(profile_id) is None:
        raise ValueError(f"Unknown speaker profile: {profile_id}")
    if database.get_speaker_observation(observation_id) is None:
        raise ValueError(f"Unknown speaker observation: {observation_id}")
    action = "attach" if attach else "detach"
    fingerprint = _sha256(
        {
            "kind": "profile_observation",
            "review_event_key": review_event_key,
            "profile_id": profile_id,
            "observation_id": observation_id,
            "action": action,
        }
    )
    return database.add_profile_observation_event(
        profile_id=profile_id,
        observation_id=observation_id,
        action=action,
        reviewer=reviewer,
        reason=reason,
        event_fingerprint=fingerprint,
    )


def record_name_claim_review(
    database: Database,
    *,
    claim_id: int,
    profile_id: int | None,
    attach: bool,
    reviewer: str,
    reason: str,
    review_event_key: str,
) -> int:
    action = "attach" if attach else "reject"
    if attach and profile_id is None:
        raise ValueError("Attaching a name claim requires a profile")
    if profile_id is not None and database.get_speaker_profile(profile_id) is None:
        raise ValueError(f"Unknown speaker profile: {profile_id}")
    if database.get_speaker_name_claim(claim_id) is None:
        raise ValueError(f"Unknown speaker name claim: {claim_id}")
    fingerprint = _sha256(
        {
            "kind": "profile_name_claim",
            "review_event_key": review_event_key,
            "profile_id": profile_id,
            "claim_id": claim_id,
            "action": action,
        }
    )
    return database.add_profile_name_claim_event(
        profile_id=profile_id,
        claim_id=claim_id,
        action=action,
        reviewer=reviewer,
        reason=reason,
        event_fingerprint=fingerprint,
    )


def record_profile_redirect(
    database: Database,
    *,
    from_profile_id: int,
    to_profile_id: int | None,
    reviewer: str,
    reason: str,
    review_event_key: str,
) -> int:
    action = "redirect" if to_profile_id is not None else "clear"
    if database.get_speaker_profile(from_profile_id) is None:
        raise ValueError(f"Unknown speaker profile: {from_profile_id}")
    if to_profile_id is not None and database.get_speaker_profile(to_profile_id) is None:
        raise ValueError(f"Unknown speaker profile: {to_profile_id}")
    if to_profile_id == from_profile_id:
        raise ValueError("A speaker profile cannot redirect to itself")
    cursor = to_profile_id
    visited = {from_profile_id}
    while cursor is not None:
        if cursor in visited:
            raise ValueError("Speaker profile redirect would create a cycle")
        visited.add(cursor)
        cursor = database.get_effective_profile_redirect(cursor)
    fingerprint = _sha256(
        {
            "kind": "profile_redirect",
            "review_event_key": review_event_key,
            "from_profile_id": from_profile_id,
            "to_profile_id": to_profile_id,
            "action": action,
        }
    )
    return database.add_profile_redirect_event(
        from_profile_id=from_profile_id,
        to_profile_id=to_profile_id,
        action=action,
        reviewer=reviewer,
        reason=reason,
        event_fingerprint=fingerprint,
    )
