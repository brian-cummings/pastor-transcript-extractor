from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

from pastor_transcript_extractor.models import SermonAnalysisRun, SpeakerProfileAnalysisRun, Video
from pastor_transcript_extractor.profile_analysis import (
    profile_membership_fingerprint,
    resolve_profile_sermon_scope,
)
from pastor_transcript_extractor.sermon_analysis import (
    ANALYZER_KEY as SCRIPTURE_ANALYZER_KEY,
    ANALYZER_VERSION as SCRIPTURE_ANALYZER_VERSION,
    PreparedSermonAnalysis,
    prepare_sermon_analysis,
)
from pastor_transcript_extractor.storage import Database


STRUCTURE_ANALYZER_KEY = "sermon-structure"
STRUCTURE_ANALYZER_VERSION = "2"
STRUCTURE_SCHEMA_VERSION = 1
PROFILE_STRUCTURE_ANALYZER_KEY = "profile-sermon-structure"
PROFILE_STRUCTURE_ANALYZER_VERSION = "2"
TOKENIZER_VERSION = "latin-word-apostrophe-v1"
LEXICAL_WINDOW_VERSION = "eight-equal-token-bins-v1"
MATTR_WINDOW = 100

FEATURE_NAMES = (
    "transcript_tokens_per_minute",
    "moving_average_type_token_ratio_100",
    "first_person_singular_per_1000_words",
    "first_person_plural_per_1000_words",
    "second_person_per_1000_words",
    "question_mark_segments_per_1000_words",
    "adjacent_eighth_lexical_cosine_mean",
    "adjacent_eighth_lexical_cosine_min",
    "opening_closing_eighth_lexical_cosine",
    "dominant_scripture_anchor_share",
    "dominant_scripture_anchor_span_fraction",
    "dominant_scripture_anchor_return_rate",
)

FEATURE_EXPLANATIONS = {
    "transcript_tokens_per_minute": (
        "tokenized transcript words / identified sermon duration in minutes; "
        "caption overlap can inflate this and it is not speaking rate"
    ),
    "moving_average_type_token_ratio_100": "mean unique-token share in rolling 100-word windows",
    "first_person_singular_per_1000_words": "I/me/my/mine/myself tokens per 1,000 words",
    "first_person_plural_per_1000_words": "we/us/our/ours/ourselves tokens per 1,000 words",
    "second_person_per_1000_words": "you/your/yours/yourself/yourselves tokens per 1,000 words",
    "question_mark_segments_per_1000_words": "timestamped transcript segments containing '?' per 1,000 words",
    "adjacent_eighth_lexical_cosine_mean": "mean content-token cosine between adjacent equal-word sermon eighths",
    "adjacent_eighth_lexical_cosine_min": "minimum content-token cosine between adjacent equal-word sermon eighths",
    "opening_closing_eighth_lexical_cosine": "content-token cosine between first and final sermon eighths",
    "dominant_scripture_anchor_share": "share of chapter-specific references belonging to the most cited book-chapter",
    "dominant_scripture_anchor_span_fraction": "normalized first-to-last position span for the dominant book-chapter",
    "dominant_scripture_anchor_return_rate": "returns to the dominant book-chapter after another chapter / chapter references",
}

_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_STOPWORDS = frozenset(
    "a an and are as at be been but by did do does for from had has have he her him his i if in is it its me my not of on or our she so than that the their them they this to us was we were what when where which who will with would you your".split()
)
_FIRST_SINGULAR = frozenset("i me my mine myself".split())
_FIRST_PLURAL = frozenset("we us our ours ourselves".split())
_SECOND_PERSON = frozenset("you your yours yourself yourselves".split())


@dataclass(frozen=True, slots=True)
class StructureOutcome:
    run: SermonAnalysisRun
    created: bool


@dataclass(frozen=True, slots=True)
class ProfileStructureOutcome:
    run: SpeakerProfileAnalysisRun
    created: bool


@dataclass(frozen=True, slots=True)
class PreparedStructureInput:
    prepared_sermon: PreparedSermonAnalysis
    scripture_run: SermonAnalysisRun
    input_fingerprint: str


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _tokens(text: str) -> list[str]:
    return [item.casefold() for item in _TOKEN.findall(text)]


def _ratio(numerator: float, denominator: float, scale: float = 1.0) -> float | None:
    return round(scale * numerator / denominator, 6) if denominator else None


def _mattr(tokens: list[str], window: int = MATTR_WINDOW) -> float | None:
    if not tokens:
        return None
    if len(tokens) <= window:
        return round(len(set(tokens)) / len(tokens), 6)
    counts = Counter(tokens[:window])
    total = len(counts) / window
    for index in range(window, len(tokens)):
        outgoing = tokens[index - window]
        counts[outgoing] -= 1
        if not counts[outgoing]:
            del counts[outgoing]
        counts[tokens[index]] += 1
        total += len(counts) / window
    return round(total / (len(tokens) - window + 1), 6)


def _cosine(left: Counter[str], right: Counter[str]) -> float | None:
    if not left or not right:
        return None
    dot = sum(value * right[key] for key, value in left.items())
    denominator = math.sqrt(sum(v * v for v in left.values())) * math.sqrt(
        sum(v * v for v in right.values())
    )
    return round(dot / denominator, 6) if denominator else None


def _lexical_bins(tokens: list[str], count: int = 8) -> list[Counter[str]]:
    if len(tokens) < count:
        return []
    result = []
    for index in range(count):
        start = index * len(tokens) // count
        end = (index + 1) * len(tokens) // count
        result.append(
            Counter(
                token for token in tokens[start:end]
                if token not in _STOPWORDS and len(token) >= 3
            )
        )
    return result


def _scripture_organization(
    database: Database, scripture_run_id: int, segment_indexes: list[int]
) -> dict[str, object]:
    ordinal_by_index = {segment_index: ordinal for ordinal, segment_index in enumerate(segment_indexes)}
    references = []
    for evidence in database.list_sermon_analysis_evidence(scripture_run_id):
        if evidence.evidence_kind != "scripture_reference":
            continue
        payload = json.loads(evidence.payload_json)
        book, chapter = payload.get("book"), payload.get("chapter")
        if (
            isinstance(book, str)
            and isinstance(chapter, int)
            and evidence.segment_index in ordinal_by_index
        ):
            references.append((f"{book} {chapter}", ordinal_by_index[evidence.segment_index], evidence.evidence_key))
    counts = Counter(anchor for anchor, _, _ in references)
    if not counts:
        return {
            "chapter_reference_count": 0,
            "dominant_anchor": None,
            "supporting_evidence_keys": [],
            "dominant_scripture_anchor_share": None,
            "dominant_scripture_anchor_span_fraction": None,
            "dominant_scripture_anchor_return_rate": None,
        }
    dominant = sorted(counts, key=lambda key: (-counts[key], key))[0]
    positions = [index for anchor, index, _ in references if anchor == dominant]
    groups = 0
    previous_was_dominant = False
    for anchor, _, _ in references:
        is_dominant = anchor == dominant
        if is_dominant and not previous_was_dominant:
            groups += 1
        previous_was_dominant = is_dominant
    return {
        "chapter_reference_count": len(references),
        "dominant_anchor": dominant,
        "supporting_evidence_keys": [key for anchor, _, key in references if anchor == dominant],
        "dominant_scripture_anchor_share": _ratio(counts[dominant], len(references)),
        "dominant_scripture_anchor_span_fraction": (
            _ratio(max(positions) - min(positions), max(1, len(segment_indexes) - 1))
            if len(positions) >= 2 else 0.0
        ),
        "dominant_scripture_anchor_return_rate": _ratio(max(0, groups - 1), len(references)),
    }


def prepare_structure_analysis(
    database: Database, video: Video
) -> PreparedStructureInput:
    prepared = prepare_sermon_analysis(database, video)
    scripture_run = database.get_sermon_analysis_run_by_fingerprint(prepared.input_fingerprint)
    if scripture_run is None:
        raise ValueError(
            f"Video {video.youtube_video_id} needs current {SCRIPTURE_ANALYZER_KEY}@{SCRIPTURE_ANALYZER_VERSION}"
        )
    fingerprint = _fingerprint(
        {
            "analyzer_key": STRUCTURE_ANALYZER_KEY,
            "analyzer_version": STRUCTURE_ANALYZER_VERSION,
            "schema_version": STRUCTURE_SCHEMA_VERSION,
            "source_content_sha256": prepared.source_content_sha256,
            "scripture_analysis_run_id": scripture_run.id,
            "scripture_analysis_input_fingerprint": scripture_run.input_fingerprint,
            "tokenizer_version": TOKENIZER_VERSION,
            "lexical_window_version": LEXICAL_WINDOW_VERSION,
            "video_id": video.id,
        }
    )
    return PreparedStructureInput(prepared, scripture_run, fingerprint)


def analyze_sermon_structure(database: Database, video: Video) -> StructureOutcome:
    structure_input = prepare_structure_analysis(database, video)
    prepared = structure_input.prepared_sermon
    scripture_run = structure_input.scripture_run
    tokens = _tokens(" ".join(segment.text for segment in prepared.segments))
    word_count = len(tokens)
    bins = _lexical_bins(tokens)
    adjacent = [
        value for left, right in zip(bins, bins[1:])
        if (value := _cosine(left, right)) is not None
    ]
    organization = _scripture_organization(
        database, scripture_run.id, [segment.index for segment in prepared.segments]
    )
    values: dict[str, object] = {
        "transcript_tokens_per_minute": _ratio(
            word_count, prepared.duration_seconds, 60
        ),
        "moving_average_type_token_ratio_100": _mattr(tokens),
        "first_person_singular_per_1000_words": _ratio(sum(t in _FIRST_SINGULAR for t in tokens), word_count, 1000),
        "first_person_plural_per_1000_words": _ratio(sum(t in _FIRST_PLURAL for t in tokens), word_count, 1000),
        "second_person_per_1000_words": _ratio(sum(t in _SECOND_PERSON for t in tokens), word_count, 1000),
        "question_mark_segments_per_1000_words": _ratio(sum("?" in s.text for s in prepared.segments), word_count, 1000),
        "adjacent_eighth_lexical_cosine_mean": round(statistics.fmean(adjacent), 6) if adjacent else None,
        "adjacent_eighth_lexical_cosine_min": min(adjacent) if adjacent else None,
        "opening_closing_eighth_lexical_cosine": _cosine(bins[0], bins[-1]) if bins else None,
        **{name: organization[name] for name in FEATURE_NAMES if name.startswith("dominant_")},
    }
    run, created = database.add_sermon_analysis_run(
        video_id=video.id,
        extraction_result_id=prepared.extraction_result_id,
        analyzer_key=STRUCTURE_ANALYZER_KEY,
        analyzer_version=STRUCTURE_ANALYZER_VERSION,
        source_kind="identified_sermon_transcript",
        source_path=str(prepared.source_path),
        source_content_sha256=prepared.source_content_sha256,
        input_fingerprint=structure_input.input_fingerprint,
        measurements=[
            ("feature_vector", _json({"schema_version": 1, "feature_names": list(FEATURE_NAMES), "by_name": values}), None),
            ("feature_explanations", _json(FEATURE_EXPLANATIONS), None),
            ("scripture_organization_trace", _json(organization), None),
            ("source_diagnostics", _json({"word_count": word_count, "duration_seconds": prepared.duration_seconds, "segment_count": len(prepared.segments), "scripture_analysis_run_id": scripture_run.id, "tokenizer_version": TOKENIZER_VERSION, "lexical_window_version": LEXICAL_WINDOW_VERSION}), None),
        ],
        evidence=[],
    )
    return StructureOutcome(run, created)


def profile_structure_input_fingerprint(
    *, profile_id: int, membership_fingerprint: str, sermon_run_ids: list[int]
) -> str:
    return _fingerprint({
        "analyzer_key": PROFILE_STRUCTURE_ANALYZER_KEY,
        "analyzer_version": PROFILE_STRUCTURE_ANALYZER_VERSION,
        "membership_fingerprint": membership_fingerprint,
        "profile_id": profile_id,
        "schema_version": 1,
        "sermon_structure_run_ids": sorted(sermon_run_ids),
    })


def _measurements(database: Database, run_id: int) -> dict[str, object]:
    return {item.metric_key: json.loads(item.value_json) for item in database.list_sermon_analysis_measurements(run_id)}


def build_profile_structure_analysis(database: Database, profile_id: int) -> ProfileStructureOutcome:
    scope = resolve_profile_sermon_scope(database, profile_id)
    membership = profile_membership_fingerprint(database, scope)
    inputs = []
    feature_rows = []
    missing = []
    for video in scope.videos:
        run = database.get_latest_sermon_analysis_run(video.id, STRUCTURE_ANALYZER_KEY, STRUCTURE_ANALYZER_VERSION)
        if run is None:
            missing.append(video.id)
            continue
        vector = _measurements(database, run.id).get("feature_vector")
        if not isinstance(vector, dict) or vector.get("schema_version") != 1:
            missing.append(video.id)
            continue
        inputs.append((run.id, video.id))
        feature_rows.append(vector["by_name"])
    summaries = {}
    for name in FEATURE_NAMES:
        observed = [float(row[name]) for row in feature_rows if row.get(name) is not None]
        summaries[name] = {
            "observed_sermons": len(observed),
            "mean": round(statistics.fmean(observed), 6) if observed else None,
            "median": round(statistics.median(observed), 6) if observed else None,
            "standard_deviation": round(statistics.pstdev(observed), 6) if observed else None,
        }
    fingerprint = profile_structure_input_fingerprint(
        profile_id=scope.profile_id,
        membership_fingerprint=membership,
        sermon_run_ids=[run_id for run_id, _ in inputs],
    )
    run, created = database.add_speaker_profile_analysis_run(
        profile_id=scope.profile_id,
        analyzer_key=PROFILE_STRUCTURE_ANALYZER_KEY,
        analyzer_version=PROFILE_STRUCTURE_ANALYZER_VERSION,
        membership_fingerprint=membership,
        input_fingerprint=fingerprint,
        inputs=inputs,
        measurements=[
            ("sermons_attached", _json(len(scope.videos)), "sermons"),
            ("sermons_analyzed", _json(len(inputs)), "sermons"),
            ("sermons_missing_analysis", _json(len(missing)), "sermons"),
            ("missing_video_ids", _json(sorted(missing)), None),
            ("feature_summaries", _json(summaries), None),
            ("feature_explanations", _json(FEATURE_EXPLANATIONS), None),
            ("deterministic_profile_feature_vector", _json({"schema_version": 1, "feature_names": list(FEATURE_NAMES), "by_name": {name: summaries[name]["mean"] for name in FEATURE_NAMES}}), None),
        ],
    )
    return ProfileStructureOutcome(run, created)
