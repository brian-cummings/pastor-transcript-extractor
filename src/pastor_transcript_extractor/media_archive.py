from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil

from pastor_transcript_extractor.config import AppPaths
from pastor_transcript_extractor.media_artifacts import (
    get_verified_normalized_media_artifact,
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
) -> ArchiveRunResult:
    destination = (
        configure_archive_destination(database, archive_root)
        if archive_root is not None
        else database.get_active_media_archive_destination()
    )
    if destination is None:
        raise ValueError("No media archive destination is configured")

    root = Path(destination.archive_root)
    candidates = _eligible_source_artifacts(database)
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

    if not root.is_dir():
        detail = f"archive destination is unavailable: {root}"
        items = []
        for artifact, entry in zip(candidates, entries):
            database.add_media_archive_attempt(
                archive_entry_id=entry.id,
                outcome="destination_unavailable",
                detail=detail,
            )
            items.append(_item(artifact, entry, "destination_unavailable", detail))
        return ArchiveRunResult(destination, len(candidates), tuple(items))

    items: list[ArchiveItemResult] = []
    for artifact, entry in zip(candidates, entries):
        if dry_run:
            items.append(_item(artifact, entry, "would_archive", None))
            continue
        outcome, detail = _archive_one(artifact, entry)
        database.add_media_archive_attempt(
            archive_entry_id=entry.id,
            outcome=outcome,
            detail=detail,
        )
        if outcome in {"archived", "already_archived"}:
            database.update_media_archive_entry_status(entry.id, "archived")
        elif outcome == "failed":
            database.update_media_archive_entry_status(entry.id, "failed")
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


def _eligible_source_artifacts(database: Database) -> list[MediaArtifact]:
    candidates: list[MediaArtifact] = []
    for video in database.list_videos():
        if get_verified_normalized_media_artifact(database, video.id) is None:
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
    artifact: MediaArtifact, entry: MediaArchiveEntry
) -> tuple[str, str | None]:
    source = Path(entry.source_path)
    destination = Path(entry.archive_path)
    try:
        if _source_points_to_archive(source, destination):
            if _matches(destination, artifact):
                return "already_archived", None
            return "failed", "archived target is missing or does not match its recorded checksum"

        if destination.exists():
            if not _matches(destination, artifact):
                return "failed", f"archive path collision: {destination}"
        else:
            if not verify_media_artifact(artifact):
                return "failed", f"source media is missing or corrupt: {source}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_name(f".{destination.name}.pte-partial-{artifact.id}")
            if partial.exists() or partial.is_symlink():
                partial.unlink()
            try:
                shutil.copy2(source, partial)
                if not _matches(partial, artifact):
                    raise RuntimeError("copied archive checksum does not match source artifact")
                os.replace(partial, destination)
            finally:
                if partial.exists() or partial.is_symlink():
                    partial.unlink()

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
