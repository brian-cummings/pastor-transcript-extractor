from __future__ import annotations

from pathlib import Path

import typer

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.profile_analysis import resolve_profile_sermon_scope
from pastor_transcript_extractor.storage import Database


def get_database(base_dir: Path | None = None) -> Database:
    paths = build_paths(base_dir, remember=True)
    ensure_directories(paths)
    database = Database(paths.database)
    database.initialize()
    return database


def _unknown_pastor_error(pastor_slug: str) -> typer.BadParameter:
    resolved_root = build_paths().root
    return typer.BadParameter(
        f"Unknown pastor slug: {pastor_slug} (app root: {resolved_root})"
    )


def _analysis_videos(
    database: Database,
    *,
    video_id: int | None,
    youtube_video_id: str | None,
    profile_id: int | None,
    pastor_slug: str | None,
) -> tuple[list, int | None]:
    if sum(
        value is not None
        for value in (video_id, youtube_video_id, profile_id, pastor_slug)
    ) != 1:
        raise typer.BadParameter(
            "Choose exactly one scope: --video-id, --youtube-video-id, "
            "--profile-id, or --pastor."
        )
    if video_id is not None:
        video = database.get_video_by_id(video_id)
        if video is None:
            raise typer.BadParameter(f"Unknown database video id: {video_id}")
        return [video], None
    if youtube_video_id is not None:
        video = database.get_video_by_youtube_id(youtube_video_id)
        if video is None:
            raise typer.BadParameter(f"Unknown YouTube video ID: {youtube_video_id}")
        return [video], None

    if pastor_slug is not None:
        pastor = database.get_pastor_by_slug(pastor_slug)
        if pastor is None:
            raise _unknown_pastor_error(pastor_slug)
        profile_id = database.get_pastor_speaker_profile_id(pastor.id)
        if profile_id is None:
            raise typer.BadParameter(
                f"Pastor {pastor_slug} is not bound to a speaker profile. "
                "Use --profile-id after identity review establishes one."
            )

    assert profile_id is not None
    try:
        scope = resolve_profile_sermon_scope(database, profile_id)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    return list(scope.videos), scope.profile_id
