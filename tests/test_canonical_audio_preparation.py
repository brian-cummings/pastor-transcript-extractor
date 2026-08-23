from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.extraction import _record_speaker_evidence_safely
from pastor_transcript_extractor.media_archive import (
    CANONICAL_CLIP_PREPARATION_POLICY_VERSION,
    _canonical_clip_preparation_status,
    prepare_canonical_audio,
    write_canonical_clip_preparation_manifest,
)
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_pair_diagnostics import CachedSpan, SpanSpec
from pastor_transcript_extractor.speaker_pair_eligibility import (
    AutomaticSpeakerObservationEligibility,
)
from pastor_transcript_extractor.storage import Database


class CanonicalAudioPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = build_paths(self.root)
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        pastor = self.database.add_pastor("sample", "Sample Pastor")
        source = self.database.add_source(
            "https://www.youtube.com/@sample",
            SourceType.CHANNEL,
            pastor_id=pastor.id,
        )
        self.video = self.database.add_video(
            source_id=source.id,
            pastor_id=pastor.id,
            youtube_video_id="canonical001",
            title="Canonical sermon",
            url="https://www.youtube.com/watch?v=canonical001",
            channel_name="Sample Church",
            published_at="2026-08-01T12:00:00+00:00",
            duration_seconds=1800,
            status=VideoStatus.EXTRACTED,
        )
        self.observation = SimpleNamespace(
            id=41,
            video_id=self.video.id,
            extraction_result_id=9,
            input_fingerprint="observation-current",
            artifact_path=str(self.root / "observation.json"),
            content_sha256="evidence-sha",
            start_seconds=120.0,
            end_seconds=1500.0,
        )
        self.artifact = SimpleNamespace(
            id=17,
            video_id=self.video.id,
            artifact_path=str(self.root / "normalized.wav"),
            manifest_path=str(self.root / "normalized-manifest.json"),
            content_sha256="normalized-sha",
        )
        Path(self.artifact.artifact_path).write_bytes(b"normalized-audio")
        self.spans = (SpanSpec(300.0, 312.0), SpanSpec(600.0, 612.0))
        self.eligibility = AutomaticSpeakerObservationEligibility(
            "eligible",
            observation=self.observation,
            media_artifact=self.artifact,
            diagnostic_spans=self.spans,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _cached_span(self, index: int, spec: SpanSpec, *, hit: bool = False):
        path = self.root / f"clip-{index}.wav"
        path.write_bytes(f"clip-{index}".encode())
        return CachedSpan(
            observation_fingerprint=self.observation.input_fingerprint,
            start_seconds=spec.start_seconds,
            end_seconds=spec.end_seconds,
            wav_path=str(path),
            wav_sha256=f"clip-sha-{index}",
            duration_seconds=12.0,
            rms_dbfs=-20.0,
            clipped_fraction=0.0,
            cache_hit=hit,
        )

    def test_missing_canonical_clips_are_generated_without_pair_comparison(self) -> None:
        prepared = [
            self._cached_span(index, span)
            for index, span in enumerate(self.spans, start=1)
        ]
        with (
            patch(
                "pastor_transcript_extractor.media_archive."
                "assess_automatic_speaker_observation",
                return_value=self.eligibility,
            ),
            patch(
                "pastor_transcript_extractor.media_archive."
                "get_authoritative_normalized_media_artifact",
                return_value=(
                    self.artifact,
                    SimpleNamespace(status="verified_local", verified=True),
                ),
            ),
            patch(
                "pastor_transcript_extractor.media_archive."
                "_canonical_clip_preparation_status",
                side_effect=("missing", "current"),
            ),
            patch(
                "pastor_transcript_extractor.media_archive.AudioSpanCache.prepare",
                side_effect=prepared,
            ) as prepare_span,
            patch(
                "pastor_transcript_extractor.media_archive."
                "write_canonical_clip_preparation_manifest"
            ) as write_manifest,
        ):
            result = prepare_canonical_audio(
                self.database,
                self.paths,
                cache_root=self.root / "cache",
                video_ids={self.video.id},
            )

        self.assertEqual(1, result.counts["prepared"])
        self.assertEqual(2, prepare_span.call_count)
        self.assertEqual(
            self.artifact.content_sha256,
            prepare_span.call_args_list[0].kwargs[
                "expected_source_audio_sha256"
            ],
        )
        self.assertEqual(
            CANONICAL_CLIP_PREPARATION_POLICY_VERSION,
            prepare_span.call_args_list[0].kwargs[
                "generation_policy_version"
            ],
        )
        write_manifest.assert_called_once()

    def test_current_manifest_replays_without_reading_or_generating_clips(self) -> None:
        with (
            patch(
                "pastor_transcript_extractor.media_archive."
                "assess_automatic_speaker_observation",
                return_value=self.eligibility,
            ),
            patch(
                "pastor_transcript_extractor.media_archive."
                "get_authoritative_normalized_media_artifact",
                return_value=(
                    self.artifact,
                    SimpleNamespace(status="verified_local", verified=True),
                ),
            ),
            patch(
                "pastor_transcript_extractor.media_archive."
                "_canonical_clip_preparation_status",
                return_value="current",
            ),
            patch(
                "pastor_transcript_extractor.media_archive.AudioSpanCache.prepare"
            ) as prepare_span,
        ):
            result = prepare_canonical_audio(
                self.database,
                self.paths,
                cache_root=self.root / "cache",
                video_ids={self.video.id},
            )

        self.assertEqual(1, result.counts["already_prepared"])
        prepare_span.assert_not_called()

    def test_batch_defers_offline_archive_and_continues(self) -> None:
        second = SimpleNamespace(id=99, youtube_video_id="canonical002")
        database = SimpleNamespace(
            list_videos=lambda: [self.video, second],
            get_latest_speaker_observation_for_video=lambda _video_id: self.observation,
        )
        prepared = [
            self._cached_span(index, span)
            for index, span in enumerate(self.spans, start=1)
        ]
        with (
            patch(
                "pastor_transcript_extractor.media_archive."
                "assess_automatic_speaker_observation",
                return_value=self.eligibility,
            ),
            patch(
                "pastor_transcript_extractor.media_archive."
                "get_authoritative_normalized_media_artifact",
                side_effect=(
                    (
                        self.artifact,
                        SimpleNamespace(
                            status="archived_media_unavailable", verified=False
                        ),
                    ),
                    (
                        self.artifact,
                        SimpleNamespace(status="verified_local", verified=True),
                    ),
                ),
            ),
            patch(
                "pastor_transcript_extractor.media_archive."
                "_canonical_clip_preparation_status",
                side_effect=("missing", "missing", "current"),
            ),
            patch(
                "pastor_transcript_extractor.media_archive.AudioSpanCache.prepare",
                side_effect=prepared,
            ),
            patch(
                "pastor_transcript_extractor.media_archive."
                "write_canonical_clip_preparation_manifest"
            ),
        ):
            result = prepare_canonical_audio(
                database,
                self.paths,
                cache_root=self.root / "cache",
                all_eligible=True,
            )

        self.assertEqual(1, result.counts["deferred"])
        self.assertEqual(1, result.counts["prepared"])

    def test_dry_run_does_not_generate_clips_or_manifest(self) -> None:
        with (
            patch(
                "pastor_transcript_extractor.media_archive."
                "assess_automatic_speaker_observation",
                return_value=self.eligibility,
            ),
            patch(
                "pastor_transcript_extractor.media_archive."
                "get_authoritative_normalized_media_artifact",
                return_value=(
                    self.artifact,
                    SimpleNamespace(status="verified_local", verified=True),
                ),
            ) as verify_audio,
            patch(
                "pastor_transcript_extractor.media_archive."
                "_canonical_clip_preparation_status",
                return_value="stale",
            ),
            patch(
                "pastor_transcript_extractor.media_archive.AudioSpanCache.prepare"
            ) as prepare_span,
            patch(
                "pastor_transcript_extractor.media_archive."
                "write_canonical_clip_preparation_manifest"
            ) as write_manifest,
        ):
            result = prepare_canonical_audio(
                self.database,
                self.paths,
                cache_root=self.root / "cache",
                video_ids={self.video.id},
                dry_run=True,
            )

        self.assertEqual(1, result.counts["would_prepare"])
        verify_audio.assert_not_called()
        prepare_span.assert_not_called()
        write_manifest.assert_not_called()

    def test_offline_defer_does_not_mutate_registry_state(self) -> None:
        before = self.database.counts_by_table()
        with (
            patch(
                "pastor_transcript_extractor.media_archive."
                "assess_automatic_speaker_observation",
                return_value=self.eligibility,
            ),
            patch(
                "pastor_transcript_extractor.media_archive."
                "get_authoritative_normalized_media_artifact",
                return_value=(
                    self.artifact,
                    SimpleNamespace(
                        status="archived_media_unavailable", verified=False
                    ),
                ),
            ),
        ):
            result = prepare_canonical_audio(
                self.database,
                self.paths,
                cache_root=self.root / "cache",
                video_ids={self.video.id},
            )

        self.assertEqual(1, result.counts["deferred"])
        self.assertEqual(before, self.database.counts_by_table())

    def test_generation_failure_retains_normalized_audio_and_publishes_no_manifest(self) -> None:
        normalized_path = Path(self.artifact.artifact_path)
        normalized_path.write_bytes(b"keep-local-normalized-audio")
        with (
            patch(
                "pastor_transcript_extractor.media_archive."
                "assess_automatic_speaker_observation",
                return_value=self.eligibility,
            ),
            patch(
                "pastor_transcript_extractor.media_archive."
                "get_authoritative_normalized_media_artifact",
                return_value=(
                    self.artifact,
                    SimpleNamespace(status="verified_local", verified=True),
                ),
            ),
            patch(
                "pastor_transcript_extractor.media_archive."
                "_canonical_clip_preparation_status",
                return_value="missing",
            ),
            patch(
                "pastor_transcript_extractor.media_archive.AudioSpanCache.prepare",
                side_effect=OSError("ffmpeg input failed"),
            ),
            patch(
                "pastor_transcript_extractor.media_archive."
                "write_canonical_clip_preparation_manifest"
            ) as write_manifest,
        ):
            result = prepare_canonical_audio(
                self.database,
                self.paths,
                cache_root=self.root / "cache",
                video_ids={self.video.id},
            )

        self.assertEqual(1, result.counts["failed"])
        self.assertEqual(b"keep-local-normalized-audio", normalized_path.read_bytes())
        write_manifest.assert_not_called()

    def test_manifest_policy_hash_fingerprint_and_window_are_exact(self) -> None:
        manifest = Path(self.artifact.manifest_path)
        manifest.write_text("{}", encoding="utf-8")
        clip = self.root / "canonical.wav"
        clip.write_bytes(b"canonical-clip")
        write_canonical_clip_preparation_manifest(
            self.paths,
            self.artifact,
            self.observation,
            clip_paths=(clip,),
            policy_version="older-policy",
        )
        self.assertEqual(
            "stale",
            _canonical_clip_preparation_status(
                self.artifact,
                self.observation,
                CANONICAL_CLIP_PREPARATION_POLICY_VERSION,
            ),
        )
        for changed_artifact, changed_observation in (
            (
                SimpleNamespace(
                    **{
                        **self.artifact.__dict__,
                        "content_sha256": "different-normalized-sha",
                    }
                ),
                self.observation,
            ),
            (
                self.artifact,
                SimpleNamespace(
                    **{
                        **self.observation.__dict__,
                        "input_fingerprint": "different-fingerprint",
                    }
                ),
            ),
            (
                self.artifact,
                SimpleNamespace(
                    **{
                        **self.observation.__dict__,
                        "start_seconds": 121.0,
                    }
                ),
            ),
        ):
            self.assertNotEqual(
                "current",
                _canonical_clip_preparation_status(
                    changed_artifact,
                    changed_observation,
                    "older-policy",
                ),
            )

    def test_existing_valid_manifest_accepts_review_clip_variation(self) -> None:
        first_clip = self.root / "canonical-first.wav"
        second_clip = self.root / "review-second.wav"
        first_clip.write_bytes(b"first-valid-clip")
        second_clip.write_bytes(b"second-valid-clip")

        first_manifest = write_canonical_clip_preparation_manifest(
            self.paths,
            self.artifact,
            self.observation,
            clip_paths=(first_clip,),
        )
        replay_manifest = write_canonical_clip_preparation_manifest(
            self.paths,
            self.artifact,
            self.observation,
            clip_paths=(second_clip,),
        )

        self.assertEqual(first_manifest, replay_manifest)
        self.assertEqual(
            "current",
            _canonical_clip_preparation_status(
                self.artifact,
                self.observation,
                CANONICAL_CLIP_PREPARATION_POLICY_VERSION,
            ),
        )

    def test_new_clip_set_supersedes_stale_manifest_without_mutation(self) -> None:
        stale_clip = self.root / "stale-canonical.wav"
        replacement_clip = self.root / "replacement-canonical.wav"
        stale_clip.write_bytes(b"stale-clip")
        replacement_clip.write_bytes(b"replacement-clip")
        stale_manifest = write_canonical_clip_preparation_manifest(
            self.paths,
            self.artifact,
            self.observation,
            clip_paths=(stale_clip,),
        )
        stale_payload = stale_manifest.read_bytes()
        stale_clip.unlink()

        replacement_manifest = write_canonical_clip_preparation_manifest(
            self.paths,
            self.artifact,
            self.observation,
            clip_paths=(replacement_clip,),
        )

        self.assertNotEqual(stale_manifest, replacement_manifest)
        self.assertEqual(stale_payload, stale_manifest.read_bytes())
        self.assertEqual(
            "current",
            _canonical_clip_preparation_status(
                self.artifact,
                self.observation,
                CANONICAL_CLIP_PREPARATION_POLICY_VERSION,
            ),
        )

    def test_single_video_cli_reports_offline_retry(self) -> None:
        result_payload = SimpleNamespace(
            items=(
                SimpleNamespace(
                    outcome="deferred", youtube_video_id=self.video.youtube_video_id
                ),
            ),
            counts={
                "prepared": 0,
                "would_prepare": 0,
                "already_prepared": 0,
                "deferred": 1,
                "blocked": 0,
                "failed": 0,
            },
        )
        with (
            patch(
                "pastor_transcript_extractor.cli.get_database",
                return_value=self.database,
            ),
            patch(
                "pastor_transcript_extractor.cli.build_paths",
                return_value=self.paths,
            ),
            patch(
                "pastor_transcript_extractor.cli.prepare_canonical_audio",
                return_value=result_payload,
            ),
        ):
            result = CliRunner().invoke(
                app,
                [
                    "media",
                    "prepare-canonical-audio",
                    "--youtube-video-id",
                    self.video.youtube_video_id,
                    "--base-dir",
                    str(self.paths.root),
                ],
            )

        self.assertNotEqual(0, result.exit_code)
        self.assertIn("archived_media_unavailable", result.output)
        self.assertIn("pte media", result.output)
        self.assertIn("prepare-canonical-audio --youtube-video-id canonical001", result.output)


class ExtractionSpeakerBindingTests(unittest.TestCase):
    def test_extraction_passes_authoritative_normalized_identity_to_observation(self) -> None:
        artifact = SimpleNamespace(id=9, content_sha256="normalized-sha")
        database = SimpleNamespace()
        paths = SimpleNamespace()
        video = SimpleNamespace(id=1)
        pastor = SimpleNamespace(id=2)
        extraction = SimpleNamespace(id=3)
        with (
            patch(
                "pastor_transcript_extractor.extraction."
                "get_registered_normalized_media_artifact",
                return_value=artifact,
            ) as select_audio,
            patch(
                "pastor_transcript_extractor.extraction."
                "record_shadow_identity_assessment"
            ) as record,
        ):
            _record_speaker_evidence_safely(
                database,
                paths,
                video=video,
                pastor=pastor,
                extraction_result=extraction,
                content_disposition={"status": "accepted_sermon"},
            )

        select_audio.assert_called_once_with(
            database, video.id, require_isolated_sermon=False
        )
        self.assertIs(
            artifact,
            record.call_args.kwargs["normalized_audio_artifact"],
        )
