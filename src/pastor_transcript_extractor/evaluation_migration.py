from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from typing import Callable, Iterable

from pastor_transcript_extractor.evaluation_storage import (
    GENERATED_EVALUATION_PREFIXES,
    generated_relative_path,
)


HASH_CHUNK_SIZE = 1024 * 1024
DATABASE_PATH_COLUMNS: tuple[tuple[str, str], ...] = (
    ("speaker_profile_discovery_promotions", "discovery_artifact_path"),
    ("speaker_profile_discovery_promotions", "promotion_judgment_artifact_path"),
    ("speaker_profile_candidate_confirmations", "association_artifact_path"),
    ("speaker_machine_evidence", "association_artifact_path"),
)


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MigrationEntry:
    category: str
    source: str
    destination: str
    byte_size: int
    status: str


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    repo_root: str
    evaluation_root: str
    entries: tuple[MigrationEntry, ...]
    conflicts: tuple[str, ...]
    symlink_rejections: tuple[str, ...]
    database_changes: tuple[dict[str, object], ...]

    @property
    def planned_files(self) -> int:
        return sum(entry.status == "planned" for entry in self.entries)

    @property
    def total_bytes(self) -> int:
        return sum(entry.byte_size for entry in self.entries if entry.status == "planned")

    @property
    def already_migrated(self) -> int:
        return sum(entry.status == "already_migrated" for entry in self.entries)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "repo_root": self.repo_root,
            "evaluation_root": self.evaluation_root,
            "summary": {
                "planned_files": self.planned_files,
                "total_bytes": self.total_bytes,
                "already_migrated": self.already_migrated,
                "conflicts": len(self.conflicts),
                "symlink_rejections": len(self.symlink_rejections),
                "database_changes": len(self.database_changes),
            },
            "entries": [asdict(entry) for entry in self.entries],
            "conflicts": list(self.conflicts),
            "symlink_rejections": list(self.symlink_rejections),
            "database_changes": list(self.database_changes),
        }


@dataclass(frozen=True, slots=True)
class MigrationResult:
    moved_files: int
    moved_bytes: int
    already_migrated: int
    failures: tuple[str, ...]
    remaining_legacy_files: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _same_file(source: Path, destination: Path) -> bool:
    return (
        source.stat().st_size == destination.stat().st_size
        and _sha256(source) == _sha256(destination)
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _iter_category_files(source: Path) -> Iterable[Path]:
    if not source.exists():
        return
    for directory, directory_names, file_names in os.walk(source, followlinks=False):
        current = Path(directory)
        directory_names[:] = sorted(directory_names)
        for name in sorted(file_names):
            yield current / name
        for name in tuple(directory_names):
            path = current / name
            if path.is_symlink():
                yield path
                directory_names.remove(name)


def audit_database_paths(
    database_path: Path,
    *,
    repo_root: Path,
    evaluation_root: Path,
) -> tuple[dict[str, object], ...]:
    if not database_path.exists():
        return ()
    changes: list[dict[str, object]] = []
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table, column in DATABASE_PATH_COLUMNS:
            if table not in tables:
                continue
            for rowid, value in connection.execute(
                f'SELECT rowid, "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'
            ):
                relative = generated_relative_path(str(value), repo_root=repo_root)
                if relative is None:
                    continue
                changes.append(
                    {
                        "table": table,
                        "column": column,
                        "rowid": int(rowid),
                        "old": str(value),
                        "new": relative.as_posix(),
                        "resolved_new": str(evaluation_root / relative),
                    }
                )
    finally:
        connection.close()
    return tuple(changes)


def plan_migration(
    *,
    repo_root: Path,
    evaluation_root: Path,
    database_path: Path | None = None,
) -> MigrationPlan:
    repo_root = repo_root.expanduser().resolve()
    evaluation_root = evaluation_root.expanduser().resolve()
    legacy_root = repo_root / "evaluation"
    if _inside(evaluation_root, legacy_root) or _inside(legacy_root, evaluation_root):
        raise MigrationError(
            "configured evaluation root and repository evaluation root must not overlap"
        )
    entries: list[MigrationEntry] = []
    conflicts: list[str] = []
    rejected: list[str] = []
    for prefix in GENERATED_EVALUATION_PREFIXES:
        category = prefix.as_posix()
        source_root = legacy_root / Path(category)
        destination_root = evaluation_root / Path(category)
        for source in _iter_category_files(source_root):
            if source.is_symlink() or not _inside(source, source_root):
                rejected.append(str(source))
                continue
            destination = destination_root / source.relative_to(source_root)
            if not _inside(destination, evaluation_root):
                rejected.append(str(destination))
                continue
            byte_size = source.stat().st_size
            status = "planned"
            if destination.exists():
                if destination.is_symlink() or not destination.is_file():
                    status = "conflict"
                elif _same_file(source, destination):
                    status = "already_migrated"
                else:
                    status = "conflict"
                if status == "conflict":
                    conflicts.append(f"{source} -> {destination}")
            entries.append(
                MigrationEntry(category, str(source), str(destination), byte_size, status)
            )
    database_changes = audit_database_paths(
        database_path,
        repo_root=repo_root,
        evaluation_root=evaluation_root,
    ) if database_path is not None else ()
    return MigrationPlan(
        str(repo_root),
        str(evaluation_root),
        tuple(entries),
        tuple(conflicts),
        tuple(rejected),
        database_changes,
    )


def write_manifest(plan: MigrationPlan, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def migrate_database_paths(
    database_path: Path,
    changes: Iterable[dict[str, object]],
    *,
    before_commit: Callable[[], None] | None = None,
) -> int:
    """Apply only audited table/column/row updates in one transaction."""
    allowed = set(DATABASE_PATH_COLUMNS)
    connection = sqlite3.connect(database_path)
    count = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        for change in changes:
            table = str(change["table"])
            column = str(change["column"])
            if (table, column) not in allowed:
                raise MigrationError(f"unapproved database path field: {table}.{column}")
            cursor = connection.execute(
                f'UPDATE "{table}" SET "{column}" = ? WHERE rowid = ? AND "{column}" = ?',
                (str(change["new"]), int(change["rowid"]), str(change["old"])),
            )
            if cursor.rowcount != 1:
                raise MigrationError(
                    f"database row changed since dry-run: {table}.{column} rowid={change['rowid']}"
                )
            count += 1
        if before_commit is not None:
            before_commit()
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return count


def backup_database(database_path: Path, backup_path: Path) -> bool:
    """Create one consistent pre-migration SQLite backup without overwriting it."""
    if not database_path.exists() or backup_path.exists():
        return False
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = backup_path.with_name(f".{backup_path.name}.tmp-{os.getpid()}")
    source = sqlite3.connect(database_path)
    destination = sqlite3.connect(temporary)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()
    temporary.replace(backup_path)
    return True


def _move_one(
    source: Path,
    destination: Path,
    *,
    copy_file: Callable[[Path, Path], object],
    force_copy: bool = False,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not force_copy and source.stat().st_dev == destination.parent.stat().st_dev:
        source.replace(destination)
        return
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.migrating-", dir=destination.parent
    )
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        copy_file(source, temporary)
        if not _same_file(source, temporary):
            raise MigrationError(f"copy verification failed: {source}")
        temporary.replace(destination)
        source.unlink()
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def apply_migration(
    plan: MigrationPlan,
    *,
    verify: bool = True,
    copy_file: Callable[[Path, Path], object] = shutil.copy2,
    progress: Callable[[MigrationEntry, int, int, float], None] | None = None,
    force_copy: bool = False,
) -> MigrationResult:
    if plan.conflicts or plan.symlink_rejections:
        raise MigrationError("migration plan contains conflicts or unsafe symlinks")
    moved_files = moved_bytes = 0
    failures: list[str] = []
    started = time.monotonic()
    for entry in plan.entries:
        source = Path(entry.source)
        destination = Path(entry.destination)
        try:
            if entry.status == "already_migrated":
                if source.exists() and _same_file(source, destination):
                    source.unlink()
                continue
            if entry.status != "planned" or not source.exists():
                continue
            if destination.exists():
                if _same_file(source, destination):
                    source.unlink()
                    continue
                raise MigrationError(f"destination collision after planning: {destination}")
            _move_one(source, destination, copy_file=copy_file, force_copy=force_copy)
            if verify and (not destination.exists() or destination.stat().st_size != entry.byte_size):
                raise MigrationError(f"post-move verification failed: {destination}")
            moved_files += 1
            moved_bytes += entry.byte_size
            if progress is not None:
                progress(entry, moved_files, moved_bytes, time.monotonic() - started)
        except Exception as error:
            failures.append(f"{source}: {error}")
    remaining = sum(
        1 for entry in plan.entries if Path(entry.source).exists() and not Path(entry.source).is_symlink()
    )
    return MigrationResult(
        moved_files, moved_bytes, plan.already_migrated, tuple(failures), remaining
    )
