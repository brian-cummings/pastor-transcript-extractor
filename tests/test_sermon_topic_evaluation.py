from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.sermon_classifier_typesafe import (
    TOPIC_PACK,
    TypeSafeBlockAnswer,
)
from pastor_transcript_extractor.sermon_topic_evaluation import (
    DEFAULT_TOPIC_BEHAVIOR_FIXTURE,
    REQUIRED_BEHAVIOR_TAGS,
    evaluate_topic_behavior_fixture,
    load_topic_behavior_fixture,
    render_topic_behavior_report,
    write_topic_behavior_report,
)
from pastor_transcript_extractor.sermon_topics import TOPIC_PACK_VERSION, TOPICS


def _distribution(score: float) -> dict[str, float]:
    lower = math.floor(score)
    upper = math.ceil(score)
    probabilities = {str(level): 0.0 for level in range(5)}
    if lower == upper:
        probabilities[str(lower)] = 1.0
    else:
        probabilities[str(lower)] = upper - score
        probabilities[str(upper)] = score - lower
    return probabilities


class FixtureAnswerClient:
    def __init__(self, fixture: dict, *, overrides: dict[tuple[int, str], float] | None = None):
        self.fixture = fixture
        self.overrides = overrides or {}
        self.calls = 0
        self.requested_packs: list[frozenset[str]] = []

    def assess_blocks(
        self,
        recording_context,
        blocks,
        *,
        collect_semantic_analysis=False,
        collect_topic_analysis=False,
        requested_packs=None,
        topic_contexts=None,
    ):
        del recording_context, collect_semantic_analysis, collect_topic_analysis
        self.calls += 1
        self.requested_packs.append(requested_packs)
        answers = {}
        for block in blocks:
            case = self.fixture["cases"][block.block_id - 1]
            scores = {}
            for topic in TOPICS:
                expectation = case["expectations"].get(topic)
                score = (
                    (
                        float(expectation["minimum_score"])
                        + float(expectation["maximum_score"])
                    )
                    / 2.0
                    if expectation is not None
                    else 0.0
                )
                score = self.overrides.get((block.block_id, topic), score)
                scores[topic] = {
                    "score": score,
                    "probabilities": _distribution(score),
                    "confidence": 0.9,
                }
            answers[block.block_id] = TypeSafeBlockAnswer(
                choice="unclear",
                probabilities={},
                confidence=None,
                resolved_model_id="jev-1.13.0",
                topic_scores=scores,
                topic_question_version=TOPIC_PACK_VERSION,
                topic_context={
                    **topic_contexts[block.block_id].state_payload(),
                    "diagnostics": dict(topic_contexts[block.block_id].diagnostics),
                },
                request_provenance={
                    "request_key": f"fixture-request-{self.calls}",
                    "requested_packs": [TOPIC_PACK],
                },
            )
        return answers


class SermonTopicEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_path = Path(__file__).parents[1] / DEFAULT_TOPIC_BEHAVIOR_FIXTURE
        cls.fixture = load_topic_behavior_fixture(cls.fixture_path)

    def test_frozen_fixture_covers_the_complete_stage_one_contract(self) -> None:
        observed_tags = {
            tag for case in self.fixture["cases"] for tag in case["tags"]
        }

        self.assertEqual(REQUIRED_BEHAVIOR_TAGS, observed_tags & REQUIRED_BEHAVIOR_TAGS)
        self.assertEqual(21, len(self.fixture["cases"]))
        self.assertEqual(
            {"prominence_absent", "performed_lyrics", "spiritual_conflict_positive"},
            {
                tag
                for tag in (
                    "prominence_absent",
                    "performed_lyrics",
                    "spiritual_conflict_positive",
                )
                if tag in observed_tags
            },
        )

    def test_evaluator_preserves_distributions_and_reuses_topic_pack_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            first_client = FixtureAnswerClient(self.fixture)
            first = evaluate_topic_behavior_fixture(
                self.fixture,
                cache_dir=cache_dir,
                model="jev-1.13.0",
                client=first_client,
            )
            replay_client = FixtureAnswerClient(self.fixture)
            replay = evaluate_topic_behavior_fixture(
                self.fixture,
                cache_dir=cache_dir,
                model="jev-1.13.0",
                client=replay_client,
            )
            output = Path(tmp) / "replay-report.json"
            first_write = write_topic_behavior_report(output, first)
            replay_write = write_topic_behavior_report(output, replay)

        self.assertEqual("passed", first["status"])
        self.assertEqual(41, first["summary"]["passed_expectations"])
        self.assertEqual(21, first["execution"]["cache_misses"])
        self.assertEqual(4, first["execution"]["provider_requests"])
        self.assertEqual(0, replay["execution"]["cache_misses"])
        self.assertEqual(21, replay["execution"]["cache_hits"])
        self.assertEqual(0, replay["execution"]["provider_requests"])
        self.assertEqual(0, replay_client.calls)
        self.assertEqual(first["result_fingerprint"], replay["result_fingerprint"])
        self.assertFalse(first_write[2])
        self.assertTrue(replay_write[2])
        self.assertEqual(
            {str(level) for level in range(5)},
            set(first["cases"][0]["scores"]["salvation_gospel"]["probabilities"]),
        )
        self.assertEqual(
            {frozenset({TOPIC_PACK})},
            set(first_client.requested_packs),
        )

    def test_evaluator_reports_range_failure_without_using_confidence(self) -> None:
        client = FixtureAnswerClient(
            self.fixture,
            overrides={(1, "salvation_gospel"): 4.0},
        )
        with tempfile.TemporaryDirectory() as tmp:
            report = evaluate_topic_behavior_fixture(
                self.fixture,
                cache_dir=Path(tmp) / "cache",
                model="jev-1.13.0",
                client=client,
            )

        self.assertEqual("failed", report["status"])
        self.assertEqual(1, report["summary"]["failed_expectations"])
        failed = report["cases"][0]["checks"][0]
        self.assertFalse(failed["passed"])
        self.assertEqual(0.9, report["cases"][0]["scores"]["salvation_gospel"]["confidence"])
        self.assertIn("never used", report["interpretation_contract"]["confidence"])

    def test_report_writer_is_content_addressed_and_repairs_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = evaluate_topic_behavior_fixture(
                self.fixture,
                cache_dir=root / "cache",
                model="jev-1.13.0",
                client=FixtureAnswerClient(self.fixture),
            )
            output = root / "report.json"
            first = write_topic_behavior_report(output, report)
            replay = write_topic_behavior_report(output, report)
            output.with_suffix(".md").write_text("tampered\n", encoding="utf-8")
            repaired = write_topic_behavior_report(output, report)

        self.assertFalse(first[2])
        self.assertTrue(replay[2])
        self.assertFalse(repaired[2])
        markdown = render_topic_behavior_report(report)
        self.assertIn("21/21 passed", markdown)
        self.assertIn("P0", markdown)
        self.assertIn("Confidence", markdown)

    def test_fixture_rejects_question_drift_and_missing_contract_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.json"
            changed = json.loads(self.fixture_path.read_text(encoding="utf-8"))
            changed["question_pack_version"] = "topics-future"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                load_topic_behavior_fixture(path)

            changed["question_pack_version"] = TOPIC_PACK_VERSION
            changed["cases"] = changed["cases"][:-1]
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing contract coverage"):
                load_topic_behavior_fixture(path)

    def test_cli_replays_complete_cache_without_credentials_or_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            evaluate_topic_behavior_fixture(
                self.fixture,
                cache_dir=cache_dir,
                model="jev-1.13.0",
                client=FixtureAnswerClient(self.fixture),
            )
            output = root / "result.json"
            with patch(
                "pastor_transcript_extractor.commands.analysis.content.TypeSafeSdkAdapter",
                side_effect=AssertionError("cached replay must not construct provider"),
            ):
                result = CliRunner().invoke(
                    app,
                    [
                        "analysis",
                        "evaluate-topic-behavior",
                        "--fixture",
                        str(self.fixture_path),
                        "--cache-dir",
                        str(cache_dir),
                        "--output",
                        str(output),
                    ],
                )
            output_written = output.exists()

        self.assertEqual(0, result.exit_code, msg=result.output)
        self.assertIn("provider_requests=0", result.output)
        self.assertTrue(output_written)


if __name__ == "__main__":
    unittest.main()
