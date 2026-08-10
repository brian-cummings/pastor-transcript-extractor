from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

from pastor_transcript_extractor.models import SpeakerProfileAnalysisRun
from pastor_transcript_extractor.profile_analysis import resolve_profile_sermon_scope
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.style_analysis import (
    STYLE_ANALYZER_KEY,
    STYLE_ANALYZER_VERSION,
    STYLE_DIMENSIONS,
)


STYLE_PROFILE_ANALYZER_KEY = "profile-style-evidence"
STYLE_PROFILE_ANALYZER_VERSION = "1"
STYLE_PROFILE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class StyleProfileOutcome:
    run: SpeakerProfileAnalysisRun
    created: bool


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _measurements(database: Database, run_id: int) -> dict[str, object]:
    return {
        item.metric_key: json.loads(item.value_json)
        for item in database.list_sermon_analysis_measurements(run_id)
    }


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator > 0 else None


def _consistency(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if mean <= 0:
        return None
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return round(1 / (1 + math.sqrt(variance) / mean), 6)


def build_profile_style_analysis(
    database: Database,
    profile_id: int,
    *,
    analyzer_version: str = STYLE_PROFILE_ANALYZER_VERSION,
    sermon_analyzer_version: str = STYLE_ANALYZER_VERSION,
) -> StyleProfileOutcome:
    if not analyzer_version.strip():
        raise ValueError("Style profile analyzer version must not be blank")
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

    inputs: list[tuple[int, int]] = []
    sermon_rows: list[dict[str, object]] = []
    total_words = 0
    total_duration = 0.0
    total_analyzed_duration = 0.0
    for video in scope.videos:
        run = database.get_latest_sermon_analysis_run(
            video.id,
            STYLE_ANALYZER_KEY,
            analyzer_version=sermon_analyzer_version,
        )
        if run is None:
            continue
        inputs.append((run.id, video.id))
        values = _measurements(database, run.id)
        dimensions = values.get("style_dimension_measurements")
        if not isinstance(dimensions, dict):
            continue
        words = values.get("word_count")
        duration = values.get("sermon_duration_seconds")
        analyzed_duration = values.get("semantic_analyzed_duration_seconds")
        if isinstance(words, int) and not isinstance(words, bool):
            total_words += words
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            total_duration += float(duration)
        if isinstance(analyzed_duration, (int, float)) and not isinstance(
            analyzed_duration, bool
        ):
            total_analyzed_duration += float(analyzed_duration)
        sermon_rows.append(
            {
                "video_id": video.id,
                "youtube_video_id": video.youtube_video_id,
                "style_analysis_run_id": run.id,
                "word_count": words,
                "sermon_duration_seconds": duration,
                "semantic_analysis_coverage_fraction": values.get(
                    "semantic_analysis_coverage_fraction"
                ),
                "dimensions": dimensions,
                "model_provenance": values.get("model_provenance"),
                "prompt_provenance": values.get("prompt_provenance"),
            }
        )

    sermons_attached = len(scope.videos)
    sermons_analyzed = len(sermon_rows)
    input_provenance = {
        json.dumps(
            {
                "model_provenance": row.get("model_provenance"),
                "prompt_provenance": row.get("prompt_provenance"),
            },
            sort_keys=True,
        )
        for row in sermon_rows
    }
    if len(input_provenance) > 1:
        raise ValueError(
            "Style profile inputs use mixed model or prompt configurations; "
            "finish rerunning style analysis for the profile before aggregation"
        )
    dimension_profiles: dict[str, dict[str, object]] = {}
    for dimension in STYLE_DIMENSIONS:
        entries = [
            row["dimensions"].get(dimension, {})
            for row in sermon_rows
            if isinstance(row.get("dimensions"), dict)
        ]
        evidence_counts = [
            int(entry.get("evidence_count", 0))
            for entry in entries
            if isinstance(entry, dict)
        ]
        durations = [
            float(entry.get("duration_seconds", 0.0))
            for entry in entries
            if isinstance(entry, dict)
        ]
        coverages = [
            float(entry.get("sermon_duration_coverage_fraction", 0.0))
            for entry in entries
            if isinstance(entry, dict)
        ]
        sustained_counts = [
            int(entry.get("sustained_run_count", 0))
            for entry in entries
            if isinstance(entry, dict)
        ]
        corroborated_counts = [
            int(entry.get("scripture_corroborated_evidence_count", 0))
            for entry in entries
            if isinstance(entry, dict)
        ]
        evidence_count = sum(evidence_counts)
        duration_seconds = sum(durations)
        dimension_profiles[dimension] = {
            "operational_definition": STYLE_DIMENSIONS[dimension],
            "evidence_count": evidence_count,
            "evidence_per_analyzed_sermon": _ratio(
                evidence_count, sermons_analyzed
            ),
            "evidence_per_1000_words": (
                round(1000 * evidence_count / total_words, 6)
                if total_words
                else None
            ),
            "duration_seconds": round(duration_seconds, 3),
            "duration_coverage_fraction": _ratio(
                duration_seconds, total_duration
            ),
            "sermons_with_evidence": sum(count > 0 for count in evidence_counts),
            "sermons_with_evidence_fraction": _ratio(
                sum(count > 0 for count in evidence_counts), sermons_analyzed
            ),
            "mean_sermon_coverage_fraction": (
                round(sum(coverages) / len(coverages), 6)
                if coverages
                else None
            ),
            "sermon_coverage_consistency": _consistency(coverages),
            "sustained_run_count": sum(sustained_counts),
            "scripture_corroborated_evidence_count": sum(corroborated_counts),
        }

    profile_values: list[tuple[str, object, str | None]] = [
        ("sermons_attached", sermons_attached, "sermons"),
        ("sermons_analyzed", sermons_analyzed, "sermons"),
        (
            "sermons_missing_style_analysis",
            sermons_attached - sermons_analyzed,
            "sermons",
        ),
        ("total_sermon_words", total_words, "words"),
        ("total_sermon_duration_seconds", round(total_duration, 3), "seconds"),
        (
            "semantic_analyzed_duration_seconds",
            round(total_analyzed_duration, 3),
            "seconds",
        ),
        (
            "semantic_analysis_coverage_fraction",
            _ratio(total_analyzed_duration, total_duration),
            None,
        ),
        ("style_dimension_profiles", dimension_profiles, None),
        ("sermon_style_support", sermon_rows, None),
        (
            "semantic_analysis_provenance",
            json.loads(next(iter(input_provenance))) if input_provenance else None,
            None,
        ),
        (
            "coverage_diagnostics",
            {
                "sermons_attached": sermons_attached,
                "sermons_analyzed": sermons_analyzed,
                "sermons_missing_style_analysis": sermons_attached
                - sermons_analyzed,
                "insufficient_values_are_null": True,
            },
            None,
        ),
    ]
    measurements = [
        (key, json.dumps(value, sort_keys=True), unit)
        for key, value, unit in profile_values
    ]
    input_fingerprint = _sha256(
        {
            "analyzer_key": STYLE_PROFILE_ANALYZER_KEY,
            "analyzer_version": analyzer_version,
            "membership_fingerprint": membership_fingerprint,
            "profile_id": scope.profile_id,
            "schema_version": STYLE_PROFILE_SCHEMA_VERSION,
            "style_analysis_run_ids": sorted(run_id for run_id, _ in inputs),
        }
    )
    run, created = database.add_speaker_profile_analysis_run(
        profile_id=scope.profile_id,
        analyzer_key=STYLE_PROFILE_ANALYZER_KEY,
        analyzer_version=analyzer_version,
        membership_fingerprint=membership_fingerprint,
        input_fingerprint=input_fingerprint,
        inputs=inputs,
        measurements=measurements,
    )
    return StyleProfileOutcome(run, created)
