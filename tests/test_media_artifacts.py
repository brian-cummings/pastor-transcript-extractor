from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import wave

from pastor_transcript_extractor.config import (
    ToolConfig,
    build_paths,
    build_transcript_artifact_paths,
    build_video_artifact_paths,
    ensure_directories,
)
from pastor_transcript_extractor.media import (
    VideoUnavailableError,
    YtDlpError,
    download_source_audio,
)
from pastor_transcript_extractor.media_archive import (
    archive_source_media,
    archive_status,
    media_archive_lock_held,
)
from pastor_transcript_extractor.media_artifacts import (
    audit_media_coverage,
    backfill_existing_media_artifacts,
    ensure_audio_for_video,
    register_media_file,
    resolve_normalized_audio_path,
)
from pastor_transcript_extractor.models import SourceType, TranscriptSourceKind, VideoStatus
from pastor_transcript_extractor.storage import Database


def write_wav(
    path: Path,
    *,
    sample_rate: int = 16000,
    channels: int = 1,
    value: int = 1000,
    duration_seconds: int = 1,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as destination:
        destination.setnchannels(channels)
        destination.setsampwidth(2)
        destination.setframerate(sample_rate)
        frame = value.to_bytes(2, "little", signed=True) * channels
        destination.writeframes(frame * sample_rate * duration_seconds)


class MediaArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.paths = build_paths(Path(self.tempdir.name))
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.pastor = self.database.add_pastor("sample", "Sample Pastor")
        self.source = self.database.add_source(
            "https://www.youtube.com/@sample",
            SourceType.CHANNEL,
            pastor_id=self.pastor.id,
        )
        self.tools = ToolConfig(
            whisper_cpp_bin=Path("whisper"),
            whisper_model_path=Path("model"),
            ffmpeg_bin="ffmpeg",
            yt_dlp_bin="yt-dlp",
            yt_dlp_js_runtimes=None,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _video(
        self,
        identifier: str,
        *,
        isolated: bool = True,
        sermon_end_seconds: float = 0.8,
        video_duration_seconds: int = 1800,
    ):
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=self.pastor.id,
            youtube_video_id=identifier,
            title=f"Sermon {identifier}",
            url=f"https://www.youtube.com/watch?v={identifier}",
            channel_name="Sample Church",
            published_at="2026-07-01T12:00:00+00:00",
            duration_seconds=video_duration_seconds,
            status=VideoStatus.EXTRACTED,
        )
        video_paths = build_video_artifact_paths(
            self.paths, self.pastor.slug, video.youtube_video_id
        )
        video_paths.extracted.mkdir(parents=True, exist_ok=True)
        proposed_path = video_paths.extracted / "proposed.json"
        proposed_path.write_text(
            json.dumps(
                {
                    "sermon_window": (
                        {
                            "start_seconds": 0.1,
                            "end_seconds": sermon_end_seconds,
                        }
                        if isolated
                        else {"start_seconds": None, "end_seconds": None}
                    ),
                    "final_disposition": {
                        "status": "accepted_sermon" if isolated else "rejected_no_sermon"
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self.database.add_extraction_result(
            video_id=video.id,
            version=1,
            proposed_text_path=str(video_paths.extracted / "proposed.md"),
            proposed_json_path=str(proposed_path),
        )
        return video, proposed_path

    def test_backfill_marks_existing_audio_reconstructed_without_modifying_it(self) -> None:
        video, _ = self._video("existing001")
        transcript_paths = build_transcript_artifact_paths(
            self.paths, self.pastor.slug, video.youtube_video_id
        )
        write_wav(transcript_paths.audio_download, sample_rate=44100, channels=2)
        write_wav(transcript_paths.audio_normalized)
        original_hash = hashlib.sha256(transcript_paths.audio_normalized.read_bytes()).hexdigest()
        original_mtime = transcript_paths.audio_normalized.stat().st_mtime_ns
        self.database.add_transcript_artifact(
            video_id=video.id,
            source_kind=TranscriptSourceKind.LOCAL_ASR,
            audio_path=str(transcript_paths.audio_normalized),
        )

        first = backfill_existing_media_artifacts(
            self.database, self.paths, video_id=video.id
        )
        second = backfill_existing_media_artifacts(
            self.database, self.paths, video_id=video.id
        )

        self.assertEqual(2, first.artifacts_registered)
        self.assertEqual(1, first.attempts_registered)
        self.assertEqual(0, second.artifacts_registered)
        self.assertEqual(0, second.attempts_registered)
        self.assertEqual(
            original_hash,
            hashlib.sha256(transcript_paths.audio_normalized.read_bytes()).hexdigest(),
        )
        self.assertEqual(original_mtime, transcript_paths.audio_normalized.stat().st_mtime_ns)
        artifacts = self.database.list_media_artifacts_for_video(video.id)
        self.assertEqual(["source_audio", "normalized_audio"], [item.artifact_kind for item in artifacts])
        self.assertTrue(all(item.provenance_kind == "reconstructed_existing" for item in artifacts))
        manifest = json.loads(Path(artifacts[-1].manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(
            "reconstructed_without_original_tool_snapshot",
            manifest["source_snapshot_semantics"],
        )

    def test_source_download_preserves_native_audio_instead_of_requesting_wav(self) -> None:
        output = self.paths.root / "work" / "source"
        captured: list[str] = []

        def fake_run(command, **_kwargs):
            captured.extend(command)
            native = output.with_suffix(".webm")
            native.parent.mkdir(parents=True, exist_ok=True)
            native.write_bytes(b"native-compressed-audio")

        with patch("pastor_transcript_extractor.media._run_yt_dlp", side_effect=fake_run):
            result = download_source_audio("https://example.test/video", "yt-dlp", output)

        self.assertEqual(".webm", result.suffix)
        self.assertIn("bestaudio/best", captured)
        self.assertNotIn("-x", captured)
        self.assertNotIn("--audio-format", captured)

    def test_caption_backed_sermon_acquires_audio_without_transcription(self) -> None:
        video, proposed_path = self._video("caption001")
        self.database.add_transcript_artifact(
            video_id=video.id,
            source_kind=TranscriptSourceKind.CAPTIONS,
            audio_path=None,
            raw_json_path="captions.json",
            raw_text_path="captions.txt",
        )
        proposed_before = proposed_path.read_bytes()
        transcript_count = self.database.counts_by_table()["transcript_artifacts"]

        def fake_download(_url, _bin, output_path, _runtimes):
            write_wav(output_path, sample_rate=44100, channels=2, value=1200)
            return output_path

        def fake_normalize(_input_path, output_path, _ffmpeg):
            write_wav(output_path, value=800)
            return output_path

        with patch(
            "pastor_transcript_extractor.media_artifacts.download_source_audio",
            side_effect=fake_download,
        ) as download, patch(
            "pastor_transcript_extractor.media_artifacts.normalize_audio",
            side_effect=fake_normalize,
        ):
            first = ensure_audio_for_video(
                self.database,
                self.paths,
                self.tools,
                video_id=video.id,
                tool_versions={"yt-dlp": "test-yt", "ffmpeg": "test-ffmpeg"},
            )
            counts_after_first = self.database.counts_by_table()
            second = ensure_audio_for_video(
                self.database,
                self.paths,
                self.tools,
                video_id=video.id,
                tool_versions={"yt-dlp": "test-yt", "ffmpeg": "test-ffmpeg"},
            )

        self.assertEqual("verified", first.outcome)
        self.assertTrue(first.downloaded)
        self.assertEqual("verified", second.outcome)
        self.assertFalse(second.downloaded)
        download.assert_called_once()
        self.assertEqual(2, counts_after_first["media_artifacts"])
        self.assertEqual(1, counts_after_first["media_acquisition_attempts"])
        self.assertEqual(counts_after_first, self.database.counts_by_table())
        self.assertEqual(
            transcript_count,
            self.database.counts_by_table()["transcript_artifacts"],
        )
        self.assertEqual(proposed_before, proposed_path.read_bytes())
        self.assertEqual(
            Path(first.artifact.artifact_path),
            resolve_normalized_audio_path(self.database, video.id),
        )

    def test_unavailable_and_failed_are_persisted_separately(self) -> None:
        unavailable_video, _ = self._video("unavailable1")
        failed_video, _ = self._video("failed00001")
        with patch(
            "pastor_transcript_extractor.media_artifacts.download_source_audio",
            side_effect=VideoUnavailableError("not available"),
        ):
            unavailable = ensure_audio_for_video(
                self.database,
                self.paths,
                self.tools,
                video_id=unavailable_video.id,
                tool_versions={"yt-dlp": "test", "ffmpeg": "test"},
            )
        with patch(
            "pastor_transcript_extractor.media_artifacts.download_source_audio",
            side_effect=YtDlpError("temporary extractor failure"),
        ):
            failed = ensure_audio_for_video(
                self.database,
                self.paths,
                self.tools,
                video_id=failed_video.id,
                tool_versions={"yt-dlp": "test", "ffmpeg": "test"},
            )

        self.assertEqual(
            ("unavailable", "video_unavailable"),
            (unavailable.outcome, unavailable.reason_code),
        )
        self.assertEqual(
            ("failed", "media_acquisition_failed"),
            (failed.outcome, failed.reason_code),
        )
        attempts = self.database.list_media_acquisition_attempts()
        self.assertEqual(["unavailable", "failed"], [attempt.outcome for attempt in attempts])
        self.assertEqual(0, self.database.counts_by_table()["media_artifacts"])
        coverage = audit_media_coverage(self.database)
        self.assertEqual((unavailable_video.youtube_video_id,), coverage.unavailable)
        self.assertEqual((failed_video.youtube_video_id,), coverage.failed)

    def test_non_sermon_is_skipped_without_download_or_attempt(self) -> None:
        video, _ = self._video("nosermon001", isolated=False)
        with patch(
            "pastor_transcript_extractor.media_artifacts.download_source_audio"
        ) as download:
            result = ensure_audio_for_video(
                self.database,
                self.paths,
                self.tools,
                video_id=video.id,
                tool_versions={"yt-dlp": "test", "ffmpeg": "test"},
            )

        self.assertFalse(result.eligible)
        self.assertEqual("skipped", result.outcome)
        download.assert_not_called()
        self.assertEqual(0, self.database.counts_by_table()["media_acquisition_attempts"])

    def test_incomplete_reconstructed_audio_is_not_resolved_as_usable(self) -> None:
        video, _ = self._video("incomplete01", sermon_end_seconds=10.0)
        transcript_paths = build_transcript_artifact_paths(
            self.paths, self.pastor.slug, video.youtube_video_id
        )
        write_wav(transcript_paths.audio_normalized)
        self.database.add_transcript_artifact(
            video_id=video.id,
            source_kind=TranscriptSourceKind.LOCAL_ASR,
            audio_path=str(transcript_paths.audio_normalized),
        )

        result = backfill_existing_media_artifacts(
            self.database, self.paths, video_id=video.id
        )

        self.assertEqual(1, result.artifacts_registered)
        attempt = self.database.get_latest_media_acquisition_attempt(video.id)
        self.assertIsNotNone(attempt)
        self.assertEqual("failed", attempt.outcome)
        self.assertEqual("reconstructed_audio_incomplete", attempt.reason_code)
        self.assertIsNone(resolve_normalized_audio_path(self.database, video.id))
        coverage = audit_media_coverage(self.database)
        self.assertEqual((video.youtube_video_id,), coverage.corrupt)

    def test_full_video_audio_is_valid_when_transcript_endpoint_overshoots(self) -> None:
        video, _ = self._video(
            "overshoot001",
            sermon_end_seconds=10.0,
            video_duration_seconds=8,
        )
        transcript_paths = build_transcript_artifact_paths(
            self.paths, self.pastor.slug, video.youtube_video_id
        )
        write_wav(transcript_paths.audio_normalized, duration_seconds=8)
        self.database.add_transcript_artifact(
            video_id=video.id,
            source_kind=TranscriptSourceKind.LOCAL_ASR,
            audio_path=str(transcript_paths.audio_normalized),
        )

        backfill_existing_media_artifacts(self.database, self.paths, video_id=video.id)

        self.assertEqual(
            transcript_paths.audio_normalized.resolve(),
            resolve_normalized_audio_path(self.database, video.id),
        )
        attempt = self.database.get_latest_media_acquisition_attempt(video.id)
        self.assertIsNotNone(attempt)
        self.assertEqual("verified", attempt.outcome)
        coverage = audit_media_coverage(self.database)
        self.assertEqual((video.youtube_video_id,), coverage.verified)

    def test_truncated_audio_is_not_validated_by_endpoint_overshoot(self) -> None:
        video, _ = self._video(
            "truncated001",
            sermon_end_seconds=10.0,
            video_duration_seconds=8,
        )
        transcript_paths = build_transcript_artifact_paths(
            self.paths, self.pastor.slug, video.youtube_video_id
        )
        write_wav(transcript_paths.audio_normalized, duration_seconds=5)
        self.database.add_transcript_artifact(
            video_id=video.id,
            source_kind=TranscriptSourceKind.LOCAL_ASR,
            audio_path=str(transcript_paths.audio_normalized),
        )

        backfill_existing_media_artifacts(self.database, self.paths, video_id=video.id)

        self.assertIsNone(resolve_normalized_audio_path(self.database, video.id))
        coverage = audit_media_coverage(self.database)
        self.assertEqual((video.youtube_video_id,), coverage.corrupt)

    def test_newer_incomplete_artifact_does_not_hide_older_verified_audio(self) -> None:
        video, _ = self._video("fallback001", sermon_end_seconds=8.0)
        media_root = build_video_artifact_paths(
            self.paths, self.pastor.slug, video.youtube_video_id
        ).audio
        valid_path = media_root / "valid.wav"
        incomplete_path = media_root / "incomplete.wav"
        write_wav(valid_path, duration_seconds=8)
        write_wav(incomplete_path)
        valid = register_media_file(
            self.database,
            self.paths,
            video=video,
            pastor_slug=self.pastor.slug,
            artifact_path=valid_path,
            artifact_kind="normalized_audio",
            provenance_kind="derived",
            acquisition_tool="test",
            acquisition_tool_version="1",
        )
        register_media_file(
            self.database,
            self.paths,
            video=video,
            pastor_slug=self.pastor.slug,
            artifact_path=incomplete_path,
            artifact_kind="normalized_audio",
            provenance_kind="derived",
            acquisition_tool="test",
            acquisition_tool_version="1",
        )

        self.assertEqual(
            Path(valid.artifact_path),
            resolve_normalized_audio_path(self.database, video.id),
        )
        coverage = audit_media_coverage(self.database)
        self.assertEqual((video.youtube_video_id,), coverage.verified)

    def test_source_archive_records_path_and_replaces_source_with_verified_symlink(self) -> None:
        video, _ = self._video("archive001")
        audio_root = build_video_artifact_paths(
            self.paths, self.pastor.slug, video.youtube_video_id
        ).audio
        source_path = audio_root / "media" / "source-test.webm"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"compressed-source-audio")
        source = register_media_file(
            self.database,
            self.paths,
            video=video,
            pastor_slug=self.pastor.slug,
            artifact_path=source_path,
            artifact_kind="source_audio",
            provenance_kind="original_download",
            acquisition_tool="test",
            acquisition_tool_version="1",
        )
        normalized_path = audio_root / "media" / "normalized-test.wav"
        write_wav(normalized_path)
        register_media_file(
            self.database,
            self.paths,
            video=video,
            pastor_slug=self.pastor.slug,
            artifact_path=normalized_path,
            artifact_kind="normalized_audio",
            provenance_kind="derived",
            acquisition_tool="test",
            acquisition_tool_version="1",
            parent=source,
        )
        other_video, _ = self._video("archive002")
        other_audio_root = build_video_artifact_paths(
            self.paths, self.pastor.slug, other_video.youtube_video_id
        ).audio
        other_source_path = other_audio_root / "media" / "source-test.webm"
        other_source_path.parent.mkdir(parents=True, exist_ok=True)
        other_source_path.write_bytes(b"other-compressed-source-audio")
        other_source = register_media_file(
            self.database,
            self.paths,
            video=other_video,
            pastor_slug=self.pastor.slug,
            artifact_path=other_source_path,
            artifact_kind="source_audio",
            provenance_kind="original_download",
            acquisition_tool="test",
            acquisition_tool_version="1",
        )
        other_normalized_path = other_audio_root / "media" / "normalized-test.wav"
        write_wav(other_normalized_path)
        register_media_file(
            self.database,
            self.paths,
            video=other_video,
            pastor_slug=self.pastor.slug,
            artifact_path=other_normalized_path,
            artifact_kind="normalized_audio",
            provenance_kind="derived",
            acquisition_tool="test",
            acquisition_tool_version="1",
            parent=other_source,
        )
        archive_root = self.paths.root / "nas"
        archive_root.mkdir()
        progress_events = []
        preflight_events = []

        first = archive_source_media(
            self.database,
            self.paths,
            archive_root=archive_root,
            video_ids={video.id},
            progress_callback=progress_events.append,
            preflight_callback=preflight_events.append,
        )
        second = archive_source_media(
            self.database, self.paths, video_ids={video.id}
        )

        self.assertEqual(1, first.counts["archived"])
        self.assertEqual(1, second.counts["already_archived"])
        self.assertEqual(
            [
                "verifying local source",
                "copying to NAS",
                "verifying NAS checksum",
                "linking archived source",
                "complete",
            ],
            [event.stage for event in progress_events],
        )
        self.assertEqual("archived", progress_events[-1].outcome)
        self.assertEqual(
            [
                "archive lock",
                "destination",
                "mount",
                "write probe",
                "persisted state",
                "eligibility",
                "eligibility",
                "recovery markers",
                "capacity",
            ],
            [event.check for event in preflight_events],
        )
        self.assertTrue(
            all(event.status != "failed" for event in preflight_events)
        )
        self.assertTrue(source_path.is_symlink())
        self.assertFalse(other_source_path.is_symlink())
        archived_path = archive_root / source_path.relative_to(self.paths.root)
        self.assertEqual(archived_path.resolve(), source_path.resolve())
        self.assertEqual(b"compressed-source-audio", archived_path.read_bytes())
        status = archive_status(self.database)
        self.assertEqual(str(archive_root.resolve()), status.destination.archive_root)
        self.assertEqual({"pending": 0, "archived": 1, "failed": 0}, status.counts)
        entry = status.entries[0]
        self.assertEqual(str(source_path.resolve(strict=False)), str(archived_path.resolve()))
        self.assertEqual(str(archived_path), entry.archive_path)
        self.assertEqual(
            ["archived", "already_archived"],
            [attempt.outcome for attempt in self.database.list_media_archive_attempts()],
        )

    def test_source_archive_persists_unavailable_attempt_and_retries_later(self) -> None:
        video, _ = self._video("retryarchive")
        audio_root = build_video_artifact_paths(
            self.paths, self.pastor.slug, video.youtube_video_id
        ).audio
        source_path = audio_root / "downloaded.wav"
        normalized_path = audio_root / "normalized.wav"
        write_wav(source_path, sample_rate=44100, channels=2)
        write_wav(normalized_path)
        source = register_media_file(
            self.database,
            self.paths,
            video=video,
            pastor_slug=self.pastor.slug,
            artifact_path=source_path,
            artifact_kind="source_audio",
            provenance_kind="reconstructed_existing",
            acquisition_tool="test",
            acquisition_tool_version="1",
        )
        register_media_file(
            self.database,
            self.paths,
            video=video,
            pastor_slug=self.pastor.slug,
            artifact_path=normalized_path,
            artifact_kind="normalized_audio",
            provenance_kind="reconstructed_existing",
            acquisition_tool="test",
            acquisition_tool_version="1",
            parent=source,
        )
        unavailable_root = self.paths.root / "temporarily-unmounted-nas"

        unavailable = archive_source_media(
            self.database,
            self.paths,
            archive_root=unavailable_root,
        )
        self.assertEqual(1, unavailable.counts["destination_unavailable"])
        self.assertFalse(source_path.is_symlink())
        self.assertEqual("pending", archive_status(self.database).entries[0].status)

        unavailable_root.mkdir()
        retried = archive_source_media(self.database, self.paths)

        self.assertEqual(1, retried.counts["archived"])
        self.assertTrue(source_path.is_symlink())
        replay = backfill_existing_media_artifacts(
            self.database, self.paths, video_id=video.id
        )
        self.assertEqual(0, replay.artifacts_registered)
        self.assertEqual(
            ["destination_unavailable", "archived"],
            [attempt.outcome for attempt in self.database.list_media_archive_attempts()],
        )

    def test_source_archive_accepts_complete_normalized_negative_recording(self) -> None:
        video, _ = self._video(
            "archivenegative",
            isolated=False,
            video_duration_seconds=1,
        )
        audio_root = build_video_artifact_paths(
            self.paths, self.pastor.slug, video.youtube_video_id
        ).audio
        source_path = audio_root / "downloaded.wav"
        normalized_path = audio_root / "normalized.wav"
        write_wav(source_path, sample_rate=44100, channels=2)
        write_wav(normalized_path)
        source = register_media_file(
            self.database,
            self.paths,
            video=video,
            pastor_slug=self.pastor.slug,
            artifact_path=source_path,
            artifact_kind="source_audio",
            provenance_kind="reconstructed_existing",
            acquisition_tool="test",
            acquisition_tool_version="1",
        )
        register_media_file(
            self.database,
            self.paths,
            video=video,
            pastor_slug=self.pastor.slug,
            artifact_path=normalized_path,
            artifact_kind="normalized_audio",
            provenance_kind="reconstructed_existing",
            acquisition_tool="test",
            acquisition_tool_version="1",
            parent=source,
        )
        archive_root = self.paths.root / "negative-archive"
        archive_root.mkdir()

        result = archive_source_media(
            self.database,
            self.paths,
            archive_root=archive_root,
            video_ids={video.id},
        )

        self.assertEqual(1, result.counts["archived"])
        self.assertTrue(source_path.is_symlink())
        self.assertTrue(normalized_path.is_file())

    def test_source_archive_refuses_a_concurrent_process(self) -> None:
        with patch(
            "pastor_transcript_extractor.media_archive.fcntl.flock",
            side_effect=BlockingIOError,
        ):
            with self.assertRaisesRegex(ValueError, "Another media archive process"):
                archive_source_media(self.database, self.paths)

    def test_media_archive_lock_reports_a_concurrent_process(self) -> None:
        with patch(
            "pastor_transcript_extractor.media_archive.fcntl.flock",
            side_effect=BlockingIOError,
        ):
            self.assertTrue(media_archive_lock_held(self.paths.root))

    def test_source_archive_can_wait_for_a_concurrent_process(self) -> None:
        attempts = 0

        def contested_lock(*args):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise BlockingIOError

        archive_root = self.paths.root / "waited-archive"
        archive_root.mkdir()
        preflight_events = []
        with (
            patch(
                "pastor_transcript_extractor.media_archive.fcntl.flock",
                side_effect=contested_lock,
            ),
            patch("pastor_transcript_extractor.media_archive.time.sleep") as sleep,
        ):
            result = archive_source_media(
                self.database,
                self.paths,
                archive_root=archive_root,
                wait_for_lock=True,
                lock_retry_seconds=0.01,
                preflight_callback=preflight_events.append,
            )

        self.assertEqual(0, result.eligible)
        sleep.assert_called_once_with(0.01)
        self.assertEqual(
            [("archive lock", "waiting"), ("archive lock", "passed")],
            [
                (event.check, event.status)
                for event in preflight_events
                if event.check == "archive lock"
            ],
        )

    def test_video_deletion_removes_media_rows_but_not_shared_registry_profiles(self) -> None:
        video, _ = self._video("deletion001")
        transcript_paths = build_transcript_artifact_paths(
            self.paths, self.pastor.slug, video.youtube_video_id
        )
        write_wav(transcript_paths.audio_normalized)
        self.database.add_transcript_artifact(
            video_id=video.id,
            source_kind=TranscriptSourceKind.LOCAL_ASR,
            audio_path=str(transcript_paths.audio_normalized),
        )
        backfill_existing_media_artifacts(self.database, self.paths, video_id=video.id)
        self.assertEqual(1, self.database.counts_by_table()["media_artifacts"])

        self.database.delete_video(video.id)

        self.assertEqual(0, self.database.counts_by_table()["media_artifacts"])
        self.assertEqual(0, self.database.counts_by_table()["media_acquisition_attempts"])


if __name__ == "__main__":
    unittest.main()
