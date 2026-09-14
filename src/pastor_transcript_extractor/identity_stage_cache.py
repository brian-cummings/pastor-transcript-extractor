from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping, Sequence


IDENTITY_STAGE_CACHE_VERSION = "identity_stage_cache_v1"

# These tables contain the durable inputs used by association and discovery.
# Deliberately include more state than either stage currently consumes: an
# unnecessary refresh is safe, while overlooking a new identity signal is not.
IDENTITY_INPUT_TABLES = (
    "pastors",
    "sources",
    "videos",
    "excluded_videos",
    "extraction_results",
    "review_results",
    "metadata_artifacts",
    "media_artifacts",
    "media_archive_destinations",
    "media_archive_entries",
    "identity_evidence",
    "identity_assessments",
    "speaker_profiles",
    "pastor_speaker_bindings",
    "speaker_observations",
    "speaker_name_claims",
    "profile_observation_events",
    "speaker_profile_creation_events",
    "speaker_profile_discovery_promotions",
    "speaker_profile_candidate_confirmations",
    "speaker_machine_evidence",
    "speaker_machine_assignment_events",
    "speaker_observation_review_events",
    "speaker_observation_grouping_events",
    "speaker_observation_difference_events",
    "profile_name_claim_events",
    "speaker_profile_redirect_events",
)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_sha256(payload: object) -> str:
    return _sha256_bytes(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"bytes_sha256": _sha256_bytes(value), "size": len(value)}
    return value


def _database_snapshot(database_path: Path) -> list[dict[str, Any]]:
    uri = f"file:{database_path.expanduser().resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        existing_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        snapshot: list[dict[str, Any]] = []
        for table in IDENTITY_INPUT_TABLES:
            if table not in existing_tables:
                continue
            columns = [
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            ]
            rows = [
                [_json_value(value) for value in row]
                for row in connection.execute(
                    f'SELECT * FROM "{table}" ORDER BY rowid'
                )
            ]
            snapshot.append(
                {"table": table, "columns": columns, "rows": rows}
            )
        return snapshot
    finally:
        connection.close()


def _file_snapshot(paths: Iterable[Path]) -> list[dict[str, Any]]:
    files: set[Path] = set()
    for candidate in paths:
        resolved = candidate.expanduser().resolve()
        if resolved.is_dir():
            files.update(path for path in resolved.rglob("*.json") if path.is_file())
        elif resolved.is_file():
            files.add(resolved)
    return [
        {
            "path": str(path),
            "size": path.stat().st_size,
            "sha256": _sha256_bytes(path.read_bytes()),
        }
        for path in sorted(files, key=str)
    ]


def build_identity_stage_fingerprint(
    database_path: Path,
    *,
    stage: str,
    parameters: Mapping[str, Any],
    input_paths: Iterable[Path] = (),
) -> str:
    """Fingerprint every durable input that may change an identity stage."""
    return _json_sha256(
        {
            "cache_version": IDENTITY_STAGE_CACHE_VERSION,
            "stage": stage,
            "parameters": dict(parameters),
            "database": _database_snapshot(database_path),
            "files": _file_snapshot(input_paths),
        }
    )


def load_identity_stage_checkpoint(
    root: Path,
    *,
    stage: str,
    input_fingerprint: str,
) -> tuple[Path, ...] | None:
    path = root.expanduser().resolve() / f"{stage}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("cache_version") != IDENTITY_STAGE_CACHE_VERSION
        or payload.get("stage") != stage
        or payload.get("input_fingerprint") != input_fingerprint
        or not isinstance(payload.get("outputs"), list)
    ):
        return None
    expected_checkpoint_sha256 = payload.get("checkpoint_sha256")
    unhashed = dict(payload)
    unhashed.pop("checkpoint_sha256", None)
    if (
        not isinstance(expected_checkpoint_sha256, str)
        or _json_sha256(unhashed) != expected_checkpoint_sha256
    ):
        return None
    outputs: list[Path] = []
    for item in payload["outputs"]:
        if not isinstance(item, dict):
            return None
        output_path = item.get("path")
        output_sha256 = item.get("sha256")
        if not isinstance(output_path, str) or not isinstance(output_sha256, str):
            return None
        resolved = Path(output_path).expanduser().resolve()
        try:
            content = resolved.read_bytes()
        except OSError:
            return None
        if _sha256_bytes(content) != output_sha256:
            return None
        outputs.append(resolved)
    return tuple(outputs)


def write_identity_stage_checkpoint(
    root: Path,
    *,
    stage: str,
    input_fingerprint: str,
    outputs: Sequence[Path],
) -> Path:
    destination = root.expanduser().resolve() / f"{stage}.json"
    output_payload = []
    for output in outputs:
        resolved = output.expanduser().resolve()
        content = resolved.read_bytes()
        output_payload.append(
            {
                "path": str(resolved),
                "size": len(content),
                "sha256": _sha256_bytes(content),
            }
        )
    payload = {
        "cache_version": IDENTITY_STAGE_CACHE_VERSION,
        "stage": stage,
        "input_fingerprint": input_fingerprint,
        "outputs": output_payload,
    }
    payload["checkpoint_sha256"] = _json_sha256(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)
    return destination
