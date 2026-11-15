"""Pilot directory layout and durable JSON helpers shared by every step."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from pastor_transcript_extractor.config import build_paths, evaluation_root_for

PILOT_NAME = 'bound-claim-pilot-v1'
REPOSITORY = Path(__file__).resolve().parents[3]


def pilot_dir(base_dir: Path | None = None) -> Path:
    path = evaluation_root_for(build_paths(base_dir), base_dir) / PILOT_NAME
    return ensure_outside_repository(path)


def ensure_outside_repository(path: Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved.is_relative_to(REPOSITORY):
        raise ValueError('Generated artifacts must be written under the configured base directory, not the repository')
    return resolved


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            sha.update(chunk)
    return sha.hexdigest()


def write_json(path: Path, value: Any) -> Path:
    """Atomic replace so an interrupted write never leaves a truncated artifact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    os.replace(temporary, path)
    return path


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def coordinate(video_id: int, block_id: int) -> str:
    return f'v{video_id}b{block_id}'


def watch_url(url: str, start_seconds: float) -> str:
    return url + ('&' if '?' in url else '?') + 't=' + str(int(start_seconds))
