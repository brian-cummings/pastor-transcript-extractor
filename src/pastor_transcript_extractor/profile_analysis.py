from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json

from pastor_transcript_extractor.models import SpeakerProfileAnalysisRun, Video
from pastor_transcript_extractor.sermon_analysis import (
    ANALYZER_KEY as SERMON_ANALYZER_KEY,
    ANALYZER_VERSION as SERMON_ANALYZER_VERSION,
    OLD_TESTAMENT_BOOKS,
)
from pastor_transcript_extractor.storage import Database


PROFILE_ANALYZER_KEY = "profile-scripture-usage"
PROFILE_ANALYZER_VERSION = "1"
PROFILE_ANALYSIS_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ProfileSermonScope:
    requested_profile_id: int
    profile_id: int
    observation_ids: tuple[int, ...]
    videos: tuple[Video, ...]


@dataclass(frozen=True, slots=True)
class ProfileAnalysisOutcome:
    run: SpeakerProfileAnalysisRun
    created: bool


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def resolve_profile_sermon_scope(
    database: Database, profile_id: int
) -> ProfileSermonScope:
    if database.get_speaker_profile(profile_id) is None:
        raise ValueError(f"Unknown speaker profile: {profile_id}")
    resolved_profile_id = database.resolve_speaker_profile_id(profile_id)
    observation_ids = tuple(
        database.list_effective_observation_ids_for_profile(resolved_profile_id)
    )
    observations = [
        observation
        for observation_id in observation_ids
        if (observation := database.get_speaker_observation(observation_id)) is not None
    ]
    video_ids = {observation.video_id for observation in observations}
    videos = tuple(
        video for video in database.list_videos() if video.id in video_ids
    )
    if not videos:
        raise ValueError(
            f"Speaker profile {resolved_profile_id} has no effectively attached sermon observations."
        )
    return ProfileSermonScope(
        requested_profile_id=profile_id,
        profile_id=resolved_profile_id,
        observation_ids=observation_ids,
        videos=videos,
    )


def _decoded_measurements(database: Database, run_id: int) -> dict[str, object]:
    return {
        measurement.metric_key: json.loads(measurement.value_json)
        for measurement in database.list_sermon_analysis_measurements(run_id)
    }


def build_profile_scripture_analysis(
    database: Database,
    profile_id: int,
    *,
    analyzer_version: str = PROFILE_ANALYZER_VERSION,
    sermon_analyzer_version: str = SERMON_ANALYZER_VERSION,
) -> ProfileAnalysisOutcome:
    if not analyzer_version.strip():
        raise ValueError("Profile analyzer version must not be blank")
    scope = resolve_profile_sermon_scope(database, profile_id)

    observations = [
        database.get_speaker_observation(observation_id)
        for observation_id in scope.observation_ids
    ]
    membership_payload = [
        {
            "extraction_result_id": observation.extraction_result_id,
            "observation_id": observation.id,
            "video_id": observation.video_id,
        }
        for observation in observations
        if observation is not None
    ]
    membership_fingerprint = _sha256(membership_payload)

    sermon_inputs = []
    analyzed_videos: list[Video] = []
    total_words = 0
    explicit_mentions = 0
    book_counts: Counter[str] = Counter()
    chapter_mentions: Counter[str] = Counter()
    chapter_videos: dict[str, set[int]] = defaultdict(set)
    testament_counts: Counter[str] = Counter()
    quarter_counts: Counter[str] = Counter()
    located_references = 0
    zero_reference_sermons = 0

    for video in scope.videos:
        run = database.get_latest_sermon_analysis_run(
            video.id,
            SERMON_ANALYZER_KEY,
            analyzer_version=sermon_analyzer_version,
        )
        if run is None:
            continue
        sermon_inputs.append((run.id, video.id))
        analyzed_videos.append(video)
        values = _decoded_measurements(database, run.id)
        word_count = values.get("word_count")
        if isinstance(word_count, int) and not isinstance(word_count, bool):
            total_words += word_count
        reference_count = values.get("scripture_reference_mentions")
        if isinstance(reference_count, int) and not isinstance(reference_count, bool):
            if reference_count == 0:
                zero_reference_sermons += 1

        sermon_start = values.get("sermon_start_seconds")
        sermon_duration = values.get("sermon_duration_seconds")
        for evidence in database.list_sermon_analysis_evidence(run.id):
            payload = json.loads(evidence.payload_json)
            if payload.get("detection_class") != "explicit":
                continue
            book = payload.get("book")
            chapter = payload.get("chapter")
            if not isinstance(book, str) or not isinstance(chapter, int):
                continue
            explicit_mentions += 1
            book_counts[book] += 1
            testament_counts["old" if book in OLD_TESTAMENT_BOOKS else "new"] += 1
            chapter_key = f"{book} {chapter}"
            chapter_mentions[chapter_key] += 1
            chapter_videos[chapter_key].add(video.id)

            if (
                isinstance(sermon_start, (int, float))
                and not isinstance(sermon_start, bool)
                and isinstance(sermon_duration, (int, float))
                and not isinstance(sermon_duration, bool)
                and sermon_duration > 0
                and evidence.start_seconds is not None
            ):
                position = (evidence.start_seconds - float(sermon_start)) / float(
                    sermon_duration
                )
                quarter = min(4, max(1, int(position * 4) + 1))
                quarter_counts[f"Q{quarter}"] += 1
                located_references += 1

    sermons_attached = len(scope.videos)
    sermons_analyzed = len(analyzed_videos)
    sermons_missing = sermons_attached - sermons_analyzed
    dated = sorted(
        video.published_at.date().isoformat()
        for video in analyzed_videos
        if video.published_at is not None
    )
    old_count = testament_counts["old"]
    new_count = testament_counts["new"]
    top_books = [
        {"book": book, "mentions": count}
        for book, count in sorted(
            book_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    repeated_chapters = [
        {
            "passage": passage,
            "sermon_count": len(chapter_videos[passage]),
            "mentions": chapter_mentions[passage],
        }
        for passage in sorted(
            (
                passage
                for passage, video_ids in chapter_videos.items()
                if len(video_ids) >= 2
            ),
            key=lambda passage: (
                -len(chapter_videos[passage]),
                -chapter_mentions[passage],
                passage,
            ),
        )
    ]
    placement = {
        quarter: {
            "mentions": quarter_counts[quarter],
            "percent": (
                round(100 * quarter_counts[quarter] / located_references, 2)
                if located_references
                else 0.0
            ),
        }
        for quarter in ("Q1", "Q2", "Q3", "Q4")
    }
    detection_diagnostics = {
        "detection_scope": "explicit_numeric_reference",
        "accepted_match_confidence": "high",
        "contextual_reference_detection": "not_implemented",
        "sermons_with_zero_explicit_references": zero_reference_sermons,
        "sermons_with_explicit_references": sermons_analyzed - zero_reference_sermons,
        "references_with_placement": located_references,
        "references_without_placement": explicit_mentions - located_references,
        "placement_precision": "source_segment_start",
    }

    values: list[tuple[str, object, str | None]] = [
        ("sermons_attached", sermons_attached, "sermons"),
        ("sermons_analyzed", sermons_analyzed, "sermons"),
        ("sermons_missing_analysis", sermons_missing, "sermons"),
        ("total_sermon_words", total_words, "words"),
        ("date_range_start", dated[0] if dated else None, None),
        ("date_range_end", dated[-1] if dated else None, None),
        ("explicit_reference_mentions", explicit_mentions, "mentions"),
        (
            "explicit_references_per_1000_words",
            round(explicit_mentions * 1000 / total_words, 4) if total_words else 0.0,
            "mentions_per_1000_words",
        ),
        ("old_testament_mentions", old_count, "mentions"),
        ("new_testament_mentions", new_count, "mentions"),
        (
            "old_testament_percent",
            round(100 * old_count / explicit_mentions, 2) if explicit_mentions else 0.0,
            "percent",
        ),
        (
            "new_testament_percent",
            round(100 * new_count / explicit_mentions, 2) if explicit_mentions else 0.0,
            "percent",
        ),
        ("top_scripture_books", top_books, None),
        ("repeated_scripture_chapters", repeated_chapters, None),
        ("reference_placement_by_quarter", placement, None),
        ("reference_detection_diagnostics", detection_diagnostics, None),
    ]
    measurements = [
        (key, json.dumps(value, sort_keys=True), unit) for key, value, unit in values
    ]

    input_fingerprint = _sha256(
        {
            "analyzer_key": PROFILE_ANALYZER_KEY,
            "analyzer_version": analyzer_version,
            "membership_fingerprint": membership_fingerprint,
            "profile_id": scope.profile_id,
            "schema_version": PROFILE_ANALYSIS_SCHEMA_VERSION,
            "sermon_analysis_run_ids": sorted(run_id for run_id, _ in sermon_inputs),
        }
    )
    run, created = database.add_speaker_profile_analysis_run(
        profile_id=scope.profile_id,
        analyzer_key=PROFILE_ANALYZER_KEY,
        analyzer_version=analyzer_version,
        membership_fingerprint=membership_fingerprint,
        input_fingerprint=input_fingerprint,
        inputs=sermon_inputs,
        measurements=measurements,
    )
    return ProfileAnalysisOutcome(run=run, created=created)
