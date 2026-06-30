from __future__ import annotations

import html
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pastor_transcript_extractor.config import AppPaths, ToolConfig, build_transcript_artifact_paths, build_video_artifact_paths
from pastor_transcript_extractor.media import download_audio, download_captions, normalize_audio
from pastor_transcript_extractor.models import TranscriptArtifact, TranscriptSourceKind, VideoStatus
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    artifact: TranscriptArtifact
    metadata_path: Path
    normalized_audio_path: Path
    raw_json_path: Path
    raw_text_path: Path


@dataclass(frozen=True, slots=True)
class CaptionResult:
    artifact: TranscriptArtifact
    metadata_path: Path
    captions_path: Path
    raw_json_path: Path
    raw_text_path: Path


_VTT_INLINE_TIMESTAMP_RE = re.compile(r"<\d{2}:\d{2}:\d{2}\.\d{3}>")
_VTT_TAG_RE = re.compile(r"</?[^>]+>")
_VTT_CUE_TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}\.\d{3})"
)


def _normalize_caption_line(line: str) -> str:
    without_timestamps = _VTT_INLINE_TIMESTAMP_RE.sub(" ", line)
    without_tags = _VTT_TAG_RE.sub("", without_timestamps)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _captions_to_plain_text(captions_path: Path) -> str:
    lines: list[str] = []
    previous_line: str | None = None
    for raw_line in captions_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if (
            not line
            or line.startswith("WEBVTT")
            or line.startswith("Kind:")
            or line.startswith("Language:")
            or line.isdigit()
            or "-->" in line
        ):
            continue
        normalized_line = _normalize_caption_line(line)
        if not normalized_line or normalized_line == previous_line:
            continue
        lines.append(normalized_line)
        previous_line = normalized_line
    return "\n".join(lines).strip() + ("\n" if lines else "")


def _parse_vtt_timestamp(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _captions_to_segments(captions_path: Path) -> list[dict[str, float | str]]:
    segments: list[dict[str, float | str]] = []
    current_start: float | None = None
    current_end: float | None = None
    current_lines: list[str] = []
    previous_text: str | None = None

    def flush() -> None:
        nonlocal current_start, current_end, current_lines, previous_text
        if current_start is None or current_end is None:
            current_lines = []
            return
        text = _normalize_caption_line(" ".join(current_lines))
        current_lines = []
        if not text or text == previous_text:
            return
        segments.append(
            {
                "start": current_start,
                "end": current_end,
                "text": text,
            }
        )
        previous_text = text

    for raw_line in captions_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        timestamp_match = _VTT_CUE_TIMESTAMP_RE.match(line)
        if timestamp_match:
            flush()
            current_start = _parse_vtt_timestamp(timestamp_match.group("start"))
            current_end = _parse_vtt_timestamp(timestamp_match.group("end"))
            continue
        if (
            not line
            or line.startswith("WEBVTT")
            or line.startswith("Kind:")
            or line.startswith("Language:")
            or line.isdigit()
        ):
            continue
        current_lines.append(line)

    flush()
    return segments


def run_whisper_cpp(whisper_cpp_bin: Path, model_path: Path, audio_path: Path, output_base: Path) -> tuple[Path, Path]:
    output_base.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(whisper_cpp_bin),
        "-m",
        str(model_path),
        "-f",
        str(audio_path),
        "-oj",
        "-otxt",
        "-of",
        str(output_base),
        "-np",
        "-nt",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"whisper.cpp exited with status {result.returncode}"
        raise RuntimeError(detail)

    json_path = output_base.with_suffix(".json")
    txt_path = output_base.with_suffix(".txt")
    if not json_path.exists():
        raise FileNotFoundError(f"whisper.cpp did not create JSON output at {json_path}")
    if not txt_path.exists():
        raise FileNotFoundError(f"whisper.cpp did not create text output at {txt_path}")
    return json_path, txt_path


def fetch_captions_video(
    database: Database,
    app_paths: AppPaths,
    tools: ToolConfig,
    video_id: int,
) -> CaptionResult:
    video = database.get_video_by_id(video_id)
    if video is None:
        raise ValueError(f"Unknown video id: {video_id}")
    pastor = database.get_pastor_by_id(video.pastor_id)
    if pastor is None:
        raise ValueError(f"Video {video_id} is missing a linked pastor")

    transcript_paths = build_transcript_artifact_paths(app_paths, pastor.slug, video.youtube_video_id)
    video_paths = build_video_artifact_paths(app_paths, pastor.slug, video.youtube_video_id)
    for directory in (video_paths.root, video_paths.audio, video_paths.raw, video_paths.extracted, video_paths.review):
        directory.mkdir(parents=True, exist_ok=True)

    captions_path = download_captions(
        video.url,
        tools.yt_dlp_bin,
        transcript_paths.raw_text,
        tools.yt_dlp_js_runtimes,
    )
    raw_text = _captions_to_plain_text(captions_path)
    raw_segments = _captions_to_segments(captions_path)
    raw_text_path = transcript_paths.raw_text
    raw_text_path.write_text(raw_text, encoding="utf-8")
    raw_json_path = transcript_paths.raw_json
    raw_json_path.write_text(
        json.dumps(
            {
                "video_id": video.id,
                "youtube_video_id": video.youtube_video_id,
                "pastor_slug": pastor.slug,
                "captions_path": str(captions_path),
                "raw_text_path": str(raw_text_path),
                "text": raw_text.strip(),
                "segments": raw_segments,
                "duration_seconds": raw_segments[-1]["end"] if raw_segments else video.duration_seconds,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    metadata = {
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "pastor_id": pastor.id,
        "pastor_slug": pastor.slug,
        "source_url": video.url,
        "transcription_backend": "captions",
        "yt_dlp_bin": str(tools.yt_dlp_bin),
        "yt_dlp_js_runtimes": tools.yt_dlp_js_runtimes,
        "captions_path": str(captions_path),
        "raw_text_path": str(raw_text_path),
        "raw_json_path": str(raw_json_path),
    }
    video_paths.metadata.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    artifact = database.add_transcript_artifact(
        video_id=video.id,
        source_kind=TranscriptSourceKind.CAPTIONS,
        audio_path=None,
        raw_json_path=str(raw_json_path),
        raw_text_path=str(raw_text_path),
    )
    database.update_video_status(video.id, VideoStatus.TRANSCRIPT_FETCHED)
    return CaptionResult(
        artifact=artifact,
        metadata_path=video_paths.metadata,
        captions_path=captions_path,
        raw_json_path=raw_json_path,
        raw_text_path=raw_text_path,
    )


def transcribe_video(
    database: Database,
    app_paths: AppPaths,
    tools: ToolConfig,
    video_id: int,
) -> TranscriptResult:
    video = database.get_video_by_id(video_id)
    if video is None:
        raise ValueError(f"Unknown video id: {video_id}")
    pastor = database.get_pastor_by_id(video.pastor_id)
    if pastor is None:
        raise ValueError(f"Video {video_id} is missing a linked pastor")

    transcript_paths = build_transcript_artifact_paths(app_paths, pastor.slug, video.youtube_video_id)
    video_paths = build_video_artifact_paths(app_paths, pastor.slug, video.youtube_video_id)
    for directory in (video_paths.root, video_paths.audio, video_paths.raw, video_paths.extracted, video_paths.review):
        directory.mkdir(parents=True, exist_ok=True)

    downloaded_audio = download_audio(
        video.url,
        tools.yt_dlp_bin,
        transcript_paths.audio_download,
        tools.yt_dlp_js_runtimes,
    )
    normalized_audio = normalize_audio(downloaded_audio, transcript_paths.audio_normalized, tools.ffmpeg_bin)
    raw_json_path, raw_text_path = run_whisper_cpp(
        tools.whisper_cpp_bin,
        tools.whisper_model_path,
        normalized_audio,
        transcript_paths.whisper_output_base,
    )

    metadata = {
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "pastor_id": pastor.id,
        "pastor_slug": pastor.slug,
        "source_url": video.url,
        "transcription_backend": "whisper.cpp",
        "yt_dlp_bin": str(tools.yt_dlp_bin),
        "yt_dlp_js_runtimes": tools.yt_dlp_js_runtimes,
        "whisper_cpp_bin": str(tools.whisper_cpp_bin),
        "whisper_model_path": str(tools.whisper_model_path),
        "normalized_audio_path": str(normalized_audio),
        "raw_json_path": str(raw_json_path),
        "raw_text_path": str(raw_text_path),
    }
    transcript_paths.root.mkdir(parents=True, exist_ok=True)
    video_paths.metadata.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    artifact = database.add_transcript_artifact(
        video_id=video.id,
        source_kind=TranscriptSourceKind.LOCAL_ASR,
        audio_path=str(normalized_audio),
        raw_json_path=str(raw_json_path),
        raw_text_path=str(raw_text_path),
    )
    database.update_video_status(video.id, VideoStatus.TRANSCRIBED_LOCAL)
    return TranscriptResult(
        artifact=artifact,
        metadata_path=video_paths.metadata,
        normalized_audio_path=normalized_audio,
        raw_json_path=raw_json_path,
        raw_text_path=raw_text_path,
    )
