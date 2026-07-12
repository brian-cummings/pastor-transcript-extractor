from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


APP_DIR_NAME = ".pastor-transcript-extractor"
APP_DIR_POINTER_NAME = ".pastor-transcript-extractor-root"
APP_CONFIG_DIR_NAME = "pastor-transcript-extractor"
APP_CONFIG_FILE_NAME = "config.json"
DEFAULT_WHISPER_CPP_BIN = Path("/Users/briancummings/code/whisper.cpp/build/bin/whisper-cli")
DEFAULT_WHISPER_MODEL_PATH = Path("/Users/briancummings/code/whisper.cpp/models/ggml-medium.en.bin")
DEFAULT_FFMPEG_BIN = "ffmpeg"
DEFAULT_YT_DLP_BIN = "yt-dlp"


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    database: Path
    artifacts: Path
    logs: Path
    exports: Path
    pastors: Path


@dataclass(frozen=True, slots=True)
class ToolConfig:
    whisper_cpp_bin: Path
    whisper_model_path: Path
    ffmpeg_bin: str
    yt_dlp_bin: str
    yt_dlp_js_runtimes: str | None


@dataclass(frozen=True, slots=True)
class LlmConfig:
    enabled: bool
    base_url: str
    model: str
    timeout_seconds: float
    prompt_version: str


@dataclass(frozen=True, slots=True)
class PastorPaths:
    root: Path
    profile: Path
    videos: Path
    exports: Path


@dataclass(frozen=True, slots=True)
class VideoArtifactPaths:
    root: Path
    metadata: Path
    audio: Path
    raw: Path
    extracted: Path
    review: Path


@dataclass(frozen=True, slots=True)
class TranscriptArtifactPaths:
    root: Path
    audio_download: Path
    audio_normalized: Path
    whisper_output_base: Path
    raw_json: Path
    raw_text: Path


def _pointer_path() -> Path:
    return Path.home() / APP_DIR_POINTER_NAME


def _config_dir_path() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser().resolve() / APP_CONFIG_DIR_NAME
    return (Path.home() / ".config" / APP_CONFIG_DIR_NAME).expanduser().resolve()


def _config_path() -> Path:
    return _config_dir_path() / APP_CONFIG_FILE_NAME


def _load_saved_base_dir_from_config() -> Path | None:
    config_path = _config_path()
    if not config_path.exists():
        return None
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    base_dir = payload.get("base_dir")
    if not isinstance(base_dir, str) or not base_dir.strip():
        return None
    return Path(base_dir).expanduser().resolve()


def _load_saved_base_dir_from_pointer() -> Path | None:
    pointer = _pointer_path()
    if not pointer.exists():
        return None
    try:
        saved = pointer.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not saved:
        return None
    return Path(saved).expanduser().resolve()


def remember_base_dir(base_dir: Path) -> None:
    resolved = base_dir.expanduser().resolve()
    try:
        _config_dir_path().mkdir(parents=True, exist_ok=True)
        _config_path().write_text(json.dumps({"base_dir": str(resolved)}, indent=2), encoding="utf-8")
    except PermissionError:
        pass
    try:
        _pointer_path().write_text(str(resolved), encoding="utf-8")
    except PermissionError:
        # Best-effort persistence: if the home directory is not writable in the
        # current environment, still honor the explicit base_dir for this run.
        pass


def resolve_base_dir(base_dir: Path | None = None) -> Path:
    if base_dir is not None:
        return base_dir.expanduser().resolve()

    env_base_dir = os.environ.get("PTE_BASE_DIR")
    if env_base_dir:
        return Path(env_base_dir).expanduser().resolve()

    config_base_dir = _load_saved_base_dir_from_config()
    if config_base_dir is not None:
        return config_base_dir

    pointer_base_dir = _load_saved_base_dir_from_pointer()
    if pointer_base_dir is not None:
        return pointer_base_dir

    return (Path.home() / APP_DIR_NAME).expanduser().resolve()


def build_paths(base_dir: Path | None = None, remember: bool = False) -> AppPaths:
    if remember and base_dir is not None:
        remember_base_dir(base_dir)
    root = resolve_base_dir(base_dir)
    pastors = root / "pastors"
    return AppPaths(
        root=root,
        database=root / "app.db",
        artifacts=root / "artifacts",
        logs=root / "logs",
        exports=root / "exports",
        pastors=pastors,
    )


def _resolve_command_path(command: str) -> str:
    candidate = Path(command)
    if candidate.exists():
        return str(candidate)
    local_candidate = Path(sys.executable).parent / command
    if local_candidate.exists():
        return str(local_candidate)
    return command


def build_tool_config() -> ToolConfig:
    return ToolConfig(
        whisper_cpp_bin=Path(os.environ.get("PTE_WHISPER_CPP_BIN", DEFAULT_WHISPER_CPP_BIN)),
        whisper_model_path=Path(os.environ.get("PTE_WHISPER_MODEL_PATH", DEFAULT_WHISPER_MODEL_PATH)),
        ffmpeg_bin=_resolve_command_path(os.environ.get("PTE_FFMPEG_BIN", DEFAULT_FFMPEG_BIN)),
        yt_dlp_bin=_resolve_command_path(os.environ.get("PTE_YT_DLP_BIN", DEFAULT_YT_DLP_BIN)),
        yt_dlp_js_runtimes=os.environ.get("PTE_YT_DLP_JS_RUNTIMES") or None,
    )


def build_llm_config() -> LlmConfig:
    enabled = os.environ.get("PTE_LLM_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    return LlmConfig(
        enabled=enabled,
        base_url=os.environ.get("PTE_LLM_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
        model=os.environ.get("PTE_LLM_MODEL", "gemma3:4b"),
        timeout_seconds=float(os.environ.get("PTE_LLM_TIMEOUT_SECONDS", "60")),
        prompt_version=os.environ.get("PTE_LLM_PROMPT_VERSION", "sermon-content-v2"),
    )


def ensure_directories(paths: AppPaths) -> None:
    for directory in (paths.root, paths.artifacts, paths.logs, paths.exports, paths.pastors):
        directory.mkdir(parents=True, exist_ok=True)


def build_pastor_paths(paths: AppPaths, pastor_slug: str) -> PastorPaths:
    pastor_root = paths.pastors / pastor_slug
    return PastorPaths(
        root=pastor_root,
        profile=pastor_root / "profile.json",
        videos=pastor_root / "videos",
        exports=pastor_root / "exports",
    )


def build_video_artifact_paths(paths: AppPaths, pastor_slug: str, youtube_video_id: str) -> VideoArtifactPaths:
    video_root = paths.pastors / pastor_slug / "videos" / youtube_video_id
    return VideoArtifactPaths(
        root=video_root,
        metadata=video_root / "metadata.json",
        audio=video_root / "audio",
        raw=video_root / "raw",
        extracted=video_root / "extracted",
        review=video_root / "review",
    )


def build_transcript_artifact_paths(paths: AppPaths, pastor_slug: str, youtube_video_id: str) -> TranscriptArtifactPaths:
    video_paths = build_video_artifact_paths(paths, pastor_slug, youtube_video_id)
    return TranscriptArtifactPaths(
        root=video_paths.root,
        audio_download=video_paths.audio / "downloaded.wav",
        audio_normalized=video_paths.audio / "normalized.wav",
        whisper_output_base=video_paths.raw / "whisper",
        raw_json=video_paths.raw / "whisper.json",
        raw_text=video_paths.raw / "whisper.txt",
    )
