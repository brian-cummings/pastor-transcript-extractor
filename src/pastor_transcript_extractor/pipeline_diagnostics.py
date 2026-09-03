from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from pastor_transcript_extractor.fixture_validation import ValidatedFixture


TRACE_SCHEMA_VERSION = 7
CONTRACT_VERSION = "sermon-isolation-contracts-v6"
REVIEWED_COVERAGE_THRESHOLD = 0.90
MAX_CONTAMINATION_RATIO = 0.10
MATERIAL_COVERAGE_DELTA = 0.01
MATERIAL_CONTAMINATION_DELTA = 0.01
MATERIAL_BOUNDARY_SECONDS = 5.0
COMPONENT_FINGERPRINT_VERSION = 3
TIMELINE_WIDTH = 72


Range = tuple[float, float]

RECALL_SENSITIVITY_THRESHOLDS = (0.80, 0.90, 0.95, 0.99)
CONTAMINATION_SENSITIVITY_THRESHOLDS = (0.05, 0.10, 0.20, 0.30)


def diagnostic_contract_definition() -> dict[str, Any]:
    """Return the versioned contract snapshot embedded in every trace."""
    return {
        "version": CONTRACT_VERSION,
        "stage_order": [
            "transcript",
            "rule",
            "coarse_evidence",
            "candidates",
            "selected",
            "joined",
            "fine",
            "arbitration",
            "verifier",
            "final",
        ],
        "downstream_identity_stage_order": [
            "speaker_observation",
            "shadow_association",
            "profile_membership",
        ],
        "reviewed_sermon_coverage_threshold": REVIEWED_COVERAGE_THRESHOLD,
        "maximum_contamination_ratio": MAX_CONTAMINATION_RATIO,
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
            "candidate_regret": (
                "best candidate reviewed coverage minus selected candidate reviewed coverage"
            ),
            "candidate_precision": (
                "per-candidate reviewed coverage, contamination, boundary error, and "
                "coverage/precision Pareto frontier"
            ),
            "contamination_attribution": (
                "first selected-path stage above the contamination contract, later recovery, "
                "and start, end, or internal contamination duration"
            ),
            "stage_regret": (
                "reviewed quality lost between selected, refined, arbitrated, and rejected "
                "alternative windows; never available to production decisions"
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
            "coarse_evidence": (
                "supporting evidence blocks, not the temporal extent of candidate proposals"
            ),
            "candidate_envelope": (
                "persisted candidate start_seconds and end_seconds define proposed coverage"
            ),
            "manual_override": (
                "reviewed final output; automatic pre-override outcome must be reported separately"
            ),
            "overall_outcome": (
                "composition of existence, localization, contamination, verifier, disposition, and "
                "manual-override state without hiding the component contracts"
            ),
            "identity_boundary_feedback": (
                "speaker-consistency evidence is a boundary advisory; causality is claimed only "
                "when an artifact explicitly persists the resulting adjustment"
            ),
            "identity_outcome": (
                "operational progress only; machine association is not speaker truth, and "
                "effective reviewed profile membership is the confirmed identity evidence"
            ),
            "component_fingerprints": (
                "semantic hashes of stage projections distinguish behavior changes from "
                "whole-file artifact rewrites"
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


def _clip_ranges(
    ranges: Iterable[Range], *, start: float | None = None, end: float | None = None
) -> list[Range]:
    clipped: list[Range] = []
    for left, right in ranges:
        clipped_left = max(left, start) if start is not None else left
        clipped_right = min(right, end) if end is not None else right
        if clipped_right > clipped_left:
            clipped.append((clipped_left, clipped_right))
    return _merge_ranges(clipped)


def _unaccepted_duration(
    output: Iterable[Range], accepted: Iterable[Range]
) -> float:
    output_ranges = _merge_ranges(output)
    return max(
        0.0,
        _duration(output_ranges) - _intersection_duration(output_ranges, accepted),
    )


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


def _semantic_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _artifact_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _trace_component_fingerprints(trace: dict[str, Any]) -> dict[str, Any]:
    """Hash behaviorally meaningful trace projections, not whole artifact bytes."""
    stages = {stage.get("key"): stage for stage in trace.get("stages", [])}

    def stage_output(stage_key: str) -> list[dict[str, Any]]:
        stage = stages.get(stage_key) or {}
        return stage.get("output_ranges", [])

    identity_events = []
    for raw in trace.get("identity_boundary_feedback", {}).get("events", []) or []:
        event = {
            key: raw.get(key)
            for key in (
                "source",
                "observation_id",
                "edge",
                "evidence_window",
                "flagged_span",
                "window_fraction",
                "relationship",
                "decision",
                "automatic_boundary_change_allowed",
                "reason_codes",
                "association_versions",
                "model_fingerprints",
                "causal_adjustment_persisted",
            )
        }
        identity_events.append(event)
    contracts = trace.get("outcome_contracts", {})
    components = {
        "transcript": {
            "output_ranges": stage_output("transcript"),
            "source": (stages.get("transcript") or {})
            .get("decision", {})
            .get("transcript_source"),
        },
        "candidate_discovery": {
            "coarse_evidence_ranges": stage_output("coarse_evidence"),
            "candidate_envelope_ranges": stage_output("candidates"),
        },
        "selected_candidate": stage_output("selected"),
        "fine_refinement": stage_output("fine"),
        "arbitration_final_window": {
            "arbitration_ranges": stage_output("arbitration"),
            "final_ranges": stage_output("final"),
        },
        "recording_verifier": (stages.get("verifier") or {}).get("decision", {}),
        "final_disposition": {
            "decision": (stages.get("final") or {}).get("decision", {}),
            "value": contracts.get("disposition", {}).get("value")
            or (stages.get("final") or {})
            .get("decision", {})
            .get("disposition_status"),
        },
        "identity_outcome": trace.get("identity_outcome", {}),
        "identity_feedback": identity_events,
    }
    return {
        "version": COMPONENT_FINGERPRINT_VERSION,
        "components": {
            key: _semantic_sha256(value) for key, value in components.items()
        },
    }


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


def _candidate_support_ranges(
    candidate: dict[str, Any], coarse: dict[int, Range]
) -> list[Range]:
    support = candidate.get("coarse_support_block_ids")
    supported = [
        coarse[block_id]
        for block_id in support if isinstance(block_id, int) and block_id in coarse
    ] if isinstance(support, list) else []
    return _merge_ranges(supported)


def _candidate_envelope_ranges(candidate: dict[str, Any]) -> list[Range]:
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


def _fixture_metadata(fixture: ValidatedFixture | None) -> dict[str, Any]:
    if fixture is None:
        return {
            "evaluation_partition": "unreviewed",
            "source_family_id": "unknown",
            "selection_origin": "unknown",
        }
    try:
        payload = json.loads(fixture.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    manifest = payload.get("selection_manifest") if isinstance(payload, dict) else None
    manifest = manifest if isinstance(manifest, dict) else {}
    return {
        "evaluation_partition": manifest.get("evaluation_partition") or "unknown",
        "source_family_id": manifest.get("source_family_id") or "unknown",
        "selection_origin": manifest.get("selection_origin") or "unknown",
    }


def _candidate_regret(
    candidates: list[dict[str, Any]],
    selected: dict[str, Any] | None,
    expected: list[Range] | None,
    allowed_interruptions: list[Range] | None,
    fine_coverage: object,
) -> dict[str, Any]:
    if expected is None:
        return {"status": "not_evaluated", "reason": "positive_ground_truth_unavailable"}
    expected_duration = _duration(expected)

    accepted = [*expected, *(allowed_interruptions or [])]

    def candidate_metrics(candidate: dict[str, Any]) -> dict[str, float]:
        ranges = _candidate_envelope_ranges(candidate)
        output_duration = _duration(ranges)
        reviewed_coverage = (
            _intersection_duration(ranges, expected) / expected_duration
            if expected_duration
            else 0.0
        )
        contamination = (
            _unaccepted_duration(ranges, accepted) / output_duration
            if output_duration
            else 0.0
        )
        boundary = _boundary(ranges)
        expected_boundary = _boundary(expected)
        start_error = (
            boundary["start_seconds"] - expected_boundary["start_seconds"]
            if boundary is not None and expected_boundary is not None
            else 0.0
        )
        end_error = (
            boundary["end_seconds"] - expected_boundary["end_seconds"]
            if boundary is not None and expected_boundary is not None
            else 0.0
        )
        return {
            "reviewed_sermon_coverage": round(reviewed_coverage, 6),
            "contamination_ratio": round(contamination, 6),
            "output_duration_seconds": round(output_duration, 3),
            "start_error_seconds": round(start_error, 3),
            "end_error_seconds": round(end_error, 3),
        }

    rows = [
        {
            "rank": candidate.get("rank"),
            "source": candidate.get("source"),
            **candidate_metrics(candidate),
            "selected": candidate is selected,
        }
        for candidate in candidates
    ]
    best = max(rows, key=lambda row: row["reviewed_sermon_coverage"], default=None)
    union_ranges = _merge_ranges(
        value for candidate in candidates for value in _candidate_envelope_ranges(candidate)
    )
    union_coverage = (
        _intersection_duration(union_ranges, expected) / expected_duration
        if expected_duration
        else 0.0
    )
    selected_metrics = candidate_metrics(selected) if selected is not None else None
    selected_coverage = (
        selected_metrics["reviewed_sermon_coverage"] if selected_metrics else 0.0
    )
    best_coverage = float(best["reviewed_sermon_coverage"]) if best is not None else 0.0
    if union_coverage < REVIEWED_COVERAGE_THRESHOLD:
        classification = "discovery_omission"
    elif (
        best_coverage >= REVIEWED_COVERAGE_THRESHOLD
        and selected_coverage < REVIEWED_COVERAGE_THRESHOLD
    ):
        classification = "ranking_loss"
    elif (
        selected_coverage >= REVIEWED_COVERAGE_THRESHOLD
        and isinstance(fine_coverage, (int, float))
        and fine_coverage < REVIEWED_COVERAGE_THRESHOLD
    ):
        classification = "refinement_loss"
    else:
        classification = "none"
    viable = [
        row
        for row in rows
        if row["reviewed_sermon_coverage"] >= REVIEWED_COVERAGE_THRESHOLD
    ]
    clean_viable = [
        row
        for row in viable
        if row["contamination_ratio"] <= MAX_CONTAMINATION_RATIO
    ]
    best_precision = min(
        viable,
        key=lambda row: (
            row["contamination_ratio"],
            -row["reviewed_sermon_coverage"],
            row.get("rank") if isinstance(row.get("rank"), int) else 10**9,
        ),
        default=None,
    )
    pareto_frontier = [
        row
        for row in rows
        if not any(
            other is not row
            and other["reviewed_sermon_coverage"] >= row["reviewed_sermon_coverage"]
            and other["contamination_ratio"] <= row["contamination_ratio"]
            and (
                other["reviewed_sermon_coverage"] > row["reviewed_sermon_coverage"]
                or other["contamination_ratio"] < row["contamination_ratio"]
            )
            for other in rows
        )
    ]
    selected_contamination = (
        selected_metrics["contamination_ratio"] if selected_metrics else None
    )
    if not viable:
        precision_classification = "not_applicable_localization_failure"
    elif (
        isinstance(selected_contamination, (int, float))
        and selected_coverage >= REVIEWED_COVERAGE_THRESHOLD
        and selected_contamination <= MAX_CONTAMINATION_RATIO
    ):
        precision_classification = "selected_candidate_acceptable"
    elif not clean_viable:
        precision_classification = "proposal_boundary_failure"
    else:
        clean_best_coverage = max(
            row["reviewed_sermon_coverage"] for row in clean_viable
        )
        precision_classification = (
            "ranking_precision_loss"
            if clean_best_coverage
            >= selected_coverage - MATERIAL_COVERAGE_DELTA
            else "recall_precision_tradeoff"
        )
    return {
        "status": "evaluated",
        "classification": classification,
        "candidate_union_coverage": round(union_coverage, 6),
        "best_candidate_coverage": round(best_coverage, 6),
        "best_candidate_rank": best.get("rank") if best else None,
        "selected_candidate_coverage": round(selected_coverage, 6),
        "selected_candidate_regret": round(max(0.0, best_coverage - selected_coverage), 6),
        "precision_classification": precision_classification,
        "best_precision_candidate_rank": (
            best_precision.get("rank") if best_precision else None
        ),
        "best_precision_candidate_coverage": (
            best_precision.get("reviewed_sermon_coverage") if best_precision else None
        ),
        "best_precision_candidate_contamination": (
            best_precision.get("contamination_ratio") if best_precision else None
        ),
        "pareto_candidate_ranks": [row.get("rank") for row in pareto_frontier],
        "candidates": rows,
    }


def _contamination_attribution(
    stages: list[dict[str, Any]], fixture: ValidatedFixture | None
) -> dict[str, Any]:
    if fixture is None or fixture.expected_outcome != "sermon":
        return {"status": "not_evaluated", "reason": "positive_ground_truth_unavailable"}
    tracked = {"selected", "joined", "fine", "arbitration", "final"}
    expected = list(fixture.expected_spans)
    accepted = [*expected, *fixture.allowed_interruptions]
    expected_boundary = _boundary(expected)
    series: list[dict[str, Any]] = []
    previous: float | None = None
    previous_components: dict[str, float] | None = None
    for stage in stages:
        if stage["key"] not in tracked:
            continue
        value = stage["measurements"].get("contamination_ratio")
        if not isinstance(value, (int, float)):
            continue
        output = _deserialize_ranges(stage.get("output_ranges"))
        total_seconds = _unaccepted_duration(output, accepted)
        if expected_boundary is not None:
            start_seconds = _unaccepted_duration(
                _clip_ranges(output, end=expected_boundary["start_seconds"]),
                accepted,
            )
            end_seconds = _unaccepted_duration(
                _clip_ranges(output, start=expected_boundary["end_seconds"]),
                accepted,
            )
        else:
            start_seconds = 0.0
            end_seconds = 0.0
        components = {
            "start_overreach_seconds": round(start_seconds, 3),
            "end_overreach_seconds": round(end_seconds, 3),
            "internal_contamination_seconds": round(
                max(0.0, total_seconds - start_seconds - end_seconds), 3
            ),
        }
        series.append(
            {
                "stage": stage["key"],
                "contamination_ratio": value,
                "delta": round(value - previous, 6) if previous is not None else None,
                **components,
                "component_deltas": (
                    {
                        key: round(value - previous_components[key], 3)
                        for key, value in components.items()
                    }
                    if previous_components is not None
                    else None
                ),
            }
        )
        previous = value
        previous_components = components
    breach_indexes = [
        index
        for index, item in enumerate(series)
        if item["contamination_ratio"] > MAX_CONTAMINATION_RATIO
    ]
    earliest = series[breach_indexes[0]]["stage"] if breach_indexes else None
    recovery = None
    if breach_indexes:
        recovery = next(
            (
                item["stage"]
                for item in series[breach_indexes[0] + 1 :]
                if item["contamination_ratio"] <= MAX_CONTAMINATION_RATIO
            ),
            None,
        )
    final = next(stage for stage in stages if stage["key"] == "final")
    measurements = final["measurements"]
    patterns: list[str] = []
    start_error = measurements.get("start_error_seconds")
    end_error = measurements.get("end_error_seconds")
    if isinstance(start_error, (int, float)):
        if start_error < 0:
            patterns.append("start_overreach")
        elif start_error > 0:
            patterns.append("start_clipped")
    if isinstance(end_error, (int, float)):
        if end_error > 0:
            patterns.append("end_overreach")
        elif end_error < 0:
            patterns.append("end_clipped")
    final_components = series[-1] if series else {}
    component_causes: dict[str, str] = {}
    for component in (
        "start_overreach_seconds",
        "end_overreach_seconds",
        "internal_contamination_seconds",
    ):
        if float(final_components.get(component) or 0.0) < MATERIAL_BOUNDARY_SECONDS:
            continue
        cause = next(
            (
                item["stage"]
                for item in series
                if float(item.get(component) or 0.0) >= MATERIAL_BOUNDARY_SECONDS
            ),
            None,
        )
        if cause is not None:
            component_causes[component] = cause
    material_patterns = [
        name.removesuffix("_seconds")
        for name in ("start_overreach_seconds", "end_overreach_seconds")
        if float(final_components.get(name) or 0.0) >= MATERIAL_BOUNDARY_SECONDS
    ]
    if float(final_components.get("internal_contamination_seconds") or 0.0) >= (
        MATERIAL_BOUNDARY_SECONDS
    ):
        material_patterns.append("internal_contamination")
    return {
        "status": "evaluated",
        "earliest_breach_stage": earliest,
        "recovery_stage": recovery,
        "final_boundary_error_patterns": patterns or ["aligned"],
        "material_final_contamination_patterns": material_patterns or ["none"],
        "terminal_component_causal_stages": component_causes,
        "final_contamination_seconds": {
            key: final_components.get(key)
            for key in (
                "start_overreach_seconds",
                "end_overreach_seconds",
                "internal_contamination_seconds",
            )
        },
        "stage_deltas": series,
    }


def _stage_regret(
    stages: list[dict[str, Any]], fixture: ValidatedFixture | None
) -> dict[str, Any]:
    if fixture is None or fixture.expected_outcome != "sermon":
        unavailable = {
            "status": "not_evaluated",
            "reason": "positive_ground_truth_unavailable",
        }
        return {"refinement": dict(unavailable), "arbitration": dict(unavailable)}
    by_key = {stage["key"]: stage for stage in stages}

    def metrics(stage_key: str) -> dict[str, Any]:
        measurements = by_key[stage_key]["measurements"]
        return {
            "reviewed_sermon_coverage": measurements.get("reviewed_sermon_coverage"),
            "contamination_ratio": measurements.get("contamination_ratio"),
            "output_duration_seconds": measurements.get("output_duration_seconds"),
        }

    selected = metrics("selected")
    fine = metrics("fine")
    selected_coverage = selected["reviewed_sermon_coverage"]
    fine_coverage = fine["reviewed_sermon_coverage"]
    selected_contamination = selected["contamination_ratio"]
    fine_contamination = fine["contamination_ratio"]
    coverage_delta = (
        round(fine_coverage - selected_coverage, 6)
        if isinstance(selected_coverage, (int, float))
        and isinstance(fine_coverage, (int, float))
        else None
    )
    contamination_delta = (
        round(fine_contamination - selected_contamination, 6)
        if isinstance(selected_contamination, (int, float))
        and isinstance(fine_contamination, (int, float))
        else None
    )
    structural_retention = by_key["fine"]["measurements"].get(
        "previous_stage_retention"
    )
    if (
        isinstance(selected_coverage, (int, float))
        and selected_coverage >= REVIEWED_COVERAGE_THRESHOLD
        and isinstance(fine_coverage, (int, float))
        and fine_coverage < REVIEWED_COVERAGE_THRESHOLD
    ):
        refinement_classification = "localization_regression"
    elif (
        isinstance(coverage_delta, (int, float))
        and coverage_delta <= -0.25
    ) or (
        isinstance(structural_retention, (int, float))
        and structural_retention < 0.5
    ):
        refinement_classification = "catastrophic_structural_loss"
    elif isinstance(contamination_delta, (int, float)) and contamination_delta >= 0.05:
        refinement_classification = "contamination_regression"
    elif (
        isinstance(contamination_delta, (int, float))
        and contamination_delta <= -0.05
    ):
        refinement_classification = "contamination_improved"
    else:
        refinement_classification = "none"
    refinement = {
        "status": "evaluated",
        "classification": refinement_classification,
        "selected": selected,
        "fine": fine,
        "coverage_delta": coverage_delta,
        "contamination_delta": contamination_delta,
        "structural_retention": structural_retention,
    }

    rule = metrics("rule")
    final = metrics("final")
    fine_coverage = fine["reviewed_sermon_coverage"]
    final_coverage = final["reviewed_sermon_coverage"]
    fine_contamination = fine["contamination_ratio"]
    final_contamination = final["contamination_ratio"]
    coverage_regret = (
        round(max(0.0, fine_coverage - final_coverage), 6)
        if isinstance(fine_coverage, (int, float))
        and isinstance(final_coverage, (int, float))
        else None
    )
    contamination_regret = (
        round(max(0.0, final_contamination - fine_contamination), 6)
        if isinstance(fine_contamination, (int, float))
        and isinstance(final_contamination, (int, float))
        else None
    )
    if (
        isinstance(fine_coverage, (int, float))
        and fine_coverage >= REVIEWED_COVERAGE_THRESHOLD
        and isinstance(final_coverage, (int, float))
        and final_coverage < REVIEWED_COVERAGE_THRESHOLD
    ):
        arbitration_classification = "localization_regression"
    elif isinstance(contamination_regret, (int, float)) and contamination_regret >= 0.05:
        arbitration_classification = "contamination_regression"
    elif (
        isinstance(coverage_regret, (int, float))
        and coverage_regret >= MATERIAL_COVERAGE_DELTA
    ) or (
        isinstance(contamination_regret, (int, float))
        and contamination_regret >= MATERIAL_CONTAMINATION_DELTA
    ):
        arbitration_classification = "material_tradeoff"
    else:
        arbitration_classification = "none"
    arbitration_evidence = by_key["arbitration"].get("evidence", {}).get(
        "arbitration", {}
    )
    arbitration = {
        "status": "evaluated",
        "classification": arbitration_classification,
        "fine": fine,
        "rule": rule,
        "chosen_final": final,
        "coverage_regret_against_fine": coverage_regret,
        "contamination_regret_against_fine": contamination_regret,
        "materiality_thresholds": {
            "coverage_delta": MATERIAL_COVERAGE_DELTA,
            "contamination_delta": MATERIAL_CONTAMINATION_DELTA,
        },
        "decision": (
            arbitration_evidence.get("decision")
            if isinstance(arbitration_evidence, dict)
            else None
        ),
        "reason": (
            arbitration_evidence.get("reason")
            if isinstance(arbitration_evidence, dict)
            else None
        ),
        "measurement_semantics": "reviewed counterfactual; unavailable to production policy",
    }
    return {"refinement": refinement, "arbitration": arbitration}


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
        output_boundary = _boundary(output)
        expected_boundary = _boundary(expected)
        if output_boundary is not None and expected_boundary is not None:
            start_error = (
                output_boundary["start_seconds"] - expected_boundary["start_seconds"]
            )
            end_error = output_boundary["end_seconds"] - expected_boundary["end_seconds"]
            measurements.update(
                {
                    "start_error_seconds": round(start_error, 3),
                    "end_error_seconds": round(end_error, 3),
                    "missing_start_seconds": round(max(0.0, start_error), 3),
                    "missing_end_seconds": round(max(0.0, -end_error), 3),
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
    if stage_key in {"rule", "coarse_evidence"}:
        return {
            "status": "informational",
            "code": (
                "comparison_baseline"
                if stage_key == "rule"
                else "supporting_evidence_not_candidate_extent"
            ),
            "observed": measurements.get("reviewed_sermon_coverage"),
            "message": (
                "The rule window is a comparator, not a required pipeline predecessor."
                if stage_key == "rule"
                else "Coarse blocks support proposals but do not define candidate coverage."
            ),
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


def _quality_contracts(
    measurements: dict[str, Any], fixture: ValidatedFixture | None
) -> dict[str, dict[str, Any]]:
    if fixture is None or fixture.expected_outcome != "sermon":
        return {
            "localization": {"status": "not_evaluated"},
            "contamination": {"status": "not_evaluated"},
        }
    coverage = measurements.get("reviewed_sermon_coverage")
    contamination = measurements.get("contamination_ratio")
    return {
        "localization": {
            "status": (
                "pass"
                if isinstance(coverage, (int, float))
                and coverage >= REVIEWED_COVERAGE_THRESHOLD
                else "fail"
            ),
            "observed": coverage,
            "threshold": REVIEWED_COVERAGE_THRESHOLD,
        },
        "contamination": {
            "status": (
                "pass"
                if isinstance(contamination, (int, float))
                and contamination <= MAX_CONTAMINATION_RATIO
                else "fail"
            ),
            "observed": contamination,
            "threshold": MAX_CONTAMINATION_RATIO,
        },
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
    stage = {
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
    stage["quality_contracts"] = _quality_contracts(measurements, fixture)
    return stage


def _observed_failure(stages: list[dict[str, Any]]) -> dict[str, Any] | None:
    contamination_tracked = {"selected", "joined", "fine", "arbitration", "final"}
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
        contamination = stage.get("quality_contracts", {}).get("contamination", {})
        if stage["key"] in contamination_tracked and contamination.get("status") == "fail":
            return {
                "stage": stage["key"],
                "code": "contamination_above_contract",
                "message": "Selected-path contamination exceeds the precision contract.",
                "observed": contamination.get("observed"),
                "threshold": contamination.get("threshold"),
            }
    return None


def _root_cause(
    observed: dict[str, Any] | None,
    stages: list[dict[str, Any]],
    fixture: ValidatedFixture | None,
    candidate_regret: dict[str, Any] | None = None,
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
        "candidates": ("candidate_discovery", "candidate_envelope_omission"),
        "selected": ("candidate_ranking", "coverage_lost_during_candidate_selection"),
        "joined": ("join_logic", "continuation_not_recovered"),
        "fine": ("fine_refinement", "coverage_lost_during_fine_refinement"),
        "arbitration": ("final_arbitration", "arbitration_selected_inferior_window"),
        "verifier": ("recording_verifier", "recording_verifier_wrong_outcome"),
        "final": ("final_disposition", "final_disposition_contract_failure"),
    }
    cause_stage, code = mapping.get(stage, (stage, "unclassified_contract_failure"))
    if observed.get("code") == "contamination_above_contract":
        code = "contamination_introduced_or_retained"
        precision = (candidate_regret or {}).get("precision_classification")
        precision_causes = {
            "proposal_boundary_failure": (
                "candidate_proposal",
                "candidate_proposals_all_violate_precision_contract",
            ),
            "ranking_precision_loss": (
                "candidate_ranking",
                "cleaner_complete_candidate_not_selected",
            ),
            "recall_precision_tradeoff": (
                "candidate_selection_policy",
                "candidate_recall_precision_tradeoff",
            ),
        }
        if stage == "selected" and precision in precision_causes:
            cause_stage, code = precision_causes[precision]
    current = by_key[stage]
    evidence = [
        f"contract={current['contract'].get('code')}",
        f"coverage={current['measurements'].get('reviewed_sermon_coverage')}",
        f"contamination={current['measurements'].get('contamination_ratio')}",
        f"seconds_removed={current['transition'].get('seconds_removed')}",
    ]
    if candidate_regret and stage == "selected":
        evidence.append(
            "candidate_precision="
            f"{candidate_regret.get('precision_classification', 'not_evaluated')}"
        )
    confidence = (
        "high"
        if stage in {"transcript", "fine", "arbitration", "verifier", "final"}
        else "medium"
    )
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
            f"The earliest measured quality contract fails at {stage}; "
            "the hypothesis is limited to persisted evidence."
        ),
        "supporting_evidence": evidence,
        "alternative_causes": alternatives,
    }


def _verifier_contract(
    verification: dict[str, Any], fixture: ValidatedFixture | None
) -> dict[str, Any]:
    source = verification.get("source")
    decision = verification.get("decision")
    predicted = verification.get("predicted_outcome")
    if fixture is None:
        return {
            "status": "not_evaluated",
            "code": "ground_truth_unavailable",
            "message": "Recording-verifier correctness is not known.",
        }
    if source in {None, "not_required"} or (decision is None and predicted is None):
        return {
            "status": "informational",
            "code": "recording_verifier_not_invoked",
            "message": "The base classifier resolved the recording without verifier inference.",
        }
    predicted_sermon = (
        predicted == "sermon" or decision == "worship_service_sermon"
    )
    if fixture.expected_outcome == "no_sermon":
        return {
            "status": "fail" if predicted_sermon else "pass",
            "code": (
                "recording_verifier_false_positive"
                if predicted_sermon
                else "recording_verifier_rejected_negative"
            ),
            "message": (
                "The verifier identified a reviewed no-sermon recording as a sermon."
                if predicted_sermon
                else "The verifier did not identify the reviewed negative as a sermon."
            ),
        }
    explicitly_negative = predicted not in {None, "sermon"} and not predicted_sermon
    return {
        "status": "fail" if explicitly_negative else "pass",
        "code": (
            "recording_verifier_false_negative"
            if explicitly_negative
            else "recording_verifier_supported_positive"
        ),
        "message": (
            "The verifier rejected a reviewed sermon recording."
            if explicitly_negative
            else "The verifier outcome is compatible with the reviewed sermon."
        ),
    }


def _outcome_contracts(
    *,
    stages: list[dict[str, Any]],
    fixture: ValidatedFixture | None,
    final_disposition: str | None,
    manual_override: bool,
) -> dict[str, Any]:
    final = next(stage for stage in stages if stage["key"] == "final")
    if fixture is None:
        existence = {"status": "not_evaluated"}
    elif fixture.expected_outcome == "no_sermon":
        accepted = final_disposition == "accepted_sermon"
        existence = {
            "status": "fail" if accepted else "pass",
            "code": "negative_accepted" if accepted else "negative_not_accepted",
        }
    else:
        rejected = final_disposition in {
            "rejected_no_sermon",
            "rejected_ambiguous_speakers",
        }
        existence = {
            "status": "fail" if rejected else "pass",
            "code": "positive_rejected" if rejected else "positive_sermon_retained",
        }
    verifier = next(stage for stage in stages if stage["key"] == "verifier")
    if fixture is None:
        disposition_contract = {"status": "not_evaluated"}
    elif fixture.expected_outcome == "no_sermon":
        disposition_contract = {
            "status": "fail" if final_disposition == "accepted_sermon" else (
                "review_required" if final_disposition == "review_required" else "pass"
            )
        }
    else:
        disposition_contract = {
            "status": (
                "pass" if final_disposition == "accepted_sermon" else
                "review_required" if final_disposition == "review_required" else "fail"
            )
        }
    return {
        "existence": existence,
        "localization": final["quality_contracts"]["localization"],
        "contamination": final["quality_contracts"]["contamination"],
        "disposition": {
            **disposition_contract,
            "value": final_disposition or "unknown",
            "automatically_accepted": final_disposition == "accepted_sermon",
        },
        "verifier": dict(verifier["contract"]),
        "manual_override_applied": manual_override,
    }


def _overall_outcome(outcome_contracts: dict[str, Any]) -> dict[str, Any]:
    dimensions = ("existence", "localization", "contamination", "verifier", "disposition")
    failed = [
        dimension
        for dimension in dimensions
        if outcome_contracts.get(dimension, {}).get("status") == "fail"
    ]
    evaluated = [
        dimension
        for dimension in dimensions
        if outcome_contracts.get(dimension, {}).get("status") in {"pass", "fail"}
    ]
    disposition = outcome_contracts.get("disposition", {}).get("value")
    manual_override = bool(outcome_contracts.get("manual_override_applied"))
    if failed:
        status = "fail"
    elif not evaluated:
        status = "not_evaluated"
    elif disposition == "review_required":
        status = "review_required"
    elif manual_override:
        status = "pass_with_manual_override"
    else:
        status = "pass"
    return {
        "status": status,
        "failed_dimensions": failed,
        "evaluated_dimensions": evaluated,
        "disposition": disposition or "unknown",
        "manual_override_applied": manual_override,
    }


def _contract_paths(
    stages: list[dict[str, Any]], outcome_contracts: dict[str, Any]
) -> dict[str, Any]:
    stage_order = [stage["key"] for stage in stages]

    def measured_path(
        dimension: str, tracked_stages: set[str]
    ) -> dict[str, Any]:
        observations: list[dict[str, Any]] = []
        for stage in stages:
            if stage["key"] not in tracked_stages:
                continue
            contract = stage.get("quality_contracts", {}).get(dimension, {})
            status = contract.get("status")
            if status not in {"pass", "fail"}:
                continue
            observations.append(
                {
                    "stage": stage["key"],
                    "status": status,
                    "observed": contract.get("observed"),
                    "threshold": contract.get("threshold"),
                }
            )
        breach_indexes = [
            index
            for index, observation in enumerate(observations)
            if observation["status"] == "fail"
        ]
        earliest = observations[breach_indexes[0]]["stage"] if breach_indexes else None
        recoveries = [
            observation["stage"]
            for index, observation in enumerate(observations)
            if observation["status"] == "pass"
            and any(breach < index for breach in breach_indexes)
        ]
        terminal = outcome_contracts.get(dimension, {}).get("status", "not_evaluated")
        likely_causal = None
        if terminal == "fail" and breach_indexes:
            last_pass_index = max(
                (
                    index
                    for index, observation in enumerate(observations)
                    if observation["status"] == "pass"
                ),
                default=-1,
            )
            likely_causal = next(
                (
                    observation["stage"]
                    for index, observation in enumerate(observations)
                    if index > last_pass_index and observation["status"] == "fail"
                ),
                earliest,
            )
        return {
            "status": "evaluated" if observations else "not_evaluated",
            "earliest_breach_stage": earliest,
            "recovery_stages": recoveries,
            "terminal_status": terminal,
            "terminal_failure": terminal == "fail",
            "likely_causal_stage": likely_causal,
            "observations": observations,
        }

    localization = measured_path(
        "localization",
        {"transcript", "candidates", "selected", "joined", "fine", "arbitration", "final"},
    )
    contamination = measured_path(
        "contamination", {"selected", "joined", "fine", "arbitration", "final"}
    )

    def terminal_path(dimension: str, stage: str) -> dict[str, Any]:
        contract = outcome_contracts.get(dimension, {})
        status = contract.get("status", "not_evaluated")
        return {
            "status": (
                "evaluated"
                if status in {"pass", "fail", "review_required"}
                else "not_evaluated"
            ),
            "earliest_breach_stage": stage if status == "fail" else None,
            "recovery_stages": [],
            "terminal_status": status,
            "terminal_failure": status == "fail",
            "likely_causal_stage": stage if status == "fail" else None,
            "observations": [
                {"stage": stage, "status": status, "code": contract.get("code")}
            ],
        }

    return {
        "stage_order": stage_order,
        "localization": localization,
        "contamination": contamination,
        "existence": terminal_path("existence", "final"),
        "verifier": terminal_path("verifier", "verifier"),
        "disposition": terminal_path("disposition", "final"),
    }


def _recovery_status(
    observed: dict[str, Any] | None,
    stages: list[dict[str, Any]],
    manual_override: bool,
) -> str:
    if manual_override:
        return "masked_by_manual_override" if observed else "manual_override_applied"
    if observed is None:
        return "clean"
    final = next(stage for stage in stages if stage["key"] == "final")
    return "recovered_automatically" if final["contract"]["status"] == "pass" else "unrecovered"


def load_identity_boundary_feedback(
    root: Path,
    *,
    database_video_ids: set[int] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """Load and deduplicate persisted identity edge advisories by database video id."""
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        return {}
    grouped: dict[int, dict[tuple[Any, ...], dict[str, Any]]] = {}
    for path in sorted(resolved.glob("*/*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        candidate = payload.get("candidate")
        candidate = candidate if isinstance(candidate, dict) else {}
        video_id = candidate.get("video_id")
        observation_id = candidate.get("observation_id")
        if not isinstance(video_id, int):
            continue
        if database_video_ids is not None and video_id not in database_video_ids:
            continue
        flags = payload.get("sermon_window_quality_flags")
        if not isinstance(flags, list):
            continue
        span_selection = payload.get("span_selection")
        span_selection = span_selection if isinstance(span_selection, dict) else {}
        candidate_selection = span_selection.get("candidate_selection")
        candidate_selection = (
            candidate_selection if isinstance(candidate_selection, dict) else {}
        )
        evidence_window = _range(
            candidate_selection.get("observation_start_seconds"),
            candidate_selection.get("observation_end_seconds"),
        )
        for raw_flag in flags:
            if not isinstance(raw_flag, dict):
                continue
            if raw_flag.get("flag") != "speaker_inconsistent_edge":
                continue
            edge = raw_flag.get("edge")
            if edge not in {"start", "end"}:
                continue
            flagged_span = _range(
                raw_flag.get("start_seconds"), raw_flag.get("end_seconds")
            )
            reasons = tuple(
                sorted(
                    str(reason)
                    for reason in raw_flag.get("reason_codes", [])
                    if isinstance(reason, str)
                )
            )
            key = (
                observation_id,
                edge,
                evidence_window,
                flagged_span,
                reasons,
                bool(raw_flag.get("automatic_boundary_change_allowed")),
            )
            events = grouped.setdefault(video_id, {})
            existing = events.get(key)
            if existing is None:
                existing = {
                    "event_kind": "identity_boundary_feedback",
                    "source": "speaker_profile_shadow_association",
                    "observation_id": (
                        observation_id if isinstance(observation_id, int) else None
                    ),
                    "edge": edge,
                    "evidence_window": (
                        {
                            "start_seconds": evidence_window[0],
                            "end_seconds": evidence_window[1],
                        }
                        if evidence_window is not None
                        else None
                    ),
                    "flagged_span": (
                        {
                            "start_seconds": flagged_span[0],
                            "end_seconds": flagged_span[1],
                        }
                        if flagged_span is not None
                        else None
                    ),
                    "window_fraction": raw_flag.get("window_fraction"),
                    "relationship": "speaker_inconsistent_edge",
                    "decision": "boundary_advisory_only",
                    "automatic_boundary_change_allowed": bool(
                        raw_flag.get("automatic_boundary_change_allowed")
                    ),
                    "reason_codes": list(reasons),
                    "association_versions": [],
                    "model_fingerprints": [],
                    "representative_artifact_path": str(path),
                    "artifact_occurrence_count": 0,
                    "causal_adjustment_persisted": False,
                }
                events[key] = existing
            existing["artifact_occurrence_count"] += 1
            association_version = payload.get("association_version")
            if (
                isinstance(association_version, str)
                and association_version not in existing["association_versions"]
            ):
                existing["association_versions"].append(association_version)
            model_fingerprint = payload.get("model_fingerprint")
            if (
                isinstance(model_fingerprint, str)
                and model_fingerprint not in existing["model_fingerprints"]
            ):
                existing["model_fingerprints"].append(model_fingerprint)
    return {
        video_id: sorted(
            events.values(),
            key=lambda event: (
                str(event.get("edge")),
                _number((event.get("flagged_span") or {}).get("start_seconds")) or 0.0,
            ),
        )
        for video_id, events in grouped.items()
    }


def load_identity_association_attempts(
    root: Path,
    *,
    database_video_ids: set[int] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """Load persisted shadow-association outcomes without running identity analysis."""
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        return {}
    grouped: dict[int, dict[tuple[Any, ...], dict[str, Any]]] = {}
    for path in sorted(resolved.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("artifact_kind") != (
            "speaker_profile_shadow_association"
        ):
            continue
        candidate = payload.get("candidate")
        candidate = candidate if isinstance(candidate, dict) else {}
        video_id = candidate.get("video_id")
        observation_id = candidate.get("observation_id")
        outcome = payload.get("outcome")
        if (
            not isinstance(video_id, int)
            or not isinstance(observation_id, int)
            or not isinstance(outcome, str)
        ):
            continue
        if database_video_ids is not None and video_id not in database_video_ids:
            continue
        proposed_profile_id = payload.get("proposed_profile_id")
        result_sha256 = payload.get("result_sha256")
        key = (
            observation_id,
            result_sha256 if isinstance(result_sha256, str) else str(path),
            outcome,
            proposed_profile_id,
        )
        created_at = payload.get("created_at")
        ordering_basis = "artifact_created_at"
        if not isinstance(created_at, str):
            try:
                created_at = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat()
                ordering_basis = "filesystem_mtime_fallback"
            except OSError:
                created_at = ""
                ordering_basis = "artifact_path_fallback"
        routing = payload.get("routing")
        routing = routing if isinstance(routing, dict) else {}
        profiles = payload.get("profiles")
        profiles = profiles if isinstance(profiles, list) else []
        comparisons = [
            comparison
            for profile in profiles
            if isinstance(profile, dict)
            for comparison in profile.get("comparisons", [])
            if isinstance(comparison, dict)
        ]
        comparison_reason_counts: dict[str, int] = {}
        for comparison in comparisons:
            reason = comparison.get("reason")
            if isinstance(reason, str) and reason:
                comparison_reason_counts[reason] = (
                    comparison_reason_counts.get(reason, 0) + 1
                )
        candidate_consistency: dict[str, Any] = {"status": "not_observed"}
        if comparisons:
            first = comparisons[0]
            metrics = first.get("metrics")
            metrics = metrics if isinstance(metrics, Mapping) else {}
            within = metrics.get("within_a")
            within = within if isinstance(within, Mapping) else {}
            policy = first.get("policy")
            policy = policy if isinstance(policy, Mapping) else {}
            median = _number(within.get("median"))
            minimum = _number(policy.get("min_within_median"))
            if median is not None and minimum is not None:
                candidate_consistency = {
                    "status": (
                        "inconsistent" if median < minimum else "coherent"
                    ),
                    "within_observation_median": median,
                    "minimum_within_observation_median": minimum,
                    "evidence_source": "candidate_side_pair_metrics",
                }
        grouped.setdefault(video_id, {})[key] = {
            "artifact_path": str(path),
            "created_at": created_at,
            "ordering_basis": ordering_basis,
            "observation_id": observation_id,
            "observation_fingerprint": candidate.get("input_fingerprint"),
            "outcome": outcome,
            "reason": payload.get("reason"),
            "proposed_profile_id": (
                proposed_profile_id if isinstance(proposed_profile_id, int) else None
            ),
            "association_version": payload.get("association_version"),
            "model_fingerprint": payload.get("model_fingerprint"),
            "result_sha256": result_sha256,
            "candidate_funnel": routing.get("candidate_funnel"),
            "comparison_evidence_summary": {
                "comparison_count": len(comparisons),
                "reason_counts": dict(sorted(comparison_reason_counts.items())),
                "candidate_consistency": candidate_consistency,
            },
            "candidate_self_comparison": any(
                comparison.get("exemplar_observation_id") == observation_id
                for profile in profiles
                if isinstance(profile, dict)
                for comparison in profile.get("comparisons", [])
                if isinstance(comparison, dict)
            ),
            "compared_profiles": [
                {
                    "profile_id": profile.get("profile_id"),
                    "meets_multi_exemplar_match": profile.get(
                        "meets_multi_exemplar_match"
                    ),
                    "comparison_counts": profile.get("comparison_counts"),
                }
                for profile in profiles
                if isinstance(profile, dict)
                and isinstance(profile.get("profile_id"), int)
            ],
        }
    return {
        video_id: list(attempts.values())
        for video_id, attempts in grouped.items()
    }


def load_identity_association_admissions(
    root: Path,
    *,
    database_video_ids: set[int] | None = None,
) -> dict[int, dict[str, Any]]:
    """Load the latest persisted pre-comparison admission per observation."""
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        return {}
    latest: dict[int, dict[str, Any]] = {}
    for path in sorted(resolved.rglob("admission-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("artifact_kind") != (
            "speaker_profile_shadow_association_admission"
        ):
            continue
        candidate = payload.get("candidate")
        candidate = candidate if isinstance(candidate, dict) else {}
        observation_id = candidate.get("observation_id")
        video_id = candidate.get("video_id")
        if not isinstance(observation_id, int) or not isinstance(video_id, int):
            continue
        if database_video_ids is not None and video_id not in database_video_ids:
            continue
        stable_input = payload.get("stable_input")
        expected_input_fingerprint = payload.get("input_fingerprint")
        expected_result_sha256 = payload.get("result_sha256")
        unhashed = dict(payload)
        unhashed.pop("result_sha256", None)
        if (
            not isinstance(stable_input, dict)
            or not isinstance(expected_input_fingerprint, str)
            or _artifact_json_sha256(stable_input) != expected_input_fingerprint
            or not isinstance(expected_result_sha256, str)
            or _artifact_json_sha256(unhashed) != expected_result_sha256
        ):
            continue
        event = {
            "artifact_path": str(path),
            "created_at": payload.get("created_at"),
            "observation_id": observation_id,
            "observation_fingerprint": candidate.get("input_fingerprint"),
            "video_id": video_id,
            "stage": payload.get("stage"),
            "reason_code": payload.get("reason_code"),
            "evidence": payload.get("evidence"),
            "input_fingerprint": expected_input_fingerprint,
        }
        existing = latest.get(observation_id)
        if existing is None or (
            str(event.get("created_at") or ""), str(path)
        ) > (
            str(existing.get("created_at") or ""),
            str(existing.get("artifact_path") or ""),
        ):
            latest[observation_id] = event
    return latest


def _identity_candidate_funnel_projection(
    attempt: dict[str, Any] | None,
    *,
    effective_profile_ids: list[int],
    profile_redirects: dict[int, int],
) -> dict[str, Any]:
    """Locate reviewed identity in persisted routing evidence without inferring cause."""
    if not effective_profile_ids:
        return {"status": "not_applicable", "classification": "identity_unreviewed"}
    if len(effective_profile_ids) != 1:
        return {
            "status": "not_evaluated",
            "classification": "multiple_effective_profiles",
            "effective_profile_ids": effective_profile_ids,
        }
    if attempt is None:
        return {"status": "not_observed", "classification": "attempt_missing"}
    funnel = attempt.get("candidate_funnel")
    if not isinstance(funnel, dict):
        return {
            "status": "not_observed",
            "classification": "candidate_funnel_not_persisted",
        }
    retrospective = funnel.get("retrospective_evaluation")
    if (
        attempt.get("candidate_self_comparison")
        or not isinstance(retrospective, dict)
        or retrospective.get("leave_one_out_applied") is not True
        or retrospective.get("membership_used_as_routing_evidence") is not False
    ):
        return {
            "status": "not_evaluated",
            "classification": "retrospective_membership_leakage",
            "evidence": {
                "candidate_self_comparison": bool(
                    attempt.get("candidate_self_comparison")
                ),
                "retrospective_evaluation": retrospective,
            },
            "causal_hypotheses": [],
        }

    target = effective_profile_ids[0]

    def resolved(profile_id: int) -> int:
        return profile_redirects.get(profile_id, profile_id)

    universe_ids = {
        int(profile_id)
        for profile_id in funnel.get("canonical_profile_ids", [])
        if isinstance(profile_id, int)
    }
    matching_historical_ids = sorted(
        profile_id for profile_id in universe_ids if resolved(profile_id) == target
    )
    exact_id_present = target in universe_ids
    resolution = {
        "effective_profile_id": target,
        "historical_profile_ids": matching_historical_ids,
        "exact_profile_id_present": exact_id_present,
        "redirect_resolution_applied": bool(
            matching_historical_ids and not exact_id_present
        ),
    }
    if not matching_historical_ids:
        return {
            "status": "observed",
            "observed_failure_location": "profile_universe",
            "classification": "profile_redirect_resolution_issue",
            "resolution": resolution,
            "evidence": {
                "historical_canonical_profile_ids": sorted(universe_ids),
            },
            "causal_hypotheses": [
                "profile_was_created_after_attempt",
                "historical_redirect_cannot_be_reconstructed",
                "profile_universe_was_incomplete",
            ],
        }

    excluded_by_id = {
        item.get("profile_id"): item
        for item in funnel.get("excluded_profiles", [])
        if isinstance(item, dict) and isinstance(item.get("profile_id"), int)
    }
    eligible_ids = {
        profile_id
        for profile_id in funnel.get("comparison_eligible_profile_ids", [])
        if isinstance(profile_id, int)
    }
    matching_eligible_ids = [
        profile_id
        for profile_id in matching_historical_ids
        if profile_id in eligible_ids
    ]
    if not matching_eligible_ids:
        exclusions = [
            excluded_by_id[profile_id]
            for profile_id in matching_historical_ids
            if profile_id in excluded_by_id
        ]
        return {
            "status": "observed",
            "observed_failure_location": "eligibility",
            "classification": "correct_profile_ineligible",
            "resolution": resolution,
            "evidence": {"profile_exclusions": exclusions},
            "causal_hypotheses": [],
        }

    retrieval_by_id = {
        item.get("profile_id"): item
        for item in funnel.get("retrieval_candidates", [])
        if isinstance(item, dict) and isinstance(item.get("profile_id"), int)
    }
    entries = [
        retrieval_by_id[profile_id]
        for profile_id in matching_eligible_ids
        if profile_id in retrieval_by_id
    ]
    if not entries:
        return {
            "status": "observed",
            "observed_failure_location": "retrieval",
            "classification": "acoustic_retrieval_miss",
            "resolution": resolution,
            "evidence": {"retrieval_candidate_missing": True},
            "causal_hypotheses": ["retrieval_instrumentation_incomplete"],
        }
    entry = sorted(
        entries,
        key=lambda item: (
            not bool(item.get("selected_for_comparison")),
            item.get("acoustic_rank") or 10**9,
        ),
    )[0]
    source_outcomes = {
        "name": "hit" if entry.get("name_match") else "miss",
        "source": "hit" if entry.get("source_match") else "miss",
        "acoustic": (
            "not_applicable_priority_route"
            if entry.get("acoustic_rank") is None
            and entry.get("selected_for_comparison")
            else "unavailable"
            if entry.get("acoustic_rank") is None
            else "within_cutoff"
            if entry.get("passed_shortlist_cutoff")
            else "below_cutoff"
        ),
        "all_eligible_acoustic_rank": entry.get(
            "all_eligible_acoustic_rank"
        ),
    }
    evidence = {
        "retrieval_candidate": entry,
        "retrieval_source_outcomes": source_outcomes,
        "shortlist": funnel.get("acoustic_shortlist"),
    }
    if not entry.get("routing_policy_eligible"):
        return {
            "status": "observed",
            "observed_failure_location": "readiness_policy_filter",
            "classification": "filtered_by_readiness_policy_before_retrieval",
            "resolution": resolution,
            "evidence": evidence,
            "causal_hypotheses": [],
        }
    if not entry.get("selected_for_comparison"):
        if entry.get("acoustic_rank") is not None:
            classification = "retrieved_below_shortlist_cutoff"
        else:
            classification = "acoustic_retrieval_miss"
        hypotheses = []
        if not entry.get("name_match"):
            hypotheses.append("name_retrieval_route_absent")
        if not entry.get("source_match"):
            hypotheses.append("source_retrieval_route_absent")
        return {
            "status": "observed",
            "observed_failure_location": "retrieval_miss",
            "classification": classification,
            "resolution": resolution,
            "evidence": evidence,
            "causal_hypotheses": hypotheses,
        }

    compared_ids = {
        profile_id
        for profile_id in funnel.get("profiles_actually_compared", [])
        if isinstance(profile_id, int)
    }
    if not any(profile_id in compared_ids for profile_id in matching_historical_ids):
        return {
            "status": "observed",
            "observed_failure_location": "comparison_dispatch",
            "classification": "selected_profile_not_compared",
            "resolution": resolution,
            "evidence": evidence,
            "causal_hypotheses": ["comparison_dispatch_or_artifact_gap"],
        }
    proposed_profile_id = attempt.get("proposed_profile_id")
    if isinstance(proposed_profile_id, int):
        correct = resolved(proposed_profile_id) == target
        classification = (
            "compared_and_proposed_correctly"
            if correct
            else "compared_and_proposed_incorrectly"
        )
    else:
        classification = "compared_but_abstained"
    return {
        "status": "observed",
        "observed_failure_location": (
            None if classification == "compared_and_proposed_correctly" else "comparison"
        ),
        "classification": classification,
        "resolution": resolution,
        "evidence": {
            **evidence,
            "association_outcome": attempt.get("outcome"),
            "proposed_profile_id": proposed_profile_id,
        },
        "causal_hypotheses": [],
    }


def build_identity_operational_outcome(
    *,
    content_disposition: str | None,
    extraction_result_id: int,
    observation: dict[str, Any] | None = None,
    effective_profile_ids: list[int] | None = None,
    association_attempts: list[dict[str, Any]] | None = None,
    boundary_feedback: list[dict[str, Any]] | None = None,
    profile_redirects: dict[int, int] | None = None,
) -> dict[str, Any]:
    """Project persisted identity progress without claiming speaker correctness."""
    observation = observation if isinstance(observation, dict) else None
    observation_id = observation.get("id") if observation else None
    observation_extraction_id = (
        observation.get("extraction_result_id") if observation else None
    )
    observation_status = (
        "missing"
        if observation is None
        else "current"
        if observation_extraction_id == extraction_result_id
        else "stale"
    )
    current_attempts = [
        attempt
        for attempt in (association_attempts or [])
        if observation_status == "current"
        and attempt.get("observation_id") == observation_id
    ]
    profile_ids = sorted(set(effective_profile_ids or []))
    attempt_outcomes = Counter(
        str(attempt.get("outcome") or "unknown") for attempt in current_attempts
    )
    latest_attempt = max(
        current_attempts,
        key=lambda attempt: (
            str(attempt.get("created_at") or ""),
            str(attempt.get("artifact_path") or ""),
        ),
        default=None,
    )
    latest_association_outcome = (
        str(latest_attempt.get("outcome") or "unknown")
        if latest_attempt is not None
        else None
    )
    content_terminal = isinstance(
        content_disposition, str
    ) and content_disposition.startswith("rejected_")
    if content_terminal and observation_status == "current":
        state = "content_terminal_with_observation"
    elif content_terminal and observation_status == "stale":
        state = "content_terminal_with_stale_observation"
    elif content_terminal:
        state = "content_terminal"
    elif observation_status == "current" and profile_ids:
        state = "profiled"
    elif observation_status == "current" and latest_association_outcome:
        state = f"association_{latest_association_outcome}"
    elif observation_status == "current":
        state = "observation_available"
    elif observation_status == "stale":
        state = "stale_observation"
    else:
        state = "not_attempted"
    return {
        "status": "available",
        "state": state,
        "interpretation": (
            "Operational identity progress only; association proposals are not confirmed "
            "speaker identity, and only effective profile membership is reviewed identity."
        ),
        "content_disposition": content_disposition or "unknown",
        "observation_status": observation_status,
        "observation_id": observation_id,
        "observation_extraction_result_id": observation_extraction_id,
        "current_extraction_result_id": extraction_result_id,
        "association_attempt_count": len(current_attempts),
        "latest_association_outcome": latest_association_outcome,
        "latest_association_attempt": latest_attempt,
        "latest_attempt_ordering_basis": (
            latest_attempt.get("ordering_basis")
            if latest_attempt is not None
            else None
        ),
        "association_outcome_counts": dict(sorted(attempt_outcomes.items())),
        "association_attempts": current_attempts,
        "effective_profile_ids": profile_ids if observation_status == "current" else [],
        "candidate_funnel_review": _identity_candidate_funnel_projection(
            latest_attempt,
            effective_profile_ids=(
                profile_ids if observation_status == "current" else []
            ),
            profile_redirects=profile_redirects or {},
        ),
        "boundary_advisory_count": len(boundary_feedback or []),
    }


def _review_graph_reinforcement_opportunities(
    member_fingerprints: Sequence[str],
    same_pairs: set[frozenset[str]],
    observation_by_fingerprint: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Find comparisons that would remove known graph bridges if confirmed same."""
    members = tuple(sorted(set(member_fingerprints)))
    member_set = set(members)
    edges = {edge for edge in same_pairs if edge.issubset(member_set)}
    adjacency = {fingerprint: set() for fingerprint in members}
    for edge in edges:
        left, right = tuple(edge)
        adjacency[left].add(right)
        adjacency[right].add(left)

    opportunities: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for edge in sorted(tuple(sorted(value)) for value in edges):
        left, right = edge
        pending = [left]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            pending.extend(
                neighbor
                for neighbor in adjacency[current]
                if tuple(sorted((current, neighbor))) != edge
                and neighbor not in visited
            )
        if right in visited:
            continue
        other = member_set - visited
        candidates = sorted(
            tuple(sorted((candidate_a, candidate_b)))
            for candidate_a in visited
            for candidate_b in other
            if frozenset((candidate_a, candidate_b)) not in edges
        )
        if candidates:
            opportunities.setdefault(candidates[0], set()).add(edge)

    return [
        {
            "operation": "compare_existing_profile_members",
            "epistemic_status": "structurally_derived_opportunity",
            "result_contingency": (
                "A same-speaker result would add a redundant graph path; "
                "the comparison outcome is not predicted."
            ),
            "observation_a": dict(observation_by_fingerprint.get(pair[0], {})),
            "observation_b": dict(observation_by_fingerprint.get(pair[1], {})),
            "fingerprints": list(pair),
            "bridge_edges_addressed": [list(edge) for edge in sorted(bridges)],
        }
        for pair, bridges in sorted(opportunities.items())
    ]


def build_identity_automation_blocker_analysis(
    traces: Sequence[Mapping[str, Any]],
    *,
    profile_readiness: Sequence[Mapping[str, Any]] = (),
    reviewed_same_pairs: Sequence[Sequence[str]] = (),
    observation_by_fingerprint: Mapping[str, Mapping[str, Any]] | None = None,
    association_eligibility_by_observation_id: Mapping[int, str] | None = None,
    association_admission_by_observation_id: Mapping[
        int, Mapping[str, Any]
    ] | None = None,
    machine_assignments: Sequence[Mapping[str, Any]] = (),
    tripped_machine_policy_fingerprints: Sequence[str] = (),
    profile_redirects: Mapping[int, int] | None = None,
) -> dict[str, Any]:
    """Join current identity stops to directly observable and contingent work."""
    observation_by_fingerprint = observation_by_fingerprint or {}
    association_eligibility_by_observation_id = (
        association_eligibility_by_observation_id or {}
    )
    association_admission_by_observation_id = (
        association_admission_by_observation_id or {}
    )
    profile_redirects = profile_redirects or {}
    tripped_machine_policies = set(tripped_machine_policy_fingerprints)
    readiness_by_profile = {
        int(profile["profile_id"]): profile
        for profile in profile_readiness
        if isinstance(profile.get("profile_id"), int)
    }
    assignments_by_observation_profile: dict[
        tuple[int, int], list[Mapping[str, Any]]
    ] = {}
    for assignment in machine_assignments:
        observation_id = assignment.get("observation_id")
        profile_id = assignment.get("profile_id")
        if isinstance(observation_id, int) and isinstance(profile_id, int):
            assignments_by_observation_profile.setdefault(
                (observation_id, profile_id), []
            ).append(assignment)
    automation_video_ids: dict[str, set[str]] = {}
    automation_details: list[dict[str, Any]] = []
    reviewed_membership_video_ids: set[str] = set()

    def record_automation_state(
        state: str,
        *,
        youtube_video_id: str,
        observation_id: int,
        proposed_profile_id: int,
        canonical_profile_id: int,
        assignment: Mapping[str, Any] | None,
        reason_codes: Sequence[str] = (),
    ) -> None:
        automation_video_ids.setdefault(state, set()).add(youtube_video_id)
        automation_details.append(
            {
                "state": state,
                "youtube_video_id": youtube_video_id,
                "observation_id": observation_id,
                "proposed_profile_id": proposed_profile_id,
                "canonical_profile_id": canonical_profile_id,
                "machine_assignment_state": (
                    assignment.get("state") if assignment is not None else None
                ),
                "machine_evidence_id": (
                    assignment.get("machine_evidence_id")
                    if assignment is not None
                    else None
                ),
                "reason_codes": sorted(set(reason_codes)),
            }
        )
    same_pairs = {
        frozenset(str(value) for value in pair)
        for pair in reviewed_same_pairs
        if len(pair) == 2
    }
    accepted_unresolved: dict[int, dict[str, Any]] = {}
    proposals_by_profile: dict[int, set[int]] = {}
    rows: dict[str, dict[str, Any]] = {}

    def row(code: str, **metadata: Any) -> dict[str, Any]:
        value = rows.setdefault(
            code,
            {
                "blocker_class": code,
                "observed_blocking_location": metadata.pop(
                    "observed_blocking_location", "identity"
                ),
                "blocking_condition_codes": set(),
                "causal_hypotheses": set(),
                "affected_profile_ids": set(),
                "affected_observation_ids": set(),
                "accepted_unresolved_youtube_video_ids": set(),
                "directly_blocked_operation_youtube_video_ids": set(),
                "structurally_derived_operations": [],
                "observable_next_operation": metadata.pop(
                    "observable_next_operation", None
                ),
                "human_necessity": metadata.pop(
                    "human_necessity",
                    {
                        "classification": "not_established",
                        "basis": "No persisted evidence establishes inherent human necessity.",
                    },
                ),
                "potential_automation_opportunity": metadata.pop(
                    "potential_automation_opportunity", None
                ),
                "evidence_scope": metadata.pop("evidence_scope", "current_state"),
            },
        )
        return value

    for trace in traces:
        identity = trace.get("identity_outcome")
        identity = identity if isinstance(identity, Mapping) else {}
        disposition = str(identity.get("content_disposition") or "unknown")
        effective_profiles = {
            value
            for value in identity.get("effective_profile_ids", []) or []
            if isinstance(value, int)
        }
        observation_id = identity.get("observation_id")
        video = trace.get("video")
        video = video if isinstance(video, Mapping) else {}
        youtube_video_id = str(
            video.get("youtube_video_id")
            or trace.get("youtube_video_id")
            or ""
        )
        if effective_profiles and youtube_video_id:
            reviewed_membership_video_ids.add(youtube_video_id)
        unresolved = (
            disposition == "accepted_sermon"
            and identity.get("observation_status") == "current"
            and isinstance(observation_id, int)
            and not effective_profiles
        )
        if unresolved:
            accepted_unresolved[observation_id] = {
                "youtube_video_id": youtube_video_id,
                "trace": trace,
            }
        latest = identity.get("latest_association_attempt")
        latest = latest if isinstance(latest, Mapping) else {}
        outcome = str(identity.get("latest_association_outcome") or "")
        proposed_profile_id = latest.get("proposed_profile_id")
        if unresolved and outcome == "proposed_match" and isinstance(
            proposed_profile_id, int
        ):
            canonical_profile_id = int(
                profile_redirects.get(proposed_profile_id, proposed_profile_id)
            )
            proposals_by_profile.setdefault(canonical_profile_id, set()).add(
                observation_id
            )
            readiness = readiness_by_profile.get(canonical_profile_id, {})
            profile_ready = readiness.get("automatic_profile_ready") is True
            readiness_blockers = [
                str(value)
                for value in readiness.get("automatic_blockers", []) or []
            ]
            result_sha256 = latest.get("result_sha256")
            association_assignments = assignments_by_observation_profile.get(
                (observation_id, canonical_profile_id), []
            )
            matching_assignments = [
                assignment
                for assignment in association_assignments
                if isinstance(result_sha256, str)
                and assignment.get("association_result_sha256") == result_sha256
            ]
            assignment = max(
                matching_assignments,
                key=lambda value: (
                    str(
                        value.get("event_created_at")
                        or value.get("evidence_created_at")
                        or ""
                    ),
                    int(value.get("machine_evidence_id") or 0),
                ),
                default=None,
            )
            assignment_state = str(
                assignment.get("state") if assignment is not None else ""
            )
            assignment_policy = (
                str(assignment.get("policy_fingerprint") or "")
                if assignment is not None
                else ""
            )
            policy_tripped = bool(
                assignment_policy
                and assignment_policy in tripped_machine_policies
            )
            redirected = canonical_profile_id != proposed_profile_id
            if redirected:
                automation_state = "stale_proposal_excluded"
                automation_reasons = ["profile_redirected_since_association"]
            elif assignment_state == "active" and not policy_tripped and profile_ready:
                automation_state = "active_provisional_assignment"
                automation_reasons = ["current_reversible_machine_assignment"]
            elif (
                assignment_state == "awaiting_activation"
                and not policy_tripped
                and profile_ready
            ):
                automation_state = "eligible_unapplied_assignment"
                automation_reasons = ["machine_evidence_awaiting_activation"]
            elif assignment_state == "blocked_policy" or policy_tripped:
                automation_state = "proposal_blocked_policy_or_circuit"
                automation_reasons = [
                    str(
                        assignment.get("reason")
                        if assignment is not None
                        else "policy_circuit_breaker_tripped"
                    )
                ]
            elif assignment_state == "revoked":
                automation_state = "stale_or_revoked_assignment_excluded"
                automation_reasons = [
                    str(assignment.get("reason") or "assignment_revoked")
                ]
            elif not profile_ready:
                automation_state = "proposal_blocked_profile_readiness"
                automation_reasons = readiness_blockers or [
                    "profile_not_automatic_ready"
                ]
            elif association_assignments:
                automation_state = "stale_or_revoked_assignment_excluded"
                automation_reasons = [
                    "machine_assignment_does_not_match_latest_proposal"
                ]
            else:
                automation_state = "assignment_evidence_missing_or_noncurrent"
                automation_reasons = [
                    "current_proposal_has_no_matching_machine_evidence"
                ]
            record_automation_state(
                automation_state,
                youtube_video_id=youtube_video_id,
                observation_id=observation_id,
                proposed_profile_id=proposed_profile_id,
                canonical_profile_id=canonical_profile_id,
                assignment=assignment,
                reason_codes=automation_reasons,
            )
            blocker_metadata = {
                "eligible_unapplied_assignment": (
                    "machine_assignment_activation",
                    "activate_eligible_machine_assignments",
                    "not_required_for_reversible_activation",
                ),
                "proposal_blocked_profile_readiness": (
                    "profile_readiness",
                    "repair_target_profile_automatic_readiness",
                    "not_inherently_required",
                ),
                "proposal_blocked_policy_or_circuit": (
                    "machine_assignment_policy",
                    "review_policy_trip_and_reconcile_assignments",
                    "required_before_automatic_reenable",
                ),
                "assignment_evidence_missing_or_noncurrent": (
                    "machine_assignment_evidence",
                    "rerun_machine_assignment_planning",
                    "not_inherently_required",
                ),
                "stale_proposal_excluded": (
                    "current_artifact_validation",
                    "rerun_current_shadow_association",
                    "not_inherently_required",
                ),
                "stale_or_revoked_assignment_excluded": (
                    "machine_assignment_reconciliation",
                    "rerun_current_machine_assignment_planning",
                    "not_inherently_required",
                ),
            }.get(automation_state)
            if blocker_metadata is not None:
                location, operation, human_classification = blocker_metadata
                target = row(
                    automation_state,
                    observed_blocking_location=location,
                    observable_next_operation={
                        "operation": operation,
                        "implementation_status": "implemented_or_available",
                        "epistemic_status": "directly_observable_next_work",
                    },
                    human_necessity={
                        "classification": human_classification,
                        "basis": (
                            "The operational automation state is derived from current "
                            "production assignment evidence; reviewed membership remains "
                            "separate."
                        ),
                    },
                    evidence_scope="current_machine_assignment_projection",
                )
                target["blocking_condition_codes"].update(automation_reasons)
                target["affected_profile_ids"].add(canonical_profile_id)
                target["affected_observation_ids"].add(observation_id)
                target["accepted_unresolved_youtube_video_ids"].add(
                    youtube_video_id
                )
                if automation_state not in {
                    "stale_proposal_excluded",
                    "stale_or_revoked_assignment_excluded",
                }:
                    target[
                        "directly_blocked_operation_youtube_video_ids"
                    ].add(youtube_video_id)
        elif unresolved and outcome in {"ambiguous", "ambiguous_match"}:
            target = row(
                "comparison_ambiguous",
                observed_blocking_location="comparison",
                observable_next_operation={
                    "operation": "human_pair_review",
                    "implementation_status": "implemented",
                    "epistemic_status": "directly_observable_next_work",
                },
                human_necessity={
                    "classification": "likely_required",
                    "basis": "Persisted acoustic comparison is genuinely ambiguous.",
                },
            )
            target["affected_observation_ids"].add(observation_id)
            target["accepted_unresolved_youtube_video_ids"].add(youtube_video_id)
        elif unresolved and outcome == "insufficient_evidence" and (
            isinstance(latest.get("comparison_evidence_summary"), Mapping)
            and isinstance(
                latest["comparison_evidence_summary"].get(
                    "candidate_consistency"
                ),
                Mapping,
            )
            and latest["comparison_evidence_summary"][
                "candidate_consistency"
            ].get("status")
            == "inconsistent"
        ):
            target = row(
                "candidate_observation_acoustically_inconsistent",
                observed_blocking_location="observation_consistency",
                observable_next_operation={
                    "operation": "repair_or_review_candidate_span_coherence",
                    "implementation_status": "partially_implemented",
                    "epistemic_status": "directly_observable_next_work",
                },
                human_necessity={
                    "classification": "not_inherently_required",
                    "basis": (
                        "Persisted candidate-side metrics fail the existing "
                        "within-observation coherence guard before identity "
                        "membership can be established."
                    ),
                },
                potential_automation_opportunity={
                    "operation": "bounded_candidate_span_coherence_repair",
                    "epistemic_status": "recommendation",
                    "membership_guard_change_implied": False,
                },
                evidence_scope="persisted_candidate_side_pair_metrics",
            )
            target["blocking_condition_codes"].add(
                "candidate_within_observation_inconsistent"
            )
            target["affected_observation_ids"].add(observation_id)
            target["accepted_unresolved_youtube_video_ids"].add(
                youtube_video_id
            )
            target["directly_blocked_operation_youtube_video_ids"].add(
                youtube_video_id
            )
        elif unresolved and outcome == "insufficient_evidence":
            target = row(
                "cross_profile_comparison_inconclusive",
                observed_blocking_location="comparison",
                observable_next_operation={
                    "operation": "sample_ranked_inconclusive_candidates",
                    "implementation_status": "partially_implemented",
                    "epistemic_status": "recommendation",
                },
                human_necessity={
                    "classification": "not_established",
                    "basis": (
                        "Abstention establishes insufficient membership evidence, "
                        "not that only a human can resolve it."
                    ),
                },
            )
            target["affected_observation_ids"].add(observation_id)
            target["accepted_unresolved_youtube_video_ids"].add(youtube_video_id)
            reason_counts = latest.get("comparison_evidence_summary", {}).get(
                "reason_counts", {}
            )
            if isinstance(reason_counts, Mapping):
                target["blocking_condition_codes"].update(
                    str(reason)
                    for reason, count in reason_counts.items()
                    if isinstance(count, int) and count > 0
                )
        elif unresolved and outcome == "no_match":
            target = row(
                "all_compared_profiles_different",
                observed_blocking_location="comparison",
                observable_next_operation={
                    "operation": "route_to_profile_discovery_or_new_evidence",
                    "implementation_status": "partially_implemented",
                    "epistemic_status": "recommendation",
                },
                human_necessity={
                    "classification": "not_established",
                    "basis": (
                        "Persisted evidence rejects the compared profiles but "
                        "does not establish whether an unrepresented profile exists."
                    ),
                },
                evidence_scope="persisted_profile_comparisons",
            )
            target["blocking_condition_codes"].add(
                "multiple_different_speaker_results_for_every_profile"
            )
            target["affected_observation_ids"].add(observation_id)
            target["accepted_unresolved_youtube_video_ids"].add(youtube_video_id)
        elif unresolved and not outcome:
            admission = association_admission_by_observation_id.get(
                observation_id
            )
            admission = admission if isinstance(admission, Mapping) else {}
            eligibility_reason = association_eligibility_by_observation_id.get(
                observation_id
            )
            admission_reason = admission.get("reason_code")
            if isinstance(admission_reason, str) and admission_reason:
                admission_stage = str(
                    admission.get("stage") or "association_admission"
                )
                blocker_class = {
                    "metadata_eligibility": (
                        "association_admission_metadata_blocked"
                    ),
                    "verified_media_eligibility": (
                        "association_admission_media_blocked"
                    ),
                    "transcript_span_selection": (
                        "association_admission_transcript_spans_blocked"
                    ),
                    "activity_span_selection": (
                        "association_admission_activity_spans_blocked"
                    ),
                    "membership_filter": (
                        "association_admission_membership_filter"
                    ),
                    "observation_review_filter": (
                        "association_admission_review_filter"
                    ),
                }.get(admission_stage, "association_admission_blocked")
                target = row(
                    blocker_class,
                    observed_blocking_location=admission_stage,
                    observable_next_operation={
                        "operation": "repair_or_reassess_association_admission",
                        "implementation_status": "partially_implemented",
                        "epistemic_status": "directly_observable_next_work",
                    },
                    human_necessity={
                        "classification": "not_inherently_required",
                        "basis": (
                            "A persisted strict-admission outcome stopped the "
                            "candidate before identity comparison."
                        ),
                    },
                    potential_automation_opportunity={
                        "operation": "route_admission_reason_specific_repair",
                        "epistemic_status": "recommendation",
                        "membership_guard_change_implied": False,
                    },
                    evidence_scope="persisted_strict_admission",
                )
                target["blocking_condition_codes"].add(admission_reason)
            elif eligibility_reason is None:
                target = row(
                    "association_eligibility_not_observed",
                    observed_blocking_location="association_eligibility",
                    observable_next_operation={
                        "operation": "inspect_association_eligibility",
                        "implementation_status": "implemented",
                        "epistemic_status": "directly_observable_next_work",
                    },
                    human_necessity={
                        "classification": "not_established",
                        "basis": (
                            "No attempt is persisted, but current candidate "
                            "eligibility was not supplied to this projection."
                        ),
                    },
                    evidence_scope="incomplete_current_state",
                )
            elif eligibility_reason != "eligible":
                target = row(
                    "association_prerequisite_unavailable",
                    observed_blocking_location="association_eligibility",
                    observable_next_operation={
                        "operation": "repair_association_prerequisite",
                        "implementation_status": "partially_implemented",
                        "epistemic_status": "directly_observable_next_work",
                    },
                    human_necessity={
                        "classification": "not_inherently_required",
                        "basis": (
                            "A persisted media, observation, or span prerequisite "
                            "is unavailable; identity judgment has not been reached."
                        ),
                    },
                    potential_automation_opportunity={
                        "operation": "route_prerequisite_specific_repair",
                        "epistemic_status": "recommendation",
                        "membership_guard_change_implied": False,
                    },
                )
                target["blocking_condition_codes"].add(eligibility_reason)
            else:
                target = row(
                    "association_not_attempted",
                    observed_blocking_location="association_dispatch",
                    observable_next_operation={
                        "operation": "run_unattempted_shadow_associations",
                        "implementation_status": "implemented",
                        "epistemic_status": "directly_observable_next_work",
                    },
                    human_necessity={
                        "classification": "not_inherently_required",
                        "basis": (
                            "No association attempt is persisted for a current "
                            "metadata-eligible observation."
                        ),
                    },
                )
            target["affected_observation_ids"].add(observation_id)
            target["accepted_unresolved_youtube_video_ids"].add(youtube_video_id)
            target["directly_blocked_operation_youtube_video_ids"].add(
                youtube_video_id
            )

        funnel_review = identity.get("candidate_funnel_review")
        funnel_review = (
            funnel_review if isinstance(funnel_review, Mapping) else {}
        )
        funnel_classification = str(
            funnel_review.get("classification") or ""
        )
        if (
            funnel_review.get("status") == "observed"
            and funnel_review.get("observed_failure_location")
        ):
            funnel_code = {
                "correct_profile_ineligible": "retrospective_profile_ineligible",
                "filtered_by_readiness_policy_before_retrieval": (
                    "retrospective_readiness_policy_filter"
                ),
                "acoustic_retrieval_miss": "retrospective_retrieval_miss",
                "retrieved_below_shortlist_cutoff": "retrospective_retrieval_miss",
                "selected_profile_not_compared": "retrospective_selected_not_compared",
                "compared_but_abstained": "retrospective_comparison_abstention",
                "compared_and_proposed_incorrectly": (
                    "retrospective_incorrect_proposal"
                ),
                "profile_redirect_resolution_issue": (
                    "retrospective_profile_resolution_issue"
                ),
            }.get(funnel_classification)
            exclusions = (
                funnel_review.get("evidence", {}).get("profile_exclusions", [])
                if isinstance(funnel_review.get("evidence"), Mapping)
                else []
            )
            exclusion_reasons = {
                str(reason)
                for exclusion in exclusions or []
                if isinstance(exclusion, Mapping)
                for reason in exclusion.get("reason_codes", []) or []
            }
            if (
                funnel_code == "retrospective_profile_ineligible"
                and "fewer_than_required_eligible_acoustic_exemplars"
                in exclusion_reasons
            ):
                funnel_code = "retrospective_acoustic_exemplar_unavailable"
            if funnel_code:
                target = row(
                    funnel_code,
                    observed_blocking_location=str(
                        funnel_review.get("observed_failure_location")
                    ),
                    evidence_scope="retrospective_reviewed_identity",
                    observable_next_operation={
                        "operation": "investigate_persisted_funnel_failure",
                        "implementation_status": "diagnostic_only",
                        "epistemic_status": "recommendation",
                    },
                    human_necessity={
                        "classification": (
                            "likely_required"
                            if funnel_code
                            == "retrospective_comparison_abstention"
                            and outcome in {"ambiguous", "ambiguous_match"}
                            else "not_established"
                        ),
                        "basis": (
                            "The failure location is observed retrospectively; "
                            "its applicability to current unresolved sermons and "
                            "the need for human judgment are not inferred."
                        ),
                    },
                )
                target["blocking_condition_codes"].add(
                    funnel_classification
                )
                target["blocking_condition_codes"].update(exclusion_reasons)
                target["causal_hypotheses"].update(
                    str(value)
                    for value in funnel_review.get("causal_hypotheses", []) or []
                    if str(value)
                )
                if isinstance(observation_id, int):
                    target["affected_observation_ids"].add(observation_id)
                resolution = funnel_review.get("resolution")
                resolution = resolution if isinstance(resolution, Mapping) else {}
                target_profile_id = resolution.get("effective_profile_id")
                if isinstance(target_profile_id, int):
                    target["affected_profile_ids"].add(target_profile_id)

        boundary = trace.get("identity_boundary_feedback")
        boundary = boundary if isinstance(boundary, Mapping) else {}
        if int(boundary.get("unconsumed_same_edge_signal_count") or 0) > 0:
            target = row(
                "unresolved_identity_boundary_feedback",
                observed_blocking_location="identity_boundary_review",
                observable_next_operation={
                    "operation": "apply_or_adjudicate_identity_boundary_review",
                    "implementation_status": "implemented",
                    "epistemic_status": "directly_observable_next_work",
                },
                human_necessity={
                    "classification": "case_dependent",
                    "basis": (
                        "Automatic guards may retain, trim, or require review; the "
                        "persisted record determines the case."
                    ),
                },
            )
            if isinstance(observation_id, int):
                target["affected_observation_ids"].add(observation_id)
            if unresolved:
                target["accepted_unresolved_youtube_video_ids"].add(
                    youtube_video_id
                )

    profiles_by_name: dict[str, list[int]] = {}
    profile_chains: list[dict[str, Any]] = []
    for profile in profile_readiness:
        profile_id = profile.get("profile_id")
        if not isinstance(profile_id, int):
            continue
        names = [
            str(value) for value in profile.get("normalized_names", []) or []
            if str(value)
        ]
        if len(names) == 1:
            profiles_by_name.setdefault(names[0], []).append(profile_id)
        blockers = [
            str(value) for value in profile.get("automatic_blockers", []) or []
        ]
        if not blockers:
            continue
        proposal_observation_ids = proposals_by_profile.get(profile_id, set())
        proposal_video_ids = {
            accepted_unresolved[value]["youtube_video_id"]
            for value in proposal_observation_ids
            if value in accepted_unresolved
        }
        structural_opportunities = (
            _review_graph_reinforcement_opportunities(
                profile.get("member_fingerprints", []) or [],
                same_pairs,
                observation_by_fingerprint,
            )
            if "reviewed_same_graph_contains_bridge" in blockers
            else []
        )
        profile_chains.append(
            {
                "profile_id": profile_id,
                "observed_blocker_chain": blockers,
                "automatic_profile_ready": False,
                "directly_blocked_proposal_observation_ids": sorted(
                    proposal_observation_ids
                ),
                "directly_blocked_proposal_youtube_video_ids": sorted(
                    proposal_video_ids
                ),
                "structurally_derived_next_operations": structural_opportunities,
                "cascade_interpretation": (
                    "Only current proposals are directly blocked. Further proposals "
                    "or memberships are contingent and are not counted as unlocks."
                ),
            }
        )
        for blocker in blockers:
            blocker_class = {
                "fewer_than_three_profile_members": "insufficient_independent_exemplars",
                "fewer_than_three_distinct_recordings": "insufficient_independent_exemplars",
                "fewer_than_three_reviewed_members": "insufficient_independent_exemplars",
                "reviewed_same_graph_contains_bridge": "review_graph_bridge",
                "reviewed_same_graph_disconnected": "review_graph_disconnected",
                "attribution_spans_multiple_profiles": "duplicate_profile_identity",
                "discovery_candidate_unconfirmed": "provisional_profile_unconfirmed",
                "internal_reviewed_difference": "reviewed_identity_conflict",
                "conflicting_explicit_attribution": "reviewed_identity_conflict",
                "conflicting_name_claim_review": "reviewed_identity_conflict",
            }.get(blocker, "profile_readiness_policy")
            target = row(
                blocker_class,
                observed_blocking_location="profile_readiness",
                observable_next_operation={
                    "operation": (
                        "compare_existing_profile_members"
                        if blocker_class == "review_graph_bridge"
                        else "reconcile_profiles"
                        if blocker_class == "duplicate_profile_identity"
                        else "gather_or_repair_profile_evidence"
                    ),
                    "implementation_status": (
                        "structurally_identifiable"
                        if blocker_class == "review_graph_bridge"
                        else "partially_implemented"
                    ),
                    "epistemic_status": "structurally_derived_opportunity",
                },
                human_necessity={
                    "classification": (
                        "required_before_conflict_resolution"
                        if blocker_class == "reviewed_identity_conflict"
                        else "not_established"
                    ),
                    "basis": (
                        "The blocker is observed; the result of additional evidence "
                        "or reconciliation is not known."
                    ),
                },
                potential_automation_opportunity={
                    "operation": (
                        "nominate_reinforcement_comparison"
                        if blocker_class == "review_graph_bridge"
                        else "generate_reconciliation_or_evidence_repair_plan"
                    ),
                    "epistemic_status": "recommendation",
                    "membership_guard_change_implied": False,
                },
            )
            target["blocking_condition_codes"].add(blocker)
            target["affected_profile_ids"].add(profile_id)
            target["affected_observation_ids"].update(
                value
                for value in profile.get("member_observation_ids", []) or []
                if isinstance(value, int)
            )
            target["accepted_unresolved_youtube_video_ids"].update(
                proposal_video_ids
            )
            target["directly_blocked_operation_youtube_video_ids"].update(
                proposal_video_ids
            )
            if blocker_class == "review_graph_bridge":
                target["structurally_derived_operations"].extend(
                    {**operation, "profile_id": profile_id}
                    for operation in structural_opportunities
                )

    duplicate_groups = [
        {"normalized_name": name, "profile_ids": sorted(profile_ids)}
        for name, profile_ids in sorted(profiles_by_name.items())
        if len(profile_ids) > 1
    ]

    finalized_rows = []
    for value in rows.values():
        for key in (
            "blocking_condition_codes",
            "causal_hypotheses",
            "affected_profile_ids",
            "affected_observation_ids",
            "accepted_unresolved_youtube_video_ids",
            "directly_blocked_operation_youtube_video_ids",
        ):
            value[key] = sorted(value[key])
        value["affected_profile_count"] = len(value["affected_profile_ids"])
        value["affected_observation_count"] = len(
            value["affected_observation_ids"]
        )
        value["accepted_unresolved_sermon_count"] = len(
            value["accepted_unresolved_youtube_video_ids"]
        )
        value["directly_blocked_operation_count"] = len(
            value["directly_blocked_operation_youtube_video_ids"]
        )
        value["structurally_derived_operation_count"] = len(
            value["structurally_derived_operations"]
        )
        value["unlock_interpretation"] = (
            "Direct counts include only persisted current work. Any cascade after "
            "the next operation is contingent and is not counted."
        )
        finalized_rows.append(value)
    finalized_rows.sort(
        key=lambda value: (
            -value["directly_blocked_operation_count"],
            -value["accepted_unresolved_sermon_count"],
            -value["structurally_derived_operation_count"],
            value["blocker_class"],
        )
    )
    investigation_priorities = [
        {
            "blocker_class": value["blocker_class"],
            "directly_blocked_operation_count": value[
                "directly_blocked_operation_count"
            ],
            "accepted_unresolved_sermon_count": value[
                "accepted_unresolved_sermon_count"
            ],
            "structurally_derived_operation_count": value[
                "structurally_derived_operation_count"
            ],
            "next_operation": value.get("observable_next_operation"),
            "priority_basis": (
                "Ordered by directly observed blocked work, then unresolved accepted "
                "sermons; this is not an expected-yield score."
            ),
        }
        for value in finalized_rows
        if value["directly_blocked_operation_count"] > 0
        or value["structurally_derived_operation_count"] > 0
    ]
    automation_state_names = (
        "active_provisional_assignment",
        "eligible_unapplied_assignment",
        "proposal_blocked_profile_readiness",
        "proposal_blocked_policy_or_circuit",
        "proposal_genuinely_requires_human_review",
        "assignment_evidence_missing_or_noncurrent",
        "stale_proposal_excluded",
        "stale_or_revoked_assignment_excluded",
    )
    automation_state_counts = {
        state: len(automation_video_ids.get(state, set()))
        for state in automation_state_names
    }
    current_proposal_video_ids = set().union(
        *(automation_video_ids.get(state, set()) for state in automation_state_names)
    )
    reviews_avoided_video_ids = (
        automation_video_ids.get("active_provisional_assignment", set())
        | automation_video_ids.get("eligible_unapplied_assignment", set())
    )
    stale_excluded_video_ids = (
        automation_video_ids.get("stale_proposal_excluded", set())
        | automation_video_ids.get(
            "stale_or_revoked_assignment_excluded", set()
        )
    )
    return {
        "schema_version": 1,
        "domain": "identity",
        "epistemic_contract": {
            "observed": "Persisted state or policy condition.",
            "structural_inference": (
                "A deterministic operation is identifiable, but its result is unknown."
            ),
            "recommendation": (
                "An engineering experiment; safety and yield are not established."
            ),
            "speculative_cascades_counted": False,
        },
        "accepted_unresolved_sermon_count": len(accepted_unresolved),
        "operational_association_summary": {
            "count_unit": "unique_current_videos",
            "reviewed_profile_membership_count": len(
                reviewed_membership_video_ids
            ),
            "current_proposal_count": len(current_proposal_video_ids),
            "state_counts": automation_state_counts,
            "state_counts_reconcile": sum(automation_state_counts.values())
            == len(current_proposal_video_ids),
            "active_provisional_assignment_count": automation_state_counts[
                "active_provisional_assignment"
            ],
            "eligible_unapplied_assignment_count": automation_state_counts[
                "eligible_unapplied_assignment"
            ],
            "proposal_blocked_profile_readiness_count": automation_state_counts[
                "proposal_blocked_profile_readiness"
            ],
            "proposal_blocked_policy_or_circuit_count": automation_state_counts[
                "proposal_blocked_policy_or_circuit"
            ],
            "proposal_genuinely_requires_human_review_count": (
                automation_state_counts[
                    "proposal_genuinely_requires_human_review"
                ]
            ),
            "assignment_evidence_missing_or_noncurrent_count": (
                automation_state_counts[
                    "assignment_evidence_missing_or_noncurrent"
                ]
            ),
            "stale_proposal_or_assignment_excluded_count": len(
                stale_excluded_video_ids
            ),
            "human_reviews_avoided_by_current_automation_count": len(
                reviews_avoided_video_ids
            ),
            "details": sorted(
                automation_details,
                key=lambda value: (
                    value["state"],
                    value["youtube_video_id"],
                    value["observation_id"],
                ),
            ),
            "interpretation": (
                "Operational association is separate from reviewed membership. "
                "Active assignments are reversible; eligible unapplied assignments "
                "need activation, not sermon-level identity review."
            ),
            "remaining_ambiguities": [
                (
                    "A current automatic-ready proposal without matching machine "
                    "evidence cannot be assigned to a specific production planning "
                    "gate because skipped-plan reasons are not persisted per artifact."
                )
            ],
        },
        "blocker_classes": finalized_rows,
        "profile_blocker_chains": sorted(
            profile_chains, key=lambda value: value["profile_id"]
        ),
        "duplicate_profile_groups": duplicate_groups,
        "investigation_priorities": investigation_priorities,
        "interpretation": (
            "This section identifies where current automation stops and which next "
            "operation is observable or structurally derivable. It does not relax "
            "identity membership policy or predict contingent cascade yield."
        ),
    }


def _identity_boundary_feedback_projection(
    events: list[dict[str, Any]],
    *,
    final_ranges: list[Range],
    expected: list[Range] | None,
    allowed_interruptions: list[Range] | None,
) -> dict[str, Any]:
    final_boundary = _boundary(final_ranges)
    expected_boundary = _boundary(expected or [])
    projected: list[dict[str, Any]] = []
    for raw in events:
        event = dict(raw)
        evidence = event.get("evidence_window")
        evidence = evidence if isinstance(evidence, dict) else {}
        evidence_range = _range(
            evidence.get("start_seconds"), evidence.get("end_seconds")
        )
        edge = event.get("edge")
        movement = None
        effect = "advisory_without_comparable_window"
        if evidence_range is not None and final_boundary is not None:
            movement = (
                final_boundary["start_seconds"] - evidence_range[0]
                if edge == "start"
                else final_boundary["end_seconds"] - evidence_range[1]
            )
            inward = (edge == "start" and movement > 0) or (
                edge == "end" and movement < 0
            )
            if abs(movement) < 0.001:
                effect = "advisory_no_boundary_change"
            elif inward:
                effect = "boundary_moved_inward_after_advisory"
            else:
                effect = "boundary_moved_outward_after_advisory"
        event["observed_boundary_movement_seconds"] = (
            round(movement, 3) if isinstance(movement, (int, float)) else None
        )
        event["observed_effect"] = effect
        same_edge_overreach_seconds = None
        if final_boundary is not None and expected_boundary is not None:
            if edge == "start":
                same_edge_overreach_seconds = max(
                    0.0,
                    expected_boundary["start_seconds"]
                    - final_boundary["start_seconds"],
                )
            elif edge == "end":
                same_edge_overreach_seconds = max(
                    0.0,
                    final_boundary["end_seconds"]
                    - expected_boundary["end_seconds"],
                )
        event["reviewed_same_edge_overreach_seconds"] = (
            round(same_edge_overreach_seconds, 3)
            if isinstance(same_edge_overreach_seconds, (int, float))
            else None
        )
        event["identity_signal_unconsumed"] = bool(
            isinstance(same_edge_overreach_seconds, (int, float))
            and same_edge_overreach_seconds >= MATERIAL_BOUNDARY_SECONDS
            and not event.get("causal_adjustment_persisted")
            and effect == "advisory_no_boundary_change"
        )
        if evidence_range is not None and expected is not None:
            before = _stage_measurements(
                [evidence_range], [evidence_range], expected, allowed_interruptions
            )
            after = _stage_measurements(
                final_ranges, [evidence_range], expected, allowed_interruptions
            )
            event["reviewed_quality_impact"] = {
                "coverage_before": before.get("reviewed_sermon_coverage"),
                "coverage_after": after.get("reviewed_sermon_coverage"),
                "contamination_before": before.get("contamination_ratio"),
                "contamination_after": after.get("contamination_ratio"),
                "attribution": (
                    "causal" if event.get("causal_adjustment_persisted") else "temporal_only"
                ),
            }
        projected.append(event)
    return {
        "status": "available" if projected else "not_observed",
        "event_count": len(projected),
        "start_edge_event_count": sum(event.get("edge") == "start" for event in projected),
        "end_edge_event_count": sum(event.get("edge") == "end" for event in projected),
        "causal_adjustment_count": sum(
            bool(event.get("causal_adjustment_persisted")) for event in projected
        ),
        "temporal_boundary_movement_count": sum(
            event.get("observed_effect")
            in {
                "boundary_moved_inward_after_advisory",
                "boundary_moved_outward_after_advisory",
            }
            for event in projected
        ),
        "unconsumed_same_edge_signal_count": sum(
            bool(event.get("identity_signal_unconsumed")) for event in projected
        ),
        "events": projected,
        "interpretation": (
            "Identity evidence is surfaced as advisory unless the causing adjustment is "
            "explicitly persisted; later boundary movement is not proof of causality."
        ),
    }


def build_diagnostic_trace(
    proposed: dict[str, Any],
    *,
    proposed_path: Path,
    youtube_video_id: str,
    database_video_id: int | None = None,
    fixture: ValidatedFixture | None = None,
    media_duration_seconds: float | None = None,
    identity_boundary_feedback: list[dict[str, Any]] | None = None,
    identity_outcome: dict[str, Any] | None = None,
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
    coarse_evidence_ranges = _merge_ranges(
        value
        for candidate in ordinary_candidates
        for value in _candidate_support_ranges(candidate, coarse_blocks)
    )
    candidate_ranges = _merge_ranges(
        value
        for candidate in ordinary_candidates
        for value in _candidate_envelope_ranges(candidate)
    )
    selected_ranges = _candidate_envelope_ranges(selected) if selected is not None else []
    joined_ranges = selected_ranges
    retained = classification.get("retained_segment_indexes")
    fine_ranges = _segment_ranges(
        segments,
        retained if isinstance(retained, list) else [],
    )
    sermon_window = proposed.get("sermon_window")
    sermon_window = sermon_window if isinstance(sermon_window, dict) else {}
    arbitration = sermon_window.get("arbitration")
    if not isinstance(arbitration, dict):
        arbitration = classification.get("window_arbitration")
    arbitration = arbitration if isinstance(arbitration, dict) else {}
    final_range = _range(
        sermon_window.get("start_seconds"), sermon_window.get("end_seconds")
    )
    final_ranges = [final_range] if final_range is not None else fine_ranges
    disposition = proposed.get("final_disposition")
    disposition = disposition if isinstance(disposition, dict) else {}
    verification = proposed.get("recording_verification")
    verification = verification if isinstance(verification, dict) else {}
    manual_override = (
        sermon_window.get("source") == "override"
        or search.get("rule_baseline_source") == "manual_override"
    )
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
            "coarse_evidence",
            "Coarse evidence",
            coarse_evidence_ranges,
            transcript_ranges,
            {"discovery": search.get("discovery")},
            {
                "candidate_count": len(ordinary_candidates),
                "range_semantics": "coarse_support_blocks",
            },
            [],
        ),
        (
            "candidates",
            "Candidate envelopes",
            candidate_ranges,
            coarse_evidence_ranges,
            {"discovery": search.get("discovery")},
            {
                "candidate_count": len(ordinary_candidates),
                "range_semantics": "persisted_candidate_start_and_end",
            },
            [],
        ),
        (
            "selected",
            "Selected candidate",
            selected_ranges,
            candidate_ranges,
            {
                "selected_rank": search.get("selected_rank"),
                "source": selected.get("source") if selected else None,
            },
            {
                "score": selected.get("score") if selected else None,
                "score_components": selected.get("score_components") if selected else None,
                "boundary_provenance": "persisted_candidate_start_and_end",
                "coarse_support_block_ids": (
                    selected.get("coarse_support_block_ids") if selected else None
                ),
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
            "arbitration",
            "Final arbitration",
            final_ranges,
            fine_ranges,
            {
                "window_source": sermon_window.get("source"),
                "window_method": sermon_window.get("method"),
                "manual_override_applied": manual_override,
                "suspicious_boundary_reasons": sermon_window.get(
                    "suspicious_boundary_reasons", []
                ),
            },
            {
                "confidence_tier": classification.get("confidence_tier"),
                "rule_baseline_source": search.get("rule_baseline_source"),
                "arbitration": arbitration,
                "boundary_precision": (
                    selected.get("boundary_precision") if selected else None
                ),
            },
            [],
        ),
        (
            "verifier",
            "Recording verifier",
            final_ranges,
            final_ranges,
            {
                "source": verification.get("source"),
                "decision": verification.get("decision"),
                "predicted_outcome": verification.get("predicted_outcome"),
                "confidence": verification.get("confidence"),
                "reason_codes": verification.get("reason_codes", []),
            },
            {
                "policy_version": verification.get("policy_version"),
                "prompt_version": verification.get("prompt_version"),
                "model": verification.get("model"),
                "model_digest": verification.get("model_digest"),
                "evidence_packet_hash": verification.get("evidence_packet_hash"),
            },
            [],
        ),
        (
            "final",
            "Final outcome",
            final_ranges,
            final_ranges,
            {
                "window_source": sermon_window.get("source"),
                "disposition_status": disposition.get("status"),
                "reason_codes": disposition.get("reason_codes", []),
                "manual_override_applied": manual_override,
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
            final_disposition=(
                str(disposition.get("status")) if disposition.get("status") else None
            ),
        )
        for key, label, output, previous, decision, evidence, warnings in stage_specs
    ]
    verifier_stage = next(stage for stage in stages if stage["key"] == "verifier")
    verifier_stage["contract"] = _verifier_contract(verification, fixture)
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
    ]
    if manual_override:
        diagnostic_gaps.append(
            {
                "code": "automatic_pre_override_final_not_persisted",
                "stage": "arbitration",
                "impact": (
                    "The reviewed result is known, but the automatic final choice immediately "
                    "before override cannot be reconstructed reliably."
                ),
                "recommended_instrumentation": (
                    "Persist the automatic window and disposition before applying an override."
                ),
            }
        )
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
    outcome_contracts = _outcome_contracts(
        stages=stages,
        fixture=fixture,
        final_disposition=(
            str(disposition.get("status")) if disposition.get("status") else None
        ),
        manual_override=manual_override,
    )
    overall_outcome = _overall_outcome(outcome_contracts)
    contract_paths = _contract_paths(stages, outcome_contracts)
    any_breach = any(
        path.get("earliest_breach_stage") is not None
        for key, path in contract_paths.items()
        if key != "stage_order" and isinstance(path, dict)
    )
    if manual_override:
        recovery_status = (
            "masked_by_manual_override" if any_breach else "manual_override_applied"
        )
    elif overall_outcome["status"] == "fail":
        recovery_status = "unrecovered"
    elif any_breach:
        recovery_status = "recovered_automatically"
    else:
        recovery_status = "clean"
    fine_stage = next(stage for stage in stages if stage["key"] == "fine")
    candidate_regret = _candidate_regret(
        candidates,
        selected,
        expected,
        allowed_interruptions,
        fine_stage["measurements"].get("reviewed_sermon_coverage"),
    )
    identity_feedback = _identity_boundary_feedback_projection(
        identity_boundary_feedback or [],
        final_ranges=final_ranges,
        expected=expected,
        allowed_interruptions=allowed_interruptions,
    )
    if (
        identity_feedback["temporal_boundary_movement_count"]
        and not identity_feedback["causal_adjustment_count"]
    ):
        diagnostic_gaps.append(
            {
                "code": "identity_boundary_adjustment_causality_not_persisted",
                "stage": "arbitration",
                "impact": (
                    "Identity edge evidence and later boundary movement coexist, but the trace "
                    "cannot prove that identity caused the adjustment."
                ),
                "recommended_instrumentation": (
                    "Persist the pre-adjustment boundary, proposed boundary, decision, immutable "
                    "speaker evidence spans, and post-adjustment boundary as one event."
                ),
            }
        )
    if identity_feedback["unconsumed_same_edge_signal_count"]:
        diagnostic_gaps.append(
            {
                "code": "identity_signal_unconsumed",
                "stage": "arbitration",
                "impact": (
                    "A speaker-inconsistent edge advisory coincides with reviewed overreach "
                    "on that edge, but no consuming decision was persisted."
                ),
                "recommended_instrumentation": (
                    "Persist whether the advisory was ignored, accepted, rejected, or sent "
                    "to review, including the boundary before and after the decision."
                ),
            }
        )
    cohort = {
        **_fixture_metadata(fixture),
        "outcome_mode": "manual_override" if manual_override else "automatic",
        "transcript_source": proposed.get("transcript_source") or "unknown",
        "algorithm_version": search.get("algorithm_version") or "unknown",
        "verifier_prompt_version": verification.get("prompt_version") or "unknown",
        "verifier_policy_version": verification.get("policy_version") or "unknown",
        "verifier_model": verification.get("model") or "unknown",
    }
    trace = {
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
        "root_cause_hypothesis": _root_cause(
            observed, stages, fixture, candidate_regret
        ),
        "cohort": cohort,
        "overall_outcome": overall_outcome,
        "contract_paths": contract_paths,
        "candidate_regret": candidate_regret,
        "stage_regret": _stage_regret(stages, fixture),
        "contamination_attribution": _contamination_attribution(stages, fixture),
        "identity_outcome": identity_outcome
        or {
            "status": "not_observed",
            "state": "not_observed",
            "interpretation": "Identity outcome evidence was not supplied.",
        },
        "identity_boundary_feedback": identity_feedback,
        "join_observability": {
            "joined_candidate_count": sum(
                candidate.get("source") == "joined_coarse_llm" for candidate in candidates
            ),
            "selected_joined_candidate": bool(
                selected and selected.get("source") == "joined_coarse_llm"
            ),
            "rejected_join_attempts_persisted": False,
        },
        "causal_path_status": recovery_status,
        "recovery_status": recovery_status,
        "outcome_contracts": outcome_contracts,
        "diagnostic_gaps": diagnostic_gaps,
    }
    trace["component_fingerprints"] = _trace_component_fingerprints(trace)
    return trace


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
    indexes = {stage.get("key"): index for index, stage in enumerate(stages)}
    predecessors = {
        "rule": "transcript",
        "coarse_evidence": "transcript",
        "candidates": "coarse_evidence",
        "selected": "candidates",
        "joined": "selected",
        "fine": "joined",
        "arbitration": "fine",
        "verifier": "arbitration",
        "final": "verifier",
    }
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
            predecessor_key = predecessors.get(stage.get("key"))
            predecessor = indexes.get(predecessor_key, index - 1)
            connector = "-.->" if stage.get("key") == "rule" else "-->"
            lines.append(
                f"  S{predecessor} {connector}|{annotation}| {node}"
                if annotation
                else f"  S{predecessor} {connector} {node}"
            )
    if "rule" in indexes and "arbitration" in indexes:
        lines.append(
            f"  S{indexes['rule']} -. comparator .-> S{indexes['arbitration']}"
        )
    identity_outcome = trace.get("identity_outcome", {})
    identity_state = str(identity_outcome.get("state") or "not_observed")
    identity_label = identity_state.replace("_", " ")
    identity = trace.get("identity_boundary_feedback", {})
    identity_event_count = int(identity.get("event_count") or 0)
    if "final" in indexes:
        lines.extend(
            [
                f'  ID["Identity outcome<br/>{identity_label}"]',
                f"  S{indexes['final']} --> ID",
            ]
        )
        classes["unknown"].append("ID")
    if identity_event_count and "arbitration" in indexes:
        lines.extend(
            [
                f'  IB["Identity edge evidence<br/>{identity_event_count} advisories"]',
                "  ID --> IB",
                f"  IB -. boundary advisory .-> S{indexes['arbitration']}",
            ]
        )
        classes["unknown"].append("IB")
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
        f"- Overall outcome: {trace.get('overall_outcome', {}).get('status', 'unknown')}",
        "- Causal path status: "
        f"{trace.get('causal_path_status', trace.get('recovery_status', 'unknown'))}",
        f"- Cohort: {trace.get('cohort', {}).get('outcome_mode', 'unknown')} / "
        f"{trace.get('cohort', {}).get('evaluation_partition', 'unknown')}",
        "",
        "## Outcome contracts",
        "",
        "| Dimension | Status | Observed | Threshold |",
        "|---|---|---:|---:|",
    ]
    for dimension in (
        "existence",
        "localization",
        "contamination",
        "verifier",
        "disposition",
    ):
        contract = trace.get("outcome_contracts", {}).get(dimension, {})
        observed_value = contract.get("observed", contract.get("value"))
        threshold = contract.get("threshold")
        lines.append(
            f"| {dimension} | {contract.get('status', 'unknown')} | "
            f"{observed_value if observed_value is not None else '—'} | "
            f"{threshold if threshold is not None else '—'} |"
        )
    lines.extend(
        [
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
    )
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
                "| Stage | Recall | Δ recall | Contamination | Start error | End error |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        previous_recall: float | None = None
        for stage in trace["stages"]:
            measurements = stage["measurements"]
            recall = measurements.get("reviewed_sermon_coverage")
            contamination = measurements.get("contamination_ratio")
            delta_recall = (
                recall - previous_recall
                if isinstance(recall, (int, float)) and previous_recall is not None
                else None
            )
            start_error = measurements.get("start_error_seconds")
            end_error = measurements.get("end_error_seconds")
            lines.append(
                f"| {stage['label']} | {recall:.1%} | "
                f"{delta_recall:+.1%} | {contamination:.1%} | "
                f"{start_error:.0f}s | {end_error:.0f}s |"
                if delta_recall is not None
                and isinstance(start_error, (int, float))
                and isinstance(end_error, (int, float))
                else f"| {stage['label']} | {recall:.1%} | — | "
                f"{contamination:.1%} | — | — |"
            )
            previous_recall = recall if isinstance(recall, (int, float)) else previous_recall
    regret = trace.get("candidate_regret", {})
    stage_regret = trace.get("stage_regret", {})
    attribution = trace.get("contamination_attribution", {})
    lines.extend(
        [
            "",
            "## Candidate regret",
            "",
            f"- Classification: {regret.get('classification', regret.get('status', 'unknown'))}",
            f"- Candidate-union coverage: {regret.get('candidate_union_coverage', '—')}",
            f"- Best candidate: rank {regret.get('best_candidate_rank', '—')} at "
            f"{regret.get('best_candidate_coverage', '—')} coverage",
            f"- Selected-candidate regret: {regret.get('selected_candidate_regret', '—')}",
            f"- Precision classification: {regret.get('precision_classification', '—')}",
            "- Best precision candidate: rank "
            f"{regret.get('best_precision_candidate_rank', '—')} at "
            f"{regret.get('best_precision_candidate_coverage', '—')} coverage / "
            f"{regret.get('best_precision_candidate_contamination', '—')} contamination",
            "- Pareto candidate ranks: "
            f"{', '.join(str(rank) for rank in regret.get('pareto_candidate_ranks', [])) or '—'}",
            "",
            "## Stage regret",
            "",
            "| Stage | Classification | Coverage delta | Contamination delta |",
            "|---|---|---:|---:|",
        ]
    )
    for stage_key in ("refinement", "arbitration"):
        value = stage_regret.get(stage_key, {})
        coverage_change = value.get(
            "coverage_delta", value.get("coverage_regret_against_fine", "—")
        )
        contamination_change = value.get(
            "contamination_delta",
            value.get("contamination_regret_against_fine", "—"),
        )
        lines.append(
            f"| {stage_key} | {value.get('classification', 'not_evaluated')} | "
            f"{coverage_change} | {contamination_change} |"
        )
    lines.extend(
        [
            "",
            "## Contract paths",
            "",
            "| Dimension | Earliest breach | Recovery | Terminal | Likely cause |",
            "|---|---|---|---|---|",
        ]
    )
    for dimension, path in trace.get("contract_paths", {}).items():
        if dimension == "stage_order" or not isinstance(path, dict):
            continue
        lines.append(
            f"| {dimension} | {path.get('earliest_breach_stage') or 'none'} | "
            f"{', '.join(path.get('recovery_stages', [])) or 'none'} | "
            f"{path.get('terminal_status', 'not_evaluated')} | "
            f"{path.get('likely_causal_stage') or 'none'} |"
        )
    identity_outcome = trace.get("identity_outcome", {})
    lines.extend(
        [
            "",
            "## Identity operational outcome",
            "",
            f"- State: {identity_outcome.get('state', 'not_observed')}",
            f"- Observation: {identity_outcome.get('observation_status', 'not_observed')}",
            "- Association attempts: "
            f"{identity_outcome.get('association_attempt_count', 0)}",
            "- Latest association outcome: "
            f"{identity_outcome.get('latest_association_outcome') or 'none'}",
            "- Association outcomes: `"
            + json.dumps(
                identity_outcome.get("association_outcome_counts", {}),
                sort_keys=True,
            )
            + "`",
            "- Effective reviewed profiles: "
            + (
                ", ".join(
                    str(profile_id)
                    for profile_id in identity_outcome.get(
                        "effective_profile_ids", []
                    )
                )
                or "none"
            ),
            f"- Interpretation: {identity_outcome.get('interpretation', 'not observed')}",
        ]
    )
    identity = trace.get("identity_boundary_feedback", {})
    lines.extend(
        [
            "",
            "## Identity boundary feedback",
            "",
            f"- Events: {identity.get('event_count', 0)}",
            "- Boundary movement after evidence: "
            f"{identity.get('temporal_boundary_movement_count', 0)}",
            f"- Causal adjustments persisted: {identity.get('causal_adjustment_count', 0)}",
            "- Unconsumed same-edge signals: "
            f"{identity.get('unconsumed_same_edge_signal_count', 0)}",
            f"- Interpretation: {identity.get('interpretation', 'not observed')}",
        ]
    )
    for event in identity.get("events", []) or []:
        quality = event.get("reviewed_quality_impact", {})
        lines.append(
            f"- {event.get('edge', 'unknown')} edge: "
            f"{event.get('observed_effect', 'unknown')} "
            f"(attribution: {quality.get('attribution', 'advisory_only')})"
        )
    lines.extend(
        [
            "",
            "## Contamination attribution",
            "",
            f"- Earliest breach: {attribution.get('earliest_breach_stage') or 'none'}",
            f"- Recovery stage: {attribution.get('recovery_stage') or 'none'}",
            "- Final boundary pattern: "
            + ", ".join(attribution.get("final_boundary_error_patterns", []) or ["not evaluated"]),
            "- Material contamination pattern: "
            + ", ".join(
                attribution.get("material_final_contamination_patterns", [])
                or ["not evaluated"]
            ),
            "- Terminal component causes: `"
            + json.dumps(
                attribution.get("terminal_component_causal_stages", {}),
                sort_keys=True,
            )
            + "`",
            "- Final contamination seconds: `"
            + json.dumps(
                attribution.get("final_contamination_seconds", {}),
                sort_keys=True,
            )
            + "`",
        ]
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


def _trace_overall_status(trace: dict[str, Any]) -> str:
    explicit = trace.get("overall_outcome", {}).get("status")
    if isinstance(explicit, str):
        return explicit
    contracts = trace.get("outcome_contracts")
    if isinstance(contracts, dict):
        return str(_overall_outcome(contracts)["status"])
    final = next(
        (stage for stage in trace.get("stages", []) if stage.get("key") == "final"),
        None,
    )
    if final is None:
        return "not_evaluated"
    statuses = [final.get("contract", {}).get("status")]
    statuses.extend(
        contract.get("status")
        for contract in final.get("quality_contracts", {}).values()
        if isinstance(contract, dict)
    )
    if "fail" in statuses:
        return "fail"
    disposition = final.get("decision", {}).get("disposition_status")
    if disposition == "review_required":
        return "review_required"
    if final.get("decision", {}).get("manual_override_applied"):
        return "pass_with_manual_override"
    if "pass" in statuses:
        return "pass"
    return "not_evaluated"


def _cohort_summary(traces: list[dict[str, Any]], field: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trace in traces:
        value = str(trace.get("cohort", {}).get(field) or "unknown")
        grouped.setdefault(value, []).append(trace)
    result: dict[str, Any] = {}
    for value, members in sorted(grouped.items()):
        overall = Counter(_trace_overall_status(trace) for trace in members)
        outcomes = Counter(
            str(trace.get("ground_truth", {}).get("expected_outcome") or "unreviewed")
            for trace in members
        )
        existence = Counter(
            str(
                trace.get("outcome_contracts", {})
                .get("existence", {})
                .get("status")
                or "not_evaluated"
            )
            for trace in members
        )
        localization = Counter()
        contamination = Counter()
        dispositions = Counter()
        for trace in members:
            contracts = trace.get("outcome_contracts", {})
            disposition_contract = contracts.get("disposition", {})
            dispositions[
                str(
                    disposition_contract.get("value")
                    or disposition_contract.get("status")
                    or "unknown"
                )
            ] += 1
            if trace.get("ground_truth", {}).get("expected_outcome") == "sermon":
                localization[
                    str(contracts.get("localization", {}).get("status") or "not_evaluated")
                ] += 1
                contamination[
                    str(contracts.get("contamination", {}).get("status") or "not_evaluated")
                ] += 1
        result[value] = {
            "trace_count": len(members),
            "fixture_outcome_counts": dict(sorted(outcomes.items())),
            "overall_outcome_counts": dict(sorted(overall.items())),
            "existence_contract_counts": dict(sorted(existence.items())),
            "positive_localization_contract_counts": dict(sorted(localization.items())),
            "positive_contamination_contract_counts": dict(sorted(contamination.items())),
            "final_disposition_counts": dict(sorted(dispositions.items())),
        }
    return result


def _sensitivity_table(
    traces: list[dict[str, Any]], thresholds: Iterable[float], metric: str
) -> list[dict[str, Any]]:
    values: list[float] = []
    for trace in traces:
        if trace.get("ground_truth", {}).get("expected_outcome") != "sermon":
            continue
        final = next(
            (stage for stage in trace.get("stages", []) if stage.get("key") == "final"),
            None,
        )
        value = final.get("measurements", {}).get(metric) if final else None
        if isinstance(value, (int, float)):
            values.append(float(value))
    rows = []
    for threshold in thresholds:
        passed = sum(
            value >= threshold if metric == "reviewed_sermon_coverage" else value <= threshold
            for value in values
        )
        rows.append(
            {
                "threshold": threshold,
                "evaluated": len(values),
                "pass": passed,
                "fail": len(values) - passed,
            }
        )
    return rows


def aggregate_diagnostic_traces(
    traces: list[dict[str, Any]],
    *,
    missing: list[dict[str, str]] | None = None,
    scope: str = "reviewed_fixtures",
    population_summary: dict[str, Any] | None = None,
    identity_automation_blockers: Mapping[str, Any] | None = None,
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
    signatures: dict[str, list[str]] = {}
    fixture_outcomes = Counter()
    recovery = Counter()
    dispositions = Counter()
    reviewed_dispositions = Counter()
    unreviewed_dispositions = Counter()
    reviewed_overall = Counter()
    localization = Counter()
    contamination = Counter()
    existence = Counter()
    overall = Counter()
    regret = Counter()
    precision_regret = Counter()
    automatic_precision_regret = Counter()
    manual_precision_regret = Counter()
    refinement_regret = Counter()
    arbitration_regret = Counter()
    terminal_failure_causes = Counter()
    contamination_breach = Counter()
    boundary_patterns = Counter()
    material_boundary_patterns = Counter()
    boundary_component_causes = Counter()
    final_contamination_seconds = Counter()
    identity_effects = Counter()
    identity_edge_counts = Counter()
    identity_operational_states = Counter()
    identity_states_by_disposition: dict[str, Counter[str]] = {}
    identity_observation_states = Counter()
    identity_association_outcomes = Counter()
    identity_latest_association_outcomes = Counter()
    identity_latest_attempt_ordering_bases = Counter()
    identity_funnel_classifications = Counter()
    identity_funnel_failure_locations = Counter()
    identity_funnel_hypotheses = Counter()
    identity_funnel_acoustic_ranks = Counter()
    identity_funnel_evaluation = Counter()
    identity_association_attempt_count = 0
    identity_association_attempt_trace_count = 0
    identity_profiled_trace_count = 0
    identity_effective_profile_membership_count = 0
    identity_event_count = 0
    identity_trace_count = 0
    identity_temporal_movement_count = 0
    identity_causal_adjustment_count = 0
    identity_unconsumed_signal_count = 0
    manual_override_count = 0
    joined_candidate_count = 0
    traces_with_joined_candidates = 0
    selected_joined_count = 0
    rejected_join_attempts_persisted = 0
    for trace in traces:
        video_id = str(trace["video"]["youtube_video_id"])
        failure = (trace.get("earliest_observed_failure") or {}).get("stage") or "none"
        affected.setdefault(str(failure), []).append(video_id)
        expected_outcome = trace.get("ground_truth", {}).get("expected_outcome") or "unreviewed"
        fixture_outcomes[str(expected_outcome)] += 1
        recovery[
            str(trace.get("causal_path_status") or trace.get("recovery_status") or "unknown")
        ] += 1
        overall[_trace_overall_status(trace)] += 1
        candidate_regret = trace.get("candidate_regret", {})
        regret[str(candidate_regret.get("classification") or "not_evaluated")] += 1
        precision_classification = str(
            candidate_regret.get("precision_classification") or "not_evaluated"
        )
        precision_regret[precision_classification] += 1
        stage_regret = trace.get("stage_regret", {})
        refinement_classification = str(
            stage_regret.get("refinement", {}).get("classification") or "not_evaluated"
        )
        arbitration_classification = str(
            stage_regret.get("arbitration", {}).get("classification") or "not_evaluated"
        )
        refinement_regret[refinement_classification] += 1
        arbitration_regret[arbitration_classification] += 1
        for dimension, path in trace.get("contract_paths", {}).items():
            if dimension == "stage_order" or not isinstance(path, dict):
                continue
            if path.get("terminal_failure"):
                stage = str(path.get("likely_causal_stage") or "unknown")
                terminal_failure_causes[f"{dimension}:{stage}"] += 1
        identity = trace.get("identity_boundary_feedback", {})
        event_count = int(identity.get("event_count") or 0)
        identity_event_count += event_count
        identity_trace_count += int(event_count > 0)
        identity_temporal_movement_count += int(
            identity.get("temporal_boundary_movement_count") or 0
        )
        identity_causal_adjustment_count += int(
            identity.get("causal_adjustment_count") or 0
        )
        identity_unconsumed_signal_count += int(
            identity.get("unconsumed_same_edge_signal_count") or 0
        )
        for event in identity.get("events", []) or []:
            identity_effects[str(event.get("observed_effect") or "unknown")] += 1
            identity_edge_counts[str(event.get("edge") or "unknown")] += 1
        identity_outcome = trace.get("identity_outcome", {})
        identity_operational_states[
            str(identity_outcome.get("state") or "not_observed")
        ] += 1
        identity_observation_states[
            str(identity_outcome.get("observation_status") or "not_observed")
        ] += 1
        attempt_count = int(identity_outcome.get("association_attempt_count") or 0)
        identity_association_attempt_count += attempt_count
        identity_association_attempt_trace_count += int(attempt_count > 0)
        latest_association_outcome = identity_outcome.get(
            "latest_association_outcome"
        )
        if latest_association_outcome:
            identity_latest_association_outcomes[
                str(latest_association_outcome)
            ] += 1
        ordering_basis = identity_outcome.get("latest_attempt_ordering_basis")
        if ordering_basis:
            identity_latest_attempt_ordering_bases[str(ordering_basis)] += 1
        funnel_review = identity_outcome.get("candidate_funnel_review", {})
        funnel_classification = funnel_review.get("classification")
        if funnel_classification:
            identity_funnel_classifications[str(funnel_classification)] += 1
            reviewed_funnel = funnel_classification != "identity_unreviewed"
            observed_reviewed_funnel = (
                reviewed_funnel
                and funnel_review.get("status") == "observed"
            )
            if observed_reviewed_funnel:
                identity_funnel_evaluation["observed_reviewed_identity"] += 1
            if observed_reviewed_funnel and funnel_classification not in {
                "correct_profile_ineligible",
                "profile_redirect_resolution_issue",
            }:
                identity_funnel_evaluation[
                    "comparison_eligible_reviewed_identity"
                ] += 1
            if reviewed_funnel and str(funnel_classification).startswith("compared_"):
                identity_funnel_evaluation[
                    "correct_profile_compared"
                ] += 1
            if (
                reviewed_funnel
                and funnel_classification == "retrieved_below_shortlist_cutoff"
            ):
                identity_funnel_evaluation[
                    "correct_profile_below_shortlist_cutoff"
                ] += 1
            retrieval_candidate = (
                funnel_review.get("evidence", {}).get("retrieval_candidate")
            )
            if reviewed_funnel and isinstance(retrieval_candidate, dict):
                if retrieval_candidate.get("selected_for_comparison"):
                    identity_funnel_evaluation[
                        "correct_profile_selected_for_comparison"
                    ] += 1
                acoustic_rank = retrieval_candidate.get(
                    "all_eligible_acoustic_rank"
                )
                if isinstance(acoustic_rank, int):
                    identity_funnel_acoustic_ranks[str(acoustic_rank)] += 1
        funnel_location = funnel_review.get("observed_failure_location")
        if funnel_location:
            identity_funnel_failure_locations[str(funnel_location)] += 1
        for hypothesis in funnel_review.get("causal_hypotheses", []) or []:
            identity_funnel_hypotheses[str(hypothesis)] += 1
        for outcome, count in identity_outcome.get(
            "association_outcome_counts", {}
        ).items():
            identity_association_outcomes[str(outcome)] += int(count)
        profile_ids = identity_outcome.get("effective_profile_ids", []) or []
        identity_profiled_trace_count += int(bool(profile_ids))
        identity_effective_profile_membership_count += len(profile_ids)
        attribution = trace.get("contamination_attribution", {})
        contamination_breach[str(attribution.get("earliest_breach_stage") or "none")] += 1
        for pattern in attribution.get("final_boundary_error_patterns", []) or []:
            boundary_patterns[str(pattern)] += 1
        for pattern in attribution.get("material_final_contamination_patterns", []) or []:
            material_boundary_patterns[str(pattern)] += 1
        for component, stage in attribution.get(
            "terminal_component_causal_stages", {}
        ).items():
            boundary_component_causes[f"{component}:{stage}"] += 1
        for component, seconds in attribution.get(
            "final_contamination_seconds", {}
        ).items():
            if isinstance(seconds, (int, float)):
                final_contamination_seconds[str(component)] += float(seconds)
        contracts = trace.get("outcome_contracts", {})
        disposition_contract = contracts.get("disposition", {})
        disposition_status = str(disposition_contract.get("status") or "unknown")
        disposition_value = str(
            disposition_contract.get("value") or disposition_status
        )
        dispositions[disposition_value] += 1
        identity_state = str(identity_outcome.get("state") or "not_observed")
        identity_states_by_disposition.setdefault(
            disposition_value, Counter()
        )[identity_state] += 1
        if expected_outcome == "unreviewed":
            unreviewed_dispositions[disposition_value] += 1
        else:
            reviewed_dispositions[disposition_value] += 1
            reviewed_overall[_trace_overall_status(trace)] += 1
        existence[str(contracts.get("existence", {}).get("status") or "not_evaluated")] += 1
        if expected_outcome == "sermon":
            localization[
                str(contracts.get("localization", {}).get("status") or "not_evaluated")
            ] += 1
            contamination[
                str(contracts.get("contamination", {}).get("status") or "not_evaluated")
            ] += 1
        manual_override = bool(contracts.get("manual_override_applied"))
        manual_override_count += int(manual_override)
        target_precision = (
            manual_precision_regret if manual_override else automatic_precision_regret
        )
        target_precision[precision_classification] += 1
        by_key = {stage["key"]: stage for stage in trace.get("stages", [])}
        join_evidence = trace.get("join_observability", {})
        joined_here = int(join_evidence.get("joined_candidate_count") or 0)
        joined_candidate_count += joined_here
        traces_with_joined_candidates += int(joined_here > 0)
        selected_joined_count += int(bool(join_evidence.get("selected_joined_candidate")))
        rejected_join_attempts_persisted += int(
            bool(join_evidence.get("rejected_join_attempts_persisted"))
        )

        def failed(stage_key: str, contract: str = "contract") -> bool:
            stage = by_key.get(stage_key, {})
            if contract == "contamination":
                value = stage.get("quality_contracts", {}).get("contamination", {})
            else:
                value = stage.get("contract", {})
            return value.get("status") == "fail"

        run_signatures: list[str] = []
        if expected_outcome == "sermon":
            if failed("candidates") and manual_override:
                run_signatures.append("candidate_omission_masked_by_manual_override")
            if failed("selected") and not failed("candidates") and manual_override:
                run_signatures.append("ranking_loss_masked_by_manual_override")
            if (
                not failed("fine")
                and failed("arbitration")
                and not manual_override
            ):
                run_signatures.append("arbitration_clipped_valid_refined_window")
            if failed("final", "contamination"):
                run_signatures.append("high_final_contamination")
                if precision_classification in {
                    "proposal_boundary_failure",
                    "ranking_precision_loss",
                    "recall_precision_tradeoff",
                }:
                    run_signatures.append(
                        f"candidate_precision_{precision_classification}"
                    )
            if (
                disposition_status == "review_required"
                or disposition_value == "review_required"
            ):
                run_signatures.append("positive_requires_review")
            if refinement_classification in {
                "localization_regression",
                "catastrophic_structural_loss",
                "contamination_regression",
            }:
                run_signatures.append(f"refinement_{refinement_classification}")
            if arbitration_classification in {
                "localization_regression",
                "contamination_regression",
            }:
                run_signatures.append(f"arbitration_{arbitration_classification}")
        elif expected_outcome == "no_sermon":
            if failed("verifier"):
                run_signatures.append("recording_verifier_false_positive")
            elif contracts.get("existence", {}).get("status") == "fail":
                run_signatures.append("negative_false_acceptance_without_verifier_failure")
        for signature in run_signatures:
            signatures.setdefault(signature, []).append(video_id)
    reviewed_trace_count = sum(
        trace.get("ground_truth", {}).get("status") == "available"
        for trace in traces
    )
    unreviewed_trace_count = len(traces) - reviewed_trace_count
    missing_reason_counts = Counter(
        str(item.get("reason") or "unknown") for item in (missing or [])
    )
    reviewed_fixture_without_trace_count = missing_reason_counts.get(
        "reviewed_fixture_video_or_extraction_missing", 0
    )
    artifact_missing_count = (
        len(missing or []) - reviewed_fixture_without_trace_count
    )
    population = {
        "scope": scope,
        "population_count": len(traces) + len(missing or []),
        "diagnostic_trace_count": len(traces),
        "reviewed_trace_count": reviewed_trace_count,
        "unreviewed_trace_count": unreviewed_trace_count,
        "missing_or_invalid_artifact_count": len(missing or []),
        "extraction_artifact_missing_or_invalid_count": artifact_missing_count,
        "reviewed_fixture_without_trace_count": reviewed_fixture_without_trace_count,
        "missing_reason_counts": dict(sorted(missing_reason_counts.items())),
        **(population_summary or {}),
    }
    return {
        "schema_version": 7,
        "report_kind": "sermon_isolation_systemic_diagnostics",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trace_count": len(traces),
        "missing_count": len(missing or []),
        "population": population,
        "observed_failure_counts": dict(sorted(observed.items())),
        "root_cause_hypothesis_counts": dict(sorted(causes.items())),
        "fixture_outcome_counts": dict(sorted(fixture_outcomes.items())),
        "recovery_status_counts": dict(sorted(recovery.items())),
        "causal_path_status_counts": dict(sorted(recovery.items())),
        "overall_outcome_counts": dict(sorted(overall.items())),
        "final_disposition_counts": dict(sorted(dispositions.items())),
        "reviewed_final_disposition_counts": dict(
            sorted(reviewed_dispositions.items())
        ),
        "unreviewed_final_disposition_counts": dict(
            sorted(unreviewed_dispositions.items())
        ),
        "reviewed_overall_outcome_counts": dict(sorted(reviewed_overall.items())),
        "existence_contract_counts": dict(sorted(existence.items())),
        "positive_localization_contract_counts": dict(sorted(localization.items())),
        "positive_contamination_contract_counts": dict(sorted(contamination.items())),
        "manual_override_count": manual_override_count,
        "cohorts": {
            "outcome_mode": _cohort_summary(traces, "outcome_mode"),
            "evaluation_partition": _cohort_summary(traces, "evaluation_partition"),
            "source_family_id": _cohort_summary(traces, "source_family_id"),
            "transcript_source": _cohort_summary(traces, "transcript_source"),
            "algorithm_version": _cohort_summary(traces, "algorithm_version"),
        },
        "unknown_evaluation_partition_count": sum(
            trace.get("cohort", {}).get("evaluation_partition") == "unknown"
            for trace in traces
        ),
        "threshold_sensitivity": {
            "reviewed_sermon_coverage": _sensitivity_table(
                traces, RECALL_SENSITIVITY_THRESHOLDS, "reviewed_sermon_coverage"
            ),
            "contamination_ratio": _sensitivity_table(
                traces, CONTAMINATION_SENSITIVITY_THRESHOLDS, "contamination_ratio"
            ),
        },
        "candidate_regret_classification_counts": dict(sorted(regret.items())),
        "candidate_precision_classification_counts": dict(
            sorted(precision_regret.items())
        ),
        "automatic_candidate_precision_classification_counts": dict(
            sorted(automatic_precision_regret.items())
        ),
        "manual_override_candidate_precision_classification_counts": dict(
            sorted(manual_precision_regret.items())
        ),
        "refinement_regret_classification_counts": dict(
            sorted(refinement_regret.items())
        ),
        "arbitration_regret_classification_counts": dict(
            sorted(arbitration_regret.items())
        ),
        "terminal_failure_causal_counts": dict(
            sorted(terminal_failure_causes.items())
        ),
        "contamination_earliest_breach_counts": dict(sorted(contamination_breach.items())),
        "final_boundary_error_pattern_counts": dict(sorted(boundary_patterns.items())),
        "material_final_contamination_pattern_counts": dict(
            sorted(material_boundary_patterns.items())
        ),
        "terminal_boundary_component_causal_counts": dict(
            sorted(boundary_component_causes.items())
        ),
        "final_contamination_seconds_by_component": {
            key: round(value, 3)
            for key, value in sorted(final_contamination_seconds.items())
        },
        "identity_boundary_feedback_summary": {
            "event_count": identity_event_count,
            "trace_count": identity_trace_count,
            "temporal_boundary_movement_count": identity_temporal_movement_count,
            "causal_adjustment_count": identity_causal_adjustment_count,
            "unconsumed_same_edge_signal_count": identity_unconsumed_signal_count,
            "observed_effect_counts": dict(sorted(identity_effects.items())),
            "edge_counts": dict(sorted(identity_edge_counts.items())),
            "causal_interpretation": (
                "causal events persisted"
                if identity_causal_adjustment_count
                else "temporal association only"
            ),
        },
        "identity_outcome_summary": {
            "count_unit": "unique_videos",
            "trace_count": len(traces),
            "state_counts": dict(sorted(identity_operational_states.items())),
            "state_counts_by_disposition": {
                disposition: dict(sorted(counts.items()))
                for disposition, counts in sorted(
                    identity_states_by_disposition.items()
                )
            },
            "state_counts_reconcile": sum(identity_operational_states.values())
            == len(traces),
            "observation_status_counts": dict(
                sorted(identity_observation_states.items())
            ),
            "association_attempt_count": identity_association_attempt_count,
            "association_attempt_trace_count": (
                identity_association_attempt_trace_count
            ),
            "latest_association_outcome_counts": dict(
                sorted(identity_latest_association_outcomes.items())
            ),
            "latest_attempt_ordering_basis_counts": dict(
                sorted(identity_latest_attempt_ordering_bases.items())
            ),
            "candidate_funnel": {
                "reviewed_identity_classification_counts": dict(
                    sorted(identity_funnel_classifications.items())
                ),
                "observed_failure_location_counts": dict(
                    sorted(identity_funnel_failure_locations.items())
                ),
                "causal_hypothesis_counts": dict(
                    sorted(identity_funnel_hypotheses.items())
                ),
                "retrospective_routing_evaluation_counts": dict(
                    sorted(identity_funnel_evaluation.items())
                ),
                "correct_profile_acoustic_rank_counts": dict(
                    sorted(
                        identity_funnel_acoustic_ranks.items(),
                        key=lambda item: int(item[0]),
                    )
                ),
                "interpretation": (
                    "Failure locations come from persisted routing decisions. "
                    "Miss explanations remain causal hypotheses unless the "
                    "funnel directly records the relevant exclusion or cutoff. "
                    "Retrospective counts use later reviewed membership only as "
                    "evaluation truth and are not production identity evidence."
                ),
            },
            "association_outcome_counts": dict(
                sorted(identity_association_outcomes.items())
            ),
            "profiled_trace_count": identity_profiled_trace_count,
            "effective_profile_membership_count": (
                identity_effective_profile_membership_count
            ),
            "interpretation": (
                "Primary outcomes are mutually exclusive unique-video states. Machine "
                "association outcomes are proposals, while effective profile membership "
                "is reviewed identity evidence. Event volume is reported separately."
            ),
        },
        "automation_blocker_analysis": {
            "schema_version": 1,
            "domains": {
                "identity": dict(identity_automation_blockers or {})
            },
            "interpretation": (
                "Domain projections preserve observed conditions, structural "
                "inferences, and recommendations as separate epistemic claims."
            ),
        },
        "join_observability": {
            "joined_candidate_count": joined_candidate_count,
            "traces_with_joined_candidates": traces_with_joined_candidates,
            "selected_joined_candidate_count": selected_joined_count,
            "rejected_join_attempts_persisted_trace_count": rejected_join_attempts_persisted,
            "rejected_join_attempts_available": bool(traces)
            and rejected_join_attempts_persisted == len(traces),
        },
        "failure_signature_counts": {
            key: len(value) for key, value in sorted(signatures.items())
        },
        "affected_video_ids_by_failure_signature": {
            key: sorted(value) for key, value in sorted(signatures.items())
        },
        "affected_video_ids_by_observed_failure": {
            key: sorted(value) for key, value in sorted(affected.items())
        },
        "missing": missing or [],
        "traces": traces,
    }


def build_systemic_outcome_mermaid(report: dict[str, Any]) -> str:
    """Render the complete operational population and reviewed-quality subset."""
    population = report.get("population", {})
    trace_count = int(report.get("trace_count") or 0)
    missing_count = int(report.get("missing_count") or 0)
    database_count = population.get("database_video_count")
    population_count = int(
        population.get("population_count") or trace_count + missing_count
    )
    root_count = int(database_count) if isinstance(database_count, int) else population_count
    extraction_count = int(
        population.get("latest_extraction_count") or trace_count + missing_count
    )
    without_extraction = int(
        population.get("videos_without_extraction_count")
        or max(0, root_count - extraction_count)
    )
    reviewed_count = int(population.get("reviewed_trace_count") or 0)
    unreviewed_count = int(population.get("unreviewed_trace_count") or 0)
    artifact_missing_count = int(
        population.get("extraction_artifact_missing_or_invalid_count")
        if population.get("extraction_artifact_missing_or_invalid_count") is not None
        else missing_count
    )
    reviewed_fixture_without_trace_count = int(
        population.get("reviewed_fixture_without_trace_count") or 0
    )
    missing_nodes = "N,M,F" if reviewed_fixture_without_trace_count else "N,M"
    lines = [
        "flowchart TD",
        f'  P["Database videos<br/>{root_count}"]',
        f'  E["Latest extraction record<br/>{extraction_count}"]',
        f'  N["No extraction record<br/>{without_extraction}"]',
        "  P --> E",
        "  P --> N",
        f'  T["Diagnostic trace<br/>{trace_count}"]',
        f'  M["Missing or invalid extraction artifact<br/>{artifact_missing_count}"]',
        "  E --> T",
        "  E --> M",
        f'  R["Reviewed subset<br/>{reviewed_count}"]',
        f'  U["Unreviewed subset<br/>{unreviewed_count}"]',
        "  T --> R",
        "  T --> U",
    ]
    if reviewed_fixture_without_trace_count:
        lines.extend(
            [
                f'  F["Reviewed fixture without trace<br/>'
                f'{reviewed_fixture_without_trace_count}"]',
                "  P -. review coverage gap .-> F",
            ]
        )
    for index, (status, count) in enumerate(
        sorted(
            population.get("videos_without_extraction_status_counts", {}).items(),
            key=lambda item: (-item[1], item[0]),
        )
    ):
        label = str(status).replace('"', "'").replace("_", " ")
        lines.append(f'  S{index}["{label}<br/>{count}"]')
        lines.append(f"  N --> S{index}")
    for index, (disposition, count) in enumerate(
        sorted(
            report.get("final_disposition_counts", {}).items(),
            key=lambda item: (-item[1], item[0]),
        )
    ):
        label = str(disposition).replace('"', "'").replace("_", " ")
        lines.append(f'  D{index}["{label}<br/>{count}"]')
        lines.append(f"  T --> D{index}")
    for index, (outcome, count) in enumerate(
        sorted(
            report.get("reviewed_overall_outcome_counts", {}).items(),
            key=lambda item: (-item[1], item[0]),
        )
    ):
        label = str(outcome).replace('"', "'").replace("_", " ")
        lines.append(f'  Q{index}["Reviewed: {label}<br/>{count}"]')
        lines.append(f"  R --> Q{index}")
    identity_outcomes = report.get("identity_outcome_summary", {})
    identity_nodes = ["I"]
    proposed_match_node: str | None = None
    lines.extend(
        [
            f'  I["Identity operational outcomes<br/>'
            f'{identity_outcomes.get("trace_count", trace_count)}"]',
            "  T --> I",
        ]
    )
    for index, (state, count) in enumerate(
        sorted(
            identity_outcomes.get("state_counts", {}).items(),
            key=lambda item: (-item[1], item[0]),
        )
    ):
        label = str(state).replace('"', "'").replace("_", " ")
        node = f"IS{index}"
        if state == "association_proposed_match":
            proposed_match_node = node
        identity_nodes.append(node)
        lines.append(f'  {node}["{label}<br/>{count}"]')
        lines.append(f"  I --> {node}")
    blocker_analysis = report.get("automation_blocker_analysis", {})
    identity_blockers = (
        blocker_analysis.get("domains", {}).get("identity", {})
        if isinstance(blocker_analysis, dict)
        else {}
    )
    automation = identity_blockers.get("operational_association_summary", {})
    automation_nodes: list[str] = []
    current_proposal_count = int(automation.get("current_proposal_count") or 0)
    if current_proposal_count:
        automation_nodes.append("OA")
        lines.append(
            f'  OA["Operational automation<br/>{current_proposal_count} current proposals"]'
        )
        lines.append(
            f"  {proposed_match_node or 'I'} --> OA"
        )
        for index, (state, count) in enumerate(
            sorted(
                automation.get("state_counts", {}).items(),
                key=lambda item: (-item[1], item[0]),
            )
        ):
            if not count:
                continue
            label = str(state).replace('"', "'").replace("_", " ")
            node = f"OAS{index}"
            automation_nodes.append(node)
            lines.append(f'  {node}["{label}<br/>{count}"]')
            lines.append(f"  OA --> {node}")
    advisory_trace_count = int(
        report.get("identity_boundary_feedback_summary", {}).get("trace_count") or 0
    )
    if advisory_trace_count:
        identity_nodes.append("IB")
        lines.append(
            f'  IB["Boundary feedback observed<br/>{advisory_trace_count} videos"]'
        )
        lines.append("  I -. feedback subset .-> IB")
        lines.append("  IB -. feedback to sermon boundaries .-> T")
    lines.extend(
        [
            "  classDef population fill:#e8eef8,stroke:#46658a,color:#172536",
            "  classDef reviewed fill:#d9f2df,stroke:#26733a,color:#102915",
            "  classDef identity fill:#ece3fa,stroke:#6b4c91,color:#28183b",
            "  classDef automation fill:#dceef8,stroke:#26718c,color:#102934",
            "  classDef missing fill:#f9e5c7,stroke:#a16413,color:#3b2408",
            "  class P,E,T,U population",
            "  class R reviewed",
            f"  class {','.join(identity_nodes)} identity",
            *(
                [f"  class {','.join(automation_nodes)} automation"]
                if automation_nodes
                else []
            ),
            f"  class {missing_nodes} missing",
        ]
    )
    return "\n".join(lines)


def build_systemic_markdown(report: dict[str, Any]) -> str:
    population = report.get("population", {})
    lines = [
        "# Systemic Pipeline Diagnostics",
        "",
        f"- Scope: {population.get('scope', 'reviewed_fixtures')}",
        f"- Database videos: {population.get('database_video_count', 'not reported')}",
        f"- Latest extraction records: "
        f"{population.get('latest_extraction_count', report['trace_count'])}",
        f"- Traces: {report['trace_count']}",
        f"- Reviewed traces: {population.get('reviewed_trace_count', report['trace_count'])}",
        f"- Unreviewed traces: {population.get('unreviewed_trace_count', 0)}",
        f"- Missing or invalid extraction artifacts: "
        f"{population.get('extraction_artifact_missing_or_invalid_count', report['missing_count'])}",
        f"- Reviewed fixtures without a trace: "
        f"{population.get('reviewed_fixture_without_trace_count', 0)}",
        f"- Manual overrides: {report['manual_override_count']}",
        f"- Unknown evaluation partitions: {report.get('unknown_evaluation_partition_count', 0)}",
        "",
        "## All-outcome map",
        "",
        "```mermaid",
        build_systemic_outcome_mermaid(report),
        "```",
        "",
        "## Overall outcomes",
        "",
        "| Outcome | Count |",
        "|---|---:|",
    ]
    for status, count in sorted(
        report.get("overall_outcome_counts", {}).items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"| {status} | {count} |")
    lines.extend(
        [
            "",
            "## Operational dispositions",
            "",
            "| Disposition | All | Reviewed | Unreviewed |",
            "|---|---:|---:|---:|",
        ]
    )
    all_dispositions = report.get("final_disposition_counts", {})
    reviewed_dispositions = report.get("reviewed_final_disposition_counts", {})
    unreviewed_dispositions = report.get("unreviewed_final_disposition_counts", {})
    for disposition in sorted(
        set(all_dispositions) | set(reviewed_dispositions) | set(unreviewed_dispositions)
    ):
        lines.append(
            f"| {disposition} | {all_dispositions.get(disposition, 0)} | "
            f"{reviewed_dispositions.get(disposition, 0)} | "
            f"{unreviewed_dispositions.get(disposition, 0)} |"
        )
    identity_outcomes = report.get("identity_outcome_summary", {})
    lines.extend(
        [
            "",
            "## Identity operational outcomes",
            "",
            identity_outcomes.get("interpretation", "No identity outcomes reported."),
            "",
            "| State | Traces |",
            "|---|---:|",
        ]
    )
    for state, count in sorted(
        identity_outcomes.get("state_counts", {}).items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"| {state} | {count} |")
    lines.extend(
        [
            "",
            "### Sermon-to-identity transitions",
            "",
            "| Sermon disposition | Identity outcome | Unique videos |",
            "|---|---|---:|",
        ]
    )
    transition_rows = [
        (disposition, state, count)
        for disposition, state_counts in identity_outcomes.get(
            "state_counts_by_disposition", {}
        ).items()
        for state, count in state_counts.items()
    ]
    for disposition, state, count in sorted(
        transition_rows, key=lambda item: (item[0], -item[2], item[1])
    ):
        lines.append(f"| {disposition} | {state} | {count} |")
    lines.extend(
        [
            "",
            f"- Unique-video denominator: {identity_outcomes.get('trace_count', 0)}",
            "- State counts reconcile: "
            f"{identity_outcomes.get('state_counts_reconcile', False)}",
            "",
            "| Latest association outcome | Unique videos |",
            "|---|---:|",
        ]
    )
    for outcome, count in sorted(
        identity_outcomes.get("latest_association_outcome_counts", {}).items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"| {outcome} | {count} |")
    candidate_funnel = identity_outcomes.get("candidate_funnel", {})
    lines.extend(
        [
            "",
            "### Reviewed identity candidate funnel",
            "",
            candidate_funnel.get(
                "interpretation", "No candidate-funnel evidence reported."
            ),
            "",
            "| Funnel classification | Reviewed identities |",
            "|---|---:|",
        ]
    )
    for classification, count in sorted(
        candidate_funnel.get(
            "reviewed_identity_classification_counts", {}
        ).items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"| {classification} | {count} |")
    lines.extend(
        [
            "",
            "| Observed failure location | Reviewed identities |",
            "|---|---:|",
        ]
    )
    for location, count in sorted(
        candidate_funnel.get("observed_failure_location_counts", {}).items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"| {location} | {count} |")
    lines.extend(
        [
            "",
            "| Retrospective routing measure | Reviewed identities |",
            "|---|---:|",
        ]
    )
    for measure, count in sorted(
        candidate_funnel.get(
            "retrospective_routing_evaluation_counts", {}
        ).items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"| {measure} | {count} |")
    rank_counts = candidate_funnel.get(
        "correct_profile_acoustic_rank_counts", {}
    )
    if rank_counts:
        lines.extend(
            [
                "",
                "| Correct-profile acoustic rank | Reviewed identities |",
                "|---:|---:|",
            ]
        )
        for rank, count in sorted(
            rank_counts.items(), key=lambda item: int(item[0])
        ):
            lines.append(f"| {rank} | {count} |")
    lines.extend(
        [
            "",
            "| Latest-attempt ordering basis | Videos |",
            "|---|---:|",
        ]
    )
    for basis, count in sorted(
        identity_outcomes.get("latest_attempt_ordering_basis_counts", {}).items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"| {basis} | {count} |")
    blocker_analysis = report.get("automation_blocker_analysis", {})
    identity_blockers = (
        blocker_analysis.get("domains", {}).get("identity", {})
        if isinstance(blocker_analysis, dict)
        else {}
    )
    operational = identity_blockers.get(
        "operational_association_summary", {}
    )
    lines.extend(
        [
            "",
            "## Identity operational automation",
            "",
            operational.get(
                "interpretation",
                "No operational machine-assignment projection reported.",
            ),
            "",
            f"- Reviewed profile membership: "
            f"{operational.get('reviewed_profile_membership_count', 0)}",
            f"- Current proposals: {operational.get('current_proposal_count', 0)}",
            f"- Active provisional assignments: "
            f"{operational.get('active_provisional_assignment_count', 0)}",
            f"- Eligible unapplied assignments: "
            f"{operational.get('eligible_unapplied_assignment_count', 0)}",
            f"- Blocked by profile readiness: "
            f"{operational.get('proposal_blocked_profile_readiness_count', 0)}",
            f"- Blocked by policy or circuit state: "
            f"{operational.get('proposal_blocked_policy_or_circuit_count', 0)}",
            f"- Genuinely requiring sermon-level human review: "
            f"{operational.get('proposal_genuinely_requires_human_review_count', 0)}",
            f"- Missing or noncurrent assignment evidence: "
            f"{operational.get('assignment_evidence_missing_or_noncurrent_count', 0)}",
            f"- Stale proposals or assignments excluded: "
            f"{operational.get('stale_proposal_or_assignment_excluded_count', 0)}",
            f"- Human reviews avoided by active/eligible automation: "
            f"{operational.get('human_reviews_avoided_by_current_automation_count', 0)}",
            f"- State counts reconcile: "
            f"{operational.get('state_counts_reconcile', False)}",
            "",
            "| Operational state | Unique current videos |",
            "|---|---:|",
        ]
    )
    for state, count in sorted(
        operational.get("state_counts", {}).items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"| {state} | {count} |")
    ambiguities = operational.get("remaining_ambiguities", []) or []
    if ambiguities:
        lines.extend(["", "Remaining reconstruction ambiguity:", ""])
        lines.extend(f"- {value}" for value in ambiguities)
    lines.extend(
        [
            "",
            "## Identity automation blockers and opportunity",
            "",
            identity_blockers.get(
                "interpretation", "No identity automation-blocker analysis reported."
            ),
            "",
            "Directly blocked work is counted separately from contingent cascade. "
            "Rows must not be summed because one profile or sermon can have a chain "
            "of blockers.",
            "",
            "| Blocker | Observed at | Conditions | Profiles | Observations | "
            "Accepted unresolved | Direct work | Structural work | Human necessity | "
            "Next operation | Causal hypotheses |",
            "|---|---|---|---:|---:|---:|---:|---:|---|---|---|",
        ]
    )
    for blocker in identity_blockers.get("blocker_classes", []) or []:
        human = blocker.get("human_necessity") or {}
        operation = blocker.get("observable_next_operation") or {}
        lines.append(
            f"| {blocker.get('blocker_class', 'unknown')} | "
            f"{blocker.get('observed_blocking_location', 'unknown')} | "
            f"{', '.join(blocker.get('blocking_condition_codes', [])) or 'none'} | "
            f"{blocker.get('affected_profile_count', 0)} | "
            f"{blocker.get('affected_observation_count', 0)} | "
            f"{blocker.get('accepted_unresolved_sermon_count', 0)} | "
            f"{blocker.get('directly_blocked_operation_count', 0)} | "
            f"{blocker.get('structurally_derived_operation_count', 0)} | "
            f"{human.get('classification', 'not_established')} | "
            f"{operation.get('operation', 'none')} | "
            f"{', '.join(blocker.get('causal_hypotheses', [])) or 'none'} |"
        )
    priorities = identity_blockers.get("investigation_priorities", []) or []
    if priorities:
        lines.extend(
            [
                "",
                "### Evidence-backed investigation order",
                "",
                "This ordering uses directly observed blocked work, not predicted yield.",
                "",
                "| Blocker | Direct work | Structural work | Accepted unresolved | "
                "Investigation |",
                "|---|---:|---:|---:|---|",
            ]
        )
        for priority in priorities:
            operation = priority.get("next_operation") or {}
            lines.append(
                f"| {priority.get('blocker_class', 'unknown')} | "
                f"{priority.get('directly_blocked_operation_count', 0)} | "
                f"{priority.get('structurally_derived_operation_count', 0)} | "
                f"{priority.get('accepted_unresolved_sermon_count', 0)} | "
                f"{operation.get('operation', 'none')} |"
            )
    chains = [
        chain
        for chain in identity_blockers.get("profile_blocker_chains", []) or []
        if chain.get("directly_blocked_proposal_observation_ids")
        or chain.get("structurally_derived_next_operations")
    ]
    if chains:
        lines.extend(
            [
                "",
                "### Profile blocker chains with current work",
                "",
                "| Profile | Observed blocker chain | Direct proposals | Structural next work |",
                "|---:|---|---:|---:|",
            ]
        )
        for chain in chains:
            structural_work = []
            for operation in chain.get("structurally_derived_next_operations", []):
                left = operation.get("observation_a", {})
                right = operation.get("observation_b", {})
                left_label = left.get("youtube_video_id") or left.get(
                    "observation_id"
                )
                right_label = right.get("youtube_video_id") or right.get(
                    "observation_id"
                )
                structural_work.append(
                    f"compare {left_label or operation.get('fingerprints', ['?'])[0]} "
                    f"to {right_label or operation.get('fingerprints', ['?', '?'])[1]}"
                )
            lines.append(
                f"| {chain.get('profile_id')} | "
                f"{', '.join(chain.get('observed_blocker_chain', [])) or 'none'} | "
                f"{len(chain.get('directly_blocked_proposal_observation_ids', []))} | "
                f"{'; '.join(structural_work) or 'none'} |"
            )
    identity_feedback = report.get("identity_boundary_feedback_summary", {})
    lines.extend(
        [
            "",
            "### Identity processing volume (not population counts)",
            "",
            "These counts measure repeated processing events and must not be added to the "
            "unique-video pipeline branches.",
            "",
            f"- Videos with association attempts: "
            f"{identity_outcomes.get('association_attempt_trace_count', 0)}",
            f"- Persisted association attempt events: "
            f"{identity_outcomes.get('association_attempt_count', 0)}",
            f"- Videos with boundary feedback: "
            f"{identity_feedback.get('trace_count', 0)}",
            f"- Persisted boundary advisory events: "
            f"{identity_feedback.get('event_count', 0)}",
            "",
            "| Historical association outcome | Attempt events |",
            "|---|---:|",
        ]
    )
    for outcome, count in sorted(
        identity_outcomes.get("association_outcome_counts", {}).items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"| {outcome} | {count} |")
    lines.extend([
        "",
        "## Final outcomes",
        "",
        "| Measure | Pass | Fail | Not evaluated |",
        "|---|---:|---:|---:|",
        (
            "| Sermon existence | "
            f"{report['existence_contract_counts'].get('pass', 0)} | "
            f"{report['existence_contract_counts'].get('fail', 0)} | "
            f"{report['existence_contract_counts'].get('not_evaluated', 0)} |"
        ),
        (
            "| Positive localization | "
            f"{report['positive_localization_contract_counts'].get('pass', 0)} | "
            f"{report['positive_localization_contract_counts'].get('fail', 0)} | "
            f"{report['positive_localization_contract_counts'].get('not_evaluated', 0)} |"
        ),
        (
            "| Positive contamination | "
            f"{report['positive_contamination_contract_counts'].get('pass', 0)} | "
            f"{report['positive_contamination_contract_counts'].get('fail', 0)} | "
            f"{report['positive_contamination_contract_counts'].get('not_evaluated', 0)} |"
        ),
        "",
        "## Cohorts",
        "",
        "| Dimension | Value | Traces | Outcomes |",
        "|---|---|---:|---|",
    ])
    for dimension in ("outcome_mode", "evaluation_partition"):
        for value, summary in report.get("cohorts", {}).get(dimension, {}).items():
            outcomes = ", ".join(
                f"{status}={count}"
                for status, count in summary.get("overall_outcome_counts", {}).items()
            )
            lines.append(f"| {dimension} | {value} | {summary['trace_count']} | {outcomes} |")
    lines.extend([
        "",
        "## Threshold sensitivity",
        "",
        "| Metric | Threshold | Pass | Fail |",
        "|---|---:|---:|---:|",
    ])
    for metric, rows in report.get("threshold_sensitivity", {}).items():
        for row in rows:
            lines.append(
                f"| {metric} | {row['threshold']:.0%} | {row['pass']} | {row['fail']} |"
            )
    join = report.get("join_observability", {})
    lines.extend([
        "",
        "## Candidate and join observability",
        "",
        "| Measure | Count |",
        "|---|---:|",
    ])
    for classification, count in report.get(
        "candidate_regret_classification_counts", {}
    ).items():
        lines.append(f"| candidate regret: {classification} | {count} |")
    for classification, count in report.get(
        "candidate_precision_classification_counts", {}
    ).items():
        lines.append(f"| candidate precision: {classification} | {count} |")
    lines.extend(
        [
            f"| joined candidates observed | {join.get('joined_candidate_count', 0)} |",
            f"| traces with joined candidates | {join.get('traces_with_joined_candidates', 0)} |",
            f"| joined candidates selected | {join.get('selected_joined_candidate_count', 0)} |",
            "| rejected-attempt evidence persisted | "
            f"{join.get('rejected_join_attempts_persisted_trace_count', 0)} |",
        ]
    )
    lines.extend(
        [
            "",
            "## Stage regret and terminal causes",
            "",
            "| Measure | Classification | Count |",
            "|---|---|---:|",
        ]
    )
    for stage_key in ("refinement", "arbitration"):
        for classification, count in report.get(
            f"{stage_key}_regret_classification_counts", {}
        ).items():
            lines.append(f"| {stage_key} regret | {classification} | {count} |")
    for cause, count in report.get("terminal_failure_causal_counts", {}).items():
        lines.append(f"| terminal cause | {cause} | {count} |")
    identity = report.get("identity_boundary_feedback_summary", {})
    lines.extend(
        [
            "",
            "## Identity boundary feedback",
            "",
            f"- Advisories: {identity.get('event_count', 0)} across "
            f"{identity.get('trace_count', 0)} trace(s)",
            "- Later boundary movements: "
            f"{identity.get('temporal_boundary_movement_count', 0)}",
            f"- Persisted causal adjustments: {identity.get('causal_adjustment_count', 0)}",
            "- Unconsumed same-edge signals: "
            f"{identity.get('unconsumed_same_edge_signal_count', 0)}",
            f"- Interpretation: {identity.get('causal_interpretation', 'not observed')}",
            "",
            "Identity evidence is not credited as the cause of a boundary adjustment unless "
            "the adjustment event itself was persisted.",
        ]
    )
    lines.extend(
        [
            "",
            "## Boundary-side contamination",
            "",
            "| Measure | Value |",
            "|---|---:|",
        ]
    )
    for pattern, count in report.get(
        "material_final_contamination_pattern_counts", {}
    ).items():
        lines.append(f"| material pattern: {pattern} | {count} |")
    for cause, count in report.get(
        "terminal_boundary_component_causal_counts", {}
    ).items():
        lines.append(f"| terminal component cause: {cause} | {count} |")
    for component, seconds in report.get(
        "final_contamination_seconds_by_component", {}
    ).items():
        lines.append(f"| aggregate {component} | {seconds:.1f}s |")
    lines.extend(
        [
        "",
        "## Recovery and masking",
        "",
        "| Status | Count |",
        "|---|---:|",
        ]
    )
    for status, count in sorted(
        report["recovery_status_counts"].items(), key=lambda item: (-item[1], item[0])
    ):
        lines.append(f"| {status} | {count} |")
    lines.extend(
        [
        "",
        "## Failure signatures",
        "",
        "| Signature | Count | Representative runs |",
        "|---|---:|---|",
        ]
    )
    for signature, count in sorted(
        report["failure_signature_counts"].items(), key=lambda item: (-item[1], item[0])
    ):
        videos = report["affected_video_ids_by_failure_signature"][signature]
        lines.append(f"| {signature} | {count} | {', '.join(videos[:8])} |")
    lines.extend(
        [
        "",
        "## Observed contract violations",
        "",
        "```text",
        "Low-quality outcomes",
        ]
    )
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


def compare_systemic_reports(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
    """Compare two persisted systemic reports without rerunning classification."""
    before_traces = {
        str(trace.get("video", {}).get("youtube_video_id")): trace
        for trace in before.get("traces", [])
        if trace.get("video", {}).get("youtube_video_id")
    }
    after_traces = {
        str(trace.get("video", {}).get("youtube_video_id")): trace
        for trace in after.get("traces", [])
        if trace.get("video", {}).get("youtube_video_id")
    }

    def snapshot(trace: dict[str, Any]) -> dict[str, Any]:
        final = next(
            (stage for stage in trace.get("stages", []) if stage.get("key") == "final"),
            {},
        )
        measurements = final.get("measurements", {})
        failure = trace.get("earliest_observed_failure") or {}
        contracts = trace.get("outcome_contracts", {})
        paths = trace.get("contract_paths", {})
        source = trace.get("source_artifact", {})
        identity = trace.get("identity_boundary_feedback", {})
        fingerprints = trace.get("component_fingerprints")
        if (
            not isinstance(fingerprints, dict)
            or fingerprints.get("version") != COMPONENT_FINGERPRINT_VERSION
        ):
            fingerprints = _trace_component_fingerprints(trace)
        disposition_contract = contracts.get("disposition", {})
        disposition_status = disposition_contract.get("status")
        disposition_value = disposition_contract.get("value")
        contract_statuses = {
            "pass",
            "fail",
            "review_required",
            "not_evaluated",
            "informational",
        }
        if disposition_status not in contract_statuses:
            disposition_value = disposition_value or disposition_status
            expected_outcome = trace.get("ground_truth", {}).get("expected_outcome")
            if disposition_value == "review_required":
                disposition_status = "review_required"
            elif expected_outcome == "no_sermon":
                disposition_status = (
                    "fail" if disposition_value == "accepted_sermon" else "pass"
                )
            elif expected_outcome == "sermon":
                disposition_status = (
                    "pass" if disposition_value == "accepted_sermon" else "fail"
                )
            else:
                disposition_status = "not_evaluated"
        return {
            "overall_outcome": _trace_overall_status(trace),
            "earliest_observed_failure": failure.get("stage"),
            "reviewed_sermon_coverage": measurements.get("reviewed_sermon_coverage"),
            "contamination_ratio": measurements.get("contamination_ratio"),
            "outcome_dimensions": {
                **{
                    dimension: contracts.get(dimension, {}).get("status")
                    for dimension in (
                        "existence",
                        "localization",
                        "contamination",
                        "verifier",
                    )
                },
                "disposition": disposition_status,
            },
            "disposition": disposition_value,
            "terminal_failure_causes": {
                dimension: path.get("likely_causal_stage")
                for dimension, path in paths.items()
                if dimension != "stage_order"
                and isinstance(path, dict)
                and path.get("terminal_failure")
            },
            "stage_regret": {
                stage: trace.get("stage_regret", {})
                .get(stage, {})
                .get("classification")
                for stage in ("refinement", "arbitration")
            },
            "identity_boundary_feedback": {
                "event_count": int(identity.get("event_count") or 0),
                "temporal_boundary_movement_count": int(
                    identity.get("temporal_boundary_movement_count") or 0
                ),
                "causal_adjustment_count": int(
                    identity.get("causal_adjustment_count") or 0
                ),
            },
            "source_artifact_sha256": source.get("sha256"),
            "algorithm_version": source.get("algorithm_version")
            or trace.get("cohort", {}).get("algorithm_version"),
            "trace_schema_version": trace.get("schema_version"),
            "contract_version": trace.get("contract_version"),
            "component_fingerprints": fingerprints.get("components", {}),
        }

    def component_directions(
        old: dict[str, Any], new: dict[str, Any]
    ) -> tuple[list[str], list[str]]:
        improved: list[str] = []
        regressed: list[str] = []
        rank = {"fail": 0, "review_required": 1, "pass": 2}
        old_dimensions = old.get("outcome_dimensions", {})
        new_dimensions = new.get("outcome_dimensions", {})
        for dimension in sorted(set(old_dimensions) | set(new_dimensions)):
            old_status = old_dimensions.get(dimension)
            new_status = new_dimensions.get(dimension)
            if old_status not in rank or new_status not in rank or old_status == new_status:
                continue
            target = improved if rank[new_status] > rank[old_status] else regressed
            target.append(f"contract:{dimension}")
        if old.get("trace_schema_version") != new.get("trace_schema_version"):
            return improved, regressed
        for stage in ("refinement", "arbitration"):
            old_regret = old.get("stage_regret", {}).get(stage)
            new_regret = new.get("stage_regret", {}).get(stage)
            if old_regret is None or new_regret is None or old_regret == new_regret:
                continue
            old_bad = old_regret not in {None, "none", "not_evaluated"}
            new_bad = new_regret not in {None, "none", "not_evaluated"}
            if old_bad and not new_bad:
                improved.append(f"regret:{stage}")
            elif not old_bad and new_bad:
                regressed.append(f"regret:{stage}")
        return improved, regressed

    def comparable_behavior_equal(old: dict[str, Any], new: dict[str, Any]) -> bool:
        for key in (
            "overall_outcome",
            "reviewed_sermon_coverage",
            "contamination_ratio",
        ):
            if old.get(key) != new.get(key):
                return False
        old_disposition = old.get("disposition")
        new_disposition = new.get("disposition")
        if (
            old_disposition is not None
            and new_disposition is not None
            and old_disposition != new_disposition
        ):
            return False
        old_dimensions = old.get("outcome_dimensions", {})
        new_dimensions = new.get("outcome_dimensions", {})
        for dimension in set(old_dimensions) & set(new_dimensions):
            old_status = old_dimensions.get(dimension)
            new_status = new_dimensions.get(dimension)
            if old_status is not None and new_status is not None and old_status != new_status:
                return False
        return True

    def component_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
        old_values = old.get("component_fingerprints", {})
        new_values = new.get("component_fingerprints", {})
        return sorted(
            key
            for key in set(old_values) | set(new_values)
            if old_values.get(key) != new_values.get(key)
        )

    def change_reasons(
        old: dict[str, Any], new: dict[str, Any], changed_components: list[str]
    ) -> list[str]:
        reasons: list[str] = []
        if any(
            component
            in {
                "transcript",
                "candidate_discovery",
                "selected_candidate",
                "fine_refinement",
                "arbitration_final_window",
            }
            for component in changed_components
        ):
            reasons.append("boundary_behavior_changed")
        if "recording_verifier" in changed_components:
            reasons.append("verifier_changed")
        if "final_disposition" in changed_components:
            reasons.append("disposition_policy_changed")
        if "identity_feedback" in changed_components:
            reasons.append("identity_evidence_changed")
        if old.get("algorithm_version") != new.get("algorithm_version"):
            reasons.append("algorithm_changed")
        artifact_changed = old.get("source_artifact_sha256") != new.get(
            "source_artifact_sha256"
        )
        if not changed_components and artifact_changed:
            reasons.append("metadata_only")
        if (
            not changed_components
            and old.get("trace_schema_version") != new.get("trace_schema_version")
        ):
            reasons.append("diagnostic_schema_only")
        return reasons or ["diagnostic_projection_changed"]

    runs: list[dict[str, Any]] = []
    transitions = Counter()
    all_ids = sorted(set(before_traces) | set(after_traces))
    for video_id in all_ids:
        old = snapshot(before_traces[video_id]) if video_id in before_traces else None
        new = snapshot(after_traces[video_id]) if video_id in after_traces else None
        if old is None:
            change = "added"
        elif new is None:
            change = "removed"
        else:
            old_failed = old["overall_outcome"] == "fail"
            new_failed = new["overall_outcome"] == "fail"
            improved_components, regressed_components = component_directions(old, new)
            changed_components = component_changes(old, new)
            reasons = change_reasons(old, new, changed_components)
            if old_failed and not new_failed:
                change = "fixed"
            elif not old_failed and new_failed:
                change = "regressed"
            elif comparable_behavior_equal(old, new) and not changed_components:
                change = "unchanged"
            elif improved_components and regressed_components:
                change = "tradeoff"
            elif improved_components:
                change = "improved"
            elif regressed_components:
                change = "regressed"
            elif (
                old.get("disposition") != new.get("disposition")
                and changed_components == ["final_disposition"]
            ):
                change = "policy_changed"
            else:
                change = "changed"
        transitions[change] += 1
        runs.append(
            {
                "youtube_video_id": video_id,
                "change": change,
                "improved_components": (
                    improved_components if old is not None and new is not None else []
                ),
                "regressed_components": (
                    regressed_components if old is not None and new is not None else []
                ),
                "changed_artifact_components": (
                    changed_components if old is not None and new is not None else []
                ),
                "change_reasons": (
                    reasons if old is not None and new is not None else [change]
                ),
                "artifact_changed": bool(
                    old
                    and new
                    and old.get("source_artifact_sha256")
                    != new.get("source_artifact_sha256")
                ),
                "algorithm_changed": bool(
                    old
                    and new
                    and old.get("algorithm_version") != new.get("algorithm_version")
                ),
                "before": old,
                "after": new,
            }
        )

    def signature_members(report: dict[str, Any]) -> dict[str, set[str]]:
        return {
            str(signature): {str(video_id) for video_id in video_ids}
            for signature, video_ids in report.get(
                "affected_video_ids_by_failure_signature", {}
            ).items()
        }

    old_signatures = signature_members(before)
    new_signatures = signature_members(after)
    signature_changes = {}
    for signature in sorted(set(old_signatures) | set(new_signatures)):
        old_ids = old_signatures.get(signature, set())
        new_ids = new_signatures.get(signature, set())
        signature_changes[signature] = {
            "before_count": len(old_ids),
            "after_count": len(new_ids),
            "resolved_video_ids": sorted(old_ids - new_ids),
            "new_video_ids": sorted(new_ids - old_ids),
        }
    reason_counts = Counter(
        reason for run in runs for reason in run.get("change_reasons", [])
    )
    artifact_component_counts = Counter(
        component
        for run in runs
        for component in run.get("changed_artifact_components", [])
    )
    return {
        "schema_version": 3,
        "report_kind": "sermon_isolation_diagnostic_comparison",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "before": {
            "generated_at": before.get("generated_at"),
            "trace_count": before.get("trace_count", len(before_traces)),
            "schema_version": before.get("schema_version"),
        },
        "after": {
            "generated_at": after.get("generated_at"),
            "trace_count": after.get("trace_count", len(after_traces)),
            "schema_version": after.get("schema_version"),
        },
        "diagnostic_schema_changed": before.get("schema_version") != after.get("schema_version"),
        "comparison_warning": (
            "Diagnostic schemas differ; changed results may reflect contract interpretation "
            "as well as artifact changes. Regenerate both reports with the same diagnostic "
            "version for a controlled pipeline comparison."
            if before.get("schema_version") != after.get("schema_version")
            else None
        ),
        "change_counts": dict(sorted(transitions.items())),
        "change_reason_counts": dict(sorted(reason_counts.items())),
        "changed_artifact_component_counts": dict(
            sorted(artifact_component_counts.items())
        ),
        "failure_signature_changes": signature_changes,
        "runs": runs,
    }


def build_comparison_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# Systemic Diagnostic Comparison",
        "",
        f"- Diagnostic schema changed: {comparison.get('diagnostic_schema_changed', False)}",
        f"- Warning: {comparison.get('comparison_warning') or 'none'}",
        "",
        "## Run changes",
        "",
        "| Change | Count |",
        "|---|---:|",
    ]
    for change, count in sorted(
        comparison.get("change_counts", {}).items(), key=lambda item: (-item[1], item[0])
    ):
        lines.append(f"| {change} | {count} |")
    lines.extend(
        [
            "",
            "## Change provenance",
            "",
            "| Reason | Count |",
            "|---|---:|",
        ]
    )
    for reason, count in comparison.get("change_reason_counts", {}).items():
        lines.append(f"| {reason} | {count} |")
    for component, count in comparison.get(
        "changed_artifact_component_counts", {}
    ).items():
        lines.append(f"| component: {component} | {count} |")
    lines.extend(
        [
            "",
            "## Failure signatures",
            "",
            "| Signature | Before | After | Resolved | New |",
            "|---|---:|---:|---|---|",
        ]
    )
    for signature, change in comparison.get("failure_signature_changes", {}).items():
        lines.append(
            f"| {signature} | {change['before_count']} | {change['after_count']} | "
            f"{', '.join(change['resolved_video_ids']) or '—'} | "
            f"{', '.join(change['new_video_ids']) or '—'} |"
        )
    lines.extend(
        [
            "",
            "## Changed runs",
            "",
            "| Video | Change | Before | After | Components | Provenance |",
            "|---|---|---|---|---|---|",
        ]
    )
    for run in comparison.get("runs", []):
        if run.get("change") == "unchanged":
            continue
        before = run.get("before") or {}
        after = run.get("after") or {}
        components = [
            *(f"+{item}" for item in run.get("improved_components", [])),
            *(f"-{item}" for item in run.get("regressed_components", [])),
        ]
        provenance = ", ".join(run.get("change_reasons", []))
        lines.append(
            f"| {run['youtube_video_id']} | {run['change']} | "
            f"{before.get('overall_outcome', '—')} / "
            f"{before.get('earliest_observed_failure') or 'none'} | "
            f"{after.get('overall_outcome', '—')} / "
            f"{after.get('earliest_observed_failure') or 'none'} | "
            f"{', '.join(components) or '—'} | {provenance or 'diagnostic/policy'} |"
        )
    lines.append("")
    return "\n".join(lines)
