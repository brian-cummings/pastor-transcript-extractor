from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.local_llm import LocalLlmResponse
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.semantic_evidence import (
    SemanticBlock,
    SemanticSegment,
    semantic_proposal_schema,
    validate_semantic_proposals,
)
from pastor_transcript_extractor.sermon_analysis import analyze_sermon
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.style_analysis import (
    STYLE_ANALYZER_KEY,
    analyze_sermon_style,
    validate_style_proposals,
)
from pastor_transcript_extractor.style_evaluation import evaluate_style_model
from pastor_transcript_extractor.style_profile_analysis import (
    build_profile_style_analysis,
)


class FakeStyleClient:
    model = "fixture-style:1"

    def __init__(self, proposals: list[dict[str, object]]) -> None:
        self.proposals = proposals
        self.calls = 0
        self.max_token_budgets: list[int] = []

    def generate_json(
        self,
        prompt: str,
        schema: dict[str, object],
        *,
        max_tokens: int = 256,
    ) -> LocalLlmResponse:
        self.calls += 1
        self.max_token_budgets.append(max_tokens)
        content = {"proposals": self.proposals}
        return LocalLlmResponse(content, json.dumps(content), self.model)


class FixtureEvaluationClient:
    model = "fixture-evaluation:1"

    def generate_json(
        self,
        prompt: str,
        schema: dict[str, object],
        *,
        max_tokens: int = 256,
    ) -> LocalLlmResponse:
        dimensions = []
        if "connects the command" in prompt:
            dimensions.append("exegetical_exposition")
        if "stranded beside the highway" in prompt:
            dimensions.append("narrative_illustration")
        proposals = [
            {
                "dimension": dimension,
                "start_segment_id": "S000000",
                "end_segment_id": "S000000",
            }
            for dimension in dimensions
        ]
        content = {"proposals": proposals}
        return LocalLlmResponse(content, json.dumps(content), self.model)


class SemanticEvidenceValidationTests(unittest.TestCase):
    def test_proposal_schema_caps_output_to_one_span_per_dimension(self) -> None:
        schema = semantic_proposal_schema(
            ("exegetical_exposition", "practical_application"),
            SemanticBlock(
                0,
                (SemanticSegment(0, "Grounded transcript text.", 0.0, 5.0),),
            ),
        )

        self.assertEqual(2, schema["properties"]["proposals"]["maxItems"])

    def test_rejects_model_invented_ids_reversed_and_short_spans(self) -> None:
        block = SemanticBlock(
            0,
            (
                SemanticSegment(2, "Too short.", 10.0, 12.0),
                SemanticSegment(
                    3,
                    "This transcript segment has enough grounded words to support deterministic validation safely.",
                    12.0,
                    20.0,
                ),
            ),
        )
        result = validate_semantic_proposals(
            {
                "proposals": [
                    {
                        "dimension": "practical_application",
                        "start_segment_id": "S999999",
                        "end_segment_id": "S999999",
                    },
                    {
                        "dimension": "practical_application",
                        "start_segment_id": "S000003",
                        "end_segment_id": "S000002",
                    },
                    {
                        "dimension": "practical_application",
                        "start_segment_id": "S000002",
                        "end_segment_id": "S000002",
                    },
                ]
            },
            block,
            ("practical_application",),
        )

        self.assertEqual(0, len(result.accepted))
        self.assertEqual(1, result.rejection_counts["ungrounded_segment_id"])
        self.assertEqual(1, result.rejection_counts["reversed_span"])
        self.assertEqual(1, result.rejection_counts["span_too_short"])

    def test_style_gate_rejects_quotation_only_and_accepts_concrete_application(self) -> None:
        quotation = SemanticBlock(
            0,
            (
                SemanticSegment(
                    0,
                    "For God so loved the world that he gave his only Son, that whoever believes in him should not perish but have eternal life.",
                    0.0,
                    20.0,
                ),
            ),
        )
        rejected = validate_style_proposals(
            {
                "proposals": [
                    {
                        "dimension": "exegetical_exposition",
                        "start_segment_id": "S000000",
                        "end_segment_id": "S000000",
                    },
                    {
                        "dimension": "doctrinal_argument",
                        "start_segment_id": "S000000",
                        "end_segment_id": "S000000",
                    },
                ]
            },
            quotation,
        )
        application = SemanticBlock(
            0,
            (
                SemanticSegment(
                    0,
                    "This week call the person you avoided, ask forgiveness, and offer one concrete way to repair the harm you caused.",
                    0.0,
                    20.0,
                ),
            ),
        )
        accepted = validate_style_proposals(
            {
                "proposals": [
                    {
                        "dimension": "practical_application",
                        "start_segment_id": "S000000",
                        "end_segment_id": "S000000",
                    }
                ]
            },
            application,
        )

        self.assertEqual(0, len(rejected.accepted))
        self.assertEqual(2, rejected.rejection_counts["failed_dimension_acceptance_gate"])
        self.assertEqual(1, len(accepted.accepted))


class StyleAnalysisPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        paths = build_paths(self.root)
        ensure_directories(paths)
        self.database = Database(paths.database)
        self.database.initialize()
        pastor = self.database.add_pastor("style", "Style Pastor")
        source = self.database.add_source(
            "https://www.youtube.com/@style", SourceType.CHANNEL, pastor_id=pastor.id
        )
        self.video = self.database.add_video(
            source_id=source.id,
            pastor_id=pastor.id,
            youtube_video_id="style123",
            title="Style Sermon",
            url="https://www.youtube.com/watch?v=style123",
            status=VideoStatus.EXTRACTED,
        )
        self.path = self.root / "style.json"
        self.payload = {
            "sermon_window": {
                "start_seconds": 0.0,
                "end_seconds": 60.0,
                "included_segment_indexes": [0, 1],
            },
            "segments": [
                {
                    "start_seconds": 0.0,
                    "end_seconds": 30.0,
                    "text": (
                        "John 3:16 begins with for because the verse explains God's saving "
                        "purpose in the preceding conversation, not an isolated slogan."
                    ),
                },
                {
                    "start_seconds": 30.0,
                    "end_seconds": 60.0,
                    "text": (
                        "This week call the person you have avoided, admit the specific harm, "
                        "ask forgiveness, and offer to repair what you damaged."
                    ),
                },
            ],
        }
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")
        self.extraction = self.database.add_extraction_result(
            video_id=self.video.id,
            version=1,
            proposed_text_path=str(self.root / "style.md"),
            proposed_json_path=str(self.path),
        )
        analyze_sermon(self.database, self.video)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _values(self, run_id: int) -> dict[str, object]:
        return {
            item.metric_key: json.loads(item.value_json)
            for item in self.database.list_sermon_analysis_measurements(run_id)
        }

    def test_persists_validated_overlapping_evidence_and_reuses_unchanged_run(self) -> None:
        client = FakeStyleClient(
            [
                {
                    "dimension": "exegetical_exposition",
                    "start_segment_id": "S000000",
                    "end_segment_id": "S000000",
                },
                {
                    "dimension": "doctrinal_argument",
                    "start_segment_id": "S000000",
                    "end_segment_id": "S000000",
                },
                {
                    "dimension": "practical_application",
                    "start_segment_id": "S000001",
                    "end_segment_id": "S000001",
                },
                {
                    "dimension": "practical_application",
                    "start_segment_id": "S999999",
                    "end_segment_id": "S999999",
                },
            ]
        )
        first = analyze_sermon_style(
            self.database,
            self.video,
            client,
            model_digest="digest-a",
            context_size=4096,
        )
        reused = analyze_sermon_style(
            self.database,
            self.video,
            client,
            model_digest="digest-a",
            context_size=4096,
        )

        self.assertTrue(first.created)
        self.assertFalse(reused.created)
        self.assertEqual(first.run.id, reused.run.id)
        self.assertEqual(1, client.calls)
        self.assertEqual([384], client.max_token_budgets)
        values = self._values(first.run.id)
        self.assertEqual(4, values["model_proposal_count"])
        self.assertEqual(3, values["semantic_evidence_count"])
        self.assertEqual(1, values["rejected_proposal_count"])
        evidence = self.database.list_sermon_analysis_evidence(first.run.id)
        self.assertEqual(3, len(evidence))
        self.assertEqual({"semantic_style_evidence"}, {item.evidence_kind for item in evidence})
        payloads = [json.loads(item.payload_json) for item in evidence]
        exegetical = next(
            item for item in payloads if item["dimension"] == "exegetical_exposition"
        )
        self.assertTrue(exegetical["scripture_corroborated"])
        self.assertEqual("digest-a", exegetical["model_provenance"]["model_digest"])
        self.assertNotIn("model_quote", exegetical)

    def test_model_change_invalidates_sermon_and_profile_derivations(self) -> None:
        client = FakeStyleClient(
            [
                {
                    "dimension": "practical_application",
                    "start_segment_id": "S000001",
                    "end_segment_id": "S000001",
                }
            ]
        )
        first_style = analyze_sermon_style(
            self.database, self.video, client, model_digest="digest-a", context_size=4096
        )
        profile = self.database.ensure_speaker_profile(
            stable_key="person:style",
            display_label="Style Pastor",
            lifecycle_state="active",
            created_reason="test",
        )
        observation = self.database.add_speaker_observation(
            video_id=self.video.id,
            extraction_result_id=self.extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="single",
            start_seconds=0.0,
            end_seconds=60.0,
            artifact_path=str(self.path),
            content_sha256="style-observation",
            extractor_version="test-v1",
            input_fingerprint="style-observation",
        )
        self.database.add_profile_observation_event(
            profile_id=profile.id,
            observation_id=observation.id,
            action="attach",
            reviewer="test",
            reason="verified",
            event_fingerprint="style-attach",
        )
        first_profile = build_profile_style_analysis(self.database, profile.id)
        reused_profile = build_profile_style_analysis(self.database, profile.id)
        second_style = analyze_sermon_style(
            self.database, self.video, client, model_digest="digest-b", context_size=4096
        )
        second_profile = build_profile_style_analysis(self.database, profile.id)

        self.assertFalse(reused_profile.created)
        self.assertNotEqual(first_style.run.id, second_style.run.id)
        self.assertTrue(second_profile.created)
        self.assertNotEqual(first_profile.run.id, second_profile.run.id)
        values = {
            item.metric_key: json.loads(item.value_json)
            for item in self.database.list_speaker_profile_analysis_measurements(
                second_profile.run.id
            )
        }
        practical = values["style_dimension_profiles"]["practical_application"]
        self.assertEqual(1, practical["evidence_count"])
        self.assertEqual(1.0, practical["sermons_with_evidence_fraction"])

        sermon_show = CliRunner().invoke(
            app,
            [
                "analysis",
                "style-show",
                "--youtube-video-id",
                self.video.youtube_video_id,
                "--base-dir",
                str(self.root),
            ],
        )
        self.assertEqual(0, sermon_show.exit_code, msg=sermon_show.output)
        self.assertIn("practical_application", sermon_show.output)
        self.assertIn("digest-b", sermon_show.output)
        profile_show = CliRunner().invoke(
            app,
            [
                "analysis",
                "style-show-profile",
                "--profile-id",
                str(profile.id),
                "--base-dir",
                str(self.root),
            ],
        )
        self.assertEqual(0, profile_show.exit_code, msg=profile_show.output)
        self.assertIn("Evidence-backed Style Dimensions", profile_show.output)

    def test_reviewed_evaluator_counts_overlap_and_negative_control(self) -> None:
        fixture = self.root / "evaluation.json"
        fixture.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "corpus_version": "test-v1",
                    "cases": [
                        {
                            "id": "exegesis",
                            "segments": [
                                "Paul says therefore because it connects the command to grace in the previous chapter."
                            ],
                            "expected_dimensions": ["exegetical_exposition"],
                        },
                        {
                            "id": "narrative",
                            "segments": [
                                "I was stranded beside the highway during a storm, and a stranger drove us home without payment."
                            ],
                            "expected_dimensions": ["narrative_illustration"],
                        },
                        {
                            "id": "negative",
                            "segments": [
                                "The meeting begins after lunch and the printed schedule is beside the main entrance today."
                            ],
                            "expected_dimensions": [],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = evaluate_style_model(
            fixture,
            FixtureEvaluationClient(),
            model_digest="fixture-digest",
        )

        self.assertEqual(1.0, result.overall.precision)
        self.assertEqual(1.0, result.overall.recall)
        self.assertEqual(1, result.overall.true_negative_cases)


if __name__ == "__main__":
    unittest.main()
