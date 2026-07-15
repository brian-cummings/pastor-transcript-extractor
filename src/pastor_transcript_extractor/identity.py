from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pastor_transcript_extractor.config import AppPaths, build_video_artifact_paths
from pastor_transcript_extractor.identity_attribution import (
    ATTRIBUTION_EXTRACTOR_VERSION,
    extract_grounded_attributions,
)
from pastor_transcript_extractor.models import (
    ExtractionResult,
    IdentityAction,
    IdentityAssessment,
    IdentityState,
    MetadataArtifact,
    Pastor,
    Video,
    utc_now,
)
from pastor_transcript_extractor.speaker_registry import persist_neutral_speaker_evidence
from pastor_transcript_extractor.storage import Database


METADATA_SCHEMA_VERSION = 1
METADATA_EXTRACTOR_VERSION = "source_metadata_v1"
IDENTITY_EVIDENCE_VERSION = "identity_evidence_v4"
IDENTITY_POLICY_VERSION = "identity_shadow_v4"
DECISION_POLICY_VERSION = "content_identity_coordinator_v1"


@dataclass(frozen=True, slots=True)
class ShadowIdentityResult:
    assessment: IdentityAssessment
    metadata_artifact: MetadataArtifact
    evidence_ledger_path: Path
    assessment_path: Path


@dataclass(frozen=True, slots=True)
class IdentityBackfillResult:
    created: int
    reused: int
    skipped: int
    failed: int


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def persist_metadata_snapshot(
    database: Database,
    app_paths: AppPaths,
    *,
    video: Video,
    pastor: Pastor,
    source_kind: str,
    raw_metadata: dict[str, Any] | None = None,
) -> MetadataArtifact:
    """Persist immutable discovery context without treating it as identity proof."""
    evidence = {
        "schema_version": METADATA_SCHEMA_VERSION,
        "extractor_version": METADATA_EXTRACTOR_VERSION,
        "source_kind": source_kind,
        "video": {
            "database_id": video.id,
            "youtube_video_id": video.youtube_video_id,
            "source_id": video.source_id,
            "assigned_target_pastor_id": video.pastor_id,
            "title": video.title,
            "url": video.url,
            "channel_name": video.channel_name,
            "published_at": video.published_at.isoformat() if video.published_at is not None else None,
            "duration_seconds": video.duration_seconds,
        },
        "target_context": {
            "pastor_id": pastor.id,
            "pastor_slug": pastor.slug,
            "pastor_display_name": pastor.display_name,
            "semantic_role": "expected_target_not_verified_speaker",
        },
        "raw_metadata": raw_metadata or {},
    }
    content_sha256 = _sha256(evidence)
    existing = database.get_latest_metadata_artifact_for_video(video.id)
    if (
        existing is not None
        and existing.content_sha256 == content_sha256
        and existing.extractor_version == METADATA_EXTRACTOR_VERSION
        and Path(existing.artifact_path).exists()
    ):
        return existing

    video_paths = build_video_artifact_paths(app_paths, pastor.slug, video.youtube_video_id)
    artifact_path = (
        video_paths.identity
        / "metadata"
        / f"source-metadata-v{METADATA_SCHEMA_VERSION}-{content_sha256[:12]}.json"
    )
    payload = {
        **evidence,
        "content_sha256": content_sha256,
        "captured_at": utc_now().isoformat(),
    }
    _write_json(artifact_path, payload)
    return database.add_metadata_artifact(
        video_id=video.id,
        schema_version=METADATA_SCHEMA_VERSION,
        source_kind=source_kind,
        artifact_path=str(artifact_path),
        content_sha256=content_sha256,
        extractor_version=METADATA_EXTRACTOR_VERSION,
    )


def recommended_action_for_state(state: IdentityState) -> IdentityAction:
    if state == IdentityState.TARGET_CONFIRMED:
        return IdentityAction.ACCEPT
    if state == IdentityState.NON_TARGET_CONFIRMED:
        return IdentityAction.REJECT_NON_TARGET
    if state == IdentityState.MIXED_OR_COMPOUND:
        return IdentityAction.REVIEW
    if state == IdentityState.ANALYSIS_FAILED:
        return IdentityAction.RETRY
    return IdentityAction.REVIEW


def coordinate_decision(
    content_disposition: dict[str, Any],
    identity_state: IdentityState,
    *,
    shadow_mode: bool,
) -> dict[str, Any]:
    """Compose independent content and identity judgments without hiding abstention."""
    content_status = str(content_disposition.get("status", "review_required"))
    identity_action = recommended_action_for_state(identity_state)

    if content_status.startswith("rejected_"):
        proposed_status = content_status
        reason_codes = ["content_rejection_is_terminal"]
    elif content_status != "accepted_sermon":
        proposed_status = "review_required"
        reason_codes = ["content_requires_review"]
    elif identity_state == IdentityState.TARGET_CONFIRMED:
        proposed_status = "accepted_target_sermon"
        reason_codes = ["content_accepted_and_target_identity_confirmed"]
    elif identity_state == IdentityState.NON_TARGET_CONFIRMED:
        proposed_status = "rejected_non_target"
        reason_codes = ["content_accepted_but_non_target_identity_confirmed"]
    elif identity_state == IdentityState.MIXED_OR_COMPOUND:
        proposed_status = "review_required"
        reason_codes = ["mixed_or_compound_identity_requires_review"]
    else:
        proposed_status = "review_required"
        reason_codes = [f"identity_{identity_state.value}_requires_review"]

    return {
        "schema_version": 1,
        "policy_version": DECISION_POLICY_VERSION,
        "shadow_mode": shadow_mode,
        "content_status": content_status,
        "identity_state": identity_state.value,
        "identity_recommended_action": identity_action.value,
        "proposed_status": proposed_status,
        "effective_status": content_status if shadow_mode else proposed_status,
        "reason_codes": reason_codes,
    }


def record_shadow_identity_assessment(
    database: Database,
    app_paths: AppPaths,
    *,
    video: Video,
    pastor: Pastor,
    extraction_result: ExtractionResult,
    content_disposition: dict[str, Any],
) -> ShadowIdentityResult:
    """Record the identity contract before any recognition backend is enabled."""
    metadata_artifact = database.get_latest_metadata_artifact_for_video(video.id)
    if metadata_artifact is None:
        metadata_artifact = persist_metadata_snapshot(
            database,
            app_paths,
            video=video,
            pastor=pastor,
            source_kind="database_backfill",
        )

    if not extraction_result.proposed_json_path:
        raise ValueError("Identity assessment requires a proposed JSON artifact")
    metadata_payload = json.loads(Path(metadata_artifact.artifact_path).read_text(encoding="utf-8"))
    proposed_payload = json.loads(Path(extraction_result.proposed_json_path).read_text(encoding="utf-8"))
    if not isinstance(metadata_payload, dict) or not isinstance(proposed_payload, dict):
        raise ValueError("Identity inputs must be JSON objects")
    attribution = extract_grounded_attributions(
        metadata_payload=metadata_payload,
        proposed_payload=proposed_payload,
        target_name=pastor.display_name,
        metadata_artifact_id=metadata_artifact.id,
        metadata_content_sha256=metadata_artifact.content_sha256,
    )
    attribution_payload = attribution.to_dict()
    neutral_evidence = persist_neutral_speaker_evidence(
        database,
        app_paths,
        video=video,
        pastor=pastor,
        extraction_result=extraction_result,
        proposed_payload=proposed_payload,
        attribution=attribution,
    )
    if tuple(attribution.outcomes) != neutral_evidence.compatibility_outcomes:
        raise ValueError("Neutral speaker claims did not reproduce target attribution outcomes")

    state = IdentityState.PROFILE_UNAVAILABLE
    action = recommended_action_for_state(state)
    coordination = coordinate_decision(content_disposition, state, shadow_mode=True)
    fingerprint_payload = {
        "policy_version": IDENTITY_POLICY_VERSION,
        "video_id": video.id,
        "target_pastor_id": pastor.id,
        "extraction_result_id": extraction_result.id,
        "content_disposition": content_disposition,
        "metadata_content_sha256": metadata_artifact.content_sha256,
        "attribution_extractor_version": ATTRIBUTION_EXTRACTOR_VERSION,
        "attribution": attribution_payload,
        "speaker_evidence_content_sha256": neutral_evidence.artifact_content_sha256,
        "state": state.value,
        "shadow_mode": True,
    }
    input_fingerprint = _sha256(fingerprint_payload)
    existing = database.get_identity_assessment_by_fingerprint(input_fingerprint)
    if existing is not None:
        return ShadowIdentityResult(
            assessment=existing,
            metadata_artifact=metadata_artifact,
            evidence_ledger_path=Path(existing.evidence_ledger_path),
            assessment_path=Path(existing.assessment_path),
        )

    video_paths = build_video_artifact_paths(app_paths, pastor.slug, video.youtube_video_id)
    evidence_ledger_path = (
        video_paths.identity / f"evidence-ledger-v4-{input_fingerprint[:12]}.json"
    )
    assessment_path = video_paths.identity / f"assessment-v4-{input_fingerprint[:12]}.json"
    observation = {
        "evidence_type": "source_target_assignment",
        "source_family": "source_context",
        "polarity": "context_only",
        "strength": "prior_only",
        "scope": "video",
        "extractor_version": IDENTITY_EVIDENCE_VERSION,
        "reason": "The source was assigned to this pastor, but assignment is not speaker verification.",
        "metadata_artifact_id": metadata_artifact.id,
        "metadata_content_sha256": metadata_artifact.content_sha256,
    }
    ledger_payload = {
        "schema_version": 4,
        "extractor_version": IDENTITY_EVIDENCE_VERSION,
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "target_pastor_id": pastor.id,
        "target_pastor_slug": pastor.slug,
        "extraction_result_id": extraction_result.id,
        "observations": [observation, *attribution_payload["observations"]],
        "attribution_outcomes": attribution_payload["outcomes"],
        "correlation_groups": attribution_payload["correlation_groups"],
        "independent_attribution_group_count": attribution_payload["independent_attribution_group_count"],
        "neutral_speaker_evidence": {
            "artifact_path": str(neutral_evidence.artifact_path),
            "content_sha256": neutral_evidence.artifact_content_sha256,
            "configured_profile_id": neutral_evidence.configured_profile.id,
            "observation_id": neutral_evidence.observation.id if neutral_evidence.observation is not None else None,
            "name_claim_ids": [claim.id for claim in neutral_evidence.claims],
            "automatic_profile_membership": False,
        },
        "limitations": [
            "No voice profile or recognition backend is active.",
            "Source assignment and recurring-channel expectation are not identity proof.",
            "Grounded attribution evidence is shadow-only and does not change identity state or effective disposition.",
            "Sermon topic, style, and theology are not identity evidence.",
        ],
        "created_at": utc_now().isoformat(),
    }
    _write_json(evidence_ledger_path, ledger_payload)
    evidence = database.add_identity_evidence(
        video_id=video.id,
        target_pastor_id=pastor.id,
        evidence_type=str(observation["evidence_type"]),
        source_family=str(observation["source_family"]),
        polarity=str(observation["polarity"]),
        strength=str(observation["strength"]),
        scope=str(observation["scope"]),
        artifact_path=str(evidence_ledger_path),
        extractor_version=IDENTITY_EVIDENCE_VERSION,
    )
    evidence_ids = [evidence.id]
    polarity_by_outcome = {
        "explicit_guest_attribution": "contradicts_target",
        "explicit_target_attribution": "supports_target",
        "metadata_target_match": "supports_target",
        "metadata_non_target_match": "context_only",
        "spoken_introduction_target": "supports_target",
        "spoken_introduction_guest": "contradicts_target",
        "conflicting_attribution": "mixed",
        "no_attribution_evidence": "neutral",
    }
    for outcome in attribution.outcomes:
        if outcome == "no_attribution_evidence":
            strength = "none"
        elif outcome == "conflicting_attribution" or outcome.startswith("explicit_") or outcome.startswith("spoken_"):
            strength = "explicit"
        else:
            strength = "contextual"
        outcome_evidence = database.add_identity_evidence(
            video_id=video.id,
            target_pastor_id=pastor.id,
            evidence_type=outcome,
            source_family="grounded_attribution",
            polarity=polarity_by_outcome[outcome],
            strength=strength,
            scope="sermon_speaker_attribution",
            artifact_path=str(evidence_ledger_path),
            extractor_version=IDENTITY_EVIDENCE_VERSION,
        )
        evidence_ids.append(outcome_evidence.id)
    assessment_payload = {
        "schema_version": 4,
        "policy_version": IDENTITY_POLICY_VERSION,
        "input_fingerprint": input_fingerprint,
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "target_pastor_id": pastor.id,
        "target_pastor_slug": pastor.slug,
        "extraction_result_id": extraction_result.id,
        "state": state.value,
        "recommended_action": action.value,
        "shadow_mode": True,
        "reason_codes": ["target_voice_profile_unavailable"],
        "attribution_outcomes": attribution_payload["outcomes"],
        "speaker_evidence_artifact_path": str(neutral_evidence.artifact_path),
        "evidence_ids": evidence_ids,
        "evidence_ledger_path": str(evidence_ledger_path),
        "coordination": coordination,
        "created_at": utc_now().isoformat(),
    }
    _write_json(assessment_path, assessment_payload)
    assessment = database.add_identity_assessment(
        video_id=video.id,
        target_pastor_id=pastor.id,
        extraction_result_id=extraction_result.id,
        state=state,
        recommended_action=action,
        shadow_mode=True,
        policy_version=IDENTITY_POLICY_VERSION,
        evidence_ledger_path=str(evidence_ledger_path),
        assessment_path=str(assessment_path),
        input_fingerprint=input_fingerprint,
    )
    return ShadowIdentityResult(
        assessment=assessment,
        metadata_artifact=metadata_artifact,
        evidence_ledger_path=evidence_ledger_path,
        assessment_path=assessment_path,
    )


def backfill_shadow_identity_assessments(
    database: Database,
    app_paths: AppPaths,
    *,
    video_id: int | None = None,
) -> IdentityBackfillResult:
    """Backfill existing extractions without reclassifying or rewriting content artifacts."""
    from pastor_transcript_extractor.disposition import build_final_disposition

    videos = database.list_videos()
    if video_id is not None:
        videos = [video for video in videos if video.id == video_id]

    created = 0
    reused = 0
    skipped = 0
    failed = 0
    for video in videos:
        extraction = database.get_latest_extraction_result_for_video(video.id)
        pastor = database.get_pastor_by_id(video.pastor_id) if video.pastor_id is not None else None
        if extraction is None or pastor is None or not extraction.proposed_json_path:
            skipped += 1
            continue
        proposed_path = Path(extraction.proposed_json_path)
        try:
            payload = json.loads(proposed_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("proposed artifact is not a JSON object")
            content_disposition = payload.get("final_disposition")
            if not isinstance(content_disposition, dict):
                content_disposition = build_final_disposition(
                    payload.get("classification"),
                    payload.get("sermon_window"),
                    guest_speaker_suspected=payload.get("guest_speaker_suspected") is True,
                )
            before = database.get_latest_identity_assessment_for_video(video.id)
            result = record_shadow_identity_assessment(
                database,
                app_paths,
                video=video,
                pastor=pastor,
                extraction_result=extraction,
                content_disposition=content_disposition,
            )
        except (OSError, ValueError, json.JSONDecodeError):
            failed += 1
            continue
        if before is not None and before.id == result.assessment.id:
            reused += 1
        else:
            created += 1
    return IdentityBackfillResult(created=created, reused=reused, skipped=skipped, failed=failed)
