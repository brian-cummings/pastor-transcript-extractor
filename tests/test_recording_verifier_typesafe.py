from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor.recording_verifier_typesafe import (
    CHOICES,
    TypeSafeRecordingPolicy,
    TypeSafeAnswers,
    TypeSafeCache,
    TypeSafeCase,
    TypeSafeRecordingState,
    TypeSafeSdkAdapter,
    TypeSafeProductionRecordingVerifier,
    _target_block_state,
    _percentile,
    build_typesafe_state,
    disagreement_sets,
    question_inventory,
    run_benchmark,
    write_reports,
)
from pastor_transcript_extractor.sermon_classification import TranscriptBlock
from pastor_transcript_extractor.sermon_classifier_typesafe import (
    FINE_PARENT_CONTEXT_KEY,
)


def proposed() -> dict[str, object]:
    return {
        "classification": {"search": {"selected_rank": 1, "candidates": [{"rank": 1, "start_seconds": 150.0, "end_seconds": 450.0}]}},
        "segments": [{"start_seconds": float(i * 30), "end_seconds": float((i + 1) * 30), "text": f"segment {i}"} for i in range(20)],
    }


class FakeClient:
    def __init__(self, answers: TypeSafeAnswers) -> None:
        self.answers, self.calls = answers, 0
    def assess(self, state: TypeSafeRecordingState) -> TypeSafeAnswers:
        del state; self.calls += 1; return self.answers


class FailingClient:
    def assess(self, state: TypeSafeRecordingState) -> TypeSafeAnswers:
        del state
        raise RuntimeError("service unavailable")


def answers(
    choice: str = "worship_service_sermon",
    *,
    probability: float = .9,
    confidence: float = .8,
) -> TypeSafeAnswers:
    probabilities = {key: 0.0 for key in CHOICES}
    probabilities[choice] = probability
    return TypeSafeAnswers(choice, probabilities, confidence, "jev-1.13.0", 17, 4)


class TypeSafeRecordingVerifierTests(unittest.TestCase):
    def test_target_block_state_attaches_matching_coarse_parent_finding(self) -> None:
        block = TranscriptBlock(12, [3], 60.0, 120.0, "minute transcript")
        parent = {
            "policy": "advisory",
            "coarse_findings": [{"block_id": 2, "selected_role": "principal_sermon"}],
        }

        state = _target_block_state(
            {FINE_PARENT_CONTEXT_KEY: {"12": parent, "13": {"stale": True}}},
            block,
        )

        self.assertEqual(parent, state["coarse_parent_finding"])
        self.assertNotIn("stale", state["coarse_parent_finding"])

    def test_percentile_uses_nearest_rank_for_small_samples(self) -> None:
        self.assertEqual(232.727, _percentile([227.692, 232.727], .95))

    def test_state_reuses_existing_sampling_boundaries(self) -> None:
        state = build_typesafe_state("Sabbath School & Church", proposed())
        self.assertEqual("Sabbath School & Church", state.recording_title)
        self.assertIn("segment", state.candidate_opening)
        judgment = state.judgment_payload()
        self.assertEqual({"recording_title", "candidate"}, set(judgment))
        self.assertEqual({"opening", "middle", "ending"}, set(judgment["candidate"]))

    def test_question_inventory_is_one_bounded_choice_with_explicit_boundaries(self) -> None:
        inventory = question_inventory()
        self.assertEqual({"recording_type"}, set(inventory))
        self.assertEqual(set(CHOICES), set(inventory["recording_type"]["criteria"]))
        sermon = inventory["recording_type"]["criteria"]["worship_service_sermon"]
        education = inventory["recording_type"]["criteria"]["religious_education_or_bible_class"]
        self.assertIn("principal worship-service sermon", sermon["choose_when"])
        self.assertIn("brief congregational answers", sermon["still_choose_when"])
        self.assertIn("substantive participant contributions", education["choose_when"])
        self.assertIn("suggesting a practical exercise", education["do_not_choose_when"])
        self.assertIn("children's story", inventory["recording_type"]["criteria"]["childrens_story_or_interactive_object_lesson"])
        self.assertIn("do not turn", inventory["recording_type"]["criteria"]["childrens_story_or_interactive_object_lesson"])
        self.assertIn("do not contain enough evidence", inventory["recording_type"]["criteria"]["unclear"])

    def test_policy_accepts_high_confidence_choice_and_maps_non_sermon_types(self) -> None:
        policy = TypeSafeRecordingPolicy()
        self.assertEqual("sermon", policy.decide("worship_service_sermon", {"worship_service_sermon": .85}, .75)[0])
        self.assertEqual(
            "no_sermon",
            policy.decide(
                "childrens_story_or_interactive_object_lesson",
                {"childrens_story_or_interactive_object_lesson": .9},
                .8,
            )[0],
        )

    def test_policy_abstains_on_unclear_low_confidence_and_bad_response(self) -> None:
        policy = TypeSafeRecordingPolicy()
        self.assertEqual("abstain", policy.decide("unclear", {"unclear": .95}, .9)[0])
        self.assertEqual("abstain", policy.decide("worship_service_sermon", {"worship_service_sermon": .84}, .9)[0])
        self.assertEqual("abstain", policy.decide("worship_service_sermon", {"worship_service_sermon": .9}, .74)[0])
        self.assertEqual("abstain", policy.decide("not_a_choice", {}, .9)[0])

    def test_production_verifier_emits_existing_artifact_contract(self) -> None:
        client = FakeClient(answers())
        verifier = TypeSafeProductionRecordingVerifier(
            model="jev-1.13.0",
            client=client,
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact = verifier.verify(
                title="A Believing Mother",
                proposed=proposed(),
                cache_dir=Path(tmp),
            )
            cached = verifier.verify(
                title="A Believing Mother",
                proposed=proposed(),
                cache_dir=Path(tmp),
            )
        self.assertEqual("typesafe_recording_verifier", artifact["source"])
        self.assertEqual("worship_service_sermon", artifact["decision"])
        self.assertEqual("sermon", artifact["predicted_outcome"])
        self.assertEqual("high", artifact["confidence"])
        self.assertIn("single_sustained_message", artifact["reason_codes"])
        self.assertEqual("worship_service_sermon", artifact["model_verdict"]["choice"])
        self.assertFalse(artifact["cache_hit"])
        self.assertTrue(cached["cache_hit"])
        self.assertEqual(1, client.calls)

    def test_production_verifier_reuses_compatible_local_artifact(self) -> None:
        client = FakeClient(answers())
        verifier = TypeSafeProductionRecordingVerifier(model="jev-1.13.0", client=client)
        with tempfile.TemporaryDirectory() as tmp:
            artifact = verifier.verify(
                title="A Believing Mother",
                proposed=proposed(),
                cache_dir=Path(tmp),
            )

        cached = verifier.reuse_local_artifact(
            title="A Believing Mother",
            proposed=proposed(),
            artifact=artifact,
        )

        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertTrue(cached["cache_hit"])
        self.assertEqual(1, client.calls)

    def test_local_artifact_requires_matching_state_and_policy(self) -> None:
        verifier = TypeSafeProductionRecordingVerifier(model="jev-1.13.0", client=FakeClient(answers()))
        artifact = {
            "source": "typesafe_recording_verifier",
            "model_digest": "jev-1.13.0",
            "prompt_version": verifier.prompt_version,
            "policy_version": verifier.policy_version,
            "evidence_packet_hash": "stale",
            "error": None,
        }

        self.assertIsNone(
            verifier.reuse_local_artifact(
                title="A Believing Mother", proposed=proposed(), artifact=artifact
            )
        )

    def test_production_verifier_maps_childrens_story_to_no_sermon(self) -> None:
        verifier = TypeSafeProductionRecordingVerifier(
            model="jev-1.13.0",
            client=FakeClient(
                answers(
                    "childrens_story_or_interactive_object_lesson",
                    probability=.98,
                    confidence=.97,
                )
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact = verifier.verify(
                title="Children's Story",
                proposed=proposed(),
                cache_dir=Path(tmp),
            )
        self.assertEqual("non_sermon_event", artifact["decision"])
        self.assertEqual("no_sermon", artifact["predicted_outcome"])
        self.assertIn(
            "childrens_story_or_interactive_object_lesson",
            artifact["reason_codes"],
        )

    def test_production_verifier_fails_closed(self) -> None:
        verifier = TypeSafeProductionRecordingVerifier(
            model="jev-1.13.0",
            client=FailingClient(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact = verifier.verify(
                title="Ambiguous service",
                proposed=proposed(),
                cache_dir=Path(tmp),
            )
        self.assertEqual("unresolved", artifact["source"])
        self.assertEqual("unclear", artifact["decision"])
        self.assertIsNone(artifact["predicted_outcome"])
        self.assertIn("service unavailable", artifact["error"])

    def test_title_gate_overrides_choice(self) -> None:
        policy = TypeSafeRecordingPolicy()
        self.assertEqual(
            "no_sermon",
            policy.decide(
                "worship_service_sermon",
                {"worship_service_sermon": .99},
                .99,
                title_gate="non_sermon_event",
            )[0],
        )
        state = TypeSafeRecordingState("Title", "b", "c", "d")
        client = FakeClient(answers())
        case = TypeSafeCase("x", "Title", "sermon", "development", state, None)
        with tempfile.TemporaryDirectory() as tmp:
            run = run_benchmark([case], client, model="jev-1.13.0", cache=TypeSafeCache(Path(tmp)))
        self.assertEqual("sermon", run["results"][0]["jev_policy_verdict"])

    def test_cache_reuses_exact_state_and_question_identity(self) -> None:
        state = TypeSafeRecordingState("Title", "b", "c", "d")
        client = FakeClient(answers())
        with tempfile.TemporaryDirectory() as tmp:
            cache = TypeSafeCache(Path(tmp))
            _, hit1, key1 = cache.get_or_assess(client, state, "jev-1.13.0")
            _, hit2, key2 = cache.get_or_assess(client, state, "jev-1.13.0")
        self.assertFalse(hit1); self.assertTrue(hit2); self.assertEqual(key1, key2); self.assertEqual(1, client.calls)

    def test_missing_key_and_dependency_are_actionable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "TYPESAFE_API_KEY"):
                TypeSafeSdkAdapter(model="jev-1.13.0")
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test"}, clear=True):
            with patch("builtins.__import__", side_effect=ImportError("no sdk")):
                with self.assertRaisesRegex(RuntimeError, "optional dependency"):
                    TypeSafeSdkAdapter(model="jev-1.13.0")

    def test_reports_and_disagreement_extraction(self) -> None:
        state = TypeSafeRecordingState("Title", "b", "c", "d")
        client = FakeClient(answers())
        case = TypeSafeCase("x", "Title", "no_sermon", "development", state, {"predicted_outcome": "no_sermon"})
        with tempfile.TemporaryDirectory() as tmp:
            run = run_benchmark([case], client, model="jev-1.13.0", cache=TypeSafeCache(Path(tmp) / "cache"))
            json_path, markdown_path = write_reports(run, Path(tmp) / "reports")
            self.assertTrue(json_path.exists()); self.assertTrue(markdown_path.exists())
        self.assertEqual(["x"], disagreement_sets(run["results"])["incorrect_automatic"])
        self.assertEqual(["x"], disagreement_sets(run["results"])["jev_vs_12b"])
        self.assertFalse(run["production_artifacts_modified"])
        self.assertIsNone(run["summary"]["existing_12b"]["input_tokens"])

    def test_held_out_cli_requires_frozen_policy_confirmation_before_sdk_setup(self) -> None:
        from pastor_transcript_extractor.cli import app

        result = CliRunner().invoke(
            app,
            ["benchmark", "recording-verifier-typesafe", "--partition", "held_out", "--output-dir", "unused"],
        )
        self.assertNotEqual(0, result.exit_code)
        self.assertIn("requires confirmation", result.output)


if __name__ == "__main__":
    unittest.main()
