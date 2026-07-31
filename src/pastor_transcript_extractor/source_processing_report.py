from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUSES = ("discovered", "transcribing", "extracted", "exported", "failed")


SOURCE_REPORT_QUERY = """
WITH
attempt_facts AS (
    SELECT
        video_id,
        1 AS attempted,
        MAX(outcome = 'verified') AS verified,
        MAX(outcome = 'unavailable') AS unavailable,
        MAX(outcome = 'failed') AS failed
    FROM media_acquisition_attempts
    GROUP BY video_id
),
artifact_facts AS (
    SELECT
        video_id,
        MAX(artifact_kind = 'source_audio') AS has_source_audio,
        MAX(artifact_kind = 'normalized_audio') AS has_normalized_audio
    FROM media_artifacts
    GROUP BY video_id
),
transcript_facts AS (
    SELECT
        video_id,
        1 AS has_transcript,
        MAX(source_kind = 'captions') AS has_captions,
        MAX(source_kind = 'local_asr') AS has_local_asr
    FROM transcript_artifacts
    GROUP BY video_id
),
processing_events AS (
    SELECT video_id, created_at AS event_at FROM media_acquisition_attempts
    UNION ALL SELECT video_id, created_at FROM media_artifacts
    UNION ALL SELECT video_id, created_at FROM transcript_artifacts
    UNION ALL SELECT video_id, created_at FROM metadata_artifacts
    UNION ALL SELECT video_id, created_at FROM extraction_results
    UNION ALL SELECT video_id, reviewed_at FROM review_results
    UNION ALL
    SELECT ma.video_id, mae.created_at
    FROM media_archive_entries mae JOIN media_artifacts ma ON ma.id = mae.media_artifact_id
    UNION ALL
    SELECT ma.video_id, mae.updated_at
    FROM media_archive_entries mae JOIN media_artifacts ma ON ma.id = mae.media_artifact_id
    UNION ALL
    SELECT ma.video_id, mae.archived_at
    FROM media_archive_entries mae JOIN media_artifacts ma ON ma.id = mae.media_artifact_id
    WHERE mae.archived_at IS NOT NULL
    UNION ALL
    SELECT ma.video_id, maa.attempted_at
    FROM media_archive_attempts maa
    JOIN media_archive_entries mae ON mae.id = maa.archive_entry_id
    JOIN media_artifacts ma ON ma.id = mae.media_artifact_id
),
latest_processing AS (
    SELECT video_id, MAX(event_at) AS latest_at
    FROM processing_events
    GROUP BY video_id
),
video_facts AS (
    SELECT
        v.id,
        v.source_id,
        v.status,
        COALESCE(af.attempted, 0) AS attempted,
        COALESCE(af.verified, 0) AS verified,
        COALESCE(af.unavailable, 0) AS unavailable,
        COALESCE(af.failed, 0) AS media_failed,
        COALESCE(tf.has_transcript, 0) AS has_transcript,
        COALESCE(tf.has_captions, 0) AS has_captions,
        COALESCE(tf.has_local_asr, 0) AS has_local_asr,
        CASE WHEN COALESCE(af.verified, 0) = 1
                  AND COALESCE(mf.has_source_audio, 0) = 1 THEN 1 ELSE 0 END
            AS verified_source_audio,
        CASE WHEN COALESCE(af.verified, 0) = 1
                  AND COALESCE(mf.has_normalized_audio, 0) = 1 THEN 1 ELSE 0 END
            AS verified_normalized_audio,
        lp.latest_at
    FROM videos v
    LEFT JOIN attempt_facts af ON af.video_id = v.id
    LEFT JOIN artifact_facts mf ON mf.video_id = v.id
    LEFT JOIN transcript_facts tf ON tf.video_id = v.id
    LEFT JOIN latest_processing lp ON lp.video_id = v.id
)
SELECT
    s.id AS source_id,
    s.url AS source_url,
    COALESCE(
        o.display_name,
        (SELECT MIN(v.channel_name) FROM videos v
         WHERE v.source_id = s.id AND NULLIF(TRIM(v.channel_name), '') IS NOT NULL),
        ''
    ) AS organization_source_name,
    COALESCE(p.display_name, '') AS assigned_pastor,
    CASE WHEN psb.profile_id IS NOT NULL THEN 1 ELSE 0 END AS has_speaker_profile,
    COUNT(vf.id) AS total_cataloged_videos,
    COALESCE(SUM(vf.status = 'discovered'), 0) AS status_discovered,
    COALESCE(SUM(vf.status = 'transcribing'), 0) AS status_transcribing,
    COALESCE(SUM(vf.status = 'extracted'), 0) AS status_extracted,
    COALESCE(SUM(vf.status = 'exported'), 0) AS status_exported,
    COALESCE(SUM(vf.status = 'failed'), 0) AS status_failed,
    COALESCE(SUM(vf.attempted), 0) AS videos_with_media_attempt,
    COALESCE(SUM(vf.attempted = 0), 0) AS videos_without_media_attempt,
    COALESCE(SUM(vf.verified), 0) AS media_outcome_verified,
    COALESCE(SUM(vf.unavailable), 0) AS media_outcome_unavailable,
    COALESCE(SUM(vf.media_failed), 0) AS media_outcome_failed,
    COALESCE(SUM(vf.verified_source_audio), 0) AS videos_with_verified_source_audio,
    COALESCE(SUM(vf.verified_normalized_audio), 0) AS videos_with_verified_normalized_audio,
    COALESCE(SUM(vf.has_transcript), 0) AS videos_with_transcript_artifacts,
    COALESCE(SUM(vf.has_captions), 0) AS videos_with_caption_transcript_artifacts,
    COALESCE(SUM(vf.has_local_asr), 0) AS videos_with_local_asr_transcript_artifacts,
    COALESCE(SUM(vf.status IN ('extracted', 'exported') AND vf.attempted = 0), 0)
        AS successful_without_media_attempt,
    COALESCE(SUM(vf.verified = 1 AND vf.status NOT IN ('extracted', 'exported')), 0)
        AS verified_audio_not_successful,
    MAX(vf.latest_at) AS latest_processing_timestamp,
    COALESCE(SUM(vf.status IN ('discovered', 'transcribing') AND vf.attempted = 0), 0)
        AS cataloged_without_processing,
    COALESCE(SUM(vf.status = 'failed' AND vf.attempted = 0), 0)
        AS failed_without_media_attempt
FROM sources s
LEFT JOIN organizations o ON o.id = s.organization_id
LEFT JOIN pastors p ON p.id = s.pastor_id
LEFT JOIN pastor_speaker_bindings psb ON psb.pastor_id = s.pastor_id
LEFT JOIN video_facts vf ON vf.source_id = s.id
GROUP BY s.id
ORDER BY
    has_speaker_profile ASC,
    videos_without_media_attempt DESC,
    total_cataloged_videos DESC,
    s.id ASC
"""


def generate_source_processing_report(
    database_path: Path,
    *,
    markdown_path: Path,
    json_path: Path,
) -> dict[str, Any]:
    database_path = database_path.expanduser().resolve()
    markdown_path = markdown_path.expanduser().resolve()
    json_path = json_path.expanduser().resolve()
    if markdown_path == json_path:
        raise ValueError("Markdown and JSON output paths must be different")
    if database_path in {markdown_path, json_path}:
        raise ValueError("report output path must not overwrite the application database")
    if not database_path.is_file():
        raise ValueError(f"application database does not exist: {database_path}")

    uri = f"{database_path.as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, timeout=30.0, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("BEGIN")
        source_rows = [dict(row) for row in connection.execute(SOURCE_REPORT_QUERY)]
        for row in source_rows:
            row["has_speaker_profile"] = bool(row["has_speaker_profile"])
            flags: list[str] = []
            if row["successful_without_media_attempt"]:
                flags.append("SUCCESS_WITHOUT_MEDIA_ATTEMPT")
            if row["verified_audio_not_successful"]:
                flags.append("MEDIA_VERIFIED_BUT_NOT_EXTRACTED")
            if row.pop("cataloged_without_processing"):
                flags.append("CATALOGED_WITHOUT_PROCESSING")
            if row.pop("failed_without_media_attempt"):
                flags.append("FAILED_WITHOUT_MEDIA_ATTEMPT")
            if not row["has_speaker_profile"]:
                flags.append("PROFILE_UNAVAILABLE")
            if row["total_cataloged_videos"] == 0:
                flags.append("ZERO_VIDEOS")
            row["flags"] = flags

        summary = _build_summary(source_rows)
        source_count = int(connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
        video_count = int(connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0])
        if summary["total_sources"] != source_count:
            raise RuntimeError("source report did not reconcile with the source table")
        if summary["total_cataloged_videos"] != video_count:
            raise RuntimeError("source report did not reconcile with the video table")
    finally:
        connection.close()

    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "report": "source_processing_report",
        "generated_at": generated_at,
        "database": str(database_path),
        "summary": summary,
        "sources": source_rows,
    }
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def _build_summary(source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total_sources": len(source_rows),
        "total_cataloged_videos": sum(row["total_cataloged_videos"] for row in source_rows),
        "videos_by_status": {
            status: sum(row[f"status_{status}"] for row in source_rows) for status in STATUSES
        },
        "videos_with_media_attempt": sum(row["videos_with_media_attempt"] for row in source_rows),
        "videos_without_media_attempt": sum(
            row["videos_without_media_attempt"] for row in source_rows
        ),
        "media_outcomes": {
            outcome: sum(row[f"media_outcome_{outcome}"] for row in source_rows)
            for outcome in ("verified", "unavailable", "failed")
        },
        "successful_without_media_attempt": sum(
            row["successful_without_media_attempt"] for row in source_rows
        ),
        "videos_with_verified_audio": sum(row["media_outcome_verified"] for row in source_rows),
        "sources_without_speaker_profile": sum(
            not row["has_speaker_profile"] for row in source_rows
        ),
    }
    if (
        summary["videos_with_media_attempt"] + summary["videos_without_media_attempt"]
        != summary["total_cataloged_videos"]
    ):
        raise RuntimeError("media-attempt totals do not reconcile")
    if sum(summary["videos_by_status"].values()) != summary["total_cataloged_videos"]:
        raise RuntimeError("video-status totals do not reconcile")
    return summary


def _render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    rows = payload["sources"]
    lines = [
        "# Source Processing Report",
        "",
        f"Generated: `{payload['generated_at']}`  ",
        f"Database (opened read-only): `{payload['database']}`",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Total sources | {summary['total_sources']} |",
        f"| Total cataloged videos | {summary['total_cataloged_videos']} |",
    ]
    for status in STATUSES:
        lines.append(f"| Videos — {status} | {summary['videos_by_status'][status]} |")
    lines.extend(
        [
            f"| Videos with media-acquisition attempts | {summary['videos_with_media_attempt']} |",
            f"| Videos without media-acquisition attempts | {summary['videos_without_media_attempt']} |",
            f"| Videos with verified media outcome | {summary['media_outcomes']['verified']} |",
            f"| Videos with unavailable media outcome | {summary['media_outcomes']['unavailable']} |",
            f"| Videos with failed media outcome | {summary['media_outcomes']['failed']} |",
            f"| Extracted/exported videos without media attempts | {summary['successful_without_media_attempt']} |",
            f"| Videos with verified audio | {summary['videos_with_verified_audio']} |",
            f"| Sources without an associated speaker profile | {summary['sources_without_speaker_profile']} |",
            "",
            "## Sources",
            "",
        ]
    )
    columns = [
        ("ID", "source_id"), ("URL", "source_url"),
        ("Organization / source", "organization_source_name"), ("Pastor", "assigned_pastor"),
        ("Profile?", "has_speaker_profile"), ("Total", "total_cataloged_videos"),
        ("Disc.", "status_discovered"), ("Transcr.", "status_transcribing"),
        ("Extr.", "status_extracted"), ("Exprt.", "status_exported"), ("Failed", "status_failed"),
        ("Attempted", "videos_with_media_attempt"), ("No attempt", "videos_without_media_attempt"),
        ("Verified", "media_outcome_verified"), ("Unavailable", "media_outcome_unavailable"),
        ("Media failed", "media_outcome_failed"),
        ("Verified source", "videos_with_verified_source_audio"),
        ("Verified normalized", "videos_with_verified_normalized_audio"),
        ("Transcript", "videos_with_transcript_artifacts"),
        ("Captions", "videos_with_caption_transcript_artifacts"),
        ("Local ASR", "videos_with_local_asr_transcript_artifacts"),
        ("Success/no attempt", "successful_without_media_attempt"),
        ("Verified/not success", "verified_audio_not_successful"),
        ("Latest processing", "latest_processing_timestamp"), ("Flags", "flags"),
    ]
    lines.append("| " + " | ".join(label for label, _ in columns) + " |")
    text_fields = {"source_url", "organization_source_name", "assigned_pastor", "latest_processing_timestamp", "flags"}
    lines.append("|" + "|".join("---" if key in text_fields else "---:" for _, key in columns) + "|")
    for row in rows:
        rendered: list[str] = []
        for _, key in columns:
            value = row[key]
            if key == "source_url":
                value = f"[{value}]({value})"
            elif key == "has_speaker_profile":
                value = "yes" if value else "no"
            elif key == "flags":
                value = ", ".join(value)
            elif value in (None, ""):
                value = "—"
            rendered.append(str(value).replace("|", "\\|"))
        lines.append("| " + " | ".join(rendered) + " |")
    lines.extend(
        [
            "",
            "## Definitions and counting notes",
            "",
            "- All totals count distinct videos via one `video_facts` row per `videos.id`; sources are left-joined so zero-video sources remain.",
            "- Media attempted means at least one `media_acquisition_attempts` row. Outcome counts are distinct videos with at least one attempt of that outcome and are not mutually exclusive.",
            "- Verified audio means at least one `verified` attempt. Verified source/normalized audio additionally requires the corresponding `media_artifacts.artifact_kind` row for that video.",
            "- Transcript counts use `transcript_artifacts`; caption and local-ASR counts use `source_kind = 'captions'` and `'local_asr'`.",
            "- Successful means video status `extracted` or `exported`; no audio or attempt state is inferred from video status or transcription failure.",
            "- `CATALOGED_WITHOUT_PROCESSING` means at least one `discovered` or `transcribing` video has no media attempt. Other flags directly correspond to their named per-source condition.",
            "- Latest processing is the latest timestamp found for a source's videos in media attempts/artifacts, transcript/metadata artifacts, extraction results, reviews, or media archive entries/attempts.",
            "- Organization/source name prefers the linked organization name, then a cataloged video's channel name, otherwise it is blank.",
            "- Sort order is: profile unavailable first, videos without media attempts descending, cataloged videos descending, source ID ascending as a stable tie-breaker.",
            "",
        ]
    )
    return "\n".join(lines)
