from __future__ import annotations

from contextlib import ExitStack
import json
import tempfile
import unittest
from pathlib import Path
from typing import Callable
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor.config import build_paths, build_pastor_paths, build_video_artifact_paths, ensure_directories
from pastor_transcript_extractor.discovery import DiscoveredVideo, extract_discovered_videos, sort_discovered_videos_by_recency
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.media import NoCaptionsAvailableError, VideoUnavailableError
from pastor_transcript_extractor.models import SourceType, TranscriptSegmentLabel, TranscriptSourceKind, VideoStatus
from pastor_transcript_extractor.extraction import extract_video
from pastor_transcript_extractor.exporting import export_pastor_review_markdown
from pastor_transcript_extractor.sources import detect_source_type
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.sermon_detection import detect_guest_speaker_flags, detect_sermon_window
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.transcription import (
    PreparedTranscriptInput,
    _captions_to_plain_text,
    fetch_captions_video,
    transcribe_video,
)
from pastor_transcript_extractor.config import ToolConfig


class DetectSourceTypeTests(unittest.TestCase):
    def test_detect_video_url(self) -> None:
        self.assertIs(detect_source_type("https://www.youtube.com/watch?v=abc123"), SourceType.VIDEO)

    def test_detect_playlist_url(self) -> None:
        self.assertIs(detect_source_type("https://www.youtube.com/playlist?list=PL123"), SourceType.PLAYLIST)

    def test_detect_channel_url(self) -> None:
        self.assertIs(detect_source_type("https://www.youtube.com/@samplechurch"), SourceType.CHANNEL)


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.tempdir.name) / "app.db"
        self.database = Database(self.database_path)
        self.database.initialize()
        self.pastor = self.database.add_pastor("sample-church", "Sample Church")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_add_source_is_idempotent(self) -> None:
        first = self.database.add_source(
            "https://www.youtube.com/watch?v=abc123",
            SourceType.VIDEO,
            pastor_id=self.pastor.id,
        )
        second = self.database.add_source(
            "https://www.youtube.com/watch?v=abc123",
            SourceType.VIDEO,
            pastor_id=self.pastor.id,
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(1, self.database.counts_by_table()["sources"])

    def test_source_timestamp_round_trips(self) -> None:
        source = self.database.add_source(
            "https://www.youtube.com/watch?v=xyz789",
            SourceType.VIDEO,
            pastor_id=self.pastor.id,
        )
        listed = self.database.list_sources()[0]

        self.assertEqual(source.added_at.isoformat(), listed.added_at.isoformat())

    def test_add_source_links_pastor(self) -> None:
        source = self.database.add_source(
            "https://www.youtube.com/watch?v=linked123",
            SourceType.VIDEO,
            pastor_id=self.pastor.id,
        )

        self.assertEqual(self.pastor.id, source.pastor_id)
        self.assertEqual(self.pastor.id, self.database.list_sources()[0].pastor_id)

    def test_excluded_video_round_trips(self) -> None:
        excluded = self.database.add_excluded_video(
            youtube_video_id="abc123def45",
            title="Excluded Sermon",
            url="https://www.youtube.com/watch?v=abc123def45",
            pastor_id=self.pastor.id,
            notes="not a sermon",
        )

        listed = self.database.list_excluded_videos()

        self.assertEqual(1, len(listed))
        self.assertEqual(excluded.youtube_video_id, listed[0].youtube_video_id)
        self.assertEqual("not a sermon", listed[0].notes)

    def test_update_video_status_if_current_only_updates_matching_status(self) -> None:
        source = self.database.add_source(
            "https://www.youtube.com/watch?v=abc123",
            SourceType.VIDEO,
            pastor_id=self.pastor.id,
        )
        video = self.database.add_video(
            source_id=source.id,
            pastor_id=self.pastor.id,
            youtube_video_id="abc123",
            title="Sample Sermon",
            url="https://www.youtube.com/watch?v=abc123",
            status=VideoStatus.DISCOVERED,
        )

        claimed = self.database.update_video_status_if_current(
            video.id,
            current_status=VideoStatus.DISCOVERED,
            new_status=VideoStatus.TRANSCRIBING_LOCAL,
        )
        stale_claim = self.database.update_video_status_if_current(
            video.id,
            current_status=VideoStatus.DISCOVERED,
            new_status=VideoStatus.TRANSCRIBED_LOCAL,
        )

        updated_video = self.database.get_video_by_id(video.id)
        self.assertTrue(claimed)
        self.assertFalse(stale_claim)
        self.assertEqual(VideoStatus.TRANSCRIBING_LOCAL, updated_video.status)


class PathTests(unittest.TestCase):
    def test_pastor_and_video_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_paths(Path(tmp))
            ensure_directories(paths)
            pastor_paths = build_pastor_paths(paths, "sample-church")
            video_paths = build_video_artifact_paths(paths, "sample-church", "abc123")

            self.assertEqual(paths.pastors / "sample-church", pastor_paths.root)
            self.assertEqual(paths.pastors / "sample-church" / "videos" / "abc123", video_paths.root)
            self.assertEqual(video_paths.root / "metadata.json", video_paths.metadata)


class DiscoveryTests(unittest.TestCase):
    def test_extract_discovered_videos_normalizes_entries(self) -> None:
        fake_info = {
            "entries": [
                {
                    "id": "abc123",
                    "title": "Sermon 1",
                    "webpage_url": "https://www.youtube.com/watch?v=abc123",
                    "channel": "Sample Church",
                    "timestamp": 1710000000,
                    "duration": 1234,
                },
                {
                    "id": "def456ghijk",
                    "title": "Sermon 2",
                    "url": "https://www.youtube.com/@samplechurch/videos",
                    "uploader": "Sample Church",
                    "release_timestamp": 1710001111,
                    "ie_key": "Youtube",
                },
            ]
        }

        class FakeCompletedProcess:
            def __init__(self, stdout: str) -> None:
                self.stdout = stdout

        with patch(
            "pastor_transcript_extractor.discovery.subprocess.run",
            return_value=FakeCompletedProcess(stdout=json.dumps(fake_info)),
        ):
            discovered = extract_discovered_videos("https://example.test", "yt-dlp")

        self.assertEqual(
            discovered,
            [
                DiscoveredVideo(
                    youtube_video_id="def456ghijk",
                    title="Sermon 2",
                    url="https://www.youtube.com/watch?v=def456ghijk",
                    channel_name="Sample Church",
                    published_at="2024-03-09T16:18:31+00:00",
                    duration_seconds=None,
                ),
                DiscoveredVideo(
                    youtube_video_id="abc123",
                    title="Sermon 1",
                    url="https://www.youtube.com/watch?v=abc123",
                    channel_name="Sample Church",
                    published_at="2024-03-09T16:00:00+00:00",
                    duration_seconds=1234,
                ),
            ],
        )

    def test_extract_discovered_videos_prefers_canonical_watch_url(self) -> None:
        fake_info = {
            "id": "abcdefghijk",
            "title": "Sermon 3",
            "webpage_url": "https://www.youtube.com/@samplechurch/videos",
            "url": "https://www.youtube.com/@samplechurch/videos",
            "channel": "Sample Church",
            "timestamp": 1710002222,
        }

        class FakeCompletedProcess:
            def __init__(self, stdout: str) -> None:
                self.stdout = stdout

        with patch(
            "pastor_transcript_extractor.discovery.subprocess.run",
            return_value=FakeCompletedProcess(stdout=json.dumps(fake_info)),
        ):
            discovered = extract_discovered_videos("https://example.test", "yt-dlp")

        self.assertEqual(1, len(discovered))
        self.assertEqual("https://www.youtube.com/watch?v=abcdefghijk", discovered[0].url)

    def test_extract_discovered_videos_ignores_channel_payload_without_entries(self) -> None:
        fake_info = {
            "id": "UCmW2jNga9PNkCvXrbCSbbvA",
            "title": "Duluth SDA Church",
            "webpage_url": "https://www.youtube.com/@duluthsdachurch1869",
            "channel": "Duluth SDA Church",
            "ie_key": "YoutubeTab",
        }

        class FakeCompletedProcess:
            def __init__(self, stdout: str) -> None:
                self.stdout = stdout

        with patch(
            "pastor_transcript_extractor.discovery.subprocess.run",
            return_value=FakeCompletedProcess(stdout=json.dumps(fake_info)),
        ):
            discovered = extract_discovered_videos("https://example.test", "yt-dlp")

        self.assertEqual([], discovered)


class SermonDetectionTests(unittest.TestCase):
    def test_detect_sermon_window_picks_main_sermon_block(self) -> None:
        drafts = [
            SegmentDraft(0.0, 120.0, "Welcome everyone and join us next week for potluck.", None, TranscriptSegmentLabel.ANNOUNCEMENTS, 0.75),
            SegmentDraft(120.0, 240.0, "Let us pray and say amen together.", None, TranscriptSegmentLabel.PRAYER, 0.7),
            SegmentDraft(240.0, 720.0, "Turn in your Bibles to John chapter three. Today I want to show you this passage.", None, TranscriptSegmentLabel.READING, 0.7),
            SegmentDraft(720.0, 1320.0, "The word of God teaches us how grace transforms the heart.", None, TranscriptSegmentLabel.SERMON, 0.55),
            SegmentDraft(1320.0, 1500.0, "Amen and thank you for being here.", None, TranscriptSegmentLabel.PRAYER, 0.7),
        ]

        result = detect_sermon_window(drafts)

        self.assertEqual(240.0, result.start_seconds)
        self.assertEqual(1320.0, result.end_seconds)
        self.assertGreater(result.confidence, 0.5)
        self.assertIn("expository language detected inside the selected window", result.reasons)

    def test_detect_sermon_window_returns_none_for_non_sermon_content(self) -> None:
        drafts = [
            SegmentDraft(0.0, 240.0, "Welcome and announcements for next week.", None, TranscriptSegmentLabel.ANNOUNCEMENTS, 0.75),
            SegmentDraft(240.0, 480.0, "Special music and worship song.", None, TranscriptSegmentLabel.MUSIC, 0.8),
            SegmentDraft(480.0, 720.0, "Let us pray amen.", None, TranscriptSegmentLabel.PRAYER, 0.7),
        ]

        result = detect_sermon_window(drafts)

        self.assertIsNone(result.start_seconds)
        self.assertIsNone(result.end_seconds)
        self.assertLess(result.confidence, 0.2)

    def test_detect_sermon_window_merges_short_interruptions(self) -> None:
        drafts = [
            SegmentDraft(0.0, 600.0, "Turn in your Bibles to Romans chapter eight.", None, TranscriptSegmentLabel.READING, 0.7),
            SegmentDraft(600.0, 660.0, "Amen.", None, TranscriptSegmentLabel.PRAYER, 0.7),
            SegmentDraft(660.0, 1380.0, "Today I want to show you the word of God in this passage.", None, TranscriptSegmentLabel.SERMON, 0.55),
        ]

        result = detect_sermon_window(drafts)

        self.assertEqual(0.0, result.start_seconds)
        self.assertEqual(1380.0, result.end_seconds)

    def test_detect_guest_speaker_flags_detects_non_pastor_title_and_intro(self) -> None:
        drafts = [
            SegmentDraft(0.0, 90.0, "We welcome Elder John Smith to bring the message today.", None, TranscriptSegmentLabel.ANNOUNCEMENTS, 0.75),
            SegmentDraft(90.0, 900.0, "Turn in your Bibles to Matthew chapter five.", None, TranscriptSegmentLabel.SERMON, 0.55),
        ]
        sermon_window = detect_sermon_window(drafts)

        result = detect_guest_speaker_flags(
            video_title='Sample Church - Elder John Smith - "Blessed Are"',
            drafts=drafts,
            pastor_name="Andrew Korp",
            sermon_window=sermon_window,
        )

        self.assertTrue(result.suspected)
        self.assertIn("Elder John Smith", result.name_candidates)
        self.assertTrue(any("title names a non-pastor speaker" in reason for reason in result.reasons))

    def test_extract_discovered_videos_recurses_through_channel_tabs(self) -> None:
        fake_info = {
            "id": "@duluthsdachurch1869",
            "title": "Duluth Seventh-Day Adventist Church",
            "_type": "playlist",
            "entries": [
                {
                    "id": "UCmW2jNga9PNkCvXrbCSbbvA",
                    "title": "Duluth Seventh-Day Adventist Church - Videos",
                    "_type": "playlist",
                    "entries": [
                        {
                            "id": "J1cti8karbo",
                            "title": "Sample Sermon",
                            "_type": "url",
                            "ie_key": "Youtube",
                            "url": "https://www.youtube.com/watch?v=J1cti8karbo",
                            "channel": "Duluth Seventh-Day Adventist Church",
                            "duration": 9514.0,
                        }
                    ],
                },
                {
                    "id": "UCmW2jNga9PNkCvXrbCSbbvA",
                    "title": "Duluth Seventh-Day Adventist Church - Live",
                    "_type": "playlist",
                    "entries": [],
                },
            ],
        }

        class FakeCompletedProcess:
            def __init__(self, stdout: str) -> None:
                self.stdout = stdout

        with patch(
            "pastor_transcript_extractor.discovery.subprocess.run",
            return_value=FakeCompletedProcess(stdout=json.dumps(fake_info)),
        ):
            discovered = extract_discovered_videos("https://example.test", "yt-dlp")

        self.assertEqual(1, len(discovered))
        self.assertEqual("J1cti8karbo", discovered[0].youtube_video_id)
        self.assertEqual("https://www.youtube.com/watch?v=J1cti8karbo", discovered[0].url)

    def test_extract_discovered_videos_prioritizes_streams_when_flat_playlist_timestamps_are_missing(self) -> None:
        fake_info = {
            "id": "@duluthsdachurch1869",
            "title": "Duluth Seventh-Day Adventist Church",
            "_type": "playlist",
            "entries": [
                {
                    "id": "videos-tab",
                    "title": "Duluth Seventh-Day Adventist Church - Videos",
                    "_type": "playlist",
                    "webpage_url": "https://www.youtube.com/@duluthsdachurch1869/videos",
                    "entries": [
                        {
                            "id": "oldervideo1a",
                            "title": "Older Upload",
                            "_type": "url",
                            "ie_key": "Youtube",
                            "url": "https://www.youtube.com/watch?v=oldervideo1a",
                            "channel": "Duluth Seventh-Day Adventist Church",
                            "timestamp": None,
                        }
                    ],
                },
                {
                    "id": "live-tab",
                    "title": "Duluth Seventh-Day Adventist Church - Live",
                    "_type": "playlist",
                    "webpage_url": "https://www.youtube.com/@duluthsdachurch1869/streams",
                    "entries": [
                        {
                            "id": "livevideo01a",
                            "title": "Latest Live Stream",
                            "_type": "url",
                            "ie_key": "Youtube",
                            "url": "https://www.youtube.com/watch?v=livevideo01a",
                            "channel": "Duluth Seventh-Day Adventist Church",
                            "timestamp": None,
                        }
                    ],
                },
                {
                    "id": "shorts-tab",
                    "title": "Duluth Seventh-Day Adventist Church - Shorts",
                    "_type": "playlist",
                    "webpage_url": "https://www.youtube.com/@duluthsdachurch1869/shorts",
                    "entries": [
                        {
                            "id": "shortvideo01",
                            "title": "A Short",
                            "_type": "url",
                            "ie_key": "Youtube",
                            "url": "https://www.youtube.com/shorts/shortvideo01",
                            "channel": "Duluth Seventh-Day Adventist Church",
                            "timestamp": None,
                        }
                    ],
                },
            ],
        }

        class FakeCompletedProcess:
            def __init__(self, stdout: str) -> None:
                self.stdout = stdout

        with patch(
            "pastor_transcript_extractor.discovery.subprocess.run",
            return_value=FakeCompletedProcess(stdout=json.dumps(fake_info)),
        ):
            discovered = extract_discovered_videos("https://example.test", "yt-dlp")

        self.assertEqual(
            ["livevideo01a", "oldervideo1a", "shortvideo01"],
            [video.youtube_video_id for video in discovered],
        )

    def test_sort_discovered_videos_by_recency_prefers_newest_live_entries(self) -> None:
        discovered = [
            DiscoveredVideo(
                youtube_video_id="oldervideo1a",
                title="Older Sermon",
                url="https://www.youtube.com/watch?v=oldervideo1a",
                channel_name="Sample Church",
                published_at="2024-03-09T16:00:00+00:00",
                duration_seconds=1234,
            ),
            DiscoveredVideo(
                youtube_video_id="livevideo01a",
                title="Live Stream",
                url="https://www.youtube.com/watch?v=livevideo01a",
                channel_name="Sample Church",
                published_at="2024-03-10T16:00:00+00:00",
                duration_seconds=None,
            ),
            DiscoveredVideo(
                youtube_video_id="unknowndate1",
                title="Unknown Date",
                url="https://www.youtube.com/watch?v=unknowndate1",
                channel_name="Sample Church",
                published_at=None,
                duration_seconds=456,
            ),
        ]

        ordered = sort_discovered_videos_by_recency(discovered)

        self.assertEqual(["livevideo01a", "oldervideo1a", "unknowndate1"], [video.youtube_video_id for video in ordered])

    def test_discover_persists_discovered_status_and_dedupes(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            database.add_pastor("sample-church", "Sample Church")
            database.add_source(
                "https://www.youtube.com/watch?v=source123",
                SourceType.VIDEO,
                pastor_id=1,
            )

            discovered = [
                DiscoveredVideo(
                    youtube_video_id="abc123",
                    title="Sermon 1",
                    url="https://www.youtube.com/watch?v=abc123",
                    channel_name="Sample Church",
                    published_at="2024-03-09T16:00:00+00:00",
                    duration_seconds=1234,
                ),
                DiscoveredVideo(
                    youtube_video_id="abc123",
                    title="Sermon 1 duplicate",
                    url="https://www.youtube.com/watch?v=abc123",
                    channel_name="Sample Church",
                    published_at="2024-03-09T16:00:00+00:00",
                    duration_seconds=1234,
                ),
            ]

            with patch("pastor_transcript_extractor.cli.extract_discovered_videos", return_value=discovered):
                result = runner.invoke(app, ["discover", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            videos = database.list_videos()
            self.assertEqual(1, len(videos))
            self.assertEqual(VideoStatus.DISCOVERED, videos[0].status)
            self.assertIn("skipped 1 duplicate", result.output)

    def test_discover_skips_excluded_videos(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            database.add_source(
                "https://www.youtube.com/watch?v=source123",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            database.add_excluded_video(
                youtube_video_id="abc123def45",
                title="Excluded Sermon",
                url="https://www.youtube.com/watch?v=abc123def45",
                pastor_id=pastor.id,
            )

            discovered = [
                DiscoveredVideo(
                    youtube_video_id="abc123def45",
                    title="Excluded Sermon",
                    url="https://www.youtube.com/watch?v=abc123def45",
                    channel_name="Sample Church",
                    published_at="2024-03-09T16:00:00+00:00",
                    duration_seconds=1234,
                ),
                DiscoveredVideo(
                    youtube_video_id="def456ghijk",
                    title="Included Sermon",
                    url="https://www.youtube.com/watch?v=def456ghijk",
                    channel_name="Sample Church",
                    published_at="2024-03-09T17:00:00+00:00",
                    duration_seconds=2345,
                ),
            ]

            with patch("pastor_transcript_extractor.cli.extract_discovered_videos", return_value=discovered):
                result = runner.invoke(app, ["discover", "--all", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            videos = database.list_videos()
            self.assertEqual(["def456ghijk"], [video.youtube_video_id for video in videos])
            self.assertIn("excluded 1", result.output)

    def test_discover_rerun_only_queues_new_videos(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            database.add_source(
                "https://www.youtube.com/@samplechurch",
                SourceType.CHANNEL,
                pastor_id=pastor.id,
            )

            first_discovered = [
                DiscoveredVideo(
                    youtube_video_id="abc123def45",
                    title="Sermon 1",
                    url="https://www.youtube.com/watch?v=abc123def45",
                    channel_name="Sample Church",
                    published_at="2024-03-09T16:00:00+00:00",
                    duration_seconds=1234,
                )
            ]
            second_discovered = [
                DiscoveredVideo(
                    youtube_video_id="abc123def45",
                    title="Sermon 1",
                    url="https://www.youtube.com/watch?v=abc123def45",
                    channel_name="Sample Church",
                    published_at="2024-03-09T16:00:00+00:00",
                    duration_seconds=1234,
                ),
                DiscoveredVideo(
                    youtube_video_id="def456ghijk",
                    title="Sermon 2",
                    url="https://www.youtube.com/watch?v=def456ghijk",
                    channel_name="Sample Church",
                    published_at="2024-03-10T16:00:00+00:00",
                    duration_seconds=2345,
                ),
            ]

            with patch("pastor_transcript_extractor.cli.extract_discovered_videos", return_value=first_discovered):
                first_result = runner.invoke(app, ["discover", "--all", "--base-dir", str(base_dir)])
            with patch("pastor_transcript_extractor.cli.extract_discovered_videos", return_value=second_discovered):
                second_result = runner.invoke(app, ["discover", "--all", "--base-dir", str(base_dir)])

            self.assertEqual(0, first_result.exit_code, msg=first_result.output)
            self.assertEqual(0, second_result.exit_code, msg=second_result.output)
            videos = database.list_videos()
            self.assertEqual(["abc123def45", "def456ghijk"], [video.youtube_video_id for video in videos])
            self.assertIn("queued 1 new video", second_result.output)
            self.assertIn("skipped 1 duplicate", second_result.output)

    def test_discover_limit_keeps_first_n_results(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            database.add_source(
                "https://www.youtube.com/@samplechurch",
                SourceType.CHANNEL,
                pastor_id=pastor.id,
            )

            discovered = [
                DiscoveredVideo(
                    youtube_video_id="abc123def45",
                    title="Sermon 1",
                    url="https://www.youtube.com/watch?v=abc123def45",
                    channel_name="Sample Church",
                    published_at=None,
                    duration_seconds=1234,
                ),
                DiscoveredVideo(
                    youtube_video_id="def456ghijk",
                    title="Sermon 2",
                    url="https://www.youtube.com/watch?v=def456ghijk",
                    channel_name="Sample Church",
                    published_at=None,
                    duration_seconds=5678,
                ),
            ]

            with patch("pastor_transcript_extractor.cli.extract_discovered_videos", return_value=discovered):
                result = runner.invoke(app, ["discover", "--limit", "1", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            videos = database.list_videos()
            self.assertEqual(1, len(videos))
            self.assertEqual("abc123def45", videos[0].youtube_video_id)

    def test_discover_limit_keeps_most_recent_results_not_raw_source_order(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            database.add_source(
                "https://www.youtube.com/@samplechurch",
                SourceType.CHANNEL,
                pastor_id=pastor.id,
            )

            discovered = [
                DiscoveredVideo(
                    youtube_video_id="oldervideo1a",
                    title="Older Sermon",
                    url="https://www.youtube.com/watch?v=oldervideo1a",
                    channel_name="Sample Church",
                    published_at="2024-03-09T16:00:00+00:00",
                    duration_seconds=1234,
                ),
                DiscoveredVideo(
                    youtube_video_id="livevideo01a",
                    title="Latest Live Stream",
                    url="https://www.youtube.com/watch?v=livevideo01a",
                    channel_name="Sample Church",
                    published_at="2024-03-10T16:00:00+00:00",
                    duration_seconds=None,
                ),
            ]

            with patch("pastor_transcript_extractor.cli.extract_discovered_videos", return_value=discovered):
                result = runner.invoke(app, ["discover", "--limit", "1", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            videos = database.list_videos()
            self.assertEqual(1, len(videos))
            self.assertEqual("livevideo01a", videos[0].youtube_video_id)

    def test_discover_defaults_to_twenty_six_results(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            database.add_source(
                "https://www.youtube.com/@samplechurch",
                SourceType.CHANNEL,
                pastor_id=pastor.id,
            )

            discovered = [
                DiscoveredVideo(
                    youtube_video_id=f"id{i:09d}"[:11],
                    title=f"Sermon {i}",
                    url=f"https://www.youtube.com/watch?v={f'id{i:09d}'[:11]}",
                    channel_name="Sample Church",
                    published_at=None,
                    duration_seconds=100 + i,
                )
                for i in range(30)
            ]

            with patch("pastor_transcript_extractor.cli.extract_discovered_videos", return_value=discovered):
                result = runner.invoke(app, ["discover", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            videos = database.list_videos()
            self.assertEqual(26, len(videos))
            self.assertIn("Found 30 video(s); queued 26 new video(s) after limit 26;", result.output)

    def test_discover_all_overrides_default_limit(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            database.add_source(
                "https://www.youtube.com/@samplechurch",
                SourceType.CHANNEL,
                pastor_id=pastor.id,
            )

            discovered = [
                DiscoveredVideo(
                    youtube_video_id=f"id{i:09d}"[:11],
                    title=f"Sermon {i}",
                    url=f"https://www.youtube.com/watch?v={f'id{i:09d}'[:11]}",
                    channel_name="Sample Church",
                    published_at=None,
                    duration_seconds=100 + i,
                )
                for i in range(30)
            ]

            with patch("pastor_transcript_extractor.cli.extract_discovered_videos", return_value=discovered):
                result = runner.invoke(app, ["discover", "--all", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            videos = database.list_videos()
            self.assertEqual(30, len(videos))

    def test_extract_skips_videos_without_transcripts(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123",
                title="Sermon",
                url="https://www.youtube.com/watch?v=abc123",
                status=VideoStatus.DISCOVERED,
            )

            result = runner.invoke(app, ["extract", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("skipped 1", result.output)
            self.assertIn("failed 0", result.output)


class CliTests(unittest.TestCase):
    def _assert_command_persists_base_dir(
        self,
        command_args: list[str],
        setup: Callable[[Path], None] | None = None,
        extra_patches: list[object] | None = None,
    ) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir(parents=True, exist_ok=True)
            custom_base_dir = Path(tmp) / "documents-appdata"
            if setup is not None:
                setup(custom_base_dir)

            with patch("pastor_transcript_extractor.config.Path.home", return_value=fake_home):
                with ExitStack() as stack:
                    for extra_patch in extra_patches or []:
                        stack.enter_context(extra_patch)
                    result = runner.invoke(
                        app,
                        [*command_args, "--base-dir", str(custom_base_dir)],
                    )
                doctor_result = runner.invoke(app, ["doctor"])
                resolved_root = build_paths().root

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertEqual(0, doctor_result.exit_code, msg=doctor_result.output)
            self.assertEqual(custom_base_dir.resolve(), resolved_root)

    def test_top_level_help_groups_workflows_under_workflow_typer(self) -> None:
        runner = CliRunner()
        result = runner.invoke(app, ["--help"])

        self.assertEqual(0, result.exit_code, msg=result.output)
        self.assertIn("Workflows", result.output)
        self.assertIn("run", result.output)
        self.assertNotIn("\nworkflow ", result.output)

    def test_pastor_add_and_add_source_flow(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            result = runner.invoke(
                app,
                [
                    "pastor",
                    "add",
                    "sample-church",
                    "Sample Church",
                    "--base-dir",
                    str(base_dir),
                ],
            )
            self.assertEqual(0, result.exit_code, msg=result.output)

            result = runner.invoke(
                app,
                [
                    "add",
                    "https://www.youtube.com/watch?v=abc123",
                    "--pastor",
                    "sample-church",
                    "--base-dir",
                    str(base_dir),
                ],
            )
            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("pastor:", result.output)
            self.assertIn("sample-church", result.output)

    def test_init_with_base_dir_persists_default_root_for_future_commands(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir(parents=True, exist_ok=True)
            custom_base_dir = Path(tmp) / "custom-appdata"

            with patch("pastor_transcript_extractor.config.Path.home", return_value=fake_home):
                init_result = runner.invoke(
                    app,
                    ["init", "--base-dir", str(custom_base_dir)],
                )
                doctor_result = runner.invoke(app, ["doctor"])
                resolved_root = build_paths().root

            self.assertEqual(0, init_result.exit_code, msg=init_result.output)
            self.assertEqual(0, doctor_result.exit_code, msg=doctor_result.output)
            self.assertEqual(custom_base_dir.resolve(), resolved_root)

    def test_status_with_base_dir_persists_default_root_for_future_commands(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir(parents=True, exist_ok=True)
            custom_base_dir = Path(tmp) / "documents-appdata"

            with patch("pastor_transcript_extractor.config.Path.home", return_value=fake_home):
                status_result = runner.invoke(
                    app,
                    ["status", "--base-dir", str(custom_base_dir)],
                )
                doctor_result = runner.invoke(app, ["doctor"])
                resolved_root = build_paths().root

            self.assertEqual(0, status_result.exit_code, msg=status_result.output)
            self.assertEqual(0, doctor_result.exit_code, msg=doctor_result.output)
            self.assertEqual(custom_base_dir.resolve(), resolved_root)

    def test_command_codepaths_with_base_dir_persist_default_root_for_future_commands(self) -> None:
        def setup_pastor(base_dir: Path) -> None:
            base_dir.mkdir(parents=True, exist_ok=True)
            database = Database(base_dir / "app.db")
            database.initialize()
            database.add_pastor("sample-church", "Sample Church")

        def setup_source(base_dir: Path) -> None:
            base_dir.mkdir(parents=True, exist_ok=True)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            database.add_source(
                "https://www.youtube.com/watch?v=abc123def45",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )

        def setup_video(base_dir: Path) -> None:
            base_dir.mkdir(parents=True, exist_ok=True)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123def45",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Sermon",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.DISCOVERED,
            )

        def setup_review(base_dir: Path) -> None:
            base_dir.mkdir(parents=True, exist_ok=True)
            database = Database(base_dir / "app.db")
            database.initialize()
            database.add_pastor("sample-church", "Sample Church")

        cases = [
            ("pastor-add", ["pastor", "add", "sample-church", "Sample Church"], None, None),
            (
                "add",
                ["add", "https://www.youtube.com/watch?v=abc123", "--pastor", "sample-church"],
                setup_pastor,
                None,
            ),
            (
                "discover",
                ["discover", "--all"],
                setup_source,
                [patch("pastor_transcript_extractor.cli.extract_discovered_videos", return_value=[])],
            ),
            ("video-list", ["video", "list"], setup_video, None),
            ("source-delete", ["source", "delete", "1", "--force"], setup_source, None),
            ("fetch", ["fetch"], None, None),
            ("transcribe", ["transcribe"], None, None),
            ("extract", ["extract"], None, None),
            ("review", ["review", "sample-church"], setup_review, None),
            ("video-exclude", ["video", "exclude", "1"], setup_video, None),
        ]

        for label, command_args, setup, extra_patches in cases:
            with self.subTest(command=label):
                self._assert_command_persists_base_dir(
                    command_args=command_args,
                    setup=setup,
                    extra_patches=extra_patches,
                )

    def test_run_replace_existing_deletes_source_before_pipeline(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123",
                SourceType.VIDEO,
                pastor_id=1,
            )

            calls: list[tuple[str, tuple, dict]] = []

            def fake_source_delete(*args, **kwargs):
                calls.append(("source_delete", args, kwargs))

            def fake_add(*args, **kwargs):
                calls.append(("add", args, kwargs))

            def fake_stage(*args, **kwargs):
                calls.append(("stage", args, kwargs))

            with patch("pastor_transcript_extractor.cli.source_delete", side_effect=fake_source_delete), patch(
                "pastor_transcript_extractor.cli.add", side_effect=fake_add
            ), patch("pastor_transcript_extractor.cli.discover", side_effect=fake_stage), patch(
                "pastor_transcript_extractor.cli.fetch", side_effect=fake_stage
            ), patch("pastor_transcript_extractor.cli.transcribe", side_effect=fake_stage), patch(
                "pastor_transcript_extractor.cli.extract", side_effect=fake_stage
            ):
                result = runner.invoke(
                    app,
                    [
                        "run",
                        "https://www.youtube.com/watch?v=abc123",
                        "--pastor",
                        "sample-church",
                        "--replace-existing",
                        "--base-dir",
                        str(base_dir),
                    ],
                )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertGreaterEqual(len(calls), 2)
            self.assertEqual("source_delete", calls[0][0])
            self.assertEqual(source.id, calls[0][2]["source_id"])
            self.assertTrue(calls[0][2]["force"])
            self.assertEqual("add", calls[1][0])

    def test_run_transcribes_only_caption_misses_by_default(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            database.add_pastor("sample-church", "Sample Church")

            calls: list[tuple[str, tuple, dict]] = []

            def fake_add(*args, **kwargs):
                calls.append(("add", args, kwargs))

            def fake_discover(*args, **kwargs):
                calls.append(("discover", args, kwargs))

            def fake_fetch(*args, **kwargs):
                calls.append(("fetch", args, kwargs))

            def fake_transcribe(*args, **kwargs):
                calls.append(("transcribe", args, kwargs))

            def fake_extract(*args, **kwargs):
                calls.append(("extract", args, kwargs))

            with patch("pastor_transcript_extractor.cli.add", side_effect=fake_add), patch(
                "pastor_transcript_extractor.cli.discover", side_effect=fake_discover
            ), patch("pastor_transcript_extractor.cli.fetch", side_effect=fake_fetch), patch(
                "pastor_transcript_extractor.cli.transcribe", side_effect=fake_transcribe
            ), patch("pastor_transcript_extractor.cli.extract", side_effect=fake_extract):
                result = runner.invoke(
                    app,
                    [
                        "run",
                        "https://www.youtube.com/@samplechurch",
                        "--pastor",
                        "sample-church",
                        "--limit",
                        "5",
                        "--base-dir",
                        str(base_dir),
                    ],
                )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertEqual("discover", calls[1][0])
            self.assertEqual(5, calls[1][2]["limit"])
            self.assertFalse(calls[1][2]["all_videos"])
            self.assertEqual("transcribe", calls[3][0])
            self.assertTrue(calls[3][2]["captions_missing_only"])

    def test_run_defaults_to_twenty_six_video_limit(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            database.add_pastor("sample-church", "Sample Church")

            calls: list[tuple[str, tuple, dict]] = []

            def fake_stage(name: str):
                def runner(*args, **kwargs):
                    calls.append((name, args, kwargs))
                return runner

            with patch("pastor_transcript_extractor.cli.add", side_effect=fake_stage("add")), patch(
                "pastor_transcript_extractor.cli.discover", side_effect=fake_stage("discover")
            ), patch("pastor_transcript_extractor.cli.fetch", side_effect=fake_stage("fetch")), patch(
                "pastor_transcript_extractor.cli.transcribe", side_effect=fake_stage("transcribe")
            ), patch("pastor_transcript_extractor.cli.extract", side_effect=fake_stage("extract")):
                result = runner.invoke(
                    app,
                    [
                        "run",
                        "https://www.youtube.com/@samplechurch",
                        "--pastor",
                        "sample-church",
                        "--base-dir",
                        str(base_dir),
                    ],
                )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertEqual(26, calls[1][2]["limit"])
            self.assertFalse(calls[1][2]["all_videos"])

    def test_run_all_overrides_default_limit(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            database.add_pastor("sample-church", "Sample Church")

            calls: list[tuple[str, tuple, dict]] = []

            def fake_stage(name: str):
                def runner(*args, **kwargs):
                    calls.append((name, args, kwargs))
                return runner

            with patch("pastor_transcript_extractor.cli.add", side_effect=fake_stage("add")), patch(
                "pastor_transcript_extractor.cli.discover", side_effect=fake_stage("discover")
            ), patch("pastor_transcript_extractor.cli.fetch", side_effect=fake_stage("fetch")), patch(
                "pastor_transcript_extractor.cli.transcribe", side_effect=fake_stage("transcribe")
            ), patch("pastor_transcript_extractor.cli.extract", side_effect=fake_stage("extract")):
                result = runner.invoke(
                    app,
                    [
                        "run",
                        "https://www.youtube.com/@samplechurch",
                        "--pastor",
                        "sample-church",
                        "--all",
                        "--base-dir",
                        str(base_dir),
                    ],
                )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertEqual(26, calls[1][2]["limit"])
            self.assertTrue(calls[1][2]["all_videos"])

    def test_run_captions_only_skips_transcribe(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            database.add_pastor("sample-church", "Sample Church")

            calls: list[tuple[str, tuple, dict]] = []

            def fake_stage(name: str):
                def runner(*args, **kwargs):
                    calls.append((name, args, kwargs))
                return runner

            with patch("pastor_transcript_extractor.cli.add", side_effect=fake_stage("add")), patch(
                "pastor_transcript_extractor.cli.discover", side_effect=fake_stage("discover")
            ), patch("pastor_transcript_extractor.cli.fetch", side_effect=fake_stage("fetch")), patch(
                "pastor_transcript_extractor.cli.transcribe", side_effect=fake_stage("transcribe")
            ), patch("pastor_transcript_extractor.cli.extract", side_effect=fake_stage("extract")):
                result = runner.invoke(
                    app,
                    [
                        "run",
                        "https://www.youtube.com/@samplechurch",
                        "--pastor",
                        "sample-church",
                        "--captions-only",
                        "--base-dir",
                        str(base_dir),
                    ],
                )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertEqual(["add", "discover", "fetch", "extract"], [call[0] for call in calls])

    def test_fetch_treats_missing_captions_as_unavailable_not_failure(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123def45",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Sermon",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.DISCOVERED,
            )

            with patch(
                "pastor_transcript_extractor.cli.fetch_captions_video",
                side_effect=NoCaptionsAvailableError("yt-dlp did not create captions"),
            ):
                result = runner.invoke(app, ["fetch", "--base-dir", str(base_dir)])

            updated_video = database.get_video_by_id(video.id)
            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("No captions for video", result.output)
            self.assertIn("unavailable 1", result.output)
            self.assertEqual(VideoStatus.DISCOVERED, updated_video.status)
            self.assertIsNone(updated_video.failure_reason)

    def test_video_list_shows_discovered_videos(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123def45",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Sermon",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.DISCOVERED,
            )

            result = runner.invoke(app, ["video", "list", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("Videos", result.output)
            self.assertIn("sample-church", result.output)
            self.assertIn("abc123def45", result.output)

    def test_video_list_filters_by_status(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123def45",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Queued Sermon",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.DISCOVERED,
            )
            database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="def456ghijk",
                title="Reviewed Sermon",
                url="https://www.youtube.com/watch?v=def456ghijk",
                status=VideoStatus.NEEDS_REVIEW,
            )

            result = runner.invoke(
                app,
                ["video", "list", "--status", "needs_review", "--base-dir", str(base_dir)],
            )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("Reviewed", result.output)
            self.assertIn("Sermon", result.output)
            self.assertNotIn("Queued Sermon", result.output)

    def test_video_exclude_deletes_local_artifacts_and_persists_exclusion(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            paths = build_paths(base_dir)
            ensure_directories(paths)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123def45",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Exclude Me",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.NEEDS_REVIEW,
            )
            video_paths = build_video_artifact_paths(paths, pastor.slug, video.youtube_video_id)
            video_paths.review.mkdir(parents=True, exist_ok=True)
            (video_paths.review / "approved.md").write_text("# test\n", encoding="utf-8")

            result = runner.invoke(app, ["video", "exclude", str(video.id), "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIsNone(database.get_video_by_id(video.id))
            excluded = database.get_excluded_video_by_youtube_id("abc123def45")
            self.assertIsNotNone(excluded)
            self.assertFalse(video_paths.root.exists())

    def test_review_builds_pastor_markdown_from_extracted_videos(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            paths = build_paths(base_dir)
            ensure_directories(paths)
            database = Database(paths.database)
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            first_video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="First Sermon",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.EXTRACTED,
            )
            second_video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="def456ghijk",
                title="Second Sermon",
                url="https://www.youtube.com/watch?v=def456ghijk",
                status=VideoStatus.EXTRACTED,
            )
            for video in [first_video, second_video]:
                video_dir = build_video_artifact_paths(paths, pastor.slug, video.youtube_video_id)
                video_dir.extracted.mkdir(parents=True, exist_ok=True)
                proposed_path = video_dir.extracted / "proposed.md"
                proposed_path.write_text(f"# {video.title}\n\nHello world.", encoding="utf-8")
                database.add_extraction_result(
                    video_id=video.id,
                    version=1,
                    proposed_text_path=str(proposed_path),
                    proposed_json_path=str(video_dir.extracted / "proposed.json"),
                )

            result = runner.invoke(app, ["review", "sample-church", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            review_path = build_pastor_paths(paths, pastor.slug).exports / "review.md"
            manifest_path = build_pastor_paths(paths, pastor.slug).exports / "review.json"
            self.assertTrue(review_path.exists())
            self.assertTrue(manifest_path.exists())
            review_text = review_path.read_text(encoding="utf-8")
            self.assertIn("# Sample Church Review", review_text)
            self.assertIn("## undated - First Sermon", review_text)
            self.assertIn("## undated - Second Sermon", review_text)
            self.assertIn("Hello world.", review_text)
            self.assertIn("Wrote pastor review markdown", result.output)

    def test_review_regenerates_without_excluded_videos(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            paths = build_paths(base_dir)
            ensure_directories(paths)
            database = Database(paths.database)
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            kept_video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Keep Me",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.EXTRACTED,
            )
            excluded_video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="def456ghijk",
                title="Exclude Me",
                url="https://www.youtube.com/watch?v=def456ghijk",
                status=VideoStatus.EXTRACTED,
            )
            for video in [kept_video, excluded_video]:
                video_dir = build_video_artifact_paths(paths, pastor.slug, video.youtube_video_id)
                video_dir.extracted.mkdir(parents=True, exist_ok=True)
                proposed_path = video_dir.extracted / "proposed.md"
                proposed_path.write_text(f"# {video.title}\n\nHello world.", encoding="utf-8")
                database.add_extraction_result(
                    video_id=video.id,
                    version=1,
                    proposed_text_path=str(proposed_path),
                    proposed_json_path=str(video_dir.extracted / "proposed.json"),
                )

            first_result = runner.invoke(app, ["review", "sample-church", "--base-dir", str(base_dir)])
            exclude_result = runner.invoke(app, ["video", "exclude", str(excluded_video.id), "--base-dir", str(base_dir)])
            second_result = runner.invoke(app, ["review", "sample-church", "--base-dir", str(base_dir)])

            self.assertEqual(0, first_result.exit_code, msg=first_result.output)
            self.assertEqual(0, exclude_result.exit_code, msg=exclude_result.output)
            self.assertEqual(0, second_result.exit_code, msg=second_result.output)
            review_path = build_pastor_paths(paths, pastor.slug).exports / "review.md"
            review_text = review_path.read_text(encoding="utf-8")
            self.assertIn("Keep Me", review_text)
            self.assertNotIn("Exclude Me", review_text)

    def test_review_prepares_missing_extractions_before_building_markdown(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            paths = build_paths(base_dir)
            ensure_directories(paths)
            database = Database(paths.database)
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Auto Extract Me",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.TRANSCRIPT_FETCHED,
            )
            artifact_dir = build_video_artifact_paths(paths, pastor.slug, video.youtube_video_id)
            artifact_dir.raw.mkdir(parents=True, exist_ok=True)
            raw_json_path = artifact_dir.raw / "whisper.json"
            raw_text_path = artifact_dir.raw / "whisper.txt"
            raw_json_path.write_text(
                json.dumps(
                    {
                        "segments": [
                            {
                                "start": 0.0,
                                "end": 5.0,
                                "text": "Welcome everyone.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            raw_text_path.write_text("Welcome everyone.", encoding="utf-8")
            database.add_transcript_artifact(
                video_id=video.id,
                source_kind=TranscriptSourceKind.CAPTIONS,
                audio_path=None,
                raw_json_path=str(raw_json_path),
                raw_text_path=str(raw_text_path),
            )

            result = runner.invoke(app, ["review", "sample-church", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("Prepared 1 video(s) for review; failed 0.", result.output)
            review_path = build_pastor_paths(paths, pastor.slug).exports / "review.md"
            self.assertTrue(review_path.exists())
            self.assertIn("Auto Extract Me", review_path.read_text(encoding="utf-8"))

    def test_transcribe_prints_progress_for_each_video(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123def45",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Queued Sermon",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.DISCOVERED,
            )

            def fake_prepare_transcription_input(*args, **kwargs):
                stage_callback = kwargs.get("stage_callback")
                if stage_callback is not None:
                    stage_callback("downloading")
                    stage_callback("normalizing")
                return PreparedTranscriptInput(
                    video_id=video.id,
                    youtube_video_id=video.youtube_video_id,
                    pastor_id=pastor.id,
                    pastor_slug="sample-church",
                    source_url=video.url,
                    transcript_root=base_dir,
                    metadata_path=base_dir / "metadata.json",
                    normalized_audio_path=base_dir / "normalized.wav",
                    whisper_output_base=base_dir / "whisper",
                )

            def fake_complete_transcription_video(*args, **kwargs):
                progress_callback = kwargs.get("progress_callback")
                stage_callback = kwargs.get("stage_callback")
                if stage_callback is not None:
                    stage_callback("transcribing")
                if progress_callback is not None:
                    progress_callback(42)
                if stage_callback is not None:
                    stage_callback("done")

            with patch(
                "pastor_transcript_extractor.cli.prepare_transcription_input",
                side_effect=fake_prepare_transcription_input,
            ), patch(
                "pastor_transcript_extractor.cli.complete_transcription_video",
                side_effect=fake_complete_transcription_video,
            ):
                result = runner.invoke(app, ["transcribe", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("Transcribing 1 video(s) with 1 worker(s).", result.output)
            self.assertIn(f"[1/1 queued] Transcribing video #{video.id}: Queued Sermon", result.output)
            self.assertIn(f"[video #{video.id} stage] dl", result.output)
            self.assertIn(f"[video #{video.id} stage] norm", result.output)
            self.assertIn(f"[video #{video.id} stage] xcribe", result.output)
            self.assertIn(f"[video #{video.id} progress] 42%", result.output)
            self.assertIn(f"[1/1 finished] Transcribed video #{video.id}", result.output)

    def test_fetch_marks_unavailable_video_as_failed(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123def45",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Sermon",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.DISCOVERED,
            )

            with patch(
                "pastor_transcript_extractor.cli.fetch_captions_video",
                side_effect=VideoUnavailableError("Video unavailable for https://www.youtube.com/watch?v=abc123def45"),
            ):
                result = runner.invoke(app, ["fetch", "--base-dir", str(base_dir)])

            updated_video = database.get_video_by_id(video.id)
            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("Video unavailable for video", result.output)
            self.assertEqual(VideoStatus.FAILED, updated_video.status)
            self.assertIn("Video unavailable", updated_video.failure_reason)

    def test_transcribe_skips_terminal_unavailable_failures(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123def45",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Sermon",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.FAILED,
                failure_reason="Video unavailable for https://www.youtube.com/watch?v=abc123def45",
            )

            with patch("pastor_transcript_extractor.cli.prepare_transcription_input") as mocked_prepare:
                result = runner.invoke(app, ["transcribe", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("skipped 1", result.output)
            mocked_prepare.assert_not_called()

    def test_transcribe_skips_caption_hits_by_default(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123def45",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Captioned Sermon",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.TRANSCRIPT_FETCHED,
            )
            database.add_transcript_artifact(
                video_id=video.id,
                source_kind=TranscriptSourceKind.CAPTIONS,
                audio_path=None,
                raw_json_path=str(base_dir / "captions.json"),
                raw_text_path=str(base_dir / "captions.txt"),
            )

            with patch("pastor_transcript_extractor.cli.prepare_transcription_input") as mocked_prepare:
                result = runner.invoke(app, ["transcribe", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("Transcribed 0 video(s); skipped 1; failed 0.", result.output)
            mocked_prepare.assert_not_called()

    def test_transcribe_all_eligible_includes_caption_hits(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123def45",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Captioned Sermon",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.TRANSCRIPT_FETCHED,
            )
            database.add_transcript_artifact(
                video_id=video.id,
                source_kind=TranscriptSourceKind.CAPTIONS,
                audio_path=None,
                raw_json_path=str(base_dir / "captions.json"),
                raw_text_path=str(base_dir / "captions.txt"),
            )

            fake_prepared = PreparedTranscriptInput(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                pastor_id=pastor.id,
                pastor_slug="sample-church",
                source_url=video.url,
                transcript_root=base_dir,
                metadata_path=base_dir / "metadata.json",
                normalized_audio_path=base_dir / "normalized.wav",
                whisper_output_base=base_dir / "whisper",
            )
            with patch("pastor_transcript_extractor.cli.prepare_transcription_input", return_value=fake_prepared) as mocked_prepare, patch(
                "pastor_transcript_extractor.cli.complete_transcription_video"
            ):
                result = runner.invoke(app, ["transcribe", "--all-eligible", "--base-dir", str(base_dir)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("Transcribing 1 video(s) with 1 worker(s).", result.output)
            mocked_prepare.assert_called_once()

    def test_transcribe_jobs_option_processes_multiple_videos(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123def45",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            first_video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Queued Sermon 1",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.DISCOVERED,
            )
            second_video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="xyz987uvw65",
                title="Queued Sermon 2",
                url="https://www.youtube.com/watch?v=xyz987uvw65",
                status=VideoStatus.DISCOVERED,
            )

            def fake_prepare_transcription_input(*args, **kwargs):
                video_id = args[3]
                stage_callback = kwargs.get("stage_callback")
                if stage_callback is not None:
                    stage_callback("downloading")
                    stage_callback("normalizing")
                youtube_video_id = "abc123def45" if video_id == first_video.id else "xyz987uvw65"
                return PreparedTranscriptInput(
                    video_id=video_id,
                    youtube_video_id=youtube_video_id,
                    pastor_id=pastor.id,
                    pastor_slug="sample-church",
                    source_url=f"https://www.youtube.com/watch?v={youtube_video_id}",
                    transcript_root=base_dir,
                    metadata_path=base_dir / f"{video_id}.json",
                    normalized_audio_path=base_dir / f"{video_id}.wav",
                    whisper_output_base=base_dir / f"{video_id}-whisper",
                )

            with patch(
                "pastor_transcript_extractor.cli.prepare_transcription_input",
                side_effect=fake_prepare_transcription_input,
            ), patch("pastor_transcript_extractor.cli.complete_transcription_video"):
                result = runner.invoke(app, ["transcribe", "--jobs", "2", "--base-dir", str(base_dir)])

            first_updated = database.get_video_by_id(first_video.id)
            second_updated = database.get_video_by_id(second_video.id)
            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("Transcribing 2 video(s) with 2 worker(s).", result.output)
            self.assertIn(f"[1/2 queued] Transcribing video #{first_video.id}: Queued Sermon 1", result.output)
            self.assertIn(f"[2/2 queued] Transcribing video #{second_video.id}: Queued Sermon 2", result.output)
            self.assertIn("Transcribed 2 video(s); skipped 0; failed 0.", result.output)
            self.assertEqual(VideoStatus.TRANSCRIBING_LOCAL, first_updated.status)
            self.assertEqual(VideoStatus.TRANSCRIBING_LOCAL, second_updated.status)


class TranscriptionTests(unittest.TestCase):
    def test_captions_to_plain_text_strips_inline_tags_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            captions_path = Path(tmp) / "sample.en.vtt"
            captions_path.write_text(
                "\n".join(
                    [
                        "WEBVTT",
                        "Kind: captions",
                        "Language: en",
                        "",
                        "Okay,<00:00:05.400><c> good</c><00:00:05.920><c> evening</c><00:00:06.840><c> everyone</c>",
                        "Okay, good evening everyone",
                        "Okay, good evening everyone",
                        "our<00:00:08.240><c> third</c><00:00:08.600><c> night</c>",
                        "our third night",
                    ]
                ),
                encoding="utf-8",
            )

            plain_text = _captions_to_plain_text(captions_path)

            self.assertEqual("Okay, good evening everyone\nour third night\n", plain_text)

    def test_fetch_captions_video_persists_timed_segments_from_vtt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            paths = build_paths(base_dir)
            ensure_directories(paths)
            database = Database(paths.database)
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123def45",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123def45",
                title="Sermon",
                url="https://www.youtube.com/watch?v=abc123def45",
                status=VideoStatus.DISCOVERED,
            )

            tools = ToolConfig(
                whisper_cpp_bin=Path("/fake/whisper-cli"),
                whisper_model_path=Path("/fake/model.bin"),
                ffmpeg_bin="ffmpeg",
                yt_dlp_bin="yt-dlp",
                yt_dlp_js_runtimes=None,
            )

            def fake_download_captions(
                url: str,
                yt_dlp_bin: str,
                output_path: Path,
                yt_dlp_js_runtimes: str | None = None,
            ) -> Path:
                del url, yt_dlp_bin, yt_dlp_js_runtimes
                output_path.parent.mkdir(parents=True, exist_ok=True)
                captions_path = output_path.with_suffix(".en.vtt")
                captions_path.write_text(
                    "\n".join(
                        [
                            "WEBVTT",
                            "",
                            "00:00:01.000 --> 00:00:03.000",
                            "Hello<00:00:01.500><c> there</c>",
                            "",
                            "00:00:03.000 --> 00:00:05.000",
                            "General Kenobi",
                        ]
                    ),
                    encoding="utf-8",
                )
                return captions_path

            with patch("pastor_transcript_extractor.transcription.download_captions", side_effect=fake_download_captions):
                result = fetch_captions_video(database, paths, tools, video.id)

            payload = json.loads(result.raw_json_path.read_text(encoding="utf-8"))
            self.assertEqual(2, len(payload["segments"]))
            self.assertEqual(1.0, payload["segments"][0]["start"])
            self.assertEqual(3.0, payload["segments"][0]["end"])
            self.assertEqual("Hello there", payload["segments"][0]["text"])

    def test_fetch_captions_video_persists_artifacts_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            paths = build_paths(base_dir)
            ensure_directories(paths)
            database = Database(paths.database)
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123",
                title="Sermon",
                url="https://www.youtube.com/watch?v=abc123",
                status=VideoStatus.DISCOVERED,
            )

            tools = ToolConfig(
                whisper_cpp_bin=Path("/fake/whisper-cli"),
                whisper_model_path=Path("/fake/model.bin"),
                ffmpeg_bin="ffmpeg",
                yt_dlp_bin="yt-dlp",
                yt_dlp_js_runtimes=None,
            )

            def fake_download_captions(
                url: str,
                yt_dlp_bin: str,
                output_path: Path,
                yt_dlp_js_runtimes: str | None = None,
            ) -> Path:
                del url, yt_dlp_bin, yt_dlp_js_runtimes
                output_path.parent.mkdir(parents=True, exist_ok=True)
                captions_path = output_path.with_suffix(".en.vtt")
                captions_path.write_text(
                    "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nWelcome everyone.\n",
                    encoding="utf-8",
                )
                return captions_path

            with patch("pastor_transcript_extractor.transcription.download_captions", side_effect=fake_download_captions):
                result = fetch_captions_video(database, paths, tools, video.id)

            latest_artifact = database.get_latest_transcript_artifact_for_video(video.id)
            updated_video = database.get_video_by_id(video.id)

            self.assertIsNotNone(latest_artifact)
            self.assertEqual(TranscriptSourceKind.CAPTIONS, latest_artifact.source_kind)
            self.assertEqual(VideoStatus.TRANSCRIPT_FETCHED, updated_video.status)
            self.assertTrue(result.metadata_path.exists())
            self.assertTrue(result.raw_json_path.exists())
            self.assertTrue(result.raw_text_path.exists())
            self.assertIn("Welcome everyone.", result.raw_text_path.read_text(encoding="utf-8"))

    def test_transcribe_video_persists_artifacts_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            paths = build_paths(base_dir)
            ensure_directories(paths)
            database = Database(paths.database)
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123",
                title="Sermon",
                url="https://www.youtube.com/watch?v=abc123",
                status=VideoStatus.DISCOVERED,
            )

            tools = ToolConfig(
                whisper_cpp_bin=Path("/fake/whisper-cli"),
                whisper_model_path=Path("/fake/model.bin"),
                ffmpeg_bin="ffmpeg",
                yt_dlp_bin="yt-dlp",
                yt_dlp_js_runtimes=None,
            )

            def fake_download_audio(
                url: str,
                yt_dlp_bin: str,
                output_path: Path,
                yt_dlp_js_runtimes: str | None = None,
            ) -> Path:
                del url, yt_dlp_bin, yt_dlp_js_runtimes
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"audio")
                return output_path

            def fake_normalize_audio(input_path: Path, output_path: Path, ffmpeg_bin: str) -> Path:
                del input_path, ffmpeg_bin
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"normalized")
                return output_path

            def fake_run_whisper_cpp(
                whisper_cpp_bin: Path,
                model_path: Path,
                audio_path: Path,
                output_base: Path,
                progress_callback=None,
            ):
                del whisper_cpp_bin, model_path, audio_path
                if progress_callback is not None:
                    progress_callback(50)
                json_path = output_base.with_suffix(".json")
                txt_path = output_base.with_suffix(".txt")
                json_path.write_text("{\"text\": \"hello\"}", encoding="utf-8")
                txt_path.write_text("hello", encoding="utf-8")
                return json_path, txt_path

            with patch("pastor_transcript_extractor.transcription.download_audio", side_effect=fake_download_audio), patch(
                "pastor_transcript_extractor.transcription.normalize_audio", side_effect=fake_normalize_audio
            ), patch("pastor_transcript_extractor.transcription.run_whisper_cpp", side_effect=fake_run_whisper_cpp):
                result = transcribe_video(database, paths, tools, video.id)

            latest_artifact = database.get_latest_transcript_artifact_for_video(video.id)
            updated_video = database.get_video_by_id(video.id)

            self.assertIsNotNone(latest_artifact)
            self.assertEqual(VideoStatus.TRANSCRIBED_LOCAL, updated_video.status)
            self.assertTrue(result.metadata_path.exists())
            self.assertTrue(result.raw_json_path.exists())
            self.assertTrue(result.raw_text_path.exists())
            self.assertEqual("hello", result.raw_text_path.read_text(encoding="utf-8"))
            self.assertEqual(1, database.counts_by_table()["transcript_artifacts"])


class ExtractionTests(unittest.TestCase):
    def test_extract_video_persists_segments_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            paths = build_paths(base_dir)
            ensure_directories(paths)
            database = Database(paths.database)
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123",
                title="Sermon",
                url="https://www.youtube.com/watch?v=abc123",
                status=VideoStatus.TRANSCRIBED_LOCAL,
            )

            artifact_dir = build_video_artifact_paths(paths, pastor.slug, video.youtube_video_id)
            artifact_dir.raw.mkdir(parents=True, exist_ok=True)
            raw_json_path = artifact_dir.raw / "whisper.json"
            raw_text_path = artifact_dir.raw / "whisper.txt"
            raw_json_path.write_text(
                json.dumps(
                    {
                        "text": "Welcome everyone. Today we open with prayer.",
                        "segments": [
                            {
                                "start": 0.0,
                                "end": 4.5,
                                "text": "Welcome everyone.",
                            },
                            {
                                "start": 4.5,
                                "end": 10.0,
                                "text": "Today we open with prayer.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            raw_text_path.write_text("Welcome everyone.\n\nToday we open with prayer.", encoding="utf-8")

            database.add_transcript_artifact(
                video_id=video.id,
                source_kind=TranscriptSourceKind.LOCAL_ASR,
                audio_path=str(artifact_dir.audio / "normalized.wav"),
                raw_json_path=str(raw_json_path),
                raw_text_path=str(raw_text_path),
            )

            result = extract_video(database, paths, video.id)
            second_result = extract_video(database, paths, video.id)
            updated_video = database.get_video_by_id(video.id)
            latest_result = database.get_latest_extraction_result_for_video(video.id)
            segments = database.list_transcript_segments(video.id)

            self.assertIsNotNone(latest_result)
            self.assertEqual(VideoStatus.EXTRACTED, updated_video.status)
            self.assertEqual(2, result.segment_count)
            self.assertEqual(2, second_result.segment_count)
            self.assertTrue(result.proposed_text_path.exists())
            self.assertTrue(result.proposed_json_path.exists())
            self.assertEqual(2, len(segments))
            self.assertEqual("announcements", segments[0].label.value)
            self.assertEqual("prayer", segments[1].label.value)
            self.assertEqual(2, database.counts_by_table()["extraction_results"])
            proposed_markdown = result.proposed_text_path.read_text(encoding="utf-8")
            proposed_json = json.loads(result.proposed_json_path.read_text(encoding="utf-8"))
            self.assertEqual("local_asr", proposed_json["transcript_source"])
            self.assertIn("sermon_window", proposed_json)
            self.assertFalse(proposed_json["guest_speaker_suspected"])
            self.assertEqual([], proposed_json["guest_name_candidates"])
            self.assertIn("- Transcript Source: local_asr", proposed_markdown)
            self.assertIn("- Likely Sermon Window:", proposed_markdown)
            self.assertIn("- Guest Speaker Suspected: no", proposed_markdown)
            self.assertIn("- Duration: 00:10", proposed_markdown)
            self.assertIn("Welcome everyone.", proposed_markdown)
            self.assertIn("Today we open with prayer.", proposed_markdown)

    def test_extract_video_override_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            paths = build_paths(base_dir)
            ensure_directories(paths)
            database = Database(paths.database)
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123",
                title="Sermon",
                url="https://www.youtube.com/watch?v=abc123",
                status=VideoStatus.TRANSCRIBED_LOCAL,
            )

            artifact_dir = build_video_artifact_paths(paths, pastor.slug, video.youtube_video_id)
            artifact_dir.raw.mkdir(parents=True, exist_ok=True)
            artifact_dir.review.mkdir(parents=True, exist_ok=True)
            raw_json_path = artifact_dir.raw / "whisper.json"
            raw_text_path = artifact_dir.raw / "whisper.txt"
            raw_json_path.write_text(
                json.dumps(
                    {
                        "text": "Turn in your Bibles. The word of God shows us grace.",
                        "segments": [
                            {"start": 0.0, "end": 600.0, "text": "Turn in your Bibles to John chapter one."},
                            {"start": 600.0, "end": 1320.0, "text": "The word of God shows us grace in this passage."},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            raw_text_path.write_text("Turn in your Bibles.\nThe word of God shows us grace.", encoding="utf-8")
            (artifact_dir.review / "window_override.json").write_text(
                json.dumps(
                    {
                        "start_seconds": 120.0,
                        "end_seconds": 900.0,
                        "notes": "manual trim",
                        "updated_at": "2026-07-05T00:00:00+00:00",
                        "updated_by": "tester",
                    }
                ),
                encoding="utf-8",
            )

            database.add_transcript_artifact(
                video_id=video.id,
                source_kind=TranscriptSourceKind.LOCAL_ASR,
                audio_path=str(artifact_dir.audio / "normalized.wav"),
                raw_json_path=str(raw_json_path),
                raw_text_path=str(raw_text_path),
            )

            result = extract_video(database, paths, video.id)
            proposed_json = json.loads(result.proposed_json_path.read_text(encoding="utf-8"))

            self.assertEqual("override", proposed_json["sermon_window"]["source"])
            self.assertEqual(120.0, proposed_json["sermon_window"]["start_seconds"])
            self.assertEqual(900.0, proposed_json["sermon_window"]["end_seconds"])
            self.assertIn("manual trim", proposed_json["sermon_window"]["reasons"])

    def test_extract_video_invalid_override_falls_back_to_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            paths = build_paths(base_dir)
            ensure_directories(paths)
            database = Database(paths.database)
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123",
                title="Sermon",
                url="https://www.youtube.com/watch?v=abc123",
                status=VideoStatus.TRANSCRIBED_LOCAL,
            )

            artifact_dir = build_video_artifact_paths(paths, pastor.slug, video.youtube_video_id)
            artifact_dir.raw.mkdir(parents=True, exist_ok=True)
            artifact_dir.review.mkdir(parents=True, exist_ok=True)
            raw_json_path = artifact_dir.raw / "whisper.json"
            raw_text_path = artifact_dir.raw / "whisper.txt"
            raw_json_path.write_text(
                json.dumps(
                    {
                        "text": "Turn in your Bibles. The word of God shows us grace.",
                        "segments": [
                            {"start": 0.0, "end": 600.0, "text": "Turn in your Bibles to John chapter one."},
                            {"start": 600.0, "end": 1320.0, "text": "The word of God shows us grace in this passage."},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            raw_text_path.write_text("Turn in your Bibles.\nThe word of God shows us grace.", encoding="utf-8")
            (artifact_dir.review / "window_override.json").write_text(
                json.dumps({"start_seconds": "bad", "end_seconds": 900.0}),
                encoding="utf-8",
            )

            database.add_transcript_artifact(
                video_id=video.id,
                source_kind=TranscriptSourceKind.LOCAL_ASR,
                audio_path=str(artifact_dir.audio / "normalized.wav"),
                raw_json_path=str(raw_json_path),
                raw_text_path=str(raw_text_path),
            )

            result = extract_video(database, paths, video.id)
            proposed_json = json.loads(result.proposed_json_path.read_text(encoding="utf-8"))

            self.assertEqual("detected", proposed_json["sermon_window"]["source"])
            self.assertTrue(any("invalid override ignored" in reason for reason in proposed_json["sermon_window"]["reasons"]))

    def test_extract_video_prefers_captions_artifact_when_both_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            paths = build_paths(base_dir)
            ensure_directories(paths)
            database = Database(paths.database)
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123",
                title="Pastor Sample Church - Sermon",
                url="https://www.youtube.com/watch?v=abc123",
                status=VideoStatus.TRANSCRIBED_LOCAL,
            )

            artifact_dir = build_video_artifact_paths(paths, pastor.slug, video.youtube_video_id)
            artifact_dir.raw.mkdir(parents=True, exist_ok=True)
            captions_json_path = artifact_dir.raw / "captions.json"
            captions_text_path = artifact_dir.raw / "captions.txt"
            captions_json_path.write_text(
                json.dumps(
                    {
                        "text": "Turn in your Bibles. The word of God is before us.",
                        "segments": [
                            {"start": 0.0, "end": 600.0, "text": "Turn in your Bibles to Romans chapter five."},
                            {"start": 600.0, "end": 1320.0, "text": "The word of God is before us in this passage."},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            captions_text_path.write_text("Turn in your Bibles.\nThe word of God is before us.", encoding="utf-8")

            asr_json_path = artifact_dir.raw / "whisper.json"
            asr_text_path = artifact_dir.raw / "whisper.txt"
            asr_json_path.write_text(
                json.dumps(
                    {
                        "text": "Welcome everyone. Join us next week.",
                        "segments": [
                            {"start": 0.0, "end": 120.0, "text": "Welcome everyone."},
                            {"start": 120.0, "end": 240.0, "text": "Join us next week."},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            asr_text_path.write_text("Welcome everyone.\nJoin us next week.", encoding="utf-8")

            database.add_transcript_artifact(
                video_id=video.id,
                source_kind=TranscriptSourceKind.LOCAL_ASR,
                audio_path=str(artifact_dir.audio / "normalized.wav"),
                raw_json_path=str(asr_json_path),
                raw_text_path=str(asr_text_path),
            )
            database.add_transcript_artifact(
                video_id=video.id,
                source_kind=TranscriptSourceKind.CAPTIONS,
                audio_path=None,
                raw_json_path=str(captions_json_path),
                raw_text_path=str(captions_text_path),
            )

            result = extract_video(database, paths, video.id)
            proposed_json = json.loads(result.proposed_json_path.read_text(encoding="utf-8"))

            self.assertEqual("captions", proposed_json["transcript_source"])
            self.assertEqual(0.0, proposed_json["sermon_window"]["start_seconds"])


class ReviewExportTests(unittest.TestCase):
    def test_export_pastor_review_markdown_persists_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            paths = build_paths(base_dir)
            ensure_directories(paths)
            database = Database(paths.database)
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/watch?v=abc123",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="abc123",
                title="Sermon",
                url="https://www.youtube.com/watch?v=abc123",
                status=VideoStatus.EXTRACTED,
            )

            video_dir = build_video_artifact_paths(paths, pastor.slug, video.youtube_video_id)
            video_dir.extracted.mkdir(parents=True, exist_ok=True)
            proposed_path = video_dir.extracted / "proposed.md"
            proposed_json_path = video_dir.extracted / "proposed.json"
            proposed_path.write_text("# Sermon\n\nHello world.", encoding="utf-8")
            proposed_json_path.write_text(
                json.dumps(
                    {
                        "transcript_source": "captions",
                        "sermon_window": {
                            "start_seconds": 120.0,
                            "end_seconds": 840.0,
                            "confidence": 0.82,
                            "reasons": ["contiguous sermon-like block exceeded the 12 minute minimum"],
                            "method": "rule_based_v1",
                            "source": "detected",
                            "included_segment_indexes": [0, 1],
                            "excluded_segment_indexes": [2],
                        },
                        "guest_speaker_suspected": True,
                        "guest_name_candidates": ["Elder John Smith"],
                        "guest_signal_reasons": ["video title names a non-pastor speaker"],
                    }
                ),
                encoding="utf-8",
            )
            extraction_result = database.add_extraction_result(
                video_id=video.id,
                version=1,
                proposed_text_path=str(proposed_path),
                proposed_json_path=str(proposed_json_path),
            )

            export_result = export_pastor_review_markdown(database, paths, pastor.slug)
            exported_video = database.get_video_by_id(video.id)

            self.assertTrue(export_result.export_path.exists())
            self.assertTrue(export_result.manifest_path.exists())
            self.assertEqual(VideoStatus.EXPORTED, exported_video.status)
            export_text = export_result.export_path.read_text(encoding="utf-8")
            manifest = json.loads(export_result.manifest_path.read_text(encoding="utf-8"))
            self.assertIn("pastor: sample-church", export_text)
            self.assertIn("- Transcript Source: captions", export_text)
            self.assertIn("- Likely Sermon Window: 02:00 - 14:00", export_text)
            self.assertIn("- Guest Speaker Suspected: yes", export_text)
            self.assertEqual("captions", manifest["videos"][0]["transcript_source"])
            self.assertTrue(manifest["videos"][0]["guest_speaker_suspected"])
            self.assertEqual("detected", manifest["videos"][0]["sermon_window"]["source"])


if __name__ == "__main__":
    unittest.main()
