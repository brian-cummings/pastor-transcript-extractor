from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Callable

from pastor_transcript_extractor.config import AppPaths
from pastor_transcript_extractor.filesystem_capacity import (
    FilesystemCapacity,
    filesystem_capacity,
)
from pastor_transcript_extractor.media_artifacts import (
    ArchivedMediaUnavailableError,
    MediaVerificationCache,
    get_authoritative_normalized_media_artifact,
    get_archive_safe_normalized_media_artifact,
    verify_media_artifact,
)
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    AcousticEvidenceUnavailableError,
    AudioSpanCache,
)
from pastor_transcript_extractor.speaker_pair_eligibility import (
    assess_automatic_speaker_observation,
)
from pastor_transcript_extractor.models import (
    MediaArchiveDestination,
    MediaArchiveEntry,
    MediaArtifact,
)
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class ArchiveItemResult:
    media_artifact_id: int
    source_path: Path
    archive_path: Path
    outcome: str
    detail: str | None


@dataclass(frozen=True, slots=True)
class ArchiveProgressEvent:
    index: int
    total: int
    media_artifact_id: int
    source_path: Path
    archive_path: Path
    stage: str
    outcome: str | None = None
    detail: str | None = None


ArchiveProgressCallback = Callable[[ArchiveProgressEvent], None]


@dataclass(frozen=True, slots=True)
class ArchivePreflightEvent:
    check: str
    status: str
    detail: str


ArchivePreflightCallback = Callable[[ArchivePreflightEvent], None]


@dataclass(frozen=True, slots=True)
class AudioSweepProgressEvent:
    index: int
    total: int
    path: Path
    stage: str


AudioSweepProgressCallback = Callable[[AudioSweepProgressEvent], None]


@dataclass(frozen=True, slots=True)
class AudioSweepItem:
    path: Path
    byte_size: int
    category: str
    outcome: str
    detail: str
    media_artifact_id: int | None = None
    archive_path: Path | None = None


@dataclass(frozen=True, slots=True)
class AudioSweepResult:
    items: tuple[AudioSweepItem, ...]
    applied: bool

    @property
    def counts(self) -> dict[str, int]:
        return {
            outcome: sum(item.outcome == outcome for item in self.items)
            for outcome in sorted({item.outcome for item in self.items})
        }

    @property
    def bytes_by_outcome(self) -> dict[str, int]:
        return {
            outcome: sum(
                item.byte_size for item in self.items if item.outcome == outcome
            )
            for outcome in sorted({item.outcome for item in self.items})
        }

    @property
    def reclaimable_bytes(self) -> int:
        return sum(
            item.byte_size
            for item in self.items
            if item.outcome in {"would_link_to_archive", "linked_to_archive"}
        )

CANONICAL_CLIP_PREPARATION_POLICY_VERSION = "canonical_speaker_clips_v1"
CANONICAL_CLIP_CACHE_NAMESPACE = "canonical-audio"


@dataclass(frozen=True, slots=True)
class CanonicalAudioPreparationItem:
    video_id: int
    youtube_video_id: str
    outcome: str
    reason: str
    media_artifact_id: int | None = None
    observation_id: int | None = None
    clip_count: int = 0


@dataclass(frozen=True, slots=True)
class CanonicalAudioPreparationResult:
    items: tuple[CanonicalAudioPreparationItem, ...]
    dry_run: bool

    @property
    def counts(self) -> dict[str, int]:
        return {
            outcome: sum(item.outcome == outcome for item in self.items)
            for outcome in (
                "prepared",
                "would_prepare",
                "already_prepared",
                "deferred",
                "blocked",
                "failed",
            )
        }


@dataclass(frozen=True, slots=True)
class CanonicalAudioPreparationProgressEvent:
    index: int
    total: int
    video_id: int
    youtube_video_id: str
    stage: str
    outcome: str | None = None
    detail: str | None = None


CanonicalAudioPreparationProgressCallback = Callable[
    [CanonicalAudioPreparationProgressEvent], None
]


@dataclass(frozen=True, slots=True)
class NormalizedArchiveEligibility:
    video_id: int
    youtube_video_id: str
    artifact: MediaArtifact | None
    eligible: bool
    reason: str
    clip_preparation_status: str


@dataclass(frozen=True, slots=True)
class ArchiveRunResult:
    destination: MediaArchiveDestination
    eligible: int
    items: tuple[ArchiveItemResult, ...]
    eligibility: tuple[NormalizedArchiveEligibility, ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        counts = {
            "archived": 0,
            "already_archived": 0,
            "destination_unavailable": 0,
            "failed": 0,
            "would_archive": 0,
        }
        for item in self.items:
            counts[item.outcome] += 1
        return counts


@dataclass(frozen=True, slots=True)
class ArchiveStatusReport:
    destination: MediaArchiveDestination | None
    destination_accessible: bool
    entries: tuple[MediaArchiveEntry, ...]
    source_entries: tuple[MediaArchiveEntry, ...] = ()
    normalized_entries: tuple[MediaArchiveEntry, ...] = ()
    normalized_eligibility: tuple[NormalizedArchiveEligibility, ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        return {
            status: sum(entry.status == status for entry in self.entries)
            for status in ("pending", "archived", "failed")
        }


def configure_archive_destination(
    database: Database, archive_root: Path
) -> MediaArchiveDestination:
    root = archive_root.expanduser().resolve(strict=False)
    return database.configure_media_archive_destination(str(root))


def archive_source_media(
    database: Database,
    app_paths: AppPaths,
    *,
    archive_root: Path | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    video_ids: set[int] | None = None,
    wait_for_lock: bool = False,
    lock_retry_seconds: float = 1.0,
    progress_callback: ArchiveProgressCallback | None = None,
    preflight_callback: ArchivePreflightCallback | None = None,
) -> ArchiveRunResult:
    with _archive_lock(
        app_paths.root,
        wait_for_lock=wait_for_lock,
        retry_seconds=lock_retry_seconds,
        preflight_callback=preflight_callback,
    ):
        _notify_preflight(preflight_callback, "archive lock", "passed", "exclusive lock acquired")
        return _archive_source_media_locked(
            database,
            app_paths,
            archive_root=archive_root,
            dry_run=dry_run,
            limit=limit,
            video_ids=video_ids,
            progress_callback=progress_callback,
            preflight_callback=preflight_callback,
            artifact_kind="source_audio",
        )


def archive_normalized_media(
    database: Database,
    app_paths: AppPaths,
    *,
    archive_root: Path | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    video_ids: set[int] | None = None,
    all_eligible: bool = False,
    wait_for_lock: bool = False,
    lock_retry_seconds: float = 1.0,
    progress_callback: ArchiveProgressCallback | None = None,
    preflight_callback: ArchivePreflightCallback | None = None,
) -> ArchiveRunResult:
    if video_ids is None and not all_eligible:
        raise ValueError("Pass --youtube-video-id or --all-eligible")
    with _archive_lock(
        app_paths.root,
        wait_for_lock=wait_for_lock,
        retry_seconds=lock_retry_seconds,
        preflight_callback=preflight_callback,
    ):
        _notify_preflight(preflight_callback, "archive lock", "passed", "exclusive lock acquired")
        return _archive_source_media_locked(
            database,
            app_paths,
            archive_root=archive_root,
            dry_run=dry_run,
            limit=limit,
            video_ids=video_ids,
            progress_callback=progress_callback,
            preflight_callback=preflight_callback,
            artifact_kind="normalized_audio",
        )


def persist_cached_canonical_clip_preparations(
    database: Database,
    app_paths: AppPaths,
    *,
    cache_root: Path,
    video_ids: set[int] | None = None,
) -> int:
    """Promote exact source-bound cached spans into normalized archive proofs."""
    span_root = cache_root.expanduser().resolve() / "spans"
    if not span_root.is_dir():
        return 0
    cached_by_observation: dict[tuple[str, str], list[Path]] = {}
    for manifest_path in sorted(span_root.glob("*.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            item = payload["input"]
            span = payload["span"]
            fingerprint = item["observation_fingerprint"]
            source_sha256 = item["source_audio_sha256"]
            wav_path = Path(span["wav_path"])
            wav_sha256 = span["wav_sha256"]
        except (OSError, UnicodeError, KeyError, TypeError, json.JSONDecodeError):
            continue
        if (
            not isinstance(fingerprint, str)
            or not isinstance(source_sha256, str)
            or not isinstance(wav_sha256, str)
            or not wav_path.is_file()
            or _sha256_file(wav_path) != wav_sha256
        ):
            continue
        cached_by_observation.setdefault(
            (fingerprint, source_sha256), []
        ).append(wav_path)

    written = 0
    for video in database.list_videos():
        if video_ids is not None and video.id not in video_ids:
            continue
        observation = database.get_latest_speaker_observation_for_video(video.id)
        if observation is None:
            continue
        artifact, availability = get_authoritative_normalized_media_artifact(
            database, video.id, require_isolated_sermon=False
        )
        if artifact is None or availability is None:
            continue
        clip_paths = tuple(
            sorted(
                set(
                    cached_by_observation.get(
                        (observation.input_fingerprint, artifact.content_sha256),
                        (),
                    )
                ),
                key=str,
            )
        )
        if not clip_paths:
            continue
        write_canonical_clip_preparation_manifest(
            app_paths,
            artifact,
            observation,
            clip_paths=clip_paths,
        )
        written += 1
    return written


def prepare_canonical_audio(
    database: Database,
    app_paths: AppPaths,
    *,
    cache_root: Path,
    video_ids: set[int] | None = None,
    all_eligible: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
    wait_for_lock: bool = False,
    lock_retry_seconds: float = 1.0,
    progress_callback: CanonicalAudioPreparationProgressCallback | None = None,
) -> CanonicalAudioPreparationResult:
    """Prepare canonical speaker inputs independently of comparison workflows."""
    if video_ids is None and not all_eligible:
        raise ValueError("Pass --youtube-video-id or --all-eligible")
    if limit is not None and limit < 1:
        raise ValueError("Canonical preparation limit must be positive")
    with _archive_lock(
        app_paths.root,
        wait_for_lock=wait_for_lock,
        retry_seconds=lock_retry_seconds,
    ):
        return _prepare_canonical_audio_locked(
            database,
            app_paths,
            cache_root=cache_root,
            video_ids=video_ids,
            dry_run=dry_run,
            limit=limit,
            progress_callback=progress_callback,
        )


def _prepare_canonical_audio_locked(
    database: Database,
    app_paths: AppPaths,
    *,
    cache_root: Path,
    video_ids: set[int] | None,
    dry_run: bool,
    limit: int | None,
    progress_callback: CanonicalAudioPreparationProgressCallback | None,
) -> CanonicalAudioPreparationResult:
    candidates = []
    for video in database.list_videos():
        if video_ids is not None and video.id not in video_ids:
            continue
        eligibility = assess_automatic_speaker_observation(
            database,
            video.id,
            verify_media=False,
        )
        observation = eligibility.observation
        if observation is None:
            observation = database.get_latest_speaker_observation_for_video(video.id)
        # Non-sermons and finalized recordings without a clip observation are
        # intentionally outside this lifecycle stage.
        if observation is None or eligibility.reason_code in {
            "extraction_unavailable",
            "extraction_artifact_unreadable",
            "extraction_artifact_malformed",
            "disposition_missing_or_malformed",
            "disposition_not_accepted",
            "sermon_window_invalid",
        }:
            continue
        candidates.append((video, eligibility, observation))
    if limit is not None:
        candidates = candidates[:limit]

    span_cache = AudioSpanCache(
        cache_root.expanduser().resolve()
        / CANONICAL_CLIP_CACHE_NAMESPACE
        / CANONICAL_CLIP_PREPARATION_POLICY_VERSION
    )
    verification_cache = MediaVerificationCache(
        app_paths.logs / "canonical-audio-verification"
    )
    items: list[CanonicalAudioPreparationItem] = []
    total = len(candidates)
    for index, (video, eligibility, observation) in enumerate(candidates, start=1):
        _notify_canonical_progress(
            progress_callback,
            index=index,
            total=total,
            video=video,
            stage="checking",
        )
        if not eligibility.eligible:
            item = CanonicalAudioPreparationItem(
                video.id,
                video.youtube_video_id,
                "blocked",
                eligibility.reason_code,
                observation_id=observation.id,
            )
            items.append(item)
            _notify_canonical_item(progress_callback, index, total, video, item)
            continue

        try:
            artifact, availability = get_authoritative_normalized_media_artifact(
                database,
                video.id,
                require_isolated_sermon=False,
                verification_cache=verification_cache,
            )
        except ArchivedMediaUnavailableError:
            item = CanonicalAudioPreparationItem(
                video.id,
                video.youtube_video_id,
                "deferred",
                "archived_media_unavailable",
                observation_id=observation.id,
            )
            items.append(item)
            _notify_canonical_item(progress_callback, index, total, video, item)
            continue
        except (OSError, RuntimeError, ValueError) as error:
            item = CanonicalAudioPreparationItem(
                video.id,
                video.youtube_video_id,
                "failed",
                f"{type(error).__name__}: {error}",
                observation_id=observation.id,
            )
            items.append(item)
            _notify_canonical_item(progress_callback, index, total, video, item)
            continue
        if (
            artifact is not None
            and availability is not None
            and availability.status == "archived_media_unavailable"
        ):
            item = CanonicalAudioPreparationItem(
                video.id,
                video.youtube_video_id,
                "deferred",
                "archived_media_unavailable",
                media_artifact_id=artifact.id,
                observation_id=observation.id,
            )
            items.append(item)
            _notify_canonical_item(progress_callback, index, total, video, item)
            continue
        if (
            artifact is None
            or availability is None
            or not availability.verified
        ):
            item = CanonicalAudioPreparationItem(
                video.id,
                video.youtube_video_id,
                "blocked",
                availability.status if availability is not None else "normalized_audio_unavailable",
                media_artifact_id=artifact.id if artifact is not None else None,
                observation_id=observation.id,
            )
            items.append(item)
            _notify_canonical_item(progress_callback, index, total, video, item)
            continue

        preparation_status = _canonical_clip_preparation_status(
            artifact,
            observation,
            CANONICAL_CLIP_PREPARATION_POLICY_VERSION,
        )
        if preparation_status == "current":
            item = CanonicalAudioPreparationItem(
                video.id,
                video.youtube_video_id,
                "already_prepared",
                "canonical preparation is current",
                media_artifact_id=artifact.id,
                observation_id=observation.id,
            )
            items.append(item)
            _notify_canonical_item(progress_callback, index, total, video, item)
            continue
        if dry_run:
            item = CanonicalAudioPreparationItem(
                video.id,
                video.youtube_video_id,
                "would_prepare",
                f"canonical preparation is {preparation_status}",
                media_artifact_id=artifact.id,
                observation_id=observation.id,
                clip_count=len(eligibility.diagnostic_spans),
            )
            items.append(item)
            _notify_canonical_item(progress_callback, index, total, video, item)
            continue

        try:
            _notify_canonical_progress(
                progress_callback,
                index=index,
                total=total,
                video=video,
                stage="preparing_clips",
            )
            clips = tuple(
                span_cache.prepare(
                    observation=observation,
                    source_audio_path=Path(artifact.artifact_path),
                    span=span,
                    expected_source_audio_sha256=artifact.content_sha256,
                    generation_policy_version=(
                        CANONICAL_CLIP_PREPARATION_POLICY_VERSION
                    ),
                )
                for span in eligibility.diagnostic_spans
            )
            if not clips:
                raise ValueError("no canonical diagnostic spans were selected")
            write_canonical_clip_preparation_manifest(
                app_paths,
                artifact,
                observation,
                clip_paths=tuple(Path(clip.wav_path) for clip in clips),
            )
            if (
                _canonical_clip_preparation_status(
                    artifact,
                    observation,
                    CANONICAL_CLIP_PREPARATION_POLICY_VERSION,
                )
                != "current"
            ):
                raise RuntimeError("canonical preparation manifest did not verify")
            item = CanonicalAudioPreparationItem(
                video.id,
                video.youtube_video_id,
                "prepared",
                "canonical clips and manifest prepared",
                media_artifact_id=artifact.id,
                observation_id=observation.id,
                clip_count=len(clips),
            )
        except ArchivedMediaUnavailableError:
            item = CanonicalAudioPreparationItem(
                video.id,
                video.youtube_video_id,
                "deferred",
                "archived_media_unavailable",
                media_artifact_id=artifact.id,
                observation_id=observation.id,
            )
        except (
            AcousticEvidenceUnavailableError,
            OSError,
            RuntimeError,
            ValueError,
            subprocess.SubprocessError,
        ) as error:
            item = CanonicalAudioPreparationItem(
                video.id,
                video.youtube_video_id,
                "failed",
                f"{type(error).__name__}: {error}",
                media_artifact_id=artifact.id,
                observation_id=observation.id,
            )
        items.append(item)
        _notify_canonical_item(progress_callback, index, total, video, item)
    return CanonicalAudioPreparationResult(tuple(items), dry_run)


def _notify_canonical_progress(
    callback: CanonicalAudioPreparationProgressCallback | None,
    *,
    index: int,
    total: int,
    video,
    stage: str,
    outcome: str | None = None,
    detail: str | None = None,
) -> None:
    if callback is not None:
        callback(
            CanonicalAudioPreparationProgressEvent(
                index=index,
                total=total,
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                stage=stage,
                outcome=outcome,
                detail=detail,
            )
        )


def _notify_canonical_item(callback, index, total, video, item) -> None:
    _notify_canonical_progress(
        callback,
        index=index,
        total=total,
        video=video,
        stage="complete",
        outcome=item.outcome,
        detail=item.reason,
    )


def media_archive_lock_held(app_root: Path) -> bool:
    """Return whether another process currently holds the media archive lock."""
    lock_path = app_root / ".media-archive.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return False


def _archive_source_media_locked(
    database: Database,
    app_paths: AppPaths,
    *,
    archive_root: Path | None,
    dry_run: bool,
    limit: int | None,
    video_ids: set[int] | None,
    progress_callback: ArchiveProgressCallback | None,
    preflight_callback: ArchivePreflightCallback | None,
    artifact_kind: str,
) -> ArchiveRunResult:
    destination = (
        configure_archive_destination(database, archive_root)
        if archive_root is not None
        else database.get_active_media_archive_destination()
    )
    if destination is None:
        raise ValueError("No media archive destination is configured")

    root = Path(destination.archive_root)
    _notify_preflight(preflight_callback, "destination", "configured", str(root))
    destination_available, unavailable_detail, capacity = _check_destination(
        root, preflight_callback
    )
    existing_entries = database.list_media_archive_entries()
    videos = database.list_videos()
    artifacts_by_video = {
        video.id: database.list_media_artifacts_for_video(video.id)
        for video in videos
    }
    artifact_kind_by_id = {
        artifact.id: artifact.artifact_kind
        for artifacts in artifacts_by_video.values()
        for artifact in artifacts
    }
    artifact_video_id_by_id = {
        artifact.id: artifact.video_id
        for artifacts in artifacts_by_video.values()
        for artifact in artifacts
    }
    relevant_entries = [
        entry
        for entry in existing_entries
        if artifact_kind_by_id.get(entry.media_artifact_id) == artifact_kind
    ]
    state_counts = {
        status: sum(entry.status == status for entry in relevant_entries)
        for status in ("pending", "archived", "failed")
    }
    _notify_preflight(
        preflight_callback,
        "persisted state",
        "ready",
        ", ".join(f"{key}={value}" for key, value in state_counts.items()),
    )
    _notify_preflight(
        preflight_callback,
        "eligibility",
        "running",
        (
            "verifying normalized audio for new, pending, and failed sources; "
            "persisted archived sources are skipped"
            if artifact_kind == "source_audio"
            else "evaluating authoritative normalized audio and canonical clip "
            "preparation; persisted archived normalized artifacts are skipped"
        ),
    )
    archived_artifact_ids = {
        entry.media_artifact_id
        for entry in relevant_entries
        if entry.status == "archived"
    }
    eligibility: tuple[NormalizedArchiveEligibility, ...] = ()
    if artifact_kind == "source_audio":
        candidates = _eligible_source_artifacts(
            database, video_ids=video_ids, excluded_artifact_ids=archived_artifact_ids
        )
    else:
        archived_normalized_ids = {
            entry.media_artifact_id
            for entry in relevant_entries
            if entry.status == "archived"
        }
        archived_authoritative_video_ids = {
            video_id
            for artifact_id in archived_normalized_ids
            if (video_id := artifact_video_id_by_id.get(artifact_id)) is not None
            and _preferred_normalized_artifact_id(
                artifacts_by_video.get(video_id, ())
            )
            == artifact_id
        }
        normalized_video_ids = {
            video.id
            for video in videos
            if (video_ids is None or video.id in video_ids)
            and video.id not in archived_authoritative_video_ids
        }
        eligibility = tuple(
            normalized_archive_eligibility(
                database,
                app_paths,
                video_ids=normalized_video_ids,
                verification_cache=MediaVerificationCache(
                    app_paths.logs / "normalized-archive-verification"
                ),
            )
        )
        candidates = [
            item.artifact for item in eligibility
            if item.eligible and item.artifact is not None and item.artifact.id not in archived_artifact_ids
        ]
    if limit is not None:
        candidates = candidates[:limit]
    entries = [
        database.upsert_media_archive_entry(
            media_artifact_id=artifact.id,
            destination_id=destination.id,
            source_path=artifact.artifact_path,
            archive_path=str(_archive_path(app_paths, root, artifact)),
            content_sha256=artifact.content_sha256,
            byte_size=artifact.byte_size,
        )
        for artifact in candidates
    ]

    eligible_bytes = sum(artifact.byte_size for artifact in candidates)
    _notify_preflight(
        preflight_callback,
        "eligibility",
        "passed",
        f"{len(candidates)} {artifact_kind} artifacts / {_format_bytes(eligible_bytes)}; "
        f"persisted archived skipped={len(archived_artifact_ids)}",
    )
    partial_count = 0
    staging_count = 0
    required_bytes = 0
    for artifact, entry in zip(candidates, entries):
        archive_path = Path(entry.archive_path)
        partial_path = archive_path.with_name(
            f".{archive_path.name}.pte-partial-{artifact.id}"
        )
        staging_path = Path(entry.source_path).with_name(
            f".{Path(entry.source_path).name}.pte-archive-staging-{artifact.id}"
        )
        if destination_available and partial_path.exists():
            partial_count += 1
        if staging_path.exists() or staging_path.is_symlink():
            staging_count += 1
        if not destination_available or not archive_path.exists():
            required_bytes += artifact.byte_size
    _notify_preflight(
        preflight_callback,
        "recovery markers",
        "passed" if staging_count == 0 else "warning",
        f"partial={partial_count}, local_staging={staging_count}",
    )
    if capacity is not None:
        available_bytes = capacity.available_bytes
        space_ok = available_bytes >= required_bytes
        capacity_detail = (
            f"available={_format_bytes(available_bytes)}, "
            f"required={_format_bytes(required_bytes)}, source={capacity.source}"
        )
        if capacity.filesystem_type is not None:
            capacity_detail += f", filesystem={capacity.filesystem_type}"
        if (
            capacity.portable_available_bytes is not None
            and capacity.portable_available_bytes != available_bytes
        ):
            capacity_detail += (
                ", shutil_available="
                f"{_format_bytes(capacity.portable_available_bytes)}"
            )
        _notify_preflight(
            preflight_callback,
            "capacity",
            "passed" if space_ok else "failed",
            capacity_detail,
        )
        if not space_ok:
            destination_available = False
            unavailable_detail = (
                f"archive destination has insufficient free space: "
                f"available={available_bytes}, required={required_bytes}"
            )

    if not destination_available:
        detail = unavailable_detail or f"archive destination is unavailable: {root}"
        items = []
        for index, (artifact, entry) in enumerate(zip(candidates, entries), start=1):
            database.add_media_archive_attempt(
                archive_entry_id=entry.id,
                outcome="destination_unavailable",
                detail=detail,
            )
            _notify(
                progress_callback,
                index=index,
                total=len(candidates),
                artifact=artifact,
                entry=entry,
                stage="complete",
                outcome="destination_unavailable",
                detail=detail,
            )
            items.append(_item(artifact, entry, "destination_unavailable", detail))
        return ArchiveRunResult(destination, len(candidates), tuple(items), eligibility)

    items: list[ArchiveItemResult] = []
    for index, (artifact, entry) in enumerate(zip(candidates, entries), start=1):
        if dry_run:
            _notify(
                progress_callback,
                index=index,
                total=len(candidates),
                artifact=artifact,
                entry=entry,
                stage="complete",
                outcome="would_archive",
            )
            items.append(_item(artifact, entry, "would_archive", None))
            continue
        notify_stage = lambda stage: _notify(
            progress_callback,
            index=index,
            total=len(candidates),
            artifact=artifact,
            entry=entry,
            stage=stage,
        )
        outcome, detail = _archive_one(
            artifact,
            entry,
            notify_stage,
            source_preverified=(artifact_kind == "normalized_audio"),
        )
        database.add_media_archive_attempt(
            archive_entry_id=entry.id,
            outcome=outcome,
            detail=detail,
        )
        if outcome in {"archived", "already_archived"}:
            database.update_media_archive_entry_status(entry.id, "archived")
        elif outcome == "failed":
            database.update_media_archive_entry_status(entry.id, "failed")
        _notify(
            progress_callback,
            index=index,
            total=len(candidates),
            artifact=artifact,
            entry=entry,
            stage="complete",
            outcome=outcome,
            detail=detail,
        )
        items.append(_item(artifact, entry, outcome, detail))
    return ArchiveRunResult(destination, len(candidates), tuple(items), eligibility)


def write_canonical_clip_preparation_manifest(
    app_paths: AppPaths,
    artifact: MediaArtifact,
    observation,
    *,
    clip_paths: tuple[Path, ...],
    policy_version: str = CANONICAL_CLIP_PREPARATION_POLICY_VERSION,
) -> Path:
    """Persist immutable proof that reusable acoustic inputs were prepared."""
    clips = []
    for path in clip_paths:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        clips.append({
            "path": str(resolved),
            "byte_size": resolved.stat().st_size,
            "sha256": _sha256_file(resolved),
        })
    identity = {
        "normalized_audio_sha256": artifact.content_sha256,
        "observation_fingerprint": observation.input_fingerprint,
        "observation_window": {
            "start_seconds": observation.start_seconds,
            "end_seconds": observation.end_seconds,
        },
        "policy_version": policy_version,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest_dir = Path(artifact.manifest_path).parent / "canonical-clips"
    manifest_path = manifest_dir / f"{fingerprint}.json"
    payload = {"schema_version": 1, "input": identity, "clips": clips}
    manifest_dir.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != payload:
            raise RuntimeError(f"canonical clip manifest collision: {manifest_path}")
    else:
        temporary = manifest_path.with_suffix(".json.partial")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, manifest_path)
    return manifest_path


def normalized_archive_eligibility(
    database: Database,
    app_paths: AppPaths,
    *,
    video_ids: set[int] | None = None,
    policy_version: str = CANONICAL_CLIP_PREPARATION_POLICY_VERSION,
    verification_cache: MediaVerificationCache | None = None,
) -> list[NormalizedArchiveEligibility]:
    results: list[NormalizedArchiveEligibility] = []
    for video in database.list_videos():
        if video_ids is not None and video.id not in video_ids:
            continue
        artifact, availability = get_authoritative_normalized_media_artifact(
            database,
            video.id,
            require_isolated_sermon=False,
            verification_cache=verification_cache,
        )
        if artifact is None:
            results.append(NormalizedArchiveEligibility(video.id, video.youtube_video_id, None, False, "authoritative normalized audio is missing or invalid", "not_applicable"))
            continue
        if availability is None or availability.status not in {"verified_local", "verified_archived"}:
            results.append(NormalizedArchiveEligibility(video.id, video.youtube_video_id, artifact, False, availability.status if availability else "missing", "not_applicable"))
            continue
        if database.get_latest_transcript_artifact_for_video(video.id) is None:
            results.append(NormalizedArchiveEligibility(video.id, video.youtube_video_id, artifact, False, "transcription incomplete", "not_applicable"))
            continue
        if database.get_latest_extraction_result_for_video(video.id) is None:
            results.append(NormalizedArchiveEligibility(video.id, video.youtube_video_id, artifact, False, "sermon classification incomplete", "not_applicable"))
            continue
        if not all((artifact.content_sha256, artifact.byte_size, artifact.format_name, artifact.duration_seconds, artifact.manifest_path)) or not Path(artifact.manifest_path).is_file():
            results.append(NormalizedArchiveEligibility(video.id, video.youtube_video_id, artifact, False, "normalized metadata or provenance manifest incomplete", "not_applicable"))
            continue
        observation_eligibility = assess_automatic_speaker_observation(
            database,
            video.id,
            verify_media=False,
        )
        observation = (
            observation_eligibility.observation
            if observation_eligibility.eligible
            else None
        )
        if observation is None:
            results.append(NormalizedArchiveEligibility(video.id, video.youtube_video_id, artifact, True, "classification finalized without clip-eligible observation", "not_applicable"))
            continue
        status = _canonical_clip_preparation_status(artifact, observation, policy_version)
        observation_is_audio_bound = (
            _observation_normalized_sha256(observation) == artifact.content_sha256
        )
        # A current canonical manifest is itself immutable proof binding the
        # exact observation fingerprint/window to this normalized SHA-256 and
        # policy. This permits legacy observations without weakening identity.
        if not observation_is_audio_bound and status != "current":
            results.append(
                NormalizedArchiveEligibility(
                    video.id,
                    video.youtube_video_id,
                    artifact,
                    False,
                    "current observation is not bound to normalized audio",
                    status,
                )
            )
            continue
        eligible = status == "current"
        reason = "canonical clip preparation complete" if eligible else ("canonical clip preparation is stale" if status == "stale" else "blocked by incomplete clip/fingerprint generation")
        results.append(NormalizedArchiveEligibility(video.id, video.youtube_video_id, artifact, eligible, reason, status))
    return results


def _observation_normalized_sha256(observation) -> str | None:
    try:
        payload = json.loads(Path(observation.artifact_path).read_text(encoding="utf-8"))
        provenance = payload.get("normalized_audio_provenance")
        if isinstance(provenance, dict) and isinstance(
            provenance.get("content_sha256"), str
        ):
            return provenance["content_sha256"]
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    # Compatibility for observations created by older imports and focused tests.
    return observation.content_sha256


def _canonical_clip_preparation_status(artifact, observation, policy_version: str) -> str:
    directory = Path(artifact.manifest_path).parent / "canonical-clips"
    saw_manifest = False
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else ():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        saw_manifest = True
        expected = {
            "normalized_audio_sha256": artifact.content_sha256,
            "observation_fingerprint": observation.input_fingerprint,
            "observation_window": {"start_seconds": observation.start_seconds, "end_seconds": observation.end_seconds},
            "policy_version": policy_version,
        }
        if payload.get("input") != expected:
            continue
        clips = payload.get("clips")
        if isinstance(clips, list) and clips and all(
            isinstance(item, dict) and Path(str(item.get("path", ""))).is_file()
            and _sha256_file(Path(str(item["path"]))) == item.get("sha256")
            for item in clips
        ):
            return "current"
    return "stale" if saw_manifest else "missing"


def archive_status(
    database: Database, app_paths: AppPaths | None = None
) -> ArchiveStatusReport:
    destination = database.get_active_media_archive_destination()
    accessible = destination is not None and Path(destination.archive_root).is_dir()
    entries = tuple(database.list_media_archive_entries())
    kind_by_id = {
        artifact.id: artifact.artifact_kind
        for video in database.list_videos()
        for artifact in database.list_media_artifacts_for_video(video.id)
    }
    return ArchiveStatusReport(
        destination=destination,
        destination_accessible=accessible,
        entries=entries,
        source_entries=tuple(e for e in entries if kind_by_id.get(e.media_artifact_id) == "source_audio"),
        normalized_entries=tuple(e for e in entries if kind_by_id.get(e.media_artifact_id) == "normalized_audio"),
        normalized_eligibility=(
            tuple(normalized_archive_eligibility(database, app_paths))
            if app_paths is not None
            else ()
        ),
    )


def sweep_local_audio(
    database: Database,
    app_paths: AppPaths,
    *,
    apply: bool = False,
    progress_callback: AudioSweepProgressCallback | None = None,
) -> AudioSweepResult:
    """Audit local audio and safely deduplicate exact archived copies.

    Dry-run is the default. Apply mode only replaces a physical local file when
    its bytes match an accessible, checksum-verified archived artifact. The
    original logical path remains available as a symlink. Unmatched, failed,
    and merely eligible files are never removed by this operation.
    """
    with _archive_lock(app_paths.root, wait_for_lock=False, retry_seconds=1.0):
        _recover_audio_sweep_staging(app_paths.pastors)
        videos = database.list_videos()
        artifacts_by_video = {
            video.id: database.list_media_artifacts_for_video(video.id)
            for video in videos
        }
        artifacts = [
            artifact
            for video_artifacts in artifacts_by_video.values()
            for artifact in video_artifacts
        ]
        artifacts_by_path: dict[Path, list[MediaArtifact]] = {}
        for artifact in artifacts:
            artifacts_by_path.setdefault(
                Path(artifact.artifact_path).expanduser().resolve(strict=False), []
            ).append(artifact)
        entries = database.list_media_archive_entries()
        entries_by_artifact_id = {
            entry.media_artifact_id: entry for entry in entries
        }
        archived_by_size: dict[int, list[MediaArchiveEntry]] = {}
        for entry in entries:
            if entry.status == "archived":
                archived_by_size.setdefault(entry.byte_size, []).append(entry)
        transcript_audio_paths = {
            Path(item.audio_path).expanduser().resolve(strict=False)
            for item in database.list_transcript_artifacts()
            if item.audio_path
        }
        physical_files = _physical_audio_files(app_paths.pastors)
        archive_verification: dict[int, bool] = {}
        results: list[AudioSweepItem] = []

        for index, path in enumerate(physical_files, start=1):
            _notify_audio_sweep(
                progress_callback, index, len(physical_files), path, "classifying"
            )
            size = path.stat().st_size
            category = _audio_sweep_category(path)
            path_key = path.resolve(strict=False)
            registered = artifacts_by_path.get(path_key, [])
            if len(registered) > 1:
                results.append(
                    AudioSweepItem(
                        path,
                        size,
                        category,
                        "retained_ambiguous_registration",
                        f"{len(registered)} media artifacts use this path",
                    )
                )
                continue

            artifact = registered[0] if registered else None
            entry = (
                entries_by_artifact_id.get(artifact.id)
                if artifact is not None
                else None
            )
            if entry is not None and entry.status != "archived":
                retry_command = (
                    "pte media archive-normalized --all-eligible"
                    if artifact.artifact_kind == "normalized_audio"
                    else "pte media archive-sources"
                )
                results.append(
                    AudioSweepItem(
                        path,
                        size,
                        category,
                        f"retained_archive_{entry.status}",
                        f"local bytes are required; retry with `{retry_command}`",
                        artifact.id,
                        Path(entry.archive_path),
                    )
                )
                continue

            matching_entry: MediaArchiveEntry | None = None
            if entry is not None:
                _notify_audio_sweep(
                    progress_callback,
                    index,
                    len(physical_files),
                    path,
                    "hashing local candidate",
                )
                local_sha256 = _sha256_file(path)
                local_matches_entry = (
                    size == entry.byte_size
                    and local_sha256 == entry.content_sha256
                )
                if local_matches_entry:
                    _notify_audio_sweep(
                        progress_callback,
                        index,
                        len(physical_files),
                        path,
                        "verifying archived target",
                    )
                if local_matches_entry and _verified_archive_entry(
                    entry, archive_verification
                ):
                    matching_entry = entry
            else:
                candidates = [
                    candidate
                    for candidate in archived_by_size.get(size, ())
                    if artifact is None
                    or candidate.media_artifact_id != artifact.id
                ]
                if candidates:
                    _notify_audio_sweep(
                        progress_callback,
                        index,
                        len(physical_files),
                        path,
                        "hashing local candidate",
                    )
                    local_sha256 = _sha256_file(path)
                    if artifact is not None and (
                        size != artifact.byte_size
                        or local_sha256 != artifact.content_sha256
                    ):
                        results.append(
                            AudioSweepItem(
                                path,
                                size,
                                category,
                                "retained_registered_corrupt",
                                "local bytes do not match the registered artifact identity",
                                artifact.id,
                            )
                        )
                        continue
                    for candidate in sorted(candidates, key=lambda item: item.id):
                        if candidate.content_sha256 != local_sha256:
                            continue
                        _notify_audio_sweep(
                            progress_callback,
                            index,
                            len(physical_files),
                            path,
                            "verifying archived duplicate",
                        )
                        if _verified_archive_entry(candidate, archive_verification):
                            matching_entry = candidate
                            break

            if matching_entry is None:
                if entry is not None:
                    outcome = "retained_archive_unavailable_or_corrupt"
                    detail = "recorded archive target is unavailable or failed checksum verification"
                elif artifact is not None:
                    outcome = "retained_registered_unarchived"
                    detail = _registered_unarchived_sweep_detail(
                        database,
                        artifact,
                        artifacts_by_video.get(artifact.video_id, ()),
                    )
                else:
                    outcome = "retained_untracked_unmatched"
                    reference = (
                        " and is referenced by a transcript"
                        if path_key in transcript_audio_paths
                        else ""
                    )
                    detail = "not registered and has no verified archived byte-identical copy" + reference
                results.append(
                    AudioSweepItem(
                        path,
                        size,
                        category,
                        outcome,
                        detail,
                        artifact.id if artifact is not None else None,
                        Path(entry.archive_path) if entry is not None else None,
                    )
                )
                continue

            archive_path = Path(matching_entry.archive_path)
            outcome = "would_link_to_archive"
            detail = (
                f"exact duplicate of archived media artifact "
                f"#{matching_entry.media_artifact_id}"
            )
            if apply:
                if artifact is not None and entry is None:
                    entry = database.upsert_media_archive_entry(
                        media_artifact_id=artifact.id,
                        destination_id=matching_entry.destination_id,
                        source_path=str(path),
                        archive_path=str(archive_path),
                        content_sha256=artifact.content_sha256,
                        byte_size=artifact.byte_size,
                    )
                try:
                    _replace_duplicate_with_symlink(
                        path,
                        archive_path,
                        size,
                        matching_entry.content_sha256,
                    )
                except (OSError, RuntimeError) as error:
                    if entry is not None and entry.status != "archived":
                        database.update_media_archive_entry_status(entry.id, "failed")
                        database.add_media_archive_attempt(
                            archive_entry_id=entry.id,
                            outcome="failed",
                            detail=f"audio sweep failed: {error}",
                        )
                    results.append(
                        AudioSweepItem(
                            path,
                            size,
                            category,
                            "retained_link_failed",
                            str(error),
                            artifact.id if artifact is not None else None,
                            archive_path,
                        )
                    )
                    continue
                if entry is not None and entry.status != "archived":
                    database.update_media_archive_entry_status(entry.id, "archived")
                    database.add_media_archive_attempt(
                        archive_entry_id=entry.id,
                        outcome="already_archived",
                        detail=(
                            "audio sweep linked byte-identical local artifact to "
                            f"archive entry #{matching_entry.id}"
                        ),
                    )
                outcome = "linked_to_archive"
            results.append(
                AudioSweepItem(
                    path,
                    size,
                    category,
                    outcome,
                    detail,
                    artifact.id if artifact is not None else None,
                    archive_path,
                )
            )
        return AudioSweepResult(tuple(results), apply)


def _registered_unarchived_sweep_detail(
    database: Database,
    artifact: MediaArtifact,
    video_artifacts: tuple[MediaArtifact, ...] | list[MediaArtifact],
) -> str:
    if artifact.artifact_kind == "source_audio":
        return (
            "registered source has no verified archived duplicate; run "
            "`pte media archive-sources`"
        )
    if _preferred_normalized_artifact_id(video_artifacts) != artifact.id:
        return (
            "historical/non-authoritative normalized artifact is preserved by "
            "archive-normalized policy"
        )
    if database.get_latest_transcript_artifact_for_video(artifact.video_id) is None:
        return "authoritative normalized artifact is blocked: transcription incomplete"
    if database.get_latest_extraction_result_for_video(artifact.video_id) is None:
        return (
            "authoritative normalized artifact is blocked: sermon classification incomplete"
        )
    if not all(
        (
            artifact.content_sha256,
            artifact.byte_size,
            artifact.format_name,
            artifact.duration_seconds,
            artifact.manifest_path,
        )
    ) or not Path(artifact.manifest_path).is_file():
        return (
            "authoritative normalized artifact is blocked: metadata or provenance "
            "manifest incomplete"
        )
    observation_eligibility = assess_automatic_speaker_observation(
        database,
        artifact.video_id,
        verify_media=False,
    )
    observation = (
        observation_eligibility.observation
        if observation_eligibility.eligible
        else None
    )
    if observation is None:
        return (
            "authoritative normalized artifact appears eligible after finalized "
            "classification; run `pte media archive-normalized --all-eligible`"
        )
    preparation = _canonical_clip_preparation_status(
        artifact, observation, CANONICAL_CLIP_PREPARATION_POLICY_VERSION
    )
    if (
        _observation_normalized_sha256(observation) != artifact.content_sha256
        and preparation != "current"
    ):
        return (
            "authoritative normalized artifact is blocked: current observation is "
            f"not bound to normalized audio; clip_preparation={preparation}"
        )
    if preparation == "current":
        return (
            "authoritative normalized artifact appears eligible; run "
            "`pte media archive-normalized --all-eligible`"
        )
    return (
        "authoritative normalized artifact is blocked: "
        + (
            "canonical clip preparation is stale"
            if preparation == "stale"
            else "clip/fingerprint generation is incomplete"
        )
        + f"; clip_preparation={preparation}"
    )


def _eligible_source_artifacts(
    database: Database,
    *,
    video_ids: set[int] | None = None,
    excluded_artifact_ids: set[int] | None = None,
) -> list[MediaArtifact]:
    excluded = excluded_artifact_ids or set()
    candidates: list[MediaArtifact] = []
    for video in database.list_videos():
        if video_ids is not None and video.id not in video_ids:
            continue
        source_artifacts = [
            artifact
            for artifact in database.list_media_artifacts_for_video(video.id)
            if artifact.artifact_kind == "source_audio"
            and artifact.id not in excluded
        ]
        if not source_artifacts:
            continue
        if get_archive_safe_normalized_media_artifact(database, video.id) is None:
            continue
        candidates.extend(source_artifacts)
    return sorted(candidates, key=lambda artifact: artifact.id)


def _preferred_normalized_artifact_id(
    artifacts: tuple[MediaArtifact, ...] | list[MediaArtifact],
) -> int | None:
    """Return the persisted provenance-priority candidate without opening bytes."""
    for provenance_kind in ("derived", "reconstructed_existing"):
        for artifact in reversed(artifacts):
            if (
                artifact.artifact_kind == "normalized_audio"
                and artifact.provenance_kind == provenance_kind
            ):
                return artifact.id
    return None


def _archive_path(app_paths: AppPaths, root: Path, artifact: MediaArtifact) -> Path:
    source = Path(artifact.artifact_path)
    try:
        relative = source.relative_to(app_paths.root)
    except ValueError:
        relative = Path("external") / artifact.content_sha256[:16] / source.name
    return root / relative


def _archive_one(
    artifact: MediaArtifact,
    entry: MediaArchiveEntry,
    stage_callback: Callable[[str], None] | None = None,
    *,
    source_preverified: bool = False,
) -> tuple[str, str | None]:
    source = Path(entry.source_path)
    destination = Path(entry.archive_path)
    try:
        if _source_points_to_archive(source, destination):
            _stage(stage_callback, "verifying existing archive")
            if _matches(destination, artifact):
                return "already_archived", None
            return "failed", "archived target is missing or does not match its recorded checksum"

        if destination.exists():
            _stage(stage_callback, "verifying existing archive")
            if not _matches(destination, artifact):
                return "failed", f"archive path collision: {destination}"
        else:
            _stage(stage_callback, "verifying local source")
            if not source_preverified and not verify_media_artifact(artifact):
                return "failed", f"source media is missing or corrupt: {source}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_name(f".{destination.name}.pte-partial-{artifact.id}")
            if partial.exists() or partial.is_symlink():
                partial.unlink()
            try:
                _stage(stage_callback, "copying to NAS")
                shutil.copy2(source, partial)
                _stage(stage_callback, "verifying NAS checksum")
                if not _matches(partial, artifact):
                    raise RuntimeError("copied archive checksum does not match source artifact")
                os.replace(partial, destination)
            finally:
                if partial.exists() or partial.is_symlink():
                    partial.unlink()
        _stage(stage_callback, "linking archived source")
        _replace_source_with_symlink(source, destination, artifact)
        return "archived", None
    except OSError as error:
        return "failed", f"{type(error).__name__}: {error}"
    except RuntimeError as error:
        return "failed", str(error)


def _replace_source_with_symlink(
    source: Path, destination: Path, artifact: MediaArtifact
) -> None:
    if source.is_symlink():
        raise RuntimeError(f"refusing to replace unrelated symlink: {source}")
    backup = source.with_name(f".{source.name}.pte-archive-staging-{artifact.id}")
    if backup.exists() or backup.is_symlink():
        raise RuntimeError(f"archive staging path already exists: {backup}")
    if source.exists():
        source.rename(backup)
    try:
        source.symlink_to(destination)
        if (
            source.resolve(strict=False) != destination.resolve(strict=False)
            or not source.exists()
            or source.stat().st_size != artifact.byte_size
        ):
            raise RuntimeError("archive symlink failed post-write verification")
    except (OSError, RuntimeError):
        if source.exists() or source.is_symlink():
            source.unlink()
        if backup.exists():
            backup.rename(source)
        raise
    if backup.exists():
        backup.unlink()


def _physical_audio_files(root: Path) -> list[Path]:
    extensions = {".aac", ".flac", ".m4a", ".mp3", ".mp4", ".ogg", ".wav", ".webm"}
    paths: list[Path] = []
    if not root.is_dir():
        return paths
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        directory_names[:] = [
            name
            for name in directory_names
            if not (directory_path / name).is_symlink()
        ]
        for name in file_names:
            path = directory_path / name
            if path.suffix.lower() not in extensions or path.is_symlink():
                continue
            try:
                if path.is_file():
                    paths.append(path)
            except OSError:
                continue
    return sorted(paths, key=str)


def _audio_sweep_category(path: Path) -> str:
    if path.name == "downloaded.wav":
        return "legacy_downloaded"
    if path.name == "normalized.wav":
        return "legacy_normalized"
    if path.name.startswith("normalized-"):
        return "content_addressed_normalized"
    if path.name.startswith("source-"):
        return "content_addressed_source"
    return "other_audio"


def _verified_archive_entry(
    entry: MediaArchiveEntry, cache: dict[int, bool]
) -> bool:
    if entry.id not in cache:
        archive_path = Path(entry.archive_path)
        try:
            cache[entry.id] = (
                archive_path.is_file()
                and archive_path.stat().st_size == entry.byte_size
                and _sha256_file(archive_path) == entry.content_sha256
            )
        except OSError:
            cache[entry.id] = False
    return cache[entry.id]


def _replace_duplicate_with_symlink(
    source: Path,
    destination: Path,
    expected_size: int,
    expected_sha256: str,
) -> None:
    if source.is_symlink() or not source.is_file():
        raise RuntimeError(f"local cleanup candidate is no longer a regular file: {source}")
    backup = source.with_name(f".{source.name}.pte-audio-sweep-staging")
    if backup.exists() or backup.is_symlink():
        raise RuntimeError(f"audio sweep staging path already exists: {backup}")
    source.rename(backup)
    try:
        if (
            backup.stat().st_size != expected_size
            or _sha256_file(backup) != expected_sha256
        ):
            raise RuntimeError(
                "local cleanup candidate changed after duplicate verification"
            )
        source.symlink_to(destination)
        if (
            source.resolve(strict=False) != destination.resolve(strict=False)
            or not source.exists()
            or source.stat().st_size != expected_size
        ):
            raise RuntimeError("audio sweep symlink failed post-write verification")
    except (OSError, RuntimeError):
        if source.exists() or source.is_symlink():
            source.unlink()
        backup.rename(source)
        raise
    backup.unlink()


def _recover_audio_sweep_staging(root: Path) -> None:
    suffix = ".pte-audio-sweep-staging"
    if not root.is_dir():
        return
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        directory_names[:] = [
            name
            for name in directory_names
            if not (directory_path / name).is_symlink()
        ]
        for name in file_names:
            if not name.startswith(".") or not name.endswith(suffix):
                continue
            backup = directory_path / name
            source = directory_path / name[1:-len(suffix)]
            if not source.exists() and not source.is_symlink():
                backup.rename(source)
                continue
            if not source.is_symlink():
                raise RuntimeError(
                    f"audio sweep recovery found conflicting paths: {source}, {backup}"
                )
            try:
                target = source.resolve(strict=True)
                completed = (
                    target.is_file()
                    and target.stat().st_size == backup.stat().st_size
                    and _sha256_file(target) == _sha256_file(backup)
                )
            except OSError:
                completed = False
            if completed:
                backup.unlink()
                continue
            source.unlink()
            backup.rename(source)


def _notify_audio_sweep(
    callback: AudioSweepProgressCallback | None,
    index: int,
    total: int,
    path: Path,
    stage: str,
) -> None:
    if callback is not None:
        callback(AudioSweepProgressEvent(index, total, path, stage))


def _source_points_to_archive(source: Path, destination: Path) -> bool:
    return source.is_symlink() and source.resolve(strict=False) == destination.resolve(strict=False)


def _matches(path: Path, artifact: MediaArtifact) -> bool:
    return (
        path.exists()
        and path.stat().st_size == artifact.byte_size
        and _sha256_file(path) == artifact.content_sha256
    )


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _item(
    artifact: MediaArtifact,
    entry: MediaArchiveEntry,
    outcome: str,
    detail: str | None,
) -> ArchiveItemResult:
    return ArchiveItemResult(
        media_artifact_id=artifact.id,
        source_path=Path(entry.source_path),
        archive_path=Path(entry.archive_path),
        outcome=outcome,
        detail=detail,
    )


def _stage(callback: Callable[[str], None] | None, stage: str) -> None:
    if callback is not None:
        callback(stage)


def _notify(
    callback: ArchiveProgressCallback | None,
    *,
    index: int,
    total: int,
    artifact: MediaArtifact,
    entry: MediaArchiveEntry,
    stage: str,
    outcome: str | None = None,
    detail: str | None = None,
) -> None:
    if callback is None:
        return
    callback(
        ArchiveProgressEvent(
            index=index,
            total=total,
            media_artifact_id=artifact.id,
            source_path=Path(entry.source_path),
            archive_path=Path(entry.archive_path),
            stage=stage,
            outcome=outcome,
            detail=detail,
        )
    )


def _check_destination(
    root: Path, callback: ArchivePreflightCallback | None
) -> tuple[bool, str | None, FilesystemCapacity | None]:
    if not root.is_dir():
        detail = f"archive destination is unavailable: {root}"
        _notify_preflight(callback, "mount", "failed", detail)
        return False, detail, None
    _notify_preflight(callback, "mount", "passed", "archive directory is accessible")

    probe_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".pte-write-probe-",
            dir=root,
            delete=False,
        ) as probe:
            probe_path = Path(probe.name)
            probe.write(b"pte archive write probe\n")
            probe.flush()
            os.fsync(probe.fileno())
        probe_path.unlink()
        probe_path = None
    except OSError as error:
        if probe_path is not None and probe_path.exists():
            try:
                probe_path.unlink()
            except OSError:
                pass
        detail = f"archive destination write probe failed: {type(error).__name__}: {error}"
        _notify_preflight(callback, "write probe", "failed", detail)
        return False, detail, None
    _notify_preflight(callback, "write probe", "passed", "create, fsync, and delete succeeded")

    try:
        capacity = filesystem_capacity(root)
    except OSError as error:
        detail = f"free-space check failed: {type(error).__name__}: {error}"
        _notify_preflight(callback, "capacity", "warning", detail)
        return True, None, None
    return True, None, capacity


@contextmanager
def _archive_lock(
    app_root: Path,
    *,
    wait_for_lock: bool = False,
    retry_seconds: float = 1.0,
    preflight_callback: ArchivePreflightCallback | None = None,
):
    if retry_seconds <= 0:
        raise ValueError("archive lock retry interval must be positive")
    lock_path = app_root / ".media-archive.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        waiting_reported = False
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if not wait_for_lock:
                    raise ValueError(
                        f"Another media archive process holds the lock: {lock_path}"
                    ) from error
                if not waiting_reported:
                    _notify_preflight(
                        preflight_callback,
                        "archive lock",
                        "waiting",
                        f"another archive process holds {lock_path}; retrying",
                    )
                    waiting_reported = True
                time.sleep(retry_seconds)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _notify_preflight(
    callback: ArchivePreflightCallback | None,
    check: str,
    status: str,
    detail: str,
) -> None:
    if callback is not None:
        callback(ArchivePreflightEvent(check=check, status=status, detail=detail))


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024.0 or unit == "TiB":
            return f"{amount:.2f} {unit}"
        amount /= 1024.0
    raise AssertionError("unreachable")
