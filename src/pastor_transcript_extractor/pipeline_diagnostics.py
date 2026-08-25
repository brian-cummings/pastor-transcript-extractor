from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from pastor_transcript_extractor.fixture_validation import ValidatedFixture


TRACE_SCHEMA_VERSION = 1
CONTRACT_VERSION = "sermon-isolation-contracts-v1"
REVIEWED_COVERAGE_THRESHOLD = 0.90
TIMELINE_WIDTH = 72


Range = tuple[float, float]


def diagnostic_contract_definition() -> dict[str, Any]:
    """Return the versioned contract snapshot embedded in every trace."""
    return {
        "version": CONTRACT_VERSION,
        "stage_order": [
            "transcript",
            "rule",
            "coarse",
            "selected",
            "joined",
            "fine",
            "final",
        ],
        "reviewed_sermon_coverage_threshold": REVIEWED_COVERAGE_THRESHOLD,
        "measurements": {
            "reviewed_sermon_coverage": (
                "duration overlap with reviewed sermon spans divided by reviewed duration"
            ),
            "contamination_ratio": (
                "output duration outside reviewed sermon and allowed-interruption spans "
                "divided by output duration"
            ),
            "previous_stage_retention": (
                "duration retained from the immediately preceding stage divided by its duration"
            ),
        },
        "interpretation": {
            "without_ground_truth": (
                "structural retention only; sermon recall and contamination are not evaluated"
            ),
            "earliest_observed_failure": "first stage whose measured output violates its contract",
            "root_cause_hypothesis": (
                "causal interpretation derived from persisted evidence; it is not an observation"
            ),
            "rule_baseline": (
                "informational comparator branching from transcript; not an upstream dependency "
                "of coarse discovery"
            ),
        },
    }


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _range(start: object, end: object) -> Range | None:
    left = _number(start)
    right = _number(end)
    return (left, right) if left is not None and right is not None and right > left else None


def _merge_ranges(ranges: Iterable[Range]) -> list[Range]:
    ordered = sorted(ranges)
    merged: list[Range] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _duration(ranges: Iterable[Range]) -> float:
    return sum(end - start for start, end in _merge_ranges(ranges))


def _intersection_duration(left: Iterable[Range], right: Iterable[Range]) -> float:
    a = _merge_ranges(left)
    b = _merge_ranges(right)
    total = 0.0
    ai = bi = 0
    while ai < len(a) and bi < len(b):
        start = max(a[ai][0], b[bi][0])
        end = min(a[ai][1], b[bi][1])
        total += max(0.0, end - start)
        if a[ai][1] <= b[bi][1]:
            ai += 1
        else:
            bi += 1
    return total


def _serialize_ranges(ranges: Iterable[Range]) -> list[dict[str, float]]:
    return [
        {"start_seconds": round(start, 3), "end_seconds": round(end, 3)}
        for start, end in _merge_ranges(ranges)
    ]


def _deserialize_ranges(raw: object) -> list[Range]:
    if not isinstance(raw, list):
        return []
    result: list[Range] = []
    for item in raw:
        if isinstance(item, dict):
            value = _range(item.get("start_seconds"), item.get("end_seconds"))
            if value is not None:
                result.append(value)
    return _merge_ranges(result)


def _boundary(ranges: Iterable[Range]) -> dict[str, float] | None:
    merged = _merge_ranges(ranges)
    if not merged:
        return None
    return {
        "start_seconds": round(merged[0][0], 3),
        "end_seconds": round(merged[-1][1], 3),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _segment_ranges(
    segments: list[dict[str, Any]], indexes: Iterable[int] | None = None
) -> list[Range]:
    selected = range(len(segments)) if indexes is None else indexes
    result: list[Range] = []
    for index in selected:
        if not isinstance(index, int) or not 0 <= index < len(segments):
            continue
        item = segments[index]
        value = _range(item.get("start_seconds"), item.get("end_seconds"))
        if value is not None:
            result.append(value)
    return _merge_ranges(result)


def _coarse_blocks(classification: dict[str, Any]) -> dict[int, Range]:
    blocks = classification.get("blocks")
    audits = classification.get("classifications")
    if not isinstance(blocks, list) or not isinstance(audits, list):
        return {}
    result: dict[int, Range] = {}
    for block, audit in zip(blocks, audits, strict=False):
        if not isinstance(block, dict) or not isinstance(audit, dict):
            continue
        evidence = str(audit.get("evidence", ""))
        if not evidence.startswith("coarse"):
            continue
        block_id = block.get("block_id")
        value = _range(block.get("start_seconds"), block.get("end_seconds"))
        if isinstance(block_id, int) and value is not None:
            result[block_id] = value
    return result


def _candidate_initial_ranges(candidate: dict[str, Any], coarse: dict[int, Range]) -> list[Range]:
    support = candidate.get("coarse_support_block_ids")
    supported = [
        coarse[block_id]
        for block_id in support if isinstance(block_id, int) and block_id in coarse
    ] if isinstance(support, list) else []
    if supported:
        return _merge_ranges(supported)
    direct = _range(candidate.get("start_seconds"), candidate.get("end_seconds"))
    return [direct] if direct is not None else []


def _selected_candidate(search: dict[str, Any]) -> dict[str, Any] | None:
    candidates = search.get("candidates")
    rank = search.get("selected_rank")
    if not isinstance(candidates, list):
        return None
    return next(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, dict) and candidate.get("rank") == rank
        ),
        None,
    )


def _stage_measurements(
    output: list[Range],
    previous: list[Range],
    expected: list[Range] | None,
    allowed_interruptions: list[Range] | None,
) -> dict[str, Any]:
    output_duration = _duration(output)
    previous_duration = _duration(previous)
    overlap_previous = _intersection_duration(output, previous)
    measurements: dict[str, Any] = {
        "output_duration_seconds": round(output_duration, 3),
        "previous_stage_retention": (
            round(overlap_previous / previous_duration, 6)
            if previous_duration > 0
            else None
        ),
        "seconds_removed": round(max(0.0, previous_duration - overlap_previous), 3),
        "seconds_added": round(max(0.0, output_duration - overlap_previous), 3),
    }
    if expected is not None:
        expected_duration = _duration(expected)
        expected_overlap = _intersection_duration(output, expected)
        accepted_overlap = _intersection_duration(
            output, [*expected, *(allowed_interruptions or [])]
        )
        measurements.update(
            {
                "reviewed_sermon_coverage": (
                    round(expected_overlap / expected_duration, 6)
                    if expected_duration > 0
                    else None
                ),
                "contamination_ratio": (
                    round(max(0.0, output_duration - accepted_overlap) / output_duration, 6)
                    if output_duration > 0
                    else 0.0
                ),
                "measurement_semantics": (
                    "coverage uses reviewed sermon spans; contamination excludes allowed "
                    "interruption spans"
                ),
            }
        )
    else:
        measurements["measurement_semantics"] = "structural_retention_without_ground_truth"
    return measurements


def _contract(
    *,
    stage_key: str,
    output: list[Range],
    measurements: dict[str, Any],
    fixture: ValidatedFixture | None,
    final_disposition: str | None,
) -> dict[str, Any]:
    if fixture is None:
        if stage_key == "transcript" and not output:
            return {
                "status": "fail",
                "code": "timed_transcript_missing",
                "message": "No timestamped transcript span is available.",
            }
        return {
            "status": "not_evaluated",
            "code": "ground_truth_unavailable",
            "message": "Structural measurements only; sermon correctness is not known.",
        }
    if fixture.expected_outcome == "no_sermon":
        if stage_key != "final":
            return {
                "status": "informational",
                "code": "negative_fixture_intermediate_candidate",
                "message": (
                    "Intermediate candidates are diagnostic and are not failures by themselves."
                ),
            }
        accepted = final_disposition == "accepted_sermon"
        return {
            "status": "fail" if accepted else "pass",
            "code": "negative_fixture_accepted" if accepted else "negative_fixture_not_accepted",
            "message": (
                "A reviewed no-sermon recording was accepted."
                if accepted
                else "The reviewed no-sermon recording was not automatically accepted."
            ),
        }
    if stage_key == "rule":
        return {
            "status": "informational",
            "code": "comparison_baseline",
            "observed": measurements.get("reviewed_sermon_coverage"),
            "message": "The rule window is a comparator, not a required pipeline predecessor.",
        }
    coverage = measurements.get("reviewed_sermon_coverage")
    passed = isinstance(coverage, (int, float)) and coverage >= REVIEWED_COVERAGE_THRESHOLD
    return {
        "status": "pass" if passed else "fail",
        "code": "reviewed_coverage_sufficient" if passed else "reviewed_coverage_below_contract",
        "threshold": REVIEWED_COVERAGE_THRESHOLD,
        "observed": coverage,
        "message": (
            f"Reviewed-sermon duration coverage is {coverage:.1%}."
            if isinstance(coverage, (int, float))
            else "Reviewed-sermon coverage could not be measured."
        ),
    }


def _make_stage(
    *,
    key: str,
    label: str,
    output: list[Range],
    previous: list[Range],
    expected: list[Range] | None,
    allowed_interruptions: list[Range] | None,
    fixture: ValidatedFixture | None,
    decision: dict[str, Any],
    evidence: dict[str, Any],
    warnings: list[str] | None = None,
    final_disposition: str | None = None,
) -> dict[str, Any]:
    output = _merge_ranges(output)
    previous = _merge_ranges(previous)
    measurements = _stage_measurements(
        output, previous, expected, allowed_interruptions
    )
    previous_boundary = _boundary(previous)
    output_boundary = _boundary(output)
    transition = {
        "start_movement_seconds": (
            round(output_boundary["start_seconds"] - previous_boundary["start_seconds"], 3)
            if previous_boundary is not None and output_boundary is not None
            else None
        ),
        "end_movement_seconds": (
            round(output_boundary["end_seconds"] - previous_boundary["end_seconds"], 3)
            if previous_boundary is not None and output_boundary is not None
            else None
        ),
        "seconds_added": measurements["seconds_added"],
        "seconds_removed": measurements["seconds_removed"],
    }
    return {
        "key": key,
        "label": label,
        "input_ranges": _serialize_ranges(previous),
        "output_ranges": _serialize_ranges(output),
        "input_boundary": previous_boundary,
        "output_boundary": output_boundary,
        "transition": transition,
        "measurements": measurements,
        "decision": decision,
        "evidence": evidence,
        "contract": _contract(
            stage_key=key,
            output=output,
            measurements=measurements,
            fixture=fixture,
            final_disposition=final_disposition,
        ),
        "warnings": warnings or [],
    }


def _observed_failure(stages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for stage in stages:
        contract = stage["contract"]
        if contract.get("status") == "fail":
            return {
                "stage": stage["key"],
                "code": contract.get("code"),
                "message": contract.get("message"),
                "observed": contract.get("observed"),
                "threshold": contract.get("threshold"),
            }
    return None


def _root_cause(
    observed: dict[str, Any] | None,
    stages: list[dict[str, Any]],
    fixture: ValidatedFixture | None,
) -> dict[str, Any]:
    if observed is None:
        return {
            "status": "none_observed",
            "stage": None,
            "code": None,
            "confidence": None,
            "reason": "No evaluated contract violation was observed.",
            "supporting_evidence": [],
            "alternative_causes": [],
        }
    stage = observed["stage"]
    by_key = {item["key"]: item for item in stages}
    if fixture is None:
        return {
            "status": "indeterminate",
            "stage": None,
            "code": "ground_truth_unavailable",
            "confidence": "low",
            "reason": "The trace has structural evidence but no reviewed sermon truth.",
            "supporting_evidence": [],
            "alternative_causes": ["unreviewed content", "missing stage instrumentation"],
        }
    mapping = {
        "transcript": ("transcript", "reviewed_span_absent_from_timed_transcript"),
        "rule": ("rule_baseline", "rule_window_omission"),
        "coarse": ("coarse_discovery", "coarse_candidate_omission"),
        "selected": ("candidate_ranking", "coverage_lost_during_candidate_selection"),
        "joined": ("join_logic", "continuation_not_recovered"),
        "fine": ("fine_refinement", "coverage_lost_during_fine_refinement"),
        "final": ("final_window", "final_window_contract_failure"),
    }
    cause_stage, code = mapping.get(stage, (stage, "unclassified_contract_failure"))
    current = by_key[stage]
    evidence = [
        f"contract={current['contract'].get('code')}",
        f"coverage={current['measurements'].get('reviewed_sermon_coverage')}",
        f"seconds_removed={current['transition'].get('seconds_removed')}",
    ]
    confidence = "high" if stage in {"transcript", "fine", "final"} else "medium"
    alternatives = ["upstream evidence not persisted", "reviewed boundary uncertainty"]
    if stage == "joined":
        confidence = "low"
        alternatives.insert(0, "rejected join attempts are not persisted")
    return {
        "status": "hypothesized",
        "stage": cause_stage,
        "code": code,
        "confidence": confidence,
        "reason": (
            f"The earliest measured coverage contract fails at {stage}; "
            "the hypothesis is limited to persisted evidence."
        ),
        "supporting_evidence": evidence,
        "alternative_causes": alternatives,
    }


def build_diagnostic_trace(
    proposed: dict[str, Any],
    *,
    proposed_path: Path,
    youtube_video_id: str,
    database_video_id: int | None = None,
    fixture: ValidatedFixture | None = None,
    media_duration_seconds: float | None = None,
) -> dict[str, Any]:
    segments = [item for item in proposed.get("segments", []) if isinstance(item, dict)]
    classification = proposed.get("classification")
    classification = classification if isinstance(classification, dict) else {}
    search = classification.get("search")
    search = search if isinstance(search, dict) else {}
    candidates = [item for item in search.get("candidates", []) if isinstance(item, dict)]
    selected = _selected_candidate(search)
    coarse_blocks = _coarse_blocks(classification)

    transcript_ranges = _segment_ranges(segments)
    rule_value = search.get("rule_baseline")
    rule_value = rule_value if isinstance(rule_value, dict) else {}
    rule_range = _range(rule_value.get("start_seconds"), rule_value.get("end_seconds"))
    rule_ranges = [rule_range] if rule_range is not None else []

    ordinary_candidates = [
        item for item in candidates if item.get("source") != "joined_coarse_llm"
    ]
    coarse_ranges = _merge_ranges(
        value
        for candidate in ordinary_candidates
        for value in _candidate_initial_ranges(candidate, coarse_blocks)
    )
    selected_fragments = (
        _candidate_initial_ranges(selected, coarse_blocks) if selected is not None else []
    )
    selected_ranges = selected_fragments
    if (
        selected is not None
        and selected.get("source") == "joined_coarse_llm"
        and selected_fragments
    ):
        joined_ranges = [(selected_fragments[0][0], selected_fragments[-1][1])]
    else:
        joined_ranges = selected_fragments
    retained = classification.get("retained_segment_indexes")
    fine_ranges = _segment_ranges(
        segments,
        retained if isinstance(retained, list) else [],
    )
    sermon_window = proposed.get("sermon_window")
    sermon_window = sermon_window if isinstance(sermon_window, dict) else {}
    final_range = _range(
        sermon_window.get("start_seconds"), sermon_window.get("end_seconds")
    )
    final_ranges = [final_range] if final_range is not None else fine_ranges
    disposition = proposed.get("final_disposition")
    disposition = disposition if isinstance(disposition, dict) else {}
    expected = fixture.expected_spans if fixture and fixture.expected_outcome == "sermon" else None
    allowed_interruptions = (
        fixture.allowed_interruptions
        if fixture and fixture.expected_outcome == "sermon"
        else None
    )
    media_range = _range(0.0, media_duration_seconds)
    transcript_input = [media_range] if media_range is not None else transcript_ranges

    stage_specs = [
        (
            "transcript",
            "Transcript",
            transcript_ranges,
            transcript_input,
            {
                "transcript_source": proposed.get("transcript_source"),
                "media_duration_seconds": media_duration_seconds,
            },
            {
                "timed_segment_count": len(
                    [
                        segment
                        for segment in segments
                        if _range(
                            segment.get("start_seconds"), segment.get("end_seconds")
                        )
                    ]
                ),
                "timestamp_coverage_semantics": (
                    "union of timed transcript spans against known media duration"
                    if media_range is not None
                    else "media duration unavailable"
                ),
            },
            [],
        ),
        (
            "rule",
            "Rule baseline",
            rule_ranges,
            transcript_ranges,
            {
                "algorithm_version": search.get("rule_baseline_algorithm_version"),
                "source": search.get("rule_baseline_source"),
            },
            {"rule_baseline": rule_value},
            [],
        ),
        (
            "coarse",
            "Coarse candidates",
            coarse_ranges,
            transcript_ranges,
            {"discovery": search.get("discovery")},
            {"candidate_count": len(ordinary_candidates)},
            [],
        ),
        (
            "selected",
            "Selected candidate",
            selected_ranges,
            coarse_ranges,
            {
                "selected_rank": search.get("selected_rank"),
                "source": selected.get("source") if selected else None,
            },
            {
                "score": selected.get("score") if selected else None,
                "score_components": selected.get("score_components") if selected else None,
                "boundary_provenance": "reconstructed_from_coarse_support_blocks",
            },
            [],
        ),
        (
            "joined",
            "Post-join",
            joined_ranges,
            selected_ranges,
            {
                "join_selected": bool(selected and selected.get("join")),
                "join": selected.get("join") if selected else None,
            },
            {"rejected_join_attempts": "not_persisted"},
            (
                ["Rejected join attempts are not persisted."]
                if not selected or not selected.get("join")
                else []
            ),
        ),
        (
            "fine",
            "Fine refinement",
            fine_ranges,
            joined_ranges,
            {
                "refinement_reasons": selected.get("refinement_reasons", []) if selected else [],
                "start_refinement": selected.get("start_refinement") if selected else None,
            },
            {"boundary_recovery": selected.get("boundary_recovery") if selected else None},
            (
                list(classification.get("warnings", []))
                if isinstance(classification.get("warnings"), list)
                else []
            ),
        ),
        (
            "final",
            "Final window",
            final_ranges,
            fine_ranges,
            {
                "window_source": sermon_window.get("source"),
                "disposition_status": disposition.get("status"),
                "reason_codes": disposition.get("reason_codes", []),
            },
            {"confidence_tier": classification.get("confidence_tier")},
            [],
        ),
    ]
    stages = [
        _make_stage(
            key=key,
            label=label,
            output=output,
            previous=previous,
            expected=expected,
            allowed_interruptions=allowed_interruptions,
            fixture=fixture,
            decision=decision,
            evidence=evidence,
            warnings=warnings,
            final_disposition=str(disposition.get("status")) if disposition.get("status") else None,
        )
        for key, label, output, previous, decision, evidence, warnings in stage_specs
    ]
    observed = _observed_failure(stages)
    diagnostic_gaps = [
        {
            "code": "rejected_join_attempts_not_persisted",
            "stage": "joined",
            "impact": "Join causality may be indeterminate when no joined candidate was selected.",
            "recommended_instrumentation": (
                "Persist each candidate pair, gap, decision, rejection code, and continuity cues."
            ),
        },
        {
            "code": "selected_pre_refinement_boundary_reconstructed",
            "stage": "selected",
            "impact": "The selected boundary is reconstructed from coarse support blocks.",
            "recommended_instrumentation": (
                "Persist selected candidate boundaries before refinement."
            ),
        },
    ]
    if media_range is None:
        diagnostic_gaps.append(
            {
                "code": "media_duration_unavailable",
                "stage": "transcript",
                "impact": (
                    "Transcript timestamp coverage cannot be compared with the full recording."
                ),
                "recommended_instrumentation": (
                    "Supply the persisted video duration when building the trace."
                ),
            }
        )
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "trace_kind": "sermon_isolation",
        "contract_version": CONTRACT_VERSION,
        "contract_definition": diagnostic_contract_definition(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "video": {
            "database_video_id": database_video_id,
            "youtube_video_id": youtube_video_id,
        },
        "source_artifact": {
            "proposed_path": str(proposed_path),
            "sha256": _sha256(proposed_path),
            "classification_method": classification.get("method"),
            "algorithm_version": search.get("algorithm_version"),
        },
        "ground_truth": {
            "status": "available" if fixture else "not_available",
            "expected_outcome": fixture.expected_outcome if fixture else None,
            "expected_ranges": _serialize_ranges(fixture.expected_spans if fixture else []),
            "allowed_interruptions": _serialize_ranges(
                fixture.allowed_interruptions if fixture else []
            ),
            "fixture_path": str(fixture.path) if fixture else None,
            "ground_truth_version": fixture.ground_truth_version if fixture else None,
        },
        "stages": stages,
        "earliest_observed_failure": observed,
        "root_cause_hypothesis": _root_cause(observed, stages, fixture),
        "diagnostic_gaps": diagnostic_gaps,
    }


def _metric_label(stage: dict[str, Any], has_truth: bool) -> str:
    measurements = stage["measurements"]
    value = (
        measurements.get("reviewed_sermon_coverage")
        if has_truth
        else measurements.get("previous_stage_retention")
    )
    return f"{value:.0%}" if isinstance(value, (int, float)) else "n/a"


def build_pipeline_mermaid(trace: dict[str, Any]) -> str:
    ground_truth = trace.get("ground_truth", {})
    has_truth = (
        ground_truth.get("status") == "available"
        and ground_truth.get("expected_outcome") == "sermon"
    )
    lines = ["flowchart LR"]
    classes: dict[str, list[str]] = {"pass": [], "fail": [], "unknown": []}
    stages = trace.get("stages", [])
    for index, stage in enumerate(stages):
        node = f"S{index}"
        status = str(stage.get("contract", {}).get("status", "unknown"))
        class_key = status if status in {"pass", "fail"} else "unknown"
        classes[class_key].append(node)
        label = f"{stage['label']}<br/>{_metric_label(stage, has_truth)}"
        lines.append(f'  {node}["{label}"]')
        if index:
            transition = stage.get("transition", {})
            removed = transition.get("seconds_removed")
            annotation = (
                f"removed {removed:.0f}s"
                if isinstance(removed, (int, float)) and removed > 0
                else ""
            )
            predecessor = 0 if stage.get("key") == "coarse" else index - 1
            connector = "-.->" if stage.get("key") == "rule" else "-->"
            lines.append(
                f"  S{predecessor} {connector}|{annotation}| {node}"
                if annotation
                else f"  S{predecessor} {connector} {node}"
            )
    lines.extend(
        [
            "  classDef pass fill:#d9f2df,stroke:#26733a,color:#102915",
            "  classDef fail fill:#f9d8d8,stroke:#a52a2a,color:#3b0d0d",
            "  classDef unknown fill:#eceff3,stroke:#65717e,color:#20262c",
        ]
    )
    for class_name, nodes in classes.items():
        if nodes:
            lines.append(f"  class {','.join(nodes)} {class_name}")
    return "\n".join(lines)


def _timeline_bar(
    ranges: list[Range], start: float, end: float, width: int = TIMELINE_WIDTH
) -> str:
    if end <= start:
        return " " * width
    cells = ["·"] * width
    for left, right in ranges:
        first = max(0, min(width - 1, int((left - start) / (end - start) * width)))
        last = max(first + 1, min(width, int((right - start) / (end - start) * width + 0.999)))
        for index in range(first, last):
            cells[index] = "█"
    return "".join(cells)


def build_timeline_markdown(trace: dict[str, Any]) -> str:
    stages = trace.get("stages", [])
    truth = _deserialize_ranges(trace.get("ground_truth", {}).get("expected_ranges"))
    all_ranges = truth + [
        value
        for stage in stages
        for value in _deserialize_ranges(stage.get("output_ranges"))
    ]
    if not all_ranges:
        return "No timestamped diagnostic ranges are available."
    start = min(value[0] for value in all_ranges)
    end = max(value[1] for value in all_ranges)
    rows: list[tuple[str, list[Range]]] = []
    if truth:
        rows.append(("Ground truth", truth))
    rows.extend(
        (str(stage["label"]), _deserialize_ranges(stage.get("output_ranges")))
        for stage in stages
    )
    lines = ["```text", f"Timeline {start:.0f}s{' ' * max(1, TIMELINE_WIDTH - 24)}{end:.0f}s"]
    for label, ranges in rows:
        lines.append(f"{label[:18]:18} {_timeline_bar(ranges, start, end)}")
    lines.append("```")
    return "\n".join(lines)


def build_diagnostic_markdown(trace: dict[str, Any]) -> str:
    video_id = trace["video"]["youtube_video_id"]
    observed = trace.get("earliest_observed_failure")
    cause = trace.get("root_cause_hypothesis", {})
    ground_truth = trace.get("ground_truth", {})
    has_truth = (
        ground_truth.get("status") == "available"
        and ground_truth.get("expected_outcome") == "sermon"
    )
    lines = [
        f"# Pipeline Diagnostic: {video_id}",
        "",
        f"- Trace schema: {trace['schema_version']}",
        f"- Contract version: {trace['contract_version']}",
        f"- Measurement mode: {'reviewed ground truth' if has_truth else 'structural only'}",
        f"- Earliest observed failure: {observed['stage'] if observed else 'none'}",
        f"- Likely causal stage: {cause.get('stage') or 'none'}",
        f"- Causal confidence: {cause.get('confidence') or 'n/a'}",
        "",
        "## Pipeline loss map",
        "",
        "```mermaid",
        build_pipeline_mermaid(trace),
        "```",
        "",
        "## Timeline overlay",
        "",
        build_timeline_markdown(trace),
        "",
        "## Stage transitions",
        "",
        "| Stage | Contract | Boundary | Added | Removed | Coverage/retention | Decision |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for stage in trace["stages"]:
        boundary = stage.get("output_boundary")
        boundary_label = (
            f"{boundary['start_seconds']:.0f}s–{boundary['end_seconds']:.0f}s"
            if boundary else "—"
        )
        decision = json.dumps(stage.get("decision", {}), sort_keys=True)
        lines.append(
            f"| {stage['label']} | {stage['contract']['status']} | {boundary_label} | "
            f"{stage['transition']['seconds_added']:.0f}s | "
            f"{stage['transition']['seconds_removed']:.0f}s | "
            f"{_metric_label(stage, has_truth)} | `{decision}` |"
        )
    lines.extend(["", "## Coverage and contamination tradeoffs", ""])
    if not has_truth:
        lines.append(
            "Ground truth is unavailable; no sermon recall or contamination claims are made."
        )
    else:
        lines.extend(
            [
                "| Stage | Recall | Δ recall | Contamination | Δ contamination |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        previous_recall: float | None = None
        previous_contamination: float | None = None
        for stage in trace["stages"]:
            measurements = stage["measurements"]
            recall = measurements.get("reviewed_sermon_coverage")
            contamination = measurements.get("contamination_ratio")
            delta_recall = (
                recall - previous_recall
                if isinstance(recall, (int, float)) and previous_recall is not None
                else None
            )
            delta_contamination = (
                contamination - previous_contamination
                if isinstance(contamination, (int, float))
                and previous_contamination is not None
                else None
            )
            lines.append(
                f"| {stage['label']} | {recall:.1%} | "
                f"{delta_recall:+.1%} | {contamination:.1%} | {delta_contamination:+.1%} |"
                if delta_recall is not None and delta_contamination is not None
                else f"| {stage['label']} | {recall:.1%} | — | {contamination:.1%} | — |"
            )
            previous_recall = recall if isinstance(recall, (int, float)) else previous_recall
            previous_contamination = (
                contamination
                if isinstance(contamination, (int, float))
                else previous_contamination
            )
    lines.extend(
        [
            "",
            "## Causal assessment",
            "",
            f"{cause.get('reason', 'No causal assessment available.')}",
            "",
            "Supporting evidence:",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in cause.get("supporting_evidence", []))
    lines.extend(["", "Alternative causes:", ""])
    lines.extend(f"- {item}" for item in cause.get("alternative_causes", []))
    lines.extend(["", "## Diagnostic gaps", ""])
    for gap in trace.get("diagnostic_gaps", []):
        lines.append(
            f"- `{gap['code']}`: {gap['impact']} Next: {gap['recommended_instrumentation']}"
        )
    lines.append("")
    return "\n".join(lines)


def aggregate_diagnostic_traces(
    traces: list[dict[str, Any]],
    *,
    missing: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    observed = Counter(
        (trace.get("earliest_observed_failure") or {}).get("stage") or "none"
        for trace in traces
    )
    causes = Counter(
        (trace.get("root_cause_hypothesis") or {}).get("code") or "none"
        for trace in traces
    )
    affected: dict[str, list[str]] = {}
    for trace in traces:
        failure = (trace.get("earliest_observed_failure") or {}).get("stage") or "none"
        affected.setdefault(str(failure), []).append(str(trace["video"]["youtube_video_id"]))
    return {
        "schema_version": 1,
        "report_kind": "sermon_isolation_systemic_diagnostics",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trace_count": len(traces),
        "missing_count": len(missing or []),
        "observed_failure_counts": dict(sorted(observed.items())),
        "root_cause_hypothesis_counts": dict(sorted(causes.items())),
        "affected_video_ids_by_observed_failure": {
            key: sorted(value) for key, value in sorted(affected.items())
        },
        "missing": missing or [],
        "traces": traces,
    }


def build_systemic_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Systemic Pipeline Diagnostics",
        "",
        f"- Traces: {report['trace_count']}",
        f"- Missing artifacts: {report['missing_count']}",
        "",
        "## Observed contract violations",
        "",
        "```text",
        "Low-quality outcomes",
    ]
    for stage, count in sorted(
        report["observed_failure_counts"].items(), key=lambda item: (-item[1], item[0])
    ):
        lines.append(f"├── {stage}: {count}")
    lines.extend(["```", "", "## Root-cause hypotheses", ""])
    lines.append(
        "Observed violations and causal hypotheses are intentionally aggregated separately."
    )
    lines.extend(["", "| Hypothesis | Count |", "|---|---:|"])
    for code, count in sorted(
        report["root_cause_hypothesis_counts"].items(), key=lambda item: (-item[1], item[0])
    ):
        lines.append(f"| {code} | {count} |")
    lines.extend(["", "## Affected runs", ""])
    for stage, video_ids in report["affected_video_ids_by_observed_failure"].items():
        lines.append(f"- **{stage}**: {', '.join(video_ids)}")
    lines.append("")
    return "\n".join(lines)
