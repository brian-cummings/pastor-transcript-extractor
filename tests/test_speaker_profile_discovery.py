from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    CachedSpan,
    DecisionPolicy,
    ModelSpec,
    SpanSpec,
)
from pastor_transcript_extractor.speaker_observation_consistency import (
    DiscoveryConsistencyPolicySpec,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    ActivityQualifiedSelectionCache,
    DiscoveryCandidate,
    DiscoverySignature,
    evaluate_shadow_profile_discovery,
    load_verified_shadow_profile_discovery,
    nominate_discovery_pairs,
    prepare_activity_qualified_spans,
    refine_activity_qualified_spans,
    select_transcript_grounded_span_candidates,
    select_transcript_grounded_spans,
    write_shadow_profile_discovery,
)
from pastor_transcript_extractor.speaker_shadow_association import ShadowPolicySpec
from pastor_transcript_extractor.storage import Database


class FakeActivitySpanCache:
    def __init__(self, rms_by_start, activity_by_start):
        self.rms_by_start = rms_by_start
        self.activity_by_start = activity_by_start

    def prepare(self, *, observation, source_audio_path, span):
        return CachedSpan(
            observation_fingerprint=observation.input_fingerprint,
            start_seconds=span.start_seconds,
            end_seconds=span.end_seconds,
            wav_path=f"{span.start_seconds}.wav",
            wav_sha256=f"sha-{span.start_seconds}",
            duration_seconds=span.end_seconds - span.start_seconds,
            rms_dbfs=self.rms_by_start[span.start_seconds],
            clipped_fraction=0.0,
            cache_hit=False,
        )

    def measure_span_activity(
        self,
        span,
        *,
        silence_threshold_dbfs,
        frame_duration_ms,
    ):
        return self.activity_by_start[span.start_seconds]


class FakeEmbeddingCache:
    def __init__(self, embedding_by_start):
        self.embedding_by_start = embedding_by_start
        self.requested_starts = []

    def get_or_compute(self, span, backend):
        self.requested_starts.append(span.start_seconds)
        return self.embedding_by_start[span.start_seconds], False


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
        consistency: float = 0.9,
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
            consistency_metrics={"weakest_clip_coherence": consistency},
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

    def _consistency_policy(self) -> DiscoveryConsistencyPolicySpec:
        return DiscoveryConsistencyPolicySpec(
            policy_version="test-consistency-v1",
            feature="weakest_clip_coherence",
            strong_minimum=0.6,
            review_status="experimental_candidate",
            artifact_sha256="b" * 64,
            calibration_report_sha256="c" * 64,
            automatic_qualification_allowed=False,
            registry_mutation_allowed=False,
        )

    def test_consistency_policy_defers_weak_signatures_by_default(self) -> None:
        signatures = (
            self._signature("a", (1.0, 0.0), consistency=0.9),
            self._signature("b", (0.99, 0.01), consistency=0.8),
            self._signature("c", (0.98, 0.02), consistency=0.7),
            self._signature("weak", (0.97, 0.03), consistency=0.2),
        )

        strong_only = nominate_discovery_pairs(
            signatures,
            nearest_neighbors=2,
            consistency_policy=self._consistency_policy(),
        )
        with_deferred = nominate_discovery_pairs(
            signatures,
            nearest_neighbors=2,
            consistency_policy=self._consistency_policy(),
            include_deferred=True,
        )

        strong_ids = {
            observation_id
            for nomination in strong_only
            for observation_id in nomination.observation_ids
        }
        weak_id = signatures[-1].candidate.observation.id
        self.assertNotIn(weak_id, strong_ids)
        self.assertFalse(
            any(weak_id in nomination.observation_ids for nomination in with_deferred)
        )
        self.assertTrue(
            all(
                nomination.consistency_tier == "strong_strong"
                for nomination in strong_only
            )
        )

    def test_discovery_report_records_calibrated_tiers(self) -> None:
        signatures = (
            self._signature("a", (1.0, 0.0), consistency=0.9),
            self._signature("b", (0.99, 0.01), consistency=0.8),
            self._signature("c", (0.98, 0.02), consistency=0.7),
            self._signature("weak", (0.0, 1.0), consistency=0.2),
        )
        consistency_policy = self._consistency_policy()
        nominations = nominate_discovery_pairs(
            signatures,
            nearest_neighbors=2,
            consistency_policy=consistency_policy,
            source_complete_link_limit=0,
            source_nearest_neighbors=0,
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
            consistency_policy=consistency_policy,
        )

        self.assertEqual(report["counts"]["strong_signatures"], 3)
        self.assertEqual(report["counts"]["deferred_signatures"], 1)
        self.assertEqual(report["counts"]["strong_strong_pairs"], 3)
        self.assertEqual(report["counts"]["deferred_pairs"], 0)
        self.assertEqual(
            report["consistency_gate"]["mode"],
            "tiered_nomination",
        )
        tiers = {
            item["observation_fingerprint"]: item["consistency_tier"]
            for item in report["observation_signatures"]
        }
        self.assertEqual(tiers["weak"], "deferred")

    def test_same_pair_closure_can_complete_three_recording_profile(self) -> None:
        signatures = (
            self._signature("a", (1.0, 0.0), consistency=0.9),
            self._signature("b", (0.999, 0.001), consistency=0.9),
            self._signature("c", (0.998, 0.002), consistency=0.9),
            self._signature("unrelated", (0.0, 1.0), consistency=0.9),
        )
        consistency_policy = self._consistency_policy()
        nominations = nominate_discovery_pairs(
            signatures,
            nearest_neighbors=2,
            maximum_pairs=1,
            source_complete_link_limit=0,
            source_nearest_neighbors=0,
            consistency_policy=consistency_policy,
        )
        compared: list[frozenset[str]] = []

        def compare(left, right, *_paths):
            pair = frozenset(
                (left.input_fingerprint, right.input_fingerprint)
            )
            compared.append(pair)
            return {
                "outcome": (
                    "same_speaker"
                    if pair <= {"a", "b", "c"}
                    else "different_speaker"
                ),
                "reason": "test",
            }

        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominations,
            compare=compare,
            policy_spec=self._policy(),
            model_fingerprint="model",
            consistency_policy=consistency_policy,
            closure_candidates_per_same_pair=1,
        )

        self.assertEqual(report["counts"]["initial_pairs"], 1)
        self.assertEqual(report["counts"]["closure_pairs"], 2)
        self.assertEqual(report["counts"]["provisional_profile_candidates"], 1)
        self.assertEqual(len(compared), 3)
        closure_results = [
            result
            for result in report["pair_results"]
            if result["retrieval_reason"] == "same_pair_closure"
        ]
        self.assertTrue(
            all(result["source_context_preferred"] for result in closure_results)
        )
        self.assertTrue(
            all(result["outcome"] == "same_speaker" for result in closure_results)
        )

    def test_source_context_never_supplies_a_closure_identity_edge(self) -> None:
        signatures = (
            self._signature("a", (1.0, 0.0)),
            self._signature("b", (0.999, 0.001)),
            self._signature("c", (0.998, 0.002)),
        )
        nominations = nominate_discovery_pairs(
            signatures,
            nearest_neighbors=2,
            maximum_pairs=1,
            source_complete_link_limit=0,
            source_nearest_neighbors=0,
        )
        initial_pair = frozenset(
            signature.candidate.observation.input_fingerprint
            for signature in (nominations[0].left, nominations[0].right)
        )

        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominations,
            compare=lambda left, right, *_paths: {
                "outcome": (
                    "same_speaker"
                    if frozenset(
                        (left.input_fingerprint, right.input_fingerprint)
                    )
                    == initial_pair
                    else "different_speaker"
                ),
                "reason": "test",
            },
            policy_spec=self._policy(),
            model_fingerprint="model",
            closure_candidates_per_same_pair=1,
        )

        self.assertEqual(report["counts"]["closure_pairs"], 2)
        self.assertEqual(report["counts"]["provisional_profile_candidates"], 0)
        self.assertTrue(
            all(
                result["source_context_preferred"]
                for result in report["pair_results"]
                if result["retrieval_reason"] == "same_pair_closure"
            )
        )

    def test_source_local_retrieval_adds_coverage_but_not_identity(self) -> None:
        signatures = (
            self._signature("source-a", (1.0, 0.0)),
            self._signature("source-b", (0.99, 0.01)),
            self._signature("source-c", (0.98, 0.02)),
        )

        nominations = nominate_discovery_pairs(
            signatures,
            nearest_neighbors=2,
            maximum_pairs=1,
            source_complete_link_limit=3,
            source_nearest_neighbors=1,
        )
        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominations,
            compare=lambda *_args: {
                "outcome": "different_speaker",
                "reason": "test_different",
            },
            policy_spec=self._policy(),
            model_fingerprint="model",
            source_complete_link_limit=3,
            source_nearest_neighbors=1,
        )

        self.assertEqual(3, len(nominations))
        self.assertEqual(1, report["counts"]["global_pairs"])
        self.assertEqual(3, report["counts"]["source_local_pairs"])
        self.assertEqual(0, report["counts"]["provisional_profile_candidates"])
        self.assertTrue(
            all(
                result["source_context"]["identity_evidence"] is False
                for result in report["pair_results"]
            )
        )

    def test_borderline_deferred_candidate_requires_both_seed_matches(self) -> None:
        signatures = (
            self._signature("seed-a", (1.0, 0.0), consistency=0.9),
            self._signature("seed-b", (0.999, 0.001), consistency=0.9),
            self._signature("borderline", (0.998, 0.002), consistency=0.55),
        )
        consistency_policy = self._consistency_policy()
        nominations = nominate_discovery_pairs(
            signatures,
            nearest_neighbors=2,
            maximum_pairs=1,
            consistency_policy=consistency_policy,
            source_complete_link_limit=0,
            source_nearest_neighbors=0,
        )

        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominations,
            compare=lambda left, right, *_paths: {
                "outcome": (
                    "same_speaker"
                    if frozenset(
                        (left.input_fingerprint, right.input_fingerprint)
                    )
                    in {
                        frozenset(("seed-a", "seed-b")),
                        frozenset(("seed-a", "borderline")),
                    }
                    else "different_speaker"
                ),
                "reason": "test",
            },
            policy_spec=self._policy(),
            model_fingerprint="model",
            consistency_policy=consistency_policy,
            source_complete_link_limit=0,
            source_nearest_neighbors=0,
            borderline_deferred_candidates_per_same_pair=1,
        )

        self.assertEqual(2, report["counts"]["borderline_deferred_pairs"])
        self.assertEqual(0, report["counts"]["provisional_profile_candidates"])
        attempt = report["borderline_deferred_closure"][0]
        self.assertEqual("borderline_deferred", attempt["tier"])
        self.assertEqual(
            "rejected_incomplete_acoustic_agreement", attempt["outcome"]
        )
        self.assertFalse(attempt["identity_edges_allowed"])
        self.assertEqual([], report["staged_review_frontier"])
        self.assertTrue(
            all(
                result["identity_edge_allowed"] is False
                for result in report["pair_results"]
                if result["retrieval_reason"] == "borderline_deferred_closure"
            )
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

    def test_near_same_ambiguous_edge_becomes_actionable_review_frontier(self) -> None:
        signatures = (
            self._signature("frontier-a", (1.0, 0.0)),
            self._signature("frontier-b", (0.99, 0.01)),
            self._signature("frontier-c", (0.98, 0.02)),
        )
        observation_ids = {
            signature.candidate.observation.input_fingerprint:
            signature.candidate.observation.id
            for signature in signatures
        }
        ambiguous_pair = tuple(
            sorted((observation_ids["frontier-b"], observation_ids["frontier-c"]))
        )

        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominate_discovery_pairs(
                signatures,
                nearest_neighbors=2,
                source_complete_link_limit=0,
                source_nearest_neighbors=0,
            ),
            compare=lambda left, right, *_paths: (
                {
                    "outcome": "insufficient_evidence",
                    "reason": "ambiguous_similarity",
                    "metrics": {
                        "cross": {"p10": 0.59, "median": 0.69}
                    },
                }
                if tuple(sorted((left.id, right.id))) == ambiguous_pair
                else {"outcome": "same_speaker", "reason": "test_same"}
            ),
            policy_spec=self._policy(),
            model_fingerprint="model",
        )

        self.assertEqual(1, len(report["review_frontier"]))
        frontier = report["review_frontier"][0]
        self.assertEqual(list(ambiguous_pair), frontier["observation_ids"])
        self.assertEqual(
            "approved_blinded_pair_review_only",
            frontier["durable_evidence_source"],
        )
        self.assertEqual(
            1,
            report["counts"][
                "blocked_components_with_actionable_review_frontier"
            ],
        )

    def test_two_ambiguous_seed_edges_stage_the_bottleneck_review(self) -> None:
        signatures = (
            self._signature("stage-a", (1.0, 0.0), consistency=0.9),
            self._signature("stage-b", (0.99, 0.01), consistency=0.9),
            self._signature("stage-c", (0.98, 0.02), consistency=0.9),
        )
        ids = {
            signature.candidate.observation.input_fingerprint:
            signature.candidate.observation.id
            for signature in signatures
        }
        seed_pair = tuple(sorted((ids["stage-a"], ids["stage-b"])))
        bottleneck_pair = tuple(sorted((ids["stage-b"], ids["stage-c"])))

        def compare(left, right, *_paths):
            pair = tuple(sorted((left.id, right.id)))
            if pair == seed_pair:
                return {"outcome": "same_speaker", "reason": "test_same"}
            if pair == bottleneck_pair:
                return {
                    "outcome": "insufficient_evidence",
                    "reason": "ambiguous_similarity",
                    "metrics": {
                        "cross": {"p10": 0.54, "median": 0.71}
                    },
                }
            return {
                "outcome": "insufficient_evidence",
                "reason": "ambiguous_similarity",
                "metrics": {"cross": {"p10": 0.59, "median": 0.69}},
            }

        nominations = nominate_discovery_pairs(
            signatures,
            nearest_neighbors=2,
            consistency_policy=self._consistency_policy(),
            source_complete_link_limit=0,
            source_nearest_neighbors=0,
        )
        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominations,
            compare=compare,
            policy_spec=self._policy(),
            model_fingerprint="model",
            consistency_policy=self._consistency_policy(),
            source_complete_link_limit=0,
            source_nearest_neighbors=0,
        )

        self.assertEqual(0, len(report["review_frontier"]))
        self.assertEqual(1, len(report["staged_review_frontier"]))
        staged = report["staged_review_frontier"][0]
        self.assertEqual(
            list(bottleneck_pair), staged["selected_review"]["observation_ids"]
        )
        self.assertEqual(2, staged["required_review_count"])
        self.assertFalse(staged["identity_edges_allowed"])
        self.assertEqual(
            0.15,
            report["review_frontier_policy"][
                "staged_maximum_same_boundary_distance"
            ],
        )
        self.assertEqual([], report["staged_review_frontier_exclusions"])
        self.assertEqual(0, report["counts"]["provisional_profile_candidates"])

        after_first_same = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominations,
            compare=compare,
            policy_spec=self._policy(),
            model_fingerprint="model",
            reviewed_same_pairs=(bottleneck_pair,),
            consistency_policy=self._consistency_policy(),
            source_complete_link_limit=0,
            source_nearest_neighbors=0,
        )

        self.assertEqual(1, len(after_first_same["review_frontier"]))
        self.assertEqual(0, len(after_first_same["staged_review_frontier"]))
        self.assertEqual(
            tuple(
                after_first_same["review_frontier"][0]["observation_ids"]
            ),
            tuple(sorted((ids["stage-a"], ids["stage-c"]))),
        )

    def test_distant_ambiguous_seed_edges_are_not_actionable_reviews(
        self,
    ) -> None:
        signatures = (
            self._signature("far-a", (1.0, 0.0), consistency=0.9),
            self._signature("far-b", (0.99, 0.01), consistency=0.9),
            self._signature("far-c", (0.98, 0.02), consistency=0.9),
        )
        ids = {
            signature.candidate.observation.input_fingerprint:
            signature.candidate.observation.id
            for signature in signatures
        }
        seed_pair = tuple(sorted((ids["far-a"], ids["far-b"])))

        def compare(left, right, *_paths):
            if tuple(sorted((left.id, right.id))) == seed_pair:
                return {"outcome": "same_speaker", "reason": "test_same"}
            return {
                "outcome": "insufficient_evidence",
                "reason": "ambiguous_similarity",
                "metrics": {"cross": {"p10": 0.25, "median": 0.35}},
            }

        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominate_discovery_pairs(
                signatures,
                nearest_neighbors=2,
                consistency_policy=self._consistency_policy(),
                source_complete_link_limit=0,
                source_nearest_neighbors=0,
            ),
            compare=compare,
            policy_spec=self._policy(),
            model_fingerprint="model",
            consistency_policy=self._consistency_policy(),
            source_complete_link_limit=0,
            source_nearest_neighbors=0,
            staged_review_maximum_same_boundary_distance=0.15,
        )

        self.assertEqual([], report["staged_review_frontier"])
        self.assertEqual(1, len(report["staged_review_frontier_exclusions"]))
        exclusion = report["staged_review_frontier_exclusions"][0]
        self.assertEqual(
            "outside_staged_review_distance_limit", exclusion["reason"]
        )
        self.assertGreater(exclusion["same_boundary_distance"], 0.15)
        self.assertFalse(exclusion["review_required"])
        self.assertEqual(
            1,
            report["counts"][
                "blocked_components_with_only_distant_staged_candidates"
            ],
        )
        self.assertEqual(
            0,
            report["counts"][
                "blocked_components_with_actionable_review_frontier"
            ],
        )

    def test_written_report_can_be_loaded_with_checksum_verification(self) -> None:
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
        path = write_shadow_profile_discovery(self.root / "reports", report)

        loaded = load_verified_shadow_profile_discovery(path)

        self.assertEqual(loaded["result_sha256"], report["result_sha256"])
        self.assertEqual(
            loaded["counts"]["provisional_profile_candidates"],
            1,
        )

    def test_reviewed_same_constraint_resolves_overlapping_cliques(self) -> None:
        signatures = (
            self._signature("a", (1.0, 0.0)),
            self._signature("b", (0.99, 0.01)),
            self._signature("c", (0.98, 0.02)),
            self._signature("d", (0.97, 0.03)),
        )
        observation_ids = {
            signature.candidate.observation.input_fingerprint:
            signature.candidate.observation.id
            for signature in signatures
        }
        unresolved_pair = tuple(
            sorted((observation_ids["c"], observation_ids["d"]))
        )

        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominate_discovery_pairs(
                signatures,
                nearest_neighbors=3,
            ),
            compare=lambda observation_a, observation_b, *_args: {
                "outcome": (
                    "insufficient_evidence"
                    if tuple(sorted((observation_a.id, observation_b.id)))
                    == unresolved_pair
                    else "same_speaker"
                ),
                "reason": "test",
            },
            policy_spec=self._policy(),
            model_fingerprint="model",
            reviewed_same_pairs=(unresolved_pair,),
        )

        self.assertEqual(1, len(report["components"]))
        component = report["components"][0]
        self.assertEqual("provisional_profile_candidate", component["outcome"])
        self.assertEqual(4, component["member_count"])
        reviewed_result = next(
            result
            for result in report["pair_results"]
            if tuple(result["observation_ids"]) == unresolved_pair
        )
        self.assertEqual("same_speaker", reviewed_result["outcome"])
        self.assertTrue(reviewed_result["reviewed_constraint"])
        self.assertEqual(
            [list(unresolved_pair)],
            report["reviewed_constraints"][
                "same_speaker_observation_pairs"
            ],
        )

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

    def test_transcript_grounding_oversamples_when_speech_is_available(self) -> None:
        observation = self._signature("oversample", (1.0, 0.0)).candidate.observation
        payload = {
            "segments": [
                {
                    "start_seconds": float(start),
                    "end_seconds": float(start + 15),
                    "label": "sermon",
                    "text": "Sustained sermon speech with enough varied words for evidence.",
                }
                for start in range(120, 870, 50)
            ]
        }

        spans = select_transcript_grounded_span_candidates(payload, observation)

        self.assertEqual(15, len(spans))

    def test_quiet_recording_uses_relative_activity_and_avoids_edges(self) -> None:
        observation = self._signature("quiet", (1.0, 0.0)).candidate.observation
        specs = tuple(
            SpanSpec(float(start), float(start + 12))
            for start in range(120, 1620, 100)
        )
        rms = {
            spec.start_seconds: -56.0 + (index % 4)
            for index, spec in enumerate(specs)
        }
        activity = {spec.start_seconds: 0.65 for spec in specs}
        activity[specs[0].start_seconds] = 0.10
        activity[specs[-1].start_seconds] = 0.15

        prepared = prepare_activity_qualified_spans(
            observation=observation,
            audio_path=Path("quiet.wav"),
            span_cache=FakeActivitySpanCache(rms, activity),
            candidate_specs=specs,
        )

        self.assertEqual(5, len(prepared.spans))
        selected_starts = {span.start_seconds for span in prepared.spans}
        self.assertNotIn(specs[0].start_seconds, selected_starts)
        self.assertNotIn(specs[-1].start_seconds, selected_starts)
        self.assertLessEqual(
            prepared.selection["silence_threshold_dbfs"],
            -60.0,
        )

    def test_activity_selection_cache_reuses_consistency_result(self) -> None:
        observation = self._signature(
            "selection-cache",
            (1.0, 0.0),
        ).candidate.observation
        specs = tuple(
            SpanSpec(float(start), float(start + 12))
            for start in (110, 250, 400, 550, 700)
        )
        span_cache = FakeActivitySpanCache(
            {spec.start_seconds: -40.0 for spec in specs},
            {spec.start_seconds: 0.8 for spec in specs},
        )
        embeddings = {
            spec.start_seconds: (1.0, 0.0) for spec in specs
        }
        backend = type(
            "Backend",
            (),
            {
                "spec": ModelSpec(
                    backend="test",
                    model_name="test",
                    model_sha256="model-sha",
                    runtime_version="1",
                )
            },
        )()
        cache = ActivityQualifiedSelectionCache(self.root / "cache")

        first = cache.get_or_prepare(
            observation=observation,
            source_audio_sha256="audio-sha",
            candidate_specs=specs,
            span_cache=span_cache,
            audio_path=Path("audio.wav"),
            embedding_cache=FakeEmbeddingCache(embeddings),
            backend=backend,
            policy=self._policy().policy,
        )
        replay = cache.get_or_prepare(
            observation=observation,
            source_audio_sha256="audio-sha",
            candidate_specs=specs,
            span_cache=object(),
            audio_path=Path("offline.wav"),
            embedding_cache=object(),
            backend=backend,
            policy=self._policy().policy,
        )

        self.assertEqual(first, replay)
        self.assertEqual(1, cache.misses)
        self.assertEqual(1, cache.hits)

    def test_consistency_fallback_replaces_one_distributed_outlier(self) -> None:
        observation = self._signature("fallback", (1.0, 0.0)).candidate.observation
        specs = tuple(
            SpanSpec(float(start), float(start + 12))
            for start in (110, 250, 400, 550, 700, 800, 980)
        )
        prepared = prepare_activity_qualified_spans(
            observation=observation,
            audio_path=Path("fallback.wav"),
            span_cache=FakeActivitySpanCache(
                {spec.start_seconds: -40.0 for spec in specs},
                {spec.start_seconds: 0.8 for spec in specs},
            ),
            candidate_specs=specs,
        )
        embeddings = {
            spec.start_seconds: (
                (0.0, 1.0)
                if spec == specs[-1]
                else (1.0, 0.0)
            )
            for spec in specs
        }

        refined = refine_activity_qualified_spans(
            prepared,
            embedding_cache=FakeEmbeddingCache(embeddings),
            backend=object(),
            policy=self._policy().policy,
        )

        self.assertNotIn(specs[-1].start_seconds, {
            span.start_seconds for span in refined.spans
        })
        self.assertTrue(
            refined.selection["consistency_fallback_used"]
        )
        self.assertEqual(
            1,
            refined.selection["consistency_fallback_replacement_count"],
        )
        self.assertEqual(
            20,
            refined.selection["consistency_fallback_subsets_evaluated"],
        )
        self.assertLessEqual(
            refined.selection[
                "consistency_fallback_pairwise_similarities"
            ],
            21,
        )
        self.assertEqual(
            [
                {
                    "flag": "speaker_inconsistent_edge",
                    "edge": "end",
                    "start_seconds": 980.0,
                    "end_seconds": 992.0,
                    "window_fraction": 0.9844444444444445,
                    "identity_fallback_replaced": True,
                    "automatic_boundary_change_allowed": False,
                    "reason_codes": [
                        "distributed_clip_inconsistent",
                        "coherent_replacement_found",
                    ],
                }
            ],
            refined.selection["sermon_window_quality_flags"],
        )

    def test_consistent_distributed_selection_does_not_expand_embeddings(self) -> None:
        observation = self._signature("consistent", (1.0, 0.0)).candidate.observation
        specs = tuple(
            SpanSpec(float(start), float(start + 12))
            for start in range(120, 820, 100)
        )
        prepared = prepare_activity_qualified_spans(
            observation=observation,
            audio_path=Path("consistent.wav"),
            span_cache=FakeActivitySpanCache(
                {spec.start_seconds: -40.0 for spec in specs},
                {spec.start_seconds: 0.8 for spec in specs},
            ),
            candidate_specs=specs,
        )
        cache = FakeEmbeddingCache(
            {spec.start_seconds: (1.0, 0.0) for spec in specs}
        )

        refined = refine_activity_qualified_spans(
            prepared,
            embedding_cache=cache,
            backend=object(),
            policy=self._policy().policy,
        )

        self.assertEqual(prepared.spans, refined.spans)
        self.assertFalse(
            refined.selection["consistency_fallback_attempted"]
        )
        self.assertEqual(5, len(cache.requested_starts))

    def test_consistency_fallback_keeps_primary_when_no_coherent_five_exist(self) -> None:
        observation = self._signature("mixed", (1.0, 0.0)).candidate.observation
        specs = tuple(
            SpanSpec(float(start), float(start + 12))
            for start in range(120, 820, 100)
        )
        prepared = prepare_activity_qualified_spans(
            observation=observation,
            audio_path=Path("mixed.wav"),
            span_cache=FakeActivitySpanCache(
                {spec.start_seconds: -40.0 for spec in specs},
                {spec.start_seconds: 0.8 for spec in specs},
            ),
            candidate_specs=specs,
        )
        embeddings = {
            spec.start_seconds: (
                (1.0, 0.0) if index % 2 == 0 else (0.0, 1.0)
            )
            for index, spec in enumerate(specs)
        }

        refined = refine_activity_qualified_spans(
            prepared,
            embedding_cache=FakeEmbeddingCache(embeddings),
            backend=object(),
            policy=self._policy().policy,
        )

        self.assertEqual(prepared.spans, refined.spans)
        self.assertTrue(
            refined.selection["consistency_fallback_attempted"]
        )
        self.assertFalse(
            refined.selection[
                "consistency_fallback_found_coherent_subset"
            ]
        )

    def test_consistency_fallback_normalizes_non_unit_embeddings(self) -> None:
        observation = self._signature(
            "non-unit-mixed",
            (1.0, 0.0),
        ).candidate.observation
        specs = tuple(
            SpanSpec(float(start), float(start + 12))
            for start in range(120, 820, 100)
        )
        prepared = prepare_activity_qualified_spans(
            observation=observation,
            audio_path=Path("non-unit-mixed.wav"),
            span_cache=FakeActivitySpanCache(
                {spec.start_seconds: -40.0 for spec in specs},
                {spec.start_seconds: 0.8 for spec in specs},
            ),
            candidate_specs=specs,
        )
        embeddings = {
            spec.start_seconds: (
                (10.0, 0.0)
                if index < 4
                else (5.0, 8.660254037844386)
            )
            for index, spec in enumerate(specs)
        }

        refined = refine_activity_qualified_spans(
            prepared,
            embedding_cache=FakeEmbeddingCache(embeddings),
            backend=object(),
            policy=self._policy().policy,
        )

        self.assertEqual(prepared.spans, refined.spans)
        self.assertTrue(
            refined.selection["consistency_fallback_attempted"]
        )
        self.assertFalse(
            refined.selection[
                "consistency_fallback_found_coherent_subset"
            ]
        )

    def test_consistency_fallback_caches_pairwise_work_across_subsets(self) -> None:
        observation = self._signature("bounded", (1.0, 0.0)).candidate.observation
        specs = tuple(
            SpanSpec(float(start), float(start + 12))
            for start in range(120, 1620, 100)
        )
        prepared = prepare_activity_qualified_spans(
            observation=observation,
            audio_path=Path("bounded.wav"),
            span_cache=FakeActivitySpanCache(
                {spec.start_seconds: -40.0 for spec in specs},
                {spec.start_seconds: 0.8 for spec in specs},
            ),
            candidate_specs=specs,
        )
        embeddings = {
            spec.start_seconds: (
                (1.0, 0.0) if index % 2 == 0 else (0.0, 1.0)
            )
            for index, spec in enumerate(specs)
        }

        refined = refine_activity_qualified_spans(
            prepared,
            embedding_cache=FakeEmbeddingCache(embeddings),
            backend=object(),
            policy=self._policy().policy,
        )

        self.assertEqual(
            500,
            refined.selection["consistency_fallback_subsets_evaluated"],
        )
        self.assertLessEqual(
            refined.selection[
                "consistency_fallback_pairwise_similarities"
            ],
            105,
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
            source_complete_link_limit=0,
            source_nearest_neighbors=0,
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
