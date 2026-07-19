from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Callable

from pastor_transcript_extractor.config import AppPaths
from pastor_transcript_extractor.media_artifacts import (
    get_archive_safe_normalized_media_artifact,
    verify_media_artifact,
)
from pastor_transcript_extractor.models import (
    MediaArchiveDestination,
    MediaArchiveEntry,
    MediaArtifact,
)
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class ArchiveItemResult:
    media_artifact_id: int
    source_path: Path
    archive_path: Path
    outcome: str
    detail: str | None


@dataclass(frozen=True, slots=True)
class ArchiveProgressEvent:
    index: int
    total: int
    media_artifact_id: int
    source_path: Path
    archive_path: Path
    stage: str
    outcome: str | None = None
    detail: str | None = None


ArchiveProgressCallback = Callable[[ArchiveProgressEvent], None]


@dataclass(frozen=True, slots=True)
class ArchivePreflightEvent:
    check: str
    status: str
    detail: str


ArchivePreflightCallback = Callable[[ArchivePreflightEvent], None]


@dataclass(frozen=True, slots=True)
class ArchiveRunResult:
    destination: MediaArchiveDestination
    eligible: int
    items: tuple[ArchiveItemResult, ...]

    @property
    def counts(self) -> dict[str, int]:
        counts = {
            "archived": 0,
            "already_archived": 0,
            "destination_unavailable": 0,
            "failed": 0,
            "would_archive": 0,
        }
        for item in self.items:
            counts[item.outcome] += 1
        return counts


@dataclass(frozen=True, slots=True)
class ArchiveStatusReport:
    destination: MediaArchiveDestination | None
    destination_accessible: bool
    entries: tuple[MediaArchiveEntry, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {
            status: sum(entry.status == status for entry in self.entries)
            for status in ("pending", "archived", "failed")
        }


def configure_archive_destination(
    database: Database, archive_root: Path
) -> MediaArchiveDestination:
    root = archive_root.expanduser().resolve(strict=False)
    return database.configure_media_archive_destination(str(root))


def archive_source_media(
    database: Database,
    app_paths: AppPaths,
    *,
    archive_root: Path | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    video_ids: set[int] | None = None,
    wait_for_lock: bool = False,
    lock_retry_seconds: float = 1.0,
    progress_callback: ArchiveProgressCallback | None = None,
    preflight_callback: ArchivePreflightCallback | None = None,
) -> ArchiveRunResult:
    with _archive_lock(
        app_paths.root,
        wait_for_lock=wait_for_lock,
        retry_seconds=lock_retry_seconds,
        preflight_callback=preflight_callback,
    ):
        _notify_preflight(preflight_callback, "archive lock", "passed", "exclusive lock acquired")
        return _archive_source_media_locked(
            database,
            app_paths,
            archive_root=archive_root,
            dry_run=dry_run,
            limit=limit,
            video_ids=video_ids,
            progress_callback=progress_callback,
            preflight_callback=preflight_callback,
        )


def _archive_source_media_locked(
    database: Database,
    app_paths: AppPaths,
    *,
    archive_root: Path | None,
    dry_run: bool,
    limit: int | None,
    video_ids: set[int] | None,
    progress_callback: ArchiveProgressCallback | None,
    preflight_callback: ArchivePreflightCallback | None,
) -> ArchiveRunResult:
    destination = (
        configure_archive_destination(database, archive_root)
        if archive_root is not None
        else database.get_active_media_archive_destination()
    )
    if destination is None:
        raise ValueError("No media archive destination is configured")

    root = Path(destination.archive_root)
    _notify_preflight(preflight_callback, "destination", "configured", str(root))
    destination_available, unavailable_detail, available_bytes = _check_destination(
        root, preflight_callback
    )
    existing_entries = database.list_media_archive_entries()
    state_counts = {
        status: sum(entry.status == status for entry in existing_entries)
        for status in ("pending", "archived", "failed")
    }
    _notify_preflight(
        preflight_callback,
        "persisted state",
        "ready",
        ", ".join(f"{key}={value}" for key, value in state_counts.items()),
    )
    _notify_preflight(
        preflight_callback,
        "eligibility",
        "running",
        "verifying normalized audio; normalized files are never archive candidates",
    )
    candidates = _eligible_source_artifacts(database, video_ids=video_ids)
    if limit is not None:
        candidates = candidates[:limit]
    entries = [
        database.upsert_media_archive_entry(
            media_artifact_id=artifact.id,
            destination_id=destination.id,
            source_path=artifact.artifact_path,
            archive_path=str(_archive_path(app_paths, root, artifact)),
            content_sha256=artifact.content_sha256,
            byte_size=artifact.byte_size,
        )
        for artifact in candidates
    ]

    eligible_bytes = sum(artifact.byte_size for artifact in candidates)
    _notify_preflight(
        preflight_callback,
        "eligibility",
        "passed",
        f"{len(candidates)} source artifacts / {_format_bytes(eligible_bytes)}; normalized selected=0",
    )
    partial_count = 0
    staging_count = 0
    required_bytes = 0
    for artifact, entry in zip(candidates, entries):
        archive_path = Path(entry.archive_path)
        partial_path = archive_path.with_name(
            f".{archive_path.name}.pte-partial-{artifact.id}"
        )
        staging_path = Path(entry.source_path).with_name(
            f".{Path(entry.source_path).name}.pte-archive-staging-{artifact.id}"
        )
        if destination_available and partial_path.exists():
            partial_count += 1
        if staging_path.exists() or staging_path.is_symlink():
            staging_count += 1
        if not destination_available or not archive_path.exists():
            required_bytes += artifact.byte_size
    _notify_preflight(
        preflight_callback,
        "recovery markers",
        "passed" if staging_count == 0 else "warning",
        f"partial={partial_count}, local_staging={staging_count}",
    )
    if available_bytes is not None:
        space_ok = available_bytes >= required_bytes
        _notify_preflight(
            preflight_callback,
            "capacity",
            "passed" if space_ok else "failed",
            f"available={_format_bytes(available_bytes)}, required={_format_bytes(required_bytes)}",
        )
        if not space_ok:
            destination_available = False
            unavailable_detail = (
                f"archive destination has insufficient free space: "
                f"available={available_bytes}, required={required_bytes}"
            )

    if not destination_available:
        detail = unavailable_detail or f"archive destination is unavailable: {root}"
        items = []
        for index, (artifact, entry) in enumerate(zip(candidates, entries), start=1):
            database.add_media_archive_attempt(
                archive_entry_id=entry.id,
                outcome="destination_unavailable",
                detail=detail,
            )
            _notify(
                progress_callback,
                index=index,
                total=len(candidates),
                artifact=artifact,
                entry=entry,
                stage="complete",
                outcome="destination_unavailable",
                detail=detail,
            )
            items.append(_item(artifact, entry, "destination_unavailable", detail))
        return ArchiveRunResult(destination, len(candidates), tuple(items))

    items: list[ArchiveItemResult] = []
    for index, (artifact, entry) in enumerate(zip(candidates, entries), start=1):
        if dry_run:
            _notify(
                progress_callback,
                index=index,
                total=len(candidates),
                artifact=artifact,
                entry=entry,
                stage="complete",
                outcome="would_archive",
            )
            items.append(_item(artifact, entry, "would_archive", None))
            continue
        notify_stage = lambda stage: _notify(
            progress_callback,
            index=index,
            total=len(candidates),
            artifact=artifact,
            entry=entry,
            stage=stage,
        )
        outcome, detail = _archive_one(artifact, entry, notify_stage)
        database.add_media_archive_attempt(
            archive_entry_id=entry.id,
            outcome=outcome,
            detail=detail,
        )
        if outcome in {"archived", "already_archived"}:
            database.update_media_archive_entry_status(entry.id, "archived")
        elif outcome == "failed":
            database.update_media_archive_entry_status(entry.id, "failed")
        _notify(
            progress_callback,
            index=index,
            total=len(candidates),
            artifact=artifact,
            entry=entry,
            stage="complete",
            outcome=outcome,
            detail=detail,
        )
        items.append(_item(artifact, entry, outcome, detail))
    return ArchiveRunResult(destination, len(candidates), tuple(items))


def archive_status(database: Database) -> ArchiveStatusReport:
    destination = database.get_active_media_archive_destination()
    accessible = destination is not None and Path(destination.archive_root).is_dir()
    return ArchiveStatusReport(
        destination=destination,
        destination_accessible=accessible,
        entries=tuple(database.list_media_archive_entries()),
    )


def _eligible_source_artifacts(
    database: Database, *, video_ids: set[int] | None = None
) -> list[MediaArtifact]:
    candidates: list[MediaArtifact] = []
    for video in database.list_videos():
        if video_ids is not None and video.id not in video_ids:
            continue
        if get_archive_safe_normalized_media_artifact(database, video.id) is None:
            continue
        candidates.extend(
            artifact
            for artifact in database.list_media_artifacts_for_video(video.id)
            if artifact.artifact_kind == "source_audio"
        )
    return sorted(candidates, key=lambda artifact: artifact.id)


def _archive_path(app_paths: AppPaths, root: Path, artifact: MediaArtifact) -> Path:
    source = Path(artifact.artifact_path)
    try:
        relative = source.relative_to(app_paths.root)
    except ValueError:
        relative = Path("external") / artifact.content_sha256[:16] / source.name
    return root / relative


def _archive_one(
    artifact: MediaArtifact,
    entry: MediaArchiveEntry,
    stage_callback: Callable[[str], None] | None = None,
) -> tuple[str, str | None]:
    source = Path(entry.source_path)
    destination = Path(entry.archive_path)
    try:
        if _source_points_to_archive(source, destination):
            _stage(stage_callback, "verifying existing archive")
            if _matches(destination, artifact):
                return "already_archived", None
            return "failed", "archived target is missing or does not match its recorded checksum"

        if destination.exists():
            _stage(stage_callback, "verifying existing archive")
            if not _matches(destination, artifact):
                return "failed", f"archive path collision: {destination}"
        else:
            _stage(stage_callback, "verifying local source")
            if not verify_media_artifact(artifact):
                return "failed", f"source media is missing or corrupt: {source}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_name(f".{destination.name}.pte-partial-{artifact.id}")
            if partial.exists() or partial.is_symlink():
                partial.unlink()
            try:
                _stage(stage_callback, "copying to NAS")
                shutil.copy2(source, partial)
                _stage(stage_callback, "verifying NAS checksum")
                if not _matches(partial, artifact):
                    raise RuntimeError("copied archive checksum does not match source artifact")
                os.replace(partial, destination)
            finally:
                if partial.exists() or partial.is_symlink():
                    partial.unlink()
        _stage(stage_callback, "linking archived source")
        _replace_source_with_symlink(source, destination, artifact)
        return "archived", None
    except OSError as error:
        return "failed", f"{type(error).__name__}: {error}"
    except RuntimeError as error:
        return "failed", str(error)


def _replace_source_with_symlink(
    source: Path, destination: Path, artifact: MediaArtifact
) -> None:
    if source.is_symlink():
        raise RuntimeError(f"refusing to replace unrelated symlink: {source}")
    backup = source.with_name(f".{source.name}.pte-archive-staging-{artifact.id}")
    if backup.exists() or backup.is_symlink():
        raise RuntimeError(f"archive staging path already exists: {backup}")
    if source.exists():
        source.rename(backup)
    try:
        source.symlink_to(destination)
        if (
            source.resolve(strict=False) != destination.resolve(strict=False)
            or not source.exists()
            or source.stat().st_size != artifact.byte_size
        ):
            raise RuntimeError("archive symlink failed post-write verification")
    except (OSError, RuntimeError):
        if source.exists() or source.is_symlink():
            source.unlink()
        if backup.exists():
            backup.rename(source)
        raise
    if backup.exists():
        backup.unlink()


def _source_points_to_archive(source: Path, destination: Path) -> bool:
    return source.is_symlink() and source.resolve(strict=False) == destination.resolve(strict=False)


def _matches(path: Path, artifact: MediaArtifact) -> bool:
    return (
        path.exists()
        and path.stat().st_size == artifact.byte_size
        and _sha256_file(path) == artifact.content_sha256
    )


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _item(
    artifact: MediaArtifact,
    entry: MediaArchiveEntry,
    outcome: str,
    detail: str | None,
) -> ArchiveItemResult:
    return ArchiveItemResult(
        media_artifact_id=artifact.id,
        source_path=Path(entry.source_path),
        archive_path=Path(entry.archive_path),
        outcome=outcome,
        detail=detail,
    )


def _stage(callback: Callable[[str], None] | None, stage: str) -> None:
    if callback is not None:
        callback(stage)


def _notify(
    callback: ArchiveProgressCallback | None,
    *,
    index: int,
    total: int,
    artifact: MediaArtifact,
    entry: MediaArchiveEntry,
    stage: str,
    outcome: str | None = None,
    detail: str | None = None,
) -> None:
    if callback is None:
        return
    callback(
        ArchiveProgressEvent(
            index=index,
            total=total,
            media_artifact_id=artifact.id,
            source_path=Path(entry.source_path),
            archive_path=Path(entry.archive_path),
            stage=stage,
            outcome=outcome,
            detail=detail,
        )
    )


def _check_destination(
    root: Path, callback: ArchivePreflightCallback | None
) -> tuple[bool, str | None, int | None]:
    if not root.is_dir():
        detail = f"archive destination is unavailable: {root}"
        _notify_preflight(callback, "mount", "failed", detail)
        return False, detail, None
    _notify_preflight(callback, "mount", "passed", "archive directory is accessible")

    probe_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".pte-write-probe-",
            dir=root,
            delete=False,
        ) as probe:
            probe_path = Path(probe.name)
            probe.write(b"pte archive write probe\n")
            probe.flush()
            os.fsync(probe.fileno())
        probe_path.unlink()
        probe_path = None
    except OSError as error:
        if probe_path is not None and probe_path.exists():
            try:
                probe_path.unlink()
            except OSError:
                pass
        detail = f"archive destination write probe failed: {type(error).__name__}: {error}"
        _notify_preflight(callback, "write probe", "failed", detail)
        return False, detail, None
    _notify_preflight(callback, "write probe", "passed", "create, fsync, and delete succeeded")

    try:
        available_bytes = shutil.disk_usage(root).free
    except OSError as error:
        detail = f"free-space check failed: {type(error).__name__}: {error}"
        _notify_preflight(callback, "capacity", "warning", detail)
        return True, None, None
    return True, None, available_bytes


@contextmanager
def _archive_lock(
    app_root: Path,
    *,
    wait_for_lock: bool = False,
    retry_seconds: float = 1.0,
    preflight_callback: ArchivePreflightCallback | None = None,
):
    if retry_seconds <= 0:
        raise ValueError("archive lock retry interval must be positive")
    lock_path = app_root / ".media-archive.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        waiting_reported = False
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if not wait_for_lock:
                    raise ValueError(
                        f"Another media archive process holds the lock: {lock_path}"
                    ) from error
                if not waiting_reported:
                    _notify_preflight(
                        preflight_callback,
                        "archive lock",
                        "waiting",
                        f"another archive process holds {lock_path}; retrying",
                    )
                    waiting_reported = True
                time.sleep(retry_seconds)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _notify_preflight(
    callback: ArchivePreflightCallback | None,
    check: str,
    status: str,
    detail: str,
) -> None:
    if callback is not None:
        callback(ArchivePreflightEvent(check=check, status=status, detail=detail))


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024.0 or unit == "TiB":
            return f"{amount:.2f} {unit}"
        amount /= 1024.0
    raise AssertionError("unreachable")
