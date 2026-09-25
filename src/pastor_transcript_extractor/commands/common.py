from __future__ import annotations

from pathlib import Path

import typer

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.storage import Database


def get_database(base_dir: Path | None = None) -> Database:
    paths = build_paths(base_dir, remember=True)
    ensure_directories(paths)
    database = Database(paths.database)
    database.initialize()
    return database


def unknown_pastor_error(
    pastor_slug: str,
    base_dir: Path | None = None,
) -> typer.BadParameter:
    resolved_root = build_paths(base_dir).root
    return typer.BadParameter(
        f"Unknown pastor slug: {pastor_slug} (app root: {resolved_root})"
    )
