from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.profile_analysis import build_profile_scripture_analysis
from pastor_transcript_extractor.sermon_analysis import ANALYZER_KEY, analyze_sermon
from pastor_transcript_extractor.storage import Database


class SermonAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tempdir.name)
        self.paths = build_paths(self.base_dir)
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.pastor = self.database.add_pastor("sample", "Sample Pastor")
        self.source = self.database.add_source(
            "https://www.youtube.com/@sample",
            SourceType.CHANNEL,
            pastor_id=self.pastor.id,
        )
        self.video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=self.pastor.id,
            youtube_video_id="analysis123",
            title="A Test Sermon",
            url="https://www.youtube.com/watch?v=analysis123",
            status=VideoStatus.EXTRACTED,
        )
        self.proposed_path = self.base_dir / "proposed.json"
        self.payload = {
            "sermon_window": {
                "start_seconds": 60.0,
                "end_seconds": 120.0,
                "included_segment_indexes": [1],
            },
            "segments": [
                {
                    "start_seconds": 0.0,
                    "end_seconds": 60.0,
                    "text": "The prelude mentions Genesis 1:1.",
                },
                {
                    "start_seconds": 60.0,
                    "end_seconds": 120.0,
                    "text": (
                        "Today we read John 3:16 and John 3:16-17. "
                        "Romans 8:1 and Daniel 7:13 are also clear. "
                        "John 99:1 is invalid."
                    ),
                },
            ],
        }
        self._write_payload()
        self.extraction = self.database.add_extraction_result(
            video_id=self.video.id,
            version=1,
            proposed_text_path=str(self.base_dir / "proposed.md"),
            proposed_json_path=str(self.proposed_path),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_payload(self, *, indent: int | None = None) -> None:
        self.proposed_path.write_text(
            json.dumps(self.payload, indent=indent), encoding="utf-8"
        )

    def _measurement_values(self, run_id: int) -> dict[str, object]:
        return {
            item.metric_key: json.loads(item.value_json)
            for item in self.database.list_sermon_analysis_measurements(run_id)
        }

    def test_measures_selected_sermon_and_persists_traceable_scripture_evidence(self) -> None:
        outcome = analyze_sermon(self.database, self.video)

        self.assertTrue(outcome.created)
        values = self._measurement_values(outcome.run.id)
        self.assertEqual(60.0, values["sermon_duration_seconds"])
        self.assertEqual(4, values["scripture_reference_mentions"])
        self.assertEqual(4, values["distinct_scripture_passages"])
        self.assertEqual(3, values["distinct_scripture_books"])
        self.assertEqual(["Daniel", "John", "Romans"], values["scripture_books"])
        self.assertGreater(values["word_count"], 0)

        evidence = self.database.list_sermon_analysis_evidence(outcome.run.id)
        self.assertEqual(4, len(evidence))
        self.assertEqual({1}, {item.segment_index for item in evidence})
        self.assertEqual({60.0}, {item.start_seconds for item in evidence})
        self.assertEqual(
            {"Daniel 7:13", "John 3:16", "John 3:16-17", "Romans 8:1"},
            {
                json.loads(item.payload_json)["canonical_reference"]
                for item in evidence
            },
        )
        for item in evidence:
            segment_text = self.payload["segments"][1]["text"]
            self.assertEqual(
                item.excerpt, segment_text[item.char_start : item.char_end]
            )

    def test_same_version_and_source_is_idempotent_even_if_json_formatting_changes(self) -> None:
        first = analyze_sermon(self.database, self.video)
        self._write_payload(indent=2)
        second = analyze_sermon(self.database, self.video)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.run.id, second.run.id)
        self.assertEqual(1, len(self.database.list_sermon_analysis_runs()))

    def test_changed_source_or_analyzer_version_intentionally_creates_new_run(self) -> None:
        first = analyze_sermon(self.database, self.video)
        versioned = analyze_sermon(self.database, self.video, analyzer_version="future-3")
        self.payload["segments"][1]["text"] += " See Matthew 5:3."
        self._write_payload()
        changed = analyze_sermon(
            self.database, self.video, analyzer_version="future-3"
        )

        self.assertNotEqual(first.run.id, versioned.run.id)
        self.assertNotEqual(versioned.run.id, changed.run.id)
        self.assertEqual(3, len(self.database.list_sermon_analysis_runs()))

    def test_failed_atomic_persistence_leaves_no_partial_run(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.add_sermon_analysis_run(
                video_id=self.video.id,
                extraction_result_id=self.extraction.id,
                analyzer_key=ANALYZER_KEY,
                analyzer_version="broken",
                source_kind="test",
                source_path=str(self.proposed_path),
                source_content_sha256="source",
                input_fingerprint="interrupted-run",
                measurements=[("duplicate", "1", None), ("duplicate", "2", None)],
                evidence=[],
            )

        self.assertIsNone(
            self.database.get_sermon_analysis_run_by_fingerprint("interrupted-run")
        )

    def test_cli_runs_and_inspects_one_sermon(self) -> None:
        runner = CliRunner()
        run_result = runner.invoke(
            app,
            [
                "analysis",
                "run",
                "--youtube-video-id",
                self.video.youtube_video_id,
                "--base-dir",
                str(self.base_dir),
            ],
        )
        self.assertEqual(0, run_result.exit_code, msg=run_result.output)
        self.assertIn("created=1", run_result.output)

        show_result = runner.invoke(
            app,
            [
                "analysis",
                "show",
                "--youtube-video-id",
                self.video.youtube_video_id,
                "--base-dir",
                str(self.base_dir),
            ],
        )
        self.assertEqual(0, show_result.exit_code, msg=show_result.output)
        self.assertIn("John 3:16", show_result.output)
        self.assertIn("Provenance", show_result.output)

    def test_cli_profile_scope_uses_effective_observation_membership(self) -> None:
        profile = self.database.ensure_speaker_profile(
            stable_key="person:sample",
            display_label="Sample Pastor",
            lifecycle_state="active",
            created_reason="test",
        )
        observation = self.database.add_speaker_observation(
            video_id=self.video.id,
            extraction_result_id=self.extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="single",
            start_seconds=60.0,
            end_seconds=120.0,
            artifact_path=str(self.proposed_path),
            content_sha256="observation-content",
            extractor_version="test-v1",
            input_fingerprint="analysis-profile-observation",
        )
        self.database.add_profile_observation_event(
            profile_id=profile.id,
            observation_id=observation.id,
            action="attach",
            reviewer="test",
            reason="verified speaker",
            event_fingerprint="analysis-profile-attach",
        )
        self.database.ensure_pastor_speaker_binding(self.pastor.id, profile.id)

        runner = CliRunner()
        profile_result = runner.invoke(
            app,
            [
                "analysis",
                "run",
                "--profile-id",
                str(profile.id),
                "--base-dir",
                str(self.base_dir),
            ],
        )
        self.assertEqual(0, profile_result.exit_code, msg=profile_result.output)
        self.assertIn(f"Speaker profile #{profile.id}: 1 sermon(s)", profile_result.output)

        compatibility_result = runner.invoke(
            app,
            [
                "analysis",
                "show",
                "--pastor",
                self.pastor.slug,
                "--base-dir",
                str(self.base_dir),
            ],
        )
        self.assertEqual(
            0, compatibility_result.exit_code, msg=compatibility_result.output
        )
        self.assertIn(f"Speaker Profile #{profile.id}", compatibility_result.output)

        summary_result = runner.invoke(
            app,
            [
                "analysis",
                "summarize-profile",
                "--profile-id",
                str(profile.id),
                "--base-dir",
                str(self.base_dir),
            ],
        )
        self.assertEqual(0, summary_result.exit_code, msg=summary_result.output)
        self.assertIn("References / 1k words", summary_result.output)
        self.assertIn("Detection scope", summary_result.output)

    def test_profile_summary_is_versioned_idempotent_and_reports_detection_coverage(self) -> None:
        profile = self.database.ensure_speaker_profile(
            stable_key="person:summary",
            display_label="Summary Pastor",
            lifecycle_state="active",
            created_reason="test",
        )
        first_observation = self.database.add_speaker_observation(
            video_id=self.video.id,
            extraction_result_id=self.extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="single",
            start_seconds=60.0,
            end_seconds=120.0,
            artifact_path=str(self.proposed_path),
            content_sha256="summary-first",
            extractor_version="test-v1",
            input_fingerprint="summary-first-observation",
        )
        self.database.add_profile_observation_event(
            profile_id=profile.id,
            observation_id=first_observation.id,
            action="attach",
            reviewer="test",
            reason="verified",
            event_fingerprint="summary-first-attach",
        )
        analyze_sermon(self.database, self.video)

        second_video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=self.pastor.id,
            youtube_video_id="analysis-zero",
            title="A Sermon Without Explicit References",
            url="https://www.youtube.com/watch?v=analysis-zero",
            status=VideoStatus.EXTRACTED,
        )
        second_path = self.base_dir / "second-proposed.json"
        second_path.write_text(
            json.dumps(
                {
                    "sermon_window": {
                        "start_seconds": 0.0,
                        "end_seconds": 100.0,
                        "included_segment_indexes": [0],
                    },
                    "segments": [
                        {
                            "start_seconds": 0.0,
                            "end_seconds": 100.0,
                            "text": "Grace and peace are proclaimed without a numeric citation.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        second_extraction = self.database.add_extraction_result(
            video_id=second_video.id,
            version=1,
            proposed_text_path=str(self.base_dir / "second-proposed.md"),
            proposed_json_path=str(second_path),
        )
        second_observation = self.database.add_speaker_observation(
            video_id=second_video.id,
            extraction_result_id=second_extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="single",
            start_seconds=0.0,
            end_seconds=100.0,
            artifact_path=str(second_path),
            content_sha256="summary-second",
            extractor_version="test-v1",
            input_fingerprint="summary-second-observation",
        )
        self.database.add_profile_observation_event(
            profile_id=profile.id,
            observation_id=second_observation.id,
            action="attach",
            reviewer="test",
            reason="verified",
            event_fingerprint="summary-second-attach",
        )
        analyze_sermon(self.database, second_video)

        first = build_profile_scripture_analysis(self.database, profile.id)
        reused = build_profile_scripture_analysis(self.database, profile.id)
        values = {
            item.metric_key: json.loads(item.value_json)
            for item in self.database.list_speaker_profile_analysis_measurements(
                first.run.id
            )
        }

        self.assertTrue(first.created)
        self.assertFalse(reused.created)
        self.assertEqual(first.run.id, reused.run.id)
        self.assertEqual(2, values["sermons_attached"])
        self.assertEqual(2, values["sermons_analyzed"])
        self.assertEqual(4, values["explicit_reference_mentions"])
        self.assertEqual(1, values["old_testament_mentions"])
        self.assertEqual(3, values["new_testament_mentions"])
        self.assertEqual(
            4,
            values["reference_placement_by_quarter"]["Q1"]["mentions"],
        )
        self.assertEqual(
            1,
            values["reference_detection_diagnostics"][
                "sermons_with_zero_explicit_references"
            ],
        )
        self.assertEqual(
            2,
            len(
                self.database.list_speaker_profile_analysis_input_run_ids(
                    first.run.id
                )
            ),
        )
        additional_observation = self.database.add_speaker_observation(
            video_id=self.video.id,
            extraction_result_id=self.extraction.id,
            role="supporting_speaker_candidate",
            multiplicity_state="multiple",
            start_seconds=80.0,
            end_seconds=90.0,
            artifact_path=str(self.proposed_path),
            content_sha256="summary-membership-change",
            extractor_version="test-v1",
            input_fingerprint="summary-membership-change-observation",
        )
        self.database.add_profile_observation_event(
            profile_id=profile.id,
            observation_id=additional_observation.id,
            action="attach",
            reviewer="test",
            reason="verified membership change",
            event_fingerprint="summary-membership-change-attach",
        )
        changed_membership = build_profile_scripture_analysis(
            self.database, profile.id
        )
        self.assertTrue(changed_membership.created)
        self.assertNotEqual(first.run.id, changed_membership.run.id)


if __name__ == "__main__":
    unittest.main()
