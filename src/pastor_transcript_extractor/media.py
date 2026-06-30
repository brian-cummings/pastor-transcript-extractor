from __future__ import annotations

import subprocess
from pathlib import Path


class YtDlpError(RuntimeError):
    pass


class NoCaptionsAvailableError(YtDlpError, FileNotFoundError):
    pass


class VideoUnavailableError(YtDlpError):
    pass


def _run_yt_dlp(command: list[str], *, url: str, expect_captions: bool = False) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 0:
        return

    output_lines = [line.strip() for line in (result.stderr or result.stdout).splitlines() if line.strip()]
    detail = output_lines[-1] if output_lines else f"yt-dlp exited with status {result.returncode}"
    lowered = detail.lower()
    if expect_captions and "there are no subtitles for the requested languages" in lowered:
        raise NoCaptionsAvailableError(f"No captions available for {url}")
    if "this video is not available" in lowered or "video unavailable" in lowered:
        raise VideoUnavailableError(f"Video unavailable for {url}")
    raise YtDlpError(detail)


def download_captions(url: str, yt_dlp_bin: str, output_path: Path, yt_dlp_js_runtimes: str | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base = output_path.with_suffix("")
    command = [
        yt_dlp_bin,
        "--no-playlist",
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        "en.*,en,en-US",
        "--sub-format",
        "vtt",
    ]
    if yt_dlp_js_runtimes:
        command.extend(["--js-runtimes", yt_dlp_js_runtimes])
    command.extend(
        [
            "--no-warnings",
            "--no-progress",
            "-o",
            f"{base}.%(ext)s",
            url,
        ]
    )
    _run_yt_dlp(command, url=url, expect_captions=True)

    candidates = list(base.parent.glob(f"{base.name}*.vtt")) + list(base.parent.glob(f"{base.name}*.srt"))
    candidates = sorted(
        candidates,
        key=lambda path: (
            0 if ".en" in path.name or "en-" in path.name else 1,
            0 if "auto" not in path.name.lower() else 1,
            -path.stat().st_mtime,
        ),
    )
    if not candidates:
        raise NoCaptionsAvailableError(f"yt-dlp did not create captions for {url}")
    return candidates[0]


def download_audio(url: str, yt_dlp_bin: str, output_path: Path, yt_dlp_js_runtimes: str | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base = output_path.with_suffix("")
    command = [
        yt_dlp_bin,
        "--no-playlist",
        "-x",
        "--audio-format",
        "wav",
        "--audio-quality",
        "0",
    ]
    if yt_dlp_js_runtimes:
        command.extend(["--js-runtimes", yt_dlp_js_runtimes])
    command.extend(
        [
            "--no-warnings",
            "--no-progress",
            "-o",
            f"{base}.%(ext)s",
            url,
        ]
    )
    _run_yt_dlp(command, url=url)

    candidates = sorted(base.parent.glob(f"{base.name}.*"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"yt-dlp did not create audio for {url}")
    return candidates[0]


def normalize_audio(input_path: Path, output_path: Path, ffmpeg_bin: str) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-vn",
        str(output_path),
    ]
    subprocess.run(command, check=True)
    if not output_path.exists():
        raise FileNotFoundError(f"ffmpeg did not create normalized audio at {output_path}")
    return output_path
