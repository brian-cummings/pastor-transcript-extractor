"""Shared freshness identities for provider-free analytical artifact caches."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def file_signature(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "exists": False}
    file = Path(path).expanduser().resolve()
    try:
        stat = file.stat()
    except OSError:
        return {"path": str(file), "exists": False}
    return {"path": str(file), "exists": True, "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns}


def database_snapshot(path: Path, now: datetime) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    return {"database": file_signature(resolved),
            "wal": file_signature(str(resolved) + "-wal"),
            "as_of_utc_hour": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")}


def write_json_markdown(path: Path, report: object, rendered: str) -> tuple[Path, Path, bool]:
    """Reuse exact output pairs; repair either artifact if its contents differ."""
    path = path.expanduser().resolve()
    markdown = path.with_suffix(".md")
    if markdown == path:
        raise ValueError("JSON output path must differ from its Markdown companion")
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    try:
        if path.read_text(encoding="utf-8") == payload and markdown.read_text(encoding="utf-8") == rendered:
            return path, markdown, True
    except (OSError, UnicodeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    markdown.write_text(rendered, encoding="utf-8")
    return path, markdown, False

