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
    PRIVATE_EVIDENCE_PATTERNS,
    generated_relative_path,
    private_evidence_relative_path,
    private_evidence_destination,
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
    compatibility_link: bool = False
    sha256: str | None = None


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
            "schema_version": 2,
            "repo_root": self.repo_root,
            "evaluation_root": self.evaluation_root,
            "summary": {
                "planned_files": self.planned_files,
                "total_bytes": self.total_bytes,
                "already_migrated": self.already_migrated,
                "conflicts": len(self.conflicts),
                "symlink_rejections": len(self.symlink_rejections),
                "database_changes": len(self.database_changes),
                "compatibility_links": sum(e.compatibility_link for e in self.entries),
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
    if source.is_symlink():
        yield source
        return
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


def _private_evidence_files(repo_root: Path) -> Iterable[Path]:
    # Never walk runtime caches or arbitrary application data. These are the
    # two bounded repository trees that historically held review artifacts.
    for root in (repo_root / "evaluation", repo_root / "docs/review-proposals",
                 repo_root / "docs/analytical-review"):
        for path in _iter_category_files(root):
            if private_evidence_relative_path(path, repo_root=repo_root) is not None:
                yield path


def audit_database_paths(
    database_path: Path,
    *,
    repo_root: Path,
    evaluation_root: Path,
) -> tuple[dict[str, object], ...]:
    if not database_path.exists():
        return ()
    changes: list[dict[str, object]] = []
    connection = sqlite3.connect(
        f"{database_path.expanduser().resolve().as_uri()}?mode=ro",
        uri=True,
    )
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
    if _inside(evaluation_root, repo_root) or _inside(legacy_root, evaluation_root):
        raise MigrationError(
            "configured evaluation root and repository evaluation root must not overlap"
        )
    entries: list[MigrationEntry] = []
    conflicts: list[str] = []
    rejected: list[str] = []
    candidates: dict[Path, tuple[str, Path, bool]] = {}
    for prefix in GENERATED_EVALUATION_PREFIXES:
        for source in _iter_category_files(legacy_root / Path(prefix)):
            candidates[source] = (prefix.as_posix(), evaluation_root / source.relative_to(legacy_root), False)
    for source in _private_evidence_files(repo_root):
        relative = source.relative_to(repo_root)
        if source not in candidates:
            candidates[source] = (
                "private-review-evidence",
                private_evidence_destination(relative, evaluation_root=evaluation_root),
                True,
            )
    # Recover interrupted moves (bytes moved but link not yet installed). Also
    # expose files newly written directly into application data to old readers.
    archived_candidates: set[Path] = set()
    for pattern in PRIVATE_EVIDENCE_PATTERNS:
        if pattern.startswith("evaluation/"):
            root = evaluation_root
            pattern = pattern.removeprefix("evaluation/")
        else:
            root = evaluation_root / "review-packets"
        if pattern.endswith("/**"):
            pattern += "/*"
        archived_candidates.update(root.glob(pattern))
    for destination in sorted(archived_candidates):
        if destination.is_symlink() or not destination.is_file():
            continue
        relative = destination.relative_to(evaluation_root)
        if relative.parts[:1] == ("review-packets",):
            original = Path(*relative.parts[1:])
        else:
            original = Path("evaluation") / relative
        if private_evidence_relative_path(original, repo_root=repo_root) is None:
            continue
        source = repo_root / original
        if not source.exists() and not source.is_symlink():
            candidates.setdefault(source, ("private-review-evidence", destination, True))
    for source, (category, destination, compatibility_link) in sorted(candidates.items()):
        # Only exact links created by this policy may survive a rerun.
        # Never follow arbitrary source symlinks or symlinked ancestors.
        parents = source.relative_to(repo_root).parents
        unsafe_parent = any((repo_root / parent).is_symlink() for parent in parents)
        if source.is_symlink():
            if (compatibility_link and not unsafe_parent
                    and source.readlink() == destination and destination.is_file()
                    and not destination.is_symlink() and _inside(destination, evaluation_root)):
                entries.append(MigrationEntry(category, str(source), str(destination),
                                              destination.stat().st_size, "compatibility_link", True,
                                              _sha256(destination)))
            else:
                rejected.append(str(source))
            continue
        if unsafe_parent or not _inside(source, repo_root):
            rejected.append(str(source))
            continue
        if not _inside(destination, evaluation_root):
            rejected.append(str(destination))
            continue
        if not source.exists():
            entries.append(MigrationEntry(category, str(source), str(destination),
                                          destination.stat().st_size, "restore_compatibility_link",
                                          True, _sha256(destination)))
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
            MigrationEntry(category, str(source), str(destination), byte_size, status,
                           compatibility_link, _sha256(source))
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


def write_manifest(plan: MigrationPlan, path: Path, *, result: MigrationResult | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    payload = plan.to_dict()
    if result is not None:
        payload["result"] = asdict(result)
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    lines = ["# Evaluation storage migration", "", "```json", json.dumps(payload["summary"], indent=2),
             "```", "", "Evidence bytes and fingerprints are preserved. Compatibility links are local, ignored pointers.",
             "Git history is unchanged; tracked files still require removal from the index before publishing.", "",
             "| Action | Source | Destination |", "| --- | --- | --- |"]
    for entry in plan.entries:
        lines.append(f"| {entry.status} | {entry.source} | {entry.destination} |")
    if result is not None:
        lines += ["", "## Apply result", "", "```json", json.dumps(asdict(result), indent=2), "```"]
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
            repository = Path(plan.repo_root)
            if (not source.is_relative_to(repository)
                    or any(p.is_symlink() for p in source.parents if p != repository and p.is_relative_to(repository))
                    or not _inside(destination, Path(plan.evaluation_root))
                    or destination.is_symlink()):
                raise MigrationError("path changed or became unsafe after planning")
            if entry.status == "compatibility_link":
                if not source.is_symlink() or source.readlink() != destination:
                    raise MigrationError("compatibility link changed after planning")
                if entry.sha256 and _sha256(destination) != entry.sha256:
                    raise MigrationError("linked evidence changed after planning")
                continue
            if entry.status == "restore_compatibility_link":
                if entry.sha256 and _sha256(destination) != entry.sha256:
                    raise MigrationError("archived evidence changed after planning")
                source.parent.mkdir(parents=True, exist_ok=True)
                source.symlink_to(destination)
                continue
            if source.is_symlink():
                raise MigrationError("source became a symlink after planning")
            if entry.sha256 and source.exists() and _sha256(source) != entry.sha256:
                raise MigrationError("source bytes changed after planning")
            if entry.status == "already_migrated":
                if source.exists() and _same_file(source, destination):
                    source.unlink()
                    if entry.compatibility_link:
                        source.symlink_to(destination)
                else:
                    raise MigrationError("previously identical destination changed after planning")
                continue
            if entry.status != "planned" or not source.exists():
                continue
            if destination.exists():
                if _same_file(source, destination):
                    source.unlink()
                    if entry.compatibility_link:
                        source.symlink_to(destination)
                    continue
                raise MigrationError(f"destination collision after planning: {destination}")
            _move_one(source, destination, copy_file=copy_file, force_copy=force_copy)
            if verify and (not destination.exists() or destination.stat().st_size != entry.byte_size
                           or (entry.sha256 and _sha256(destination) != entry.sha256)):
                raise MigrationError(f"post-move verification failed: {destination}")
            if entry.compatibility_link:
                source.symlink_to(destination)
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
