"""Bounded cache-first listener-directive development; no production activation."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from pastor_transcript_extractor.analysis_artifact_cache import file_signature, write_json_markdown
from pastor_transcript_extractor.sermon_classification import TranscriptBlock
from pastor_transcript_extractor.sermon_classifier_typesafe import TypeSafeBlockAnswer, TypeSafeBlockCache
from pastor_transcript_extractor.sermon_leaf_packs import (
    LEAF_PACKS, LISTENER_DIRECTIVES, LISTENER_DIRECTIVES_V2,
    LISTENER_DIRECTIVE_REFINEMENT, REVISED_DIRECTIVE_LEAVES, listener_directive_route,
)
from pastor_transcript_extractor.sermon_topic_profile_analysis import read_topic_analysis_for_gate
from pastor_transcript_extractor.sermon_topic_projection import assess_topic_profile_projection
from pastor_transcript_extractor.sermon_topics import TOPIC_PACK_VERSION, TopicBlockContext, resolve_topic_block_context

DEFAULT_REVIEW_OUTPUT = Path("evaluation/sermon-topics/listener-directives-review-v3.json")
DEFAULT_BASELINE_INPUT = Path("evaluation/sermon-topics/listener-directives-review-v2.json")
BASELINE_REVIEW_FINGERPRINT = "5aa669ea4324bd96a157e554eac51aba10c2bb83ad2e9e3b2aa82f0de7188bc2"
DEFAULT_VIDEO_IDS = (1200, 590, 4430)
REVIEW_POLICY = "listener-directive-bounded-review-v1"
REVIEW_DISPLAY_THRESHOLD = 0.70
PROBE_PATH = Path(__file__).parent / "data" / "listener-directive-probes-v1.json"
# Cues select a diverse inspection sample; they never establish a directive or gate inference.
CUES = re.compile(r"\b(trust|believe|repent|confess|pray|prayer|read|study|share|witness|serve|help|give|join|vote|should|must|let us|need to)\b", re.I)


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def select_cases(blocks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Four deterministic eligible strata per sermon, including router challenges."""
    eligible = [b for b in sorted(blocks, key=lambda b: int(b["block_id"]))
                if listener_directive_route(b)["route"]]
    chosen: list[dict[str, Any]] = []
    remaining = list(eligible)
    for stratum in ("outside_salvation", "cue_rich", "no_cue", "coverage"):
        candidates = remaining
        if stratum == "outside_salvation":
            candidates = [b for b in remaining if b.get("salvation_support", 0) < 0.55]
        elif stratum == "no_cue":
            candidates = [b for b in remaining if not CUES.search(b["target_text"])]
        if not candidates:
            continue
        item = max(candidates, key=lambda b: (len(CUES.findall(b["target_text"])), -int(b["block_id"]))) if stratum == "cue_rich" else candidates[len(candidates) // 2]
        chosen.append({**item, "review_stratum": stratum,
                       "expected_positive_leaves": None,
                       "proposed_label": "inspect_target_only_before_acceptance"})
        remaining.remove(item)
    return chosen


def prepare_review(database, *, model: str, probe_cache: Path,
                   pack=LISTENER_DIRECTIVES, probe_path: Path = PROBE_PATH,
                   selector=select_cases, router=listener_directive_route) -> dict[str, Any]:
    from pastor_transcript_extractor.sermon_topics import topic_supporting_or_above_probability, validated_topic_scores

    database_path = database.database_path
    database_sources = [{"signature": file_signature(path)}
                        for path in (database_path, str(database_path) + "-wal")]
    cases: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for video_id in DEFAULT_VIDEO_IDS:
        video = database.get_video_by_id(video_id)
        if video is None:
            raise ValueError(f"Missing bounded review video {video_id}")
        gate = assess_topic_profile_projection(database, video)
        if not gate.eligible or gate.source_path is None:
            raise ValueError(f"Video {video_id} is not projection eligible")
        signature = file_signature(gate.source_path)
        analysis, _ = read_topic_analysis_for_gate(gate)
        if analysis.get("question_pack_version") != TOPIC_PACK_VERSION:
            raise ValueError(f"Video {video_id} has stale broad questions")
        candidates = []
        raw_blocks = analysis.get("blocks")
        if not isinstance(raw_blocks, list):
            raise ValueError(f"Video {video_id} has no broad blocks")
        for raw in raw_blocks:
            context = resolve_topic_block_context(raw)
            scores = validated_topic_scores(raw)
            item = {"video_id": video_id, "title": video.title,
                    "block_id": raw["block_id"], "segment_indexes": raw["segment_indexes"],
                    "start_seconds": raw["start_seconds"], "end_seconds": raw["end_seconds"],
                    "target_text": context["target_text"],
                    "leading_context": context.get("leading_context", ""),
                    "trailing_context": context.get("trailing_context", ""),
                    "context_diagnostics": context.get("diagnostics", {}),
                    "projection_eligibility": raw.get("projection_eligibility"),
                    "salvation_support": topic_supporting_or_above_probability(scores["salvation_gospel"]),
                    "route": router(raw),
                    "public_life_support": topic_supporting_or_above_probability(scores["society_public_life"]),
                    "cache_dir": str(Path(gate.source_path).parent / "inference-cache")}
            candidates.append(item)
        selected = selector(candidates)
        if not selected:
            raise ValueError(f"Video {video_id} has no eligible review blocks")
        cases.extend(selected)
        excluded = [b for b in candidates if not listener_directive_route(b)["route"]]
        exclusions.extend(excluded[:2])
        if file_signature(gate.source_path) != signature:
            raise ValueError("Source changed during bounded review preparation")
        sources.append({"video_id": video_id, "signature": signature,
                        "topic_fingerprint": gate.topic_analysis_fingerprint,
                        "eligible_block_count": sum(listener_directive_route(b)["route"] for b in candidates),
                        "candidate_routed_block_count": sum(b["route"]["route"] for b in candidates),
                        "excluded_block_count": len(excluded)})
    _check_sources(sources + database_sources)
    probes = json.loads(probe_path.read_text())
    for position, probe in enumerate(probes):
        expected = probe["expected_positive_leaves"]
        if not set(expected) <= pack.definitions.keys():
            raise ValueError("Probe has unknown leaf")
        cases.append({**probe, "video_id": "contract-probes", "block_id": position,
                      "start_seconds": float(position * 60), "end_seconds": float((position + 1) * 60),
                      "segment_indexes": [position], "context_diagnostics": {},
                      "leading_context": probe.get("leading_context", ""),
                      "trailing_context": probe.get("trailing_context", ""),
                      "cache_dir": str(probe_cache), "review_stratum": "authored_contract_probe"})
    packet = {"schema_version": 1, "review_policy": REVIEW_POLICY,
              "question_pack_version": pack.version,
              "question_pack_digest": pack.digest(),
              "question_inventory": pack.questions(0),
              "requested_model_id": model, "sources": sources,
              "database_sources": database_sources,
              "cases": cases, "excluded_content_controls": exclusions,
              "status": "prepared_pending_evaluation", "analytical_credit": "none",
              "proposed_decision": "Approve the nine-action behavior contract and eligible-block router only after bounded review; retain raw answers and defer production thresholds.",
              "routing_proposal": "Route all final projection-eligible blocks. Salvation support and text cues are sampling diagnostics only.",
              "sampling_limit": "At most twelve natural blocks from three sermons plus authored probes; this tests boundaries, not corpus recall or a validated taxonomy.",
              "review_display_threshold": REVIEW_DISPLAY_THRESHOLD,
              "observation_policy": "Raw probabilities only; 0.70 is a provisional review display cutoff, not a collection threshold."}
    packet["input_fingerprint"] = fingerprint(packet)
    return packet


def prepare_refinement_review(database, *, model: str, probe_cache: Path,
                              baseline_path: Path = DEFAULT_BASELINE_INPUT) -> dict[str, Any]:
    """Freeze the reviewed cases and reuse only leaves with identical question semantics."""
    baseline = json.loads(baseline_path.read_text())
    packet = prepare_review(database, model=model, probe_cache=probe_cache)
    packet = attach_leaf_refinement(packet, baseline, baseline_pack=LISTENER_DIRECTIVES_V2,
        pack=LISTENER_DIRECTIVES, refinement_pack=LISTENER_DIRECTIVE_REFINEMENT,
        expected_fingerprint=BASELINE_REVIEW_FINGERPRINT)
    unchanged = set(LISTENER_DIRECTIVES.definitions) - set(REVISED_DIRECTIVE_LEAVES)

    packet.update({
        "review_policy": "listener-directive-serve-only-refinement-v3",
        "baseline_review_fingerprint": BASELINE_REVIEW_FINGERPRINT,
        "inference_pack_version": LISTENER_DIRECTIVE_REFINEMENT.version,
        "revised_leaves": list(REVISED_DIRECTIVE_LEAVES),
        "unchanged_leaves": sorted(unchanged),
        "stage_gate": {"router": "pass", "target_only_evidence": "pass",
                       "unchanged_eight_leaves": "preserved", "serve": "pending_refinement_review"},
        "proposed_decision": "Approve the refined question set for broader analysis if the four overlap regressions remain clean and serve recovers on 590:64 while the other eight answers remain unchanged; do not tune thresholds or expand the cohort.",
    })
    packet.pop("input_fingerprint")
    packet["input_fingerprint"] = fingerprint(packet)
    return packet


def _check_sources(sources: list[Mapping[str, Any]]) -> None:
    for source in sources:
        if file_signature(source["signature"]["path"]) != source["signature"]:
            raise ValueError("Source changed during bounded review; prepare again")


def evaluate_review(packet: Mapping[str, Any], *, client, pack=LISTENER_DIRECTIVES) -> tuple[dict[str, Any], dict[str, int]]:
    """Evaluate only this pack using the same per-block cache as subsequent packs."""
    identity = {key: value for key, value in packet.items() if key != "input_fingerprint"}
    if packet.get("input_fingerprint") != fingerprint(identity):
        raise ValueError("Review packet fingerprint mismatch")
    if packet.get("status") not in (None, "prepared_pending_evaluation"):
        raise ValueError("Evaluation requires a freshly prepared packet")
    _check_sources(packet["sources"] + packet.get("database_sources", []))
    if packet.get("question_pack_digest") != pack.digest():
        raise ValueError("Review uses stale directive questions")
    inference_pack = packet.get("inference_pack_version", pack.version)
    if inference_pack not in LEAF_PACKS or not set(LEAF_PACKS[inference_pack].definitions) <= set(pack.definitions):
        raise ValueError("Unsupported leaf inference pack")
    cases = packet["cases"]
    if len(cases) > 48:
        raise ValueError("Listener review exceeds the bounded 48-block limit")
    evaluated: list[dict[str, Any]] = []
    execution = {"hits": 0, "misses": 0, "provider_requests": 0}
    for cache_dir in sorted({str(c["cache_dir"]) for c in cases}):
        selected = [c for c in cases if str(c["cache_dir"]) == cache_dir]
        if len({c["block_id"] for c in selected}) != len(selected):
            raise ValueError("Duplicate review block IDs in one cache scope")
        blocks = [TranscriptBlock(block_id=c["block_id"], segment_indexes=c["segment_indexes"],
                                  start_seconds=c["start_seconds"], end_seconds=c["end_seconds"],
                                  text=c["target_text"]) for c in selected]
        contexts = {c["block_id"]: TopicBlockContext(
            target_text=c["target_text"], leading_context=c["leading_context"],
            trailing_context=c["trailing_context"], diagnostics=c["context_diagnostics"])
                    for c in selected}
        cache = TypeSafeBlockCache(Path(cache_dir), model=packet["requested_model_id"])
        answers = cache.assess_packs(client, {}, blocks,
                                    requested_packs=frozenset({inference_pack}),
                                    topic_contexts=contexts)
        for key in execution:
            execution[key] += getattr(cache, key)
        for case in selected:
            answer = answers[case["block_id"]]
            if inference_pack != pack.version:
                baseline_pack = packet.get("baseline_pack_version", LISTENER_DIRECTIVES_V2.version)
                baseline_answer = TypeSafeBlockAnswer(
                    choice="unclear", probabilities={}, confidence=None,
                    resolved_model_id=case["baseline_resolved_model_id"],
                    request_provenance=case["baseline_request_provenance"],
                    leaf_answers={baseline_pack: case["baseline_leaf_answer"]},
                )
                answer = cache.compose_leaf_answer(
                    next(b for b in blocks if b.block_id == case["block_id"]),
                    pack=pack.version, topic_context=contexts[case["block_id"]],
                    sources={leaf: (inference_pack, answer) if leaf in LEAF_PACKS[inference_pack].definitions
                             else (baseline_pack, baseline_answer)
                             for leaf in pack.definitions},
                )
            leaf = answer.leaf_answers[pack.version]
            probabilities = dict(leaf["probabilities"])
            displayed = sorted(k for k, value in probabilities.items() if value >= packet.get("review_display_threshold", REVIEW_DISPLAY_THRESHOLD))
            expected = case.get("expected_positive_leaves")
            evaluated.append({**case, "leaf_answer": leaf,
                              "resolved_model_id": answer.resolved_model_id,
                              "request_provenance": answer.request_provenance,
                              "provisional_display_leaves": displayed,
                              "probe_matches_proposal": displayed == sorted(expected) if expected is not None else None})
    _check_sources(packet["sources"] + packet.get("database_sources", []))
    result = {**packet, "cases": evaluated, "status": "evaluated_pending_human_review",
              "prepared_input_fingerprint": packet["input_fingerprint"]}
    if pack == LISTENER_DIRECTIVES and inference_pack == LISTENER_DIRECTIVE_REFINEMENT.version:
        result["refinement_checks"] = _refinement_checks(evaluated)
    result.pop("input_fingerprint")
    result["input_fingerprint"] = fingerprint(result)
    return result, execution


def _refinement_checks(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    overlap_leaves = {"change_behavior", "give", "serve"}
    overlaps = []
    authored = []
    for case in cases:
        if case["video_id"] == "contract-probes":
            expected = sorted(set(case["expected_positive_leaves"]) & overlap_leaves)
            observed = sorted(set(case["provisional_display_leaves"]) & overlap_leaves)
            authored.append({"block_id": case["block_id"], "expected_revised_leaves": expected,
                             "displayed_revised_leaves": observed, "matches_proposal": observed == expected})
        if case["video_id"] == "contract-probes" and case["block_id"] in (5, 16, 18, 19):
            overlaps.append(authored[-1])
    natural = []
    for video, block_id, expected in ((590, 64, ("participate", "spiritual_practice", "witness")),
                                      (4430, 22, ("witness",))):
        case = next((c for c in cases if c["video_id"] == video and c["block_id"] == block_id), None)
        if case is not None:
            natural.append({"video_id": video, "block_id": block_id,
                            "expected_actions": list(expected),
                            "probabilities": {k: case["leaf_answer"]["probabilities"][k] for k in expected},
                            "retained_at_provisional_display": all(k in case["provisional_display_leaves"] for k in expected)})
    return {"overlap_regressions": overlaps, "all_authored_overlap_checks": authored,
            "recomputed_leaves": list(REVISED_DIRECTIVE_LEAVES),
            "natural_action_regressions": natural,
            "interpretation": "Display comparisons are diagnostic, not collection thresholds or automatic approval. Repent at .69 remains an unchanged accepted boundary observation."}


def write_review(path: Path, packet: Mapping[str, Any], *, title="Listener directive bounded review"):
    lines = ["# " + title, "", str(packet["status"]), "",
             str(packet["proposed_decision"]), "", str(packet["sampling_limit"]), "",
             str(packet["observation_policy"]), "", "## Cases", ""]
    if "refinement_checks" in packet:
        lines.extend(["## Focused refinement checks", "", "```json",
                      json.dumps(packet["refinement_checks"], indent=2), "```", ""])
    for case in packet["cases"]:
        lines.extend([f"### {case['video_id']}:{case['block_id']} — {case['review_stratum']}", "",
                      f"Expected: {case.get('expected_positive_leaves')}; provisional display: {case.get('provisional_display_leaves')}", "",
                      "Context (clarification only): " + case["leading_context"], "",
                      "Target: " + case["target_text"], "",
                      "Context (clarification only): " + case["trailing_context"], ""])
        if "leaf_answer" in case:
            lines.extend(["Probabilities: " + json.dumps(case["leaf_answer"]["probabilities"], sort_keys=True), ""])
    lines.extend(["## Excluded content controls (never sent to the provider)", ""])
    for case in packet["excluded_content_controls"]:
        lines.extend([f"{case['video_id']}:{case['block_id']} — {case['projection_eligibility']}", "", case["target_text"], ""])
    return write_json_markdown(path, packet, "\n".join(lines) + "\n")


COMPLETED_REVIEW_INPUT = Path("evaluation/sermon-topics/listener-directives-review-v3.json")
COMPLETED_REVIEW_FINGERPRINT = "d117434e432c36596e1bc39a22942543e59f9cc9980e483cea850dcf666cff30"
DEFAULT_COMPLETION_OUTPUT = Path("evaluation/sermon-topics/listener-directive-stage-gate-v3.json")


def build_listener_completion(path: Path = COMPLETED_REVIEW_INPUT) -> dict[str, Any]:
    """Record accepted interpretation without altering cached inference or historical reports."""
    review = json.loads(path.read_text())
    identity = {k: v for k, v in review.items() if k != "input_fingerprint"}
    if (fingerprint(identity) != COMPLETED_REVIEW_FINGERPRINT
            or review.get("input_fingerprint") != COMPLETED_REVIEW_FINGERPRINT
            or review.get("question_pack_digest") != LISTENER_DIRECTIVES.digest()):
        raise ValueError("Listener completion requires the frozen fingerprint-valid V3 review")
    checks = _refinement_checks(review["cases"])
    if len(checks["all_authored_overlap_checks"]) != 24 or not all(
            c["matches_proposal"] for c in checks["all_authored_overlap_checks"]):
        raise ValueError("Listener completion requires the accepted overlap checks")
    result = {
        "schema_version": 1, "decision_version": "listener-directive-question-readiness-v3",
        "reviewed_by": "Brian Cummings", "reviewed_on": "2026-10-13",
        "source_review_fingerprint": COMPLETED_REVIEW_FINGERPRINT,
        "question_pack_version": LISTENER_DIRECTIVES.version,
        "question_pack_digest": LISTENER_DIRECTIVES.digest(),
        "question_set_readiness": "ready_for_broader_analysis",
        "approved_leaves": list(LISTENER_DIRECTIVES.definitions),
        "router": "pass_bounded_review", "directive_evidence_contract": "pass_target_only",
        "corrected_natural_expectation": {
            "video_id": 590, "block_id": 64,
            "expected_actions": ["participate", "spiritual_practice", "witness"],
            "serve_probability": .42,
            "interpretation": "Reasonable secondary ambiguity; service is inferential here rather than an explicit act of help. Remove the prior serve-positive gate, not the raw probability.",
        },
        "corrected_review_checks": checks,
        "review_display_threshold": REVIEW_DISPLAY_THRESHOLD,
        "collection_threshold_status": "not_established_by_display_cutoff",
        "policy_effect": "question_level_readiness_only",
        "next_question_set": "public_life_treatment",
        "interpretation": "Close listener question-set validation. Freeze V3 questions, target-only evidence, independent cached probabilities, and existing router. No further serve tuning or inference, threshold change, or larger listener cohort is required. Historical reports retain their original pending/recovery fields; this decision records subsequent acceptance.",
    }
    result["input_fingerprint"] = fingerprint(result)
    return result


def write_listener_completion(path: Path, decision: Mapping[str, Any]):
    corrected = decision["corrected_natural_expectation"]
    rendered = ("# Listener directive validation complete\n\n"
                "Question-set readiness: **PASS — ready for broader analysis**.\n\n"
                + str(decision["interpretation"]) + "\n\n"
                + f"590:64 expected actions: {', '.join(corrected['expected_actions'])}. "
                + "Serve=.42 is reasonable secondary ambiguity, not a failure. "
                + "The .70 review display cutoff remains unchanged and is not a collection threshold.\n\n"
                + "All four original overlap regressions and all 24 authored overlap checks remain clean. "
                + "Original V1/V2/V3 evidence is preserved; no provider requests were made to record acceptance.\n\n"
                + "Next question set: public-life treatment.\n")
    return write_json_markdown(path, decision, rendered)


def attach_leaf_refinement(packet, baseline, *, baseline_pack, pack, refinement_pack,
                           expected_fingerprint: str):
    """Reuse identical leaves only when the reviewed evidence and meanings match."""
    identity = {k: v for k, v in baseline.items() if k != "input_fingerprint"}
    if (baseline.get("input_fingerprint") != expected_fingerprint
            or fingerprint(identity) != expected_fingerprint
            or baseline.get("question_pack_version") != baseline_pack.version
            or baseline.get("question_pack_digest") != baseline_pack.digest()
            or baseline.get("requested_model_id") != packet["requested_model_id"]):
        raise ValueError("Refinement requires the fingerprint-valid reviewed baseline and same model")
    def key(case):
        return str(case["video_id"]), int(case["block_id"])
    old_cases = {key(c): c for c in baseline["cases"]}
    if len(old_cases) != len(baseline["cases"]) or set(old_cases) != {key(c) for c in packet["cases"]}:
        raise ValueError("Bounded refinement cases changed")
    unchanged = set(pack.definitions) - set(refinement_pack.definitions)
    evidence_keys = ("target_text", "leading_context", "trailing_context", "context_diagnostics",
                     "start_seconds", "end_seconds", "segment_indexes")
    for case in packet["cases"]:
        old = old_cases[key(case)]
        if any(case.get(k) != old.get(k) for k in evidence_keys):
            raise ValueError("Bounded refinement evidence changed")
        baseline_pack.validate(old["leaf_answer"]["probabilities"])
        if old["leaf_answer"].get("version") != baseline_pack.version:
            raise ValueError("Baseline answer pack version differs")
        for leaf in unchanged:
            if pack.questions(0)[pack.question_id(0, leaf)] != baseline_pack.questions(0)[baseline_pack.question_id(0, leaf)]:
                raise ValueError("Unchanged leaf question semantics differ")
        case.update({"baseline_leaf_answer": deepcopy(old["leaf_answer"]),
                     "baseline_request_provenance": deepcopy(old["request_provenance"]),
                     "baseline_resolved_model_id": old["resolved_model_id"]})
    packet.update({"baseline_review_fingerprint": expected_fingerprint,
                   "baseline_pack_version": baseline_pack.version,
                   "inference_pack_version": refinement_pack.version,
                   "revised_leaves": list(refinement_pack.definitions),
                   "unchanged_leaves": sorted(unchanged)})
    packet.pop("input_fingerprint", None)
    packet["input_fingerprint"] = fingerprint(packet)
    return packet
