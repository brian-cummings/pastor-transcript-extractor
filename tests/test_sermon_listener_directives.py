from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.recording_verifier_typesafe import TypeSafeSdkAdapter
from pastor_transcript_extractor.sermon_classifier_typesafe import TypeSafeBlockAnswer, TypeSafeBlockCache, SALVATION_RELATIONSHIPS_PACK
from pastor_transcript_extractor.sermon_leaf_packs import LISTENER_DIRECTIVES as PACK, listener_directive_route
from pastor_transcript_extractor.sermon_listener_directive_review import (
    select_cases, evaluate_review, fingerprint, write_review, PROBE_PATH, prepare_review,
    prepare_refinement_review, BASELINE_REVIEW_FINGERPRINT, DEFAULT_BASELINE_INPUT,
)
from pastor_transcript_extractor.sermon_classification import TranscriptBlock
from pastor_transcript_extractor.sermon_topics import TopicBlockContext


class Sdk:
    def __init__(self):
        self.requests = []

    def system_one(self, state, questions, **kwargs):
        self.requests.append((state, questions))
        return SimpleNamespace(
            model="jev-1.13.0", nouls={key: SimpleNamespace(noul=0.8) for key in questions},
            choices={}, scores={}, usage=None,
        )


def adapter(sdk):
    result = object.__new__(TypeSafeSdkAdapter)
    result.model = "jev-1.13.0"
    result.timeout_seconds = 45
    result._client = sdk
    result._Noul = lambda **kwargs: kwargs
    return result


def block(number=0, text="Trust Jesus today."):
    return TranscriptBlock(number, [number], number * 60., (number + 1) * 60., text)


def context(b):
    return TopicBlockContext(target_text=b.text, leading_context="", trailing_context="", diagnostics={})


class ListenerDirectiveTests(unittest.TestCase):
    def test_independent_questions_and_complete_semantic_digest(self):
        self.assertEqual(9, len(PACK.questions(0)))
        self.assertTrue(all(q["kind"] == "noul" for q in PACK.questions(0).values()))
        from dataclasses import replace
        self.assertNotEqual(PACK.digest(), replace(PACK, boundary="Changed boundary").digest())
        self.assertIn("target_text", str(PACK.questions(2)))
        PACK.validate({leaf: 0.5 for leaf in PACK.definitions})
        for value in (float("nan"), float("inf"), -0.1, 1.1, True, "0.8"):
            with self.assertRaises(ValueError):
                PACK.validate({leaf: value for leaf in PACK.definitions})
        with self.assertRaises(ValueError):
            PACK.validate({})

    def test_route_is_not_conditioned_on_salvation_or_cues(self):
        self.assertTrue(listener_directive_route({"projection_eligibility": {"eligible": True}})["route"])
        for eligibility in (None, {}, {"eligible": False}, {"eligible": "false"}):
            self.assertFalse(listener_directive_route({"projection_eligibility": eligibility})["route"])

    def test_cache_replays_changed_batch_and_repairs_corruption(self):
        sdk = Sdk()
        with tempfile.TemporaryDirectory() as directory:
            cache = TypeSafeBlockCache(Path(directory), model="jev-1.13.0")
            first, second = block(), block(1)
            def assess(items):
                return cache.assess_packs(adapter(sdk), {}, items, requested_packs=frozenset({PACK.version}),
                                          topic_contexts={b.block_id: context(b) for b in items})
            assess([first, second])
            self.assertEqual(1, len(sdk.requests))
            answer = assess([second])[second.block_id]
            self.assertEqual(1, len(sdk.requests))
            self.assertEqual(set(PACK.definitions), set(answer.leaf_answers[PACK.version]["probabilities"]))
            self.assertFalse((cache.root / "packs" / SALVATION_RELATIONSHIPS_PACK).exists())
            self.assertEqual([PACK.state_key], list(sdk.requests[0][0]))
            self.assertEqual(18, len(sdk.requests[0][1]))
            path = cache._pack_path(PACK.version, cache._pack_identity({}, second, pack=PACK.version, role_context=None, topic_context=context(second)))
            data = json.loads(path.read_text())
            data["answer"]["leaf_answer"]["probabilities"]["trust"] = float("nan")
            path.write_text(json.dumps(data))
            assess([second])
            self.assertEqual(2, len(sdk.requests))
            assess([second])
            self.assertEqual(2, len(sdk.requests))
            changed = block(1, "Give money today.")
            assess([changed])
            self.assertEqual(3, len(sdk.requests))

    def test_changed_model_or_context_invalidates_only_directive_pack(self):
        sdk = Sdk()
        with tempfile.TemporaryDirectory() as directory:
            b = block()
            for model, leading in (("jev-1.13.0", ""), ("different-model", ""),
                                   ("jev-1.13.0", "Clarification")):
                cache = TypeSafeBlockCache(Path(directory), model=model)
                c = TopicBlockContext(target_text=b.text, leading_context=leading,
                                      trailing_context="", diagnostics={})
                cache.assess_packs(adapter(sdk), {}, [b], requested_packs=frozenset({PACK.version}),
                                   topic_contexts={b.block_id: c})
            self.assertEqual(3, len(sdk.requests))
            cache = TypeSafeBlockCache(Path(directory), model="jev-1.13.0")
            with self.assertRaisesRegex(ValueError, "target differs"):
                cache.assess_packs(adapter(sdk), {}, [b], requested_packs=frozenset({PACK.version}),
                                   topic_contexts={b.block_id: context(block(text="Other text"))})
            self.assertEqual(3, len(sdk.requests))

    def test_rejects_malformed_provider_answer_without_caching(self):
        class BadSdk(Sdk):
            def system_one(self, state, questions, **kwargs):
                result = super().system_one(state, questions, **kwargs)
                next(iter(result.nouls.values())).noul = float("nan")
                return result
        with tempfile.TemporaryDirectory() as directory:
            cache = TypeSafeBlockCache(Path(directory), model="jev-1.13.0")
            b = block()
            with self.assertRaisesRegex(ValueError, "malformed answer pack"):
                cache.assess_packs(adapter(BadSdk()), {}, [b], requested_packs=frozenset({PACK.version}),
                                   topic_contexts={b.block_id: context(b)})
            self.assertEqual([], list(Path(directory).rglob("*.json")))

    def test_refinement_preserves_eight_questions_and_original_baseline(self):
        from pastor_transcript_extractor.sermon_leaf_packs import (
            LISTENER_DIRECTIVES_V2, LISTENER_DIRECTIVE_REFINEMENT, REVISED_DIRECTIVE_LEAVES,
        )
        baseline = json.loads(DEFAULT_BASELINE_INPUT.read_text())
        identity = {k: v for k, v in baseline.items() if k != "input_fingerprint"}
        self.assertEqual(BASELINE_REVIEW_FINGERPRINT, fingerprint(identity))
        self.assertEqual(baseline["question_pack_digest"], LISTENER_DIRECTIVES_V2.digest())
        self.assertEqual(1, len(LISTENER_DIRECTIVE_REFINEMENT.questions(0)))
        for leaf in PACK.definitions:
            qid = PACK.question_id(0, leaf)
            if leaf in REVISED_DIRECTIVE_LEAVES:
                self.assertNotEqual(PACK.questions(0)[qid], LISTENER_DIRECTIVES_V2.questions(0)[qid])
            else:
                self.assertEqual(PACK.questions(0)[qid], LISTENER_DIRECTIVES_V2.questions(0)[qid])

    def test_refinement_asks_only_serve_and_composed_nine_replay_in_shared_cache(self):
        from pastor_transcript_extractor.sermon_leaf_packs import LISTENER_DIRECTIVES_V2, LISTENER_DIRECTIVE_REFINEMENT
        with tempfile.TemporaryDirectory() as directory:
            b = block()
            ctx = {**context(b).state_payload(), "diagnostics": {}}
            baseline_leaf = {"version": LISTENER_DIRECTIVES_V2.version,
                             "probabilities": {k: .21 for k in PACK.definitions}, "context": ctx}
            case = {"video_id": "contract-probes", "block_id": 0, "target_text": b.text, "segment_indexes": [0],
                    "start_seconds": 0., "end_seconds": 60., "leading_context": "", "trailing_context": "",
                    "context_diagnostics": {}, "cache_dir": directory, "review_stratum": "probe",
                    "expected_positive_leaves": ["trust"], "baseline_leaf_answer": baseline_leaf,
                    "baseline_request_provenance": {"original_request": "v1"},
                    "baseline_resolved_model_id": "jev-1.13.0"}
            packet = {"question_pack_digest": PACK.digest(), "requested_model_id": "jev-1.13.0",
                      "inference_pack_version": LISTENER_DIRECTIVE_REFINEMENT.version,
                      "cases": [case], "sources": []}
            packet["input_fingerprint"] = fingerprint(packet)
            sdk = Sdk()
            result, execution = evaluate_review(packet, client=adapter(sdk))
            self.assertEqual(1, execution["provider_requests"])
            self.assertEqual(1, len(sdk.requests[0][1]))
            answer = result["cases"][0]["leaf_answer"]
            for leaf in PACK.definitions:
                self.assertEqual(.8 if leaf == "serve" else .21,
                                 answer["probabilities"][leaf])
            repeated, execution = evaluate_review(packet, client=adapter(sdk))
            self.assertEqual(result, repeated)
            self.assertEqual(0, execution["provider_requests"])
            cache = TypeSafeBlockCache(Path(directory), model="jev-1.13.0")
            full = cache.assess_packs(adapter(sdk), {}, [b], requested_packs=frozenset({PACK.version}),
                                     topic_contexts={b.block_id: context(b)})
            self.assertEqual(0, cache.provider_requests)
            self.assertEqual(answer, full[0].leaf_answers[PACK.version])
            with self.assertRaisesRegex(ValueError, "semantics differ"):
                cache.compose_leaf_answer(b, pack=PACK.version, topic_context=context(b),
                    sources={leaf: (LISTENER_DIRECTIVES_V2.version, TypeSafeBlockAnswer(
                        choice="unclear", probabilities={}, confidence=None, resolved_model_id="jev-1.13.0",
                        leaf_answers={LISTENER_DIRECTIVES_V2.version: baseline_leaf})) for leaf in PACK.definitions})

    def test_refinement_preparation_rejects_changed_case_evidence(self):
        from copy import deepcopy
        baseline = json.loads(DEFAULT_BASELINE_INPUT.read_text())
        prepared = {**baseline, "question_pack_version": PACK.version,
                    "question_pack_digest": PACK.digest(), "status": "prepared_pending_evaluation"}
        prepared["cases"] = [{k: v for k, v in c.items() if k not in (
            "leaf_answer", "request_provenance", "resolved_model_id", "provisional_display_leaves", "probe_matches_proposal")}
            for c in baseline["cases"]]
        module = "pastor_transcript_extractor.sermon_listener_directive_review"
        with patch(module + ".prepare_review", return_value=deepcopy(prepared)):
            packet = prepare_refinement_review(None, model="jev-1.13.0", probe_cache=Path("unused"))
        self.assertEqual(36, len(packet["cases"]))
        self.assertEqual("pass", packet["stage_gate"]["router"])
        self.assertEqual(8, len(packet["unchanged_leaves"]))
        changed = deepcopy(prepared)
        changed["cases"][0]["target_text"] = "Changed evidence"
        with patch(module + ".prepare_review", return_value=changed):
            with self.assertRaisesRegex(ValueError, "evidence changed"):
                prepare_refinement_review(None, model="jev-1.13.0", probe_cache=Path("unused"))

    def test_overlapping_versions_cannot_overwrite_provider_questions(self):
        from pastor_transcript_extractor.sermon_leaf_packs import LISTENER_DIRECTIVE_REFINEMENT
        sdk = Sdk()
        b = block()
        with self.assertRaisesRegex(ValueError, "Overlapping leaf question IDs"):
            adapter(sdk).assess_blocks({}, [b],
                requested_packs=frozenset({PACK.version, LISTENER_DIRECTIVE_REFINEMENT.version}),
                topic_contexts={b.block_id: context(b)})
        self.assertEqual([], sdk.requests)

    def test_bounded_selection_includes_no_cue_and_outside_salvation(self):
        candidates = [{"block_id": i, "target_text": "Trust and pray" if i % 2 else "Story description",
                       "salvation_support": 0.1 if i < 6 else 0.8,
                       "projection_eligibility": {"eligible": i != 1}} for i in range(10)]
        cases = select_cases(candidates)
        self.assertLessEqual(len(cases), 4)
        self.assertEqual(len(cases), len({c["block_id"] for c in cases}))
        self.assertIn("no_cue", [c["review_stratum"] for c in cases])
        self.assertTrue(all(c["block_id"] != 1 for c in cases))
        self.assertLess(next(c for c in cases if c["review_stratum"] == "outside_salvation")["salvation_support"], 0.55)

    def test_probes_cover_all_leaves_negatives_and_overlap(self):
        probes = json.loads(PROBE_PATH.read_text())
        self.assertEqual(set(PACK.definitions), {leaf for p in probes for leaf in p["expected_positive_leaves"]})
        self.assertTrue(any(not p["expected_positive_leaves"] for p in probes))
        self.assertTrue(any(len(p["expected_positive_leaves"]) > 1 for p in probes))
        self.assertTrue(any(p.get("leading_context") for p in probes))

    def test_preparation_is_bounded_provider_free_and_keeps_exclusions(self):
        from pastor_transcript_extractor.sermon_topics import TOPICS, TOPIC_PACK_VERSION
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "classification.json"
            source.write_text("cached evidence")
            scores = {key: {"score": 0., "confidence": 1.,
                            "probabilities": {str(i): float(i == 0) for i in range(5)}}
                      for key in TOPICS}
            raw = [{"block_id": i, "segment_indexes": [i], "start_seconds": i * 60.,
                    "end_seconds": (i + 1) * 60., "scores": scores,
                    "projection_eligibility": {"eligible": i != 2},
                    "context": {"target_text": "Pray today" if i == 0 else "A narrative",
                                "leading_context": "", "trailing_context": "", "diagnostics": {}}}
                   for i in range(3)]
            class Database:
                database_path = source
                def get_video_by_id(self, video_id):
                    return SimpleNamespace(id=video_id, title="Prepared sermon")
            gate = SimpleNamespace(eligible=True, source_path=source, topic_analysis_fingerprint="frozen")
            module = "pastor_transcript_extractor.sermon_listener_directive_review"
            with patch(module + ".assess_topic_profile_projection", return_value=gate), \
                 patch(module + ".read_topic_analysis_for_gate", return_value=({
                     "question_pack_version": TOPIC_PACK_VERSION, "blocks": raw}, {})), \
                 patch(module + ".resolve_topic_block_context", side_effect=lambda b: b["context"]):
                packet = prepare_review(Database(), model="jev-1.13.0", probe_cache=Path(directory))
            natural = [c for c in packet["cases"] if isinstance(c["video_id"], int)]
            self.assertLessEqual(len(natural), 12)
            self.assertEqual(3, len(packet["excluded_content_controls"]))
            self.assertEqual("none", packet["analytical_credit"])
            self.assertTrue(all(c["route"]["route"] for c in natural))
            source.write_text("changed evidence")
            with self.assertRaisesRegex(ValueError, "Source changed"):
                evaluate_review(packet, client=adapter(Sdk()))

    def test_packet_replay_repairs_output_and_applies_no_production_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            case = {"video_id": "probe", "block_id": 0, "target_text": "Trust Jesus.", "segment_indexes": [0],
                    "start_seconds": 0., "end_seconds": 60., "leading_context": "", "trailing_context": "",
                    "context_diagnostics": {}, "cache_dir": directory, "review_stratum": "probe",
                    "expected_positive_leaves": ["trust"]}
            packet = {"question_pack_digest": PACK.digest(), "requested_model_id": "jev-1.13.0",
                      "cases": [case], "excluded_content_controls": [], "sources": [],
                      "proposed_decision": "pending", "sampling_limit": "bounded", "observation_policy": "raw only"}
            packet["input_fingerprint"] = fingerprint(packet)
            sdk = Sdk()
            result, execution = evaluate_review(packet, client=adapter(sdk))
            self.assertEqual(1, execution["provider_requests"])
            repeated, execution = evaluate_review(packet, client=adapter(sdk))
            self.assertEqual(0, execution["provider_requests"])
            self.assertEqual(result, repeated)
            self.assertFalse(result["cases"][0]["probe_matches_proposal"])
            adjusted = {**packet, "review_display_threshold": 0.95}
            adjusted.pop("input_fingerprint")
            adjusted["input_fingerprint"] = fingerprint(adjusted)
            adjusted_result, adjusted_execution = evaluate_review(adjusted, client=adapter(sdk))
            self.assertEqual(0, adjusted_execution["provider_requests"])
            self.assertEqual([], adjusted_result["cases"][0]["provisional_display_leaves"])
            output = Path(directory) / "review.json"
            self.assertFalse(write_review(output, result)[2])
            self.assertTrue(write_review(output, result)[2])
            output.with_suffix(".md").write_text("corrupt")
            self.assertFalse(write_review(output, result)[2])


if __name__ == "__main__":
    unittest.main()
