from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import html
import json
from pathlib import Path
import random
from typing import Any, Sequence

from pastor_transcript_extractor.models import SpeakerObservation
from pastor_transcript_extractor.media_artifacts import ArchivedMediaUnavailableError
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    AudioSpanCache,
    CachedSpan,
    RecordingActivityProfile,
    SpanSpec,
    select_diagnostic_spans,
    validate_reviewed_pair_fixture,
)
from pastor_transcript_extractor.speaker_review_invalidation import (
    load_review_revocations,
    pair_artifact_is_revoked,
)


REVIEW_WORKFLOW_VERSION = "speaker_pair_review_v3"
CLIP_ACTIVITY_POLICY_VERSION = "speaker_pair_clip_activity_v3"
DEFAULT_MIN_NON_SILENT_FRACTION = 0.40
DEFAULT_MIN_CLIP_RMS_DBFS = -52.0
ACTIVITY_FRAME_DURATION_MS = 30.0
ACTIVITY_REFERENCE_PERCENTILE = 0.90
ACTIVITY_THRESHOLD_OFFSET_DB = 15.0
ACTIVITY_MINIMUM_THRESHOLD_DBFS = -60.0
ACTIVITY_MAXIMUM_THRESHOLD_DBFS = -50.0
STANDARD_VARIATION_TAGS = (
    "different_date",
    "different_microphone",
    "different_room",
    "varied_audio_quality",
)


class ObservationQualification(StrEnum):
    QUALIFIED_SINGLE_SPEAKER = "qualified_single_speaker"
    MULTIPLE_SPEAKERS = "multiple_speakers"
    INVALID_AUDIO = "invalid_audio"
    CANNOT_DETERMINE = "cannot_determine"


class PairJudgment(StrEnum):
    SAME_SPEAKER = "same_speaker"
    DIFFERENT_SPEAKER = "different_speaker"
    CANNOT_DETERMINE = "cannot_determine"


class ReviewEvidenceMode(StrEnum):
    AUDIO_ONLY = "audio_only"
    AUDIO_PLUS_VISUAL = "audio_plus_visual"


class InsufficientSpeechActivityError(ValueError):
    def __init__(self, observation_fingerprint: str, summary: dict[str, Any]):
        self.observation_fingerprint = observation_fingerprint
        self.summary = summary
        super().__init__(
            f"insufficient_speech_activity for observation "
            f"{observation_fingerprint}: found {summary['qualified_clip_count']} "
            f"qualified clip(s), require at least {summary['minimum_clip_count']}"
        )


@dataclass(frozen=True, slots=True)
class ReviewDraft:
    pair_id: str
    draft_path: Path
    packet_path: Path
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReviewSubmission:
    event_path: Path
    fixture_path: Path | None
    fixture_status: str


@dataclass(frozen=True, slots=True)
class PreparedReviewObservation:
    spans: tuple[CachedSpan, ...]
    clip_selection: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ObservationReviewPacket:
    manifest_path: Path
    packet_path: Path
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReviewSelectionAuditIssue:
    pair_id: str
    draft_path: Path
    reviewed: bool
    reason_code: str
    actual_fingerprints: tuple[str, ...]
    manifest_fingerprints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewSelectionAudit:
    draft_count: int
    automatic_count: int
    reviewed_count: int
    exact_verified_count: int
    legacy_checked_count: int
    unverifiable_count: int
    issues: tuple[ReviewSelectionAuditIssue, ...]


def audit_review_selection_artifacts(
    evaluation_root: Path,
) -> ReviewSelectionAudit:
    root = evaluation_root.expanduser().resolve()
    revocations = load_review_revocations(root)
    reviewed_pair_ids = set()
    for path in (root / "reviews").glob("*/*.json"):
        review = json.loads(path.read_text(encoding="utf-8"))
        if not pair_artifact_is_revoked(review, revocations):
            reviewed_pair_ids.add(path.parent.name)
    draft_paths = sorted(
        path
        for path in (root / "drafts").glob("*.json")
        if ".rejected." not in path.name
    )
    automatic_count = 0
    active_draft_count = 0
    reviewed_count = 0
    exact_verified_count = 0
    legacy_checked_count = 0
    unverifiable_count = 0
    issues: list[ReviewSelectionAuditIssue] = []
    for path in draft_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: expected a JSON object")
        if pair_artifact_is_revoked(payload, revocations):
            continue
        active_draft_count += 1
        _validate_draft(payload)
        manifest = payload.get("selection_manifest")
        if not isinstance(manifest, dict) or manifest.get(
            "selection_origin"
        ) != "automatic":
            continue
        automatic_count += 1
        pair_id = str(payload["pair_id"])
        if pair_id in reviewed_pair_ids:
            reviewed_count += 1
        actual = tuple(
            sorted(
                str(observation["input_fingerprint"])
                for observation in payload["observations"].values()
            )
        )
        exact = manifest.get("selected_observation_fingerprints")
        if isinstance(exact, dict) and set(exact) == {"a", "b"} and all(
            isinstance(value, str) for value in exact.values()
        ):
            exact_verified_count += 1
            expected = tuple(sorted(str(value) for value in exact.values()))
            if actual != expected:
                issues.append(
                    ReviewSelectionAuditIssue(
                        pair_id=pair_id,
                        draft_path=path,
                        reviewed=pair_id in reviewed_pair_ids,
                        reason_code="selected_observation_fingerprint_mismatch",
                        actual_fingerprints=actual,
                        manifest_fingerprints=expected,
                    )
                )
            continue
        components = manifest.get("profile_growth_components")
        if isinstance(components, list) and all(
            isinstance(component, list) for component in components
        ):
            legacy_checked_count += 1
            expected_members = tuple(
                sorted(
                    {
                        str(fingerprint)
                        for component in components
                        for fingerprint in component
                        if isinstance(fingerprint, str)
                    }
                )
            )
            if not set(actual).issubset(expected_members):
                issues.append(
                    ReviewSelectionAuditIssue(
                        pair_id=pair_id,
                        draft_path=path,
                        reviewed=pair_id in reviewed_pair_ids,
                        reason_code="legacy_profile_growth_pair_mismatch",
                        actual_fingerprints=actual,
                        manifest_fingerprints=expected_members,
                    )
                )
            continue
        unverifiable_count += 1
    return ReviewSelectionAudit(
        draft_count=active_draft_count,
        automatic_count=automatic_count,
        reviewed_count=reviewed_count,
        exact_verified_count=exact_verified_count,
        legacy_checked_count=legacy_checked_count,
        unverifiable_count=unverifiable_count,
        issues=tuple(issues),
    )


def prepare_review_observation(
    *,
    observation: SpeakerObservation,
    audio_path: Path,
    span_cache: AudioSpanCache,
    span_count: int = 5,
    span_duration_seconds: float = 12.0,
    min_qualified_spans: int | None = None,
    min_non_silent_fraction: float = DEFAULT_MIN_NON_SILENT_FRACTION,
    fallback_candidate_multiplier: int = 3,
) -> PreparedReviewObservation:
    """Prepare the exact deterministic clips used by blinded pair review."""
    if fallback_candidate_multiplier < 1:
        raise ValueError("fallback candidate multiplier must be positive")
    if min_qualified_spans is None:
        min_qualified_spans = span_count
    if min_qualified_spans < 1 or min_qualified_spans > span_count:
        raise ValueError("minimum qualified spans must be between one and span count")
    primary_specs = select_diagnostic_spans(
        observation,
        count=span_count,
        duration_seconds=span_duration_seconds,
    )
    if not primary_specs:
        raise ValueError(
            f"observation {observation.input_fingerprint} is too short for review"
        )
    fallback_specs = select_diagnostic_spans(
        observation,
        count=span_count * fallback_candidate_multiplier,
        duration_seconds=span_duration_seconds,
    )
    candidate_specs = _unique_span_specs((*primary_specs, *fallback_specs))
    activity_profile = span_cache.recording_activity_profile(
        audio_path,
        policy_version=CLIP_ACTIVITY_POLICY_VERSION,
        frame_duration_ms=ACTIVITY_FRAME_DURATION_MS,
        reference_percentile=ACTIVITY_REFERENCE_PERCENTILE,
        threshold_offset_db=ACTIVITY_THRESHOLD_OFFSET_DB,
        minimum_threshold_dbfs=ACTIVITY_MINIMUM_THRESHOLD_DBFS,
        maximum_threshold_dbfs=ACTIVITY_MAXIMUM_THRESHOLD_DBFS,
    )
    spans, clip_selection = _prepare_review_spans(
        observation=observation,
        audio_path=audio_path,
        span_cache=span_cache,
        candidate_specs=candidate_specs,
        requested_count=span_count,
        minimum_count=min_qualified_spans,
        min_non_silent_fraction=min_non_silent_fraction,
        activity_profile=activity_profile,
    )
    return PreparedReviewObservation(tuple(spans), clip_selection)


def create_observation_review_packet(
    *,
    observation: SpeakerObservation,
    youtube_video_id: str,
    audio_path: Path,
    span_cache: AudioSpanCache,
    evaluation_root: Path,
) -> ObservationReviewPacket:
    """Create a provenance-bound, unblinded packet for one observation."""
    normalized_audio_sha256 = _source_audio_identity(audio_path)
    if normalized_audio_sha256.startswith("unavailable:"):
        if audio_path.is_symlink():
            raise ArchivedMediaUnavailableError(None, audio_path.resolve(strict=False))
        raise ValueError(f"normalized audio is unavailable: {audio_path}")
    prepared = prepare_review_observation(
        observation=observation,
        audio_path=audio_path,
        span_cache=span_cache,
    )
    stable = {
        "schema_version": 1,
        "workflow_version": REVIEW_WORKFLOW_VERSION,
        "event_kind": "single_observation_review_packet",
        "youtube_video_id": youtube_video_id,
        "youtube_url": f"https://www.youtube.com/watch?v={youtube_video_id}",
        "input_fingerprint": observation.input_fingerprint,
        "observation_window": {
            "start_seconds": observation.start_seconds,
            "end_seconds": observation.end_seconds,
        },
        "normalized_audio_path": str(audio_path.expanduser().resolve()),
        "normalized_audio_sha256": normalized_audio_sha256,
        "clips": [_draft_clip(span) for span in prepared.spans],
        "clip_selection": prepared.clip_selection,
    }
    packet_id = _sha256_json(stable)
    payload = {**stable, "packet_id": packet_id}
    root = evaluation_root / "observation-reviews"
    stem = (
        f"{youtube_video_id}-{observation.input_fingerprint[:12]}-"
        f"{normalized_audio_sha256[:12]}"
    )
    manifest_path = root / f"{stem}.json"
    packet_path = root / f"{stem}.html"
    _write_json_idempotent(manifest_path, payload)
    _write_text_idempotent(packet_path, _observation_review_packet(payload))
    return ObservationReviewPacket(manifest_path, packet_path, payload)


def _observation_review_packet(payload: dict[str, Any]) -> str:
    window = payload["observation_window"]
    clips: list[str] = []
    for index, clip in enumerate(payload["clips"], start=1):
        start = float(clip["start_seconds"])
        end = float(clip["end_seconds"])
        youtube_url = f"{payload['youtube_url']}&t={max(0, int(start))}s"
        audio_url = Path(clip["wav_path"]).expanduser().resolve().as_uri()
        clips.append(
            "<li>"
            f"<strong>Clip {index}: {start:.3f}s–{end:.3f}s</strong> "
            '<a target="_blank" rel="noopener noreferrer" '
            f'href="{html.escape(youtube_url, quote=True)}">'
            f"{html.escape(youtube_url)}</a>"
            '<audio controls preload="metadata" '
            f'src="{html.escape(audio_url, quote=True)}"></audio>'
            "</li>"
        )
    exact_url = html.escape(str(payload["youtube_url"]), quote=True)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Observation review {html.escape(str(payload['youtube_video_id']))}</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem}}li{{margin:1.2rem 0}}audio{{display:block;width:100%;margin-top:.4rem}}</style></head>
<body><h1>Single-observation review</h1>
<p>Observation window: {float(window['start_seconds']):.3f}s–{float(window['end_seconds']):.3f}s</p>
<p>Exact video: <a target="_blank" rel="noopener noreferrer" href="{exact_url}">{exact_url}</a></p>
<ol>{''.join(clips)}</ol></body></html>
"""


def create_review_draft(
    *,
    observation_a: SpeakerObservation,
    observation_b: SpeakerObservation,
    video_id_a: str,
    video_id_b: str,
    audio_path_a: Path,
    audio_path_b: Path,
    span_cache: AudioSpanCache,
    evaluation_root: Path,
    span_count: int = 5,
    span_duration_seconds: float = 12.0,
    min_qualified_spans: int | None = None,
    min_non_silent_fraction: float = DEFAULT_MIN_NON_SILENT_FRACTION,
    fallback_candidate_multiplier: int = 3,
    selection_manifest: dict[str, object] | None = None,
) -> ReviewDraft:
    if observation_a.input_fingerprint == observation_b.input_fingerprint:
        raise ValueError("a pair review requires two distinct observations")
    if min_qualified_spans is None:
        min_qualified_spans = span_count
    ordered_inputs = sorted(
        (
            (observation_a.input_fingerprint, video_id_a, observation_a, audio_path_a),
            (observation_b.input_fingerprint, video_id_b, observation_b, audio_path_b),
        ),
        key=lambda value: value[0],
    )
    source_observations = {
        "source_a": ordered_inputs[0][1:],
        "source_b": ordered_inputs[1][1:],
    }
    expected_audio_sha256 = {
        source_key: _source_audio_identity(Path(values[2]))
        for source_key, values in source_observations.items()
    }
    unavailable_paths = [
        Path(values[2]).resolve(strict=False)
        for source_key, values in source_observations.items()
        if expected_audio_sha256[source_key].startswith("unavailable:")
        and Path(values[2]).is_symlink()
    ]
    if unavailable_paths:
        # Preflight both sources before creating clips, caches, drafts, or manifests.
        raise ArchivedMediaUnavailableError(None, unavailable_paths[0])
    canonical_fingerprints = [value[0] for value in ordered_inputs]
    pair_id = f"pair-{_sha256_json(canonical_fingerprints)[:16]}"
    prior_path = evaluation_root / "drafts" / f"{pair_id}.json"
    if prior_path.exists():
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        revocations = load_review_revocations(evaluation_root)
        if prior.get("draft_id") in revocations.draft_ids:
            replacement_identity = {
                "observations": canonical_fingerprints,
                "normalized_audio_sha256": expected_audio_sha256,
            }
            pair_id = f"pair-{_sha256_json(replacement_identity)[:16]}"
    existing_draft = _load_existing_review_draft(
        pair_id=pair_id,
        evaluation_root=evaluation_root,
        canonical_fingerprints=canonical_fingerprints,
        expected_audio_sha256=expected_audio_sha256,
    )
    if existing_draft is not None:
        return existing_draft
    evidence_mode = _review_evidence_mode(selection_manifest)
    presentation_sources = ["source_a", "source_b"]
    rng = random.Random(pair_id)
    rng.shuffle(presentation_sources)

    observations: dict[str, Any] = {}
    presentation: dict[str, Any] = {}
    for source_key, (video_id, observation, audio_path) in source_observations.items():
        try:
            prepared = prepare_review_observation(
                observation=observation,
                audio_path=audio_path,
                span_cache=span_cache,
                span_count=span_count,
                span_duration_seconds=span_duration_seconds,
                min_qualified_spans=min_qualified_spans,
                min_non_silent_fraction=min_non_silent_fraction,
                fallback_candidate_multiplier=fallback_candidate_multiplier,
            )
        except InsufficientSpeechActivityError as error:
            rejection_path = _record_activity_rejection(
                pair_id=pair_id,
                source_observations=source_observations,
                failed_source_key=source_key,
                error=error,
                selection_manifest=selection_manifest,
                evaluation_root=evaluation_root,
            )
            raise ValueError(f"{error}; recorded selection rejection: {rejection_path}") from None
        spans = prepared.spans
        clip_selection = prepared.clip_selection
        observations[source_key] = {
            "youtube_video_id": video_id,
            "input_fingerprint": observation.input_fingerprint,
            "observation_window": {
                "start_seconds": observation.start_seconds,
                "end_seconds": observation.end_seconds,
            },
            "normalized_audio_sha256": expected_audio_sha256[source_key],
            "clips": [_draft_clip(span) for span in spans],
            "clip_selection": clip_selection,
        }

    for label, source_key in zip(("A", "B"), presentation_sources):
        clips = list(observations[source_key]["clips"])
        rng.shuffle(clips)
        presentation[label] = {
            "source_key": source_key,
            "clips": [clip["wav_sha256"] for clip in clips],
        }

    stable_payload = {
        "schema_version": 1,
        "workflow_version": REVIEW_WORKFLOW_VERSION,
        "review_status": "draft",
        "review_evidence_mode": evidence_mode,
        "pair_id": pair_id,
        "blinding": {
            "packet_hides_video_ids": (
                evidence_mode == ReviewEvidenceMode.AUDIO_ONLY
            ),
            "packet_hides_titles_names_and_channels": True,
            "presentation_order_deterministic": True,
        },
        "observations": observations,
        "presentation": presentation,
    }
    if selection_manifest is not None:
        stable_payload["selection_manifest"] = _selection_manifest_for_presentation(
            selection_manifest,
            presentation,
        )
    draft_id = _sha256_json(stable_payload)
    payload = {**stable_payload, "draft_id": draft_id}
    draft_path = evaluation_root / "drafts" / f"{pair_id}.json"
    packet_path = evaluation_root / "drafts" / f"{pair_id}.html"
    _write_json_idempotent(draft_path, payload)
    packet = _review_packet(payload)
    _write_text_idempotent(packet_path, packet)
    return ReviewDraft(pair_id, draft_path, packet_path, payload)


def _load_existing_review_draft(
    *,
    pair_id: str,
    evaluation_root: Path,
    canonical_fingerprints: Sequence[str],
    expected_audio_sha256: dict[str, str],
) -> ReviewDraft | None:
    """Load an immutable draft when an interrupted review reopens its pair."""
    draft_path = evaluation_root / "drafts" / f"{pair_id}.json"
    if not draft_path.exists():
        return None
    existing = json.loads(draft_path.read_text(encoding="utf-8"))
    if not isinstance(existing, dict):
        raise ValueError(f"{draft_path}: expected a JSON object")
    _validate_draft(existing)
    persisted_fingerprints = sorted(
        str(observation.get("input_fingerprint", ""))
        for observation in existing["observations"].values()
    )
    if persisted_fingerprints != sorted(canonical_fingerprints):
        raise ValueError(f"{draft_path}: observation fingerprints do not match requested pair")
    persisted_audio_sha256 = {
        source_key: observation.get("normalized_audio_sha256")
        for source_key, observation in existing["observations"].items()
    }
    if persisted_audio_sha256 != expected_audio_sha256:
        raise ValueError(
            f"{draft_path}: normalized-audio provenance mismatch; "
            "remove or preserve the stale draft under a different path before regenerating"
        )
    packet_path = evaluation_root / "drafts" / f"{pair_id}.html"
    if not packet_path.exists():
        _write_text_idempotent(packet_path, _review_packet(existing))
    return ReviewDraft(pair_id, draft_path, packet_path, existing)


def submit_review(
    *,
    draft: dict[str, Any],
    qualification_a: ObservationQualification,
    qualification_b: ObservationQualification,
    pair_judgment: PairJudgment,
    reviewer: str,
    reviewed_at: str | None,
    variation_tags: Sequence[str],
    notes: str,
    approval_confirmed: bool,
    evaluation_root: Path,
) -> ReviewSubmission:
    _validate_draft(draft)
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    qualified = (
        qualification_a == ObservationQualification.QUALIFIED_SINGLE_SPEAKER
        and qualification_b == ObservationQualification.QUALIFIED_SINGLE_SPEAKER
    )
    evidence_mode = ReviewEvidenceMode(
        draft.get("review_evidence_mode", ReviewEvidenceMode.AUDIO_ONLY)
    )
    identity_evidence_eligible = (
        qualified
        and pair_judgment
        in {PairJudgment.SAME_SPEAKER, PairJudgment.DIFFERENT_SPEAKER}
        and approval_confirmed
    )
    if not qualified and pair_judgment != PairJudgment.CANNOT_DETERMINE:
        raise ValueError("an unqualified observation requires cannot_determine pair judgment")
    normalized_tags = sorted({tag.strip() for tag in variation_tags if tag.strip()})
    reviewed_at_value = reviewed_at or datetime.now(timezone.utc).isoformat()
    event_without_id = {
        "schema_version": 1,
        "workflow_version": REVIEW_WORKFLOW_VERSION,
        "event_kind": "speaker_pair_human_review",
        "pair_id": draft["pair_id"],
        "draft_id": draft["draft_id"],
        "reviewer": reviewer,
        "reviewed_at": reviewed_at_value,
        "qualification": {
            "A": qualification_a,
            "B": qualification_b,
        },
        "pair_judgment": pair_judgment,
        "review_evidence_mode": evidence_mode,
        "variation_tags": normalized_tags,
        "notes": notes.strip(),
        "clip_quality": _review_clip_quality(draft),
        "approval_confirmed": approval_confirmed,
        "identity_evidence_eligible": identity_evidence_eligible,
        "fixture_eligible": (
            identity_evidence_eligible
            and evidence_mode == ReviewEvidenceMode.AUDIO_ONLY
        ),
    }
    if "selection_manifest" in draft:
        event_without_id["selection_manifest"] = draft["selection_manifest"]
    event_id = _sha256_json(event_without_id)
    event = {**event_without_id, "review_event_id": event_id}
    event_path = (
        evaluation_root / "reviews" / draft["pair_id"] / f"{event_id}.json"
    )
    _write_json_idempotent(event_path, event)

    if not event["fixture_eligible"]:
        return ReviewSubmission(
            event_path,
            None,
            (
                "identity_only"
                if event["identity_evidence_eligible"]
                else "not_eligible"
            ),
        )

    fixture = _fixture_from_review(draft, event)
    validate_reviewed_pair_fixture(fixture)
    fixture_path = evaluation_root / "fixtures" / f"{draft['pair_id']}.json"
    if not fixture_path.exists():
        _write_json_idempotent(fixture_path, fixture)
        return ReviewSubmission(event_path, fixture_path, "created")

    existing = json.loads(fixture_path.read_text(encoding="utf-8"))
    validate_reviewed_pair_fixture(existing)
    same_evidence = _fixture_evidence_identity(existing) == _fixture_evidence_identity(fixture)
    same_judgment = existing.get("expected_outcome") == fixture["expected_outcome"]
    if same_evidence and same_judgment:
        return ReviewSubmission(event_path, fixture_path, "existing_consistent")
    return ReviewSubmission(event_path, fixture_path, "existing_conflict_preserved")


def _fixture_from_review(draft: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for label, fixture_side in (("A", "a"), ("B", "b")):
        source_key = draft["presentation"][label]["source_key"]
        source = draft["observations"][source_key]
        observations[fixture_side] = {
            "youtube_video_id": source["youtube_video_id"],
            "input_fingerprint": source["input_fingerprint"],
            "reviewed_spans": [
                {
                    "start_seconds": clip["start_seconds"],
                    "end_seconds": clip["end_seconds"],
                    "wav_sha256": clip["wav_sha256"],
                    "rms_dbfs": clip["rms_dbfs"],
                    "non_silent_fraction": clip["non_silent_fraction"],
                }
                for clip in source["clips"]
            ],
        }
    fixture = {
        "schema_version": 1,
        "workflow_version": REVIEW_WORKFLOW_VERSION,
        "pair_id": draft["pair_id"],
        "review_status": "approved",
        "reviewer": event["reviewer"],
        "reviewed_at": event["reviewed_at"],
        "review_event_id": event["review_event_id"],
        "expected_outcome": event["pair_judgment"],
        "review_evidence_mode": ReviewEvidenceMode.AUDIO_ONLY,
        "variation_tags": event["variation_tags"],
        "notes": event["notes"],
        "qualification": event["qualification"],
        "observations": observations,
    }
    if "selection_manifest" in draft:
        fixture["selection_manifest"] = draft["selection_manifest"]
        partitions = draft["selection_manifest"].get("evaluation_partitions")
        if (
            isinstance(partitions, dict)
            and partitions.get("a")
            and partitions.get("a") == partitions.get("b")
        ):
            fixture["evaluation_partition"] = partitions["a"]
    return fixture


def _review_packet(draft: dict[str, Any]) -> str:
    clips_by_hash = {
        clip["wav_sha256"]: clip
        for observation in draft["observations"].values()
        for clip in observation["clips"]
    }
    groups: list[str] = []
    evidence_mode = ReviewEvidenceMode(
        draft.get("review_evidence_mode", ReviewEvidenceMode.AUDIO_ONLY)
    )
    packet_title = (
        "Blinded speaker pair review"
        if evidence_mode == ReviewEvidenceMode.AUDIO_ONLY
        else "Audio-plus-visual speaker identity review"
    )
    for label in ("A", "B"):
        source_key = draft["presentation"][label]["source_key"]
        observation = draft["observations"][source_key]
        players: list[str] = []
        for index, clip_hash in enumerate(draft["presentation"][label]["clips"], start=1):
            clip = clips_by_hash[clip_hash]
            source = Path(clip["wav_path"]).expanduser().resolve().as_uri()
            video_link = ""
            if evidence_mode == ReviewEvidenceMode.AUDIO_PLUS_VISUAL:
                start_seconds = max(0, int(float(clip["start_seconds"])))
                video_url = (
                    "https://www.youtube.com/watch?v="
                    f"{observation['youtube_video_id']}&t={start_seconds}s"
                )
                minutes, seconds = divmod(start_seconds, 60)
                video_link = (
                    '<a class="source-link" target="_blank" '
                    'rel="noopener noreferrer" '
                    f'href="{html.escape(video_url, quote=True)}">'
                    f"View video at {minutes}:{seconds:02d}</a>"
                )
            players.append(
                f'<li><span>Clip {index}</span><div><audio controls '
                f'preload="metadata" src="{html.escape(source, quote=True)}">'
                f"</audio>{video_link}</div></li>"
            )
        groups.append(
            f'<section><h2>Observation {label}</h2><ol>{"".join(players)}</ol></section>'
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{packet_title}</title>
  <style>
    body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 920px; margin: 2rem auto; padding: 0 1rem; }}
    section {{ border: 1px solid #ccc; border-radius: 8px; margin: 1rem 0; padding: 1rem; }}
    li {{ margin: .8rem 0; display: grid; grid-template-columns: 6rem 1fr; align-items: center; }}
    audio {{ width: 100%; }}
    .source-link {{ display: inline-block; margin-top: .35rem; }}
    .warning {{ background: #fff4d6; border-left: 4px solid #b77900; padding: .8rem; }}
  </style>
</head>
<body>
  <h1>Speaker pair review</h1>
  <p class="warning">{(
      "Judge only the voices in these clips. Names, titles, channels, and metadata are intentionally hidden."
      if evidence_mode == ReviewEvidenceMode.AUDIO_ONLY
      else "Timestamp links are available for visual identity confirmation. Titles, names, and channels are not shown in this packet."
  )}</p>
  <p>First decide whether every clip in each observation contains one consistent principal speaker. Compare A and B only if both observations qualify.</p>
  {''.join(groups)}
</body>
</html>
"""


def _review_evidence_mode(
    selection_manifest: dict[str, object] | None,
) -> ReviewEvidenceMode:
    selection_goal = (
        selection_manifest.get("selection_goal")
        if selection_manifest is not None
        else None
    )
    if selection_goal in {"profile-growth", "automation-readiness"}:
        return ReviewEvidenceMode.AUDIO_PLUS_VISUAL
    return ReviewEvidenceMode.AUDIO_ONLY


def _draft_clip(span: CachedSpan) -> dict[str, Any]:
    return {
        "start_seconds": span.start_seconds,
        "end_seconds": span.end_seconds,
        "wav_path": span.wav_path,
        "wav_sha256": span.wav_sha256,
        "duration_seconds": span.duration_seconds,
        "rms_dbfs": span.rms_dbfs,
        "clipped_fraction": span.clipped_fraction,
        "non_silent_fraction": span.non_silent_fraction,
    }


def _prepare_review_spans(
    *,
    observation: SpeakerObservation,
    audio_path: Path,
    span_cache: AudioSpanCache,
    candidate_specs: Sequence[SpanSpec],
    requested_count: int,
    minimum_count: int,
    min_non_silent_fraction: float,
    activity_profile: RecordingActivityProfile,
) -> tuple[list[CachedSpan], dict[str, Any]]:
    if requested_count < 2 or minimum_count < 2 or minimum_count > requested_count:
        raise ValueError("review clip counts require 2 <= minimum <= requested")
    if not 0.0 <= min_non_silent_fraction <= 1.0:
        raise ValueError("minimum non-silent fraction must be between zero and one")
    qualified: list[CachedSpan] = []
    attempts: list[dict[str, Any]] = []
    for spec in candidate_specs:
        span = span_cache.prepare(
            observation=observation,
            source_audio_path=audio_path,
            span=spec,
        )
        non_silent_fraction = span_cache.measure_span_activity(
            span,
            silence_threshold_dbfs=(
                activity_profile.silence_threshold_dbfs
            ),
            frame_duration_ms=activity_profile.frame_duration_ms,
        )
        span = replace(
            span,
            non_silent_fraction=non_silent_fraction,
        )
        activity_available = span.non_silent_fraction is not None
        accepted = (
            activity_available
            and span.rms_dbfs >= DEFAULT_MIN_CLIP_RMS_DBFS
            and span.non_silent_fraction >= min_non_silent_fraction
        )
        attempts.append(
            {
                "start_seconds": span.start_seconds,
                "end_seconds": span.end_seconds,
                "wav_sha256": span.wav_sha256,
                "rms_dbfs": span.rms_dbfs,
                "non_silent_fraction": span.non_silent_fraction,
                "accepted": accepted,
                "reason": (
                    "qualified"
                    if accepted
                    else (
                        "activity_measurement_unavailable"
                        if not activity_available
                        else (
                            "clip_rms_too_low"
                            if span.rms_dbfs < DEFAULT_MIN_CLIP_RMS_DBFS
                            else "majority_silence"
                        )
                    )
                ),
            }
        )
        if accepted:
            qualified.append(span)
            if len(qualified) == requested_count:
                break
    summary = {
        "policy_version": CLIP_ACTIVITY_POLICY_VERSION,
        "requested_clip_count": requested_count,
        "minimum_clip_count": minimum_count,
        "candidate_clip_count": len(candidate_specs),
        "prepared_clip_count": len(attempts),
        "qualified_clip_count": len(qualified),
        "selection_outcome": (
            "complete" if len(qualified) == requested_count else "partial"
        ),
        "thresholds": {
            "min_rms_dbfs": DEFAULT_MIN_CLIP_RMS_DBFS,
            "min_non_silent_fraction": min_non_silent_fraction,
        },
        "recording_activity_profile": {
            key: value
            for key, value in asdict(activity_profile).items()
            if key != "cache_hit"
        },
        "attempts": attempts,
    }
    if len(qualified) < minimum_count:
        raise InsufficientSpeechActivityError(
            observation.input_fingerprint,
            summary,
        )
    return qualified, summary


def _unique_span_specs(specs: Sequence[SpanSpec]) -> tuple[SpanSpec, ...]:
    unique: list[SpanSpec] = []
    seen: set[tuple[float, float]] = set()
    for spec in specs:
        key = (spec.start_seconds, spec.end_seconds)
        if key not in seen:
            seen.add(key)
            unique.append(spec)
    return tuple(unique)


def _review_clip_quality(draft: dict[str, Any]) -> dict[str, Any]:
    quality: dict[str, Any] = {}
    for label in ("A", "B"):
        source_key = draft["presentation"][label]["source_key"]
        source = draft["observations"][source_key]
        quality[label] = {
            "clip_selection": source.get("clip_selection"),
            "clips": [
                {
                    "wav_sha256": clip["wav_sha256"],
                    "rms_dbfs": clip.get("rms_dbfs"),
                    "non_silent_fraction": clip.get("non_silent_fraction"),
                }
                for clip in source["clips"]
            ],
        }
    return quality


def _record_activity_rejection(
    *,
    pair_id: str,
    source_observations: dict[
        str, tuple[str, SpeakerObservation, Path]
    ],
    failed_source_key: str,
    error: InsufficientSpeechActivityError,
    selection_manifest: dict[str, object] | None,
    evaluation_root: Path,
) -> Path:
    observations = {
        source_key: {
            "youtube_video_id": video_id,
            "input_fingerprint": observation.input_fingerprint,
            "observation_window": {
                "start_seconds": observation.start_seconds,
                "end_seconds": observation.end_seconds,
            },
        }
        for source_key, (video_id, observation, _audio_path) in source_observations.items()
    }
    observations[failed_source_key]["clip_selection"] = error.summary
    stable = {
        "schema_version": 1,
        "workflow_version": REVIEW_WORKFLOW_VERSION,
        "event_kind": "speaker_pair_automatic_selection_rejection",
        "review_status": "rejected_automatically",
        "pair_id": pair_id,
        "reason": "insufficient_speech_activity",
        "failed_observation_fingerprint": error.observation_fingerprint,
        "observations": observations,
    }
    if selection_manifest is not None:
        stable["selection_manifest"] = selection_manifest
    rejection_id = _sha256_json(stable)
    payload = {**stable, "rejection_id": rejection_id}
    path = evaluation_root / "drafts" / f"{pair_id}.rejected.{rejection_id[:12]}.json"
    _write_json_idempotent(path, payload)
    return path


def _fixture_evidence_identity(fixture: dict[str, Any]) -> object:
    return {
        side: {
            "input_fingerprint": fixture["observations"][side]["input_fingerprint"],
            "wav_sha256": [
                span["wav_sha256"] for span in fixture["observations"][side]["reviewed_spans"]
            ],
        }
        for side in ("a", "b")
    }


def _selection_manifest_for_presentation(
    selection_manifest: dict[str, object],
    presentation: dict[str, Any],
) -> dict[str, object]:
    """Align canonical selector a/b reuse counts with blinded packet A/B sides."""
    manifest = dict(selection_manifest)
    for field in (
        "selected_observation_fingerprints",
        "observation_prior_use",
        "source_family_ids",
        "source_family_prior_use",
        "evaluation_partitions",
    ):
        side_values = selection_manifest.get(field)
        if not isinstance(side_values, dict) or set(side_values) != {"a", "b"}:
            continue
        canonical = {
            "source_a": side_values["a"],
            "source_b": side_values["b"],
        }
        manifest[field] = {
            "a": canonical[presentation["A"]["source_key"]],
            "b": canonical[presentation["B"]["source_key"]],
        }
    return manifest


def _validate_draft(draft: dict[str, Any]) -> None:
    if draft.get("schema_version") != 1 or draft.get("review_status") != "draft":
        raise ValueError("invalid speaker-pair review draft")
    stable = {key: value for key, value in draft.items() if key != "draft_id"}
    if draft.get("draft_id") != _sha256_json(stable):
        raise ValueError("speaker-pair review draft fingerprint mismatch")
    for label in ("A", "B"):
        source_key = draft.get("presentation", {}).get(label, {}).get("source_key")
        if source_key not in draft.get("observations", {}):
            raise ValueError(f"draft presentation {label} has no source observation")
        hashes = draft["presentation"][label].get("clips")
        available = {
            clip["wav_sha256"] for clip in draft["observations"][source_key].get("clips", [])
        }
        if not isinstance(hashes, list) or len(hashes) < 2 or set(hashes) != available:
            raise ValueError(f"draft presentation {label} does not preserve exact clips")


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source_audio_identity(path: Path) -> str:
    """Return content identity; the fallback supports injected test span caches."""
    try:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return f"unavailable:{path}"


def _write_json_idempotent(path: Path, payload: object) -> None:
    _write_text_idempotent(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text_idempotent(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"refusing to overwrite changed review artifact: {path}")
        return
    path.write_text(content, encoding="utf-8")
