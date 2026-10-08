from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.sermon_topic_profile_analysis import (
    TOPIC_PROFILE_ANALYTICAL_STATUS,
    build_profile_topic_analysis,
    materialize_topic_sermon_analysis,
)
from pastor_transcript_extractor.sermon_topics import TOPICS
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
)
from pastor_transcript_extractor.storage import Database


class SermonTopicProfileAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.database = Database(self.root / "app.db")
        self.database.initialize()
        pastor = self.database.add_pastor("topic-pastor", "Topic Pastor")
        self.source = self.database.add_source(
            "https://www.youtube.com/@topic-pastor",
            SourceType.CHANNEL,
            pastor_id=pastor.id,
        )
        self.profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="Reviewed topic profile",
            review_event_key="topic-profile",
        )
        self.videos = []
        self.paths = []
        self._add_video("topic-a", support=0.2, expected=0.4)
        self._add_video("topic-b", support=0.8, expected=0.6)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _payload(
        self,
        *,
        support: float,
        expected: float,
        question_pack: str = "topics-v3-mission-discourse-boundary",
        disposition: str = "accepted_sermon",
    ) -> dict[str, object]:
        scores = {
            topic: {
                "score": round(4 * expected, 6),
                "probabilities": {
                    "0": round(1 - support, 6),
                    "1": 0.0,
                    "2": round(support, 6),
                    "3": 0.0,
                    "4": 0.0,
                },
                "confidence": 0.5,
            }
            for topic in TOPICS
        }
        measurements = {
            topic: {
                "mean_normalized_expected_prominence": expected,
                "mean_supporting_or_above_probability": support,
                "representative_blocks": [
                    {
                        "block_id": 1,
                        "score": round(4 * expected, 6),
                        "supporting_or_above_probability": support,
                    }
                ],
                "counterevidence_blocks": [
                    {
                        "block_id": 1,
                        "score": round(4 * expected, 6),
                        "supporting_or_above_probability": support,
                    }
                ],
            }
            for topic in TOPICS
        }
        topic_analysis = {
            "question_pack_version": question_pack,
            "blocks": [
                {
                    "block_id": 1,
                    "start_seconds": 0.0,
                    "end_seconds": 60.0,
                    "context": {
                        "leading_context": "",
                        "target_text": "A cached sermon topic evidence block.",
                        "trailing_context": "",
                    },
                    "content_role": "principal_sermon",
                    "projection_eligibility": {
                        "eligible": True,
                        "exclusion_reasons": [],
                    },
                    "scores": scores,
                }
            ],
            "sermon_projection": {
                "policy_version": "sermon-topic-full-block-role-density-v1",
                "final_disposition_status": disposition,
                "eligible_block_count": 1,
                "eligible_sermon_seconds": 60.0,
                "measurements": measurements,
            },
        }
        return {
            "final_disposition": {"status": disposition},
            "sermon_window": {
                "start_seconds": 0.0,
                "end_seconds": 60.0,
                "included_segment_indexes": [0],
            },
            "segments": [
                {
                    "start_seconds": 0.0,
                    "end_seconds": 60.0,
                    "text": "A cached sermon topic evidence block.",
                }
            ],
            "classification": {
                "final_disposition": {"status": disposition},
                "search": {"topic_analysis": topic_analysis},
            },
        }

    def _add_video(self, youtube_id: str, *, support: float, expected: float) -> None:
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=None,
            youtube_video_id=youtube_id,
            title=f"Sermon {youtube_id}",
            url=f"https://www.youtube.com/watch?v={youtube_id}",
            status=VideoStatus.EXTRACTED,
        )
        path = self.root / f"{youtube_id}.json"
        path.write_text(
            json.dumps(self._payload(support=support, expected=expected)),
            encoding="utf-8",
        )
        extraction = self.database.add_extraction_result(
            video_id=video.id,
            version=1,
            proposed_text_path=str(path.with_suffix(".md")),
            proposed_json_path=str(path),
        )
        observation = self.database.add_speaker_observation(
            video_id=video.id,
            extraction_result_id=extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="single",
            start_seconds=0.0,
            end_seconds=60.0,
            artifact_path=str(path),
            content_sha256=f"content-{youtube_id}",
            extractor_version="test",
            input_fingerprint=f"observation-{youtube_id}",
        )
        attach_reviewed_observation(
            self.database,
            profile_id=self.profile.id,
            observation_id=observation.id,
            reviewer="reviewer",
            reason="Reviewed same speaker",
            review_event_key=f"attach-{youtube_id}",
        )
        self.videos.append(video)
        self.paths.append(path)

    def _profile_values(self, run_id: int) -> dict[str, object]:
        return {
            item.metric_key: json.loads(item.value_json)
            for item in self.database.list_speaker_profile_analysis_measurements(
                run_id
            )
        }

    def test_sermon_materialization_reuses_exact_topic_analysis(self) -> None:
        first = materialize_topic_sermon_analysis(
            self.database,
            self.videos[0],
        )
        replay = materialize_topic_sermon_analysis(
            self.database,
            self.videos[0],
        )

        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(first.run.id, replay.run.id)
        self.assertEqual(
            2 * len(TOPICS),
            len(self.database.list_sermon_analysis_evidence(first.run.id)),
        )

        payload = json.loads(self.paths[0].read_text(encoding="utf-8"))
        payload["classification"]["search"]["topic_analysis"][
            "sermon_projection"
        ]["measurements"]["discipleship_spiritual_formation"][
            "mean_supporting_or_above_probability"
        ] = 0.3
        self.paths[0].write_text(json.dumps(payload), encoding="utf-8")

        changed = materialize_topic_sermon_analysis(
            self.database,
            self.videos[0],
        )
        self.assertTrue(changed.created)
        self.assertNotEqual(first.run.id, changed.run.id)

    def test_profile_uses_equal_sermon_weighting_and_reuses_both_layers(self) -> None:
        first = build_profile_topic_analysis(self.database, self.profile.id)
        replay = build_profile_topic_analysis(self.database, self.profile.id)

        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(first.run.id, replay.run.id)
        values = self._profile_values(first.run.id)
        self.assertEqual(TOPIC_PROFILE_ANALYTICAL_STATUS, values["analytical_status"])
        self.assertFalse(values["aggregation_policy"]["comparative_use_allowed"])
        self.assertEqual("equal_sermon_mean", values["aggregation_policy"]["estimand"])
        discipleship = values["topic_profiles"][
            "discipleship_spiritual_formation"
        ]
        self.assertEqual(0.5, discipleship["developed_emphasis_probability"])
        self.assertEqual(
            0.5,
            discipleship["normalized_expected_prominence_sensitivity"],
        )
        self.assertEqual(2, discipleship["sermon_count"])
        self.assertEqual(
            2,
            len(
                self.database.list_speaker_profile_analysis_input_run_ids(
                    first.run.id
                )
            ),
        )

    def test_blocked_sermon_is_visible_but_does_not_enter_mean(self) -> None:
        payload = json.loads(self.paths[1].read_text(encoding="utf-8"))
        payload["final_disposition"]["status"] = "review_required"
        payload["classification"]["final_disposition"][
            "status"
        ] = "review_required"
        payload["classification"]["search"]["topic_analysis"][
            "sermon_projection"
        ]["final_disposition_status"] = "review_required"
        self.paths[1].write_text(json.dumps(payload), encoding="utf-8")

        outcome = build_profile_topic_analysis(self.database, self.profile.id)
        values = self._profile_values(outcome.run.id)

        self.assertEqual(2, values["sermons_attached"])
        self.assertEqual(1, values["sermons_analyzed"])
        self.assertEqual(1, values["sermons_blocked"])
        self.assertIn(
            "disposition_not_accepted",
            values["blocked_sermons"][0]["reason_codes"],
        )
        topic = values["topic_profiles"]["discipleship_spiritual_formation"]
        self.assertEqual(0.2, topic["developed_emphasis_probability"])

        payload["final_disposition"]["status"] = "rejected_non_sermon"
        payload["classification"]["final_disposition"][
            "status"
        ] = "rejected_non_sermon"
        payload["classification"]["search"]["topic_analysis"][
            "sermon_projection"
        ]["final_disposition_status"] = "rejected_non_sermon"
        self.paths[1].write_text(json.dumps(payload), encoding="utf-8")
        changed_blocker = build_profile_topic_analysis(
            self.database,
            self.profile.id,
        )
        self.assertTrue(changed_blocker.created)
        self.assertNotEqual(outcome.run.id, changed_blocker.run.id)

    def test_mixed_topic_packs_fail_closed(self) -> None:
        payload = json.loads(self.paths[1].read_text(encoding="utf-8"))
        payload["classification"]["search"]["topic_analysis"][
            "question_pack_version"
        ] = "topics-v2-performed-worship-boundary"
        self.paths[1].write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "mixed question-pack"):
            build_profile_topic_analysis(self.database, self.profile.id)

    def test_cli_materializes_then_reuses_profile_without_provider_work(self) -> None:
        runner = CliRunner()
        arguments = [
            "analysis",
            "topic-summarize-profile",
            "--profile-id",
            str(self.profile.id),
            "--base-dir",
            str(self.root),
        ]

        created = runner.invoke(app, arguments)
        reused = runner.invoke(app, arguments)

        self.assertEqual(0, created.exit_code, msg=created.output)
        self.assertIn("created", created.output)
        self.assertIn("Developed emphasis", created.output)
        self.assertIn("Stage 4 cross-sermon repeatability is pending", created.output)
        self.assertEqual(0, reused.exit_code, msg=reused.output)
        self.assertIn("reused", reused.output)


if __name__ == "__main__":
    unittest.main()
