"""Provider-free sensitivity packet for the frozen pastor salvation cohorts."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from pastor_transcript_extractor.analysis_artifact_cache import write_json_markdown
from pastor_transcript_extractor.sermon_salvation_convergence import (
    _hash, _mean, build_convergence,
)


POLICY_VERSION = "salvation-pastor-uncertainty-v1"
DEFAULT_OUTPUT = Path("evaluation/sermon-topics/salvation-pastor-uncertainty-v1.json")


def build_uncertainty(proposal: Mapping[str, Any], sermons_by_profile: Mapping[int, list[Mapping[str, Any]]]) -> dict[str, Any]:
    """Preserve primary rates and existing strata; add auditable sensitivity diagnostics."""
    convergence = build_convergence(proposal, sermons_by_profile)
    pastors = []
    for pastor in convergence["pastors"]:
        sermons = sorted((item for item in sermons_by_profile[pastor["profile_id"]]
                          if item.get("measurement_status") != "unavailable_missing_cached_leaf_artifact"),
                         key=lambda item: int(item["video_id"]))
        relationships = {}
        for leaf, summary in pastor["relationships"].items():
            values = {int(item["video_id"]): float(item["relationships"][leaf]["routed_block_fraction"])
                      for item in sermons}
            positive_ids = [int(item["video_id"]) for item in sermons if item["relationships"][leaf]["observed"]]
            routed_ids = [int(item["video_id"]) for item in sermons if int(item["routed_block_count"]) > 0]
            omissions = [{"omitted_video_id": video_id,
                          "equal_sermon_mean": _mean([value for other_id, value in values.items() if other_id != video_id])}
                         for video_id in values]
            checkpoints = []
            previous = None
            for point in summary["checkpoints"]:
                movement = dict(point)
                if point["status"] == "available":
                    mean = point["primary_equal_sermon_mean"]
                    movement["previous_available_n"] = previous[0] if previous else None
                    movement["signed_delta_from_previous"] = round(mean - previous[1], 6) if previous else None
                    previous = (point["n"], mean)
                checkpoints.append(movement)
            conditional = _mean([values[video_id] for video_id in routed_ids]) if routed_ids else None
            relationships[leaf] = {
                **summary, "checkpoints": checkpoints,
                "positive_sermon_ids": positive_ids,
                "leave_one_sermon_out": {"minimum": min(item["equal_sermon_mean"] for item in omissions),
                                          "maximum": max(item["equal_sermon_mean"] for item in omissions),
                                          "omissions": omissions},
                "denominator_sensitivity": {
                    "primary": "equal_sermon_including_zero_routed",
                    "primary_sermons": len(sermons),
                    "primary_mean": summary["full_available_equal_sermon_mean"],
                    "conditional_routed_sermons": len(routed_ids),
                    "conditional_routed_mean": conditional,
                    "status": "available" if routed_ids else "unavailable_no_routed_sermons",
                    "signed_delta_from_primary": round(conditional - summary["full_available_equal_sermon_mean"], 6)
                    if conditional is not None else None,
                },
            }
        pastors.append({**pastor, "relationships": relationships,
                        "sermon_measurements": sermons})
    identity = {"schema_version": 1, "policy_version": POLICY_VERSION,
                "proposal_fingerprint": proposal["input_fingerprint"],
                "convergence_fingerprint": convergence["input_fingerprint"],
                "observation_policy_version": convergence["observation_policy_version"],
                "question_pack_version": convergence["question_pack_version"],
                "measured_relationships": convergence["measured_relationships"],
                "unresolved_relationships": convergence["unresolved_relationships"],
                "pastors": pastors}
    return {**identity, "input_fingerprint": _hash(identity), "provider_requests": 0,
            "status": "diagnostic_pending_bounded_review", "pastor_level_sufficiency_granted": False}


def render_uncertainty(report: Mapping[str, Any]) -> str:
    lines = ["# Pastor salvation uncertainty packet", "",
             f"Fingerprint: `{report['input_fingerprint']}`",
             f"Frozen cohort: `{report['proposal_fingerprint']}`", "Provider requests: 0", "",
             "Primary rates retain equal sermon weights, including observed-zero sermons with no routed blocks.",
             "Conditional rates exclude only zero-routed sermons. Missing evidence remains unmeasured.",
             "Leave-one-out ranges describe sensitivity to the measured sample; they are not confidence intervals.",
             "Zero detections mean insufficient positive evidence, not theological absence.",
             "Unknown period/series provenance remains visible. No cutoff is fitted, no questions are retuned,",
             "and this packet grants no pastor-level sample-size sufficiency.", ""]
    for pastor in report["pastors"]:
        lines += [f"## {pastor['display_name']} (profile {pastor['profile_id']})", "",
                  f"Measured/selected: {pastor['sermon_count']}/{pastor['selected_sermon_count']}; "
                  f"zero-route IDs: {pastor['zero_routed_sermon_ids']}; "
                  f"unmeasured IDs: {[item['video_id'] for item in pastor['unavailable_sermons']]}; "
                  f"unknown period/series counts: {pastor['missing_period_provenance']}/{pastor['missing_series_provenance']}.", "",
                  "| Leaf | Positive sermons | Primary mean | Leave-one-out range | Routed-only mean (N) |",
                  "| --- | ---: | ---: | ---: | ---: |"]
        for leaf, summary in pastor["relationships"].items():
            loo = summary["leave_one_sermon_out"]
            denominator = summary["denominator_sensitivity"]
            conditional = denominator["conditional_routed_mean"]
            value = f"{conditional:.3f}" if conditional is not None else "unavailable"
            lines.append(f"| `{leaf}` | {summary['full_sermons_with_observation']}/{pastor['sermon_count']} | "
                         f"{summary['full_available_equal_sermon_mean']:.3f} | {loo['minimum']:.3f}–{loo['maximum']:.3f} | "
                         f"{value} ({denominator['conditional_routed_sermons']}) |")
        for leaf, summary in pastor["relationships"].items():
            lines += ["", f"### {leaf}", "", f"Evidence: {summary['evidence_status']}; positive video IDs: {summary['positive_sermon_ids']}.", "",
                      "| Checkpoint N | Primary mean | Change from previous checkpoint |", "| ---: | ---: | ---: |"]
            for point in summary["checkpoints"]:
                if point["status"] != "available":
                    lines.append(f"| {point['n']} | unavailable | — |")
                else:
                    delta = point["signed_delta_from_previous"]
                    value = f"{delta:+.3f}" if delta is not None else "—"
                    lines.append(f"| {point['n']} | {point['primary_equal_sermon_mean']:.3f} | {value} |")
            lines += ["", "| Period | Sermons | Mean |", "| --- | ---: | ---: |"]
            for group in summary["period_sensitivity"]:
                lines.append(f"| {group['period_key']} | {group['sermons']} | {group['equal_sermon_mean']:.3f} |")
            lines += ["", "| Replicated series | Inside N / mean | Outside N / mean | Absolute difference |",
                      "| --- | ---: | ---: | ---: |"]
            for group in summary["series_sensitivity"]:
                lines.append(f"| {group['series_key']} | {group['within_sermons']} / {group['within_mean']:.3f} | "
                             f"{group['outside_sermons']} / {group['outside_mean']:.3f} | {group['absolute_delta']:.3f} |")
            if not summary["series_sensitivity"]:
                lines += ["", "No replicated-series comparison is available."]
        lines += ["", "Exact omission results, per-sermon evidence, source hashes, and order sensitivity are in the JSON.", ""]
    lines += ["## Prepared review", "",
              "Review the named leaves with few positive sermons, large checkpoint movements,",
              "wide omission ranges, or material denominator/period/series differences.",
              "Proposed decision: retain these diagnostics and the primary denominator; defer a universal",
              "sample-size or uncertainty cutoff until this bounded packet is reviewed.", ""]
    return "\n".join(lines)


def write_uncertainty(path: Path, report: Mapping[str, Any]) -> tuple[Path, Path, bool]:
    return write_json_markdown(path, report, render_uncertainty(report))
