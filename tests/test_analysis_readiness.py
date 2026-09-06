from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.analysis_readiness import (
    build_readiness_report,
    run_deterministic_backfill,
)
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.sermon_analysis import analyze_sermon
from pastor_transcript_extractor.storage import Database


class AnalysisReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tempdir.name)
        paths = build_paths(self.base_dir)
        ensure_directories(paths)
        self.database = Database(paths.database)
        self.database.initialize()
        pastor = self.database.add_pastor("sample", "Sample")
        self.source = self.database.add_source(
            "https://www.youtube.com/@sample",
            SourceType.CHANNEL,
            pastor_id=pastor.id,
        )
        self.profile = self.database.ensure_speaker_profile(
            stable_key="person:readiness",
            display_label=None,
            lifecycle_state="provisional",
            created_reason="test",
        )
        self.videos = [self._add_sermon(index) for index in range(3)]

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _add_sermon(self, index: int):
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=None,
            youtube_video_id=f"ready{index}",
            title=f"Sermon {index}",
            url=f"https://www.youtube.com/watch?v=ready{index}",
            status=VideoStatus.EXTRACTED,
        )
        path = self.base_dir / f"ready{index}.json"
        path.write_text(
            json.dumps(
                {
                    "sermon_window": {
                        "start_seconds": 0.0,
                        "end_seconds": 60.0,
                        "included_segment_indexes": [0],
                    },
                    "segments": [
                        {
                            "start_seconds": 0.0,
                            "end_seconds": 60.0,
                            "text": f"Sermon {index}. John 3:16.",
                        }
                    ],
                }
            ),
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
            content_sha256=f"content-{index}",
            extractor_version="test",
            input_fingerprint=f"observation-{index}",
        )
        self.database.add_profile_observation_event(
            profile_id=self.profile.id,
            observation_id=observation.id,
            action="attach",
            reviewer="test",
            reason="test",
            event_fingerprint=f"attach-{index}",
        )
        return video

    def test_backfill_is_profile_centric_and_idempotent(self) -> None:
        before = build_readiness_report(self.database)
        self.assertEqual(3, before.eligible_sermons)
        self.assertEqual(3, before.missing_sermons)
        self.assertEqual("missing", before.profiles[0].aggregate_state)

        first = run_deterministic_backfill(self.database)
        self.assertEqual(3, first.created_sermon_runs)
        self.assertEqual(1, first.created_profile_runs)
        self.assertEqual(100.0, first.after.coverage_percent)
        self.assertEqual("current", first.after.profiles[0].aggregate_state)

        second = run_deterministic_backfill(self.database)
        self.assertEqual(0, second.created_sermon_runs)
        self.assertEqual(0, second.reused_sermon_runs)
        self.assertEqual(0, second.created_profile_runs)
        self.assertEqual(3, len(self.database.list_sermon_analysis_runs()))

    def test_source_and_membership_changes_make_derived_state_stale(self) -> None:
        run_deterministic_backfill(self.database)
        source_path = Path(
            self.database.get_latest_extraction_result_for_video(
                self.videos[0].id
            ).proposed_json_path
        )
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        payload["segments"][0]["text"] += " Romans 8:1."
        source_path.write_text(json.dumps(payload), encoding="utf-8")

        changed = build_readiness_report(self.database)
        self.assertEqual(1, changed.stale_sermons)
        self.assertEqual("stale", changed.profiles[0].aggregate_state)

        self._add_sermon(3)
        membership_changed = build_readiness_report(self.database)
        self.assertEqual(1, membership_changed.missing_sermons)
        self.assertEqual(1, membership_changed.stale_sermons)
        self.assertEqual("stale", membership_changed.profiles[0].aggregate_state)

    def test_interrupted_batch_preserves_completed_sermon_and_resumes(self) -> None:
        calls = 0

        def interrupt_after_one(database, video, *, analyzer_version):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            return analyze_sermon(database, video, analyzer_version=analyzer_version)

        with self.assertRaises(KeyboardInterrupt):
            run_deterministic_backfill(self.database, analyze=interrupt_after_one)
        partial = build_readiness_report(self.database)
        self.assertEqual(1, partial.current_sermons)
        self.assertEqual("missing", partial.profiles[0].aggregate_state)

        resumed = run_deterministic_backfill(self.database)
        self.assertEqual(2, resumed.created_sermon_runs)
        self.assertEqual(1, resumed.created_profile_runs)
        self.assertEqual("current", resumed.after.profiles[0].aggregate_state)

    def test_failure_is_reported_without_stopping_other_sermons(self) -> None:
        broken_path = Path(
            self.database.get_latest_extraction_result_for_video(
                self.videos[1].id
            ).proposed_json_path
        )
        broken_path.write_text("not json", encoding="utf-8")

        result = run_deterministic_backfill(self.database)

        self.assertEqual(2, result.created_sermon_runs)
        self.assertEqual(1, len(result.failed_sermons))
        self.assertEqual(self.videos[1].id, result.failed_sermons[0][0])
        self.assertEqual(2, result.after.current_sermons)
        self.assertEqual(1, result.after.blocked_sermons)
        self.assertEqual(0, result.created_profile_runs)

    def test_analyzer_version_change_invalidates_sermons_and_profile(self) -> None:
        run_deterministic_backfill(self.database)

        changed = build_readiness_report(
            self.database,
            analyzer_version="sermon-future",
            profile_analyzer_version="profile-future",
        )

        self.assertEqual(3, changed.stale_sermons)
        self.assertEqual("stale", changed.profiles[0].aggregate_state)

    def test_removed_effective_membership_makes_aggregate_stale(self) -> None:
        run_deterministic_backfill(self.database)
        observation_id = self.database.list_effective_observation_ids_for_profile(
            self.profile.id
        )[0]
        self.database.add_profile_observation_event(
            profile_id=self.profile.id,
            observation_id=observation_id,
            action="detach",
            reviewer="test",
            reason="membership correction",
            event_fingerprint="detach-for-readiness-test",
        )

        report = build_readiness_report(self.database)

        self.assertEqual(2, report.eligible_sermons)
        self.assertEqual("stale", report.profiles[0].aggregate_state)

    def test_dry_run_writes_nothing(self) -> None:
        result = CliRunner().invoke(
            app,
            [
                "analysis",
                "backfill",
                "--all-attached",
                "--dry-run",
                "--base-dir",
                str(self.base_dir),
            ],
        )
        self.assertEqual(0, result.exit_code, msg=result.output)
        self.assertIn("no analysis or profile rows were written", result.output)
        self.assertEqual([], self.database.list_sermon_analysis_runs())


if __name__ == "__main__":
    unittest.main()
