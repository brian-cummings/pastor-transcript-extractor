from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.speaker_observation_consistency import (
    build_observation_consistency_plan,
    collect_reviewed_observation_examples,
    evaluate_observation_consistency_examples,
    load_consistency_score_index,
    load_discovery_consistency_policy,
    write_observation_consistency_report,
)
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    EmbeddingCache,
    ModelSpec,
    observation_consistency_metrics,
)


class FakeBackend:
    def __init__(self, vectors: dict[str, tuple[float, ...]]):
        self.vectors = vectors
        self.spec = ModelSpec(
            backend="fake",
            model_name="consistency-test",
            model_sha256=hashlib.sha256(b"consistency-test").hexdigest(),
            runtime_version="1",
        )

    def embed(self, wav_path: Path):
        return self.vectors[wav_path.stem]


def clip(name: str, index: int) -> dict[str, object]:
    return {
        "start_seconds": float(index * 20),
        "end_seconds": float(index * 20 + 12),
        "wav_path": f"/tmp/{name}.wav",
        "wav_sha256": hashlib.sha256(name.encode()).hexdigest(),
        "duration_seconds": 12.0,
        "rms_dbfs": -20.0,
        "clipped_fraction": 0.0,
        "non_silent_fraction": 0.9,
    }


class SpeakerObservationConsistencyTests(unittest.TestCase):
    def test_loads_experimental_discovery_tiering_policy(self) -> None:
        payload = {
            "schema_version": 1,
            "policy_version": "test-consistency-v1",
            "purpose": "shadow_discovery_nomination_tiering",
            "feature": "weakest_clip_coherence",
            "strong_minimum": 0.6,
            "review_status": "experimental_candidate",
            "automatic_qualification_allowed": False,
            "registry_mutation_allowed": False,
            "calibration": {"report_sha256": "a" * 64},
        }
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            policy = load_discovery_consistency_policy(path)

        self.assertEqual(policy.strong_minimum, 0.6)
        self.assertEqual(policy.feature, "weakest_clip_coherence")
        self.assertEqual(policy.review_status, "experimental_candidate")
        self.assertFalse(policy.automatic_qualification_allowed)
        self.assertFalse(policy.registry_mutation_allowed)

    def test_metrics_distinguish_compact_voice_from_two_clusters(self) -> None:
        compact = observation_consistency_metrics(
            [
                (1.0, 0.0),
                (0.999, 0.02),
                (0.998, -0.03),
                (0.997, 0.04),
            ]
        )
        clustered = observation_consistency_metrics(
            [
                (1.0, 0.0),
                (0.99, 0.10),
                (0.0, 1.0),
                (0.10, 0.99),
            ]
        )
        single_outlier = observation_consistency_metrics(
            [
                (0.0, 1.0),
                (1.0, 0.0),
                (0.99, 0.01),
                (0.98, -0.02),
            ]
        )

        self.assertGreater(
            compact["weakest_clip_coherence"],
            clustered["weakest_clip_coherence"],
        )
        self.assertLess(
            compact["strongest_two_cluster_split"]["separation"],
            clustered["strongest_two_cluster_split"]["separation"],
        )
        self.assertGreater(
            single_outlier["strongest_two_cluster_split"]["separation"],
            0.9,
        )

    def test_review_labels_are_deduplicated_and_scored_without_policy(self) -> None:
        draft = {
            "pair_id": "pair-ab",
            "draft_id": "draft-ab",
            "presentation": {
                "A": {"source_key": "source_a"},
                "B": {"source_key": "source_b"},
            },
            "observations": {
                "source_a": {
                    "input_fingerprint": "observation-a",
                    "youtube_video_id": "video-a",
                    "clips": [clip(f"a-{index}", index) for index in range(3)],
                },
                "source_b": {
                    "input_fingerprint": "observation-b",
                    "youtube_video_id": "video-b",
                    "clips": [clip(f"b-{index}", index) for index in range(3)],
                },
            },
        }
        review = {
            "pair_id": "pair-ab",
            "draft_id": "draft-ab",
            "review_event_id": "event-ab",
            "qualification": {
                "A": "qualified_single_speaker",
                "B": "multiple_speakers",
            },
        }
        examples, conflicts = collect_reviewed_observation_examples(
            drafts=[draft],
            reviews=[review, review],
        )
        plan = build_observation_consistency_plan(
            examples=examples,
            conflicts=conflicts,
        )

        self.assertEqual(2, plan["reviewed_example_count"])
        self.assertEqual(
            1,
            plan["qualification_counts"]["qualified_single_speaker"],
        )
        self.assertEqual(1, plan["qualification_counts"]["multiple_speakers"])
        self.assertFalse(plan["automatic_qualification_allowed"])

        vectors = {
            "a-0": (1.0, 0.0),
            "a-1": (0.99, 0.01),
            "a-2": (0.98, -0.02),
            "b-0": (1.0, 0.0),
            "b-1": (0.99, 0.01),
            "b-2": (0.0, 1.0),
        }
        with tempfile.TemporaryDirectory() as tempdir:
            report = evaluate_observation_consistency_examples(
                examples=examples,
                conflicts=conflicts,
                embedding_cache=EmbeddingCache(Path(tempdir)),
                backend=FakeBackend(vectors),
            )
            report_path = Path(tempdir) / "report.json"
            write_observation_consistency_report(report_path, report)
            index = load_consistency_score_index(report_path)

        self.assertEqual(2, report["scored_case_count"])
        self.assertFalse(report["registry_mutation_allowed"])
        self.assertIn("report_sha256", report)
        self.assertEqual(report["report_sha256"], index.report_sha256)
        self.assertEqual(2, len(index.scores))
        cases = {
            case["reviewed_qualification"]: case
            for case in report["cases"]
        }
        self.assertGreater(
            cases["qualified_single_speaker"]["analysis"]["metrics"][
                "weakest_clip_coherence"
            ],
            cases["multiple_speakers"]["analysis"]["metrics"][
                "weakest_clip_coherence"
            ],
        )


if __name__ == "__main__":
    unittest.main()
