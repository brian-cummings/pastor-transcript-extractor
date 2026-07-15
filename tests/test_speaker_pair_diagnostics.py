from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import wave

from pastor_transcript_extractor.models import SpeakerObservation
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    AudioSpanCache,
    CachedSpan,
    DecisionPolicy,
    EmbeddingCache,
    ModelSpec,
    PairOutcome,
    analyze_observation_pair,
    evaluate_reviewed_pair_results,
    select_diagnostic_spans,
    validate_reviewed_pair_fixture,
    write_pair_result,
)
from pastor_transcript_extractor.storage import Database


class FakeSpanCache:
    def __init__(self, root: Path, *, fail: bool = False):
        self.root = root
        self.fail = fail

    def prepare(self, *, observation, source_audio_path, span):
        if self.fail:
            raise OSError("decoder unavailable")
        key = f"{observation.input_fingerprint}-{span.start_seconds:.3f}"
        digest = hashlib.sha256(key.encode()).hexdigest()
        return CachedSpan(
            observation_fingerprint=observation.input_fingerprint,
            start_seconds=span.start_seconds,
            end_seconds=span.end_seconds,
            wav_path=str(self.root / f"{key}.wav"),
            wav_sha256=digest,
            duration_seconds=span.end_seconds - span.start_seconds,
            rms_dbfs=-20.0,
            clipped_fraction=0.0,
            cache_hit=False,
        )


class FakeBackend:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = 0
        digest = hashlib.sha256(repr(sorted(vectors.items())).encode()).hexdigest()
        self.spec = ModelSpec("fake", "review-test", digest, "1")

    def embed(self, wav_path):
        self.calls += 1
        observation = Path(wav_path).name.split("-")[0]
        return self.vectors[observation]


def observation(fingerprint: str, *, start: float = 100.0, end: float = 1100.0):
    return SpeakerObservation(
        id=1,
        video_id=1,
        extraction_result_id=1,
        role="principal_speaker_candidate",
        multiplicity_state="unknown",
        start_seconds=start,
        end_seconds=end,
        artifact_path="speaker-evidence.json",
        content_sha256="b" * 64,
        extractor_version="speaker_evidence_v1",
        input_fingerprint=fingerprint,
        created_at=datetime.now(timezone.utc),
    )


def approved_policy() -> DecisionPolicy:
    return DecisionPolicy(
        version="test-only-v1",
        min_valid_spans=2,
        min_within_median=0.95,
        same_min_cross_p10=0.98,
        same_min_cross_median=0.99,
        different_max_cross_p90=0.10,
    )


class SpeakerPairDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.a = observation("obsA")
        self.b = replace(observation("obsB"), id=2, video_id=2)

    def tearDown(self):
        self.tempdir.cleanup()

    def _analyze(self, backend, *, policy=None, span_cache=None):
        return analyze_observation_pair(
            observation_a=self.a,
            observation_b=self.b,
            audio_path_a=Path("a.wav"),
            audio_path_b=Path("b.wav"),
            span_cache=span_cache or FakeSpanCache(self.root),
            embedding_cache=EmbeddingCache(self.root / "cache"),
            backend=backend,
            policy=policy,
            span_count=3,
        )

    def test_span_selection_is_deterministic_and_avoids_edges(self):
        first = select_diagnostic_spans(self.a, count=3, duration_seconds=12)
        second = select_diagnostic_spans(self.a, count=3, duration_seconds=12)

        self.assertEqual(first, second)
        self.assertEqual(250.0, first[0].start_seconds)
        self.assertEqual(950.0, first[-1].end_seconds)

    def test_without_approved_policy_valid_analysis_abstains_and_replays_exactly(self):
        backend = FakeBackend({"obsA": (1.0, 0.0), "obsB": (1.0, 0.0)})
        first = self._analyze(backend)
        first_calls = backend.calls
        second = self._analyze(backend)

        self.assertEqual(PairOutcome.INSUFFICIENT_EVIDENCE, first["outcome"])
        self.assertEqual("decision_policy_unavailable", first["reason"])
        self.assertEqual(first, second)
        self.assertEqual(first_calls, backend.calls)
        self.assertFalse(first["registry_mutation_allowed"])

        first_path = self.root / "first.json"
        second_path = self.root / "second.json"
        write_pair_result(first_path, first)
        write_pair_result(second_path, second)
        self.assertEqual(first_path.read_bytes(), second_path.read_bytes())

    def test_audio_span_cache_verifies_nested_manifest_checksum_on_replay(self):
        source = self.root / "source.wav"
        source.write_bytes(b"source-present")
        cache = AudioSpanCache(self.root / "audio-cache")
        span = select_diagnostic_spans(self.a, count=3)[0]

        def fake_ffmpeg(arguments, **_kwargs):
            with wave.open(arguments[-1], "wb") as destination:
                destination.setnchannels(1)
                destination.setsampwidth(2)
                destination.setframerate(16000)
                destination.writeframes((1000).to_bytes(2, "little", signed=True) * (16000 * 12))

        with patch(
            "pastor_transcript_extractor.speaker_pair_diagnostics.subprocess.run",
            side_effect=fake_ffmpeg,
        ):
            first = cache.prepare(observation=self.a, source_audio_path=source, span=span)
        replay = cache.prepare(observation=self.a, source_audio_path=source, span=span)

        self.assertFalse(first.cache_hit)
        self.assertTrue(replay.cache_hit)
        self.assertEqual(first.wav_sha256, replay.wav_sha256)

    def test_approved_policy_has_wide_same_different_and_abstention_regions(self):
        same = self._analyze(
            FakeBackend({"obsA": (1.0, 0.0), "obsB": (1.0, 0.0)}),
            policy=approved_policy(),
        )
        different = self._analyze(
            FakeBackend({"obsA": (1.0, 0.0), "obsB": (0.0, 1.0)}),
            policy=approved_policy(),
        )
        borderline = self._analyze(
            FakeBackend({"obsA": (1.0, 0.0), "obsB": (0.8, 0.6)}),
            policy=approved_policy(),
        )

        self.assertEqual(PairOutcome.SAME_SPEAKER, same["outcome"])
        self.assertEqual(PairOutcome.DIFFERENT_SPEAKER, different["outcome"])
        self.assertEqual(PairOutcome.INSUFFICIENT_EVIDENCE, borderline["outcome"])
        self.assertEqual("ambiguous_similarity", borderline["reason"])

    def test_missing_evidence_is_distinct_from_technical_failure(self):
        backend = FakeBackend({"obsA": (1.0, 0.0), "obsB": (0.0, 1.0)})
        missing = analyze_observation_pair(
            observation_a=None,
            observation_b=self.b,
            audio_path_a=None,
            audio_path_b=Path("b.wav"),
            span_cache=FakeSpanCache(self.root),
            embedding_cache=EmbeddingCache(self.root),
            backend=backend,
        )
        failed = self._analyze(backend, span_cache=FakeSpanCache(self.root, fail=True))

        self.assertEqual(PairOutcome.INSUFFICIENT_EVIDENCE, missing["outcome"])
        self.assertEqual("observation_unavailable", missing["reason"])
        self.assertEqual(PairOutcome.ANALYSIS_FAILED, failed["outcome"])
        self.assertEqual("technical_failure", failed["reason"])

    def test_fixture_requires_reviewed_identity_and_exact_span_hashes(self):
        payload = self._fixture_payload()
        validate_reviewed_pair_fixture(payload)
        payload["review_status"] = "draft"
        with self.assertRaisesRegex(ValueError, "explicitly approved"):
            validate_reviewed_pair_fixture(payload)

    def _fixture_payload(self):
        return {
            "schema_version": 1,
            "pair_id": "pair-1",
            "review_status": "approved",
            "reviewer": "human",
            "reviewed_at": "2026-07-15T12:00:00Z",
            "expected_outcome": "same_speaker",
            "variation_tags": ["different_date", "different_microphone"],
            "observations": {
                "a": {
                    "input_fingerprint": "obsA",
                    "reviewed_spans": [{"wav_sha256": "a" * 64}, {"wav_sha256": "b" * 64}],
                },
                "b": {
                    "input_fingerprint": "obsB",
                    "reviewed_spans": [{"wav_sha256": "c" * 64}, {"wav_sha256": "d" * 64}],
                },
            },
        }

    def test_evaluation_requires_exact_reviewed_spans_and_does_not_reward_abstention(self):
        fixture = self._fixture_payload()
        result = {
            "observations": {"a": "obsA", "b": "obsB"},
            "spans": {
                "a": [{"wav_sha256": "a" * 64}, {"wav_sha256": "b" * 64}],
                "b": [{"wav_sha256": "c" * 64}, {"wav_sha256": "d" * 64}],
            },
            "model": {"model_sha256": "e" * 64},
            "policy_version": "reviewed-v1",
            "outcome": "insufficient_evidence",
        }
        report = evaluate_reviewed_pair_results(
            [fixture],
            [result],
            required_decisions_per_outcome=1,
            required_variation_tags=fixture["variation_tags"],
        )

        self.assertEqual(1, report["counts"]["insufficient_evidence"])
        self.assertEqual(0.0, report["rates"]["decision_coverage"])
        self.assertTrue(report["gates"]["observed_zero_error_gate"])
        self.assertFalse(report["gates"]["promotion_ready"])

        result["spans"]["a"][0]["wav_sha256"] = "f" * 64
        mismatch = evaluate_reviewed_pair_results([fixture], [result])
        self.assertEqual(1, mismatch["counts"]["missing_or_nonreplayable_result"])

    def test_decision_policy_file_must_be_approved(self):
        path = self.root / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "review_status": "draft",
                    "version": "v1",
                    "min_valid_spans": 2,
                    "min_within_median": 0.9,
                    "same_min_cross_p10": 0.9,
                    "same_min_cross_median": 0.95,
                    "different_max_cross_p90": 0.2,
                }
            )
        )
        with self.assertRaisesRegex(ValueError, "explicitly approved"):
            DecisionPolicy.from_path(path)

    def test_readonly_database_supports_diagnostics_but_rejects_mutation(self):
        path = self.root / "app.db"
        writable = Database(path)
        writable.initialize()
        writable.add_pastor("sample", "Sample Pastor")
        readonly = Database(path, readonly=True)

        self.assertEqual("sample", readonly.list_pastors()[0].slug)
        with self.assertRaises(sqlite3.OperationalError):
            readonly.add_pastor("forbidden", "Forbidden Write")
        self.assertEqual(1, len(writable.list_pastors()))


if __name__ == "__main__":
    unittest.main()
