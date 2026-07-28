from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.speaker_pair_diagnostics import CachedSpan
from pastor_transcript_extractor.speaker_profile_review import (
    ProfileReviewRepresentative,
    write_profile_review_packet,
)


def cached_span(path: Path, fingerprint: str) -> CachedSpan:
    return CachedSpan(
        observation_fingerprint=fingerprint,
        start_seconds=10.0,
        end_seconds=22.0,
        wav_path=str(path),
        wav_sha256=f"hash-{fingerprint}",
        duration_seconds=12.0,
        rms_dbfs=-20.0,
        clipped_fraction=0.0,
        cache_hit=True,
        non_silent_fraction=0.9,
    )


class SpeakerProfileReviewPacketTests(unittest.TestCase):
    def test_packet_reuses_exact_cached_spans_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            current = cached_span(root / "current.wav", "current")
            representative = cached_span(root / "representative.wav", "member")

            first = write_profile_review_packet(
                observation_fingerprint="current-observation",
                spans=(current,),
                representatives=(
                    ProfileReviewRepresentative(
                        profile_id=7,
                        observation_fingerprint="member",
                        spans=(representative,),
                    ),
                ),
                output_root=root,
            )
            replay = write_profile_review_packet(
                observation_fingerprint="current-observation",
                spans=(current,),
                representatives=(
                    ProfileReviewRepresentative(
                        profile_id=7,
                        observation_fingerprint="member",
                        spans=(representative,),
                    ),
                ),
                output_root=root,
            )

            self.assertEqual(first, replay)
            packet = first.read_text(encoding="utf-8")
            self.assertIn((root / "current.wav").resolve().as_uri(), packet)
            self.assertIn((root / "representative.wav").resolve().as_uri(), packet)
            self.assertIn("Anonymous profile #7", packet)
            self.assertIn(
                "source-family filter, when used, only bounds the queue",
                packet,
            )
            self.assertNotIn("acoustic score", packet.lower())


if __name__ == "__main__":
    unittest.main()
