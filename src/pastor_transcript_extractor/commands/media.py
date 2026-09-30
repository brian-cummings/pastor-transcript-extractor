from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from pastor_transcript_extractor.commands.apps import media_app
from pastor_transcript_extractor.commands.common import get_database
from pastor_transcript_extractor.config import build_paths, build_tool_config
from pastor_transcript_extractor.media_artifacts import (
    ArchivedMediaUnavailableError,
    MediaVerificationCache,
    audit_media_coverage,
    backfill_existing_media_artifacts,
    ensure_audio_for_video,
    get_verified_normalized_media_artifact,
    video_has_isolated_sermon,
)


console = Console()


@media_app.command(
    "backfill",
    help="Register existing audio as reconstructed immutable media artifacts without moving files.",
)
def media_backfill(
    video_id: int | None = typer.Option(None, help="Only migrate one database video id."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    result = backfill_existing_media_artifacts(
        database,
        build_paths(base_dir),
        video_id=video_id,
    )
    console.print(
        f"Examined {result.videos_examined} video(s); registered "
        f"{result.artifacts_registered} media artifact(s) and "
        f"{result.attempts_registered} acquisition result(s); "
        f"missing historical paths={result.missing_paths}."
    )


@media_app.command(
    "ensure-audio",
    help="Ensure isolated sermons have verified audio without running local ASR.",
)
def media_ensure_audio(
    video_id: int | None = typer.Option(None, help="Only process one database video id."),
    all_eligible: bool = typer.Option(
        False,
        "--all-eligible",
        help="Process unresolved videos with a valid isolated sermon window.",
    ),
    limit: int | None = typer.Option(None, min=1, help="Maximum eligible videos to process."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if (video_id is None) == (not all_eligible):
        raise typer.BadParameter("Pass exactly one of --video-id or --all-eligible.")
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    tools = build_tool_config()
    if video_id is not None:
        videos = [database.get_video_by_id(video_id)]
        if videos[0] is None:
            raise typer.BadParameter(f"Unknown video id: {video_id}")
    else:
        videos = []
        inventory = database.list_videos()
        verification_cache_root = paths.evaluation / "speaker-pairs/cache"
        verification_cache = MediaVerificationCache(
            verification_cache_root,
            fallback_roots=(
                verification_cache_root / "media-verification",
            ),
        )
        existing = 0
        console.print(
            "Audio ensure inventory: scanning "
            f"{len(inventory)} video(s) for isolated sermons missing "
            "verified normalized audio."
        )
        for inventory_index, video in enumerate(inventory, start=1):
            if (
                inventory_index == 1
                or inventory_index == len(inventory)
                or inventory_index % 25 == 0
            ):
                console.print(
                    "Audio ensure inventory: "
                    f"video={inventory_index}/{len(inventory)} "
                    f"queued={len(videos)} existing={existing}"
                )
            if not video_has_isolated_sermon(database, video.id)[0]:
                continue
            try:
                verified = get_verified_normalized_media_artifact(
                    database,
                    video.id,
                    verification_cache=verification_cache,
                )
            except ArchivedMediaUnavailableError:
                existing += 1
                continue
            if verified is not None:
                existing += 1
                continue
            videos.append(video)
        if limit is not None:
            videos = videos[:limit]
        console.print(
            "Audio ensure inventory complete: "
            f"queued={len(videos)} existing={existing}."
        )
    counts = {"verified": 0, "unavailable": 0, "failed": 0, "skipped": 0}
    downloaded = 0
    for index, video in enumerate(videos, start=1):
        console.print(
            f"Audio ensure [{index}/{len(videos)}] "
            f"{video.youtube_video_id}: starting"
        )
        result = ensure_audio_for_video(
            database,
            paths,
            tools,
            video_id=video.id,
            event_callback=lambda message, index=index, video=video: (
                console.print(
                    f"Audio ensure [{index}/{len(videos)}] "
                    f"{video.youtube_video_id}: {message}",
                    markup=False,
                )
            ),
        )
        counts[result.outcome] += 1
        downloaded += int(result.downloaded)
        console.print(
            f"[{index}/{len(videos)}] {video.youtube_video_id}: "
            f"{result.outcome} ({result.reason_code})"
        )
    console.print(
        "Audio ensure complete: "
        f"verified={counts['verified']} (downloaded={downloaded}), "
        f"unavailable={counts['unavailable']}, failed={counts['failed']}, "
        f"skipped={counts['skipped']}."
    )


@media_app.command(
    "audit",
    help="Report isolated-sermon audio coverage without downloading or modifying media.",
)
def media_audit(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    report = audit_media_coverage(database)
    console.print(
        f"Isolated sermons={report.isolated_sermons}; verified={len(report.verified)}; "
        f"unavailable={len(report.unavailable)}; failed={len(report.failed)}; "
        f"corrupt={len(report.corrupt)}; missing={len(report.missing)}."
    )
    for label, values in (
        ("unavailable", report.unavailable),
        ("failed", report.failed),
        ("corrupt", report.corrupt),
        ("missing", report.missing),
    ):
        if values:
            console.print(f"{label}: {', '.join(values)}")
