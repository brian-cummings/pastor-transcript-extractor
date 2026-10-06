from __future__ import annotations

from importlib import metadata as importlib_metadata
from pathlib import Path
import shutil
import sys

import typer
from rich.console import Console
from rich.table import Table

from pastor_transcript_extractor import config, local_llm
from pastor_transcript_extractor.commands.apps import root_app
from pastor_transcript_extractor.config import ensure_directories
from pastor_transcript_extractor.sermon_policy import (
    maximum_sermon_duration_seconds,
    minimum_sermon_duration_seconds,
)


console = Console()


def _path_status(path: Path) -> str:
    return "ok" if path.exists() else "missing"


def _tool_status(command: str) -> tuple[str, str]:
    resolved = shutil.which(command)
    if resolved is None:
        local_candidate = Path(sys.executable).parent / command
        if local_candidate.exists():
            resolved = str(local_candidate)
    return (resolved or command, "ok" if resolved else "missing")


def _package_status(distribution: str) -> tuple[str, str]:
    try:
        return (importlib_metadata.version(distribution), "ok")
    except importlib_metadata.PackageNotFoundError:
        return ("not installed", "missing")


@root_app.command(help="Validate local tool paths and app data directories.")
def doctor(
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    paths = config.build_paths(base_dir, remember=True)
    tools = config.build_tool_config()
    llm = config.build_llm_config()
    sermon_minimum = minimum_sermon_duration_seconds()
    sermon_maximum = maximum_sermon_duration_seconds()

    try:
        ensure_directories(paths)
        app_status = "ok"
    except PermissionError:
        app_status = "unwritable"

    rows = [
        ("app root", str(paths.root), app_status),
        ("database", str(paths.database), _path_status(paths.database)),
        ("pastors dir", str(paths.pastors), _path_status(paths.pastors)),
        ("whisper.cpp", str(tools.whisper_cpp_bin), _path_status(tools.whisper_cpp_bin)),
        (
            "whisper model",
            str(tools.whisper_model_path),
            _path_status(tools.whisper_model_path),
        ),
        ("sermon minimum", f"{sermon_minimum:g} seconds", "configured"),
        ("sermon-video maximum", f"{sermon_maximum:g} seconds", "configured"),
    ]

    ffmpeg_resolved, ffmpeg_status = _tool_status(tools.ffmpeg_bin)
    yt_dlp_resolved, yt_dlp_status = _tool_status(tools.yt_dlp_bin)
    rows.append(("ffmpeg", ffmpeg_resolved, ffmpeg_status))
    rows.append(("yt-dlp", yt_dlp_resolved, yt_dlp_status))
    rows.append(
        (
            "yt-dlp js runtime",
            tools.yt_dlp_js_runtimes or "none detected",
            "ok" if tools.yt_dlp_js_runtimes else "missing",
        )
    )
    ejs_version, ejs_status = _package_status("yt-dlp-ejs")
    rows.append(("yt-dlp EJS solver", ejs_version, ejs_status))
    rows.append(("local LLM", llm.base_url, "enabled" if llm.enabled else "disabled"))
    rows.append(
        ("local LLM model", llm.model, "configured" if llm.enabled else "inactive")
    )
    if llm.enabled:
        health = local_llm.OllamaClient(llm).check_health()
        rows.append(
            (
                "Ollama connectivity",
                health.detail,
                "ok" if health.reachable else "failed",
            )
        )
        rows.append(
            (
                "Ollama model installed",
                llm.model,
                "ok" if health.model_available else "failed",
            )
        )
        rows.append(
            (
                "Ollama structured output",
                health.detail,
                "ok" if health.structured_output else "failed",
            )
        )

    table = Table(title="Doctor")
    table.add_column("Check")
    table.add_column("Resolved Path")
    table.add_column("Status")
    for check, resolved, status_value in rows:
        table.add_row(check, resolved, status_value)
    console.print(table)
