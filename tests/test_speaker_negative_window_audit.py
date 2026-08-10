from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from pastor_transcript_extractor.speaker_negative_window_audit import (
    audit_speaker_negative_windows,
)


class _FakeDatabase:
    def __init__(self, root: Path) -> None:
        self.observations = {
            "old-current": self._observation(1, 1, "old-current", 0.0, 3000.0),
            "old-stale": self._observation(2, 2, "old-stale", 0.0, 3600.0),
            "new-stale": self._observation(3, 2, "new-stale", 600.0, 1800.0),
            "manual-invalid": self._observation(4, 3, "manual-invalid", 900.0, 1500.0),
        }
        self.videos = {
            1: self._video(1, "video-current", 5000),
            2: self._video(2, "video-stale", 4000),
            3: self._video(3, "video-manual", 3000),
        }
        self.actions = {1: "multiple_speakers", 2: "invalid", 4: "invalid"}
        self.extractions = {}
        for video_id, window in {
            1: (0.0, 3000.0),
            2: (600.0, 1800.0),
            3: (900.0, 1500.0),
        }.items():
            path = root / f"proposal-{video_id}.json"
            path.write_text(
                json.dumps(
                    {
                        "sermon_window": {
                            "start_seconds": window[0],
                            "end_seconds": window[1],
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.extractions[video_id] = SimpleNamespace(
                id=video_id, proposed_json_path=str(path)
            )

    @staticmethod
    def _observation(identifier, video_id, fingerprint, start, end):
        return SimpleNamespace(
            id=identifier,
            video_id=video_id,
            input_fingerprint=fingerprint,
            start_seconds=start,
            end_seconds=end,
        )

    @staticmethod
    def _video(identifier, youtube_id, duration):
        return SimpleNamespace(
            id=identifier,
            youtube_video_id=youtube_id,
            duration_seconds=duration,
        )

    def list_speaker_observations(self):
        return list(self.observations.values())

    def get_effective_observation_review_action(self, observation_id):
        return self.actions.get(observation_id)

    def get_speaker_observation_by_fingerprint(self, fingerprint):
        return self.observations.get(fingerprint)

    def get_video_by_id(self, video_id):
        return self.videos.get(video_id)

    def get_video_by_youtube_id(self, youtube_video_id):
        return next(
            (video for video in self.videos.values() if video.youtube_video_id == youtube_video_id),
            None,
        )

    def get_latest_extraction_result_for_video(self, video_id):
        return self.extractions.get(video_id)

    def get_speaker_observation_for_extraction_window(
        self, video_id, extraction_id, *, start_seconds, end_seconds
    ):
        del extraction_id
        return next(
            (
                observation
                for observation in self.observations.values()
                if observation.video_id == video_id
                and observation.start_seconds == start_seconds
                and observation.end_seconds == end_seconds
            ),
            None,
        )


class SpeakerNegativeWindowAuditTests(unittest.TestCase):
    def test_audit_combines_pair_reviews_with_manual_registry_negatives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pair_root = root / "speaker-pairs"
            (pair_root / "drafts").mkdir(parents=True)
            (pair_root / "reviews" / "pair-test").mkdir(parents=True)
            (pair_root / "drafts" / "pair-test.json").write_text(
                json.dumps(
                    {
                        "pair_id": "pair-test",
                        "draft_id": "draft-test",
                        "observations": {
                            "source_a": {
                                "input_fingerprint": "old-current",
                                "youtube_video_id": "video-current",
                                "observation_window": {
                                    "start_seconds": 0.0,
                                    "end_seconds": 3000.0,
                                },
                            },
                            "source_b": {
                                "input_fingerprint": "old-stale",
                                "youtube_video_id": "video-stale",
                                "observation_window": {
                                    "start_seconds": 0.0,
                                    "end_seconds": 3600.0,
                                },
                            },
                        },
                        "presentation": {
                            "A": {"source_key": "source_a"},
                            "B": {"source_key": "source_b"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (pair_root / "reviews" / "pair-test" / "review.json").write_text(
                json.dumps(
                    {
                        "pair_id": "pair-test",
                        "draft_id": "draft-test",
                        "review_event_id": "review-test",
                        "reviewed_at": "2026-07-27T00:00:00+00:00",
                        "qualification": {
                            "A": "multiple_speakers",
                            "B": "invalid_audio",
                        },
                    }
                ),
                encoding="utf-8",
            )
            audit = audit_speaker_negative_windows(_FakeDatabase(root), pair_root)
            self.assertEqual(3, len(audit.records))
            self.assertEqual(2, len(audit.actionable))
            self.assertEqual("video-current", audit.actionable[0].youtube_video_id)
            self.assertIn("broad_window", audit.actionable[0].reason_codes)
            stale = next(record for record in audit.records if record.youtube_video_id == "video-stale")
            self.assertFalse(stale.actionable)
            self.assertIn("stale_observation", stale.reason_codes)
            manual = next(record for record in audit.records if record.youtube_video_id == "video-manual")
            self.assertEqual(("invalid_audio",), manual.qualifications)

            fixtures = root / "fixtures"
            fixtures.mkdir()
            (fixtures / "video-current.json").write_text(
                json.dumps(
                    {
                        "expected_outcome": "sermon",
                        "expected_spans": [
                            {"start_seconds": 0.0, "end_seconds": 3000.0}
                        ],
                        "allowed_interruptions": [],
                    }
                ),
                encoding="utf-8",
            )
            resolved = audit_speaker_negative_windows(_FakeDatabase(root), pair_root)

        confirmed = next(
            record for record in resolved.records if record.youtube_video_id == "video-current"
        )
        self.assertFalse(confirmed.actionable)
        self.assertIn("ground_truth_window_confirmed", confirmed.reason_codes)


if __name__ == "__main__":
    unittest.main()
