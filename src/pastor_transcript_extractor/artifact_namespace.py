from __future__ import annotations

from pathlib import Path, PurePosixPath

from pastor_transcript_extractor.config import (
    AppPaths,
    TranscriptArtifactPaths,
    VideoArtifactPaths,
    build_transcript_artifact_paths_at_root,
    build_video_artifact_paths_at_root,
)
from pastor_transcript_extractor.models import Video
from pastor_transcript_extractor.storage import Database


def resolve_video_artifact_paths(
    database: Database,
    app_paths: AppPaths,
    video: Video,
) -> VideoArtifactPaths:
    root = resolve_video_artifact_root(database, app_paths, video)
    return build_video_artifact_paths_at_root(root)


def resolve_transcript_artifact_paths(
    database: Database,
    app_paths: AppPaths,
    video: Video,
) -> TranscriptArtifactPaths:
    root = resolve_video_artifact_root(database, app_paths, video)
    return build_transcript_artifact_paths_at_root(root)


def resolve_video_artifact_root(
    database: Database,
    app_paths: AppPaths,
    video: Video,
) -> Path:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT relative_root
            FROM video_artifact_namespaces
            WHERE video_id = ?
            """,
            (video.id,),
        ).fetchone()
        if row is None:
            database._ensure_video_artifact_namespace(
                connection,
                video_id=video.id,
                pastor_id=video.pastor_id,
                youtube_video_id=video.youtube_video_id,
            )
            row = connection.execute(
                """
                SELECT relative_root
                FROM video_artifact_namespaces
                WHERE video_id = ?
                """,
                (video.id,),
            ).fetchone()
    if row is None:
        raise RuntimeError(f"Video {video.id} has no artifact namespace")
    relative = PurePosixPath(str(row["relative_root"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Video {video.id} has an unsafe artifact namespace")
    return app_paths.root.joinpath(*relative.parts)
