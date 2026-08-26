from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_pair_eligibility import (
    AutomaticSpeakerObservationEligibility,
    assess_automatic_speaker_observation,
    select_verified_automatic_speaker_pair,
)
from pastor_transcript_extractor.speaker_pair_selector import (
    PairCandidateObservation,
    PairSelection,
)
from pastor_transcript_extractor.storage import Database


class SpeakerPairEligibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.paths = build_paths(Path(self.tempdir.name))
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
            youtube_video_id="accepted001",
            title="Accepted sermon",
            url="https://www.youtube.com/watch?v=accepted001",
            channel_name="Sample Church",
            published_at="2026-07-01T14:00:00+00:00",
            duration_seconds=2400,
            status=VideoStatus.EXTRACTED,
        )
        self.proposed_path = self.paths.root / "proposed.json"
        self.payload = {
            "sermon_window": {
                "source": "detected",
                "start_seconds": 120.0,
                "end_seconds": 1800.0,
            },
            "final_disposition": {"status": "accepted_sermon"},
        }
        self._write_payload()
        self.extraction = self.database.add_extraction_result(
            video_id=self.video.id,
            version=1,
            proposed_text_path=str(self.paths.root / "proposed.md"),
            proposed_json_path=str(self.proposed_path),
        )
        self.observation = self._add_observation(
            extraction_result_id=self.extraction.id,
            start_seconds=120.0,
            end_seconds=1800.0,
            fingerprint="current-observation",
        )
        self.media = SimpleNamespace(
            format_name="wav",
            sample_rate_hz=16_000,
            channel_count=1,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_payload(self) -> None:
        self.proposed_path.write_text(
            json.dumps(self.payload, sort_keys=True),
            encoding="utf-8",
        )

    def _add_observation(
        self,
        *,
        extraction_result_id: int,
        start_seconds: float,
        end_seconds: float,
        fingerprint: str,
    ):
        return self.database.add_speaker_observation(
            video_id=self.video.id,
            extraction_result_id=extraction_result_id,
            role="principal_speaker_candidate",
            multiplicity_state="unknown",
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            artifact_path=str(self.paths.root / f"{fingerprint}.json"),
            content_sha256=f"sha-{fingerprint}",
            extractor_version="speaker_evidence_v1",
            input_fingerprint=fingerprint,
        )

    def _assess(self):
        with patch(
            "pastor_transcript_extractor.speaker_pair_eligibility."
            "get_verified_normalized_media_artifact",
            return_value=self.media,
        ):
            return assess_automatic_speaker_observation(
                self.database,
                self.video.id,
            )

    def test_accepted_current_observation_is_eligible(self) -> None:
        result = self._assess()

        self.assertTrue(result.eligible)
        self.assertEqual(self.observation.id, result.observation.id)
        self.assertEqual(5, len(result.diagnostic_spans))
        self.assertIs(self.media, result.media_artifact)

    def test_matching_window_wins_over_later_incompatible_observation(self) -> None:
        self._add_observation(
            extraction_result_id=self.extraction.id,
            start_seconds=120.0,
            end_seconds=1600.0,
            fingerprint="later-incompatible-observation",
        )

        result = self._assess()

        self.assertTrue(result.eligible)
        self.assertEqual(self.observation.id, result.observation.id)

    def test_unreadable_latest_extraction_is_excluded(self) -> None:
        self.proposed_path.unlink()

        result = self._assess()

        self.assertFalse(result.eligible)
        self.assertEqual("extraction_artifact_unreadable", result.reason_code)

    def test_missing_verified_media_is_excluded(self) -> None:
        with patch(
            "pastor_transcript_extractor.speaker_pair_eligibility."
            "get_verified_normalized_media_artifact",
            return_value=None,
        ):
            result = assess_automatic_speaker_observation(
                self.database,
                self.video.id,
            )

        self.assertFalse(result.eligible)
        self.assertEqual(
            "verified_normalized_media_unavailable",
            result.reason_code,
        )

    def test_metadata_only_status_eligibility_does_not_verify_media(self) -> None:
        with (
            patch(
                "pastor_transcript_extractor.speaker_pair_eligibility."
                "get_registered_normalized_media_artifact",
                return_value=self.media,
            ) as registered,
            patch(
                "pastor_transcript_extractor.speaker_pair_eligibility."
                "get_verified_normalized_media_artifact"
            ) as verified,
        ):
            result = assess_automatic_speaker_observation(
                self.database,
                self.video.id,
                verify_media=False,
            )

        self.assertTrue(result.eligible)
        registered.assert_called_once_with(self.database, self.video.id)
        verified.assert_not_called()

    def test_selected_pair_only_is_verified(self) -> None:
        candidates = [
            PairCandidateObservation(
                input_fingerprint=fingerprint,
                video_id=f"video-{fingerprint}",
                recording_date=None,
            )
            for fingerprint in ("a", "b", "c")
        ]
        videos = {
            candidate.video_id: SimpleNamespace(id=index)
            for index, candidate in enumerate(candidates, start=1)
        }
        database = SimpleNamespace(get_video_by_youtube_id=videos.get)

        def select_pair(remaining):
            return PairSelection(remaining[0], remaining[1], {})

        fingerprints_by_id = {
            video.id: candidate.input_fingerprint
            for candidate, video in zip(candidates, videos.values())
        }

        def assess(_database, video_id, **_kwargs):
            return AutomaticSpeakerObservationEligibility(
                "eligible",
                observation=SimpleNamespace(
                    input_fingerprint=fingerprints_by_id[video_id]
                ),
                media_artifact=self.media,
            )

        with patch(
            "pastor_transcript_extractor.speaker_pair_eligibility."
            "assess_automatic_speaker_observation",
            side_effect=assess,
        ) as assess_mock:
            result = select_verified_automatic_speaker_pair(
                database,
                candidates,
                select_pair=select_pair,
            )

        self.assertEqual("a", result.selection.observation_a.input_fingerprint)
        self.assertEqual("b", result.selection.observation_b.input_fingerprint)
        self.assertEqual(1, result.selection_attempts)
        self.assertEqual({}, result.rejection_counts)
        self.assertEqual(
            [1, 2],
            [call.args[1] for call in assess_mock.call_args_list],
        )
        self.assertTrue(
            all(
                call.kwargs["verify_media"]
                for call in assess_mock.call_args_list
            )
        )

    def test_failed_selected_media_advances_deterministically(self) -> None:
        candidates = [
            PairCandidateObservation(
                input_fingerprint=fingerprint,
                video_id=f"video-{fingerprint}",
                recording_date=None,
            )
            for fingerprint in ("a", "b", "c", "d")
        ]
        videos = {
            candidate.video_id: SimpleNamespace(id=index)
            for index, candidate in enumerate(candidates, start=1)
        }
        database = SimpleNamespace(get_video_by_youtube_id=videos.get)

        def select_pair(remaining):
            return PairSelection(remaining[0], remaining[1], {})

        fingerprints_by_id = {
            video.id: candidate.input_fingerprint
            for candidate, video in zip(candidates, videos.values())
        }

        def assess(_database, video_id, **_kwargs):
            if video_id == 1:
                return AutomaticSpeakerObservationEligibility(
                    "verified_normalized_media_unavailable"
                )
            return AutomaticSpeakerObservationEligibility(
                "eligible",
                observation=SimpleNamespace(
                    input_fingerprint=fingerprints_by_id[video_id]
                ),
                media_artifact=self.media,
            )

        with patch(
            "pastor_transcript_extractor.speaker_pair_eligibility."
            "assess_automatic_speaker_observation",
            side_effect=assess,
        ) as assess_mock:
            result = select_verified_automatic_speaker_pair(
                database,
                candidates,
                select_pair=select_pair,
            )

        self.assertEqual("b", result.selection.observation_a.input_fingerprint)
        self.assertEqual("c", result.selection.observation_b.input_fingerprint)
        self.assertEqual(2, result.selection_attempts)
        self.assertEqual(
            {"verified_normalized_media_unavailable": 1},
            result.rejection_counts,
        )
        self.assertEqual(
            [1, 2, 2, 3],
            [call.args[1] for call in assess_mock.call_args_list],
        )

    def test_review_required_recording_is_excluded(self) -> None:
        self.payload["final_disposition"] = {"status": "review_required"}
        self._write_payload()

        result = self._assess()

        self.assertFalse(result.eligible)
        self.assertEqual("disposition_not_accepted", result.reason_code)

    def test_review_required_recording_can_supply_boundary_review_evidence(self) -> None:
        self.payload["final_disposition"] = {"status": "review_required"}
        self._write_payload()

        with patch(
            "pastor_transcript_extractor.speaker_pair_eligibility."
            "get_verified_normalized_media_artifact",
            return_value=self.media,
        ):
            result = assess_automatic_speaker_observation(
                self.database,
                self.video.id,
                allow_review_required=True,
            )

        self.assertTrue(result.eligible)
        self.assertEqual(self.observation.id, result.observation.id)

    def test_rejected_recording_is_excluded_even_with_valid_window(self) -> None:
        self.payload["final_disposition"] = {"status": "rejected_no_sermon"}
        self._write_payload()

        result = self._assess()

        self.assertFalse(result.eligible)
        self.assertEqual("disposition_not_accepted", result.reason_code)

    def test_missing_malformed_and_unknown_dispositions_are_excluded(self) -> None:
        cases = (
            (None, "disposition_missing_or_malformed"),
            ("accepted_sermon", "disposition_missing_or_malformed"),
            ({"status": 7}, "disposition_missing_or_malformed"),
            ({"status": "unknown"}, "disposition_not_accepted"),
        )
        for disposition, reason_code in cases:
            with self.subTest(disposition=disposition):
                if disposition is None:
                    self.payload.pop("final_disposition", None)
                else:
                    self.payload["final_disposition"] = disposition
                self._write_payload()

                result = self._assess()

                self.assertFalse(result.eligible)
                self.assertEqual(reason_code, result.reason_code)

    def test_observation_tied_to_older_extraction_is_excluded(self) -> None:
        self.database.add_extraction_result(
            video_id=self.video.id,
            version=2,
            proposed_text_path=str(self.paths.root / "proposed-v2.md"),
            proposed_json_path=str(self.proposed_path),
        )

        result = self._assess()

        self.assertFalse(result.eligible)
        self.assertEqual("observation_not_current_extraction", result.reason_code)

    def test_observation_with_obsolete_window_boundaries_is_excluded(self) -> None:
        self.payload["sermon_window"] = {
            "source": "hybrid_llm",
            "start_seconds": 240.0,
            "end_seconds": 1700.0,
        }
        self._write_payload()

        result = self._assess()

        self.assertFalse(result.eligible)
        self.assertEqual("observation_window_mismatch", result.reason_code)

    def test_accepted_manual_override_remains_eligible(self) -> None:
        self.payload["sermon_window"]["source"] = "override"
        self.payload["final_disposition"] = {
            "status": "accepted_sermon",
            "manual_content_override_present": True,
        }
        self._write_payload()

        result = self._assess()

        self.assertTrue(result.eligible)

    def test_stale_observation_cannot_reenter_after_disposition_changes(self) -> None:
        self.assertTrue(self._assess().eligible)

        for status in ("review_required", "rejected_ambiguous_speakers"):
            with self.subTest(status=status):
                self.payload["final_disposition"] = {"status": status}
                self._write_payload()

                result = self._assess()

                self.assertFalse(result.eligible)
                self.assertEqual("disposition_not_accepted", result.reason_code)


if __name__ == "__main__":
    unittest.main()
