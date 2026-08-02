from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from pastor_transcript_extractor.speaker_registry import (
    record_observation_difference,
    record_observation_disposition,
    record_observation_review,
)
from pastor_transcript_extractor.storage import Database


REVIEW_INVALIDATION_VERSION = "normalized_audio_review_invalidation_v1"


@dataclass(frozen=True, slots=True)
class ReviewRevocations:
    draft_ids: frozenset[str]
    review_event_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class ReviewInvalidationResult:
    revocation_paths: tuple[Path, ...]
    affected_observation_fingerprints: tuple[str, ...]
    revoked_draft_ids: tuple[str, ...]
    revoked_review_event_ids: tuple[str, ...]
    dispositions_reset: int
    memberships_detached: int
    differences_cleared: int


def load_review_revocations(evaluation_root: Path) -> ReviewRevocations:
    draft_ids: set[str] = set()
    event_ids: set[str] = set()
    for path in sorted((evaluation_root / "revocations").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("event_kind") != (
            "speaker_review_provenance_revocation"
        ):
            continue
        draft_ids.update(
            str(value) for value in payload.get("revoked_draft_ids", []) if value
        )
        event_ids.update(
            str(value)
            for value in payload.get("revoked_review_event_ids", [])
            if value
        )
    return ReviewRevocations(frozenset(draft_ids), frozenset(event_ids))


def pair_artifact_is_revoked(
    payload: dict[str, Any], revocations: ReviewRevocations
) -> bool:
    draft_id = payload.get("draft_id")
    event_id = payload.get("review_event_id")
    return (
        isinstance(draft_id, str)
        and draft_id in revocations.draft_ids
    ) or (
        isinstance(event_id, str)
        and event_id in revocations.review_event_ids
    )


def filter_active_pair_artifacts(
    payloads: Iterable[dict[str, Any]],
    revocations: ReviewRevocations,
) -> list[dict[str, Any]]:
    return [
        payload
        for payload in payloads
        if not pair_artifact_is_revoked(payload, revocations)
    ]


def invalidate_reviews_for_videos(
    database: Database,
    *,
    evaluation_root: Path,
    youtube_video_ids: set[str],
    suspect_audio_sha256_by_video: dict[str, set[str]] | None = None,
    reviewer: str,
    reason: str,
) -> ReviewInvalidationResult:
    """Append revocations and neutralize registry state derived from suspect audio."""
    root = evaluation_root.expanduser().resolve()
    reviewer = reviewer.strip()
    reason = reason.strip()
    if not reviewer or not reason:
        raise ValueError("reviewer and reason are required for evidence invalidation")
    existing_revocations = load_review_revocations(root)
    drafts = filter_active_pair_artifacts(
        _load_objects(sorted((root / "drafts").glob("*.json"))),
        existing_revocations,
    )
    affected_drafts = [
        draft
        for draft in drafts
        if any(
            _observation_uses_suspect_audio(
                observation,
                youtube_video_ids=youtube_video_ids,
                suspect_audio_sha256_by_video=suspect_audio_sha256_by_video,
            )
            for observation in draft.get("observations", {}).values()
            if isinstance(observation, dict)
        )
    ]
    draft_ids = {
        str(draft["draft_id"])
        for draft in affected_drafts
        if draft.get("draft_id")
    }
    pair_ids = {
        str(draft["pair_id"])
        for draft in affected_drafts
        if draft.get("pair_id")
    }
    fingerprints = {
        str(observation["input_fingerprint"])
        for draft in affected_drafts
        for observation in draft.get("observations", {}).values()
        if isinstance(observation, dict)
        and _observation_uses_suspect_audio(
            observation,
            youtube_video_ids=youtube_video_ids,
            suspect_audio_sha256_by_video=suspect_audio_sha256_by_video,
        )
        and observation.get("input_fingerprint")
    }
    reviews = _load_objects(
        sorted(
            path
            for pair_id in pair_ids
            for path in (root / "reviews" / pair_id).glob("*.json")
        )
    )
    event_ids = {
        str(review["review_event_id"])
        for review in reviews
        if review.get("draft_id") in draft_ids and review.get("review_event_id")
    }
    fixtures = _load_objects(
        sorted(
            path
            for path in (root / "fixtures").glob("*.json")
            if path.stem in pair_ids
        )
    )
    event_ids.update(
        str(fixture["review_event_id"])
        for fixture in fixtures
        if fixture.get("pair_id") in pair_ids and fixture.get("review_event_id")
    )
    stable = {
        "schema_version": 1,
        "invalidation_version": REVIEW_INVALIDATION_VERSION,
        "event_kind": "speaker_review_provenance_revocation",
        "affected_youtube_video_ids": sorted(youtube_video_ids),
        "affected_observation_fingerprints": sorted(fingerprints),
        "revoked_draft_ids": sorted(draft_ids),
        "revoked_review_event_ids": sorted(event_ids),
        "reviewer": reviewer,
        "reason": reason,
    }
    revocation_paths: tuple[Path, ...] = ()
    if draft_ids or event_ids:
        revocation_id = _sha256_json(stable)
        path = root / "revocations" / f"{revocation_id}.json"
        _write_json_idempotent(path, {**stable, "revocation_id": revocation_id})
        revocation_paths = (path,)
    cleanup_key = _sha256_json(stable)
    dispositions_reset = 0
    memberships_detached = 0
    differences_cleared = 0
    observations = [
        database.get_speaker_observation_by_fingerprint(fingerprint)
        for fingerprint in sorted(fingerprints)
    ]
    observation_ids = {
        observation.id for observation in observations if observation is not None
    }
    for observation in observations:
        if observation is None:
            continue
        if database.get_effective_observation_review_action(
            observation.id
        ) != "unresolved":
            record_observation_disposition(
                database,
                observation_id=observation.id,
                action="unresolved",
                reviewer=reviewer,
                reason=reason,
                review_event_key=(
                    f"{REVIEW_INVALIDATION_VERSION}:disposition:"
                    f"{cleanup_key}:{observation.id}"
                ),
            )
            dispositions_reset += 1
        for profile_id in database.list_effective_profile_ids_for_observation(
            observation.id
        ):
            record_observation_review(
                database,
                profile_id=profile_id,
                observation_id=observation.id,
                attach=False,
                reviewer=reviewer,
                reason=reason,
                review_event_key=(
                    f"{REVIEW_INVALIDATION_VERSION}:membership:"
                    f"{cleanup_key}:{profile_id}:{observation.id}"
                ),
            )
            memberships_detached += 1
    for observation_a_id, observation_b_id in (
        database.list_effective_observation_difference_pairs()
    ):
        if not {observation_a_id, observation_b_id}.intersection(observation_ids):
            continue
        record_observation_difference(
            database,
            observation_a_id=observation_a_id,
            observation_b_id=observation_b_id,
            different=False,
            reviewer=reviewer,
            reason=reason,
            review_event_key=(
                f"{REVIEW_INVALIDATION_VERSION}:difference:"
                f"{cleanup_key}:{observation_a_id}:{observation_b_id}"
            ),
        )
        differences_cleared += 1
    return ReviewInvalidationResult(
        revocation_paths=revocation_paths,
        affected_observation_fingerprints=tuple(sorted(fingerprints)),
        revoked_draft_ids=tuple(sorted(draft_ids)),
        revoked_review_event_ids=tuple(sorted(event_ids)),
        dispositions_reset=dispositions_reset,
        memberships_detached=memberships_detached,
        differences_cleared=differences_cleared,
    )


def evaluation_root_for_pair_artifact(path: Path) -> Path | None:
    if path.parent.name in {"drafts", "fixtures"}:
        return path.parent.parent
    if path.parent.parent.name == "reviews":
        return path.parent.parent.parent
    return None


def _observation_uses_suspect_audio(
    observation: dict[str, Any],
    *,
    youtube_video_ids: set[str],
    suspect_audio_sha256_by_video: dict[str, set[str]] | None,
) -> bool:
    youtube_video_id = observation.get("youtube_video_id")
    if youtube_video_id not in youtube_video_ids:
        return False
    if suspect_audio_sha256_by_video is None:
        return True
    audio_sha256 = observation.get("normalized_audio_sha256")
    # Legacy drafts lacked an audio identity and are conservatively suspect.
    return not isinstance(audio_sha256, str) or audio_sha256 in (
        suspect_audio_sha256_by_video.get(str(youtube_video_id), set())
    )


def _load_objects(paths: Sequence[Path]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: expected a JSON object")
        payloads.append(payload)
    return payloads


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_json_idempotent(path: Path, payload: object) -> None:
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"refusing to overwrite changed revocation: {path}")
        return
    path.write_text(content, encoding="utf-8")
