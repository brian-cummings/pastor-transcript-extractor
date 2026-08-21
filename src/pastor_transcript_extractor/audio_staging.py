from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable

from pastor_transcript_extractor.media_artifacts import (
    StageSourceAudioResult,
    verify_media_artifact,
)
from pastor_transcript_extractor.storage import Database


AUDIO_STAGE_SCHEMA_VERSION = 1
AudioStageVerificationProgress = Callable[[int, int, str], None]


def write_audio_stage_manifest(
    root: Path,
    results: Iterable[StageSourceAudioResult],
) -> Path:
    rows = []
    for result in sorted(results, key=lambda item: item.video_id):
        artifact = result.artifact
        rows.append(
            {
                "video_id": result.video_id,
                "youtube_video_id": result.youtube_video_id,
                "outcome": result.outcome,
                "reason_code": result.reason_code,
                "artifact_id": artifact.id if artifact else None,
                "artifact_path": artifact.artifact_path if artifact else None,
                "content_sha256": artifact.content_sha256 if artifact else None,
                "byte_size": artifact.byte_size if artifact else None,
                "duration_seconds": artifact.duration_seconds if artifact else None,
            }
        )
    stable = {"schema_version": AUDIO_STAGE_SCHEMA_VERSION, "videos": rows}
    fingerprint = _fingerprint(stable)
    payload = {
        **stable,
        "stage_fingerprint": fingerprint,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    destination = root / "audio-stages" / f"{fingerprint}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def load_and_verify_audio_stage_manifest(
    database: Database,
    path: Path,
    *,
    progress_callback: AudioStageVerificationProgress | None = None,
) -> set[int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Unable to read audio stage manifest {path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != AUDIO_STAGE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported audio stage manifest: {path}")
    videos = payload.get("videos")
    stable = {"schema_version": AUDIO_STAGE_SCHEMA_VERSION, "videos": videos}
    if not isinstance(videos, list) or payload.get("stage_fingerprint") != _fingerprint(stable):
        raise ValueError(f"Audio stage manifest fingerprint mismatch: {path}")
    video_ids: set[int] = set()
    invalid_verified: list[str] = []
    manifest_video_ids: set[int] = set()
    verified_total = sum(
        isinstance(row, dict) and row.get("outcome") == "verified"
        for row in videos
    )
    verified_index = 0
    for row in videos:
        if not isinstance(row, dict) or not isinstance(row.get("video_id"), int):
            raise ValueError(f"Malformed audio stage manifest row: {path}")
        video_id = row["video_id"]
        youtube_id = str(row.get("youtube_video_id") or video_id)
        if video_id in manifest_video_ids:
            raise ValueError(f"Duplicate video id in audio stage manifest: {video_id}")
        manifest_video_ids.add(video_id)
        if row.get("outcome") != "verified":
            continue
        verified_index += 1
        if progress_callback is not None:
            progress_callback(verified_index, verified_total, youtube_id)
        matching = [
            artifact
            for artifact in database.list_media_artifacts_for_video(video_id)
            if artifact.id == row.get("artifact_id")
            and artifact.artifact_kind == "source_audio"
            and artifact.provenance_kind == "original_download"
            and artifact.artifact_path == row.get("artifact_path")
            and artifact.content_sha256 == row.get("content_sha256")
            and artifact.byte_size == row.get("byte_size")
        ]
        if len(matching) != 1 or not verify_media_artifact(matching[0]):
            invalid_verified.append(youtube_id)
            continue
        video_ids.add(video_id)
    if invalid_verified:
        raise ValueError(
            "Audio stage no longer verifies for claimed verified entries: "
            + ", ".join(invalid_verified)
        )
    if not video_ids:
        raise ValueError("Audio stage manifest contains no verified videos.")
    return video_ids


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
