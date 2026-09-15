from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping, Sequence


IDENTITY_STAGE_CACHE_VERSION = "identity_stage_cache_v1"
ASSOCIATION_INPUT_STATE_VERSION = "association_input_state_v1"

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

ASSOCIATION_GLOBAL_TABLES = (
    "pastors",
    "media_archive_destinations",
    "speaker_profiles",
    "pastor_speaker_bindings",
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

ASSOCIATION_RECORDING_TABLES = (
    "extraction_results",
    "review_results",
    "metadata_artifacts",
    "media_artifacts",
    "identity_evidence",
    "identity_assessments",
    "speaker_observations",
    "speaker_name_claims",
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


def _database_snapshot(
    database_path: Path,
    *,
    tables: Sequence[str] = IDENTITY_INPUT_TABLES,
) -> list[dict[str, Any]]:
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
        for table in tables:
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


def _table_content(
    connection: sqlite3.Connection,
    table: str,
) -> tuple[list[str], list[list[Any]]]:
    cursor = connection.execute(f'SELECT * FROM "{table}" ORDER BY id')
    return (
        [str(item[0]) for item in cursor.description or ()],
        [
            [_json_value(value) for value in row]
            for row in cursor.fetchall()
        ],
    )


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


def build_association_input_state(
    database_path: Path,
    *,
    parameters: Mapping[str, Any],
    global_input_paths: Iterable[Path] = (),
) -> dict[str, Any]:
    """Build state that permits only provably local association refreshes."""
    database_path = database_path.expanduser().resolve()
    global_fingerprint = _json_sha256(
        {
            "version": ASSOCIATION_INPUT_STATE_VERSION,
            "parameters": dict(parameters),
            "database": _database_snapshot(
                database_path,
                tables=ASSOCIATION_GLOBAL_TABLES,
            ),
            "files": _file_snapshot(global_input_paths),
        }
    )
    uri = f"file:{database_path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        recordings: dict[str, dict[str, Any]] = {}
        source_columns, source_rows = _table_content(connection, "sources")
        source_id_index = source_columns.index("id")
        sources_by_id = {row[source_id_index]: row for row in source_rows}
        video_columns, video_rows = _table_content(connection, "videos")
        video_id_index = video_columns.index("id")
        video_source_index = video_columns.index("source_id")
        youtube_id_index = video_columns.index("youtube_video_id")

        table_columns: dict[str, list[str]] = {}
        rows_by_table_and_video: dict[str, dict[Any, list[list[Any]]]] = {}
        for table in ASSOCIATION_RECORDING_TABLES:
            columns, rows = _table_content(connection, table)
            table_columns[table] = columns
            video_index = columns.index("video_id")
            grouped: dict[Any, list[list[Any]]] = {}
            for row in rows:
                grouped.setdefault(row[video_index], []).append(row)
            rows_by_table_and_video[table] = grouped

        archive_cursor = connection.execute(
            "SELECT media.video_id AS grouping_video_id, entry.* "
            "FROM media_archive_entries entry "
            "JOIN media_artifacts media ON media.id = entry.media_artifact_id "
            "ORDER BY entry.id"
        )
        archive_columns = [
            str(item[0]) for item in archive_cursor.description or ()
        ][1:]
        archive_rows_by_video: dict[Any, list[list[Any]]] = {}
        for raw_row in archive_cursor.fetchall():
            archive_rows_by_video.setdefault(raw_row[0], []).append(
                [_json_value(value) for value in raw_row[1:]]
            )

        observation_columns = table_columns["speaker_observations"]
        observation_fingerprint_index = observation_columns.index(
            "input_fingerprint"
        )
        proposed_path_index = table_columns["extraction_results"].index(
            "proposed_json_path"
        )
        for video_row in video_rows:
            video_id = video_row[video_id_index]
            youtube_video_id = video_row[youtube_id_index]
            source_row = sources_by_id.get(video_row[video_source_index])
            tables: dict[str, Any] = {
                "sources": {
                    "columns": source_columns,
                    "rows": [source_row] if source_row is not None else [],
                },
                "videos": {"columns": video_columns, "rows": [video_row]},
            }
            for table in ASSOCIATION_RECORDING_TABLES:
                tables[table] = {
                    "columns": table_columns[table],
                    "rows": rows_by_table_and_video[table].get(video_id, []),
                }
            tables["media_archive_entries"] = {
                "columns": archive_columns,
                "rows": archive_rows_by_video.get(video_id, []),
            }
            extraction_rows = rows_by_table_and_video[
                "extraction_results"
            ].get(video_id, [])
            proposed_paths = [
                Path(row[proposed_path_index])
                for row in extraction_rows
                if row[proposed_path_index]
            ]
            observation_rows = rows_by_table_and_video[
                "speaker_observations"
            ].get(video_id, [])
            latest_observation = observation_rows[-1] if observation_rows else None
            recording_payload = {
                "tables": tables,
                "proposed_files": _file_snapshot(proposed_paths),
            }
            recordings[str(youtube_video_id)] = {
                "fingerprint": _json_sha256(recording_payload),
                "current_observation_fingerprint": (
                    str(latest_observation[observation_fingerprint_index])
                    if latest_observation
                    else None
                ),
            }

        excluded_columns, excluded_rows = _table_content(
            connection, "excluded_videos"
        )
        excluded_youtube_index = excluded_columns.index("youtube_video_id")
        for row in excluded_rows:
            youtube_video_id = str(row[excluded_youtube_index])
            recordings[f"excluded:{youtube_video_id}"] = {
                "fingerprint": _json_sha256(
                    [_json_value(value) for value in row]
                ),
                "current_observation_fingerprint": None,
            }
    finally:
        connection.close()
    return {
        "version": ASSOCIATION_INPUT_STATE_VERSION,
        "global_fingerprint": global_fingerprint,
        "recordings": recordings,
    }


def association_refresh_mode(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
) -> str:
    """Return ``incremental`` only when every change has a new observation."""
    if not isinstance(previous, Mapping) or not isinstance(current, Mapping):
        return "full"
    if (
        previous.get("version") != ASSOCIATION_INPUT_STATE_VERSION
        or current.get("version") != ASSOCIATION_INPUT_STATE_VERSION
        or previous.get("global_fingerprint") != current.get("global_fingerprint")
    ):
        return "full"
    old = previous.get("recordings")
    new = current.get("recordings")
    if not isinstance(old, Mapping) or not isinstance(new, Mapping):
        return "full"
    if not set(old).issubset(new):
        return "full"
    old_observations = {
        item.get("current_observation_fingerprint")
        for item in old.values()
        if isinstance(item, Mapping)
        and isinstance(item.get("current_observation_fingerprint"), str)
    }
    for key, current_item in new.items():
        previous_item = old.get(key)
        if previous_item == current_item:
            continue
        if previous_item is None:
            continue
        if not isinstance(previous_item, Mapping) or not isinstance(
            current_item, Mapping
        ):
            return "full"
        old_observation = previous_item.get("current_observation_fingerprint")
        new_observation = current_item.get("current_observation_fingerprint")
        if (
            not isinstance(new_observation, str)
            or new_observation == old_observation
            or new_observation in old_observations
        ):
            return "full"
    return "incremental"


def _load_verified_checkpoint(root: Path, stage: str) -> dict[str, Any] | None:
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
    for item in payload["outputs"]:
        if not isinstance(item, dict):
            return None
        output_path = item.get("path")
        output_sha256 = item.get("sha256")
        if not isinstance(output_path, str) or not isinstance(output_sha256, str):
            return None
        resolved = Path(output_path).expanduser().resolve()
        try:
            stat = resolved.stat()
        except OSError:
            return None
        recorded_size = item.get("size")
        recorded_mtime_ns = item.get("mtime_ns")
        if not (
            isinstance(recorded_size, int)
            and isinstance(recorded_mtime_ns, int)
            and stat.st_size == recorded_size
            and stat.st_mtime_ns == recorded_mtime_ns
        ):
            try:
                content = resolved.read_bytes()
            except OSError:
                return None
            if _sha256_bytes(content) != output_sha256:
                return None
    return payload


def load_identity_stage_input_state(
    root: Path,
    *,
    stage: str,
) -> Mapping[str, Any] | None:
    payload = _load_verified_checkpoint(root, stage)
    state = payload.get("input_state") if payload is not None else None
    return state if isinstance(state, Mapping) else None


def load_identity_stage_checkpoint(
    root: Path,
    *,
    stage: str,
    input_fingerprint: str,
) -> tuple[Path, ...] | None:
    payload = _load_verified_checkpoint(root, stage)
    if (
        payload is None
        or payload.get("input_fingerprint") != input_fingerprint
    ):
        return None
    outputs: list[Path] = []
    for item in payload["outputs"]:
        outputs.append(Path(item["path"]).expanduser().resolve())
    return tuple(outputs)


def write_identity_stage_checkpoint(
    root: Path,
    *,
    stage: str,
    input_fingerprint: str,
    outputs: Sequence[Path],
    input_state: Mapping[str, Any] | None = None,
) -> Path:
    destination = root.expanduser().resolve() / f"{stage}.json"
    output_payload = []
    for output in outputs:
        resolved = output.expanduser().resolve()
        content = resolved.read_bytes()
        stat = resolved.stat()
        output_payload.append(
            {
                "path": str(resolved),
                "size": len(content),
                "mtime_ns": stat.st_mtime_ns,
                "sha256": _sha256_bytes(content),
            }
        )
    payload = {
        "cache_version": IDENTITY_STAGE_CACHE_VERSION,
        "stage": stage,
        "input_fingerprint": input_fingerprint,
        "outputs": output_payload,
    }
    if input_state is not None:
        payload["input_state"] = dict(input_state)
    payload["checkpoint_sha256"] = _json_sha256(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)
    return destination
