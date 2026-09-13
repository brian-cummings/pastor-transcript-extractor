from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from itertools import combinations
import json
import math
import random
import statistics
from typing import Iterable

from pastor_transcript_extractor.analysis_readiness import build_readiness_report
from pastor_transcript_extractor.comparison_features import (
    BENCHMARK_FEATURE_SCHEMA_VERSION,
    CORE_FEATURE_NAMES,
    DEPTH_SENSITIVE_FEATURE_NAMES,
    DIAGNOSTIC_ONLY_FEATURE_NAMES,
    FEATURE_ROLE_ASSIGNMENTS,
    RAW_CANONICAL_SHARE_FEATURE_NAMES,
)
from pastor_transcript_extractor.models import PopulationAnalysisSnapshot
from pastor_transcript_extractor.profile_analysis import (
    CANONICAL_DIVISIONS,
    PROFILE_ANALYZER_KEY,
    PROFILE_ANALYZER_VERSION,
    PROFILE_FEATURE_ORDER,
)
from pastor_transcript_extractor.sermon_analysis import OLD_TESTAMENT_BOOKS
from pastor_transcript_extractor.storage import Database


POPULATION_ANALYZER_VERSION = "scripture-population-diagnostics@3"
FEATURE_SCHEMA_VERSION = "deterministic-profile-feature-vector@2"
ELIGIBILITY_POLICY_VERSION = "population-current-profiles@1"
MIN_CORRELATION_PROFILES = 10
MIN_OUTLIER_PROFILES = 8
STRONG_CORRELATION_THRESHOLD = 0.75
HIGH_CORRELATION_THRESHOLD = 0.90
UNSUPPORTED_BOOTSTRAP_FEATURES = frozenset({
    "cross_sermon_anchor_coverage",
    "mean_pairwise_book_distribution_cosine",
    "chapter_breadth_per_10_references",
    "book_breadth_per_10_references",
})
PRIMARY_FEATURES = ("references_per_1000_words", "scripture_text_engagement_fraction")

FEATURE_NAMES = tuple(
    name for name in PROFILE_FEATURE_ORDER if name != "analysis_coverage_fraction"
)


@dataclass(frozen=True, slots=True)
class PopulationPolicy:
    minimum_sermons: int = 3
    bootstrap_samples: int = 200
    version: str = ELIGIBILITY_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.minimum_sermons < 2:
            raise ValueError("Population diagnostics require at least two sermons")
        if self.bootstrap_samples < 20:
            raise ValueError("Bootstrap samples must be at least 20")
        if not self.version.strip():
            raise ValueError("Eligibility policy version must not be blank")

    def payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "minimum_sermons": self.minimum_sermons,
            "bootstrap_samples": self.bootstrap_samples,
            "eligible_profile_lifecycles": ["active", "provisional"],
            "requires_exact_current_profile_analysis": True,
        }


@dataclass(frozen=True, slots=True)
class PopulationSnapshotOutcome:
    snapshot: PopulationAnalysisSnapshot
    created: bool
    report: dict[str, object]


@dataclass(frozen=True, slots=True)
class SermonRecord:
    run_id: int
    video_id: int
    source_id: int
    published_ordinal: int | None
    word_count: int
    books: Counter[str]
    chapters: Counter[str]
    multi_verse_references: int
    alignment_count: int
    anchored_alignment_count: int
    aligned_span_words: int
    alignment_scores: tuple[float, ...]
    aligned_chapters: Counter[str]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator > 0 else None


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _variance(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = statistics.fmean(values)
    return statistics.fmean((value - mean) ** 2 for value in values)


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_sd = math.sqrt(statistics.fmean((value - left_mean) ** 2 for value in left))
    right_sd = math.sqrt(statistics.fmean((value - right_mean) ** 2 for value in right))
    if left_sd == 0 or right_sd == 0:
        return None
    covariance = statistics.fmean(
        (x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True)
    )
    return round(covariance / (left_sd * right_sd), 6)


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    keys = set(left) | set(right)
    dot = sum(left[key] * right[key] for key in keys)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm)


def _measurements(database: Database, run_id: int) -> dict[str, object]:
    return {
        item.metric_key: json.loads(item.value_json)
        for item in database.list_sermon_analysis_measurements(run_id)
    }


def _profile_measurements(database: Database, run_id: int) -> dict[str, object]:
    return {
        item.metric_key: json.loads(item.value_json)
        for item in database.list_speaker_profile_analysis_measurements(run_id)
    }


def _load_sermon_record(
    database: Database,
    run_id: int,
    *,
    runs_by_id: dict[int, object],
    videos_by_id: dict[int, object],
) -> SermonRecord:
    run = runs_by_id[run_id]
    video = videos_by_id[run.video_id]
    values = _measurements(database, run_id)
    word_count = values.get("word_count")
    if not isinstance(word_count, int) or isinstance(word_count, bool):
        raise ValueError(f"Sermon analysis run {run_id} has no integer word_count")
    books: Counter[str] = Counter()
    chapters: Counter[str] = Counter()
    aligned_chapters: Counter[str] = Counter()
    multi_verse = alignments = anchored = aligned_words = 0
    scores: list[float] = []
    for evidence in database.list_sermon_analysis_evidence(run_id):
        payload = json.loads(evidence.payload_json)
        if evidence.evidence_kind == "scripture_reference":
            if payload.get("detection_class") not in {"explicit", "contextual"}:
                continue
            book = payload.get("book")
            chapter = payload.get("chapter")
            if not isinstance(book, str):
                continue
            books[book] += 1
            if isinstance(chapter, int):
                chapters[f"{book} {chapter}"] += 1
            start = payload.get("verse_start")
            end = payload.get("verse_end")
            if isinstance(start, int) and isinstance(end, int) and end > start:
                multi_verse += 1
        elif evidence.evidence_kind == "scripture_text_alignment":
            alignments += 1
            anchored += payload.get("alignment_class") == "anchored"
            span_words = payload.get("transcript_span_word_count")
            if isinstance(span_words, int) and not isinstance(span_words, bool):
                aligned_words += span_words
            score = _number(payload.get("alignment_score"))
            if score is not None:
                scores.append(score)
            book = payload.get("book")
            chapter = payload.get("chapter")
            if isinstance(book, str) and isinstance(chapter, int):
                aligned_chapters[f"{book} {chapter}"] += 1
    published = video.published_at
    return SermonRecord(
        run_id=run_id,
        video_id=run.video_id,
        source_id=video.source_id,
        published_ordinal=published.date().toordinal() if published else None,
        word_count=word_count,
        books=books,
        chapters=chapters,
        multi_verse_references=multi_verse,
        alignment_count=alignments,
        anchored_alignment_count=anchored,
        aligned_span_words=aligned_words,
        alignment_scores=tuple(scores),
        aligned_chapters=aligned_chapters,
    )


def aggregate_sermon_records(records: Iterable[SermonRecord]) -> dict[str, float | None]:
    sermons = list(records)
    total_words = sum(item.word_count for item in sermons)
    book_counts: Counter[str] = Counter()
    chapter_counts: Counter[str] = Counter()
    aligned_chapters: Counter[str] = Counter()
    for item in sermons:
        book_counts.update(item.books)
        chapter_counts.update(item.chapters)
        aligned_chapters.update(item.aligned_chapters)
    references = sum(book_counts.values())
    alignments = sum(item.alignment_count for item in sermons)
    raw_hhi = (
        sum((count / references) ** 2 for count in book_counts.values())
        if references
        else None
    )
    repeated_anchor_coverage = [
        sum(chapter in item.chapters for item in sermons) / len(sermons)
        for chapter in chapter_counts
        if len(sermons) >= 2 and sum(chapter in item.chapters for item in sermons) >= 2
    ]
    book_vectors = [item.books for item in sermons if sum(item.books.values()) > 0]
    cosine_values = [_cosine(left, right) for left, right in combinations(book_vectors, 2)]
    densities = [
        1000 * sum(item.books.values()) / item.word_count
        for item in sermons
        if item.word_count > 0
    ]
    density_consistency = None
    if len(densities) >= 2 and statistics.fmean(densities) > 0:
        mean = statistics.fmean(densities)
        coefficient = math.sqrt(statistics.fmean((value - mean) ** 2 for value in densities)) / mean
        density_consistency = round(1 / (1 + coefficient), 6)
    testament_old = sum(
        count for book, count in book_counts.items() if book in OLD_TESTAMENT_BOOKS
    )
    division_counts = Counter(
        {
            division: sum(book_counts[book] for book in books)
            for division, books in CANONICAL_DIVISIONS.items()
        }
    )
    alignment_scores = [score for item in sermons for score in item.alignment_scores]
    values: dict[str, float | None] = {
        "zero_detected_reference_sermon_fraction": _ratio(
            sum(sum(item.books.values()) == 0 for item in sermons), len(sermons)
        ),
        "references_per_1000_words": _ratio(1000 * references, total_words),
        "book_breadth_per_10_references": _ratio(10 * len(book_counts), references),
        "chapter_breadth_per_10_references": _ratio(10 * len(chapter_counts), references),
        "book_concentration_hhi": round(raw_hhi, 6) if raw_hhi is not None else None,
        "effective_book_count": (
            round(1 / raw_hhi, 6) if raw_hhi is not None and raw_hhi > 0 else None
        ),
        "old_testament_share": _ratio(testament_old, references),
        **{
            f"{division}_share": _ratio(division_counts[division], references)
            for division in CANONICAL_DIVISIONS
        },
        "sustained_chapter_reference_ratio": _ratio(
            sum(
                count
                for item in sermons
                for count in item.chapters.values()
                if count >= 2
            ),
            references,
        ),
        "multi_verse_reference_ratio": _ratio(
            sum(item.multi_verse_references for item in sermons), references
        ),
        "cross_sermon_anchor_coverage": (
            round(max(repeated_anchor_coverage), 6)
            if repeated_anchor_coverage
            else 0.0 if references and len(sermons) >= 2 else None
        ),
        "mean_pairwise_book_distribution_cosine": (
            round(statistics.fmean(cosine_values), 6) if cosine_values else None
        ),
        "reference_density_consistency": density_consistency,
        "scripture_text_engagement_fraction": _ratio(
            sum(item.aligned_span_words for item in sermons), total_words
        ),
        "sermons_with_text_alignment_fraction": _ratio(
            sum(item.alignment_count > 0 for item in sermons), len(sermons)
        ),
        "anchored_text_alignment_fraction": _ratio(
            sum(item.anchored_alignment_count for item in sermons), alignments
        ),
        "mean_scripture_text_alignment_score": (
            round(statistics.fmean(alignment_scores), 6) if alignment_scores else None
        ),
        "aligned_passage_concentration_hhi": (
            round(
                sum((count / alignments) ** 2 for count in aligned_chapters.values()), 6
            )
            if alignments
            else None
        ),
    }
    assert tuple(values) == FEATURE_NAMES
    return values


def _distribution(values: list[float], population_count: int) -> dict[str, object]:
    median = statistics.median(values) if values else None
    return {
        "observed_count": len(values),
        "missing_count": population_count - len(values),
        "missing_fraction": round((population_count - len(values)) / population_count, 6)
        if population_count
        else None,
        "zero_count": sum(value == 0 for value in values),
        "zero_fraction": round(sum(value == 0 for value in values) / len(values), 6)
        if values
        else None,
        "minimum": min(values) if values else None,
        "q1": _quantile(values, 0.25),
        "median": median,
        "q3": _quantile(values, 0.75),
        "maximum": max(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
        "standard_deviation": math.sqrt(_variance(values) or 0.0) if values else None,
        "median_absolute_deviation": (
            statistics.median(abs(value - median) for value in values)
            if values and median is not None
            else None
        ),
    }


def _scale(distribution: dict[str, object]) -> float | None:
    q1 = _number(distribution["q1"])
    q3 = _number(distribution["q3"])
    if q1 is not None and q3 is not None and q3 > q1:
        return q3 - q1
    standard_deviation = _number(distribution["standard_deviation"])
    if standard_deviation is not None and standard_deviation > 0:
        return standard_deviation
    minimum = _number(distribution["minimum"])
    maximum = _number(distribution["maximum"])
    if minimum is not None and maximum is not None and maximum > minimum:
        return maximum - minimum
    return None


def _profile_stability(
    records: list[SermonRecord],
    baseline: dict[str, float | None],
    *,
    bootstrap_samples: int,
    seed: str,
) -> dict[str, object]:
    leave_one_out = [
        aggregate_sermon_records(records[:index] + records[index + 1 :])
        for index in range(len(records))
    ]
    generator = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))
    bootstraps = [
        aggregate_sermon_records([generator.choice(records) for _ in records])
        for _ in range(bootstrap_samples)
    ]
    features: dict[str, object] = {}
    for name in FEATURE_NAMES:
        center = baseline[name]
        loo_values = [value for item in leave_one_out if (value := item[name]) is not None]
        bootstrap_values = (
            [value for item in bootstraps if (value := item[name]) is not None]
            if name not in UNSUPPORTED_BOOTSTRAP_FEATURES else []
        )
        deltas = [abs(value - center) for value in loo_values] if center is not None else []
        features[name] = {
            "leave_one_out_observed": len(loo_values),
            "leave_one_out_max_absolute_delta": max(deltas) if deltas else None,
            "leave_one_out_median_absolute_delta": statistics.median(deltas) if deltas else None,
            "leave_one_out_variance": _variance(loo_values),
            "bootstrap_status": (
                "unsupported_distinct_origin_or_exposure_estimator_required"
                if name in UNSUPPORTED_BOOTSTRAP_FEATURES
                else "conditional_on_collected_sermons_not_pastor_reliability"
            ),
            "bootstrap_observed": len(bootstrap_values),
            "bootstrap_ci_95_lower": _quantile(bootstrap_values, 0.025),
            "bootstrap_ci_95_upper": _quantile(bootstrap_values, 0.975),
        }
    sermon_distributions = {}
    for name in PRIMARY_FEATURES:
        observations = [
            {"sermon_run_id": record.run_id, "video_id": record.video_id,
             "value": aggregate_sermon_records([record])[name]}
            for record in records
        ]
        values = [item["value"] for item in observations if item["value"] is not None]
        sermon_distributions[name] = {
            "estimand": "equal_sermon_distribution",
            "distribution": _distribution(values, len(records)),
            "population_variance": _variance(values),
            "observations": observations,
        }
    return {"features": features, "sermon_distributions": sermon_distributions}


def _selection_delta(
    records: list[SermonRecord], baseline: dict[str, float | None]
) -> tuple[dict[str, float], dict[str, float]]:
    dated = sorted(
        (item for item in records if item.published_ordinal is not None),
        key=lambda item: item.published_ordinal or 0,
    )
    date_deltas: dict[str, float] = {}
    if len(dated) >= 4:
        midpoint = len(dated) // 2
        early = aggregate_sermon_records(dated[:midpoint])
        late = aggregate_sermon_records(dated[midpoint:])
        for name in FEATURE_NAMES:
            if early[name] is not None and late[name] is not None:
                date_deltas[name] = abs(early[name] - late[name])
    source_deltas: dict[str, float] = {}
    sources = sorted({item.source_id for item in records})
    if len(sources) >= 2:
        for name in FEATURE_NAMES:
            center = baseline[name]
            values = []
            for source_id in sources:
                subset = [item for item in records if item.source_id != source_id]
                if len(subset) < 2 or center is None:
                    continue
                value = aggregate_sermon_records(subset)[name]
                if value is not None:
                    values.append(abs(value - center))
            if values:
                source_deltas[name] = max(values)
    return date_deltas, source_deltas


def _recommendation(
    name: str,
    distribution: dict[str, object],
    stability: str,
    redundant_with: list[str],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if (_number(distribution["missing_fraction"]) or 0) > 0.25:
        reasons.append("high_missingness")
    if (_number(distribution["zero_fraction"]) or 0) >= 0.8:
        reasons.append("high_zero_inflation")
    if stability == "low":
        reasons.append("low_leave_one_out_stability")
    if stability == "not_evaluable":
        reasons.append("no_usable_between_profile_scale")
    if redundant_with:
        reasons.append("high_pairwise_correlation")
    role = _reviewed_role(name)
    if role == "diagnostic_only":
        reasons.append("reviewed_diagnostic_only_role")
        decision = "diagnostic_only_reviewed"
    elif role == "composition_source_not_independent_dimension":
        reasons.append("reviewed_compositional_family_source")
        decision = "use_only_via_canonical_composition"
    elif "no_usable_between_profile_scale" in reasons:
        decision = "move_to_diagnostic_only_or_collect_more_profiles"
    elif "high_missingness" in reasons:
        decision = "investigate_detector_or_require_larger_corpus"
    elif "low_leave_one_out_stability" in reasons:
        decision = "require_larger_corpus_or_transform"
    elif "high_zero_inflation" in reasons:
        decision = "move_to_diagnostic_only_or_transform"
    elif redundant_with:
        decision = "review_redundancy"
    elif role == "depth_sensitive_minimum_8_sermons":
        decision = "validate_before_comparison"
    elif role == "core_minimum_5_sermons":
        decision = "validate_before_comparison"
    else:
        decision = "description_only_pending_validation"
    reasons.append("deletion_sensitivity_does_not_establish_reliability")
    return decision, reasons


def _reviewed_role(name: str) -> str:
    if name in CORE_FEATURE_NAMES:
        return "core_minimum_5_sermons"
    if name in DEPTH_SENSITIVE_FEATURE_NAMES:
        return "depth_sensitive_minimum_8_sermons"
    if name in RAW_CANONICAL_SHARE_FEATURE_NAMES:
        return "composition_source_not_independent_dimension"
    if name in DIAGNOSTIC_ONLY_FEATURE_NAMES:
        return "diagnostic_only"
    return "not_selected"


def build_population_snapshot(
    database: Database,
    *,
    policy: PopulationPolicy | None = None,
    analyzer_version: str = POPULATION_ANALYZER_VERSION,
) -> PopulationSnapshotOutcome:
    policy = policy or PopulationPolicy()
    if not analyzer_version.strip():
        raise ValueError("Population analyzer version must not be blank")
    readiness = build_readiness_report(database)
    eligible = [
        item
        for item in readiness.profiles
        if item.eligible_sermons >= policy.minimum_sermons
        and item.aggregate_state == "current"
        and item.aggregate_run_id is not None
    ]
    inputs = sorted((item.profile_id, int(item.aggregate_run_id)) for item in eligible)
    all_runs = {run.id: run for run in database.list_sermon_analysis_runs()}
    videos = {video.id: video for video in database.list_videos()}
    diagnostic_inputs = []
    for item in eligible:
        profile_run_id = int(item.aggregate_run_id)
        sermon_metadata = []
        for run_id in database.list_speaker_profile_analysis_input_run_ids(profile_run_id):
            run = all_runs[run_id]
            video = videos[run.video_id]
            sermon_metadata.append(
                {
                    "sermon_analysis_run_id": run_id,
                    "source_id": video.source_id,
                    "published_at": video.published_at.isoformat() if video.published_at else None,
                    "video_id": video.id,
                }
            )
        diagnostic_inputs.append(
            {
                "lifecycle_state": item.lifecycle_state,
                "profile_analysis_run_id": profile_run_id,
                "profile_id": item.profile_id,
                "sermons": sermon_metadata,
            }
        )
    fingerprint = _fingerprint(
        {
            "analyzer_version": analyzer_version,
            "diagnostic_inputs": diagnostic_inputs,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "policy": policy.payload(),
            "profile_analyzer_key": PROFILE_ANALYZER_KEY,
            "profile_analyzer_version": PROFILE_ANALYZER_VERSION,
            "reviewed_comparison_schema_version": BENCHMARK_FEATURE_SCHEMA_VERSION,
            "reviewed_feature_roles": FEATURE_ROLE_ASSIGNMENTS,
        }
    )
    existing = database.get_population_analysis_snapshot_by_fingerprint(fingerprint)
    if existing is not None:
        return PopulationSnapshotOutcome(
            snapshot=existing, created=False, report=json.loads(existing.report_json)
        )
    if not inputs:
        raise ValueError("No current eligible profile analyses are available")

    profiles: list[dict[str, object]] = []
    records_cache: dict[int, SermonRecord] = {}
    for profile_id, profile_run_id in inputs:
        measurements = _profile_measurements(database, profile_run_id)
        vector = measurements.get("deterministic_profile_feature_vector")
        if not isinstance(vector, dict) or vector.get("schema_version") != 2:
            raise ValueError(f"Profile analysis run {profile_run_id} has an incompatible vector")
        by_name = vector.get("by_name")
        if not isinstance(by_name, dict):
            raise ValueError(f"Profile analysis run {profile_run_id} has no named vector")
        values = {name: _number(by_name.get(name)) for name in FEATURE_NAMES}
        sermon_run_ids = database.list_speaker_profile_analysis_input_run_ids(profile_run_id)
        records = []
        for run_id in sermon_run_ids:
            if run_id not in records_cache:
                records_cache[run_id] = _load_sermon_record(
                    database, run_id, runs_by_id=all_runs, videos_by_id=videos
                )
            records.append(records_cache[run_id])
        recomputed = aggregate_sermon_records(records)
        parity = {
            name: (
                abs(values[name] - recomputed[name])
                if values[name] is not None and recomputed[name] is not None
                else None
            )
            for name in FEATURE_NAMES
        }
        stability = _profile_stability(
            records,
            recomputed,
            bootstrap_samples=policy.bootstrap_samples,
            seed=f"{analyzer_version}:{profile_id}:{profile_run_id}",
        )
        date_deltas, source_deltas = _selection_delta(records, recomputed)
        profile = database.get_speaker_profile(profile_id)
        profiles.append(
            {
                "profile_id": profile_id,
                "display_label": profile.display_label if profile else None,
                "lifecycle_state": profile.lifecycle_state if profile else None,
                "profile_analysis_run_id": profile_run_id,
                "sermon_analysis_run_ids": sermon_run_ids,
                "sermon_count": len(records),
                "source_count": len({item.source_id for item in records}),
                "dated_sermon_count": sum(item.published_ordinal is not None for item in records),
                "values": values,
                "recomputation_parity_max_absolute_delta": max(
                    (value for value in parity.values() if value is not None), default=None
                ),
                "stability": stability,
                "date_split_absolute_deltas": date_deltas,
                "leave_one_source_out_max_absolute_deltas": source_deltas,
            }
        )

    distributions = {
        name: _distribution(
            [value for profile in profiles if (value := profile["values"][name]) is not None],
            len(profiles),
        )
        for name in FEATURE_NAMES
    }
    strong_correlations = []
    high_correlations = []
    redundant: dict[str, list[str]] = {name: [] for name in FEATURE_NAMES}
    for left_name, right_name in combinations(FEATURE_NAMES, 2):
        pairs = [
            (left, right)
            for profile in profiles
            if (left := profile["values"][left_name]) is not None
            and (right := profile["values"][right_name]) is not None
        ]
        correlation = _pearson(
            [left for left, _ in pairs], [right for _, right in pairs]
        )
        if (
            len(pairs) >= MIN_CORRELATION_PROFILES
            and correlation is not None
            and abs(correlation) >= STRONG_CORRELATION_THRESHOLD
        ):
            item = {
                "left": left_name,
                "right": right_name,
                "pearson": correlation,
                "shared_profiles": len(pairs),
            }
            strong_correlations.append(item)
            redundant[left_name].append(right_name)
            redundant[right_name].append(left_name)
            if abs(correlation) >= HIGH_CORRELATION_THRESHOLD:
                high_correlations.append(item)

    feature_diagnostics: dict[str, object] = {}
    sermon_counts = [float(profile["sermon_count"]) for profile in profiles]
    positive_standard_deviations = [
        value
        for distribution in distributions.values()
        if (value := _number(distribution["standard_deviation"])) is not None and value > 0
    ]
    median_sd = statistics.median(positive_standard_deviations) if positive_standard_deviations else 0.0
    for name in FEATURE_NAMES:
        distribution = distributions[name]
        scale = _scale(distribution)
        median = _number(distribution["median"])
        mad = _number(distribution["median_absolute_deviation"])
        outliers = []
        minimum = _number(distribution["minimum"])
        maximum = _number(distribution["maximum"])
        zero_fraction = _number(distribution["zero_fraction"])
        bounded = (
            minimum is not None
            and maximum is not None
            and 0 <= minimum <= maximum <= 1
        )
        outlier_policy = (
            "suppressed_bounded_or_zero_inflated"
            if bounded or (zero_fraction is not None and zero_fraction >= 0.2)
            else "modified_z_mad_3.5"
        )
        outlier_population = (
            profiles
            if int(distribution["observed_count"]) >= MIN_OUTLIER_PROFILES
            and outlier_policy == "modified_z_mad_3.5"
            else []
        )
        for profile in outlier_population:
            value = profile["values"][name]
            if value is None:
                continue
            is_outlier = bool(
                median is not None
                and mad is not None
                and mad > 0
                and abs(value - median) / (1.4826 * mad) > 3.5
            )
            if is_outlier:
                outliers.append({"profile_id": profile["profile_id"], "value": value})
        normalized_loo = []
        normalized_bootstrap = []
        within_variances = []
        date_sensitivity = []
        source_sensitivity = []
        for profile in profiles:
            detail = profile["stability"]["features"][name]
            loo_delta = _number(detail["leave_one_out_max_absolute_delta"])
            if loo_delta is not None and scale:
                normalized_loo.append(loo_delta / scale)
            lower = _number(detail["bootstrap_ci_95_lower"])
            upper = _number(detail["bootstrap_ci_95_upper"])
            if lower is not None and upper is not None and scale:
                normalized_bootstrap.append((upper - lower) / scale)
            variance = _number(detail["leave_one_out_variance"])
            if variance is not None:
                within_variances.append(variance)
            date_delta = profile["date_split_absolute_deltas"].get(name)
            source_delta = profile["leave_one_source_out_max_absolute_deltas"].get(name)
            if date_delta is not None and scale:
                date_sensitivity.append(date_delta / scale)
            if source_delta is not None and scale:
                source_sensitivity.append(source_delta / scale)
        median_loo = statistics.median(normalized_loo) if normalized_loo else None
        stability_label = (
            "not_evaluable" if median_loo is None
            else "high" if median_loo <= 0.25
            else "moderate" if median_loo <= 0.75
            else "low"
        )
        observed_values = [
            value for profile in profiles if (value := profile["values"][name]) is not None
        ]
        paired_counts = [
            count for count, profile in zip(sermon_counts, profiles, strict=True)
            if profile["values"][name] is not None
        ]
        between_variance = _variance(observed_values)
        mean_within = statistics.fmean(within_variances) if within_variances else None
        decision, reasons = _recommendation(
            name, distribution, stability_label, redundant[name]
        )
        standard_deviation = _number(distribution["standard_deviation"])
        feature_diagnostics[name] = {
            "distribution": distribution,
            "scale_ratio_to_median_feature_sd": (
                round(standard_deviation / median_sd, 6)
                if standard_deviation is not None and median_sd > 0
                else None
            ),
            "corpus_size_pearson": _pearson(paired_counts, observed_values),
            "leave_one_out": {
                "profiles_evaluated": len(normalized_loo),
                "median_max_delta_in_population_iqr": (
                    round(median_loo, 6) if median_loo is not None else None
                ),
                "worst_max_delta_in_population_iqr": (
                    round(max(normalized_loo), 6) if normalized_loo else None
                ),
                "deletion_sensitivity": ({"high": "low", "moderate": "moderate", "low": "high", "not_evaluable": "not_evaluable"}[stability_label]),
            },
            "bootstrap": {
                "status": ("unsupported_distinct_origin_or_exposure_estimator_required"
                           if name in UNSUPPORTED_BOOTSTRAP_FEATURES
                           else "conditional_on_collected_sermons_not_pastor_reliability"),
                "profiles_evaluated": len(normalized_bootstrap),
                "median_ci_width_in_population_iqr": (
                    round(statistics.median(normalized_bootstrap), 6)
                    if normalized_bootstrap
                    else None
                ),
            },
            "between_profile_variance": between_variance,
            "mean_aggregate_deletion_variance": mean_within,
            "between_to_aggregate_deletion_variance_ratio": (
                round(between_variance / mean_within, 6)
                if between_variance is not None and mean_within is not None and mean_within > 0
                else None
            ),
            "date_split": {
                "profiles_evaluated": len(date_sensitivity),
                "median_delta_in_population_iqr": (
                    round(statistics.median(date_sensitivity), 6)
                    if date_sensitivity
                    else None
                ),
            },
            "leave_one_source_out": {
                "profiles_evaluated": len(source_sensitivity),
                "median_max_delta_in_population_iqr": (
                    round(statistics.median(source_sensitivity), 6)
                    if source_sensitivity
                    else None
                ),
            },
            "highly_correlated_with": sorted(redundant[name]),
            "reviewed_schema_role": _reviewed_role(name),
            "outlier_policy": outlier_policy,
            "outliers": sorted(outliers, key=lambda item: item["profile_id"]),
            "recommendation": decision,
            "recommendation_reasons": reasons,
        }

    depth_stability = {}
    for minimum in (3, 5, 8, 10):
        cohort = [profile for profile in profiles if profile["sermon_count"] >= minimum]
        stable = 0
        evaluated = 0
        for profile in cohort:
            for name in FEATURE_NAMES:
                delta = _number(
                    profile["stability"]["features"][name][
                        "leave_one_out_max_absolute_delta"
                    ]
                )
                scale = _scale(distributions[name])
                if delta is not None and scale:
                    evaluated += 1
                    stable += delta / scale <= 0.25
        depth_stability[str(minimum)] = {
            "profile_count": len(cohort),
            "feature_estimates_evaluated": evaluated,
            "low_deletion_sensitivity_fraction": round(stable / evaluated, 6) if evaluated else None,
            "sampling": "eligible_cohort_full_samples_not_matched_depth",
        }

    report: dict[str, object] = {
        "schema_version": "scripture-population-report@2",
        "analyzer_version": analyzer_version,
        "profile_analyzer": f"{PROFILE_ANALYZER_KEY}@{PROFILE_ANALYZER_VERSION}",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "reviewed_comparison_schema_version": BENCHMARK_FEATURE_SCHEMA_VERSION,
        "reviewed_feature_roles": FEATURE_ROLE_ASSIGNMENTS,
        "eligibility_policy": policy.payload(),
        "input_fingerprint": fingerprint,
        "population": {
            "profile_count": len(profiles),
            "sermon_count": sum(profile["sermon_count"] for profile in profiles),
            "depth_counts": {
                str(minimum): sum(profile["sermon_count"] >= minimum for profile in profiles)
                for minimum in (3, 5, 8, 10)
            },
        },
        "feature_names": list(FEATURE_NAMES),
        "feature_diagnostics": feature_diagnostics,
        "strong_correlations": sorted(
            strong_correlations,
            key=lambda item: (-abs(item["pearson"]), item["left"], item["right"]),
        ),
        "high_correlations": sorted(
            high_correlations,
            key=lambda item: (-abs(item["pearson"]), item["left"], item["right"]),
        ),
        "cohorts_by_minimum_sermons": depth_stability,
        "profiles": profiles,
        "interpretation": {
            "recommendations_are_advisory": True,
            "feature_schema_changed": False,
            "comparison_or_ranking_performed": False,
            "aggregate_deletion_variance_is_not_sermon_variance": True,
            "cohort_summaries_are_not_learning_curves": True,
            "certified_comparison_features": [],
            "primary_profile_estimates_are_pooled_word_weighted": True,
            "manual_inspection_included": False,
            "null_values_mean_insufficient_evidence": True,
            "minimum_profiles_for_correlation_flag": MIN_CORRELATION_PROFILES,
            "minimum_profiles_for_outlier_flag": MIN_OUTLIER_PROFILES,
            "strong_correlation_threshold": STRONG_CORRELATION_THRESHOLD,
            "high_correlation_threshold": HIGH_CORRELATION_THRESHOLD,
        },
        "metadata_coverage": {
            "dated_sermons": sum(
                profile["dated_sermon_count"] for profile in profiles
            ),
            "total_sermons": sum(profile["sermon_count"] for profile in profiles),
            "profiles_eligible_for_date_split": sum(
                profile["dated_sermon_count"] >= 4 for profile in profiles
            ),
            "multi_source_profiles": sum(
                profile["source_count"] >= 2 for profile in profiles
            ),
        },
    }
    snapshot, created = database.add_population_analysis_snapshot(
        analyzer_version=analyzer_version,
        profile_analyzer_key=PROFILE_ANALYZER_KEY,
        profile_analyzer_version=PROFILE_ANALYZER_VERSION,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        eligibility_policy_json=_json(policy.payload()),
        input_fingerprint=fingerprint,
        report_json=_json(report),
        inputs=inputs,
    )
    return PopulationSnapshotOutcome(snapshot=snapshot, created=created, report=report)


def load_population_snapshot_report(
    database: Database, snapshot_id: int | None = None
) -> tuple[PopulationAnalysisSnapshot, dict[str, object]]:
    snapshot = (
        database.get_population_analysis_snapshot(snapshot_id)
        if snapshot_id is not None
        else database.get_latest_population_analysis_snapshot_for_analyzer(
            POPULATION_ANALYZER_VERSION
        )
    )
    if snapshot is None:
        raise ValueError("No population analysis snapshot is available")
    return snapshot, json.loads(snapshot.report_json)
