from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_pair_diagnostics import DecisionPolicy
from pastor_transcript_extractor.speaker_profile_discovery import (
    DiscoveryCandidate,
    DiscoverySignature,
    evaluate_shadow_profile_discovery,
    nominate_discovery_pairs,
    select_transcript_grounded_spans,
    write_shadow_profile_discovery,
)
from pastor_transcript_extractor.speaker_shadow_association import ShadowPolicySpec
from pastor_transcript_extractor.storage import Database


class SpeakerProfileDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = build_paths(self.root / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.source = self.database.add_source(
            "https://www.youtube.com/@discovery",
            SourceType.CHANNEL,
            pastor_id=None,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _signature(
        self,
        key: str,
        centroid: tuple[float, ...],
        *,
        names: tuple[str, ...] = (),
    ) -> DiscoverySignature:
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=None,
            youtube_video_id=f"video-{key}",
            title=f"Video {key}",
            url=f"https://www.youtube.com/watch?v=video-{key}",
            status=VideoStatus.EXTRACTED,
        )
        extraction = self.database.add_extraction_result(
            video_id=video.id,
            version=1,
            proposed_text_path=f"{key}.md",
            proposed_json_path=f"{key}.json",
        )
        observation = self.database.add_speaker_observation(
            video_id=video.id,
            extraction_result_id=extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="unknown",
            start_seconds=100.0,
            end_seconds=1000.0,
            artifact_path=f"{key}.speaker.json",
            content_sha256=f"content-{key}",
            extractor_version="speaker_evidence_v1",
            input_fingerprint=key,
        )
        return DiscoverySignature(
            candidate=DiscoveryCandidate(
                observation=observation,
                audio_path=Path(f"{key}.wav"),
                source_id=self.source.id,
                normalized_names=names,
            ),
            centroid=centroid,
            span_evidence=(),
            consistency_metrics={"weakest_clip_coherence": 0.9},
            signature_sha256=f"signature-{key}",
        )

    def _policy(self) -> ShadowPolicySpec:
        return ShadowPolicySpec(
            policy=DecisionPolicy(
                version="test-policy",
                min_valid_spans=2,
                min_within_median=0.7,
                same_min_cross_p10=0.6,
                same_min_cross_median=0.7,
                different_max_cross_p90=0.3,
            ),
            review_status="experimental_candidate",
            artifact_sha256="a" * 64,
            automatic_use_allowed=False,
        )

    def test_complete_link_triangle_proposes_provisional_profile(self) -> None:
        signatures = (
            self._signature("a", (1.0, 0.0)),
            self._signature("b", (0.99, 0.01)),
            self._signature("c", (0.98, 0.02)),
        )
        nominations = nominate_discovery_pairs(
            signatures,
            nearest_neighbors=2,
        )

        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominations,
            compare=lambda *_args: {
                "outcome": "same_speaker",
                "reason": "test_same",
            },
            policy_spec=self._policy(),
            model_fingerprint="model",
        )

        self.assertEqual(3, len(nominations))
        self.assertEqual(1, report["counts"]["provisional_profile_candidates"])
        component = report["components"][0]
        self.assertEqual("provisional_profile_candidate", component["outcome"])
        self.assertEqual(
            {
                "required": 3,
                "same_speaker": 3,
                "different_speaker": 0,
                "unresolved": 0,
            },
            component["edge_counts"],
        )
        self.assertFalse(report["automatic_profile_creation_allowed"])
        self.assertFalse(component["automatic_profile_creation_allowed"])

    def test_transcript_grounding_selects_distributed_sermon_speech(self) -> None:
        observation = self._signature(
            "speech",
            (1.0, 0.0),
        ).candidate.observation
        text = (
            "This is a sustained sermon sentence with enough distinct "
            "words for acoustic speaker evidence."
        )
        payload = {
            "segments": [
                {
                    "start_seconds": start,
                    "end_seconds": start + 15.0,
                    "label": "sermon",
                    "text": f"{text} section {index}",
                }
                for index, start in enumerate(
                    (150.0, 300.0, 450.0, 600.0, 750.0)
                )
            ]
        }

        spans = select_transcript_grounded_spans(payload, observation)

        self.assertEqual(5, len(spans))
        self.assertEqual(sorted(span.start_seconds for span in spans), [
            span.start_seconds for span in spans
        ])

    def test_transcript_grounding_rejects_repetitive_non_sermon_text(self) -> None:
        observation = self._signature(
            "noise",
            (1.0, 0.0),
        ).candidate.observation
        payload = {
            "segments": [
                {
                    "start_seconds": start,
                    "end_seconds": start + 15.0,
                    "label": "unknown",
                    "text": "Heat. Heat.",
                }
                for start in (150.0, 300.0, 450.0, 600.0, 750.0)
            ]
        }

        self.assertEqual(
            (),
            select_transcript_grounded_spans(payload, observation),
        )

    def test_incomplete_component_is_blocked(self) -> None:
        signatures = (
            self._signature("a", (1.0, 0.0)),
            self._signature("b", (0.99, 0.01)),
            self._signature("c", (0.98, 0.02)),
            self._signature("d", (0.97, 0.03)),
        )
        nominations = nominate_discovery_pairs(
            signatures,
            nearest_neighbors=2,
            maximum_pairs=2,
        )

        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominations,
            compare=lambda *_args: {
                "outcome": "same_speaker",
                "reason": "test_same",
            },
            policy_spec=self._policy(),
            model_fingerprint="model",
        )

        self.assertEqual(0, report["counts"]["provisional_profile_candidates"])
        self.assertIn(
            "component_not_complete_link",
            report["components"][0]["blockers"],
        )

    def test_conflicting_names_block_otherwise_complete_component(self) -> None:
        signatures = (
            self._signature("a", (1.0, 0.0), names=("alice",)),
            self._signature("b", (0.99, 0.01), names=("alice",)),
            self._signature("c", (0.98, 0.02), names=("bob",)),
        )
        nominations = nominate_discovery_pairs(
            signatures,
            nearest_neighbors=2,
        )

        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominations,
            compare=lambda *_args: {
                "outcome": "same_speaker",
                "reason": "test_same",
            },
            policy_spec=self._policy(),
            model_fingerprint="model",
        )

        self.assertEqual("blocked", report["components"][0]["outcome"])
        self.assertIn(
            "conflicting_explicit_attribution",
            report["components"][0]["blockers"],
        )

    def test_single_same_bridge_does_not_destroy_two_complete_components(self) -> None:
        signatures = tuple(
            self._signature(key, (1.0, index / 100.0))
            for index, key in enumerate(("a", "b", "c", "d", "e", "f"))
        )
        first = {"a", "b", "c"}
        second = {"d", "e", "f"}

        def compare(left, right, *_paths):
            pair = {left.input_fingerprint, right.input_fingerprint}
            same = (
                pair <= first
                or pair <= second
                or pair == {"c", "d"}
            )
            return {
                "outcome": "same_speaker" if same else "different_speaker",
                "reason": "test",
            }

        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominate_discovery_pairs(
                signatures,
                nearest_neighbors=5,
            ),
            compare=compare,
            policy_spec=self._policy(),
            model_fingerprint="model",
        )

        self.assertEqual(2, report["counts"]["provisional_profile_candidates"])

    def test_reviewed_difference_overrides_acoustic_comparer(self) -> None:
        signatures = (
            self._signature("a", (1.0, 0.0)),
            self._signature("b", (0.99, 0.01)),
            self._signature("c", (0.98, 0.02)),
        )
        nominations = nominate_discovery_pairs(
            signatures,
            nearest_neighbors=2,
        )
        compared_pairs: list[tuple[int, int]] = []

        def compare(left, right, *_paths):
            compared_pairs.append(tuple(sorted((left.id, right.id))))
            return {"outcome": "same_speaker", "reason": "test_same"}

        blocked_pair = nominations[0].observation_ids
        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominations,
            compare=compare,
            policy_spec=self._policy(),
            model_fingerprint="model",
            reviewed_difference_pairs=(blocked_pair,),
        )

        result = next(
            item
            for item in report["pair_results"]
            if tuple(item["observation_ids"]) == blocked_pair
        )
        self.assertEqual("different_speaker", result["outcome"])
        self.assertNotIn(blocked_pair, compared_pairs)
        self.assertEqual(0, report["counts"]["provisional_profile_candidates"])

    def test_content_addressed_report_is_idempotent(self) -> None:
        signatures = (
            self._signature("a", (1.0, 0.0)),
            self._signature("b", (0.99, 0.01)),
            self._signature("c", (0.98, 0.02)),
        )
        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominate_discovery_pairs(
                signatures,
                nearest_neighbors=2,
            ),
            compare=lambda *_args: {
                "outcome": "same_speaker",
                "reason": "test_same",
            },
            policy_spec=self._policy(),
            model_fingerprint="model",
        )

        first = write_shadow_profile_discovery(self.root / "runs", report)
        second = write_shadow_profile_discovery(self.root / "runs", report)

        self.assertEqual(first, second)
        self.assertTrue(first.exists())

        corrupted = dict(report)
        corrupted["counts"] = {
            **report["counts"],
            "provisional_profile_candidates": 99,
        }
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            write_shadow_profile_discovery(self.root / "runs", corrupted)


if __name__ == "__main__":
    unittest.main()
