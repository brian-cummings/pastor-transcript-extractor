from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CATASTROPHIC_RECALL_THRESHOLD = 0.90


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ranges(payload: dict[str, Any], field: str) -> list[tuple[float, float]]:
    return [
        (float(item["start_seconds"]), float(item["end_seconds"]))
        for item in payload.get(field, [])
        if isinstance(item, dict)
        and isinstance(item.get("start_seconds"), (int, float))
        and isinstance(item.get("end_seconds"), (int, float))
    ]


def _overlap_seconds(start: float, end: float, ranges: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(end, range_end) - max(start, range_start)) for range_start, range_end in ranges)


def _segments_matching_ranges(
    segments: list[dict[str, Any]], ranges: list[tuple[float, float]]
) -> set[int]:
    matching: set[int] = set()
    for index, segment in enumerate(segments):
        start = segment.get("start_seconds")
        end = segment.get("end_seconds")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            continue
        duration = float(end) - float(start)
        if _overlap_seconds(float(start), float(end), ranges) >= duration * 0.5:
            matching.add(index)
    return matching


def _timed_segment_indexes(segments: list[dict[str, Any]]) -> set[int]:
    return {
        index
        for index, segment in enumerate(segments)
        if isinstance(segment.get("start_seconds"), (int, float))
        and isinstance(segment.get("end_seconds"), (int, float))
        and float(segment["end_seconds"]) > float(segment["start_seconds"])
    }


def _detected_boundary(
    segments: list[dict[str, Any]], detected: set[int]
) -> tuple[float | None, float | None]:
    retained = [segments[index] for index in detected if 0 <= index < len(segments)]
    starts = [segment.get("start_seconds") for segment in retained if isinstance(segment.get("start_seconds"), (int, float))]
    ends = [segment.get("end_seconds") for segment in retained if isinstance(segment.get("end_seconds"), (int, float))]
    return (float(min(starts)), float(max(ends))) if starts and ends else (None, None)


def _candidate_ground_truth_rank(
    candidates: list[dict[str, Any]], expected: list[tuple[float, float]]
) -> int | None:
    scored: list[tuple[float, int]] = []
    for candidate in candidates:
        start = candidate.get("start_seconds")
        end = candidate.get("end_seconds")
        rank = candidate.get("rank")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not isinstance(rank, int):
            continue
        scored.append((_overlap_seconds(float(start), float(end), expected), rank))
    if not scored:
        return None
    return max(scored, key=lambda item: (item[0], -item[1]))[1]


def _segment_runs(indexes: set[int], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs: list[list[int]] = []
    for index in sorted(indexes):
        if not runs or index != runs[-1][-1] + 1:
            runs.append([index])
        else:
            runs[-1].append(index)
    result: list[dict[str, Any]] = []
    for run in runs:
        first, last = segments[run[0]], segments[run[-1]]
        texts = [str(segments[index].get("text", "")).strip() for index in run]
        result.append({
            "start_segment": run[0],
            "end_segment": run[-1],
            "segment_count": len(run),
            "start_seconds": first.get("start_seconds"),
            "end_seconds": last.get("end_seconds"),
            "text_preview": " ".join(text for text in texts if text)[:240],
        })
    return result


def _classification_ranges(
    classification: dict[str, Any], target_indexes: set[int]
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    # Coarse and fine namespaces may reuse block IDs. The audit persists both
    # lists in corresponding order, so positional pairing is unambiguous.
    for block, item in zip(
        classification.get("blocks", []), classification.get("classifications", []), strict=False
    ):
        if not isinstance(block, dict) or not isinstance(item, dict):
            continue
        if block.get("block_id") != item.get("block_id"):
            continue
        block_indexes = {index for index in block.get("segment_indexes", []) if isinstance(index, int)}
        overlap = block_indexes & target_indexes
        if not overlap:
            continue
        evidence = str(item.get("evidence", ""))
        phase, _, reason = evidence.partition(":")
        details.append({
            "phase": phase or "unknown",
            "block_id": item.get("block_id"),
            "start_seconds": block.get("start_seconds"),
            "end_seconds": block.get("end_seconds"),
            "label": item.get("label"),
            "reason_code": reason or None,
            "overlapping_segment_count": len(overlap),
        })
    return details


def build_failure_analysis(fixture: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    """Explain a failed result using only frozen truth and persisted inference evidence."""
    segments = [item if isinstance(item, dict) else {} for item in proposed.get("segments", [])]
    classification = proposed.get("classification") if isinstance(proposed.get("classification"), dict) else {}
    retained = {
        index for index in classification.get("retained_segment_indexes", [])
        if isinstance(index, int) and 0 <= index < len(segments)
    }
    timed = _timed_segment_indexes(segments)
    expected_ranges = _ranges(fixture, "expected_spans")
    expected = _segments_matching_ranges(segments, expected_ranges)
    missed = expected - retained
    contaminating = (retained - expected) & timed
    search = classification.get("search") if isinstance(classification.get("search"), dict) else {}
    candidates = search.get("candidates") if isinstance(search.get("candidates"), list) else []
    selected_rank = search.get("selected_rank")
    selected = next(
        (candidate for candidate in candidates if isinstance(candidate, dict) and candidate.get("rank") == selected_rank),
        None,
    )
    coarse = _classification_ranges(classification, timed)
    coarse = [item for item in coarse if item["phase"] == "coarse"]
    fine = _classification_ranges(classification, timed)
    fine = [item for item in fine if item["phase"] == "fine"]
    disagreements: list[dict[str, Any]] = []
    for coarse_item in coarse:
        for fine_item in fine:
            if not all(isinstance(item.get(key), (int, float)) for item in (coarse_item, fine_item) for key in ("start_seconds", "end_seconds")):
                continue
            start = max(float(coarse_item["start_seconds"]), float(fine_item["start_seconds"]))
            end = min(float(coarse_item["end_seconds"]), float(fine_item["end_seconds"]))
            if end > start and coarse_item["label"] != fine_item["label"]:
                disagreements.append({
                    "start_seconds": start,
                    "end_seconds": end,
                    "coarse_label": coarse_item["label"],
                    "fine_label": fine_item["label"],
                })
    return {
        "schema_version": 1,
        "video_id": fixture.get("video_id"),
        "expected_outcome": fixture.get("expected_outcome"),
        "expected_spans": fixture.get("expected_spans", []),
        "allowed_interruptions": fixture.get("allowed_interruptions", []),
        "detected_retained_ranges": _segment_runs(retained, segments),
        "missed_segment_ranges": _segment_runs(missed, segments),
        "contaminating_segment_ranges": _segment_runs(contaminating, segments),
        "missed_range_classifications": _classification_ranges(classification, missed),
        "contaminating_range_classifications": _classification_ranges(classification, contaminating),
        "candidate": selected,
        "candidate_score_components": selected.get("score_components") if isinstance(selected, dict) else None,
        "candidate_score_components_status": (
            "available" if isinstance(selected, dict) and isinstance(selected.get("score_components"), dict)
            else "not_persisted"
        ),
        "confidence_tier": classification.get("confidence_tier"),
        "confidence_reasons": classification.get("confidence_reasons"),
        "confidence_reasons_status": (
            "available" if isinstance(classification.get("confidence_reasons"), list) else "not_persisted"
        ),
        "warnings": classification.get("warnings", []),
        "coarse_fine_disagreements": disagreements,
        "coarse_label_ranges": coarse,
        "fine_label_ranges": fine,
    }


def build_failure_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        f"# Failure Analysis: {analysis['video_id']}",
        "",
        f"- Expected outcome: {analysis['expected_outcome']}",
        f"- Confidence: {analysis.get('confidence_tier', '—')}",
        f"- Candidate score components: {analysis['candidate_score_components_status']}",
        f"- Confidence reasons: {analysis['confidence_reasons_status']}",
        f"- Coarse/fine disagreements: {len(analysis['coarse_fine_disagreements'])}",
        "",
    ]
    for title, key in (
        ("Expected spans", "expected_spans"),
        ("Detected retained ranges", "detected_retained_ranges"),
        ("Missed sermon ranges", "missed_segment_ranges"),
        ("Contaminating ranges", "contaminating_segment_ranges"),
    ):
        lines.extend([f"## {title}", ""])
        values = analysis.get(key, [])
        if not values:
            lines.append("None.")
        for item in values:
            lines.append(
                f"- {item.get('start_seconds')}s–{item.get('end_seconds')}s"
                + (f" ({item.get('segment_count')} segments): {item.get('text_preview', '')}" if "segment_count" in item else "")
            )
        lines.append("")
    lines.extend(["## Persisted label evidence", "", "| Phase | Block | Time | Label | Reason | Overlap |", "|---|---:|---:|---|---|---:|"])
    evidence = analysis.get("missed_range_classifications", []) + analysis.get("contaminating_range_classifications", [])
    for item in evidence:
        lines.append(
            f"| {item['phase']} | {item['block_id']} | {item['start_seconds']}–{item['end_seconds']} | "
            f"{item['label']} | {item.get('reason_code') or '—'} | {item['overlapping_segment_count']} |"
        )
    lines.extend(["", "## Candidate and confidence evidence", "", "```json", json.dumps({
        "candidate": analysis.get("candidate"),
        "candidate_score_components": analysis.get("candidate_score_components"),
        "confidence_reasons": analysis.get("confidence_reasons"),
        "warnings": analysis.get("warnings"),
    }, indent=2, sort_keys=True), "```", ""])
    return "\n".join(lines)


def evaluate_fixture_payload(
    fixture: dict[str, Any],
    proposed: dict[str, Any],
    *,
    fixture_path: Path,
    proposed_path: Path,
) -> dict[str, Any]:
    segments_raw = proposed.get("segments")
    classification = proposed.get("classification")
    if not isinstance(segments_raw, list) or not isinstance(classification, dict):
        return {
            "video_id": fixture.get("video_id"),
            "status": "missing_classification_artifact",
            "fixture_path": str(fixture_path),
            "proposed_path": str(proposed_path),
        }
    search_raw = classification.get("search")
    if (
        classification.get("method") != "adaptive_llm_v3"
        or not isinstance(search_raw, dict)
        or search_raw.get("algorithm_version") != "adaptive_llm_v3"
    ):
        return {
            "video_id": fixture.get("video_id"),
            "status": "stale_or_non_adaptive_classification",
            "classification_method": classification.get("method"),
            "algorithm_version": search_raw.get("algorithm_version") if isinstance(search_raw, dict) else None,
            "fixture_path": str(fixture_path),
            "proposed_path": str(proposed_path),
        }
    segments = [segment if isinstance(segment, dict) else {} for segment in segments_raw]
    retained_raw = classification.get("retained_segment_indexes")
    if not isinstance(retained_raw, list):
        return {
            "video_id": fixture.get("video_id"),
            "status": "missing_retained_segments",
            "fixture_path": str(fixture_path),
            "proposed_path": str(proposed_path),
        }
    detected = {index for index in retained_raw if isinstance(index, int) and 0 <= index < len(segments)}
    timed = _timed_segment_indexes(segments)
    expected_ranges = _ranges(fixture, "expected_spans")
    interruption_ranges = _ranges(fixture, "allowed_interruptions")
    expected = _segments_matching_ranges(segments, expected_ranges)
    interruption_segments = _segments_matching_ranges(segments, interruption_ranges)
    search = search_raw
    candidates = search.get("candidates") if isinstance(search.get("candidates"), list) else []
    selected_rank = search.get("selected_rank") if isinstance(search.get("selected_rank"), int) else None
    confidence = str(classification.get("confidence_tier", "unknown"))
    cache_stats = classification.get("cache_stats") if isinstance(classification.get("cache_stats"), dict) else {}
    sermon_window = proposed.get("sermon_window") if isinstance(proposed.get("sermon_window"), dict) else {}
    common = {
        "video_id": str(fixture.get("video_id")),
        "status": "evaluated",
        "expected_outcome": fixture.get("expected_outcome"),
        "fixture_version": fixture.get("ground_truth_version"),
        "fixture_hash": _canonical_hash(fixture),
        "transcript_hash": _canonical_hash(
            [(segment.get("start_seconds"), segment.get("end_seconds"), segment.get("text")) for segment in segments]
        ),
        "algorithm_version": search.get("algorithm_version") or classification.get("method"),
        "search_schema_version": search.get("schema_version"),
        "prompt_version": classification.get("prompt_version"),
        "model_name": classification.get("model"),
        "model_digest": search.get("model_digest") or classification.get("model_digest"),
        "fixture_path": str(fixture_path),
        "proposed_path": str(proposed_path),
        "candidate_search_artifact": str(proposed_path),
        "selected_candidate_rank": selected_rank,
        "confidence_tier": confidence,
        "cache_hits": int(cache_stats.get("hits", 0)),
        "cache_misses": int(cache_stats.get("misses", 0)),
    }
    if fixture.get("expected_outcome") == "no_sermon":
        candidate_produced = bool(candidates and selected_rank is not None)
        baseline_protected = confidence != "high" and sermon_window.get("source") != "hybrid_llm"
        return {
            **common,
            "candidate_produced": candidate_produced,
            "retained_segment_count": len(detected),
            "timed_segment_count": len(timed),
            "false_positive_ratio": len(detected) / max(len(timed), 1),
            "false_high_confidence_acceptance": candidate_produced and confidence == "high",
            "baseline_protection_prevented_replacement": baseline_protected,
        }

    true_positive = detected & expected
    missed = expected - detected
    contamination = (detected - expected) & timed
    detected_start, detected_end = _detected_boundary(segments, detected)
    expected_start = min((start for start, _ in expected_ranges), default=None)
    expected_end = max((end for _, end in expected_ranges), default=None)
    rule_baseline = search.get("rule_baseline") if isinstance(search.get("rule_baseline"), dict) else {}
    rule_ranges = []
    if isinstance(rule_baseline.get("start_seconds"), (int, float)) and isinstance(rule_baseline.get("end_seconds"), (int, float)):
        rule_ranges = [(float(rule_baseline["start_seconds"]), float(rule_baseline["end_seconds"]))]
    rule_segments = _segments_matching_ranges(segments, rule_ranges)
    rule_overlap = len(detected & rule_segments) / max(len(detected | rule_segments), 1)
    ground_truth_best_rank = _candidate_ground_truth_rank(candidates, expected_ranges)
    recall = len(true_positive) / max(len(expected), 1)
    return {
        **common,
        "expected_retained_segment_count": len(expected),
        "detected_retained_segment_count": len(detected),
        "true_positive_retained_segment_count": len(true_positive),
        "missed_sermon_segment_count": len(missed),
        "contaminating_segment_count": len(contamination),
        "allowed_interruption_segment_count": len(interruption_segments),
        "retained_allowed_interruption_segment_count": len(detected & interruption_segments),
        "sermon_recall": recall,
        "contamination_ratio": len(contamination) / max(len(detected), 1),
        "detected_start_seconds": detected_start,
        "detected_end_seconds": detected_end,
        "expected_start_seconds": expected_start,
        "expected_end_seconds": expected_end,
        "start_boundary_error_seconds": None if detected_start is None or expected_start is None else detected_start - expected_start,
        "end_boundary_error_seconds": None if detected_end is None or expected_end is None else detected_end - expected_end,
        "ground_truth_best_candidate_rank": ground_truth_best_rank,
        "correct_top_candidate": selected_rank is not None and selected_rank == ground_truth_best_rank,
        "rule_llm_overlap": rule_overlap,
        "catastrophic_omission": recall < CATASTROPHIC_RECALL_THRESHOLD,
    }


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [result for result in results if result.get("status") == "evaluated"]
    positives = [result for result in evaluated if result.get("expected_outcome") == "sermon"]
    negatives = [result for result in evaluated if result.get("expected_outcome") == "no_sermon"]
    recalls = [float(result["sermon_recall"]) for result in positives]
    contamination = [float(result["contamination_ratio"]) for result in positives]
    top_candidates = [bool(result.get("correct_top_candidate")) for result in positives]
    return {
        "fixture_count": len(results),
        "evaluated_fixture_count": len(evaluated),
        "missing_artifact_count": len(results) - len(evaluated),
        "positive_fixture_count": len(positives),
        "negative_fixture_count": len(negatives),
        "mean_sermon_recall": sum(recalls) / len(recalls) if recalls else None,
        "worst_sermon_recall": min(recalls) if recalls else None,
        "mean_contamination_ratio": sum(contamination) / len(contamination) if contamination else None,
        "catastrophic_omissions": sum(bool(result.get("catastrophic_omission")) for result in positives),
        "negative_candidates_produced": sum(bool(result.get("candidate_produced")) for result in negatives),
        "negative_high_confidence_false_positives": sum(bool(result.get("false_high_confidence_acceptance")) for result in negatives),
        "correct_top_candidate_rate": sum(top_candidates) / len(top_candidates) if top_candidates else None,
    }


def build_markdown_report(run: dict[str, Any]) -> str:
    aggregate = run["aggregate"]
    def metric(value: object, digits: int = 3) -> str:
        return f"{value:.{digits}f}" if isinstance(value, (int, float)) else "—"

    lines = [
        "# Sermon Extraction Evaluation",
        "",
        f"- Run ID: {run['run_id']}",
        f"- Fixtures: {aggregate['fixture_count']}",
        f"- Evaluated: {aggregate['evaluated_fixture_count']}",
        f"- Missing artifacts: {aggregate['missing_artifact_count']}",
        f"- Mean sermon recall: {metric(aggregate['mean_sermon_recall'])}",
        f"- Worst sermon recall: {metric(aggregate['worst_sermon_recall'])}",
        f"- Mean contamination ratio: {metric(aggregate['mean_contamination_ratio'])}",
        f"- Correct top-candidate rate: {metric(aggregate['correct_top_candidate_rate'])}",
        f"- Catastrophic omissions: {aggregate['catastrophic_omissions']}",
        f"- Negative high-confidence false positives: {aggregate['negative_high_confidence_false_positives']}",
        "",
        "## Positive fixtures",
        "",
        "| Video | Confidence | Recall | Contam. | Start error | End error | Selected / best rank | Rule overlap | Cache H/M | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    positives = [result for result in run["results"] if result.get("expected_outcome") == "sermon"]
    negatives = [result for result in run["results"] if result.get("expected_outcome") == "no_sermon"]
    unknown = [result for result in run["results"] if result.get("expected_outcome") not in {"sermon", "no_sermon"}]
    for result in positives:
        lines.append(
            f"| {result.get('video_id')} | {result.get('confidence_tier', '—')} | "
            f"{metric(result.get('sermon_recall'))} | {metric(result.get('contamination_ratio'))} | "
            f"{metric(result.get('start_boundary_error_seconds'), 1)} | {metric(result.get('end_boundary_error_seconds'), 1)} | "
            f"{result.get('selected_candidate_rank', '—')} / {result.get('ground_truth_best_candidate_rank', '—')} | "
            f"{metric(result.get('rule_llm_overlap'))} | {result.get('cache_hits', 0)}/{result.get('cache_misses', 0)} | "
            f"{result.get('status')} |"
        )
    lines.extend([
        "",
        "## Negative fixtures",
        "",
        "| Video | Candidate | Confidence | Retained | False-positive ratio | Baseline protected | Cache H/M | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ])
    for result in negatives:
        lines.append(
            f"| {result.get('video_id')} | {'yes' if result.get('candidate_produced') else 'no'} | "
            f"{result.get('confidence_tier', '—')} | {result.get('retained_segment_count', '—')} | "
            f"{metric(result.get('false_positive_ratio'))} | "
            f"{'yes' if result.get('baseline_protection_prevented_replacement') else 'no'} | "
            f"{result.get('cache_hits', 0)}/{result.get('cache_misses', 0)} | {result.get('status')} |"
        )
    if unknown:
        lines.extend(["", "## Unevaluated fixtures", ""])
        for result in unknown:
            lines.append(f"- `{result.get('video_id')}`: {result.get('status')}")
    lines.append("")
    failures = [
        result for result in run["results"]
        if result.get("status") != "evaluated"
        or result.get("catastrophic_omission")
        or result.get("false_high_confidence_acceptance")
    ]
    if failures:
        lines.extend(["## Failures requiring review", ""])
        for result in failures:
            lines.append(f"- `{result.get('video_id')}`: {json.dumps(result, sort_keys=True)}")
    return "\n".join(lines) + "\n"


def create_evaluation_run(results: list[dict[str, Any]]) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "run_id": generated_at.strftime("%Y%m%dT%H%M%SZ"),
        "generated_at": generated_at.isoformat(),
        "aggregate": aggregate_results(results),
        "results": results,
    }
