from __future__ import annotations

from dataclasses import dataclass
import hashlib
from itertools import combinations
import json
import math
import statistics

from pastor_transcript_extractor.models import PopulationAnalysisSnapshot
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.structure_analysis import (
    FEATURE_NAMES,
    PROFILE_STRUCTURE_ANALYZER_KEY,
    PROFILE_STRUCTURE_ANALYZER_VERSION,
)
from pastor_transcript_extractor.structure_readiness import build_structure_readiness


STRUCTURE_POPULATION_ANALYZER_VERSION = "structure-population-diagnostics@1"
FEATURE_SCHEMA_VERSION = "deterministic-structure-profile-vector@1"
POLICY_VERSION = "structure-current-profiles@1"
SOURCE_SENSITIVE_FEATURES = {
    "transcript_tokens_per_minute",
    "question_mark_segments_per_1000_words",
}
MIN_CORRELATION_PROFILES = 10


@dataclass(frozen=True, slots=True)
class StructurePopulationOutcome:
    snapshot: PopulationAnalysisSnapshot
    created: bool
    report: dict[str, object]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _distribution(values: list[float], count: int) -> dict[str, object]:
    median = statistics.median(values) if values else None
    return {
        "observed_count": len(values),
        "missing_count": count - len(values),
        "missing_fraction": round((count - len(values)) / count, 6) if count else None,
        "zero_count": sum(value == 0 for value in values),
        "minimum": min(values) if values else None,
        "q1": _quantile(values, 0.25),
        "median": median,
        "q3": _quantile(values, 0.75),
        "maximum": max(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
        "standard_deviation": statistics.pstdev(values) if values else None,
        "median_absolute_deviation": (
            statistics.median(abs(value - median) for value in values)
            if values and median is not None else None
        ),
    }


def _scale(distribution: dict[str, object]) -> float | None:
    q1, q3 = _number(distribution["q1"]), _number(distribution["q3"])
    if q1 is not None and q3 is not None and q3 > q1:
        return q3 - q1
    sd = _number(distribution["standard_deviation"])
    return sd if sd is not None and sd > 0 else None


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    left_sd, right_sd = statistics.pstdev(left), statistics.pstdev(right)
    if not left_sd or not right_sd:
        return None
    lm, rm = statistics.fmean(left), statistics.fmean(right)
    return round(statistics.fmean((a - lm) * (b - rm) for a, b in zip(left, right)) / (left_sd * right_sd), 6)


def _profile_measurements(database: Database, run_id: int) -> dict[str, object]:
    return {item.metric_key: json.loads(item.value_json) for item in database.list_speaker_profile_analysis_measurements(run_id)}


def _sermon_vector(database: Database, run_id: int) -> dict[str, object]:
    values = {item.metric_key: json.loads(item.value_json) for item in database.list_sermon_analysis_measurements(run_id)}
    vector = values.get("feature_vector")
    if not isinstance(vector, dict) or vector.get("schema_version") != 1 or not isinstance(vector.get("by_name"), dict):
        raise ValueError(f"Structure run #{run_id} has an incompatible feature vector")
    return vector["by_name"]


def build_structure_population_snapshot(
    database: Database, *, minimum_sermons: int = 3
) -> StructurePopulationOutcome:
    if minimum_sermons < 2:
        raise ValueError("Structure population diagnostics require at least two sermons")
    readiness = build_structure_readiness(database)
    eligible = [
        item for item in readiness.profiles
        if item.sermon_count >= minimum_sermons and item.aggregate_state == "current" and item.aggregate_run_id is not None
    ]
    inputs = sorted((item.profile_id, int(item.aggregate_run_id)) for item in eligible)
    if not inputs:
        raise ValueError("No current eligible structure profile analyses are available")
    fingerprint = _fingerprint({
        "analyzer_version": STRUCTURE_POPULATION_ANALYZER_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "inputs": inputs,
        "minimum_sermons": minimum_sermons,
        "policy_version": POLICY_VERSION,
        "profile_analyzer_key": PROFILE_STRUCTURE_ANALYZER_KEY,
        "profile_analyzer_version": PROFILE_STRUCTURE_ANALYZER_VERSION,
    })
    existing = database.get_population_analysis_snapshot_by_fingerprint(fingerprint)
    if existing is not None:
        return StructurePopulationOutcome(existing, False, json.loads(existing.report_json))
    profiles = []
    runs_by_id = {run.id: run for run in database.list_sermon_analysis_runs()}
    videos_by_id = {video.id: video for video in database.list_videos()}
    for profile_id, run_id in inputs:
        measurements = _profile_measurements(database, run_id)
        summaries = measurements.get("feature_summaries")
        if not isinstance(summaries, dict):
            raise ValueError(f"Profile structure run #{run_id} lacks feature summaries")
        sermon_run_ids = database.list_speaker_profile_analysis_input_run_ids(run_id)
        rows = [_sermon_vector(database, sermon_run_id) for sermon_run_id in sermon_run_ids]
        values = {name: _number(summaries[name]["mean"]) for name in FEATURE_NAMES}
        loo = {}
        for name in FEATURE_NAMES:
            observed = [_number(row.get(name)) for row in rows]
            observed = [value for value in observed if value is not None]
            center = values[name]
            loo_values = [statistics.fmean(observed[:i] + observed[i + 1:]) for i in range(len(observed)) if len(observed) > 1]
            loo[name] = max((abs(value - center) for value in loo_values), default=None) if center is not None else None
        profile = database.get_speaker_profile(profile_id)
        videos = [videos_by_id[runs_by_id[run_id].video_id] for run_id in sermon_run_ids]
        profiles.append({
            "profile_id": profile_id,
            "display_label": profile.display_label if profile else None,
            "profile_analysis_run_id": run_id,
            "sermon_run_ids": sermon_run_ids,
            "sermon_count": len(rows),
            "source_count": len({video.source_id for video in videos}),
            "dated_sermon_count": sum(video.published_at is not None for video in videos),
            "values": values,
            "leave_one_out_max_absolute_delta": loo,
            "sermon_values": rows,
        })
    distributions = {
        name: _distribution([profile["values"][name] for profile in profiles if profile["values"][name] is not None], len(profiles))
        for name in FEATURE_NAMES
    }
    diagnostics = {}
    for name in FEATURE_NAMES:
        scale = _scale(distributions[name])
        normalized_loo = [
            profile["leave_one_out_max_absolute_delta"][name] / scale
            for profile in profiles
            if scale and profile["leave_one_out_max_absolute_delta"][name] is not None
        ]
        median_loo = statistics.median(normalized_loo) if normalized_loo else None
        stability = "high" if median_loo is not None and median_loo <= 0.15 else "moderate" if median_loo is not None and median_loo <= 0.35 else "low" if median_loo is not None else "not_evaluable"
        within = [
            statistics.pvariance(observed)
            for profile in profiles
            if len(observed := [_number(row.get(name)) for row in profile["sermon_values"] if _number(row.get(name)) is not None]) >= 2
        ]
        profile_values = [profile["values"][name] for profile in profiles if profile["values"][name] is not None]
        between_variance = statistics.pvariance(profile_values) if len(profile_values) >= 2 else None
        within_variance = statistics.fmean(within) if within else None
        size_pairs = [(profile["sermon_count"], profile["values"][name]) for profile in profiles if profile["values"][name] is not None]
        reasons = []
        if name in SOURCE_SENSITIVE_FEATURES:
            reasons.append("known_source_sensitive_proxy")
        if (distributions[name]["missing_fraction"] or 0) > 0.25:
            reasons.append("high_missingness")
        if stability in {"low", "not_evaluable"}:
            reasons.append("insufficient_leave_one_out_stability")
        diagnostics[name] = {
            "distribution": distributions[name],
            "leave_one_out": {"median_max_delta_in_population_iqr_units": median_loo, "stability": stability},
            "between_profile_variance": between_variance,
            "mean_within_profile_variance": within_variance,
            "between_to_within_variance_ratio": (round(between_variance / within_variance, 6) if between_variance is not None and within_variance else None),
            "corpus_size_pearson": _pearson([float(a) for a, _ in size_pairs], [float(b) for _, b in size_pairs]),
            "recommendation": "diagnostic_only" if reasons else "candidate_for_further_review",
            "reasons": reasons,
        }
    correlations = []
    for left, right in combinations(FEATURE_NAMES, 2):
        pairs = [(profile["values"][left], profile["values"][right]) for profile in profiles if profile["values"][left] is not None and profile["values"][right] is not None]
        value = (
            _pearson([float(a) for a, _ in pairs], [float(b) for _, b in pairs])
            if len(pairs) >= MIN_CORRELATION_PROFILES else None
        )
        if value is not None and abs(value) >= 0.75:
            correlations.append({"left": left, "right": right, "pearson": value, "profile_count": len(pairs)})
    correlated = {name: [] for name in FEATURE_NAMES}
    for item in correlations:
        correlated[item["left"]].append(item["right"])
        correlated[item["right"]].append(item["left"])
    for name, related in correlated.items():
        diagnostics[name]["strongly_correlated_with"] = sorted(related)
        if related:
            diagnostics[name]["reasons"].append("strong_pairwise_correlation")
            if diagnostics[name]["recommendation"] != "diagnostic_only":
                diagnostics[name]["recommendation"] = "review_redundancy"
    report = {
        "schema_version": 1,
        "population": {"profile_count": len(profiles), "sermon_count": sum(profile["sermon_count"] for profile in profiles), "minimum_sermons": minimum_sermons},
        "feature_names": list(FEATURE_NAMES),
        "feature_diagnostics": diagnostics,
        "strong_correlations": correlations,
        "stability_policy": {
            "scale": "population interquartile range with standard-deviation fallback",
            "high_maximum_median_loo_delta": 0.15,
            "moderate_maximum_median_loo_delta": 0.35,
            "minimum_profiles_for_pairwise_correlation": MIN_CORRELATION_PROFILES,
        },
        "metadata_coverage": {
            "dated_sermons": sum(profile["dated_sermon_count"] for profile in profiles),
            "total_sermons": sum(profile["sermon_count"] for profile in profiles),
            "multi_source_profiles": sum(profile["source_count"] >= 2 for profile in profiles),
        },
        "profiles": [{key: value for key, value in profile.items() if key != "sermon_values"} for profile in profiles],
        "interpretation": "Advisory deterministic diagnostics only; no comparison schema, PCA, ranking, or clustering changed.",
    }
    snapshot, created = database.add_population_analysis_snapshot(
        analyzer_version=STRUCTURE_POPULATION_ANALYZER_VERSION,
        profile_analyzer_key=PROFILE_STRUCTURE_ANALYZER_KEY,
        profile_analyzer_version=PROFILE_STRUCTURE_ANALYZER_VERSION,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        eligibility_policy_json=_json({"version": POLICY_VERSION, "minimum_sermons": minimum_sermons}),
        input_fingerprint=fingerprint,
        report_json=_json(report),
        inputs=inputs,
    )
    return StructurePopulationOutcome(snapshot, created, json.loads(snapshot.report_json))


def load_structure_population_snapshot(
    database: Database, snapshot_id: int | None = None
) -> tuple[PopulationAnalysisSnapshot, dict[str, object]]:
    snapshot = database.get_population_analysis_snapshot(snapshot_id) if snapshot_id is not None else database.get_latest_population_analysis_snapshot_for_analyzer(STRUCTURE_POPULATION_ANALYZER_VERSION)
    if snapshot is None or snapshot.analyzer_version != STRUCTURE_POPULATION_ANALYZER_VERSION:
        raise ValueError("No matching structure population snapshot is available")
    return snapshot, json.loads(snapshot.report_json)
