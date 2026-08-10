from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
from itertools import combinations
import json
import math

from pastor_transcript_extractor.models import SpeakerProfileAnalysisRun, Video
from pastor_transcript_extractor.sermon_analysis import (
    ANALYZER_KEY as SERMON_ANALYZER_KEY,
    ANALYZER_VERSION as SERMON_ANALYZER_VERSION,
    OLD_TESTAMENT_BOOKS,
)
from pastor_transcript_extractor.storage import Database


PROFILE_ANALYZER_KEY = "profile-scripture-usage"
PROFILE_ANALYZER_VERSION = "2"
PROFILE_ANALYSIS_SCHEMA_VERSION = 1

CANONICAL_DIVISIONS: dict[str, tuple[str, ...]] = {
    "pentateuch": ("Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"),
    "historical": (
        "Joshua", "Judges", "Ruth", "1 Samuel", "2 Samuel", "1 Kings",
        "2 Kings", "1 Chronicles", "2 Chronicles", "Ezra", "Nehemiah", "Esther",
    ),
    "wisdom_poetry": ("Job", "Psalms", "Proverbs", "Ecclesiastes", "Song of Solomon"),
    "major_prophets": ("Isaiah", "Jeremiah", "Lamentations", "Ezekiel", "Daniel"),
    "minor_prophets": (
        "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah", "Nahum",
        "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi",
    ),
    "gospels": ("Matthew", "Mark", "Luke", "John"),
    "acts": ("Acts",),
    "pauline_epistles": (
        "Romans", "1 Corinthians", "2 Corinthians", "Galatians", "Ephesians",
        "Philippians", "Colossians", "1 Thessalonians", "2 Thessalonians",
        "1 Timothy", "2 Timothy", "Titus", "Philemon",
    ),
    "general_epistles": (
        "Hebrews", "James", "1 Peter", "2 Peter", "1 John", "2 John",
        "3 John", "Jude",
    ),
    "revelation": ("Revelation",),
}
BOOK_TO_DIVISION = {
    book: division
    for division, books in CANONICAL_DIVISIONS.items()
    for book in books
}

PROFILE_FEATURE_ORDER = (
    "analysis_coverage_fraction",
    "zero_explicit_reference_sermon_fraction",
    "explicit_references_per_1000_words",
    "book_breadth_per_10_references",
    "chapter_breadth_per_10_references",
    "book_concentration_hhi",
    "effective_book_count",
    "old_testament_share",
    "pentateuch_share",
    "historical_share",
    "wisdom_poetry_share",
    "major_prophets_share",
    "minor_prophets_share",
    "gospels_share",
    "acts_share",
    "pauline_epistles_share",
    "general_epistles_share",
    "revelation_share",
    "sustained_chapter_reference_ratio",
    "multi_verse_reference_ratio",
    "cross_sermon_anchor_coverage",
    "mean_pairwise_book_distribution_cosine",
    "reference_density_consistency",
)


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


def _rounded_ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    shared = set(left) | set(right)
    dot = sum(left[key] * right[key] for key in shared)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("Cosine similarity requires two non-empty distributions")
    return dot / (left_norm * right_norm)


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
    division_counts: Counter[str] = Counter()
    sermon_book_counts: dict[int, Counter[str]] = {}
    sermon_chapter_counts: dict[int, Counter[str]] = {}
    sermon_word_counts: dict[int, int] = {}
    sermon_run_ids: dict[int, int] = {}
    located_references = 0
    zero_reference_sermons = 0
    multi_verse_references = 0

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
        sermon_run_ids[video.id] = run.id
        sermon_book_counts[video.id] = Counter()
        sermon_chapter_counts[video.id] = Counter()
        values = _decoded_measurements(database, run.id)
        word_count = values.get("word_count")
        if isinstance(word_count, int) and not isinstance(word_count, bool):
            total_words += word_count
            sermon_word_counts[video.id] = word_count
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
            sermon_book_counts[video.id][book] += 1
            testament_counts["old" if book in OLD_TESTAMENT_BOOKS else "new"] += 1
            division = BOOK_TO_DIVISION.get(book)
            if division is not None:
                division_counts[division] += 1
            chapter_key = f"{book} {chapter}"
            chapter_mentions[chapter_key] += 1
            chapter_videos[chapter_key].add(video.id)
            sermon_chapter_counts[video.id][chapter_key] += 1
            verse_start = payload.get("verse_start")
            verse_end = payload.get("verse_end")
            if (
                isinstance(verse_start, int)
                and isinstance(verse_end, int)
                and verse_end > verse_start
            ):
                multi_verse_references += 1

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
        {
            "book": book,
            "mentions": count,
            "share": round(count / explicit_mentions, 6) if explicit_mentions else None,
        }
        for book, count in sorted(
            book_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    repeated_chapters = [
        {
            "passage": passage,
            "sermon_count": len(chapter_videos[passage]),
            "mentions": chapter_mentions[passage],
            "sermon_fraction": (
                round(len(chapter_videos[passage]) / sermons_analyzed, 6)
                if sermons_analyzed
                else None
            ),
            "video_ids": sorted(chapter_videos[passage]),
            "sermon_analysis_run_ids": sorted(
                sermon_run_ids[video_id] for video_id in chapter_videos[passage]
            ),
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

    raw_book_concentration_hhi = (
        sum((count / explicit_mentions) ** 2 for count in book_counts.values())
        if explicit_mentions
        else None
    )
    book_concentration_hhi = (
        round(raw_book_concentration_hhi, 6)
        if raw_book_concentration_hhi is not None
        else None
    )
    effective_book_count = (
        round(1 / raw_book_concentration_hhi, 6)
        if raw_book_concentration_hhi is not None
        and raw_book_concentration_hhi > 0
        else None
    )
    book_breadth = (
        round(10 * len(book_counts) / explicit_mentions, 6)
        if explicit_mentions
        else None
    )
    chapter_breadth = (
        round(10 * len(chapter_mentions) / explicit_mentions, 6)
        if explicit_mentions
        else None
    )
    sustained_mentions = sum(
        count
        for counts in sermon_chapter_counts.values()
        for count in counts.values()
        if count >= 2
    )
    sustained_ratio = _rounded_ratio(sustained_mentions, explicit_mentions)
    multi_verse_ratio = _rounded_ratio(multi_verse_references, explicit_mentions)
    repeated_anchor_coverages = [
        len(video_ids) / sermons_analyzed
        for video_ids in chapter_videos.values()
        if len(video_ids) >= 2 and sermons_analyzed
    ]
    cross_sermon_anchor_coverage = (
        round(max(repeated_anchor_coverages), 6)
        if repeated_anchor_coverages
        else 0.0 if explicit_mentions and sermons_analyzed >= 2 else None
    )

    reference_bearing_book_counts = [
        counts for counts in sermon_book_counts.values() if sum(counts.values()) > 0
    ]
    cosine_values = [
        _cosine_similarity(left, right)
        for left, right in combinations(reference_bearing_book_counts, 2)
    ]
    mean_pairwise_cosine = (
        round(sum(cosine_values) / len(cosine_values), 6)
        if cosine_values
        else None
    )
    sermon_densities = [
        1000 * sum(sermon_book_counts[video.id].values()) / sermon_word_counts[video.id]
        for video in analyzed_videos
        if sermon_word_counts.get(video.id, 0) > 0
    ]
    density_consistency = None
    if len(sermon_densities) >= 2:
        density_mean = sum(sermon_densities) / len(sermon_densities)
        if density_mean > 0:
            variance = sum(
                (density - density_mean) ** 2 for density in sermon_densities
            ) / len(sermon_densities)
            coefficient_of_variation = math.sqrt(variance) / density_mean
            density_consistency = round(1 / (1 + coefficient_of_variation), 6)

    division_emphasis = {
        division: {
            "mentions": division_counts[division],
            "share": _rounded_ratio(division_counts[division], explicit_mentions),
        }
        for division in CANONICAL_DIVISIONS
    }
    sermon_structure = []
    for video in analyzed_videos:
        books = sermon_book_counts[video.id]
        chapters = sermon_chapter_counts[video.id]
        reference_count = sum(books.values())
        top_chapter_count = max(chapters.values(), default=0)
        words = sermon_word_counts.get(video.id)
        sermon_structure.append(
            {
                "video_id": video.id,
                "youtube_video_id": video.youtube_video_id,
                "sermon_analysis_run_id": sermon_run_ids[video.id],
                "word_count": words,
                "explicit_reference_mentions": reference_count,
                "reference_density_per_1000_words": (
                    round(1000 * reference_count / words, 6)
                    if words is not None and words > 0
                    else None
                ),
                "distinct_books": len(books),
                "distinct_chapters": len(chapters),
                "top_chapter_share": _rounded_ratio(
                    top_chapter_count, reference_count
                ),
                "book_mentions": dict(sorted(books.items())),
                "chapter_mentions": dict(sorted(chapters.items())),
            }
        )

    feature_values: dict[str, float | None] = {
        "analysis_coverage_fraction": _rounded_ratio(
            sermons_analyzed, sermons_attached
        ),
        "zero_explicit_reference_sermon_fraction": _rounded_ratio(
            zero_reference_sermons, sermons_analyzed
        ),
        "explicit_references_per_1000_words": (
            round(explicit_mentions * 1000 / total_words, 6)
            if total_words
            else None
        ),
        "book_breadth_per_10_references": book_breadth,
        "chapter_breadth_per_10_references": chapter_breadth,
        "book_concentration_hhi": book_concentration_hhi,
        "effective_book_count": effective_book_count,
        "old_testament_share": _rounded_ratio(old_count, explicit_mentions),
        **{
            f"{division}_share": division_emphasis[division]["share"]
            for division in CANONICAL_DIVISIONS
        },
        "sustained_chapter_reference_ratio": sustained_ratio,
        "multi_verse_reference_ratio": multi_verse_ratio,
        "cross_sermon_anchor_coverage": cross_sermon_anchor_coverage,
        "mean_pairwise_book_distribution_cosine": mean_pairwise_cosine,
        "reference_density_consistency": density_consistency,
    }
    assert tuple(feature_values) == PROFILE_FEATURE_ORDER
    feature_vector = {
        "schema_version": 1,
        "feature_names": list(PROFILE_FEATURE_ORDER),
        "values": [feature_values[name] for name in PROFILE_FEATURE_ORDER],
        "by_name": feature_values,
    }
    structural_coverage = {
        "sermons_attached": sermons_attached,
        "sermons_analyzed": sermons_analyzed,
        "sermons_with_explicit_references": sermons_analyzed
        - zero_reference_sermons,
        "sermons_with_zero_explicit_references": zero_reference_sermons,
        "explicit_reference_mentions": explicit_mentions,
        "reference_bearing_sermon_pairs_compared": len(cosine_values),
        "sermons_with_word_counts": len(sermon_densities),
        "contextual_reference_detection": "not_implemented",
        "insufficient_values_are_null": True,
    }
    feature_explanations = {
        "analysis_coverage_fraction": "analyzed sermons / effectively attached sermons",
        "zero_explicit_reference_sermon_fraction": (
            "analyzed sermons with zero explicit matches / analyzed sermons"
        ),
        "explicit_references_per_1000_words": (
            "1000 * explicit mentions / words across analyzed sermons"
        ),
        "book_breadth_per_10_references": "10 * distinct books / explicit mentions",
        "chapter_breadth_per_10_references": "10 * distinct book-chapters / explicit mentions",
        "book_concentration_hhi": "sum of squared book mention shares",
        "effective_book_count": "1 / book concentration HHI",
        "old_testament_share": "Old Testament mentions / explicit mentions",
        **{
            f"{division}_share": f"{division} mentions / explicit mentions"
            for division in CANONICAL_DIVISIONS
        },
        "sustained_chapter_reference_ratio": (
            "share of mentions whose book-chapter has at least two mentions in that sermon"
        ),
        "multi_verse_reference_ratio": "share of explicit references spanning multiple verses",
        "cross_sermon_anchor_coverage": (
            "largest share of analyzed sermons citing the same book-chapter; "
            "requires at least two sermons"
        ),
        "mean_pairwise_book_distribution_cosine": (
            "mean cosine similarity across reference-bearing sermon book-count vectors"
        ),
        "reference_density_consistency": (
            "1 / (1 + population coefficient of variation) of sermon reference densities"
        ),
    }
    assert set(feature_explanations) == set(PROFILE_FEATURE_ORDER)

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
        ("canonical_division_emphasis", division_emphasis, None),
        ("sermon_scripture_structure", sermon_structure, None),
        ("structural_scripture_features", feature_values, None),
        ("structural_coverage_diagnostics", structural_coverage, None),
        ("structural_feature_explanations", feature_explanations, None),
        ("deterministic_profile_feature_vector", feature_vector, None),
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
