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
    style_proposal_schema,
    validate_style_proposals,
)
from pastor_transcript_extractor.style_evaluation import evaluate_style_model
from pastor_transcript_extractor.style_profile_analysis import (
    build_profile_style_analysis,
)
from pastor_transcript_extractor.style_review import (
    create_style_review_packet,
    evaluate_style_boundaries,
    finalize_style_review,
)


def style_proposal(
    dimension: str,
    support_start: str,
    support_end: str,
    *,
    run_start: str | None = None,
    run_end: str | None = None,
) -> dict[str, object]:
    return {
        "dimension": dimension,
        "run_start_segment_id": run_start or support_start,
        "run_end_segment_id": run_end or support_end,
        "support_start_segment_id": support_start,
        "support_end_segment_id": support_end,
    }


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
            style_proposal(dimension, "S000000", "S000000")
            for dimension in dimensions
        ]
        content = {"proposals": proposals}
        return LocalLlmResponse(content, json.dumps(content), self.model)


class BoundaryContinuationClient:
    model = "fixture-continuation:1"

    def generate_json(
        self,
        prompt: str,
        schema: dict[str, object],
        *,
        max_tokens: int = 256,
    ) -> LocalLlmResponse:
        item_properties = schema["properties"]["proposals"]["items"]["properties"]
        ids = item_properties["run_start_segment_id"]["enum"]
        content = {
            "proposals": [
                style_proposal(
                    "doctrinal_argument",
                    ids[0],
                    ids[-1],
                    run_start=ids[0],
                    run_end=ids[-1],
                )
            ]
        }
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

        style_schema = style_proposal_schema(
            SemanticBlock(
                0,
                (SemanticSegment(0, "Grounded transcript text.", 0.0, 5.0),),
            )
        )
        self.assertEqual(4, style_schema["properties"]["proposals"]["maxItems"])

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
                    style_proposal(
                        "exegetical_exposition", "S000000", "S000000"
                    ),
                    style_proposal("doctrinal_argument", "S000000", "S000000"),
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
                    style_proposal("practical_application", "S000000", "S000000")
                ]
            },
            application,
        )

        self.assertEqual(0, len(rejected.accepted))
        self.assertEqual(2, rejected.rejection_counts["failed_dimension_acceptance_gate"])
        self.assertEqual(1, len(accepted.accepted))

    def test_style_support_must_be_inside_candidate_run(self) -> None:
        block = SemanticBlock(
            0,
            (
                SemanticSegment(
                    0,
                    "This week call your neighbor, listen carefully, and ask forgiveness for the harm.",
                    0.0,
                    15.0,
                ),
                SemanticSegment(
                    1,
                    "Continue with another sufficiently long transcript segment for boundary validation.",
                    15.0,
                    30.0,
                ),
            ),
        )
        result = validate_style_proposals(
            {
                "proposals": [
                    style_proposal(
                        "practical_application",
                        "S000000",
                        "S000000",
                        run_start="S000001",
                        run_end="S000001",
                    )
                ]
            },
            block,
        )

        self.assertFalse(result.accepted)
        self.assertEqual(1, result.rejection_counts["support_outside_run"])


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
                style_proposal(
                    "exegetical_exposition", "S000000", "S000000"
                ),
                style_proposal("doctrinal_argument", "S000000", "S000000"),
                style_proposal("practical_application", "S000001", "S000001"),
                style_proposal("practical_application", "S999999", "S999999"),
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
        self.assertEqual([512], client.max_token_budgets)
        values = self._values(first.run.id)
        self.assertEqual(4, values["model_proposal_count"])
        self.assertEqual(3, values["semantic_evidence_count"])
        self.assertEqual(1, values["rejected_proposal_count"])
        evidence = self.database.list_sermon_analysis_evidence(first.run.id)
        self.assertEqual(6, len(evidence))
        self.assertEqual(
            {"semantic_style_evidence", "semantic_style_run"},
            {item.evidence_kind for item in evidence},
        )
        payloads = [
            json.loads(item.payload_json)
            for item in evidence
            if item.evidence_kind == "semantic_style_evidence"
        ]
        exegetical = next(
            item for item in payloads if item["dimension"] == "exegetical_exposition"
        )
        self.assertTrue(exegetical["scripture_corroborated"])
        self.assertEqual("digest-a", exegetical["model_provenance"]["model_digest"])
        self.assertNotIn("model_quote", exegetical)

    def test_model_change_invalidates_sermon_and_profile_derivations(self) -> None:
        client = FakeStyleClient(
            [
                style_proposal("practical_application", "S000001", "S000001")
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
        self.assertEqual(30.0, practical["accepted_evidence_duration_seconds"])
        self.assertEqual(1, practical["candidate_style_run_count"])
        self.assertEqual("unreviewed", practical["candidate_style_run_boundary_status"])

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
        self.assertIn("unreviewed model boundaries", profile_show.output)

    def test_boundary_touching_adjacent_blocks_form_one_candidate_run(self) -> None:
        payload = {
            "sermon_window": {
                "start_seconds": 0.0,
                "end_seconds": 160.0,
                "included_segment_indexes": [0, 1, 2, 3],
            },
            "segments": [
                {
                    "start_seconds": index * 40.0,
                    "end_seconds": (index + 1) * 40.0,
                    "text": (
                        "Because God gives grace through Christ, therefore salvation cannot "
                        "depend upon our merit or religious achievement alone."
                    ),
                }
                for index in range(4)
            ],
        }
        path = self.root / "continuation.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.database.add_extraction_result(
            video_id=self.video.id,
            version=2,
            proposed_text_path=str(self.root / "continuation.md"),
            proposed_json_path=str(path),
        )
        analyze_sermon(self.database, self.video)

        outcome = analyze_sermon_style(
            self.database,
            self.video,
            BoundaryContinuationClient(),
            model_digest="continuation-digest",
            context_size=4096,
        )
        values = self._values(outcome.run.id)
        runs = [
            item
            for item in self.database.list_sermon_analysis_evidence(outcome.run.id)
            if item.evidence_kind == "semantic_style_run"
        ]

        self.assertEqual(1, len(runs))
        self.assertEqual(0.0, runs[0].start_seconds)
        self.assertEqual(160.0, runs[0].end_seconds)
        doctrine = values["style_dimension_measurements"]["doctrinal_argument"]
        self.assertEqual(1, doctrine["candidate_style_run_count"])
        self.assertEqual(160.0, doctrine["candidate_style_run_duration_seconds"])

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

    def test_full_sermon_review_distinguishes_boundary_error_and_missed_run(self) -> None:
        analyze_sermon_style(
            self.database,
            self.video,
            FakeStyleClient(
                [style_proposal("practical_application", "S000001", "S000001")]
            ),
            model_digest="review-digest",
            context_size=4096,
        )
        draft = self.root / "style-review-draft.json"
        reviewed = self.root / "style-review-reviewed.json"
        payload = create_style_review_packet(
            self.database, self.video, draft
        )

        self.assertEqual(2, len(payload["segments"]))
        self.assertTrue(draft.with_suffix(".md").exists())
        self.assertTrue(payload["scripture_references"])
        candidate = payload["candidate_style_runs"][0]
        candidate["adjudication"] = {
            "judgment": "correct_but_undersized",
            "reviewed_start_segment_id": "S000000",
            "reviewed_end_segment_id": "S000001",
            "notes": "Application begins during the transition.",
        }
        payload["missed_style_runs"] = [
            {
                "dimension": "exegetical_exposition",
                "start_segment_id": "S000000",
                "end_segment_id": "S000000",
                "notes": "Entire interpretive run was missed.",
            }
        ]
        draft.write_text(json.dumps(payload), encoding="utf-8")
        finalized = finalize_style_review(
            draft, reviewed, reviewer="reviewer@example.test"
        )
        result = evaluate_style_boundaries([reviewed])

        self.assertEqual("reviewed", finalized["review_status"])
        self.assertEqual(1, result.overall.matched_run_count)
        self.assertEqual(1, result.overall.missed_run_count)
        self.assertEqual(0.5, result.overall.run_recall)
        self.assertEqual(1.0, result.overall.accepted_duration_precision)
        self.assertEqual(30.0, result.overall.overlapping_duration_seconds)
        self.assertEqual(90.0, result.overall.reviewed_duration_seconds)


if __name__ == "__main__":
    unittest.main()
