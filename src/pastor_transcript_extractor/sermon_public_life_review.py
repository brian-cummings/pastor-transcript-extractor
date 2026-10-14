"""First bounded public-life treatment pack, reusing independent leaf infrastructure."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from pastor_transcript_extractor.sermon_leaf_packs import PUBLIC_LIFE_TREATMENT, listener_directive_route
from pastor_transcript_extractor.sermon_listener_directive_review import prepare_review, fingerprint
from pastor_transcript_extractor.sermon_topics import validated_topic_scores, topic_supporting_or_above_probability

DEFAULT_PUBLIC_REVIEW_OUTPUT = Path("evaluation/sermon-topics/public-life-treatment-review-v2.json")
PUBLIC_PROBE_PATH = Path(__file__).parent / "data" / "public-life-treatment-probes-v1.json"
PUBLIC_ROUTE_VERSION = "public-life-route-supporting-mass-v1-candidate"
PUBLIC_ROUTE_THRESHOLD = 0.55


def public_life_support_route_v1(block: Mapping[str, Any]) -> dict[str, Any]:
    eligible = listener_directive_route(block)["eligible"]
    support = topic_supporting_or_above_probability(validated_topic_scores(block)["society_public_life"])
    reasons = [] if eligible else ["projection_ineligible"]
    if support < PUBLIC_ROUTE_THRESHOLD:
        reasons.append("below_supporting_mass_threshold")
    return {"policy_version": PUBLIC_ROUTE_VERSION, "eligible": eligible,
            "supporting_or_above_probability": support, "threshold": PUBLIC_ROUTE_THRESHOLD,
            "route": eligible and support >= PUBLIC_ROUTE_THRESHOLD,
            "exclusion_reasons": reasons, "status": "candidate_pending_bounded_review"}


PUBLIC_COVERAGE_ROUTE_VERSION = "public-life-route-eligible-v2-candidate"


def public_life_route(block: Mapping[str, Any]) -> dict[str, Any]:
    """Coverage proposal: content eligibility gates treatment, topic scores do not."""
    eligibility = block.get("projection_eligibility")
    eligible = isinstance(eligibility, Mapping) and eligibility.get("eligible") is True
    return {"policy_version": PUBLIC_COVERAGE_ROUTE_VERSION,
            "eligible": eligible, "route": eligible,
            "signal": "final_content_projection_eligibility",
            "exclusion_reasons": [] if eligible else ["projection_ineligible"],
            "topic_signal_role": "sampling_diagnostic_only",
            "status": "proposed_pending_routing_review"}


def select_public_cases(blocks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    eligible = sorted((b for b in blocks if listener_directive_route(b)["route"]),
                      key=lambda b: (float(b["public_life_support"]), int(b["block_id"])))
    chosen = []
    for stratum in ("strong_public", "route_boundary", "below_route_shadow", "absent_public_control"):
        remaining = [b for b in eligible if b["block_id"] not in {c["block_id"] for c in chosen}]
        if stratum in ("strong_public", "route_boundary"):
            remaining = [b for b in remaining if b["public_life_support"] >= PUBLIC_ROUTE_THRESHOLD]
        elif stratum == "below_route_shadow":
            remaining = [b for b in remaining if 0 < b["public_life_support"] < PUBLIC_ROUTE_THRESHOLD]
        else:
            remaining = [b for b in remaining if b["public_life_support"] == 0]
        if not remaining:
            continue
        item = remaining[-1] if stratum in ("strong_public", "below_route_shadow") else remaining[0]
        chosen.append({**item, "review_stratum": stratum,
                       "evaluation_scope": "prior_supporting_mass_route" if item["public_life_support"] >= PUBLIC_ROUTE_THRESHOLD else "prior_below_route_control",
                       "expected_positive_leaves": None,
                       "proposed_label": "inspect_preacher_attribution_and_treatment_before_acceptance"})
    return chosen


def prepare_public_review(database, *, model: str, probe_cache: Path) -> dict[str, Any]:
    packet = prepare_review(database, model=model, probe_cache=probe_cache,
                            pack=PUBLIC_LIFE_TREATMENT, probe_path=PUBLIC_PROBE_PATH,
                            selector=select_public_cases, router=public_life_support_route_v1)
    packet.update({
        "review_policy": "public-life-treatment-bounded-review-v1",
        "proposed_decision": "Review eight independent treatment questions and supporting-mass routing with shadow controls before granting question readiness; retain raw probabilities and defer collection thresholds.",
        "routing_proposal": "Candidate: final projection eligibility plus society_public_life Supporting-or-above mass >= .55. Eligible below-route blocks are bounded diagnostic controls, not production-routed evidence.",
        "sampling_limit": "At most twelve natural blocks from the same three reviewed sermons plus authored probes; absent strata remain visible. No corpus recall or pastor-level stance claim.",
        "route_policy_version": PUBLIC_ROUTE_VERSION,
        "stratum_counts": {stratum: sum(c["review_stratum"] == stratum for c in packet["cases"])
                           for stratum in ("strong_public", "route_boundary", "below_route_shadow", "absent_public_control")},
    })
    packet.pop("input_fingerprint")
    packet["input_fingerprint"] = fingerprint(packet)
    return packet


PUBLIC_BASELINE_INPUT = Path("evaluation/sermon-topics/public-life-treatment-review-v1.json")
PUBLIC_BASELINE_FINGERPRINT = "4134e90dd540f5f8bb0d263091ee44605b1dee37944633c472dc1ef15d714b77"
PUBLIC_V2_OUTPUT = DEFAULT_PUBLIC_REVIEW_OUTPUT


def prepare_public_refinement(database, *, model: str, probe_cache: Path) -> dict[str, Any]:
    import json
    from pastor_transcript_extractor.sermon_leaf_packs import PUBLIC_LIFE_TREATMENT_V1, PUBLIC_LIFE_REFINEMENT
    from pastor_transcript_extractor.sermon_listener_directive_review import attach_leaf_refinement

    packet = prepare_public_review(database, model=model, probe_cache=probe_cache)
    baseline = json.loads(PUBLIC_BASELINE_INPUT.read_text())
    packet = attach_leaf_refinement(packet, baseline, baseline_pack=PUBLIC_LIFE_TREATMENT_V1,
        pack=PUBLIC_LIFE_TREATMENT, refinement_pack=PUBLIC_LIFE_REFINEMENT,
        expected_fingerprint=PUBLIC_BASELINE_FINGERPRINT)
    # Interpretation changes do not change source texts, prompts, or answer identities.
    corrected = {14: ["descriptive", "illustrative", "theological", "moral"],
                 16: ["theological", "critical", "moral"]}
    for case in packet["cases"]:
        if case["video_id"] == "contract-probes" and case["block_id"] in corrected:
            case["prior_expected_positive_leaves"] = list(case["expected_positive_leaves"])
            case["expected_positive_leaves"] = corrected[case["block_id"]]
            case["expectation_interpretation"] = "Explicit normative rejection is also moral evaluation; preserve theological content and reasonable near-cutoff observations."
    packet.update({"review_policy": "public-life-treatment-two-leaf-refinement-v2",
                   "proposed_decision": "Recommend question readiness if reported positions remain descriptive and prescriptive requires an independently stated public ought-claim. Preserve legitimate overlap and .69 boundary observations; evaluate routing separately.",
                   "interpretation_scope": "Block-level treatment and expressed perspective only. This pack does not bind support/criticism to a particular object or proposition; do not infer object-specific or pastor-level stance from co-occurrence."})
    packet.pop("input_fingerprint")
    packet["input_fingerprint"] = fingerprint(packet)
    return packet


def public_refinement_checks(cases):
    targets = []
    for case in cases:
        if case["video_id"] == "contract-probes" and case["block_id"] in (3, 7, 8, 14, 15, 16):
            targets.append({"block_id": case["block_id"],
                            "expected_actions": case["expected_positive_leaves"],
                            "probabilities": case["leaf_answer"]["probabilities"],
                            "provisional_display": case["provisional_display_leaves"],
                            "interpretation": {
                                3: "Moral and critical are independently evidenced; prescriptive should not be inferred from condemnation alone.",
                                7: "Support and listener advocacy are explicit; no specified institutional rule/change is stated.",
                                8: "Reporting the governor's praise is descriptive, not the preacher's support.",
                                14: "Theological/moral/illustrative framing coexist; descriptive=.69 in V1 is a reasonable boundary observation, not a required cutoff crossing.",
                                15: "Explicit repeal supplies a public policy outcome alongside moral criticism and listener advocacy.",
                                16: "Rejecting misuse of God's name conveys theological and moral criticism. V1 theological=.69 is not a failed measurement.",
                            }[case["block_id"]]})
    routing = []
    for case in cases:
        if case["video_id"] != "contract-probes" and not case["route"]["route"]:
            routing.append({"video_id": case["video_id"], "block_id": case["block_id"],
                            "public_life_support": case["public_life_support"],
                            "treatment_probabilities": case["leaf_answer"]["probabilities"],
                            "provisional_display": case["provisional_display_leaves"],
                            "scope": "Below-route diagnostic, not evidence of corpus recall"})
    return {"focused_semantic_checks": targets, "below_route_diagnostics": routing,
            "router_status": "not_approved_for_coverage; .55 misses reviewed treatment at 1200:26 and 4430:34",
            "routing_recommendation": "Retain .55 as a sampling diagnostic. Propose eligibility-only coverage routing for broader treatment measurement; no routing change is activated by this question refinement.",
            "threshold_policy": ".70 remains display-only; readiness requires semantic interpretation, not exact label matching at that cutoff."}


def evaluate_public_refinement(packet, *, client):
    from pastor_transcript_extractor.sermon_listener_directive_review import evaluate_review
    result, execution = evaluate_review(packet, pack=PUBLIC_LIFE_TREATMENT, client=client)
    result["refinement_checks"] = public_refinement_checks(result["cases"])
    result.pop("input_fingerprint")
    result["input_fingerprint"] = fingerprint(result)
    return result, execution


PUBLIC_COMPLETED_FINGERPRINT = "8930a9ad6776bf3267a6593776cd5e1028ce74895211eca871433c666f092048"
PUBLIC_COMPLETION_OUTPUT = Path("evaluation/sermon-topics/public-life-treatment-stage-gate-v2.json")
PUBLIC_ROUTING_OUTPUT = Path("evaluation/sermon-topics/public-life-routing-comparison-v2.json")


def load_approved_public_review(path: Path = PUBLIC_V2_OUTPUT):
    import json
    review = json.loads(path.read_text())
    identity = {k: v for k, v in review.items() if k != "input_fingerprint"}
    if (review.get("input_fingerprint") != PUBLIC_COMPLETED_FINGERPRINT
            or fingerprint(identity) != PUBLIC_COMPLETED_FINGERPRINT
            or review.get("question_pack_version") != PUBLIC_LIFE_TREATMENT.version
            or review.get("question_pack_digest") != PUBLIC_LIFE_TREATMENT.digest()):
        raise ValueError("Completion requires the fingerprint-valid approved public-life V2 review")
    return review


def build_public_completion(path: Path = PUBLIC_V2_OUTPUT):
    review = load_approved_public_review(path)
    report = {"schema_version": 1, "decision_version": "public-life-question-readiness-v2",
              "reviewed_by": "Brian Cummings", "reviewed_on": "2026-10-13",
              "source_review_fingerprint": PUBLIC_COMPLETED_FINGERPRINT,
              "question_pack_version": PUBLIC_LIFE_TREATMENT.version,
              "question_pack_digest": PUBLIC_LIFE_TREATMENT.digest(),
              "question_set_readiness": "ready_for_broader_analysis",
              "approved_leaves": list(PUBLIC_LIFE_TREATMENT.definitions),
              "router": "supporting_mass_055_not_approved_for_coverage",
              "review_display_threshold": review["review_display_threshold"],
              "collection_threshold_status": "not_established_by_display_cutoff",
              "policy_effect": "question_level_readiness_only; no_broader_collection_activation",
              "provider_requests": 0,
              "interpretation": "Close treatment-question validation. Freeze V2 and six reused V1 dimensions; preserve legitimate overlaps and .69 boundary observations. No treatment V3, threshold tuning, or additional inference. Address eligibility-only routing separately before broader collection. Object-specific and pastor-level inference remain outside this approval."}
    report["input_fingerprint"] = fingerprint(report)
    return report


def build_public_routing_comparison(path: Path = PUBLIC_V2_OUTPUT):
    """Compare routing on saved evidence only; no provider or database reads."""
    review = load_approved_public_review(path)
    rows = []
    exclusions = []
    cutoff = review["review_display_threshold"]
    for case in review["cases"]:
        if case["video_id"] == "contract-probes":
            continue
        probabilities = case["leaf_answer"]["probabilities"]
        PUBLIC_LIFE_TREATMENT.validate(probabilities)
        eligible = public_life_route(case)["route"]
        old = eligible and case["public_life_support"] >= PUBLIC_ROUTE_THRESHOLD
        displayed = sorted(k for k, p in probabilities.items() if p >= cutoff)
        rows.append({"video_id": case["video_id"], "block_id": case["block_id"],
                     "target_text": case["target_text"],
                     "projection_eligibility": case["projection_eligibility"],
                     "public_life_support": case["public_life_support"],
                     "old_supporting_mass_route": old, "proposed_eligibility_route": eligible,
                     "probabilities": probabilities, "provisional_display_leaves": displayed,
                     "reviewed_coverage_miss": (case["video_id"], case["block_id"]) in ((4430, 34), (1200, 26)),
                     "source_pack_lineage": {leaf: {"source_pack": source["source_pack"],
                         "source_pack_digest": source["source_pack_digest"]}
                         for leaf, source in case["leaf_answer"].get("leaf_sources", {}).items()}})
    for case in review["excluded_content_controls"]:
        proposal = public_life_route(case)
        if proposal["route"]:
            raise ValueError("Saved excluded-content control is eligible; inspect evidence before routing approval")
        exclusions.append({"video_id": case["video_id"], "block_id": case["block_id"],
                           "projection_eligibility": case["projection_eligibility"],
                           "proposed_route": proposal, "target_text": case["target_text"]})
    old_count = sum(c["old_supporting_mass_route"] for c in rows)
    new_count = sum(c["proposed_eligibility_route"] for c in rows)
    positives = [c for c in rows if c["provisional_display_leaves"]]
    report = {"schema_version": 1, "comparison_version": "public-life-eligible-routing-review-v2",
              "source_review_fingerprint": PUBLIC_COMPLETED_FINGERPRINT,
              "question_pack_version": PUBLIC_LIFE_TREATMENT.version,
              "question_pack_digest": PUBLIC_LIFE_TREATMENT.digest(),
              "old_route_policy_version": PUBLIC_ROUTE_VERSION,
              "proposed_route_policy_version": PUBLIC_COVERAGE_ROUTE_VERSION,
              "status": "routing_recommendation_pending_review",
              "proposed_decision": "Adopt eligibility-only routing for broader treatment collection. Keep public-life topic support as a sampling/prioritization diagnostic, not an inference gate.",
              "rows": rows, "excluded_content_controls": exclusions,
              "summary": {"natural_cases": len(rows), "old_routed": old_count,
                          "proposed_routed": new_count, "additional_routed": new_count-old_count,
                          "display_positive_cases": len(positives),
                          "old_omitted_display_positive_cases": sum(not c["old_supporting_mass_route"] for c in positives),
                          "reviewed_misses_recovered": sum(c["reviewed_coverage_miss"] and c["proposed_eligibility_route"] for c in rows),
                          "ineligible_controls_excluded": len(exclusions)},
              "review_display_threshold": cutoff,
              "analytical_credit": "routing_diagnostic_only",
              "broader_collection_activated": False,
              "provider_requests": 0,
              "limitations": "The deliberately stratified ten-case natural sample is not a corpus recall or cost estimate. Three displayed positive omissions include 590:60, whose quoted national/theological framing still requires interpretation. Only 4430:34 and 1200:26 are the two explicitly reviewed misses. Zero-treatment eligible blocks still require answers; missing evidence must not be treated as zero. Existing source eligible_block_count fields in V1/V2 counted candidate routes, not all eligible blocks; do not use them for workload estimates.",
              "cache_contract": "Routing does not enter question-pack cache identity. All compared probabilities and per-leaf V1/V2 provenance are reused unchanged. Current projection eligibility must be reassessed during collection; no new membership or content-role credit is granted by this historical comparison."}
    report["input_fingerprint"] = fingerprint(report)
    return report


def write_public_policy_report(path: Path, report):
    from pastor_transcript_extractor.analysis_artifact_cache import write_json_markdown
    if "summary" in report:
        summary = report["summary"]
        lines = ["# Public-life routing comparison", "", report["proposed_decision"], "",
                 f"Saved natural cases: {summary['natural_cases']}. Old route: {summary['old_routed']}; eligibility-only: {summary['proposed_routed']}.", "",
                 "| Video:block | Public support | .55 route | Eligibility route | Displayed treatment |", "|---|---:|---|---|---|"]
        for row in report["rows"]:
            lines.append(f"| {row['video_id']}:{row['block_id']} | {row['public_life_support']:.2f} | {row['old_supporting_mass_route']} | {row['proposed_eligibility_route']} | {', '.join(row['provisional_display_leaves']) or 'none'} |")
        lines.extend(["", report["limitations"], "", report["cache_contract"], "",
                      "Proposal implemented for review; broader collection remains inactive. Provider requests: 0.", ""])
    else:
        lines = ["# Public-life treatment validation complete", "", "Question-set readiness: **PASS — ready for broader analysis**.", "", report["interpretation"], "", "The .70 display cutoff is unchanged and does not establish collection thresholds. Provider requests: 0.", ""]
    return write_json_markdown(path, report, "\n".join(lines))
