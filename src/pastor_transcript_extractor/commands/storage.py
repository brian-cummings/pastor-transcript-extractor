from __future__ import annotations

from pathlib import Path
import sqlite3

import typer
from rich.console import Console
from rich.table import Table

from pastor_transcript_extractor.commands.apps import storage_app
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.storage_maintenance import (
    StorageMaintenanceError,
    apply_storage_maintenance,
    plan_storage_maintenance,
    restore_storage_archive,
    verify_storage_archive,
    write_maintenance_manifest,
)


console = Console()


def _format_bytes(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"


def _resolve_archive_root(base_dir: Path | None, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit.expanduser().resolve()
    paths = build_paths(base_dir)
    if not paths.database.is_file():
        return None
    database = Database(paths.database, readonly=True)
    try:
        destination = database.get_active_media_archive_destination()
    except sqlite3.Error as error:
        raise StorageMaintenanceError(
            "unable to read the configured archive destination; pass --archive-root "
            f"explicitly ({error})"
        ) from error
    if destination is None:
        return None
    return Path(destination.archive_root).expanduser().resolve() / "evaluation-storage"


@storage_app.command(
    "compact",
    help="Apply explicit retention: discard old diagnostics and archive cache candidates.",
)
def compact_storage(
    apply: bool = typer.Option(False, "--apply/--dry-run", help="Apply; dry-run is default."),
    archive_root: Path | None = typer.Option(
        None,
        "--archive-root",
        help=(
            "Artifact archive root. By default, reuse the configured media archive "
            "destination beneath evaluation-storage/."
        ),
    ),
    keep_diagnostic_runs: int = typer.Option(3, min=1),
    repo_root: Path = typer.Option(Path.cwd(), "--repo-root"),
    manifest: Path | None = typer.Option(None, "--manifest"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir)
    try:
        resolved_archive_root = _resolve_archive_root(base_dir, archive_root)
    except StorageMaintenanceError as error:
        raise typer.BadParameter(str(error)) from error
    plan = plan_storage_maintenance(
        paths,
        repository_root=repo_root,
        archive_root=resolved_archive_root,
        keep_diagnostic_runs=keep_diagnostic_runs,
    )
    manifest_path = manifest or paths.evaluation / "storage-manifests/compact-plan.json"
    write_maintenance_manifest(plan, manifest_path)
    table = Table(title=f"Storage compaction {'apply' if apply else 'dry-run'}")
    table.add_column("Category")
    table.add_column("Action")
    table.add_column("Units", justify="right")
    table.add_column("Files", justify="right")
    table.add_column("Local bytes", justify="right")
    categories = sorted({unit.category for unit in plan.units})
    for category in categories:
        units = [unit for unit in plan.units if unit.category == category]
        table.add_row(
            category,
            ", ".join(sorted({unit.action.replace("_", " ") for unit in units})),
            str(len(units)),
            str(sum(len(unit.members) for unit in units)),
            _format_bytes(sum(unit.byte_size for unit in units)),
        )
    console.print(table)
    console.print(f"Archive root: {resolved_archive_root or 'not configured'}")
    console.print(f"Manifest: {manifest_path}")
    if plan.blocked:
        for item in plan.blocked:
            console.print(f"BLOCKED: {item}")
    if not apply:
        console.print("No files changed. Re-run with --apply after reviewing the manifest.")
        return
    if resolved_archive_root is None and any(
        unit.action == "archive_verify_remove_local" for unit in plan.units
    ):
        raise typer.BadParameter(
            "No archive destination is configured. Pass --archive-root or configure the media archive."
        )
    try:
        result = apply_storage_maintenance(plan, app_root=paths.root)
    except StorageMaintenanceError as error:
        raise typer.BadParameter(str(error)) from error
    write_maintenance_manifest(plan, manifest_path, result=result)
    console.print(
        f"Storage compaction complete: removed_files={result.removed_files}, "
        f"removed_bytes={_format_bytes(result.removed_bytes)}, "
        f"failures={len(result.failures)}."
    )
    for failure in result.failures:
        console.print(f"FAILED {failure.category}/{failure.unit_id}: {failure.detail}")
    if result.failures:
        raise typer.Exit(code=1)


@storage_app.command("verify", help="Verify a self-describing storage archive and every member hash.")
def verify_archive(archive: Path) -> None:
    try:
        result = verify_storage_archive(archive)
    except (OSError, StorageMaintenanceError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Verified {result.category}/{result.unit_id}: members={result.member_count}, "
        f"bytes={_format_bytes(result.byte_size)}, sha256={result.archive_sha256}."
    )


@storage_app.command("restore", help="Plan or restore every member of a verified storage archive.")
def restore_archive(
    archive: Path,
    apply: bool = typer.Option(False, "--apply/--dry-run"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir)
    try:
        result = restore_storage_archive(
            archive,
            evaluation_root=paths.evaluation,
            apply=apply,
        )
    except (OSError, StorageMaintenanceError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Restore {'applied' if apply else 'dry-run'}: restore={result.restored}, "
        f"already_present={result.already_present}, conflicts={len(result.conflicts)}."
    )
    for conflict in result.conflicts:
        console.print(f"CONFLICT: {conflict}")
    if result.conflicts:
        raise typer.Exit(code=1)
