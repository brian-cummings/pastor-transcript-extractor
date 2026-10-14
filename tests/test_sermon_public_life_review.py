from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_sermon_listener_directives import Sdk, adapter
from pastor_transcript_extractor.sermon_leaf_packs import PUBLIC_LIFE_TREATMENT as PACK, LISTENER_DIRECTIVES
from pastor_transcript_extractor.sermon_listener_directive_review import (
    build_listener_completion, COMPLETED_REVIEW_INPUT, evaluate_review, fingerprint,
)
from pastor_transcript_extractor.sermon_public_life_review import (
    public_life_route, public_life_support_route_v1, select_public_cases, prepare_public_review, PUBLIC_PROBE_PATH,
)
from pastor_transcript_extractor.sermon_topics import TOPICS, TOPIC_PACK_VERSION


def raw_block(index, support, eligible=True):
    scores = {key: {"score": 0., "confidence": 1.,
                    "probabilities": {str(i): float(i == 0) for i in range(5)}} for key in TOPICS}
    scores["society_public_life"] = {"score": 2 * support, "confidence": .5,
        "probabilities": {"0": 1-support, "1": 0., "2": support, "3": 0., "4": 0.}}
    return {"block_id": index, "segment_indexes": [index], "start_seconds": index*60.,
            "end_seconds": (index+1)*60., "scores": scores,
            "projection_eligibility": {"eligible": eligible},
            "context": {"target_text": "The council held a hearing.",
                        "leading_context": "", "trailing_context": "", "diagnostics": {}}}


class PublicLifeTests(unittest.TestCase):
    def test_listener_completion_corrects_expectation_and_freezes_inference(self):
        before = COMPLETED_REVIEW_INPUT.read_bytes()
        decision = build_listener_completion()
        self.assertEqual(before, COMPLETED_REVIEW_INPUT.read_bytes())
        self.assertEqual("ready_for_broader_analysis", decision["question_set_readiness"])
        expected = decision["corrected_natural_expectation"]["expected_actions"]
        self.assertNotIn("serve", expected)
        self.assertEqual(.42, decision["corrected_natural_expectation"]["serve_probability"])
        self.assertEqual(.70, decision["review_display_threshold"])
        natural = decision["corrected_review_checks"]["natural_action_regressions"]
        self.assertTrue(next(c for c in natural if c["video_id"] == 590)["retained_at_provisional_display"])
        self.assertEqual(LISTENER_DIRECTIVES.digest(), decision["question_pack_digest"])
        with tempfile.TemporaryDirectory() as directory:
            damaged = json.loads(before)
            damaged["cases"][0]["target_text"] = "Changed evidence"
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps(damaged))
            with self.assertRaisesRegex(ValueError, "fingerprint-valid"):
                build_listener_completion(path)

    def test_independent_public_questions_and_probes_cover_inventory(self):
        self.assertEqual(8, len(PACK.questions(0)))
        self.assertTrue(all(q["kind"] == "noul" for q in PACK.questions(0).values()))
        self.assertNotIn("ask the listener to", str(PACK.questions(0)))
        probes = json.loads(PUBLIC_PROBE_PATH.read_text())
        self.assertEqual(set(PACK.definitions), {k for p in probes for k in p["expected_positive_leaves"]})
        self.assertTrue(any(not p["expected_positive_leaves"] for p in probes))
        self.assertTrue(any(len(p["expected_positive_leaves"]) > 1 for p in probes))

    def test_route_uses_distribution_and_final_projection_eligibility(self):
        self.assertTrue(public_life_support_route_v1(raw_block(1, .55))["route"])
        self.assertFalse(public_life_support_route_v1(raw_block(1, .54))["route"])
        self.assertFalse(public_life_support_route_v1(raw_block(1, .99, False))["route"])
        self.assertEqual("candidate_pending_bounded_review", public_life_support_route_v1(raw_block(1, .8))["status"])

    def test_sampling_separates_shadow_cases_from_excluded_content(self):
        blocks = []
        for i, support in enumerate((.9, .56, .4, 0., .99)):
            raw = raw_block(i, support, i != 4)
            blocks.append({**raw, "public_life_support": support, "route": public_life_support_route_v1(raw)})
        cases = select_public_cases(blocks)
        self.assertEqual(4, len(cases))
        self.assertEqual(4, len({c["block_id"] for c in cases}))
        self.assertNotIn(4, [c["block_id"] for c in cases])
        shadow = next(c for c in cases if c["review_stratum"] == "below_route_shadow")
        self.assertEqual("prior_below_route_control", shadow["evaluation_scope"])
        self.assertFalse(shadow["route"]["route"])

    def test_preparation_and_evaluation_reuse_shared_cache_without_sibling_packs(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "classification.json"
            source.write_text("cached")
            raw = [raw_block(i, p, i != 4) for i, p in enumerate((.9, .56, .4, 0., .99))]
            database = SimpleNamespace(database_path=source,
                get_video_by_id=lambda i: SimpleNamespace(id=i, title="Public life"))
            gate = SimpleNamespace(eligible=True, source_path=source, topic_analysis_fingerprint="frozen")
            module = "pastor_transcript_extractor.sermon_listener_directive_review"
            with patch(module + ".assess_topic_profile_projection", return_value=gate), \
                 patch(module + ".read_topic_analysis_for_gate", return_value=({"question_pack_version": TOPIC_PACK_VERSION, "blocks": raw}, {})), \
                 patch(module + ".resolve_topic_block_context", side_effect=lambda b: b["context"]):
                packet = prepare_public_review(database, model="jev-1.13.0", probe_cache=Path(directory)/"probes")
            self.assertEqual(30, len(packet["cases"]))
            self.assertEqual(4, packet["sources"][0]["eligible_block_count"])
            self.assertEqual(2, packet["sources"][0]["candidate_routed_block_count"])
            self.assertEqual(3, len(packet["excluded_content_controls"]))
            # Separate per-video scopes, matching real per-video source directories.
            for case in packet["cases"]:
                if isinstance(case["video_id"], int):
                    case["cache_dir"] += str(case["video_id"])
            packet.pop("input_fingerprint")
            packet["input_fingerprint"] = fingerprint(packet)
            sdk = Sdk()
            first, counts = evaluate_review(packet, pack=PACK, client=adapter(sdk))
            self.assertGreater(counts["provider_requests"], 0)
            self.assertTrue(all(list(state) == [PACK.state_key] for state, questions in sdk.requests))
            self.assertTrue(all(len(questions) % 8 == 0 for state, questions in sdk.requests))
            repeated, counts = evaluate_review(packet, pack=PACK, client=adapter(sdk))
            self.assertEqual(0, counts["provider_requests"])
            self.assertEqual(first, repeated)
            self.assertFalse(list(Path(directory).rglob(LISTENER_DIRECTIVES.version)))

    def test_refinement_freezes_six_questions_and_reruns_only_two_on_same_cases(self):
        from pastor_transcript_extractor.sermon_leaf_packs import PUBLIC_LIFE_TREATMENT_V1, PUBLIC_LIFE_REFINEMENT
        from pastor_transcript_extractor.sermon_public_life_review import (
            PUBLIC_BASELINE_INPUT, PUBLIC_BASELINE_FINGERPRINT,
            prepare_public_refinement, evaluate_public_refinement,
        )
        baseline = json.loads(PUBLIC_BASELINE_INPUT.read_text())
        self.assertEqual(PUBLIC_BASELINE_FINGERPRINT, fingerprint({k:v for k,v in baseline.items() if k != "input_fingerprint"}))
        self.assertEqual(PUBLIC_LIFE_TREATMENT_V1.digest(), baseline["question_pack_digest"])
        for leaf in PACK.definitions:
            old = PUBLIC_LIFE_TREATMENT_V1.questions(0)[PUBLIC_LIFE_TREATMENT_V1.question_id(0, leaf)]
            new = PACK.questions(0)[PACK.question_id(0, leaf)]
            self.assertEqual(old == new, leaf not in PUBLIC_LIFE_REFINEMENT.definitions)
        prepared = deepcopy(baseline)
        prepared.update(question_pack_version=PACK.version, question_pack_digest=PACK.digest(), status="prepared_pending_evaluation", sources=[], database_sources=[])
        with tempfile.TemporaryDirectory() as directory:
            for case in prepared["cases"]:
                for key in ("leaf_answer", "request_provenance", "resolved_model_id", "provisional_display_leaves", "probe_matches_proposal"):
                    case.pop(key, None)
                case["cache_dir"] = str(Path(directory) / str(case["video_id"]))
            module = "pastor_transcript_extractor.sermon_public_life_review"
            with patch(module + ".prepare_public_review", return_value=deepcopy(prepared)):
                packet = prepare_public_refinement(None, model="jev-1.13.0", probe_cache=Path(directory))
            self.assertEqual(28, len(packet["cases"]))
            self.assertEqual(6, len(packet["unchanged_leaves"]))
            sdk = Sdk()
            result, counts = evaluate_public_refinement(packet, client=adapter(sdk))
            self.assertEqual(56, sum(len(q) for state, q in sdk.requests))
            old_cases = {(str(c["video_id"]), c["block_id"]): c for c in baseline["cases"]}
            for case in result["cases"]:
                old = old_cases[str(case["video_id"]), case["block_id"]]
                for leaf in packet["unchanged_leaves"]:
                    self.assertEqual(old["leaf_answer"]["probabilities"][leaf], case["leaf_answer"]["probabilities"][leaf])
            repeated, counts = evaluate_public_refinement(packet, client=adapter(sdk))
            self.assertEqual(0, counts["provider_requests"])
            self.assertEqual(result, repeated)
            corrected = next(c for c in result["cases"] if c["video_id"] == "contract-probes" and c["block_id"] == 16)
            self.assertIn("moral", corrected["expected_positive_leaves"])
            self.assertEqual(.69, corrected["leaf_answer"]["probabilities"]["theological"])
            prepared["cases"][0]["target_text"] = "changed"
            with patch(module + ".prepare_public_review", return_value=prepared):
                with self.assertRaisesRegex(ValueError, "evidence changed"):
                    prepare_public_refinement(None, model="jev-1.13.0", probe_cache=Path(directory))

    def test_coverage_route_requires_only_current_content_eligibility(self):
        for support in (0., .04, .54, .55, 1.):
            self.assertTrue(public_life_route(raw_block(1, support))["route"])
            self.assertFalse(public_life_route(raw_block(1, support, False))["route"])
        self.assertTrue(public_life_route({"projection_eligibility": {"eligible": True}})["route"])
        for value in (False, "false", None):
            self.assertFalse(public_life_route({"projection_eligibility": {"eligible": value}})["route"])
        self.assertFalse(public_life_route({})["route"])

    def test_completed_questions_and_cached_routing_comparison_preserve_evidence(self):
        from pastor_transcript_extractor.sermon_public_life_review import (
            PUBLIC_V2_OUTPUT, build_public_completion, build_public_routing_comparison,
            write_public_policy_report,
        )
        before = PUBLIC_V2_OUTPUT.read_bytes()
        completion = build_public_completion()
        comparison = build_public_routing_comparison()
        self.assertEqual(before, PUBLIC_V2_OUTPUT.read_bytes())
        self.assertEqual("ready_for_broader_analysis", completion["question_set_readiness"])
        self.assertEqual(PACK.digest(), completion["question_pack_digest"])
        self.assertEqual(0, comparison["provider_requests"])
        self.assertFalse(comparison["broader_collection_activated"])
        self.assertEqual(4, comparison["summary"]["old_routed"])
        self.assertEqual(10, comparison["summary"]["proposed_routed"])
        self.assertEqual(2, comparison["summary"]["reviewed_misses_recovered"])
        self.assertTrue(all(not c["proposed_route"]["route"] for c in comparison["excluded_content_controls"]))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "comparison.json"
            self.assertFalse(write_public_policy_report(output, comparison)[2])
            self.assertTrue(write_public_policy_report(output, comparison)[2])
            output.with_suffix(".md").write_text("broken")
            self.assertFalse(write_public_policy_report(output, comparison)[2])


if __name__ == "__main__":
    unittest.main()
