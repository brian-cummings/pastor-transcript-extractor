from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.sermon_analysis import analyze_sermon
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.structure_analysis import (
    STRUCTURE_ANALYZER_KEY,
    analyze_sermon_structure,
    build_profile_structure_analysis,
)
from pastor_transcript_extractor.structure_population_analysis import (
    build_structure_population_snapshot,
    load_structure_population_snapshot,
)
from pastor_transcript_extractor.structure_readiness import (
    build_structure_readiness,
    run_structure_backfill,
)


class StructurePopulationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tempdir.name)
        paths = build_paths(self.base_dir)
        ensure_directories(paths)
        self.database = Database(paths.database)
        self.database.initialize()
        pastor = self.database.add_pastor("structure", "Structure Test")
        self.source = self.database.add_source(
            "https://www.youtube.com/@structure",
            SourceType.CHANNEL,
            pastor_id=pastor.id,
        )
        self.pastor_id = pastor.id

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _build_profile(
        self, key: str, *, sermon_count: int = 3, analyze_structure: bool = True
    ):
        profile = self.database.ensure_speaker_profile(
            stable_key=f"person:{key}",
            display_label=key.title(),
            lifecycle_state="active",
            created_reason="test",
        )
        videos = []
        for index in range(sermon_count):
            video = self.database.add_video(
                source_id=self.source.id,
                pastor_id=self.pastor_id,
                youtube_video_id=f"{key}-{index}",
                title=f"{key} sermon {index}",
                url=f"https://www.youtube.com/watch?v={key}-{index}",
                status=VideoStatus.EXTRACTED,
            )
            path = self.base_dir / f"{key}-{index}.json"
            segments = []
            for segment in range(8):
                text = (
                    f"We consider John 3:{16 + index}. You and I return to grace "
                    f"with {key} theme {segment}."
                )
                segments.append({
                    "start_seconds": float(segment * 30),
                    "end_seconds": float((segment + 1) * 30),
                    "text": text,
                })
            path.write_text(json.dumps({
                "sermon_window": {
                    "start_seconds": 0.0,
                    "end_seconds": 240.0,
                    "included_segment_indexes": list(range(8)),
                },
                "segments": segments,
            }), encoding="utf-8")
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
                end_seconds=240.0,
                artifact_path=str(path),
                content_sha256=f"{key}-{index}-content",
                extractor_version="test",
                input_fingerprint=f"{key}-{index}-observation",
            )
            self.database.add_profile_observation_event(
                profile_id=profile.id,
                observation_id=observation.id,
                action="attach",
                reviewer="test",
                reason="fixture",
                event_fingerprint=f"{key}-{index}-attach",
            )
            analyze_sermon(self.database, video)
            if analyze_structure:
                analyze_sermon_structure(self.database, video)
            videos.append(video)
        if analyze_structure:
            build_profile_structure_analysis(self.database, profile.id)
        return profile, videos

    def test_readiness_and_backfill_are_resumable_and_dry_run_is_read_only(self) -> None:
        profile, videos = self._build_profile("pending", analyze_structure=False)
        before = build_structure_readiness(self.database)
        item = next(item for item in before.profiles if item.profile_id == profile.id)
        self.assertEqual(3, item.missing_sermons)
        self.assertEqual("missing", item.aggregate_state)

        planned = run_structure_backfill(self.database, dry_run=True)
        self.assertTrue(planned.dry_run)
        self.assertFalse(any(
            self.database.get_latest_sermon_analysis_run(video.id, STRUCTURE_ANALYZER_KEY)
            for video in videos
        ))

        completed = run_structure_backfill(self.database)
        self.assertEqual(3, completed.created_sermon_runs)
        self.assertEqual(1, completed.created_profile_runs)
        self.assertEqual(3, completed.after.totals["current"])
        rerun = run_structure_backfill(self.database)
        self.assertEqual(0, rerun.created_sermon_runs)
        self.assertEqual(1, rerun.reused_profile_runs)

    def test_population_snapshot_is_correct_idempotent_and_cli_visible(self) -> None:
        self._build_profile("alpha")
        self._build_profile("beta")
        self._build_profile("gamma")

        first = build_structure_population_snapshot(self.database)
        reused = build_structure_population_snapshot(self.database)
        snapshot, report = load_structure_population_snapshot(self.database)

        self.assertTrue(first.created)
        self.assertFalse(reused.created)
        self.assertEqual(first.snapshot.id, reused.snapshot.id)
        self.assertEqual(first.snapshot.id, snapshot.id)
        self.assertEqual(3, report["population"]["profile_count"])
        self.assertEqual(9, report["population"]["sermon_count"])
        self.assertEqual(12, len(report["feature_diagnostics"]))
        self.assertEqual(
            "diagnostic_only",
            report["feature_diagnostics"]["transcript_tokens_per_minute"]["recommendation"],
        )
        self.assertEqual(3, len(self.database.list_population_analysis_snapshot_inputs(snapshot.id)))

        shown = CliRunner().invoke(
            app,
            [
                "analysis", "structure-population-show", "--base-dir", str(self.base_dir),
            ],
        )
        self.assertEqual(0, shown.exit_code, shown.output)
        self.assertIn("Preliminary Structure Feature Diagnostics", shown.output)
        self.assertIn("no comparison schema", shown.output)
        self.assertIn("clustering changed", shown.output)


if __name__ == "__main__":
    unittest.main()
