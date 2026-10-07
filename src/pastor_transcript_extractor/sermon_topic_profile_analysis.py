"""Cached sermon and equal-sermon profile projections for TypeSafe topics."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from pastor_transcript_extractor.models import (
    SermonAnalysisRun,
    SpeakerProfileAnalysisRun,
    Video,
)
from pastor_transcript_extractor.profile_analysis import (
    profile_membership_fingerprint,
    resolve_profile_sermon_scope,
)
from pastor_transcript_extractor.sermon_topic_projection import (
    TopicProfileProjectionGate,
    assess_topic_profile_projection,
)
from pastor_transcript_extractor.sermon_topics import (
    TOPICS,
    resolve_topic_analysis_artifact,
)
from pastor_transcript_extractor.storage import Database


TOPIC_SERMON_ANALYZER_KEY = "typesafe-topic-projection"
TOPIC_SERMON_ANALYZER_VERSION = "1"
TOPIC_SERMON_SCHEMA_VERSION = 1
TOPIC_PROFILE_ANALYZER_KEY = "profile-typesafe-topic-evidence"
TOPIC_PROFILE_ANALYZER_VERSION = "1"
TOPIC_PROFILE_SCHEMA_VERSION = 1
TOPIC_PROFILE_AGGREGATION_POLICY_VERSION = (
    "equal-sermon-support-primary-expected-sensitivity-v1"
)
TOPIC_PROFILE_ANALYTICAL_STATUS = "exploratory_stage4_repeatability_pending"


@dataclass(frozen=True, slots=True)
class TopicSermonAnalysisOutcome:
    run: SermonAnalysisRun
    created: bool


@dataclass(frozen=True, slots=True)
class TopicProfileAnalysisOutcome:
    run: SpeakerProfileAnalysisRun
    created: bool


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"TypeSafe topic {label} is unavailable or malformed")
    return value


def _number(value: object, *, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"TypeSafe topic {label} is unavailable or malformed")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"TypeSafe topic {label} must be between 0 and 1")
    return result


def _read_topic_analysis(
    gate: TopicProfileProjectionGate,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if gate.source_path is None:
        raise ValueError("TypeSafe topic source artifact is unavailable")
    source_path = Path(gate.source_path)
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Cannot read TypeSafe topic source artifact: {source_path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise ValueError("TypeSafe topic source artifact is malformed")
    classification = _mapping(payload.get("classification"), label="classification")
    analysis = resolve_topic_analysis_artifact(classification)
    projection = _mapping(
        analysis.get("sermon_projection"),
        label="sermon projection",
    )
    return analysis, projection


def _projection_measurements(
    projection: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    raw_measurements = _mapping(
        projection.get("measurements"),
        label="sermon projection measurements",
    )
    if set(raw_measurements) != set(TOPICS):
        missing = sorted(set(TOPICS) - set(raw_measurements))
        extra = sorted(set(raw_measurements) - set(TOPICS))
        raise ValueError(
            "TypeSafe topic sermon projection has the wrong topic inventory "
            f"(missing={missing}, extra={extra})"
        )
    result: dict[str, dict[str, Any]] = {}
    for topic in TOPICS:
        raw = _mapping(raw_measurements[topic], label=f"measurement {topic}")
        expected = _number(
            raw.get("mean_normalized_expected_prominence"),
            label=f"expected prominence for {topic}",
        )
        support = _number(
            raw.get("mean_supporting_or_above_probability"),
            label=f"support probability for {topic}",
        )
        representative = raw.get("representative_blocks")
        counterevidence = raw.get("counterevidence_blocks")
        if not isinstance(representative, list) or not isinstance(
            counterevidence, list
        ):
            raise ValueError(
                f"TypeSafe topic evidence links for {topic} are malformed"
            )
        result[topic] = {
            "developed_emphasis_probability": support,
            "normalized_expected_prominence": expected,
            "representative_blocks": representative,
            "counterevidence_blocks": counterevidence,
        }
    return result


def _sermon_input_fingerprint(
    gate: TopicProfileProjectionGate,
    *,
    analyzer_version: str,
) -> str:
    if gate.topic_analysis_fingerprint is None:
        raise ValueError("TypeSafe topic analysis fingerprint is unavailable")
    return _sha256(
        {
            "analyzer_key": TOPIC_SERMON_ANALYZER_KEY,
            "analyzer_version": analyzer_version,
            "extraction_result_id": gate.extraction_result_id,
            "schema_version": TOPIC_SERMON_SCHEMA_VERSION,
            "topic_analysis_fingerprint": gate.topic_analysis_fingerprint,
            "video_id": gate.video_id,
        }
    )


def _evidence_rows(
    analysis: Mapping[str, Any],
    measurements: Mapping[str, Mapping[str, Any]],
) -> list[
    tuple[
        str,
        str,
        int | None,
        float | None,
        float | None,
        int | None,
        int | None,
        str,
        str,
    ]
]:
    raw_blocks = analysis.get("blocks")
    blocks = raw_blocks if isinstance(raw_blocks, list) else []
    blocks_by_id = {
        block.get("block_id"): block
        for block in blocks
        if isinstance(block, Mapping)
    }
    rows = []
    for topic, values in measurements.items():
        for evidence_kind, key in (
            ("representative", "representative_blocks"),
            ("counterevidence", "counterevidence_blocks"),
        ):
            for rank, link in enumerate(values[key]):
                if not isinstance(link, Mapping):
                    raise ValueError(
                        f"TypeSafe topic evidence link for {topic} is malformed"
                    )
                block_id = link.get("block_id")
                block = blocks_by_id.get(block_id)
                if not isinstance(block, Mapping):
                    raise ValueError(
                        f"TypeSafe topic evidence block {block_id!r} is unavailable"
                    )
                start = block.get("start_seconds")
                end = block.get("end_seconds")
                excerpt = block.get("target_text")
                if not isinstance(excerpt, str):
                    raise ValueError(
                        f"TypeSafe topic evidence block {block_id!r} has no text"
                    )
                payload = {
                    "block_id": block_id,
                    "content_role": block.get("content_role"),
                    "projection_eligibility": block.get("projection_eligibility"),
                    "rank": rank,
                    "score": link.get("score"),
                    "supporting_or_above_probability": link.get(
                        "supporting_or_above_probability"
                    ),
                    "topic": topic,
                }
                rows.append(
                    (
                        f"topic_{evidence_kind}",
                        f"{topic}:{evidence_kind}:{rank}:{block_id}",
                        None,
                        float(start) if isinstance(start, (int, float)) else None,
                        float(end) if isinstance(end, (int, float)) else None,
                        None,
                        None,
                        excerpt,
                        _canonical_json(payload),
                    )
                )
    return rows


def materialize_topic_sermon_analysis(
    database: Database,
    video: Video,
    *,
    analyzer_version: str = TOPIC_SERMON_ANALYZER_VERSION,
) -> TopicSermonAnalysisOutcome:
    """Persist a deterministic projection of already-cached topic evidence."""
    if not analyzer_version.strip():
        raise ValueError("Topic sermon analyzer version must not be blank")
    gate = assess_topic_profile_projection(database, video)
    if not gate.eligible:
        reasons = ", ".join(gate.reason_codes) or "unknown"
        raise ValueError(
            f"Video {video.youtube_video_id} is not eligible for topic projection: "
            f"{reasons}"
        )
    analysis, projection = _read_topic_analysis(gate)
    measurements = _projection_measurements(projection)
    question_pack_version = analysis.get("question_pack_version")
    projection_policy_version = projection.get("policy_version")
    eligible_seconds = projection.get("eligible_sermon_seconds")
    if not isinstance(question_pack_version, str) or not question_pack_version:
        raise ValueError("TypeSafe topic question-pack version is unavailable")
    if (
        not isinstance(projection_policy_version, str)
        or not projection_policy_version
    ):
        raise ValueError("TypeSafe topic projection policy version is unavailable")
    if not isinstance(eligible_seconds, (int, float)) or isinstance(
        eligible_seconds, bool
    ) or float(eligible_seconds) <= 0:
        raise ValueError("TypeSafe topic eligible-sermon duration is malformed")

    values: list[tuple[str, object, str | None]] = [
        ("topic_question_pack_version", question_pack_version, None),
        ("sermon_projection_policy_version", projection_policy_version, None),
        ("eligible_block_count", gate.eligible_block_count, "blocks"),
        ("eligible_sermon_seconds", round(float(eligible_seconds), 3), "seconds"),
        ("topic_measurements", measurements, None),
        (
            "measurement_policy",
            {
                "primary": "developed_emphasis_probability",
                "primary_source": "mean_supporting_or_above_probability",
                "sensitivity": "normalized_expected_prominence",
                "sensitivity_source": "mean_normalized_expected_prominence",
            },
            None,
        ),
        (
            "projection_provenance",
            {
                "extraction_result_id": gate.extraction_result_id,
                "gate_input_fingerprint": gate.input_fingerprint,
                "observation_id": gate.observation_id,
                "observation_input_fingerprint": gate.observation_input_fingerprint,
                "profile_id_at_materialization": gate.profile_id,
                "topic_analysis_fingerprint": gate.topic_analysis_fingerprint,
            },
            None,
        ),
    ]
    input_fingerprint = _sermon_input_fingerprint(
        gate,
        analyzer_version=analyzer_version,
    )
    assert gate.extraction_result_id is not None
    assert gate.source_path is not None
    assert gate.topic_analysis_fingerprint is not None
    run, created = database.add_sermon_analysis_run(
        video_id=video.id,
        extraction_result_id=gate.extraction_result_id,
        analyzer_key=TOPIC_SERMON_ANALYZER_KEY,
        analyzer_version=analyzer_version,
        source_kind="cached_typesafe_topic_analysis",
        source_path=gate.source_path,
        source_content_sha256=gate.topic_analysis_fingerprint,
        input_fingerprint=input_fingerprint,
        measurements=[
            (key, _canonical_json(value), unit) for key, value, unit in values
        ],
        evidence=_evidence_rows(analysis, measurements),
    )
    return TopicSermonAnalysisOutcome(run=run, created=created)


def load_topic_sermon_measurements(
    database: Database,
    run_id: int,
) -> dict[str, object]:
    """Load one immutable materialized topic run's decoded measurements."""
    return {
        measurement.metric_key: json.loads(measurement.value_json)
        for measurement in database.list_sermon_analysis_measurements(run_id)
    }


def _profile_evidence_links(
    sermon_rows: list[dict[str, Any]],
    topic: str,
    *,
    key: str,
    reverse: bool,
) -> list[dict[str, Any]]:
    candidates = []
    for row in sermon_rows:
        topic_values = row["topic_measurements"][topic]
        for link in topic_values[key]:
            if not isinstance(link, Mapping):
                continue
            candidates.append(
                {
                    "block_id": link.get("block_id"),
                    "score": link.get("score"),
                    "sermon_analysis_run_id": row["sermon_analysis_run_id"],
                    "supporting_or_above_probability": link.get(
                        "supporting_or_above_probability"
                    ),
                    "video_id": row["video_id"],
                    "youtube_video_id": row["youtube_video_id"],
                }
            )
    candidates.sort(
        key=lambda item: (
            float(item.get("supporting_or_above_probability") or 0.0),
            float(item.get("score") or 0.0),
            -int(item.get("video_id") or 0),
            -int(item.get("block_id") or 0),
        ),
        reverse=reverse,
    )
    return candidates[:3]


def build_profile_topic_analysis(
    database: Database,
    profile_id: int,
    *,
    analyzer_version: str = TOPIC_PROFILE_ANALYZER_VERSION,
    sermon_analyzer_version: str = TOPIC_SERMON_ANALYZER_VERSION,
) -> TopicProfileAnalysisOutcome:
    """Materialize an exploratory, equal-sermon topic profile from cached evidence."""
    if not analyzer_version.strip():
        raise ValueError("Topic profile analyzer version must not be blank")
    scope = resolve_profile_sermon_scope(database, profile_id)
    membership_fingerprint = profile_membership_fingerprint(database, scope)
    sermon_rows: list[dict[str, Any]] = []
    inputs: list[tuple[int, int]] = []
    blocked_sermons = []
    configurations: set[tuple[str, str]] = set()
    scope_gate_fingerprints = []

    for video in scope.videos:
        gate = assess_topic_profile_projection(database, video)
        scope_gate_fingerprints.append(
            {
                "gate_input_fingerprint": gate.input_fingerprint,
                "video_id": video.id,
            }
        )
        if not gate.eligible or gate.profile_id != scope.profile_id:
            reasons = list(gate.reason_codes)
            if gate.eligible and gate.profile_id != scope.profile_id:
                reasons.append("profile_membership_mismatch")
            blocked_sermons.append(
                {
                    "reason_codes": reasons,
                    "video_id": video.id,
                    "youtube_video_id": video.youtube_video_id,
                }
            )
            continue
        outcome = materialize_topic_sermon_analysis(
            database,
            video,
            analyzer_version=sermon_analyzer_version,
        )
        values = load_topic_sermon_measurements(database, outcome.run.id)
        question_pack = values.get("topic_question_pack_version")
        projection_policy = values.get("sermon_projection_policy_version")
        topic_measurements = values.get("topic_measurements")
        if (
            not isinstance(question_pack, str)
            or not isinstance(projection_policy, str)
            or not isinstance(topic_measurements, dict)
        ):
            raise ValueError(
                f"Video {video.youtube_video_id} has malformed materialized topic evidence"
            )
        configurations.add((question_pack, projection_policy))
        inputs.append((outcome.run.id, video.id))
        sermon_rows.append(
            {
                "eligible_block_count": values.get("eligible_block_count"),
                "eligible_sermon_seconds": values.get("eligible_sermon_seconds"),
                "sermon_analysis_run_id": outcome.run.id,
                "sermon_analysis_input_fingerprint": outcome.run.input_fingerprint,
                "topic_measurements": topic_measurements,
                "video_id": video.id,
                "youtube_video_id": video.youtube_video_id,
            }
        )

    if not sermon_rows:
        raise ValueError(
            f"Speaker profile {scope.profile_id} has no eligible cached TypeSafe "
            "topic projections"
        )
    if len(configurations) != 1:
        raise ValueError(
            "TypeSafe topic profile inputs use mixed question-pack or projection "
            "versions; refresh the profile's sermons before aggregation"
        )
    question_pack_version, projection_policy_version = next(iter(configurations))
    topic_profiles: dict[str, dict[str, Any]] = {}
    for topic in TOPICS:
        support_values = [
            _number(
                row["topic_measurements"][topic].get(
                    "developed_emphasis_probability"
                ),
                label=f"materialized support probability for {topic}",
            )
            for row in sermon_rows
        ]
        expected_values = [
            _number(
                row["topic_measurements"][topic].get(
                    "normalized_expected_prominence"
                ),
                label=f"materialized expected prominence for {topic}",
            )
            for row in sermon_rows
        ]
        topic_profiles[topic] = {
            "developed_emphasis_probability": round(
                sum(support_values) / len(support_values),
                6,
            ),
            "normalized_expected_prominence_sensitivity": round(
                sum(expected_values) / len(expected_values),
                6,
            ),
            "sermon_count": len(sermon_rows),
            "sermon_values": [
                {
                    "developed_emphasis_probability": support,
                    "normalized_expected_prominence": expected,
                    "video_id": row["video_id"],
                    "youtube_video_id": row["youtube_video_id"],
                }
                for row, support, expected in zip(
                    sermon_rows,
                    support_values,
                    expected_values,
                    strict=True,
                )
            ],
            "representative_blocks": _profile_evidence_links(
                sermon_rows,
                topic,
                key="representative_blocks",
                reverse=True,
            ),
            "counterevidence_blocks": _profile_evidence_links(
                sermon_rows,
                topic,
                key="counterevidence_blocks",
                reverse=False,
            ),
        }

    aggregation_policy = {
        "comparative_use_allowed": False,
        "estimand": "equal_sermon_mean",
        "expected_prominence_role": "secondary_sensitivity_measure",
        "primary_measure": "developed_emphasis_probability",
        "primary_source": "mean_supporting_or_above_probability",
        "status": TOPIC_PROFILE_ANALYTICAL_STATUS,
        "version": TOPIC_PROFILE_AGGREGATION_POLICY_VERSION,
    }
    profile_values: list[tuple[str, object, str | None]] = [
        ("analytical_status", TOPIC_PROFILE_ANALYTICAL_STATUS, None),
        ("aggregation_policy", aggregation_policy, None),
        ("topic_question_pack_version", question_pack_version, None),
        ("sermon_projection_policy_version", projection_policy_version, None),
        ("sermons_attached", len(scope.videos), "sermons"),
        ("sermons_analyzed", len(sermon_rows), "sermons"),
        ("sermons_blocked", len(blocked_sermons), "sermons"),
        ("blocked_sermons", blocked_sermons, None),
        ("topic_profiles", topic_profiles, None),
        ("sermon_topic_support", sermon_rows, None),
    ]
    input_fingerprint = _sha256(
        {
            "aggregation_policy_version": (
                TOPIC_PROFILE_AGGREGATION_POLICY_VERSION
            ),
            "analyzer_key": TOPIC_PROFILE_ANALYZER_KEY,
            "analyzer_version": analyzer_version,
            "membership_fingerprint": membership_fingerprint,
            "profile_id": scope.profile_id,
            "schema_version": TOPIC_PROFILE_SCHEMA_VERSION,
            "scope_gate_fingerprints": sorted(
                scope_gate_fingerprints,
                key=lambda item: int(item["video_id"]),
            ),
            "sermon_analysis_input_fingerprints": sorted(
                row["sermon_analysis_input_fingerprint"] for row in sermon_rows
            ),
        }
    )
    run, created = database.add_speaker_profile_analysis_run(
        profile_id=scope.profile_id,
        analyzer_key=TOPIC_PROFILE_ANALYZER_KEY,
        analyzer_version=analyzer_version,
        membership_fingerprint=membership_fingerprint,
        input_fingerprint=input_fingerprint,
        inputs=inputs,
        measurements=[
            (key, _canonical_json(value), unit) for key, value, unit in profile_values
        ],
    )
    return TopicProfileAnalysisOutcome(run=run, created=created)
