from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pastor_transcript_extractor.config import _detect_yt_dlp_js_runtime
from pastor_transcript_extractor.media import (
    AUDIO_NORMALIZATION_TIMEOUT_SECONDS,
    NoCaptionsAvailableError,
    VideoNotYetAvailableError,
    VideoUnavailableError,
    YtDlpError,
    YtDlpConfigurationError,
    YtDlpRateLimitError,
    _run_yt_dlp,
    download_source_audio,
    normalize_audio,
)


class YtDlpErrorClassificationTests(unittest.TestCase):
    def _run_with_stderr(self, stderr: str, *, expect_captions: bool = False) -> None:
        completed = subprocess.CompletedProcess(["yt-dlp"], 1, stdout="", stderr=stderr)
        with patch("pastor_transcript_extractor.media.subprocess.run", return_value=completed):
            _run_yt_dlp(
                ["yt-dlp", "https://example.test/video"],
                url="https://example.test/video",
                expect_captions=expect_captions,
            )

    def test_missing_js_solver_is_configuration_error_not_video_unavailable(self) -> None:
        stderr = "\n".join(
            (
                "WARNING: No supported JavaScript runtime could be found.",
                "ERROR: This video is not available",
            )
        )

        with self.assertRaises(YtDlpConfigurationError):
            self._run_with_stderr(stderr)

    def test_no_captions_uses_full_output_not_only_last_line(self) -> None:
        stderr = "\n".join(
            (
                "There are no subtitles for the requested languages",
                "ERROR: subtitle download failed",
            )
        )

        with self.assertRaises(NoCaptionsAvailableError):
            self._run_with_stderr(stderr, expect_captions=True)

    def test_future_livestream_is_retryable(self) -> None:
        with self.assertRaises(VideoNotYetAvailableError):
            self._run_with_stderr("ERROR: This live event will begin in 20 hours")

    def test_real_unavailable_error_remains_terminal(self) -> None:
        with self.assertRaises(VideoUnavailableError):
            self._run_with_stderr("ERROR: This video is not available")

    def test_rate_limit_is_classified_separately(self) -> None:
        with self.assertRaises(YtDlpRateLimitError):
            self._run_with_stderr(
                "ERROR: Unable to download API page: HTTP Error 429: Too Many Requests"
            )

    def test_error_line_wins_over_trailing_stdout_info(self) -> None:
        completed = subprocess.CompletedProcess(
            ["yt-dlp"],
            1,
            stdout="[info] video: Downloading 1 format(s): 251\n",
            stderr="ERROR: unable to download video data: HTTP Error 403: Forbidden\n",
        )
        with patch(
            "pastor_transcript_extractor.media.subprocess.run",
            return_value=completed,
        ), self.assertRaisesRegex(YtDlpError, "HTTP Error 403"):
            _run_yt_dlp(
                ["yt-dlp", "https://example.test/video"],
                url="https://example.test/video",
            )

    def test_audio_download_retries_403_with_embedded_player_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "source"
            commands: list[list[str]] = []

            def fake_run(command: list[str], **_kwargs: object) -> None:
                commands.append(command)
                if len(commands) == 1:
                    raise YtDlpError(
                        "ERROR: unable to download video data: HTTP Error 403: Forbidden"
                    )
                output.with_suffix(".webm").write_bytes(b"audio")

            with patch(
                "pastor_transcript_extractor.media._run_yt_dlp",
                side_effect=fake_run,
            ):
                result = download_source_audio(
                    "https://www.youtube.com/watch?v=test",
                    "yt-dlp",
                    output,
                )

        self.assertEqual(".webm", result.suffix)
        self.assertEqual(2, len(commands))
        self.assertNotIn("--extractor-args", commands[0])
        self.assertIn("--extractor-args", commands[1])
        self.assertIn("youtube:player_client=web_embedded", commands[1])

    def test_audio_download_does_not_retry_non_403_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "pastor_transcript_extractor.media._run_yt_dlp",
            side_effect=YtDlpError("temporary extractor failure"),
        ) as run:
            with self.assertRaisesRegex(YtDlpError, "temporary extractor failure"):
                download_source_audio(
                    "https://www.youtube.com/watch?v=test",
                    "yt-dlp",
                    Path(tmp) / "source",
                )

        run.assert_called_once()


class YtDlpRuntimeDetectionTests(unittest.TestCase):
    def test_detects_node_when_deno_is_missing(self) -> None:
        resolved = {"deno": None, "node": "/opt/homebrew/bin/node"}
        with patch(
            "pastor_transcript_extractor.config.shutil.which",
            side_effect=lambda command: resolved.get(command),
        ):
            self.assertEqual("node:/opt/homebrew/bin/node", _detect_yt_dlp_js_runtime())

    def test_returns_none_when_no_supported_runtime_exists(self) -> None:
        with patch("pastor_transcript_extractor.config.shutil.which", return_value=None):
            self.assertIsNone(_detect_yt_dlp_js_runtime())


class AudioNormalizationTests(unittest.TestCase):
    def test_ffmpeg_cannot_read_terminal_input_and_has_a_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.webm"
            output = root / "normalized.wav"
            source.write_bytes(b"source")

            def complete_normalization(*_args, **_kwargs):
                output.write_bytes(b"normalized")
                return subprocess.CompletedProcess(["ffmpeg"], 0)

            with patch(
                "pastor_transcript_extractor.media.subprocess.run",
                side_effect=complete_normalization,
            ) as run:
                result = normalize_audio(source, output, "ffmpeg")

        self.assertEqual(output, result)
        command = run.call_args.args[0]
        self.assertIn("-nostdin", command)
        self.assertIn("-xerror", command)
        self.assertIs(subprocess.DEVNULL, run.call_args.kwargs["stdin"])
        self.assertEqual(
            AUDIO_NORMALIZATION_TIMEOUT_SECONDS,
            run.call_args.kwargs["timeout"],
        )

    def test_normalization_timeout_propagates_as_subprocess_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "pastor_transcript_extractor.media.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["ffmpeg"], 600),
        ), self.assertRaises(subprocess.TimeoutExpired):
            normalize_audio(
                Path(tmp) / "source.webm",
                Path(tmp) / "normalized.wav",
                "ffmpeg",
            )


if __name__ == "__main__":
    unittest.main()
