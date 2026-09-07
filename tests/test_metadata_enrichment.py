from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.identity import persist_metadata_snapshot
from pastor_transcript_extractor.media import VideoUnavailableError
from pastor_transcript_extractor.metadata_enrichment import (
    METADATA_ENRICHMENT_SOURCE_KIND,
    enrich_metadata,
    videos_for_profile,
)
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_profile_metadata_attribution import (
    build_profile_metadata_inputs,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
)
from pastor_transcript_extractor.storage import Database


class MetadataEnrichmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.paths = build_paths(Path(self.tempdir.name) / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        source = self.database.add_source(
            "https://www.youtube.com/@metadata-enrichment",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        self.video = self.database.add_video(
            source_id=source.id,
            pastor_id=None,
            youtube_video_id="enrich00001",
            title="Worship Service",
            url="https://www.youtube.com/watch?v=enrich00001",
            status=VideoStatus.EXTRACTED,
        )
        extraction = self.database.add_extraction_result(
            video_id=self.video.id,
            version=1,
            proposed_text_path="proposed.md",
            proposed_json_path="proposed.json",
        )
        observation = self.database.add_speaker_observation(
            video_id=self.video.id,
            extraction_result_id=extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="single",
            start_seconds=10.0,
            end_seconds=100.0,
            artifact_path="speaker.json",
            content_sha256="speaker-content",
            extractor_version="speaker_evidence_v2",
            input_fingerprint="speaker-input",
        )
        self.profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="same speaker",
            review_event_key="metadata-enrichment-profile",
        )
        attach_reviewed_observation(
            self.database,
            profile_id=self.profile.id,
            observation_id=observation.id,
            reviewer="reviewer",
            reason="same speaker",
            review_event_key="attach-metadata-enrichment",
        )
        self.original = persist_metadata_snapshot(
            self.database,
            self.paths,
            video=self.video,
            pastor=None,
            source_kind="yt_dlp_flat_playlist",
            raw_metadata={"title": "Worship Service", "description": "  "},
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_missing_description_appends_enrichment_and_flows_to_attribution(self) -> None:
        calls: list[str] = []
        progress: list[str] = []

        def fetch(url: str, _binary: str, _runtime: str | None) -> dict[str, object]:
            calls.append(url)
            return {
                "id": "enrich00001",
                "title": "Worship Service",
                "description": "The message is presented by Pastor Ada Example.",
            }

        result = enrich_metadata(
            self.database,
            self.paths,
            videos_for_profile(self.database, self.profile.id),
            yt_dlp_bin="yt-dlp",
            fetcher=fetch,
            progress_callback=lambda _i, _n, _v, outcome, _detail: progress.append(outcome),
        )

        self.assertEqual(1, result.eligible)
        self.assertEqual(1, result.enriched)
        self.assertEqual([self.video.url], calls)
        self.assertEqual(["enriched"], progress)
        latest = self.database.get_latest_metadata_artifact_for_video(self.video.id)
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertNotEqual(self.original.id, latest.id)
        self.assertEqual(METADATA_ENRICHMENT_SOURCE_KIND, latest.source_kind)
        self.assertTrue(Path(self.original.artifact_path).is_file())
        self.assertTrue(Path(latest.artifact_path).is_file())
        with self.database.connect() as connection:
            history_count = connection.execute(
                "SELECT COUNT(*) FROM metadata_artifacts WHERE video_id = ?",
                (self.video.id,),
            ).fetchone()[0]
        self.assertEqual(2, history_count)

        candidates = build_profile_metadata_inputs(
            self.database,
            profile_ids=frozenset((self.profile.id,)),
            model="fixture:1",
            model_digest="digest",
        )
        description_fields = [
            field
            for field in candidates[0].fields
            if field.field_path == "raw_metadata.description"
        ]
        self.assertEqual(1, len(description_fields))
        self.assertIn("Pastor Ada Example", description_fields[0].text)

    def test_existing_description_skips_network_request(self) -> None:
        persist_metadata_snapshot(
            self.database,
            self.paths,
            video=self.video,
            pastor=None,
            source_kind=METADATA_ENRICHMENT_SOURCE_KIND,
            raw_metadata={"description": "Already complete."},
        )

        def unexpected_fetch(*_args):
            self.fail("complete metadata must not make a network request")

        result = enrich_metadata(
            self.database,
            self.paths,
            (self.video,),
            yt_dlp_bin="yt-dlp",
            fetcher=unexpected_fetch,
        )

        self.assertEqual(1, result.already_complete)
        self.assertEqual(0, result.eligible)
        self.assertEqual(0, result.enriched)

    def test_unavailable_video_does_not_abort_remaining_videos(self) -> None:
        second = self.database.add_video(
            source_id=self.video.source_id,
            pastor_id=None,
            youtube_video_id="enrich00002",
            title="Second Service",
            url="https://www.youtube.com/watch?v=enrich00002",
            status=VideoStatus.EXTRACTED,
        )

        def fetch(url: str, _binary: str, _runtime: str | None) -> dict[str, object]:
            if url == self.video.url:
                raise VideoUnavailableError("Private video")
            return {"description": "Pastor Grace Example gives the sermon."}

        result = enrich_metadata(
            self.database,
            self.paths,
            (self.video, second),
            yt_dlp_bin="yt-dlp",
            fetcher=fetch,
        )

        self.assertEqual(2, result.eligible)
        self.assertEqual(1, result.unavailable)
        self.assertEqual(1, result.enriched)
        self.assertEqual(0, result.failed)

    def test_replay_uses_latest_description_and_is_idempotent(self) -> None:
        calls = 0

        def fetch(_url: str, _binary: str, _runtime: str | None) -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {"description": "Pastor Replay Example is speaking."}

        first = enrich_metadata(
            self.database,
            self.paths,
            (self.video,),
            yt_dlp_bin="yt-dlp",
            fetcher=fetch,
        )
        replay = enrich_metadata(
            self.database,
            self.paths,
            (self.video,),
            yt_dlp_bin="yt-dlp",
            fetcher=fetch,
        )

        self.assertEqual(1, first.enriched)
        self.assertEqual(1, replay.already_complete)
        self.assertEqual(1, calls)
        with self.database.connect() as connection:
            history_count = connection.execute(
                "SELECT COUNT(*) FROM metadata_artifacts WHERE video_id = ?",
                (self.video.id,),
            ).fetchone()[0]
        self.assertEqual(2, history_count)

    def test_success_without_description_is_counted_as_failed(self) -> None:
        result = enrich_metadata(
            self.database,
            self.paths,
            (self.video,),
            yt_dlp_bin="yt-dlp",
            fetcher=lambda *_args: {"title": "Still no description"},
        )

        self.assertEqual(1, result.failed)
        self.assertEqual(0, result.enriched)
        self.assertEqual(1, self.database.counts_by_table()["metadata_artifacts"])

    def test_all_anonymous_profiles_cli_prints_progress_and_summary(self) -> None:
        runner = CliRunner()
        with patch(
            "pastor_transcript_extractor.metadata_enrichment.fetch_video_metadata",
            return_value={"description": "Pastor CLI Example is speaking."},
        ) as fetch:
            result = runner.invoke(
                app,
                [
                    "identity",
                    "enrich-metadata",
                    "--all-anonymous-profiles",
                    "--base-dir",
                    str(self.paths.root),
                ],
            )

        self.assertEqual(0, result.exit_code, msg=result.output)
        fetch.assert_called_once()
        self.assertIn("[1/1]", result.output)
        self.assertIn("enriched", result.output)
        for count in (
            "eligible=1",
            "enriched=1",
            "already_complete=0",
            "unavailable=0",
            "failed=0",
        ):
            self.assertIn(count, result.output)

    def test_all_anonymous_profiles_plan_only_has_no_network_or_writes(self) -> None:
        runner = CliRunner()
        with patch(
            "pastor_transcript_extractor.metadata_enrichment.fetch_video_metadata"
        ) as fetch:
            result = runner.invoke(
                app,
                [
                    "identity",
                    "enrich-metadata",
                    "--all-anonymous-profiles",
                    "--plan-only",
                    "--base-dir",
                    str(self.paths.root),
                ],
            )

        self.assertEqual(0, result.exit_code, msg=result.output)
        fetch.assert_not_called()
        normalized_output = " ".join(result.output.split())
        self.assertIn(
            "profiles=1 videos=1 eligible=1 already_complete=0",
            normalized_output,
        )
        self.assertIn("no network requests or writes", normalized_output)
        self.assertEqual(1, self.database.counts_by_table()["metadata_artifacts"])

    def test_analyze_all_anonymous_profiles_plan_only_avoids_ollama(self) -> None:
        runner = CliRunner()
        with patch(
            "pastor_transcript_extractor.cli.build_llm_config"
        ) as build_llm:
            result = runner.invoke(
                app,
                [
                    "identity",
                    "analyze-profile-metadata",
                    "--all-anonymous-profiles",
                    "--plan-only",
                    "--base-dir",
                    str(self.paths.root),
                ],
            )

        self.assertEqual(0, result.exit_code, msg=result.output)
        build_llm.assert_not_called()
        normalized_output = " ".join(result.output.split())
        self.assertIn("eligible=1", normalized_output)
        self.assertIn("no Ollama calls or artifact writes", normalized_output)

    def test_review_all_anonymous_profiles_plan_only_avoids_review_writes(self) -> None:
        runner = CliRunner()
        observation = self.database.list_effective_observation_ids_for_profile(
            self.profile.id
        )[0]
        observation_record = self.database.get_speaker_observation(observation)
        assert observation_record is not None
        with patch(
            "pastor_transcript_extractor.cli.load_profile_attribution_clip_timestamps",
            return_value={observation_record.input_fingerprint: 10},
        ), patch(
            "pastor_transcript_extractor.cli.write_profile_attribution_packet"
        ) as write_packet:
            result = runner.invoke(
                app,
                [
                    "identity",
                    "review-profile-attribution",
                    "--all-anonymous-profiles",
                    "--plan-only",
                    "--reviewer",
                    "reviewer",
                    "--base-dir",
                    str(self.paths.root),
                ],
            )

        self.assertEqual(0, result.exit_code, msg=result.output)
        write_packet.assert_not_called()
        normalized_output = " ".join(result.output.split())
        self.assertIn("profiles=1 metadata_proposals=0", normalized_output)
        self.assertIn(
            "no packets opened and no review events written",
            normalized_output,
        )


if __name__ == "__main__":
    unittest.main()
