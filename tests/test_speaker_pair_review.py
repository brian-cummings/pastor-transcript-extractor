from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.models import SpeakerObservation
from pastor_transcript_extractor.speaker_pair_diagnostics import CachedSpan
from pastor_transcript_extractor.speaker_pair_review import (
    ObservationQualification,
    PairJudgment,
    create_review_draft,
    submit_review,
)


class FakeSpanCache:
    def __init__(self, root: Path):
        self.root = root

    def prepare(self, *, observation, source_audio_path, span):
        key = f"{observation.input_fingerprint}-{span.start_seconds:.3f}"
        digest = hashlib.sha256(key.encode()).hexdigest()
        wav_path = self.root / f"{digest}.wav"
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(key.encode())
        return CachedSpan(
            observation_fingerprint=observation.input_fingerprint,
            start_seconds=span.start_seconds,
            end_seconds=span.end_seconds,
            wav_path=str(wav_path),
            wav_sha256=digest,
            duration_seconds=span.end_seconds - span.start_seconds,
            rms_dbfs=-20.0,
            clipped_fraction=0.0,
            cache_hit=False,
        )


def observation(fingerprint: str, identifier: int) -> SpeakerObservation:
    return SpeakerObservation(
        id=identifier,
        video_id=identifier,
        extraction_result_id=identifier,
        role="principal_speaker_candidate",
        multiplicity_state="unknown",
        start_seconds=100.0,
        end_seconds=1100.0,
        artifact_path="speaker-evidence.json",
        content_sha256="a" * 64,
        extractor_version="speaker_evidence_v1",
        input_fingerprint=fingerprint,
        created_at=datetime.now(timezone.utc),
    )


class SpeakerPairReviewTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.evaluation_root = self.root / "speaker-pairs"
        self.span_cache = FakeSpanCache(self.root / "cache")
        self.observation_a = observation("observation-a", 1)
        self.observation_b = observation("observation-b", 2)

    def tearDown(self):
        self.tempdir.cleanup()

    def _draft(self):
        return create_review_draft(
            observation_a=self.observation_a,
            observation_b=self.observation_b,
            video_id_a="video-a",
            video_id_b="video-b",
            audio_path_a=Path("audio-a.wav"),
            audio_path_b=Path("audio-b.wav"),
            span_cache=self.span_cache,
            evaluation_root=self.evaluation_root,
        )

    def _submit(self, draft, **overrides):
        values = {
            "qualification_a": ObservationQualification.QUALIFIED_SINGLE_SPEAKER,
            "qualification_b": ObservationQualification.QUALIFIED_SINGLE_SPEAKER,
            "pair_judgment": PairJudgment.SAME_SPEAKER,
            "reviewer": "reviewer-1",
            "reviewed_at": "2026-07-15T12:00:00+00:00",
            "variation_tags": ["different_date", "different_microphone"],
            "notes": "Listened to every clip.",
            "approval_confirmed": True,
        }
        values.update(overrides)
        return submit_review(
            draft=draft.payload,
            evaluation_root=self.evaluation_root,
            **values,
        )

    def test_draft_and_blinded_packet_are_deterministic(self):
        first = self._draft()
        first_json = first.draft_path.read_bytes()
        first_html = first.packet_path.read_bytes()
        second = self._draft()
        reversed_draft = create_review_draft(
            observation_a=self.observation_b,
            observation_b=self.observation_a,
            video_id_a="video-b",
            video_id_b="video-a",
            audio_path_a=Path("audio-b.wav"),
            audio_path_b=Path("audio-a.wav"),
            span_cache=self.span_cache,
            evaluation_root=self.evaluation_root,
        )

        self.assertEqual(first.pair_id, second.pair_id)
        self.assertEqual(first.pair_id, reversed_draft.pair_id)
        self.assertEqual(first_json, second.draft_path.read_bytes())
        self.assertEqual(first.payload, reversed_draft.payload)
        self.assertEqual(first_html, second.packet_path.read_bytes())
        packet = first.packet_path.read_text(encoding="utf-8")
        self.assertNotIn("video-a", packet)
        self.assertNotIn("video-b", packet)
        self.assertNotIn("observation-a", packet)
        self.assertIn("Observation A", packet)
        self.assertIn("Observation B", packet)
        self.assertEqual(5, len(first.payload["presentation"]["A"]["clips"]))
        self.assertEqual(5, len(first.payload["presentation"]["B"]["clips"]))

    def test_qualified_explicit_review_creates_exact_frozen_fixture(self):
        draft = self._draft()
        result = self._submit(draft)

        self.assertEqual("created", result.fixture_status)
        self.assertIsNotNone(result.fixture_path)
        fixture = json.loads(result.fixture_path.read_text(encoding="utf-8"))
        event = json.loads(result.event_path.read_text(encoding="utf-8"))
        self.assertEqual("same_speaker", fixture["expected_outcome"])
        self.assertEqual(event["review_event_id"], fixture["review_event_id"])
        self.assertEqual(5, len(fixture["observations"]["a"]["reviewed_spans"]))
        self.assertEqual(5, len(fixture["observations"]["b"]["reviewed_spans"]))
        self.assertNotIn("wav_path", fixture["observations"]["a"]["reviewed_spans"][0])

    def test_unqualified_or_indeterminate_review_remains_append_only_without_fixture(self):
        draft = self._draft()
        result = self._submit(
            draft,
            qualification_a=ObservationQualification.MULTIPLE_SPEAKERS,
            pair_judgment=PairJudgment.CANNOT_DETERMINE,
            approval_confirmed=False,
        )

        self.assertEqual("not_eligible", result.fixture_status)
        self.assertIsNone(result.fixture_path)
        self.assertTrue(result.event_path.exists())
        self.assertFalse((self.evaluation_root / "fixtures").exists())

    def test_unqualified_observation_cannot_receive_binary_pair_label(self):
        draft = self._draft()
        with self.assertRaisesRegex(ValueError, "requires cannot_determine"):
            self._submit(
                draft,
                qualification_b=ObservationQualification.INVALID_AUDIO,
                pair_judgment=PairJudgment.DIFFERENT_SPEAKER,
            )

    def test_rereview_never_overwrites_existing_fixture(self):
        draft = self._draft()
        original = self._submit(draft)
        original_bytes = original.fixture_path.read_bytes()
        consistent = self._submit(
            draft,
            reviewer="reviewer-2",
            reviewed_at="2026-07-16T12:00:00+00:00",
        )
        conflict = self._submit(
            draft,
            reviewer="reviewer-3",
            reviewed_at="2026-07-17T12:00:00+00:00",
            pair_judgment=PairJudgment.DIFFERENT_SPEAKER,
        )

        self.assertEqual("existing_consistent", consistent.fixture_status)
        self.assertEqual("existing_conflict_preserved", conflict.fixture_status)
        self.assertEqual(original_bytes, original.fixture_path.read_bytes())
        events = list((self.evaluation_root / "reviews" / draft.pair_id).glob("*.json"))
        self.assertEqual(3, len(events))

    def test_draft_tampering_is_rejected(self):
        draft = self._draft()
        tampered = json.loads(json.dumps(draft.payload))
        tampered["presentation"]["A"]["clips"].pop()

        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            submit_review(
                draft=tampered,
                qualification_a=ObservationQualification.CANNOT_DETERMINE,
                qualification_b=ObservationQualification.CANNOT_DETERMINE,
                pair_judgment=PairJudgment.CANNOT_DETERMINE,
                reviewer="reviewer",
                reviewed_at="2026-07-15T12:00:00+00:00",
                variation_tags=[],
                notes="",
                approval_confirmed=False,
                evaluation_root=self.evaluation_root,
            )


if __name__ == "__main__":
    unittest.main()
