from __future__ import annotations

import json
from pathlib import Path
import shlex

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from pastor_transcript_extractor.commands.apps import media_app
from pastor_transcript_extractor.commands.common import get_database
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.media_archive import (
    ArchivePreflightEvent,
    ArchiveProgressEvent,
    AudioSweepProgressEvent,
    CanonicalAudioPreparationProgressEvent,
    archive_normalized_media,
    archive_source_media,
    archive_status,
    prepare_canonical_audio,
    sweep_local_audio,
)


console = Console()


def _format_sync_bytes(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"


@media_app.command(
    "archive-sources",
    help="Archive comparison-independent source audio and replace local files with verified symlinks.",
)
def media_archive_sources(
    archive_root: Path | None = typer.Option(
        None,
        "--archive-root",
        help="NAS archive root. Supplying it records and activates the destination for later retries.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Record eligible entries and show destinations without copying or replacing files.",
    ),
    limit: int | None = typer.Option(None, min=1, help="Maximum eligible source artifacts to process."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        with Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("Verifying normalized-audio eligibility", total=None)

            def report_archive_preflight(event: ArchivePreflightEvent) -> None:
                progress.console.print(
                    f"Preflight {event.check}: {event.status} — {event.detail}",
                    markup=False,
                )
                if event.check == "eligibility" and event.status == "running":
                    progress.update(task_id, description="Verifying normalized-audio eligibility")

            def update_archive_progress(event: ArchiveProgressEvent) -> None:
                if event.stage == "complete":
                    detail = f" ({event.detail})" if event.detail else ""
                    progress.console.print(
                        f"[{event.index}/{event.total}] media artifact #{event.media_artifact_id}: "
                        f"{event.outcome} -> {event.archive_path}{detail}",
                        markup=False,
                    )
                    progress.update(
                        task_id,
                        total=event.total,
                        completed=event.index,
                        description=f"Archived source audio ({event.index}/{event.total})",
                    )
                    return
                progress.update(
                    task_id,
                    total=event.total,
                    completed=event.index - 1,
                    description=(
                        f"[{event.index}/{event.total}] {event.source_path.name}: {event.stage}"
                    ),
                )

            result = archive_source_media(
                database,
                build_paths(base_dir),
                archive_root=archive_root,
                dry_run=dry_run,
                limit=limit,
                progress_callback=update_archive_progress,
                preflight_callback=report_archive_preflight,
            )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    counts = result.counts
    console.print(
        f"Archive root={result.destination.archive_root}; eligible={result.eligible}; "
        f"archived={counts['archived']}; already_archived={counts['already_archived']}; "
        f"unavailable={counts['destination_unavailable']}; failed={counts['failed']}; "
        f"would_archive={counts['would_archive']}."
    )


@media_app.command(
    "prepare-canonical-audio",
    help="Prepare current canonical speaker clips without running comparisons.",
)
def media_prepare_canonical_audio(
    dry_run: bool = typer.Option(False, "--dry-run"),
    limit: int | None = typer.Option(None, min=1),
    youtube_video_id: str | None = typer.Option(None, "--youtube-video-id"),
    all_eligible: bool = typer.Option(False, "--all-eligible"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if (youtube_video_id is None) == (not all_eligible):
        raise typer.BadParameter(
            "Pass exactly one of --youtube-video-id or --all-eligible."
        )
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    video_ids = None
    if youtube_video_id is not None:
        video = database.get_video_by_youtube_id(youtube_video_id)
        if video is None:
            raise typer.BadParameter(f"Unknown YouTube video ID: {youtube_video_id}")
        video_ids = {video.id}

    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Scanning canonical audio", total=None)

        def report(event: CanonicalAudioPreparationProgressEvent) -> None:
            if event.stage == "complete":
                progress.console.print(
                    f"[{event.index}/{event.total}] {event.youtube_video_id}: "
                    f"{event.outcome} — {event.detail}",
                    markup=False,
                )
                progress.update(
                    task_id,
                    total=event.total,
                    completed=event.index,
                    description=(
                        f"Canonical audio ({event.index}/{event.total})"
                    ),
                )
                return
            progress.update(
                task_id,
                total=event.total,
                completed=event.index - 1,
                description=(
                    f"[{event.index}/{event.total}] "
                    f"{event.youtube_video_id}: {event.stage}"
                ),
            )

        try:
            result = prepare_canonical_audio(
                database,
                paths,
                cache_root=paths.evaluation / "speaker-pairs/cache",
                video_ids=video_ids,
                all_eligible=all_eligible,
                dry_run=dry_run,
                limit=limit,
                wait_for_lock=True,
                progress_callback=report,
            )
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error

    deferred = next(
        (item for item in result.items if item.outcome == "deferred"),
        None,
    )
    if youtube_video_id is not None and deferred is not None:
        retry = (
            "pte media prepare-canonical-audio "
            f"--youtube-video-id {youtube_video_id} "
            f"--base-dir {shlex.quote(str(paths.root))}"
        )
        raise typer.BadParameter(
            f"archived_media_unavailable for {youtube_video_id}. Retry: {retry}"
        )
    counts = result.counts
    console.print(
        "Canonical audio preparation: "
        f"prepared={counts['prepared']} "
        f"would_prepare={counts['would_prepare']} "
        f"already_prepared={counts['already_prepared']} "
        f"deferred={counts['deferred']} blocked={counts['blocked']} "
        f"failed={counts['failed']}."
    )


@media_app.command(
    "archive-normalized",
    help="Archive eligible normalized audio after canonical speaker inputs are prepared.",
)
def media_archive_normalized(
    archive_root: Path | None = typer.Option(None, "--archive-root"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    limit: int | None = typer.Option(None, min=1),
    youtube_video_id: str | None = typer.Option(None, "--youtube-video-id"),
    all_eligible: bool = typer.Option(False, "--all-eligible"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if (youtube_video_id is None) == (not all_eligible):
        raise typer.BadParameter(
            "Pass exactly one of --youtube-video-id or --all-eligible."
        )
    database = get_database(base_dir)
    video_ids = None
    if youtube_video_id is not None:
        video = database.get_video_by_youtube_id(youtube_video_id)
        if video is None:
            raise typer.BadParameter(f"Unknown YouTube video ID: {youtube_video_id}")
        video_ids = {video.id}
    try:
        with Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task(
                "Evaluating normalized-audio eligibility", total=None
            )

            def report_preflight(event: ArchivePreflightEvent) -> None:
                progress.console.print(
                    f"Preflight {event.check}: {event.status} — {event.detail}",
                    markup=False,
                )

            def report_progress(event: ArchiveProgressEvent) -> None:
                if event.stage == "complete":
                    detail = f" ({event.detail})" if event.detail else ""
                    progress.console.print(
                        f"[{event.index}/{event.total}] normalized artifact "
                        f"#{event.media_artifact_id}: {event.outcome} -> "
                        f"{event.archive_path}{detail}",
                        markup=False,
                    )
                    progress.update(
                        task_id,
                        total=event.total,
                        completed=event.index,
                        description=(
                            f"Normalized archive ({event.index}/{event.total})"
                        ),
                    )
                    return
                progress.update(
                    task_id,
                    total=event.total,
                    completed=event.index - 1,
                    description=(
                        f"[{event.index}/{event.total}] "
                        f"{event.source_path.name}: {event.stage}"
                    ),
                )

            result = archive_normalized_media(
                database,
                build_paths(base_dir),
                archive_root=archive_root,
                dry_run=dry_run,
                limit=limit,
                video_ids=video_ids,
                all_eligible=all_eligible,
                progress_callback=report_progress,
                preflight_callback=report_preflight,
            )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    for item in result.eligibility:
        state = "eligible" if item.eligible else "blocked"
        console.print(
            f"{item.youtube_video_id}: {state}; {item.reason}; "
            f"clip_preparation={item.clip_preparation_status}"
        )
    counts = result.counts
    console.print(
        f"Normalized archive root={result.destination.archive_root}; eligible={result.eligible}; "
        f"archived={counts['archived']}; already_archived={counts['already_archived']}; "
        f"unavailable={counts['destination_unavailable']}; failed={counts['failed']}; "
        f"would_archive={counts['would_archive']}."
    )


@media_app.command(
    "archive-status",
    help="Report source and normalized archive state and normalized eligibility.",
)
def media_archive_status(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    report = archive_status(database, build_paths(base_dir))
    if report.destination is None:
        console.print("No media archive destination is configured.")
        return
    counts = report.counts
    source_counts = {
        status: sum(entry.status == status for entry in report.source_entries)
        for status in ("pending", "archived", "failed")
    }
    normalized_counts = {
        status: sum(entry.status == status for entry in report.normalized_entries)
        for status in ("pending", "archived", "failed")
    }
    eligible = sum(item.eligible for item in report.normalized_eligibility)
    stale = sum(
        item.clip_preparation_status == "stale"
        for item in report.normalized_eligibility
    )
    blocked = sum(
        item.clip_preparation_status == "missing"
        for item in report.normalized_eligibility
    )
    console.print(
        f"Archive root={report.destination.archive_root}; "
        f"accessible={report.destination_accessible}; entries={len(report.entries)}; "
        f"archived={counts['archived']}; pending={counts['pending']}; failed={counts['failed']}."
    )
    console.print(
        f"Source audio: entries={len(report.source_entries)}; archived={source_counts['archived']}; "
        f"pending={source_counts['pending']}; failed={source_counts['failed']}."
    )
    console.print(
        f"Normalized audio: entries={len(report.normalized_entries)}; "
        f"archived={normalized_counts['archived']}; pending={normalized_counts['pending']}; "
        f"failed={normalized_counts['failed']}; unavailable="
        f"{normalized_counts['archived'] if not report.destination_accessible else 0}; "
        f"eligible={eligible}; stale_clip_preparation={stale}; "
        f"blocked_clip_fingerprint_generation={blocked}."
    )


@media_app.command(
    "sweep-audio",
    help=(
        "Audit physical local audio and optionally replace byte-identical archived "
        "duplicates with symlinks. Dry-run is the default."
    ),
)
def media_sweep_audio(
    apply: bool = typer.Option(
        False,
        "--apply",
        help=(
            "Replace only byte-identical, checksum-verified archived duplicates "
            "with symlinks. Unmatched files are never removed."
        ),
    ),
    report: Path | None = typer.Option(
        None,
        "--report",
        help="Write the complete machine-readable audit as JSON.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Print every retained file in addition to reclaimable files.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    last_stage: tuple[Path, str] | None = None

    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Inventorying physical local audio", total=None)

        def report_progress(event: AudioSweepProgressEvent) -> None:
            nonlocal last_stage
            current = (event.path, event.stage)
            if current == last_stage:
                return
            last_stage = current
            progress.update(
                task_id,
                total=event.total,
                completed=event.index - 1,
                description=(
                    f"[{event.index}/{event.total}] {event.path.name}: {event.stage}"
                ),
            )

        try:
            result = sweep_local_audio(
                database,
                paths,
                apply=apply,
                progress_callback=report_progress,
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise typer.BadParameter(str(error)) from error
        progress.update(
            task_id,
            completed=len(result.items),
            total=len(result.items),
            description="Local audio sweep complete",
        )

    for item in result.items:
        if not verbose and item.outcome not in {
            "would_link_to_archive",
            "linked_to_archive",
            "retained_link_failed",
        }:
            continue
        destination = f" -> {item.archive_path}" if item.archive_path else ""
        console.print(
            f"{item.outcome}: {_format_sync_bytes(item.byte_size)} "
            f"{item.path}{destination} ({item.detail})",
            markup=False,
        )

    summary = Table(title="Local audio sweep")
    summary.add_column("Outcome")
    summary.add_column("Files", justify="right")
    summary.add_column("Bytes", justify="right")
    for outcome, count in sorted(result.counts.items()):
        summary.add_row(
            outcome,
            str(count),
            _format_sync_bytes(result.bytes_by_outcome[outcome]),
        )
    console.print(summary)
    action = "reclaimed" if apply else "reclaimable"
    console.print(
        f"Sweep mode={'apply' if apply else 'dry-run'}; {action}="
        f"{_format_sync_bytes(result.reclaimable_bytes)}. "
        "Registered unarchived and failed items remain for the normal archive commands."
    )

    if report is not None:
        report_path = report.expanduser().resolve(strict=False)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "mode": "apply" if apply else "dry-run",
            "reclaimable_bytes": result.reclaimable_bytes,
            "counts": result.counts,
            "bytes_by_outcome": result.bytes_by_outcome,
            "items": [
                {
                    "path": str(item.path),
                    "byte_size": item.byte_size,
                    "category": item.category,
                    "outcome": item.outcome,
                    "detail": item.detail,
                    "media_artifact_id": item.media_artifact_id,
                    "archive_path": (
                        str(item.archive_path) if item.archive_path else None
                    ),
                }
                for item in result.items
            ],
        }
        report_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        console.print(f"Report written: {report_path}", markup=False)
