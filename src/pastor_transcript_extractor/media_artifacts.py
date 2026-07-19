from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any
import wave

from pastor_transcript_extractor.config import (
    AppPaths,
    ToolConfig,
    build_transcript_artifact_paths,
    build_video_artifact_paths,
)
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
    }
    input_fingerprint = _sha256_json(fingerprint_payload)
    video_paths = build_video_artifact_paths(app_paths, pastor_slug, video.youtube_video_id)
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
        if video.pastor_id is None:
            continue
        pastor = database.get_pastor_by_id(video.pastor_id)
        if pastor is None:
            continue
        transcript_paths = build_transcript_artifact_paths(
            app_paths, pastor.slug, video.youtube_video_id
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
                pastor_slug=pastor.slug,
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
                    pastor_slug=pastor.slug,
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
    if video.pastor_id is None:
        raise ValueError(f"Video {video.id} is missing a linked pastor")
    pastor = database.get_pastor_by_id(video.pastor_id)
    if pastor is None:
        raise ValueError(f"Video {video.id} is missing a linked pastor")

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
    video_paths = build_video_artifact_paths(app_paths, pastor.slug, video.youtube_video_id)
    media_root = video_paths.audio / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=".media-work-", dir=video_paths.audio) as work:
            work_root = Path(work)
            downloaded = download_source_audio(
                video.url,
                tools.yt_dlp_bin,
                work_root / "source",
                tools.yt_dlp_js_runtimes,
            )
            source_path = _materialize_content_addressed(
                downloaded, media_root, prefix="source"
            )
            source_artifact = register_media_file(
                database,
                app_paths,
                video=video,
                pastor_slug=pastor.slug,
                artifact_path=source_path,
                artifact_kind="source_audio",
                provenance_kind="original_download",
                acquisition_tool="yt-dlp",
                acquisition_tool_version=versions["yt-dlp"],
            )
            normalized_work = normalize_audio(
                downloaded,
                work_root / "normalized.wav",
                tools.ffmpeg_bin,
            )
            normalized_path = _materialize_content_addressed(
                normalized_work, media_root, prefix="normalized"
            )
            normalized_artifact = register_media_file(
                database,
                app_paths,
                video=video,
                pastor_slug=pastor.slug,
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
            True,
        )
    except VideoUnavailableError as error:
        attempt = _record_attempt(
            database,
            video=video,
            outcome="unavailable",
            reason_code="video_unavailable",
            detail=str(error),
            artifact=None,
        )
        return EnsureAudioResult(
            video.id,
            video.youtube_video_id,
            True,
            "unavailable",
            "video_unavailable",
            None,
            attempt,
            False,
        )
    except (YtDlpError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        attempt = _record_attempt(
            database,
            video=video,
            outcome="failed",
            reason_code="media_acquisition_failed",
            detail=f"{type(error).__name__}: {error}",
            artifact=None,
        )
        return EnsureAudioResult(
            video.id,
            video.youtube_video_id,
            True,
            "failed",
            "media_acquisition_failed",
            None,
            attempt,
            False,
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


def resolve_normalized_audio_path(database: Database, video_id: int) -> Path | None:
    artifact = get_verified_normalized_media_artifact(database, video_id)
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
    database: Database, video_id: int
) -> MediaArtifact | None:
    artifacts = database.list_media_artifacts_for_video(video_id)
    for artifact in reversed(artifacts):
        if artifact.artifact_kind != "normalized_audio":
            continue
        if verify_media_artifact(artifact) and media_artifact_covers_isolated_sermon(
            database, artifact
        ):
            return artifact
    return None


def get_archive_safe_normalized_media_artifact(
    database: Database, video_id: int
) -> MediaArtifact | None:
    artifacts = database.list_media_artifacts_for_video(video_id)
    for artifact in reversed(artifacts):
        if artifact.artifact_kind != "normalized_audio":
            continue
        if not verify_media_artifact(artifact):
            continue
        if media_artifact_covers_isolated_sermon(
            database, artifact
        ) or media_artifact_covers_complete_recording(database, artifact):
            return artifact
    return None


def verify_media_artifact(artifact: MediaArtifact) -> bool:
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
) -> MediaAcquisitionAttempt:
    fingerprint = _sha256_json(
        {
            "service_version": MEDIA_SERVICE_VERSION,
            "video_id": video.id,
            "target_kind": "normalized_audio",
            "outcome": outcome,
            "reason_code": reason_code,
            "detail": detail,
            "media_artifact_fingerprint": artifact.input_fingerprint if artifact else None,
        }
    )
    return database.add_media_acquisition_attempt(
        video_id=video.id,
        target_kind="normalized_audio",
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


def _materialize_content_addressed(source: Path, root: Path, *, prefix: str) -> Path:
    content_sha256 = _sha256_file(source)
    suffix = source.suffix.lower() or ".bin"
    destination = root / f"{prefix}-{content_sha256}{suffix}"
    if destination.exists():
        if _sha256_file(destination) != content_sha256:
            raise RuntimeError(f"content-addressed media collision: {destination}")
        return destination
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if _sha256_file(destination) != content_sha256:
        raise RuntimeError(f"media copy verification failed: {destination}")
    return destination


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
