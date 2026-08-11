from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

from pastor_transcript_extractor.models import Video
from pastor_transcript_extractor.sermon_analysis import (
    ANALYZER_KEY as SCRIPTURE_ANALYZER_KEY,
    ANALYZER_VERSION as SCRIPTURE_ANALYZER_VERSION,
    load_identified_sermon_source,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.style_analysis import (
    STYLE_ANALYZER_KEY,
    STYLE_DIMENSIONS,
)


STYLE_REVIEW_WORKFLOW_VERSION = "full-sermon-style-runs-v1"
STYLE_REVIEW_SCHEMA_VERSION = 1
STYLE_REVIEW_JUDGMENTS = {
    "correct_representative_boundaries",
    "correct_but_undersized",
    "correct_but_oversized",
    "incorrect_category",
}


@dataclass(frozen=True, slots=True)
class BoundaryMetrics:
    predicted_run_count: int
    reviewed_run_count: int
    matched_run_count: int
    false_positive_run_count: int
    missed_run_count: int
    run_precision: float
    run_recall: float
    reviewed_duration_seconds: float
    accepted_duration_seconds: float
    overlapping_duration_seconds: float
    reviewed_duration_recall: float
    accepted_duration_precision: float
    duration_intersection_over_union: float


@dataclass(frozen=True, slots=True)
class StyleBoundaryEvaluation:
    sermon_count: int
    overall: BoundaryMetrics
    by_dimension: dict[str, BoundaryMetrics]
    judgment_counts: dict[str, int]


def _decoded_measurements(database: Database, run_id: int) -> dict[str, object]:
    return {
        item.metric_key: json.loads(item.value_json)
        for item in database.list_sermon_analysis_measurements(run_id)
    }


def _evidence_payload(item: Any) -> dict[str, Any]:
    payload = json.loads(item.payload_json)
    return {
        "evidence_key": item.evidence_key,
        "evidence_kind": item.evidence_kind,
        "start_seconds": item.start_seconds,
        "end_seconds": item.end_seconds,
        "excerpt": item.excerpt,
        "payload": payload,
    }


def _timestamp(seconds: object) -> str:
    total = max(0, int(float(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, second = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{second:02d}"


def render_style_review_markdown(payload: dict[str, Any]) -> str:
    video = payload["video"]
    candidates = payload["candidate_style_runs"]
    lines = [
        f"# Full-sermon style review — {video['youtube_video_id']}",
        "",
        f"{video['title']}",
        "",
        "Edit the JSON draft, not this inspection view. Adjudicate every candidate "
        "run and add every entirely missed run before finalizing.",
        "",
        "## Candidate representative runs",
        "",
    ]
    if candidates:
        for candidate in candidates:
            lines.append(
                f"- `{candidate['dimension']}` `{candidate['start_segment_id']}`–"
                f"`{candidate['end_segment_id']}`; key `{candidate['evidence_key']}`"
            )
    else:
        lines.append("- No candidate runs were accepted.")
    lines.extend(["", "## Complete timestamped transcript", ""])
    annotations: dict[int, list[str]] = defaultdict(list)
    groups = (
        ("SUPPORT", payload["supporting_evidence"]),
        ("RUN", candidates),
        ("REFERENCE", payload["scripture_references"]),
        ("ALIGNMENT", payload["scripture_text_alignments"]),
    )
    for label, items in groups:
        for item in items:
            evidence_payload = item.get("payload", {})
            start = evidence_payload.get(
                "source_segment_start_index", item.get("segment_index")
            )
            end = evidence_payload.get("source_segment_end_index", start)
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            detail = evidence_payload.get("dimension") or evidence_payload.get(
                "canonical_reference"
            )
            annotation = f"{label}:{detail or item['evidence_key'][:8]}"
            for index in range(start, end + 1):
                annotations[index].append(annotation)
    for segment in payload["segments"]:
        tags = " ".join(f"[{tag}]" for tag in sorted(annotations[segment["segment_index"]]))
        lines.append(
            f"- `{segment['segment_id']}` [{_timestamp(segment['start_seconds'])}–"
            f"{_timestamp(segment['end_seconds'])}] {tags} {segment['text']}".rstrip()
        )
    return "\n".join(lines) + "\n"


def create_style_review_packet(
    database: Database,
    video: Video,
    output_path: Path,
) -> dict[str, Any]:
    style_run = database.get_latest_sermon_analysis_run(
        video.id, STYLE_ANALYZER_KEY
    )
    if style_run is None:
        raise ValueError(
            f"Video {video.youtube_video_id} needs {STYLE_ANALYZER_KEY} before style review"
        )
    style_measurements = _decoded_measurements(database, style_run.id)
    scripture_run = database.get_latest_sermon_analysis_run(
        video.id,
        SCRIPTURE_ANALYZER_KEY,
        analyzer_version=SCRIPTURE_ANALYZER_VERSION,
    )
    if scripture_run is None:
        raise ValueError(
            f"Video {video.youtube_video_id} needs {SCRIPTURE_ANALYZER_KEY}@"
            f"{SCRIPTURE_ANALYZER_VERSION} before style review"
        )
    supporting_scripture_run_id = style_measurements.get("scripture_analysis_run_id")
    if not isinstance(supporting_scripture_run_id, int):
        supporting_scripture_run_id = scripture_run.id
    source_segments, sermon_start, sermon_duration = load_identified_sermon_source(
        Path(style_run.source_path)
    )
    style_evidence = [
        _evidence_payload(item)
        for item in database.list_sermon_analysis_evidence(style_run.id)
    ]
    scripture_evidence = [
        _evidence_payload(item)
        for item in database.list_sermon_analysis_evidence(supporting_scripture_run_id)
        if item.evidence_kind in {"scripture_reference", "scripture_text_alignment"}
    ]
    candidate_runs = []
    supporting_evidence = []
    for item in style_evidence:
        if item["evidence_kind"] == "semantic_style_run":
            payload = item["payload"]
            candidate_runs.append(
                {
                    **item,
                    "dimension": payload.get("dimension"),
                    "start_segment_id": f"S{int(payload['source_segment_start_index']):06d}",
                    "end_segment_id": f"S{int(payload['source_segment_end_index']):06d}",
                    "adjudication": {
                        "judgment": "unreviewed",
                        "reviewed_start_segment_id": None,
                        "reviewed_end_segment_id": None,
                        "notes": "",
                    },
                }
            )
        elif item["evidence_kind"] == "semantic_style_evidence":
            supporting_evidence.append(item)
    if not candidate_runs:
        # Version 2 stored only exemplar spans. Expose each as a legacy candidate so
        # the review workflow can directly measure the suspected undersizing.
        for item in supporting_evidence:
            evidence_payload = item["payload"]
            start_index = int(evidence_payload["source_segment_start_index"])
            end_index = int(evidence_payload["source_segment_end_index"])
            candidate_runs.append(
                {
                    **item,
                    "dimension": evidence_payload.get("dimension"),
                    "start_segment_id": f"S{start_index:06d}",
                    "end_segment_id": f"S{end_index:06d}",
                    "candidate_origin": "legacy_accepted_evidence_span",
                    "adjudication": {
                        "judgment": "unreviewed",
                        "reviewed_start_segment_id": None,
                        "reviewed_end_segment_id": None,
                        "notes": "",
                    },
                }
            )
    payload: dict[str, Any] = {
        "schema_version": STYLE_REVIEW_SCHEMA_VERSION,
        "workflow_version": STYLE_REVIEW_WORKFLOW_VERSION,
        "review_status": "unreviewed",
        "reviewed_by": None,
        "reviewed_at": None,
        "video": {
            "database_id": video.id,
            "youtube_video_id": video.youtube_video_id,
            "title": video.title,
            "url": video.url,
        },
        "source": {
            "style_analysis_run_id": style_run.id,
            "style_analyzer_version": style_run.analyzer_version,
            "style_analysis_input_fingerprint": style_run.input_fingerprint,
            "scripture_analysis_run_id": supporting_scripture_run_id,
            "scripture_analysis_input_fingerprint": (
                scripture_run.input_fingerprint
                if supporting_scripture_run_id == scripture_run.id
                else None
            ),
            "sermon_start_seconds": sermon_start,
            "sermon_duration_seconds": sermon_duration,
            "style_measurements": style_measurements,
        },
        "instructions": {
            "candidate_judgments": sorted(STYLE_REVIEW_JUDGMENTS),
            "boundary_rule": (
                "For undersized or oversized judgments, supply reviewed segment "
                "boundaries for the full contiguous semantic run."
            ),
            "missed_run_rule": (
                "Add every entirely missed run with dimension, start/end segment IDs, "
                "and notes. Scripture engagement is a diagnostic, not automatic exegesis."
            ),
        },
        "segments": [
            {
                "segment_id": f"S{segment.index:06d}",
                "segment_index": segment.index,
                "start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds,
                "text": segment.text,
            }
            for segment in source_segments
        ],
        "supporting_evidence": supporting_evidence,
        "candidate_style_runs": candidate_runs,
        "scripture_references": [
            item for item in scripture_evidence if item["evidence_kind"] == "scripture_reference"
        ],
        "scripture_text_alignments": [
            item
            for item in scripture_evidence
            if item["evidence_kind"] == "scripture_text_alignment"
        ],
        "missed_style_runs": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    output_path.with_suffix(".md").write_text(
        render_style_review_markdown(payload), encoding="utf-8"
    )
    return payload


def finalize_style_review(
    draft_path: Path,
    output_path: Path,
    *,
    reviewer: str,
) -> dict[str, Any]:
    payload = json.loads(draft_path.read_text(encoding="utf-8"))
    _review_intervals(payload, require_reviewed=False)
    if not reviewer.strip():
        raise ValueError("Reviewer must not be blank")
    candidate_runs = payload.get("candidate_style_runs")
    if not isinstance(candidate_runs, list):
        raise ValueError("Style review has no candidate_style_runs list")
    for candidate in candidate_runs:
        adjudication = candidate.get("adjudication") if isinstance(candidate, dict) else None
        if (
            not isinstance(adjudication, dict)
            or adjudication.get("judgment") not in STYLE_REVIEW_JUDGMENTS
        ):
            raise ValueError("Every candidate style run must have a final adjudication")
    payload["review_status"] = "reviewed"
    payload["reviewed_by"] = reviewer.strip()
    payload["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    _review_intervals(payload, require_reviewed=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return payload


def _segment_interval(
    segment_by_id: dict[str, dict[str, object]], start_id: object, end_id: object
) -> tuple[float, float]:
    if not isinstance(start_id, str) or not isinstance(end_id, str):
        raise ValueError("Style run boundaries must be segment IDs")
    start = segment_by_id.get(start_id)
    end = segment_by_id.get(end_id)
    if start is None or end is None:
        raise ValueError(f"Unknown style review segment boundary: {start_id}–{end_id}")
    if int(start["segment_index"]) > int(end["segment_index"]):
        raise ValueError("Style run end must not precede its start")
    return float(start["start_seconds"]), float(end["end_seconds"])


def _review_intervals(
    payload: dict[str, object], *, require_reviewed: bool
) -> tuple[
    dict[str, list[tuple[float, float]]],
    dict[str, list[tuple[float, float]]],
    Counter[str],
]:
    if payload.get("schema_version") != STYLE_REVIEW_SCHEMA_VERSION:
        raise ValueError("Unsupported style review schema_version")
    if require_reviewed and payload.get("review_status") != "reviewed":
        raise ValueError("Style review is not finalized")
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Style review has no transcript segments")
    segment_by_id = {
        str(item["segment_id"]): item
        for item in segments
        if isinstance(item, dict) and isinstance(item.get("segment_id"), str)
    }
    predicted: dict[str, list[tuple[float, float]]] = defaultdict(list)
    reviewed: dict[str, list[tuple[float, float]]] = defaultdict(list)
    judgments: Counter[str] = Counter()
    candidates = payload.get("candidate_style_runs")
    if not isinstance(candidates, list):
        raise ValueError("Style review has no candidate_style_runs list")
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("dimension") not in STYLE_DIMENSIONS:
            raise ValueError("Invalid candidate style run")
        dimension = str(candidate["dimension"])
        predicted_interval = _segment_interval(
            segment_by_id,
            candidate.get("start_segment_id"),
            candidate.get("end_segment_id"),
        )
        predicted[dimension].append(predicted_interval)
        adjudication = candidate.get("adjudication")
        if not isinstance(adjudication, dict):
            raise ValueError("Candidate style run lacks adjudication")
        judgment = adjudication.get("judgment")
        if judgment == "unreviewed" and not require_reviewed:
            continue
        if judgment not in STYLE_REVIEW_JUDGMENTS:
            raise ValueError(f"Invalid style run judgment: {judgment!r}")
        judgments[str(judgment)] += 1
        if judgment == "incorrect_category":
            continue
        if judgment == "correct_representative_boundaries":
            reviewed[dimension].append(predicted_interval)
            continue
        reviewed[dimension].append(
            _segment_interval(
                segment_by_id,
                adjudication.get("reviewed_start_segment_id"),
                adjudication.get("reviewed_end_segment_id"),
            )
        )
    missed = payload.get("missed_style_runs")
    if not isinstance(missed, list):
        raise ValueError("Style review missed_style_runs must be a list")
    for item in missed:
        if not isinstance(item, dict) or item.get("dimension") not in STYLE_DIMENSIONS:
            raise ValueError("Invalid missed style run")
        reviewed[str(item["dimension"])].append(
            _segment_interval(
                segment_by_id,
                item.get("start_segment_id"),
                item.get("end_segment_id"),
            )
        )
        judgments["entirely_missed"] += 1
    return predicted, reviewed, judgments


def _merged(intervals: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[list[float]] = []
    for start, end in sorted(intervals):
        if not result or start > result[-1][1]:
            result.append([start, end])
        else:
            result[-1][1] = max(result[-1][1], end)
    return [(start, end) for start, end in result]


def _duration(intervals: Iterable[tuple[float, float]]) -> float:
    return sum(end - start for start, end in _merged(intervals))


def _intersection_duration(
    left: Iterable[tuple[float, float]], right: Iterable[tuple[float, float]]
) -> float:
    a = _merged(left)
    b = _merged(right)
    total = 0.0
    for a_start, a_end in a:
        for b_start, b_end in b:
            total += max(0.0, min(a_end, b_end) - max(a_start, b_start))
    return total


def _safe_ratio(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 6) if denominator else 1.0


def evaluate_style_boundaries(paths: Iterable[Path]) -> StyleBoundaryEvaluation:
    path_list = tuple(paths)
    accumulated_predicted: dict[str, list[tuple[float, float]]] = defaultdict(list)
    accumulated_reviewed: dict[str, list[tuple[float, float]]] = defaultdict(list)
    judgments: Counter[str] = Counter()
    matched_by_dimension: Counter[str] = Counter()
    false_positive_by_dimension: Counter[str] = Counter()
    missed_by_dimension: Counter[str] = Counter()
    dimension_offsets = {
        dimension: index * 100_000.0
        for index, dimension in enumerate(STYLE_DIMENSIONS)
    }
    sermon_count = 0
    for path in path_list:
        payload = json.loads(path.read_text(encoding="utf-8"))
        predicted, reviewed, review_judgments = _review_intervals(
            payload, require_reviewed=True
        )
        sermon_count += 1
        judgments.update(review_judgments)
        for candidate in payload.get("candidate_style_runs", []):
            dimension = str(candidate.get("dimension"))
            judgment = candidate.get("adjudication", {}).get("judgment")
            if judgment == "incorrect_category":
                false_positive_by_dimension[dimension] += 1
            elif judgment in STYLE_REVIEW_JUDGMENTS:
                matched_by_dimension[dimension] += 1
        for item in payload.get("missed_style_runs", []):
            missed_by_dimension[str(item.get("dimension"))] += 1
        # Offset sermons and dimensions so unrelated interval unions cannot overlap.
        for dimension, intervals in predicted.items():
            offset = sermon_count * 1_000_000.0 + dimension_offsets[dimension]
            accumulated_predicted[dimension].extend(
                (start + offset, end + offset) for start, end in intervals
            )
        for dimension, intervals in reviewed.items():
            offset = sermon_count * 1_000_000.0 + dimension_offsets[dimension]
            accumulated_reviewed[dimension].extend(
                (start + offset, end + offset) for start, end in intervals
            )
    if not sermon_count:
        raise ValueError("At least one reviewed style packet is required")

    correct = sum(
        judgments[key]
        for key in (
            "correct_representative_boundaries",
            "correct_but_undersized",
            "correct_but_oversized",
        )
    )
    false_positive = judgments["incorrect_category"]
    missed = judgments["entirely_missed"]

    def metrics(dimension: str | None) -> BoundaryMetrics:
        predicted = (
            [item for values in accumulated_predicted.values() for item in values]
            if dimension is None
            else accumulated_predicted[dimension]
        )
        reviewed = (
            [item for values in accumulated_reviewed.values() for item in values]
            if dimension is None
            else accumulated_reviewed[dimension]
        )
        if dimension is None:
            matched_count = correct
            false_positive_count = false_positive
            missed_count = missed
        else:
            matched_count = matched_by_dimension[dimension]
            false_positive_count = false_positive_by_dimension[dimension]
            missed_count = missed_by_dimension[dimension]
        predicted_duration = _duration(predicted)
        reviewed_duration = _duration(reviewed)
        intersection = _intersection_duration(predicted, reviewed)
        union = predicted_duration + reviewed_duration - intersection
        return BoundaryMetrics(
            predicted_run_count=matched_count + false_positive_count,
            reviewed_run_count=matched_count + missed_count,
            matched_run_count=matched_count,
            false_positive_run_count=false_positive_count,
            missed_run_count=missed_count,
            run_precision=_safe_ratio(
                matched_count, matched_count + false_positive_count
            ),
            run_recall=_safe_ratio(matched_count, matched_count + missed_count),
            reviewed_duration_seconds=round(reviewed_duration, 3),
            accepted_duration_seconds=round(predicted_duration, 3),
            overlapping_duration_seconds=round(intersection, 3),
            reviewed_duration_recall=_safe_ratio(intersection, reviewed_duration),
            accepted_duration_precision=_safe_ratio(intersection, predicted_duration),
            duration_intersection_over_union=_safe_ratio(intersection, union),
        )

    return StyleBoundaryEvaluation(
        sermon_count,
        metrics(None),
        {dimension: metrics(dimension) for dimension in STYLE_DIMENSIONS},
        dict(sorted(judgments.items())),
    )
