from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Sequence
import wave

from pastor_transcript_extractor.artifact_namespace import (
    resolve_transcript_artifact_paths,
    resolve_video_artifact_paths,
)
from pastor_transcript_extractor.config import AppPaths, ToolConfig
from pastor_transcript_extractor.media import (
    VideoUnavailableError,
    YtDlpError,
    download_source_audio,
    normalize_audio,
)
from pastor_transcript_extractor.models import (
    MediaAcquisitionAttempt,
    MediaArtifact,
    Video,
)
from pastor_transcript_extractor.storage import Database


MEDIA_SERVICE_VERSION = "media_foundation_v1"
MEDIA_VERIFICATION_RECEIPT_VERSION = 1
NORMALIZED_PROVENANCE_REPAIR_VERSION = "normalized_provenance_repair_v1"


@dataclass(frozen=True, slots=True)
class EnsureAudioResult:
    video_id: int
    youtube_video_id: str
    eligible: bool
    outcome: str
    reason_code: str
    artifact: MediaArtifact | None
    attempt: MediaAcquisitionAttempt | None
    downloaded: bool


@dataclass(frozen=True, slots=True)
class StageSourceAudioResult:
    video_id: int
    youtube_video_id: str
    outcome: str
    reason_code: str
    artifact: MediaArtifact | None
    attempt: MediaAcquisitionAttempt | None
    downloaded: bool


@dataclass(frozen=True, slots=True)
class MediaBackfillResult:
    videos_examined: int
    artifacts_registered: int
    attempts_registered: int
    missing_paths: int


@dataclass(frozen=True, slots=True)
class MediaCoverageReport:
    isolated_sermons: int
    verified: tuple[str, ...]
    unavailable: tuple[str, ...]
    failed: tuple[str, ...]
    corrupt: tuple[str, ...]
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NormalizedAudioProvenanceRecord:
    video_id: int
    youtube_video_id: str
    derived_artifact: MediaArtifact
    reconstructed_artifact: MediaArtifact
    reconstructed_currently_selected: bool
    legacy_reconstructed_override: bool
    historical_reconstructed_override: bool
    reconstructed_age_seconds: float


@dataclass(frozen=True, slots=True)
class NormalizedAudioProvenanceAudit:
    generated_at: datetime
    records: tuple[NormalizedAudioProvenanceRecord, ...]

    @property
    def affected(self) -> tuple[NormalizedAudioProvenanceRecord, ...]:
        return tuple(
            record for record in self.records if record.legacy_reconstructed_override
        )


@dataclass(frozen=True, slots=True)
class NormalizedAudioRepairResult:
    video_id: int
    youtube_video_id: str
    artifact: MediaArtifact
    source_artifact: MediaArtifact


class ArchivedMediaUnavailableError(RuntimeError):
    """The authoritative artifact is archived, but its storage is offline."""

    reason_code = "archived_media_unavailable"

    def __init__(self, artifact: MediaArtifact | None, archive_path: Path):
        self.artifact = artifact
        self.archive_path = archive_path
        super().__init__(
            f"archived_media_unavailable: media artifact "
            f"{artifact.id if artifact is not None else 'unknown'} is authoritative "
            f"but archived media is unavailable at {archive_path}"
        )


@dataclass(frozen=True, slots=True)
class MediaAvailability:
    status: str
    artifact: MediaArtifact
    path: Path
    detail: str | None = None

    @property
    def verified(self) -> bool:
        return self.status in {"verified_local", "verified_archived"}


def media_artifact_availability(
    database: Database,
    artifact: MediaArtifact,
    *,
    verification_cache: MediaVerificationCache | None = None,
) -> MediaAvailability:
    """Classify bytes without discarding persisted authority when a mount is offline."""
    path = Path(artifact.artifact_path)
    entry = database.get_media_archive_entry_for_artifact(artifact.id)
    archived = entry is not None and entry.status == "archived"
    archive_path = Path(entry.archive_path) if entry is not None else path
    try:
        exists = path.exists()
    except OSError as error:
        if archived:
            return MediaAvailability("archived_media_unavailable", artifact, archive_path, str(error))
        return MediaAvailability("missing", artifact, path, str(error))
    if not exists:
        if archived:
            # A persisted archived entry plus the original archive symlink remains
            # authoritative even when its target cannot currently be reached.
            if path.is_symlink() and path.resolve(strict=False) == archive_path.resolve(strict=False):
                destination = database.get_active_media_archive_destination()
                if (
                    destination is not None
                    and Path(destination.archive_root).is_dir()
                ):
                    return MediaAvailability(
                        "missing", artifact, archive_path,
                        "archive destination is accessible but the immutable file is missing",
                    )
                return MediaAvailability("archived_media_unavailable", artifact, archive_path)
            return MediaAvailability("provenance_mismatch", artifact, path)
        return MediaAvailability("missing", artifact, path)
    try:
        valid = verify_media_artifact(artifact, verification_cache=verification_cache)
    except OSError as error:
        if archived:
            return MediaAvailability("archived_media_unavailable", artifact, archive_path, str(error))
        return MediaAvailability("missing", artifact, path, str(error))
    if not valid:
        return MediaAvailability("corrupt", artifact, archive_path if archived else path)
    if archived:
        if not path.is_symlink() or path.resolve(strict=False) != archive_path.resolve(strict=False):
            return MediaAvailability("provenance_mismatch", artifact, path)
        return MediaAvailability("verified_archived", artifact, path)
    return MediaAvailability("verified_local", artifact, path)


def require_media_artifact_bytes(
    database: Database,
    artifact: MediaArtifact,
    *,
    verification_cache: MediaVerificationCache | None = None,
) -> Path:
    availability = media_artifact_availability(
        database, artifact, verification_cache=verification_cache
    )
    if availability.status == "archived_media_unavailable":
        raise ArchivedMediaUnavailableError(artifact, availability.path)
    if not availability.verified:
        raise ValueError(
            f"{availability.status}: media artifact {artifact.id} is unavailable at "
            f"{availability.path}"
        )
    return Path(artifact.artifact_path)


class MediaVerificationCache:
    """Reuse a full artifact hash while the underlying file is unchanged."""

    def __init__(
        self,
        root: Path,
        *,
        fallback_roots: Sequence[Path] = (),
    ):
        self.root = root
        self.fallback_roots = tuple(
            fallback_root
            for fallback_root in fallback_roots
            if fallback_root != root
        )

    def verify(self, artifact: MediaArtifact) -> bool:
        path = Path(artifact.artifact_path)
        try:
            file_stat = path.stat()
        except OSError:
            return False
        if file_stat.st_size != artifact.byte_size:
            return False

        receipt_path = self._receipt_path(artifact)
        expected_stat = {
            "device": file_stat.st_dev,
            "inode": file_stat.st_ino,
            "size": file_stat.st_size,
            "mtime_ns": file_stat.st_mtime_ns,
        }
        for candidate_path in self._receipt_paths(artifact):
            try:
                receipt = json.loads(
                    candidate_path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(receipt, dict)
                and receipt.get("schema_version")
                == MEDIA_VERIFICATION_RECEIPT_VERSION
                and receipt.get("artifact") == self._artifact_identity(artifact)
                and receipt.get("file_stat") == expected_stat
            ):
                if candidate_path != receipt_path:
                    receipt_path.parent.mkdir(parents=True, exist_ok=True)
                    receipt_path.write_text(
                        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                return True

        if _sha256_file(path) != artifact.content_sha256:
            return False
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": MEDIA_VERIFICATION_RECEIPT_VERSION,
            "artifact": self._artifact_identity(artifact),
            "file_stat": expected_stat,
        }
        receipt_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return True

    def _receipt_path(self, artifact: MediaArtifact) -> Path:
        return self._receipt_path_under(self.root, artifact)

    def _receipt_paths(self, artifact: MediaArtifact) -> tuple[Path, ...]:
        return (
            self._receipt_path(artifact),
            *(
                self._receipt_path_under(root, artifact)
                for root in self.fallback_roots
            ),
        )

    @classmethod
    def _receipt_path_under(
        cls,
        root: Path,
        artifact: MediaArtifact,
    ) -> Path:
        identity = json.dumps(
            cls._artifact_identity(artifact),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return root / "media-verifications" / f"{hashlib.sha256(identity).hexdigest()}.json"

    @staticmethod
    def _artifact_identity(artifact: MediaArtifact) -> dict[str, object]:
        return {
            "artifact_id": artifact.id,
            "artifact_path": artifact.artifact_path,
            "byte_size": artifact.byte_size,
            "content_sha256": artifact.content_sha256,
        }


def video_has_isolated_sermon(database: Database, video_id: int) -> tuple[bool, str]:
    window, reason = _isolated_sermon_window(database, video_id)
    return window is not None, reason


def _isolated_sermon_window(
    database: Database, video_id: int
) -> tuple[tuple[float, float] | None, str]:
    extraction = database.get_latest_extraction_result_for_video(video_id)
    if extraction is None or not extraction.proposed_json_path:
        return None, "extraction_unavailable"
    try:
        payload = json.loads(Path(extraction.proposed_json_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "extraction_artifact_unreadable"
    window = payload.get("sermon_window")
    if not isinstance(window, dict):
        return None, "sermon_window_unavailable"
    start = window.get("start_seconds")
    end = window.get("end_seconds")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None, "sermon_window_unavailable"
    if float(end) <= float(start):
        return None, "sermon_window_invalid"
    return (float(start), float(end)), "isolated_sermon"


def register_media_file(
    database: Database,
    app_paths: AppPaths,
    *,
    video: Video,
    pastor_slug: str,
    artifact_path: Path,
    artifact_kind: str,
    provenance_kind: str,
    acquisition_tool: str,
    acquisition_tool_version: str,
    parent: MediaArtifact | None = None,
    operation_kind: str | None = None,
) -> MediaArtifact:
    resolved_path = artifact_path.expanduser().resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(resolved_path)
    content_sha256 = _sha256_file(resolved_path)
    metadata = _probe_audio(resolved_path)
    fingerprint_payload = {
        "service_version": MEDIA_SERVICE_VERSION,
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "artifact_kind": artifact_kind,
        "provenance_kind": provenance_kind,
        "content_sha256": content_sha256,
        "parent_content_sha256": parent.content_sha256 if parent else None,
        "acquisition_tool": acquisition_tool,
        "acquisition_tool_version": acquisition_tool_version,
        "operation_kind": operation_kind,
    }
    input_fingerprint = _sha256_json(fingerprint_payload)
    video_paths = resolve_video_artifact_paths(database, app_paths, video)
    manifest_path = (
        video_paths.audio
        / "media"
        / "manifests"
        / f"{artifact_kind}-{input_fingerprint[:16]}.json"
    )
    manifest = {
        "schema_version": 1,
        "service_version": MEDIA_SERVICE_VERSION,
        "input_fingerprint": input_fingerprint,
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "artifact_kind": artifact_kind,
        "provenance_kind": provenance_kind,
        "artifact_path": str(resolved_path),
        "content_sha256": content_sha256,
        "byte_size": resolved_path.stat().st_size,
        "duration_seconds": metadata["duration_seconds"],
        "format_name": metadata["format_name"],
        "sample_rate_hz": metadata["sample_rate_hz"],
        "channel_count": metadata["channel_count"],
        "parent": (
            {
                "media_artifact_id": parent.id,
                "content_sha256": parent.content_sha256,
            }
            if parent
            else None
        ),
        "acquisition_tool": acquisition_tool,
        "acquisition_tool_version": acquisition_tool_version,
        "operation_kind": operation_kind,
        "source_snapshot_semantics": (
            "reconstructed_without_original_tool_snapshot"
            if provenance_kind == "reconstructed_existing"
            else "captured_by_media_service"
        ),
    }
    _write_json_idempotent(manifest_path, manifest)
    return database.add_media_artifact(
        video_id=video.id,
        parent_media_artifact_id=parent.id if parent else None,
        artifact_kind=artifact_kind,
        provenance_kind=provenance_kind,
        artifact_path=str(resolved_path),
        manifest_path=str(manifest_path),
        content_sha256=content_sha256,
        byte_size=resolved_path.stat().st_size,
        duration_seconds=metadata["duration_seconds"],
        format_name=metadata["format_name"],
        sample_rate_hz=metadata["sample_rate_hz"],
        channel_count=metadata["channel_count"],
        acquisition_tool=acquisition_tool,
        acquisition_tool_version=acquisition_tool_version,
        input_fingerprint=input_fingerprint,
    )


def backfill_existing_media_artifacts(
    database: Database,
    app_paths: AppPaths,
    *,
    video_id: int | None = None,
) -> MediaBackfillResult:
    videos = [database.get_video_by_id(video_id)] if video_id is not None else database.list_videos()
    videos = [video for video in videos if video is not None]
    before_artifacts = database.counts_by_table()["media_artifacts"]
    before_attempts = database.counts_by_table()["media_acquisition_attempts"]
    missing_paths = 0
    for video in videos:
        pastor = (
            database.get_pastor_by_id(video.pastor_id)
            if video.pastor_id is not None
            else None
        )
        transcript_paths = resolve_transcript_artifact_paths(
            database, app_paths, video
        )
        existing_artifacts = database.list_media_artifacts_for_video(video.id)
        source_artifact = _artifact_at_logical_path(
            existing_artifacts,
            artifact_kind="source_audio",
            path=transcript_paths.audio_download,
        )
        if source_artifact is None and transcript_paths.audio_download.exists():
            source_artifact = register_media_file(
                database,
                app_paths,
                video=video,
                pastor_slug=pastor.slug if pastor is not None else "",
                artifact_path=transcript_paths.audio_download,
                artifact_kind="source_audio",
                provenance_kind="reconstructed_existing",
                acquisition_tool="unknown_reconstructed",
                acquisition_tool_version="unknown",
            )
        candidate_paths = [
            Path(transcript.audio_path).expanduser().resolve()
            for transcript in database.list_transcript_artifacts_for_video(video.id)
            if transcript.audio_path
        ]
        if transcript_paths.audio_normalized.exists():
            candidate_paths.append(transcript_paths.audio_normalized.resolve())
        seen_paths: set[Path] = set()
        for path in candidate_paths:
            if path in seen_paths:
                continue
            seen_paths.add(path)
            if not path.exists():
                missing_paths += 1
                continue
            normalized = _artifact_at_logical_path(
                existing_artifacts,
                artifact_kind="normalized_audio",
                path=path,
            )
            if normalized is None:
                normalized = register_media_file(
                    database,
                    app_paths,
                    video=video,
                    pastor_slug=pastor.slug if pastor is not None else "",
                    artifact_path=path,
                    artifact_kind="normalized_audio",
                    provenance_kind="reconstructed_existing",
                    acquisition_tool="unknown_reconstructed",
                    acquisition_tool_version="unknown",
                    parent=source_artifact,
                )
                existing_artifacts.append(normalized)
            covers_window = media_artifact_covers_isolated_sermon(database, normalized)
            _record_attempt(
                database,
                video=video,
                outcome="verified" if covers_window else "failed",
                reason_code=(
                    "reconstructed_existing_audio"
                    if covers_window
                    else "reconstructed_audio_incomplete"
                ),
                detail=(
                    "Historical audio registered without an original downloader snapshot."
                    if covers_window
                    else "Historical audio does not cover the isolated sermon window."
                ),
                artifact=normalized,
            )
    after = database.counts_by_table()
    return MediaBackfillResult(
        videos_examined=len(videos),
        artifacts_registered=after["media_artifacts"] - before_artifacts,
        attempts_registered=after["media_acquisition_attempts"] - before_attempts,
        missing_paths=missing_paths,
    )


def _artifact_at_logical_path(
    artifacts: list[MediaArtifact],
    *,
    artifact_kind: str,
    path: Path,
) -> MediaArtifact | None:
    logical_path = path.expanduser().absolute()
    for artifact in reversed(artifacts):
        if artifact.artifact_kind != artifact_kind:
            continue
        if Path(artifact.artifact_path).expanduser().absolute() == logical_path:
            return artifact
    return None


def ensure_audio_for_video(
    database: Database,
    app_paths: AppPaths,
    tools: ToolConfig,
    *,
    video_id: int,
    tool_versions: dict[str, str] | None = None,
    allow_download: bool = True,
    event_callback: Callable[[str], None] | None = None,
) -> EnsureAudioResult:
    video = database.get_video_by_id(video_id)
    if video is None:
        raise ValueError(f"Unknown video id: {video_id}")
    eligible, eligibility_reason = video_has_isolated_sermon(database, video.id)
    if not eligible:
        return EnsureAudioResult(
            video.id,
            video.youtube_video_id,
            False,
            "skipped",
            eligibility_reason,
            None,
            None,
            False,
        )
    pastor = (
        database.get_pastor_by_id(video.pastor_id)
        if video.pastor_id is not None
        else None
    )

    emit = event_callback or (lambda _message: None)
    emit("checking existing media registration and integrity")
    backfill_existing_media_artifacts(database, app_paths, video_id=video.id)
    existing = get_verified_normalized_media_artifact(database, video.id)
    if existing is not None:
        latest_attempt = database.get_latest_media_acquisition_attempt(video.id)
        if (
            latest_attempt is not None
            and latest_attempt.outcome == "verified"
            and latest_attempt.media_artifact_id == existing.id
        ):
            attempt = latest_attempt
            reason_code = latest_attempt.reason_code
        else:
            attempt = _record_attempt(
                database,
                video=video,
                outcome="verified",
                reason_code="verified_existing_audio",
                detail=None,
                artifact=existing,
            )
            reason_code = "verified_existing_audio"
        return EnsureAudioResult(
            video.id,
            video.youtube_video_id,
            True,
            "verified",
            reason_code,
            existing,
            attempt,
            False,
        )
    versions = tool_versions or {
        "yt-dlp": _tool_version(tools.yt_dlp_bin, "--version"),
        "ffmpeg": _tool_version(tools.ffmpeg_bin, "-version"),
    }
    video_paths = resolve_video_artifact_paths(database, app_paths, video)
    media_root = video_paths.audio / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    try:
        source_artifact = get_verified_source_media_artifact(database, video.id)
        downloaded_source = False
        if source_artifact is None:
            if not allow_download:
                raise RuntimeError(
                    "offline media processing requires a verified staged source artifact"
                )
            emit("normalized audio missing; preparing source audio")
            staged = stage_source_audio_for_video(
                database,
                app_paths,
                tools,
                video_id=video.id,
                tool_versions=versions,
                record_attempt=False,
                event_callback=event_callback,
            )
            if staged.artifact is None:
                reason_code = (
                    "video_unavailable"
                    if staged.outcome == "unavailable"
                    else "media_acquisition_failed"
                )
                attempt = _record_attempt(
                    database,
                    video=video,
                    outcome=staged.outcome,
                    reason_code=reason_code,
                    detail=None,
                    artifact=None,
                )
                return EnsureAudioResult(
                    video.id,
                    video.youtube_video_id,
                    True,
                    staged.outcome,
                    reason_code,
                    None,
                    attempt,
                    staged.downloaded,
                )
            source_artifact = staged.artifact
            downloaded_source = staged.downloaded
        with tempfile.TemporaryDirectory(prefix=".media-work-", dir=video_paths.audio) as work:
            work_root = Path(work)
            emit("normalizing source audio")
            normalized_work = normalize_audio(
                Path(source_artifact.artifact_path),
                work_root / "normalized.wav",
                tools.ffmpeg_bin,
            )
            normalized_path = _materialize_content_addressed(
                normalized_work,
                media_root,
                prefix="normalized",
                protected_paths=_registered_media_paths(database, video.id),
                quarantine_root=(
                    app_paths.logs / "media-recovery" / video.youtube_video_id
                ),
                event_callback=event_callback,
            )
            emit("registering and verifying normalized audio")
            normalized_artifact = register_media_file(
                database,
                app_paths,
                video=video,
                pastor_slug=pastor.slug if pastor is not None else "",
                artifact_path=normalized_path,
                artifact_kind="normalized_audio",
                provenance_kind="derived",
                acquisition_tool="ffmpeg",
                acquisition_tool_version=versions["ffmpeg"],
                parent=source_artifact,
            )
            if not media_artifact_covers_isolated_sermon(database, normalized_artifact):
                raise RuntimeError("normalized audio does not cover the isolated sermon window")
        attempt = _record_attempt(
            database,
            video=video,
            outcome="verified",
            reason_code="downloaded_and_normalized",
            detail=None,
            artifact=normalized_artifact,
        )
        return EnsureAudioResult(
            video.id,
            video.youtube_video_id,
            True,
            "verified",
            "downloaded_and_normalized",
            normalized_artifact,
            attempt,
            downloaded_source,
        )
    except VideoUnavailableError as error:
        attempt = _record_attempt(
            database, video=video, outcome="unavailable", reason_code="video_unavailable",
            detail=str(error), artifact=None,
        )
        return EnsureAudioResult(
            video.id, video.youtube_video_id, True, "unavailable", "video_unavailable",
            None, attempt, False,
        )
    except (YtDlpError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        attempt = _record_attempt(
            database, video=video, outcome="failed", reason_code="media_acquisition_failed",
            detail=f"{type(error).__name__}: {error}", artifact=None,
        )
        return EnsureAudioResult(
            video.id, video.youtube_video_id, True, "failed", "media_acquisition_failed",
            None, attempt, False,
        )


def get_verified_source_media_artifact(
    database: Database,
    video_id: int,
    *,
    verification_cache: MediaVerificationCache | None = None,
) -> MediaArtifact | None:
    """Return the newest verified immutable downloader source for a video."""
    for artifact in reversed(database.list_media_artifacts_for_video(video_id)):
        if (
            artifact.artifact_kind == "source_audio"
            and artifact.provenance_kind == "original_download"
            and verify_media_artifact(artifact, verification_cache=verification_cache)
        ):
            return artifact
    return None


def stage_source_audio_for_video(
    database: Database,
    app_paths: AppPaths,
    tools: ToolConfig,
    *,
    video_id: int,
    tool_versions: dict[str, str] | None = None,
    record_attempt: bool = True,
    event_callback: Callable[[str], None] | None = None,
) -> StageSourceAudioResult:
    """Download and register source audio without normalizing or changing video state."""
    video = database.get_video_by_id(video_id)
    if video is None:
        raise ValueError(f"Unknown video id: {video_id}")
    emit = event_callback or (lambda _message: None)
    emit("checking for verified source audio")
    existing = get_verified_source_media_artifact(database, video.id)
    if existing is not None:
        return StageSourceAudioResult(
            video.id, video.youtube_video_id, "verified", "verified_existing_source",
            existing, None, False,
        )
    pastor = database.get_pastor_by_id(video.pastor_id) if video.pastor_id else None
    versions = tool_versions or {
        "yt-dlp": _tool_version(tools.yt_dlp_bin, "--version"),
    }
    video_paths = resolve_video_artifact_paths(database, app_paths, video)
    media_root = video_paths.audio / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=".source-stage-", dir=video_paths.audio) as work:
            emit("downloading source audio")
            downloaded = download_source_audio(
                video.url,
                tools.yt_dlp_bin,
                Path(work) / "source",
                tools.yt_dlp_js_runtimes,
            )
            emit("source download complete; registering source audio")
            source_path = _materialize_content_addressed(
                downloaded,
                media_root,
                prefix="source",
                protected_paths=_registered_media_paths(database, video.id),
                quarantine_root=(
                    app_paths.logs / "media-recovery" / video.youtube_video_id
                ),
                event_callback=event_callback,
            )
            artifact = register_media_file(
                database,
                app_paths,
                video=video,
                pastor_slug=pastor.slug if pastor is not None else "",
                artifact_path=source_path,
                artifact_kind="source_audio",
                provenance_kind="original_download",
                acquisition_tool="yt-dlp",
                acquisition_tool_version=versions["yt-dlp"],
            )
        attempt = (
            _record_attempt(
                database, video=video, outcome="verified", reason_code="source_audio_staged",
                detail=None, artifact=artifact, target_kind="source_audio",
            )
            if record_attempt else None
        )
        return StageSourceAudioResult(
            video.id, video.youtube_video_id, "verified", "source_audio_staged",
            artifact, attempt, True,
        )
    except VideoUnavailableError as error:
        attempt = (
            _record_attempt(
                database, video=video, outcome="unavailable", reason_code="video_unavailable",
                detail=str(error), artifact=None, target_kind="source_audio",
            )
            if record_attempt else None
        )
        return StageSourceAudioResult(
            video.id, video.youtube_video_id, "unavailable", "video_unavailable",
            None, attempt, False,
        )
    except (YtDlpError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        attempt = (
            _record_attempt(
                database, video=video, outcome="failed", reason_code="source_audio_stage_failed",
                detail=f"{type(error).__name__}: {error}", artifact=None,
                target_kind="source_audio",
            )
            if record_attempt else None
        )
        return StageSourceAudioResult(
            video.id, video.youtube_video_id, "failed", "source_audio_stage_failed",
            None, attempt, False,
        )
def audit_media_coverage(database: Database) -> MediaCoverageReport:
    verified: list[str] = []
    unavailable: list[str] = []
    failed: list[str] = []
    corrupt: list[str] = []
    missing: list[str] = []
    isolated_sermons = 0
    for video in database.list_videos():
        eligible, _ = video_has_isolated_sermon(database, video.id)
        if not eligible:
            continue
        isolated_sermons += 1
        artifacts = [
            artifact
            for artifact in database.list_media_artifacts_for_video(video.id)
            if artifact.artifact_kind == "normalized_audio"
        ]
        if artifacts:
            if get_verified_normalized_media_artifact(database, video.id) is not None:
                verified.append(video.youtube_video_id)
            else:
                corrupt.append(video.youtube_video_id)
            continue
        attempt = database.get_latest_media_acquisition_attempt(video.id)
        if attempt is None:
            missing.append(video.youtube_video_id)
        elif attempt.outcome == "unavailable":
            unavailable.append(video.youtube_video_id)
        elif attempt.outcome == "failed":
            failed.append(video.youtube_video_id)
        else:
            missing.append(video.youtube_video_id)
    return MediaCoverageReport(
        isolated_sermons=isolated_sermons,
        verified=tuple(verified),
        unavailable=tuple(unavailable),
        failed=tuple(failed),
        corrupt=tuple(corrupt),
        missing=tuple(missing),
    )


def resolve_normalized_audio_path(
    database: Database,
    video_id: int,
    *,
    verification_cache: MediaVerificationCache | None = None,
) -> Path | None:
    artifact = get_verified_normalized_media_artifact(
        database,
        video_id,
        verification_cache=verification_cache,
    )
    if artifact is not None:
        return Path(artifact.artifact_path)
    if any(
        item.artifact_kind == "normalized_audio"
        for item in database.list_media_artifacts_for_video(video_id)
    ):
        # Once a legacy path has been registered, the media record is authoritative.
        # Falling back to the same incomplete or corrupt file would bypass validation.
        return None
    legacy = database.get_latest_audio_transcript_artifact_for_video(video_id)
    if legacy is None or not legacy.audio_path:
        return None
    path = Path(legacy.audio_path).expanduser().resolve()
    return path if path.exists() else None


def get_verified_normalized_media_artifact(
    database: Database,
    video_id: int,
    *,
    verification_cache: MediaVerificationCache | None = None,
) -> MediaArtifact | None:
    artifact, availability = get_authoritative_normalized_media_artifact(
        database, video_id, verification_cache=verification_cache
    )
    if availability is not None and availability.status == "archived_media_unavailable":
        assert artifact is not None
        raise ArchivedMediaUnavailableError(artifact, availability.path)
    return artifact


def get_registered_normalized_media_artifact(
    database: Database,
    video_id: int,
    *,
    require_isolated_sermon: bool = True,
) -> MediaArtifact | None:
    """Select authoritative normalized-media metadata without touching its bytes.

    This is intended for metadata-only ingestion, inventory, and status work.
    Callers that will consume media must use
    ``get_verified_normalized_media_artifact``.
    """
    artifacts = database.list_media_artifacts_for_video(video_id)
    for provenance_kind in ("derived", "reconstructed_existing"):
        for artifact in reversed(artifacts):
            if (
                artifact.artifact_kind != "normalized_audio"
                or artifact.provenance_kind != provenance_kind
            ):
                continue
            covers_required_audio = media_artifact_covers_isolated_sermon(
                database, artifact
            ) or (
                not require_isolated_sermon
                and media_artifact_covers_complete_recording(database, artifact)
            )
            if covers_required_audio:
                return artifact
    return None


def get_authoritative_normalized_media_artifact(
    database: Database,
    video_id: int,
    *,
    verification_cache: MediaVerificationCache | None = None,
    require_isolated_sermon: bool = True,
) -> tuple[MediaArtifact | None, MediaAvailability | None]:
    """Select by provenance while preserving an offline archived derivative's authority."""
    artifacts = database.list_media_artifacts_for_video(video_id)
    # A verified media-service derivative is authoritative regardless of when
    # a historical reconstructed path was registered. Reconstructed audio is
    # retained as the fallback for videos without a usable derivative.
    for provenance_kind in ("derived", "reconstructed_existing"):
        for artifact in reversed(artifacts):
            if (
                artifact.artifact_kind != "normalized_audio"
                or artifact.provenance_kind != provenance_kind
            ):
                continue
            availability = media_artifact_availability(
                database, artifact, verification_cache=verification_cache
            )
            covers_required_audio = media_artifact_covers_isolated_sermon(
                database, artifact
            ) or (
                not require_isolated_sermon
                and media_artifact_covers_complete_recording(database, artifact)
            )
            if availability.status == "archived_media_unavailable":
                if covers_required_audio:
                    return artifact, availability
                continue
            if availability.verified and covers_required_audio:
                return artifact, availability
            # A corrupt/mismatched derived artifact may permit the historical
            # reconstructed fallback; only an offline archived artifact must defer.
    return None, None


def audit_normalized_audio_provenance(
    database: Database,
    *,
    now: datetime | None = None,
) -> NormalizedAudioProvenanceAudit:
    """Report verified derived/reconstructed conflicts without modifying state."""
    generated_at = now or datetime.now(timezone.utc)
    records: list[NormalizedAudioProvenanceRecord] = []
    for video in database.list_videos():
        artifacts = database.list_media_artifacts_for_video(video.id)
        derived = _latest_verified_normalized_artifact(
            database, artifacts, provenance_kind="derived"
        )
        reconstructed = _latest_verified_normalized_artifact(
            database, artifacts, provenance_kind="reconstructed_existing"
        )
        if derived is None or reconstructed is None:
            continue
        selected, _selected_availability = get_authoritative_normalized_media_artifact(
            database, video.id
        )
        reconstructed_created_at = reconstructed.created_at
        if reconstructed_created_at.tzinfo is None:
            reconstructed_created_at = reconstructed_created_at.replace(
                tzinfo=timezone.utc
            )
        records.append(
            NormalizedAudioProvenanceRecord(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                derived_artifact=derived,
                reconstructed_artifact=reconstructed,
                reconstructed_currently_selected=(
                    selected is not None and selected.id == reconstructed.id
                ),
                legacy_reconstructed_override=(
                    reconstructed.created_at > derived.created_at
                    and reconstructed.content_sha256 != derived.content_sha256
                ),
                historical_reconstructed_override=any(
                    artifact.artifact_kind == "normalized_audio"
                    and artifact.provenance_kind == "derived"
                    and artifact.created_at < reconstructed.created_at
                    and artifact.content_sha256
                    != reconstructed.content_sha256
                    and media_artifact_availability(database, artifact).status
                    in {"verified_local", "verified_archived", "archived_media_unavailable"}
                    and media_artifact_covers_isolated_sermon(database, artifact)
                    for artifact in artifacts
                ),
                reconstructed_age_seconds=max(
                    0.0, (generated_at - reconstructed_created_at).total_seconds()
                ),
            )
        )
    return NormalizedAudioProvenanceAudit(generated_at, tuple(records))


def repair_normalized_audio_provenance(
    database: Database,
    app_paths: AppPaths,
    tools: ToolConfig,
    *,
    video_ids: set[int] | None = None,
    tool_version: str | None = None,
) -> tuple[NormalizedAudioRepairResult, ...]:
    """Re-normalize affected videos from each derivative's verified source."""
    affected = [
        record
        for record in audit_normalized_audio_provenance(database).affected
        if video_ids is None or record.video_id in video_ids
    ]
    # Resolve every required byte source before the first artifact mutation.
    for record in affected:
        source = _verified_source_for_derived(database, record.derived_artifact)
        if source is None:
            raise ValueError(
                f"{record.youtube_video_id}: derived normalized audio has no verified source artifact"
            )
    ffmpeg_version = tool_version or _tool_version(tools.ffmpeg_bin, "-version")
    results: list[NormalizedAudioRepairResult] = []
    for record in affected:
        video = database.get_video_by_id(record.video_id)
        if video is None:
            continue
        source = _verified_source_for_derived(database, record.derived_artifact)
        if source is None:
            raise ValueError(
                f"{record.youtube_video_id}: derived normalized audio has no verified source artifact"
            )
        video_paths = resolve_video_artifact_paths(database, app_paths, video)
        media_root = video_paths.audio / "media"
        media_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".provenance-repair-", dir=video_paths.audio
        ) as work:
            normalized_work = normalize_audio(
                Path(source.artifact_path),
                Path(work) / "normalized.wav",
                tools.ffmpeg_bin,
            )
            normalized_path = _materialize_content_addressed(
                normalized_work,
                media_root,
                prefix="normalized",
                protected_paths=_registered_media_paths(database, video.id),
                quarantine_root=(
                    app_paths.logs / "media-recovery" / video.youtube_video_id
                ),
            )
            repaired = register_media_file(
                database,
                app_paths,
                video=video,
                pastor_slug="",
                artifact_path=normalized_path,
                artifact_kind="normalized_audio",
                provenance_kind="derived",
                acquisition_tool="ffmpeg",
                acquisition_tool_version=ffmpeg_version,
                parent=source,
                operation_kind=NORMALIZED_PROVENANCE_REPAIR_VERSION,
            )
        if not media_artifact_covers_isolated_sermon(database, repaired):
            raise RuntimeError(
                f"{record.youtube_video_id}: repaired audio does not cover the isolated sermon"
            )
        _record_attempt(
            database,
            video=video,
            outcome="verified",
            reason_code="normalized_provenance_repaired",
            detail=(
                f"Re-normalized from verified source artifact {source.id}; "
                f"preserved reconstructed artifact {record.reconstructed_artifact.id}."
            ),
            artifact=repaired,
        )
        results.append(
            NormalizedAudioRepairResult(video.id, video.youtube_video_id, repaired, source)
        )
    return tuple(results)


def _latest_verified_normalized_artifact(
    database: Database,
    artifacts: list[MediaArtifact],
    *,
    provenance_kind: str,
) -> MediaArtifact | None:
    for artifact in reversed(artifacts):
        if (
            artifact.artifact_kind == "normalized_audio"
            and artifact.provenance_kind == provenance_kind
            and media_artifact_availability(database, artifact).status
            in {"verified_local", "verified_archived", "archived_media_unavailable"}
            and media_artifact_covers_isolated_sermon(database, artifact)
        ):
            return artifact
    return None


def _verified_source_for_derived(
    database: Database,
    derived: MediaArtifact,
) -> MediaArtifact | None:
    by_id = {
        artifact.id: artifact
        for artifact in database.list_media_artifacts_for_video(derived.video_id)
    }
    parent = by_id.get(derived.parent_media_artifact_id)
    if (
        parent is not None
        and parent.artifact_kind == "source_audio"
        and parent.provenance_kind == "original_download"
    ):
        availability = media_artifact_availability(database, parent)
        if availability.status == "archived_media_unavailable":
            raise ArchivedMediaUnavailableError(parent, availability.path)
        if availability.verified:
            return parent
    return None


def get_archive_safe_normalized_media_artifact(
    database: Database, video_id: int
) -> MediaArtifact | None:
    artifacts = database.list_media_artifacts_for_video(video_id)
    for provenance_kind in ("derived", "reconstructed_existing"):
        for artifact in reversed(artifacts):
            if (
                artifact.artifact_kind != "normalized_audio"
                or artifact.provenance_kind != provenance_kind
            ):
                continue
            if not verify_media_artifact(artifact):
                continue
            if media_artifact_covers_isolated_sermon(
                database, artifact
            ) or media_artifact_covers_complete_recording(database, artifact):
                return artifact
    return None


def verify_media_artifact(
    artifact: MediaArtifact,
    *,
    verification_cache: MediaVerificationCache | None = None,
) -> bool:
    if verification_cache is not None:
        return verification_cache.verify(artifact)
    path = Path(artifact.artifact_path)
    return (
        path.exists()
        and path.stat().st_size == artifact.byte_size
        and _sha256_file(path) == artifact.content_sha256
    )


def media_artifact_covers_isolated_sermon(
    database: Database,
    artifact: MediaArtifact,
    *,
    tolerance_seconds: float = 2.0,
) -> bool:
    window, _ = _isolated_sermon_window(database, artifact.video_id)
    if window is None or artifact.duration_seconds is None:
        return False
    if artifact.duration_seconds + tolerance_seconds >= window[1]:
        return True

    # Caption/transcript segment endpoints can extend beyond the actual media
    # endpoint, especially when the final segment is rounded to a fixed block.
    # Treat a hash-valid full-video artifact as complete only when its measured
    # duration agrees closely with the independently stored video duration and
    # the sermon window reaches that endpoint. The agreement check prevents a
    # stale, shorter video-duration value from blessing genuinely truncated
    # audio.
    video = database.get_video_by_id(artifact.video_id)
    if video is None or video.duration_seconds is None or video.duration_seconds <= 0:
        return False
    video_duration = float(video.duration_seconds)
    reaches_recorded_video_end = (
        abs(artifact.duration_seconds - video_duration) <= tolerance_seconds
    )
    sermon_reaches_video_end = window[1] + tolerance_seconds >= video_duration
    return reaches_recorded_video_end and sermon_reaches_video_end


def media_artifact_covers_complete_recording(
    database: Database,
    artifact: MediaArtifact,
    *,
    tolerance_seconds: float = 2.0,
) -> bool:
    if artifact.duration_seconds is None:
        return False
    video = database.get_video_by_id(artifact.video_id)
    if video is None or video.duration_seconds is None or video.duration_seconds <= 0:
        return False
    return (
        abs(artifact.duration_seconds - float(video.duration_seconds))
        <= tolerance_seconds
    )


def _record_attempt(
    database: Database,
    *,
    video: Video,
    outcome: str,
    reason_code: str,
    detail: str | None,
    artifact: MediaArtifact | None,
    target_kind: str = "normalized_audio",
) -> MediaAcquisitionAttempt:
    fingerprint = _sha256_json(
        {
            "service_version": MEDIA_SERVICE_VERSION,
            "video_id": video.id,
            "target_kind": target_kind,
            "outcome": outcome,
            "reason_code": reason_code,
            "detail": detail,
            "media_artifact_fingerprint": artifact.input_fingerprint if artifact else None,
        }
    )
    return database.add_media_acquisition_attempt(
        video_id=video.id,
        target_kind=target_kind,
        outcome=outcome,
        reason_code=reason_code,
        detail=detail,
        media_artifact_id=artifact.id if artifact else None,
        service_version=MEDIA_SERVICE_VERSION,
        input_fingerprint=fingerprint,
    )


def _probe_audio(path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "duration_seconds": None,
        "format_name": path.suffix.lower().lstrip(".") or None,
        "sample_rate_hz": None,
        "channel_count": None,
    }
    try:
        with wave.open(str(path), "rb") as source:
            metadata.update(
                {
                    "duration_seconds": source.getnframes() / source.getframerate(),
                    "format_name": "wav",
                    "sample_rate_hz": source.getframerate(),
                    "channel_count": source.getnchannels(),
                }
            )
    except (wave.Error, EOFError, ZeroDivisionError):
        pass
    return metadata


def _registered_media_paths(database: Database, video_id: int) -> set[Path]:
    return {
        Path(artifact.artifact_path).expanduser().absolute()
        for artifact in database.list_media_artifacts_for_video(video_id)
    }


def _materialize_content_addressed(
    source: Path,
    root: Path,
    *,
    prefix: str,
    protected_paths: set[Path] | None = None,
    quarantine_root: Path | None = None,
    event_callback: Callable[[str], None] | None = None,
) -> Path:
    """Publish immutable media atomically and recover abandoned local outputs."""
    content_sha256 = _sha256_file(source)
    suffix = source.suffix.lower() or ".bin"
    destination = root / f"{prefix}-{content_sha256}{suffix}"
    root.mkdir(parents=True, exist_ok=True)
    protected = {
        path.expanduser().absolute() for path in (protected_paths or set())
    }
    emit = event_callback or (lambda _message: None)
    lock_path = root / ".pte-materialize.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            partial_pattern = f".{destination.name}.pte-partial-*"
            for abandoned in root.glob(partial_pattern):
                if abandoned.is_symlink() or not abandoned.is_file():
                    raise RuntimeError(
                        f"unsafe media partial recovery target: {abandoned}"
                    )
                abandoned.unlink()
                emit(f"removed abandoned media partial: {abandoned}")

            if destination.exists() or destination.is_symlink():
                actual_sha256 = (
                    _sha256_file(destination)
                    if not destination.is_symlink() and destination.is_file()
                    else None
                )
                if (
                    actual_sha256 is not None
                    and actual_sha256 == content_sha256
                ):
                    return destination
                if destination.is_symlink():
                    raise RuntimeError(
                        f"refusing to replace content-addressed media symlink: "
                        f"{destination}"
                    )
                if destination.expanduser().absolute() in protected:
                    raise RuntimeError(
                        f"registered content-addressed media collision: {destination}"
                    )
                if not destination.is_file():
                    raise RuntimeError(
                        f"unsafe content-addressed media collision: {destination}"
                    )
                if quarantine_root is None:
                    raise RuntimeError(
                        f"content-addressed media collision: {destination}"
                    )
                assert actual_sha256 is not None
                quarantine_root.mkdir(parents=True, exist_ok=True)
                quarantine = _unique_quarantine_path(
                    quarantine_root,
                    destination.name,
                    actual_sha256,
                )
                destination.rename(quarantine)
                emit(
                    "quarantined stale unregistered media collision: "
                    f"{destination} -> {quarantine} "
                    f"(expected_sha256={content_sha256}, "
                    f"actual_sha256={actual_sha256})"
                )

            partial_file = tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{destination.name}.pte-partial-",
                dir=root,
                delete=False,
            )
            partial = Path(partial_file.name)
            try:
                with partial_file:
                    with source.open("rb") as source_file:
                        shutil.copyfileobj(source_file, partial_file)
                    partial_file.flush()
                    os.fsync(partial_file.fileno())
                if (
                    partial.stat().st_size != source.stat().st_size
                    or _sha256_file(partial) != content_sha256
                ):
                    raise RuntimeError(
                        f"media copy verification failed: {destination}"
                    )
                os.replace(partial, destination)
            finally:
                if partial.exists() or partial.is_symlink():
                    partial.unlink()
            return destination
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _unique_quarantine_path(
    root: Path, original_name: str, actual_sha256: str
) -> Path:
    stem = f"{original_name}.mismatched-{actual_sha256[:16]}"
    candidate = root / stem
    sequence = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = root / f"{stem}-{sequence}"
        sequence += 1
    return candidate


def _tool_version(command: str, flag: str) -> str:
    try:
        result = subprocess.run(
            [command, flag],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    first_line = (result.stdout or result.stderr).splitlines()
    return first_line[0].strip() if first_line else "unknown"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_json_idempotent(path: Path, payload: object) -> None:
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"refusing to overwrite changed media manifest: {path}")
        return
    path.write_text(content, encoding="utf-8")
