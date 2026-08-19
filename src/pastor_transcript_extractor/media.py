from __future__ import annotations

import subprocess
from pathlib import Path


class YtDlpError(RuntimeError):
    pass


class NoCaptionsAvailableError(YtDlpError, FileNotFoundError):
    pass


class VideoUnavailableError(YtDlpError):
    pass


class VideoNotYetAvailableError(YtDlpError):
    pass


class YtDlpConfigurationError(YtDlpError):
    pass


class YtDlpRateLimitError(YtDlpError):
    pass


def _run_yt_dlp(command: list[str], *, url: str, expect_captions: bool = False) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 0:
        return

    raw_output = "\n".join(part for part in (result.stderr, result.stdout) if part)
    output_lines = [line.strip() for line in raw_output.splitlines() if line.strip()]
    full_output = "\n".join(output_lines)
    lowered_output = full_output.lower()
    error_lines = [
        line for line in output_lines if line.lower().startswith("error:")
    ]
    detail = (
        error_lines[-1]
        if error_lines
        else output_lines[-1]
        if output_lines
        else f"yt-dlp exited with status {result.returncode}"
    )
    lowered = detail.lower()
    if expect_captions and "there are no subtitles for the requested languages" in lowered_output:
        raise NoCaptionsAvailableError(f"No captions available for {url}")
    if "this live event will begin" in lowered_output or "premieres in" in lowered_output:
        raise VideoNotYetAvailableError(f"Video has not started yet for {url}: {detail}")
    configuration_markers = (
        "no supported javascript runtime could be found",
        "remote component challenge solver script",
        "ensure you have a supported javascript runtime and challenge solver script distribution installed",
    )
    if any(marker in lowered_output for marker in configuration_markers):
        raise YtDlpConfigurationError(
            "yt-dlp cannot solve YouTube JavaScript challenges; install the "
            "yt-dlp default extras and configure a supported JS runtime"
        )
    if "http error 429" in lowered_output or "too many requests" in lowered_output:
        raise YtDlpRateLimitError(
            f"YouTube rate limited yt-dlp for {url}: {detail}"
        )
    if "this video is not available" in lowered or "video unavailable" in lowered:
        raise VideoUnavailableError(f"Video unavailable for {url}")
    raise YtDlpError(detail)


def _run_audio_download(command: list[str], *, url: str) -> None:
    """Retry YouTube GVS 403s with the token-free embedded player client."""
    try:
        _run_yt_dlp(command, url=url)
    except YtDlpError as error:
        if "http error 403" not in str(error).lower():
            raise
        retry_command = [
            *command[:-1],
            "--extractor-args",
            "youtube:player_client=web_embedded",
            command[-1],
        ]
        _run_yt_dlp(retry_command, url=url)


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


def download_source_audio(
    url: str,
    yt_dlp_bin: str,
    output_path: Path,
    yt_dlp_js_runtimes: str | None = None,
) -> Path:
    """Download native best audio without decoding it to a second WAV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base = output_path.with_suffix("")
    command = [
        yt_dlp_bin,
        "--no-playlist",
        "-f",
        "bestaudio/best",
    ]
    if yt_dlp_js_runtimes:
        command.extend(["--js-runtimes", yt_dlp_js_runtimes])
    command.extend(
        [
            "--no-progress",
            "-o",
            f"{base}.%(ext)s",
            url,
        ]
    )
    _run_audio_download(command, url=url)
    candidates = sorted(
        (
            path
            for path in base.parent.glob(f"{base.name}.*")
            if path.suffix not in {".part", ".ytdl"}
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"yt-dlp did not create source audio for {url}")
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
