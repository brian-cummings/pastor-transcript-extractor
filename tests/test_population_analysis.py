from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.population_analysis import (
    PopulationPolicy,
    SermonRecord,
    aggregate_sermon_records,
    build_population_snapshot,
    load_population_snapshot_report,
)
from pastor_transcript_extractor.profile_analysis import build_profile_scripture_analysis
from pastor_transcript_extractor.sermon_analysis import analyze_sermon
from pastor_transcript_extractor.storage import Database


class PopulationAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tempdir.name)
        paths = build_paths(self.base_dir)
        ensure_directories(paths)
        self.database = Database(paths.database)
        self.database.initialize()
        self.profiles = []
        for profile_index in range(3):
            profile = self.database.ensure_speaker_profile(
                stable_key=f"person:population-{profile_index}",
                display_label=(f"Profile {profile_index}" if profile_index == 0 else None),
                lifecycle_state="active" if profile_index < 2 else "provisional",
                created_reason="test",
            )
            self.profiles.append(profile)
            pastor = self.database.add_pastor(
                f"population-{profile_index}", f"Population {profile_index}"
            )
            source = self.database.add_source(
                f"https://www.youtube.com/@population{profile_index}",
                SourceType.CHANNEL,
                pastor_id=pastor.id,
            )
            for sermon_index in range(3):
                references = " ".join(
                    ["John 3:16"] * (profile_index + 1)
                    + ["Romans 8:1"] * sermon_index
                )
                if profile_index == 0 and sermon_index == 0:
                    references += (
                        " For God so loved the world that he gave his only born Son, "
                        "that whoever believes in him should not perish but have eternal life."
                    )
                self._add_sermon(
                    profile.id,
                    source.id,
                    profile_index,
                    sermon_index,
                    references or "No numeric reference here.",
                )
            build_profile_scripture_analysis(self.database, profile.id)
        self.policy = PopulationPolicy(bootstrap_samples=20)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _add_sermon(
        self,
        profile_id: int,
        source_id: int,
        profile_index: int,
        sermon_index: int,
        text: str,
    ) -> None:
        key = f"population-{profile_index}-{sermon_index}"
        video = self.database.add_video(
            source_id=source_id,
            pastor_id=None,
            youtube_video_id=key,
            title=key,
            url=f"https://www.youtube.com/watch?v={key}",
            published_at=f"2026-0{sermon_index + 1}-01T12:00:00+00:00",
            status=VideoStatus.EXTRACTED,
        )
        path = self.base_dir / f"{key}.json"
        path.write_text(
            json.dumps(
                {
                    "sermon_window": {
                        "start_seconds": 0.0,
                        "end_seconds": 60.0,
                        "included_segment_indexes": [0],
                    },
                    "segments": [
                        {"start_seconds": 0.0, "end_seconds": 60.0, "text": text}
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
            content_sha256=key,
            extractor_version="test",
            input_fingerprint=f"observation-{key}",
        )
        self.database.add_profile_observation_event(
            profile_id=profile_id,
            observation_id=observation.id,
            action="attach",
            reviewer="test",
            reason="test",
            event_fingerprint=f"attach-{key}",
        )
        analyze_sermon(self.database, video)

    def test_snapshot_is_traceable_reproducible_and_idempotent(self) -> None:
        first = build_population_snapshot(self.database, policy=self.policy)
        second = build_population_snapshot(self.database, policy=self.policy)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.snapshot.id, second.snapshot.id)
        self.assertEqual(3, first.report["population"]["profile_count"])
        self.assertEqual(9, first.report["population"]["sermon_count"])
        inputs = self.database.list_population_analysis_snapshot_inputs(first.snapshot.id)
        self.assertEqual([profile.id for profile in self.profiles], [item[0] for item in inputs])
        self.assertEqual(
            [
                self.database.get_latest_speaker_profile_analysis_run(
                    profile.id, "profile-scripture-usage"
                ).id
                for profile in self.profiles
            ],
            [item[1] for item in inputs],
        )
        self.assertEqual(
            0,
            sum(
                (profile["recomputation_parity_max_absolute_delta"] or 0) > 0.000001
                for profile in first.report["profiles"]
            ),
        )
        density = first.report["feature_diagnostics"]["references_per_1000_words"]
        self.assertEqual(3, density["distribution"]["observed_count"])
        self.assertIn(
            density["leave_one_out"]["stability"],
            {"high", "moderate", "low", "not_evaluable"},
        )
        self.assertTrue(first.report["interpretation"]["recommendations_are_advisory"])

    def test_changed_profile_run_or_population_version_creates_new_snapshot(self) -> None:
        first = build_population_snapshot(self.database, policy=self.policy)
        profile = self.profiles[0]
        source = self.database.list_sources()[0]
        self._add_sermon(profile.id, source.id, 0, 3, "Matthew 5:3")
        build_profile_scripture_analysis(self.database, profile.id)

        changed = build_population_snapshot(self.database, policy=self.policy)
        versioned = build_population_snapshot(
            self.database, policy=self.policy, analyzer_version="population-future"
        )

        self.assertTrue(changed.created)
        self.assertNotEqual(first.snapshot.id, changed.snapshot.id)
        self.assertEqual(10, changed.report["population"]["sermon_count"])
        self.assertTrue(versioned.created)
        self.assertNotEqual(changed.snapshot.id, versioned.snapshot.id)

    def test_snapshot_persistence_is_atomic(self) -> None:
        run_id = self.database.get_latest_speaker_profile_analysis_run(
            self.profiles[0].id, "profile-scripture-usage"
        ).id
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.add_population_analysis_snapshot(
                analyzer_version="broken",
                profile_analyzer_key="profile-scripture-usage",
                profile_analyzer_version="4",
                feature_schema_version="test",
                eligibility_policy_json="{}",
                input_fingerprint="broken-population-snapshot",
                report_json="{}",
                inputs=[(self.profiles[0].id, run_id), (self.profiles[0].id, run_id)],
            )
        self.assertIsNone(
            self.database.get_population_analysis_snapshot_by_fingerprint(
                "broken-population-snapshot"
            )
        )

    def test_sparse_sermons_preserve_nulls_and_zero_reference_diagnostics(self) -> None:
        empty = SermonRecord(
            run_id=1,
            video_id=1,
            source_id=1,
            published_ordinal=None,
            word_count=1000,
            books=Counter(),
            chapters=Counter(),
            multi_verse_references=0,
            alignment_count=0,
            anchored_alignment_count=0,
            aligned_span_words=0,
            alignment_scores=(),
            aligned_chapters=Counter(),
        )
        referenced = SermonRecord(
            run_id=2,
            video_id=2,
            source_id=1,
            published_ordinal=None,
            word_count=1000,
            books=Counter({"John": 2}),
            chapters=Counter({"John 3": 2}),
            multi_verse_references=0,
            alignment_count=0,
            anchored_alignment_count=0,
            aligned_span_words=0,
            alignment_scores=(),
            aligned_chapters=Counter(),
        )

        mixed = aggregate_sermon_records([empty, referenced])
        all_empty = aggregate_sermon_records([empty, empty])

        self.assertEqual(0.5, mixed["zero_detected_reference_sermon_fraction"])
        self.assertEqual(1.0, mixed["sustained_chapter_reference_ratio"])
        self.assertIsNone(all_empty["book_concentration_hhi"])
        self.assertIsNone(all_empty["old_testament_share"])
        self.assertEqual(1.0, all_empty["zero_detected_reference_sermon_fraction"])

    def test_cli_builds_and_shows_snapshot(self) -> None:
        runner = CliRunner()
        built = runner.invoke(
            app,
            [
                "analysis",
                "population-build",
                "--bootstrap-samples",
                "20",
                "--base-dir",
                str(self.base_dir),
            ],
        )
        self.assertEqual(0, built.exit_code, msg=built.output)
        self.assertIn("Population snapshot #", built.output)
        self.assertIn("Recommendations are advisory only", built.output)

        shown = runner.invoke(
            app,
            [
                "analysis",
                "population-show",
                "--json",
                "--base-dir",
                str(self.base_dir),
            ],
        )
        self.assertEqual(0, shown.exit_code, msg=shown.output)
        self.assertIn('"scripture-population-report@1"', shown.output)
        snapshot, report = load_population_snapshot_report(self.database)
        self.assertGreater(snapshot.id, 0)
        self.assertEqual("scripture-population-report@1", report["schema_version"])


if __name__ == "__main__":
    unittest.main()
