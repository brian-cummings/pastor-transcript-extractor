from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.config import _detect_yt_dlp_js_runtime
from pastor_transcript_extractor.media import (
    NoCaptionsAvailableError,
    VideoNotYetAvailableError,
    VideoUnavailableError,
    YtDlpConfigurationError,
    _run_yt_dlp,
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


if __name__ == "__main__":
    unittest.main()
