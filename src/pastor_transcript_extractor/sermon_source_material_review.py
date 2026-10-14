"""Bounded source/material development using shared independent leaf infrastructure."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from pastor_transcript_extractor.sermon_leaf_packs import SOURCE_MATERIAL, listener_directive_route
from pastor_transcript_extractor.sermon_listener_directive_review import prepare_review, fingerprint

DEFAULT_SOURCE_REVIEW_OUTPUT = Path("evaluation/sermon-topics/source-material-review-v1.json")
SOURCE_PROBE_PATH = Path(__file__).parent / "data" / "source-material-probes-v1.json"
SOURCE_ROUTE_VERSION = "source-material-route-eligible-v1-candidate"
# Inspection cues do not establish source presence or decide coverage routing.
SOURCE_CUES = {
    "biblical_story_cue": re.compile(r"\b(Jesus|Peter|Moses|Abraham|disciples|David)\b", re.I),
    "testimony_cue": re.compile(r"\b(I|my|testimony|testified|experience)\b", re.I),
    "attribution_cue": re.compile(r"\b(writes|wrote|quoted|quote|history|White|Manual|confession)\b", re.I),
}


def source_material_route(block: Mapping[str, Any]) -> dict[str, Any]:
    return {**listener_directive_route(block), "policy_version": SOURCE_ROUTE_VERSION,
            "signal": "final_content_projection_eligibility",
            "topic_signal_role": "sampling_diagnostic_only",
            "status": "candidate_pending_bounded_review"}


def select_source_cases(blocks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    remaining = sorted((b for b in blocks if source_material_route(b)["route"]),
                       key=lambda b: int(b["block_id"]))
    chosen = []
    for stratum in (*SOURCE_CUES, "no_source_cue"):
        candidates = [b for b in remaining if
                      (bool(SOURCE_CUES[stratum].search(b["target_text"])) if stratum in SOURCE_CUES
                       else not any(c.search(b["target_text"]) for c in SOURCE_CUES.values()))]
        if not candidates:
            continue
        item = candidates[len(candidates) // 2]
        chosen.append({**item, "review_stratum": stratum,
                       "expected_positive_leaves": None,
                       "proposed_label": "inspect_target_material_and_attribution"})
        remaining.remove(item)
    # Keep bounded coverage when one or more cue strata are absent.
    for item in remaining:
        if len(chosen) == 4:
            break
        chosen.append({**item, "review_stratum": "coverage_fallback",
                       "expected_positive_leaves": None,
                       "proposed_label": "inspect_target_material_and_attribution"})
    return chosen


def prepare_source_review(database, *, model: str, probe_cache: Path) -> dict[str, Any]:
    packet = prepare_review(database, model=model, probe_cache=probe_cache,
                            pack=SOURCE_MATERIAL, probe_path=SOURCE_PROBE_PATH,
                            selector=select_source_cases, router=source_material_route)
    packet.update({
        "review_policy": "source-material-bounded-review-v1",
        "route_policy_version": SOURCE_ROUTE_VERSION,
        "proposed_decision": "Review six independent source/form questions, target-only attribution, and eligibility-only routing separately. Recommend readiness only after semantic interpretation; preserve overlaps and defer production thresholds.",
        "routing_proposal": "Route all current final projection-eligible blocks. No broad-topic cutoff or cue gates source measurement.",
        "sampling_limit": "At most twelve natural blocks from three reviewed sermons plus 23 authored probes; not a corpus recall or workload estimate.",
        "broader_collection_activated": False,
        "stratum_counts": {name: sum(c["review_stratum"] == name for c in packet["cases"])
                           for name in (*SOURCE_CUES, "no_source_cue", "coverage_fallback")},
    })
    packet.pop("input_fingerprint")
    packet["input_fingerprint"] = fingerprint(packet)
    return packet


SOURCE_COMPLETED_FINGERPRINT = "0cec4f832c1b0488a2d53406887423484d1d23ae6785ab27bee8fca5383c285e"
SOURCE_COMPLETION_OUTPUT = Path("evaluation/sermon-topics/source-material-stage-gate-v1.json")


def build_source_completion(path: Path = DEFAULT_SOURCE_REVIEW_OUTPUT) -> dict[str, Any]:
    """Record accepted V1 interpretation from frozen evidence without inference."""
    import json

    review = json.loads(path.read_text())
    identity = {key: value for key, value in review.items() if key != "input_fingerprint"}
    if (review.get("input_fingerprint") != SOURCE_COMPLETED_FINGERPRINT
            or fingerprint(identity) != SOURCE_COMPLETED_FINGERPRINT
            or review.get("question_pack_version") != SOURCE_MATERIAL.version
            or review.get("question_pack_digest") != SOURCE_MATERIAL.digest()
            or review.get("status") != "evaluated_pending_human_review"):
        raise ValueError("Source completion requires the fingerprint-valid reviewed V1 evidence and unchanged questions")
    cases = review["cases"]
    authored = [c for c in cases if c["video_id"] == "contract-probes"]
    natural = [c for c in cases if c["video_id"] != "contract-probes"]
    if len(authored) != 23 or len(natural) != 12 or not all(c["probe_matches_proposal"] is True for c in authored):
        raise ValueError("Source completion requires all 23 accepted authored probes and twelve natural cases")
    for case in cases:
        SOURCE_MATERIAL.validate(case["leaf_answer"]["probabilities"])
    indexed = {(c["video_id"], c["block_id"]): c for c in natural}
    observations = []
    for block_id, interpretation in (
        (36, "Historical example=.63 is a retained below-display boundary observation on colonization/slavery material as presented. The surrounding Mendoza dramatization is not independently verified historical evidence."),
        (37, "Quotation=.80 and reported testimony=.76 describe presented dialogue and spiritual experience. Retain these as source/form observations, not verified lived testimony; the film/story ambiguity remains explicit and is not ground truth for factual accuracy."),
        (57, "Personal testimony=.70, reported testimony=.88, and quotation=.88 legitimately coexist: the preacher recounts his interaction and the man's spiritual experience and words."),
    ):
        case = indexed[4430, block_id]
        observations.append({"video_id": 4430, "block_id": block_id,
                             "probabilities": dict(case["leaf_answer"]["probabilities"]),
                             "interpretation": interpretation})
    report = {
        "schema_version": 1, "decision_version": "source-material-question-readiness-v1",
        "reviewed_by": "Brian Cummings", "reviewed_on": "2026-10-13",
        "source_review_fingerprint": SOURCE_COMPLETED_FINGERPRINT,
        "question_pack_version": SOURCE_MATERIAL.version,
        "question_pack_digest": SOURCE_MATERIAL.digest(),
        "question_set_readiness": "ready_for_broader_analysis",
        "stage_gate": "PASS", "approved_leaves": list(SOURCE_MATERIAL.definitions),
        "authored_probe_count": 23, "authored_probe_matches": 23,
        "natural_case_count": 12, "natural_observations": observations,
        "target_only_evidence": "pass_bounded_review",
        "routing": {"policy_version": SOURCE_ROUTE_VERSION,
                    "decision": "accepted_eligibility_only",
                    "requires": "strict_current_final_projection_eligibility",
                    "topic_signal_role": "sampling_diagnostic_only",
                    "excluded_control_count": len(review["excluded_content_controls"]),
                    "current_eligibility_must_be_reassessed": True},
        "review_display_threshold": review["review_display_threshold"],
        "collection_threshold_status": "not_established_by_display_cutoff",
        "broader_collection_activated": False, "provider_requests": 0,
        "policy_effect": "question_readiness_and_routing_acceptance_only",
        "interpretation": "Close source/material V1 validation and freeze all six questions. No V2, display-cutoff tuning, overlap suppression, or larger validation cohort is required. Source/material measures material used in developing the sermon, not endorsement, factual accuracy, theological agreement, or denominational identity. Preserve all raw probabilities and provenance, including .63 boundary and film/story ambiguity observations. Historical V1 review remains unchanged.",
        "next_step": "The four planned enrichment sets have completed question validation. Define a concrete downstream use and separate collection/projection contract before broader collection; do not invent another leaf taxonomy automatically.",
        "limitations": "Selected natural blocks and authored probes are bounded semantic evidence, not corpus recall, cost estimates, factual verification, or pastor-level conclusions.",
    }
    report["input_fingerprint"] = fingerprint(report)
    return report


def write_source_completion(path: Path, report: Mapping[str, Any]):
    from pastor_transcript_extractor.analysis_artifact_cache import write_json_markdown

    lines = ["# Source/material V1 validation complete", "",
             "Question-set readiness: **PASS — ready for broader analysis**.", "",
             str(report["interpretation"]), "",
             "All 23 authored probes match their proposals; twelve natural cases were reviewed.", "",
             "Eligibility-only routing is accepted. Reassess strict current final projection eligibility at collection time; topic signals only support sampling/diagnostics.", "",
             "## Retained natural observations", ""]
    for observation in report["natural_observations"]:
        lines.extend([f"- {observation['video_id']}:{observation['block_id']}: {observation['interpretation']}"])
    lines.extend(["", "The .70 cutoff remains display-only. Broader collection is inactive. Provider requests: 0.", "",
                  f"Frozen review fingerprint: `{report['source_review_fingerprint']}`.", "",
                  f"Frozen question digest: `{report['question_pack_digest']}`.", "",
                  str(report["limitations"]), "", str(report["next_step"]), ""])
    return write_json_markdown(path, report, "\n".join(lines))
