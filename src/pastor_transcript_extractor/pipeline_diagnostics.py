from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from pastor_transcript_extractor.fixture_validation import ValidatedFixture


TRACE_SCHEMA_VERSION = 3
CONTRACT_VERSION = "sermon-isolation-contracts-v3"
REVIEWED_COVERAGE_THRESHOLD = 0.90
MAX_CONTAMINATION_RATIO = 0.10
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
            "contamination_attribution": (
                "first selected-path stage above the contamination contract, later recovery, "
                "and final boundary-error direction"
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
                "composition of existence, localization, contamination, disposition, and "
                "manual-override state without hiding the component contracts"
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
    fine_coverage: object,
) -> dict[str, Any]:
    if expected is None:
        return {"status": "not_evaluated", "reason": "positive_ground_truth_unavailable"}
    expected_duration = _duration(expected)

    def coverage(candidate: dict[str, Any]) -> float:
        ranges = _candidate_envelope_ranges(candidate)
        return (
            _intersection_duration(ranges, expected) / expected_duration
            if expected_duration
            else 0.0
        )

    rows = [
        {
            "rank": candidate.get("rank"),
            "source": candidate.get("source"),
            "reviewed_sermon_coverage": round(coverage(candidate), 6),
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
    selected_coverage = coverage(selected) if selected is not None else 0.0
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
    return {
        "status": "evaluated",
        "classification": classification,
        "candidate_union_coverage": round(union_coverage, 6),
        "best_candidate_coverage": round(best_coverage, 6),
        "best_candidate_rank": best.get("rank") if best else None,
        "selected_candidate_coverage": round(selected_coverage, 6),
        "selected_candidate_regret": round(max(0.0, best_coverage - selected_coverage), 6),
        "candidates": rows,
    }


def _contamination_attribution(
    stages: list[dict[str, Any]], fixture: ValidatedFixture | None
) -> dict[str, Any]:
    if fixture is None or fixture.expected_outcome != "sermon":
        return {"status": "not_evaluated", "reason": "positive_ground_truth_unavailable"}
    tracked = {"selected", "joined", "fine", "arbitration", "final"}
    series: list[dict[str, Any]] = []
    previous: float | None = None
    for stage in stages:
        if stage["key"] not in tracked:
            continue
        value = stage["measurements"].get("contamination_ratio")
        if not isinstance(value, (int, float)):
            continue
        series.append(
            {
                "stage": stage["key"],
                "contamination_ratio": value,
                "delta": round(value - previous, 6) if previous is not None else None,
            }
        )
        previous = value
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
    return {
        "status": "evaluated",
        "earliest_breach_stage": earliest,
        "recovery_stage": recovery,
        "final_boundary_error_patterns": patterns or ["aligned"],
        "stage_deltas": series,
    }


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
        "candidates": ("candidate_discovery", "candidate_envelope_omission"),
        "selected": ("candidate_ranking", "coverage_lost_during_candidate_selection"),
        "joined": ("join_logic", "continuation_not_recovered"),
        "fine": ("fine_refinement", "coverage_lost_during_fine_refinement"),
        "arbitration": ("final_arbitration", "arbitration_selected_inferior_window"),
        "verifier": ("recording_verifier", "recording_verifier_wrong_outcome"),
        "final": ("final_disposition", "final_disposition_contract_failure"),
    }
    cause_stage, code = mapping.get(stage, (stage, "unclassified_contract_failure"))
    current = by_key[stage]
    evidence = [
        f"contract={current['contract'].get('code')}",
        f"coverage={current['measurements'].get('reviewed_sermon_coverage')}",
        f"seconds_removed={current['transition'].get('seconds_removed')}",
    ]
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
            f"The earliest measured coverage contract fails at {stage}; "
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
        rejected = final_disposition == "rejected_no_sermon"
        existence = {
            "status": "fail" if rejected else "pass",
            "code": "positive_rejected" if rejected else "positive_sermon_retained",
        }
    return {
        "existence": existence,
        "localization": final["quality_contracts"]["localization"],
        "contamination": final["quality_contracts"]["contamination"],
        "disposition": {
            "status": final_disposition or "unknown",
            "automatically_accepted": final_disposition == "accepted_sermon",
        },
        "manual_override_applied": manual_override,
    }


def _overall_outcome(outcome_contracts: dict[str, Any]) -> dict[str, Any]:
    dimensions = ("existence", "localization", "contamination")
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
    disposition = outcome_contracts.get("disposition", {}).get("status")
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
    recovery_status = _recovery_status(observed, stages, manual_override)
    outcome_contracts = _outcome_contracts(
        stages=stages,
        fixture=fixture,
        final_disposition=(
            str(disposition.get("status")) if disposition.get("status") else None
        ),
        manual_override=manual_override,
    )
    overall_outcome = _overall_outcome(outcome_contracts)
    fine_stage = next(stage for stage in stages if stage["key"] == "fine")
    cohort = {
        **_fixture_metadata(fixture),
        "outcome_mode": "manual_override" if manual_override else "automatic",
        "transcript_source": proposed.get("transcript_source") or "unknown",
        "algorithm_version": search.get("algorithm_version") or "unknown",
        "verifier_prompt_version": verification.get("prompt_version") or "unknown",
        "verifier_policy_version": verification.get("policy_version") or "unknown",
        "verifier_model": verification.get("model") or "unknown",
    }
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
        "cohort": cohort,
        "overall_outcome": overall_outcome,
        "candidate_regret": _candidate_regret(
            candidates,
            selected,
            expected,
            fine_stage["measurements"].get("reviewed_sermon_coverage"),
        ),
        "contamination_attribution": _contamination_attribution(stages, fixture),
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
    for dimension in ("existence", "localization", "contamination"):
        contract = trace.get("outcome_contracts", {}).get(dimension, {})
        observed_value = contract.get("observed")
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
            "",
            "## Contamination attribution",
            "",
            f"- Earliest breach: {attribution.get('earliest_breach_stage') or 'none'}",
            f"- Recovery stage: {attribution.get('recovery_stage') or 'none'}",
            "- Final boundary pattern: "
            + ", ".join(attribution.get("final_boundary_error_patterns", []) or ["not evaluated"]),
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
            dispositions[
                str(contracts.get("disposition", {}).get("status") or "unknown")
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
    localization = Counter()
    contamination = Counter()
    existence = Counter()
    overall = Counter()
    regret = Counter()
    contamination_breach = Counter()
    boundary_patterns = Counter()
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
        regret[
            str(trace.get("candidate_regret", {}).get("classification") or "not_evaluated")
        ] += 1
        attribution = trace.get("contamination_attribution", {})
        contamination_breach[str(attribution.get("earliest_breach_stage") or "none")] += 1
        for pattern in attribution.get("final_boundary_error_patterns", []) or []:
            boundary_patterns[str(pattern)] += 1
        contracts = trace.get("outcome_contracts", {})
        disposition = contracts.get("disposition", {}).get("status") or "unknown"
        dispositions[str(disposition)] += 1
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
            if disposition == "review_required":
                run_signatures.append("positive_requires_review")
        elif expected_outcome == "no_sermon":
            if failed("verifier"):
                run_signatures.append("recording_verifier_false_positive")
            elif contracts.get("existence", {}).get("status") == "fail":
                run_signatures.append("negative_false_acceptance_without_verifier_failure")
        for signature in run_signatures:
            signatures.setdefault(signature, []).append(video_id)
    return {
        "schema_version": 3,
        "report_kind": "sermon_isolation_systemic_diagnostics",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trace_count": len(traces),
        "missing_count": len(missing or []),
        "observed_failure_counts": dict(sorted(observed.items())),
        "root_cause_hypothesis_counts": dict(sorted(causes.items())),
        "fixture_outcome_counts": dict(sorted(fixture_outcomes.items())),
        "recovery_status_counts": dict(sorted(recovery.items())),
        "causal_path_status_counts": dict(sorted(recovery.items())),
        "overall_outcome_counts": dict(sorted(overall.items())),
        "final_disposition_counts": dict(sorted(dispositions.items())),
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
        "contamination_earliest_breach_counts": dict(sorted(contamination_breach.items())),
        "final_boundary_error_pattern_counts": dict(sorted(boundary_patterns.items())),
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


def build_systemic_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Systemic Pipeline Diagnostics",
        "",
        f"- Traces: {report['trace_count']}",
        f"- Missing artifacts: {report['missing_count']}",
        f"- Manual overrides: {report['manual_override_count']}",
        f"- Unknown evaluation partitions: {report.get('unknown_evaluation_partition_count', 0)}",
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
        return {
            "overall_outcome": _trace_overall_status(trace),
            "earliest_observed_failure": failure.get("stage"),
            "reviewed_sermon_coverage": measurements.get("reviewed_sermon_coverage"),
            "contamination_ratio": measurements.get("contamination_ratio"),
        }

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
            if old_failed and not new_failed:
                change = "fixed"
            elif not old_failed and new_failed:
                change = "regressed"
            elif old == new:
                change = "unchanged"
            else:
                change = "changed"
        transitions[change] += 1
        runs.append({"youtube_video_id": video_id, "change": change, "before": old, "after": new})

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
    return {
        "schema_version": 1,
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
            "| Video | Change | Before | After |",
            "|---|---|---|---|",
        ]
    )
    for run in comparison.get("runs", []):
        if run.get("change") == "unchanged":
            continue
        before = run.get("before") or {}
        after = run.get("after") or {}
        lines.append(
            f"| {run['youtube_video_id']} | {run['change']} | "
            f"{before.get('overall_outcome', '—')} / "
            f"{before.get('earliest_observed_failure') or 'none'} | "
            f"{after.get('overall_outcome', '—')} / "
            f"{after.get('earliest_observed_failure') or 'none'} |"
        )
    lines.append("")
    return "\n".join(lines)
