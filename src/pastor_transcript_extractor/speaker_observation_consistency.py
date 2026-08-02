from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.speaker_pair_diagnostics import (
    CachedSpan,
    EmbeddingBackend,
    EmbeddingCache,
    analyze_cached_observation_consistency,
)


CONSISTENCY_REPORT_VERSION = "speaker_observation_consistency_v1"
REVIEWED_QUALIFICATIONS = {
    "qualified_single_speaker",
    "multiple_speakers",
    "invalid_audio",
}


@dataclass(frozen=True, slots=True)
class ReviewedObservationExample:
    input_fingerprint: str
    youtube_video_id: str
    qualification: str
    clips: tuple[CachedSpan, ...]
    review_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConsistencyScoreIndex:
    scores: Mapping[str, float]
    report_sha256: str | None


@dataclass(frozen=True, slots=True)
class DiscoveryConsistencyPolicySpec:
    policy_version: str
    feature: str
    strong_minimum: float
    review_status: str
    artifact_sha256: str
    calibration_report_sha256: str
    automatic_qualification_allowed: bool
    registry_mutation_allowed: bool


def load_discovery_consistency_policy(
    path: Path,
) -> DiscoveryConsistencyPolicySpec:
    resolved = path.expanduser().resolve()
    raw = resolved.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("discovery consistency policy must be a JSON object")
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported discovery consistency policy schema")
    if payload.get("purpose") != "shadow_discovery_nomination_tiering":
        raise ValueError("unsupported discovery consistency policy purpose")
    review_status = str(payload.get("review_status", ""))
    if review_status not in {"experimental_candidate", "approved"}:
        raise ValueError(
            "discovery consistency policy must be approved or experimental"
        )
    feature = str(payload.get("feature", ""))
    if feature != "weakest_clip_coherence":
        raise ValueError("unsupported discovery consistency feature")
    strong_minimum = payload.get("strong_minimum")
    if (
        isinstance(strong_minimum, bool)
        or not isinstance(strong_minimum, (int, float))
        or not math.isfinite(float(strong_minimum))
        or not -1.0 <= float(strong_minimum) <= 1.0
    ):
        raise ValueError("discovery consistency threshold is invalid")
    calibration = payload.get("calibration")
    if not isinstance(calibration, Mapping):
        raise ValueError("discovery consistency calibration is missing")
    report_sha256 = calibration.get("report_sha256")
    if not isinstance(report_sha256, str) or len(report_sha256) != 64:
        raise ValueError("discovery consistency calibration hash is invalid")
    automatic_allowed = payload.get("automatic_qualification_allowed") is True
    registry_allowed = payload.get("registry_mutation_allowed") is True
    if review_status != "approved" and (automatic_allowed or registry_allowed):
        raise ValueError("experimental consistency policy cannot mutate state")
    return DiscoveryConsistencyPolicySpec(
        policy_version=str(payload.get("policy_version", "")),
        feature=feature,
        strong_minimum=float(strong_minimum),
        review_status=review_status,
        artifact_sha256=hashlib.sha256(raw).hexdigest(),
        calibration_report_sha256=report_sha256,
        automatic_qualification_allowed=automatic_allowed,
        registry_mutation_allowed=registry_allowed,
    )


def collect_reviewed_observation_examples(
    *,
    drafts: Sequence[Mapping[str, Any]],
    reviews: Sequence[Mapping[str, Any]],
) -> tuple[tuple[ReviewedObservationExample, ...], tuple[dict[str, Any], ...]]:
    drafts_by_pair = {
        str(draft["pair_id"]): draft
        for draft in drafts
        if draft.get("pair_id") and draft.get("draft_id")
    }
    records: dict[str, list[tuple[str, str, tuple[CachedSpan, ...], str]]] = {}
    for review in reviews:
        pair_id = str(review.get("pair_id", ""))
        draft = drafts_by_pair.get(pair_id)
        if (
            draft is None
            or review.get("draft_id") != draft.get("draft_id")
            or not isinstance(review.get("qualification"), Mapping)
        ):
            continue
        for label in ("A", "B"):
            qualification = review["qualification"].get(label)
            if qualification not in REVIEWED_QUALIFICATIONS:
                continue
            source_key = (
                draft.get("presentation", {})
                .get(label, {})
                .get("source_key")
            )
            observation = draft.get("observations", {}).get(source_key)
            if not isinstance(observation, Mapping):
                continue
            fingerprint = observation.get("input_fingerprint")
            video_id = observation.get("youtube_video_id")
            if not isinstance(fingerprint, str) or not isinstance(video_id, str):
                continue
            clips = _cached_spans(observation.get("clips"), fingerprint)
            if len(clips) < 3:
                continue
            records.setdefault(fingerprint, []).append(
                (
                    str(qualification),
                    video_id,
                    clips,
                    str(review.get("review_event_id", "")),
                )
            )

    examples: list[ReviewedObservationExample] = []
    conflicts: list[dict[str, Any]] = []
    for fingerprint, values in sorted(records.items()):
        qualifications = sorted({value[0] for value in values})
        if len(qualifications) != 1:
            conflicts.append(
                {
                    "input_fingerprint": fingerprint,
                    "qualifications": qualifications,
                    "review_event_ids": sorted(
                        value[3] for value in values if value[3]
                    ),
                }
            )
            continue
        first = values[0]
        examples.append(
            ReviewedObservationExample(
                input_fingerprint=fingerprint,
                youtube_video_id=first[1],
                qualification=first[0],
                clips=first[2],
                review_event_ids=tuple(
                    sorted({value[3] for value in values if value[3]})
                ),
            )
        )
    return tuple(examples), tuple(conflicts)


def build_observation_consistency_plan(
    *,
    examples: Sequence[ReviewedObservationExample],
    conflicts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    counts = {
        qualification: sum(
            example.qualification == qualification
            for example in examples
        )
        for qualification in sorted(REVIEWED_QUALIFICATIONS)
    }
    return {
        "schema_version": 1,
        "report_version": CONSISTENCY_REPORT_VERSION,
        "purpose": "threshold_free_observation_consistency_calibration",
        "reviewed_example_count": len(examples),
        "qualification_counts": counts,
        "conflict_count": len(conflicts),
        "conflicts": list(conflicts),
        "automatic_qualification_allowed": False,
        "registry_mutation_allowed": False,
    }


def evaluate_observation_consistency_examples(
    *,
    examples: Sequence[ReviewedObservationExample],
    conflicts: Sequence[Mapping[str, Any]],
    embedding_cache: EmbeddingCache,
    backend: EmbeddingBackend,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for example in examples:
        analysis = analyze_cached_observation_consistency(
            spans=example.clips,
            embedding_cache=embedding_cache,
            backend=backend,
        )
        cases.append(
            {
                "input_fingerprint": example.input_fingerprint,
                "youtube_video_id": example.youtube_video_id,
                "reviewed_qualification": example.qualification,
                "review_event_ids": list(example.review_event_ids),
                "analysis": analysis,
            }
        )
    feature_summary = _feature_summary(cases)
    report = {
        **build_observation_consistency_plan(
            examples=examples,
            conflicts=conflicts,
        ),
        "model": asdict(backend.spec),
        "scored_case_count": sum(
            case["analysis"].get("status") == "scored"
            for case in cases
        ),
        "feature_summary": feature_summary,
        "cases": cases,
    }
    report["report_sha256"] = _sha256_json(report)
    return report


def load_consistency_score_index(path: Path) -> ConsistencyScoreIndex:
    if not path.exists():
        return ConsistencyScoreIndex({}, None)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("report_version") != CONSISTENCY_REPORT_VERSION:
        raise ValueError("unsupported observation consistency report")
    report_sha256 = payload.get("report_sha256")
    content = dict(payload)
    content.pop("report_sha256", None)
    if (
        not isinstance(report_sha256, str)
        or report_sha256 != _sha256_json(content)
    ):
        raise ValueError("observation consistency report checksum mismatch")
    scores: dict[str, float] = {}
    for case in payload.get("cases", []):
        if not isinstance(case, Mapping):
            continue
        fingerprint = case.get("input_fingerprint")
        metrics = case.get("analysis", {}).get("metrics", {})
        value = metrics.get("weakest_clip_coherence")
        if (
            isinstance(fingerprint, str)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
        ):
            scores[fingerprint] = float(value)
    return ConsistencyScoreIndex(scores, report_sha256)


def write_observation_consistency_report(
    path: Path,
    report: Mapping[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _cached_spans(
    value: object,
    fingerprint: str,
) -> tuple[CachedSpan, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    spans: list[CachedSpan] = []
    for clip in value:
        if not isinstance(clip, Mapping):
            continue
        try:
            spans.append(
                CachedSpan(
                    observation_fingerprint=fingerprint,
                    start_seconds=float(clip["start_seconds"]),
                    end_seconds=float(clip["end_seconds"]),
                    wav_path=str(clip["wav_path"]),
                    wav_sha256=str(clip["wav_sha256"]),
                    duration_seconds=float(clip["duration_seconds"]),
                    rms_dbfs=float(clip["rms_dbfs"]),
                    clipped_fraction=float(clip["clipped_fraction"]),
                    cache_hit=True,
                    non_silent_fraction=(
                        float(clip["non_silent_fraction"])
                        if clip.get("non_silent_fraction") is not None
                        else None
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(spans)


def _feature_summary(
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    features = (
        "weakest_clip_coherence",
        "pairwise_spread",
    )
    summary: dict[str, Any] = {}
    for qualification in sorted(REVIEWED_QUALIFICATIONS):
        values_by_feature: dict[str, list[float]] = {
            feature: [] for feature in features
        }
        for case in cases:
            if case.get("reviewed_qualification") != qualification:
                continue
            metrics = case.get("analysis", {}).get("metrics", {})
            for feature in features:
                value = metrics.get(feature)
                if isinstance(value, (int, float)):
                    values_by_feature[feature].append(float(value))
        summary[qualification] = {
            feature: _distribution(values)
            for feature, values in values_by_feature.items()
        }
    return summary


def _distribution(values: Sequence[float]) -> dict[str, float | int] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "median": statistics.median(ordered),
        "max": ordered[-1],
    }


def _sha256_json(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
