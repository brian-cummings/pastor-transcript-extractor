from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.models import Video, VideoStatus
from pastor_transcript_extractor.sermon_classifier_typesafe import (
    SALVATION_RELATIONSHIPS_PACK,
    TypeSafeBlockAnswer,
)
from pastor_transcript_extractor.sermon_salvation_relationship_review import (
    ALL_REVIEWED_CANDIDATE_KEYS,
    PRIOR_REVIEWED_CANDIDATE_KEYS,
    PRIOR_V4_SALVATION_RELATIONSHIPS_PACK_VERSION,
    PRIOR_V5_SALVATION_RELATIONSHIPS_PACK_VERSION,
    PRIOR_V6_SALVATION_RELATIONSHIPS_PACK_VERSION,
    PRIOR_V8_SALVATION_RELATIONSHIPS_PACK_VERSION,
    SEMANTIC_CALIBRATION_RELATIONSHIPS,
    V5_CALIBRATION_RELATIONSHIPS,
    V5_REVIEW_LABELS,
    V6_REPENTANCE_REGRESSION_LABELS,
    V7_REPENTANCE_REGRESSION_LABELS,
    SALVATION_V8_CONVERSION_REGRESSION_LABELS,
    SALVATION_V8_CONVERSION_SOURCE_FINGERPRINT,
    SALVATION_V8_CONVERSION_SOURCE_POLICY_VERSION,
    SALVATION_FINAL_BOUNDARY_REVIEW_LABELS,
    SALVATION_FINAL_BOUNDARY_SOURCE_REVIEW_FINGERPRINT,
    SALVATION_FINAL_BOUNDARY_SOURCE_REVIEW_POLICY_VERSION,
    SALVATION_CONDITION_BOUNDARY_SOURCE_FINGERPRINT,
    SALVATION_V9_CONSEQUENCE_REGRESSION_LABELS,
    _select_semantic_heldout_probes,
    _select_v5_heldout_probes,
    _select_repentance_heldout_probes,
    _select_review_candidates,
    build_salvation_v5_threshold_review,
    build_salvation_condition_boundary_review,
    evaluate_salvation_final_calibration,
    evaluate_salvation_semantic_calibration,
    evaluate_salvation_relationship_review,
    evaluate_salvation_v5_calibration,
    evaluate_salvation_v6_repentance_calibration,
    evaluate_salvation_v7_repentance_calibration,
    evaluate_salvation_v8_conversion_calibration,
    evaluate_salvation_final_boundary_calibration,
    select_obedience_consequence_calibration_candidates,
    write_salvation_relationship_review,
)
from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIPS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
    salvation_relationship_pack_digest,
)
from pastor_transcript_extractor.sermon_topics import TOPICS, TOPIC_PACK_VERSION


class _Database:
    def __init__(self, videos: list[Video]) -> None:
        self._videos = videos

    def list_videos(self) -> list[Video]:
        return self._videos


class _Client:
    def __init__(self) -> None:
        self.calls = 0

    def assess_blocks(
        self,
        recording_context,
        blocks,
        *,
        requested_packs=None,
        topic_contexts=None,
        **_kwargs,
    ):
        del recording_context
        self.calls += 1
        self.assert_leaf_request(requested_packs, topic_contexts, blocks)
        return {
            block.block_id: TypeSafeBlockAnswer(
                choice="unclear",
                probabilities={},
                confidence=None,
                resolved_model_id="jev-1.13.0",
                request_provenance={"request_key": f"request-{self.calls}"},
                salvation_relationship_probabilities={
                    relationship: 0.75
                    for relationship in SALVATION_RELATIONSHIPS
                },
                salvation_relationship_question_version=(
                    SALVATION_RELATIONSHIPS_PACK_VERSION
                ),
                salvation_relationship_context={},
            )
            for block in blocks
        }

    @staticmethod
    def assert_leaf_request(requested_packs, topic_contexts, blocks) -> None:
        if requested_packs != frozenset({SALVATION_RELATIONSHIPS_PACK}):
            raise AssertionError(requested_packs)
        if set(topic_contexts or {}) != {block.block_id for block in blocks}:
            raise AssertionError("missing contexts")


def _video(video_id: int) -> Video:
    return Video(
        id=video_id,
        source_id=1,
        pastor_id=None,
        youtube_video_id=f"youtube-{video_id}",
        title=f"Sermon {video_id}",
        url=f"https://www.youtube.com/watch?v=youtube-{video_id}",
        channel_name=None,
        published_at=None,
        duration_seconds=1200,
        status=VideoStatus.EXTRACTED,
    )


def _block(block_id: int, support: float) -> dict[str, object]:
    scores = {
        topic: {
            "score": 0.0,
            "probabilities": {
                "0": 1.0,
                "1": 0.0,
                "2": 0.0,
                "3": 0.0,
                "4": 0.0,
            },
            "confidence": 1.0,
        }
        for topic in TOPICS
    }
    scores["salvation_gospel"] = {
        "score": support * 2,
        "probabilities": {
            "0": 1.0 - support,
            "1": 0.0,
            "2": support,
            "3": 0.0,
            "4": 0.0,
        },
        "confidence": 0.5,
    }
    return {
        "block_id": block_id,
        "start_seconds": float(block_id * 60),
        "end_seconds": float((block_id + 1) * 60),
        "segment_indexes": [block_id],
        "context": {
            "leading_context": f"Leading {block_id}.",
            "target_text": f"Target {block_id} salvation relationship.",
            "trailing_context": f"Trailing {block_id}.",
            "diagnostics": {"policy_version": "context-v1"},
        },
        "scores": scores,
        "projection_eligibility": {"eligible": True},
    }


class SalvationRelationshipReviewTests(unittest.TestCase):
    def test_v5_calibration_selects_fresh_diverse_probes_on_both_sides(self) -> None:
        candidates = [
            {
                "candidate_key": f"800{pastor}:{block}",
                "pastor": {"slug": f"pastor-{pastor}"},
            }
            for pastor in range(4)
            for block in range(4)
        ]
        prior = {
            candidate["candidate_key"]: {
                relationship: round(
                    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS.get(
                        relationship,
                        0.57,
                    )
                    + (-0.01, 0.01)[index % 2],
                    2,
                )
                for relationship in V5_CALIBRATION_RELATIONSHIPS
            }
            for index, candidate in enumerate(candidates)
        }

        probes = _select_v5_heldout_probes(
            candidates,
            prior,
            excluded_case_keys=set(),
        )

        self.assertEqual(16, len(probes))
        for relationship in V5_CALIBRATION_RELATIONSHIPS:
            selected = [
                probe for probe in probes if probe["relationship"] == relationship
            ]
            self.assertEqual(4, len(selected))
            self.assertEqual(
                {"below", "at_or_above"},
                {probe["prior_boundary_side"] for probe in selected},
            )

    def test_v5_calibration_fills_sparse_side_from_nearest_fresh_cases(self) -> None:
        candidates = [
            {
                "candidate_key": f"900{index}:{index}",
                "pastor": {"slug": f"pastor-{index}"},
            }
            for index in range(8)
        ]
        sparse_relationship = "obedience_as_condition_or_means"
        prior = {
            candidate["candidate_key"]: {
                relationship: (
                    0.71
                    if relationship == sparse_relationship and index == 0
                    else 0.69
                    if relationship == sparse_relationship
                    else SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[relationship]
                    + (-0.01, 0.01)[index % 2]
                )
                for relationship in V5_CALIBRATION_RELATIONSHIPS
            }
            for index, candidate in enumerate(candidates)
        }

        probes = _select_v5_heldout_probes(
            candidates,
            prior,
            excluded_case_keys=set(),
        )

        selected = [
            probe
            for probe in probes
            if probe["relationship"] == sparse_relationship
        ]
        self.assertEqual(4, len(selected))
        self.assertEqual(
            1,
            sum(
                probe["prior_boundary_side"] == "at_or_above"
                for probe in selected
            ),
        )
        self.assertEqual(
            1,
            sum(probe["selection_mode"] == "quota_fill" for probe in selected),
        )

    def test_v6_repentance_selects_eight_fresh_diverse_boundary_cases(self) -> None:
        candidates = [
            {
                "candidate_key": f"v6:{index}",
                "pastor": {"slug": f"pastor-{index % 4}"},
            }
            for index in range(18)
        ]
        prior = {
            candidate["candidate_key"]: {
                "repentance_as_receiving_response": 0.56 if index < 9 else 0.58
            }
            for index, candidate in enumerate(candidates)
        }

        probes = _select_repentance_heldout_probes(
            candidates,
            prior,
            excluded_case_keys={"v6:0", "v6:9"},
            threshold=0.57,
            calibration_version="V6",
        )

        self.assertEqual(8, len(probes))
        self.assertEqual(
            {"below": 4, "at_or_above": 4},
            {
                side: sum(
                    probe["prior_boundary_side"] == side for probe in probes
                )
                for side in ("below", "at_or_above")
            },
        )
        self.assertTrue(
            {"v6:0", "v6:9"}.isdisjoint(
                {probe["candidate_key"] for probe in probes}
            )
        )

    def test_v6_repentance_calibration_uses_regressions_and_fresh_cases(
        self,
    ) -> None:
        regression_keys = sorted(
            judgment_key.rsplit(":", 1)[0]
            for judgment_key in V6_REPENTANCE_REGRESSION_LABELS
        )
        fresh_keys = [f"fresh:{index}" for index in range(20)]
        all_keys = regression_keys + fresh_keys
        candidates = [
            {
                "candidate_key": key,
                "pastor": {"slug": f"pastor-{index % 4}"},
            }
            for index, key in enumerate(all_keys)
        ]
        prior = {
            key: {
                "repentance_as_receiving_response": (
                    0.56 if index < 10 else 0.58
                )
            }
            for index, key in enumerate(fresh_keys)
        }
        prior.update(
            {
                key: {"repentance_as_receiving_response": 0.57}
                for key in regression_keys
            }
        )
        evaluated = [
            {
                **candidate,
                "leaf_probabilities": {
                    "repentance_as_receiving_response": 0.75,
                },
            }
            for candidate in candidates
        ]
        final_check = {
            "review_policy_version": "salvation-final-collection-boundary-check-v1",
            "question_pack_version": PRIOR_V5_SALVATION_RELATIONSHIPS_PACK_VERSION,
            "observation_policy_version": (
                "salvation-relationship-observation-thresholds-v4-v5-final"
            ),
            "input_fingerprint": "final-check",
            "current_thresholds": {
                "repentance_as_receiving_response": 0.57,
            },
            "probes": [
                {
                    "judgment_key": judgment_key,
                    "relationship": "repentance_as_receiving_response",
                }
                for judgment_key in V6_REPENTANCE_REGRESSION_LABELS
            ],
            "cases": [{"case_key": key} for key in regression_keys],
        }
        v5_calibration = {
            "review_policy_version": "salvation-v5-causal-boundaries-calibration-v1",
            "revised_leaf_pack_version": PRIOR_V5_SALVATION_RELATIONSHIPS_PACK_VERSION,
            "input_fingerprint": "v5-calibration",
            "cases": [],
        }
        collection_review = {
            "review_policy_version": (
                "salvation-collected-observation-boundaries-v2-deduplicated-evidence"
            ),
            "question_pack_version": PRIOR_V5_SALVATION_RELATIONSHIPS_PACK_VERSION,
            "input_fingerprint": "collection-review",
            "cases": [],
        }

        with (
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review.SALVATION_RELATIONSHIPS_PACK_VERSION",
                PRIOR_V6_SALVATION_RELATIONSHIPS_PACK_VERSION,
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review._routed_candidates",
                return_value=(candidates, "readiness-fingerprint"),
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review._relationship_probabilities_for_pack",
                return_value=prior,
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review.evaluate_salvation_relationship_candidates",
                return_value=(
                    evaluated,
                    {"hits": 0, "misses": 16, "provider_requests": 16},
                ),
            ),
        ):
            packet, execution = evaluate_salvation_v6_repentance_calibration(
                None,
                {"cohort_sha256": "cohort"},
                final_check,
                v5_calibration,
                collection_review,
                model="jev-1.13.0",
                client=_Client(),
            )

        self.assertEqual(8, len(packet["regression_probes"]))
        self.assertEqual(8, len(packet["heldout_probes"]))
        self.assertEqual(16, len(packet["cases"]))
        self.assertEqual(16, execution["provider_requests"])
        self.assertTrue(
            set(regression_keys).isdisjoint(
                {probe["candidate_key"] for probe in packet["heldout_probes"]}
            )
        )

    def test_v7_repentance_calibration_reuses_all_v6_cases_as_regressions(
        self,
    ) -> None:
        regression_keys = sorted(
            judgment_key.rsplit(":", 1)[0]
            for judgment_key in V7_REPENTANCE_REGRESSION_LABELS
        )
        fresh_keys = [f"v7-fresh:{index}" for index in range(20)]
        candidates = [
            {
                "candidate_key": key,
                "pastor": {"slug": f"pastor-{index % 4}"},
            }
            for index, key in enumerate(regression_keys + fresh_keys)
        ]
        prior = {
            key: {
                "repentance_as_receiving_response": (
                    0.56 if index < 10 else 0.58
                )
            }
            for index, key in enumerate(fresh_keys)
        }
        prior.update(
            {
                key: {"repentance_as_receiving_response": 0.57}
                for key in regression_keys
            }
        )
        evaluated = [
            {
                **candidate,
                "leaf_probabilities": {
                    "repentance_as_receiving_response": 0.75,
                },
            }
            for candidate in candidates
        ]
        v6_calibration = {
            "review_policy_version": "salvation-v6-repentance-entry-calibration-v1",
            "revised_leaf_pack_version": PRIOR_V6_SALVATION_RELATIONSHIPS_PACK_VERSION,
            "input_fingerprint": "v6-calibration",
            "repentance_threshold": 0.57,
            "approved_numeric_changes": {},
            "excluded_reviewed_case_keys": [],
            "cases": [
                {
                    "candidate_key": key,
                    "leaf_probabilities": {
                        "repentance_as_receiving_response": 0.57,
                    },
                }
                for key in regression_keys
            ],
        }

        with (
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review.UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS",
                frozenset(),
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review._routed_candidates",
                return_value=(candidates, "readiness-fingerprint"),
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review._relationship_probabilities_for_pack",
                return_value=prior,
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review.evaluate_salvation_relationship_candidates",
                return_value=(
                    evaluated,
                    {"hits": 0, "misses": 24, "provider_requests": 24},
                ),
            ),
        ):
            packet, execution = evaluate_salvation_v7_repentance_calibration(
                None,
                {"cohort_sha256": "cohort"},
                v6_calibration,
                model="jev-1.13.0",
                client=_Client(),
            )

        self.assertEqual(16, len(packet["regression_probes"]))
        self.assertEqual(8, len(packet["heldout_probes"]))
        self.assertEqual(24, len(packet["cases"]))
        self.assertEqual(24, execution["provider_requests"])
        self.assertTrue(
            set(regression_keys).isdisjoint(
                {probe["candidate_key"] for probe in packet["heldout_probes"]}
            )
        )

    def test_v8_conversion_calibration_is_bounded_fresh_and_cache_first(
        self,
    ) -> None:
        regression_keys = sorted(
            judgment_key.rsplit(":", 1)[0]
            for judgment_key in SALVATION_V8_CONVERSION_REGRESSION_LABELS
        )
        fresh_keys = [f"v8-fresh:{index}" for index in range(12)]
        candidates = [
            {
                "candidate_key": key,
                "pastor": {"slug": f"pastor-{index % 4}"},
            }
            for index, key in enumerate(regression_keys + fresh_keys)
        ]
        prior = {
            key: {
                "conversion_new_birth": 0.54 if index < 6 else 0.56,
            }
            for index, key in enumerate(fresh_keys)
        }
        prior.update(
            {
                key: {"conversion_new_birth": 0.55}
                for key in regression_keys
            }
        )
        evaluated = [
            {
                **candidate,
                "leaf_probabilities": {"conversion_new_birth": 0.75},
            }
            for candidate in candidates
        ]
        conversion_review = {
            "review_policy_version": SALVATION_V8_CONVERSION_SOURCE_POLICY_VERSION,
            "question_pack_version": PRIOR_V8_SALVATION_RELATIONSHIPS_PACK_VERSION,
            "input_fingerprint": SALVATION_V8_CONVERSION_SOURCE_FINGERPRINT,
            "excluded_reviewed_case_keys": [],
            "probes": [
                {
                    "judgment_key": judgment_key,
                    "relationship": "conversion_new_birth",
                    "probability": 0.54,
                }
                for judgment_key in SALVATION_V8_CONVERSION_REGRESSION_LABELS
            ],
            "cases": [{"case_key": key} for key in regression_keys],
        }

        with (
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review.SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION",
                "salvation-relationship-observation-thresholds-v7-eleven-leaf-final",
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review.SALVATION_RELATIONSHIPS_PACK_VERSION",
                "salvation-relationships-v8-conversion-saving-state-transition",
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review._routed_candidates",
                return_value=(candidates, "readiness-fingerprint"),
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review._relationship_probabilities_for_pack",
                return_value=prior,
            ) as probability_loader,
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review.evaluate_salvation_relationship_candidates",
                return_value=(
                    evaluated,
                    {"hits": 14, "misses": 0, "provider_requests": 0},
                ),
            ),
        ):
            packet, execution = evaluate_salvation_v8_conversion_calibration(
                None,
                {"cohort_sha256": "cohort"},
                conversion_review,
                model="jev-1.13.0",
                client=_Client(),
            )

        probability_loader.assert_called_once_with(
            None,
            {"cohort_sha256": "cohort"},
            expected_pack_version=PRIOR_V8_SALVATION_RELATIONSHIPS_PACK_VERSION,
        )
        self.assertEqual(6, len(packet["regression_probes"]))
        self.assertEqual(8, len(packet["heldout_probes"]))
        self.assertEqual(14, len(packet["cases"]))
        self.assertEqual(10, len(packet["frozen_relationships"]))
        self.assertEqual(0, execution["provider_requests"])
        self.assertTrue(
            set(regression_keys).isdisjoint(
                {probe["candidate_key"] for probe in packet["heldout_probes"]}
            )
        )
        self.assertEqual(
            {"below": 4, "at_or_above": 4},
            {
                side: sum(
                    probe["prior_boundary_side"] == side
                    for probe in packet["heldout_probes"]
                )
                for side in ("below", "at_or_above")
            },
        )

    def test_v8_conversion_calibration_is_archived_after_freeze(self) -> None:
        with self.assertRaisesRegex(ValueError, "archived after"):
            evaluate_salvation_v8_conversion_calibration(
                None,
                {},
                {},
                model="jev-1.13.0",
                client=_Client(),
            )

    def test_final_boundary_calibration_is_bounded_and_mixed_mode(self) -> None:
        relationship = "obedience_as_consequence_or_evidence"
        regression_keys = {
            key.rsplit(":", 1)[0]
            for key in SALVATION_V9_CONSEQUENCE_REGRESSION_LABELS
        }
        numeric_keys = {
            key.rsplit(":", 1)[0]
            for key in SALVATION_FINAL_BOUNDARY_REVIEW_LABELS
        }
        fresh_keys = [f"final-fresh:{index}" for index in range(12)]
        all_keys = sorted(
            regression_keys
            | numeric_keys
            | {"1037:58"}
            | set(fresh_keys)
        )
        candidates = [
            {
                "candidate_key": key,
                "pastor": {
                    "display_name": f"Pastor {index % 4}",
                    "slug": f"pastor-{index % 4}",
                },
                "video_id": 1037 if key == "1037:58" else index + 1,
                "youtube_video_id": "5Yf-TlFDnD4" if key == "1037:58" else f"yt-{index}",
                "title": f"Sermon {index}",
                "block_id": 58 if key == "1037:58" else index,
                "start_seconds": 2552.319 if key == "1037:58" else float(index),
                "end_seconds": 2621.589 if key == "1037:58" else float(index + 1),
                "leading_context": "Leading.",
                "target_text": "Target.",
                "trailing_context": "Trailing.",
            }
            for index, key in enumerate(all_keys)
        ]
        prior = {
            key: {
                "atonement_as_basis": 0.1,
                "judgment_final_destiny": 0.1,
                relationship: 0.54 if index < 6 else 0.56,
            }
            for index, key in enumerate(all_keys)
        }
        prior["281:124"]["atonement_as_basis"] = 0.68
        prior["4458:72"]["atonement_as_basis"] = 0.71
        prior["4394:51"]["judgment_final_destiny"] = 0.64
        prior["4394:43"]["judgment_final_destiny"] = 0.66
        prior["4589:41"][relationship] = 0.54
        prior["4430:28"][relationship] = 0.56
        for index, key in enumerate(fresh_keys):
            prior[key][relationship] = 0.54 if index < 6 else 0.56
        evaluated = [
            {
                **candidate,
                "leaf_probabilities": {relationship: 0.75},
            }
            for candidate in candidates
        ]
        collection_review = {
            "review_policy_version": (
                SALVATION_FINAL_BOUNDARY_SOURCE_REVIEW_POLICY_VERSION
            ),
            "input_fingerprint": SALVATION_FINAL_BOUNDARY_SOURCE_REVIEW_FINGERPRINT,
            "question_pack_version": (
                "salvation-relationships-v8-conversion-saving-state-transition"
            ),
            "observation_policy_version": (
                "salvation-relationship-observation-thresholds-v8-eleven-leaf-final"
            ),
            "cases": [],
        }

        with (
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review.SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION",
                "salvation-relationship-observation-thresholds-v8-eleven-leaf-final",
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review._routed_candidates",
                return_value=(candidates, "readiness-fingerprint"),
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review._relationship_probabilities_for_pack",
                return_value=prior,
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review.evaluate_salvation_relationship_candidates",
                return_value=(
                    evaluated,
                    {"hits": 10, "misses": 0, "provider_requests": 0},
                ),
            ),
        ):
            packet, execution = evaluate_salvation_final_boundary_calibration(
                None,
                {"cohort_sha256": "cohort"},
                collection_review,
                model="jev-1.13.0",
                client=_Client(),
            )

        self.assertEqual(4, len(packet["numeric_probes"]))
        self.assertEqual(
            {"atonement_as_basis": 2, "judgment_final_destiny": 2},
            packet["numeric_probe_counts"],
        )
        self.assertEqual(2, len(packet["consequence_regression_probes"]))
        self.assertEqual(8, len(packet["consequence_heldout_probes"]))
        self.assertEqual(8, len(packet["frozen_relationships"]))
        self.assertEqual(0, execution["provider_requests"])
        self.assertIn("5Yf-TlFDnD4", packet["transcription_review"]["youtube_url"])
        self.assertTrue(
            regression_keys.isdisjoint(
                {
                    probe["candidate_key"]
                    for probe in packet["consequence_heldout_probes"]
                }
            )
        )

    def test_final_boundary_calibration_is_archived_after_review(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "archived after its reviewed numeric and semantic decisions",
        ):
            evaluate_salvation_final_boundary_calibration(
                None,
                {},
                {},
                model="jev-1.13.0",
                client=_Client(),
            )

    def test_condition_boundary_review_uses_cached_probability_tail(self) -> None:
        relationship = "obedience_as_condition_or_means"
        candidate_keys = ["1037:58", *[f"tail-{index}:1" for index in range(14)]]
        candidates = [
            {
                "candidate_key": key,
                "pastor": {
                    "display_name": f"Pastor {index % 4}",
                    "slug": f"pastor-{index % 4}",
                },
                "video_id": 1037 if key == "1037:58" else index + 1,
                "youtube_video_id": (
                    "5Yf-TlFDnD4" if key == "1037:58" else f"yt-{index}"
                ),
                "title": f"Sermon {index}",
                "block_id": 58 if key == "1037:58" else 1,
                "start_seconds": float(index),
                "end_seconds": float(index + 1),
                "leading_context": "Leading.",
                "target_text": "Target.",
                "trailing_context": "Trailing.",
            }
            for index, key in enumerate(candidate_keys)
        ]
        probabilities = {
            key: {relationship: round(0.50 - index * 0.01, 2)}
            for index, key in enumerate(candidate_keys)
        }
        probabilities["1037:58"][relationship] = 0.51
        final_boundary = {
            "input_fingerprint": SALVATION_CONDITION_BOUNDARY_SOURCE_FINGERPRINT,
            "revised_leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
            "status": "final_bounded_salvation_review_pending",
        }

        with (
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review._routed_candidates",
                return_value=(candidates, "readiness-fingerprint"),
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review._relationship_probabilities_for_pack",
                return_value=probabilities,
            ) as probability_loader,
        ):
            packet = build_salvation_condition_boundary_review(
                None,
                {"cohort_sha256": "cohort"},
                final_boundary,
            )

        self.assertEqual(12, len(packet["probes"]))
        self.assertEqual("1037:58", packet["probes"][0]["candidate_key"])
        self.assertEqual(
            "affirmative_transcription_confirmed",
            packet["probes"][0]["review_label"],
        )
        self.assertEqual(
            "usurp",
            packet["transcription_adjudication"]["heard_word"],
        )
        self.assertTrue(
            all(
                not item["collected_at_current_threshold"]
                for item in packet["probes"]
            )
        )
        probability_loader.assert_called_once()

    def test_v5_calibration_assembles_current_relationship_definitions(self) -> None:
        case_keys = sorted(
            {judgment_key.rsplit(":", 1)[0] for judgment_key in V5_REVIEW_LABELS}
        )
        candidates = [
            {"candidate_key": case_key, "pastor": {"slug": "pastor"}}
            for case_key in case_keys
        ]
        prior = {
            case_key: {
                relationship: 0.5
                for relationship in V5_CALIBRATION_RELATIONSHIPS
            }
            for case_key in case_keys
        }
        evaluated = [
            {
                **candidate,
                "case_key": candidate["candidate_key"],
                "leaf_probabilities": {
                    relationship: 0.6
                    for relationship in V5_CALIBRATION_RELATIONSHIPS
                },
            }
            for candidate in candidates
        ]
        boundary_review = {
            "review_policy_version": "salvation-four-leaf-boundary-recalibration-v1",
            "question_pack_version": PRIOR_V4_SALVATION_RELATIONSHIPS_PACK_VERSION,
            "input_fingerprint": "boundary-fingerprint",
            "probes": [
                {
                    "judgment_key": judgment_key,
                    "relationship": judgment_key.rsplit(":", 1)[1],
                }
                for judgment_key in V5_REVIEW_LABELS
            ],
            "cases": [],
        }
        collection_review = {
            "input_fingerprint": "collection-fingerprint",
            "cases": [],
        }

        with (
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review.SALVATION_RELATIONSHIPS_PACK_VERSION",
                PRIOR_V5_SALVATION_RELATIONSHIPS_PACK_VERSION,
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review._routed_candidates",
                return_value=(candidates, "readiness-fingerprint"),
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review._relationship_probabilities_for_pack",
                return_value=prior,
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review._select_v5_heldout_probes",
                return_value=[],
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_relationship_review.evaluate_salvation_relationship_candidates",
                return_value=(
                    evaluated,
                    {"hits": 0, "misses": 0, "provider_requests": 0},
                ),
            ),
        ):
            packet, _execution = evaluate_salvation_v5_calibration(
                None,
                {"cohort_sha256": "cohort"},
                boundary_review,
                collection_review,
                model="jev-1.13.0",
                client=_Client(),
            )

        self.assertEqual(
            set(V5_CALIBRATION_RELATIONSHIPS),
            set(packet["relationship_definitions"]),
        )

    def test_v5_threshold_review_uses_conversion_window_and_sparse_boundaries(
        self,
    ) -> None:
        probabilities = (0.44, 0.45, 0.50, 0.54, 0.55, 0.60, 0.70, 0.71)
        cases = [
            {
                "candidate_key": f"case:{index}",
                "pastor": {"slug": f"pastor-{index % 4}"},
                "leaf_probabilities": {
                    "divine_grace_initiative": probability,
                    "conversion_new_birth": probability,
                    "obedience_as_condition_or_means": (
                        0.78 if index == len(probabilities) - 1 else probability / 2
                    ),
                    "obedience_as_consequence_or_evidence": probability,
                },
            }
            for index, probability in enumerate(probabilities)
        ]
        calibration = {
            "review_policy_version": "salvation-v5-causal-boundaries-calibration-v1",
            "revised_leaf_pack_version": PRIOR_V5_SALVATION_RELATIONSHIPS_PACK_VERSION,
            "revised_leaf_pack_digest": salvation_relationship_pack_digest(),
            "input_fingerprint": "v5-fingerprint",
            "unchanged_thresholds": {
                relationship: SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[
                    relationship
                ]
                for relationship in V5_CALIBRATION_RELATIONSHIPS
            },
            "cases": cases,
            "regression_probes": [],
        }

        with patch(
            "pastor_transcript_extractor.sermon_salvation_relationship_review.SALVATION_RELATIONSHIPS_PACK_VERSION",
            PRIOR_V5_SALVATION_RELATIONSHIPS_PACK_VERSION,
        ):
            packet = build_salvation_v5_threshold_review(calibration)

        conversion = [
            probe
            for probe in packet["probes"]
            if probe["relationship"] == "conversion_new_birth"
        ]
        self.assertEqual(
            [0.45, 0.50, 0.54, 0.55, 0.60, 0.70],
            [probe["probability"] for probe in conversion],
        )
        for relationship in V5_CALIBRATION_RELATIONSHIPS:
            if relationship != "conversion_new_birth":
                self.assertEqual(
                    4,
                    sum(
                        probe["relationship"] == relationship
                        for probe in packet["probes"]
                    ),
                )
        condition = [
            probe
            for probe in packet["probes"]
            if probe["relationship"] == "obedience_as_condition_or_means"
        ]
        self.assertEqual(
            1,
            sum(probe["selection"] == "nearest_at_or_above" for probe in condition),
        )
        self.assertEqual(0, packet["provider_requests"])

    def test_archived_final_calibration_fails_closed_after_policy_freeze(self) -> None:
        with self.assertRaisesRegex(ValueError, "archived for the reviewed pre-freeze"):
            evaluate_salvation_final_calibration(
                None,
                {},
                model="jev-1.13.0",
                client=_Client(),
            )

    def test_archived_semantic_calibration_fails_closed_after_pack_revision(self) -> None:
        with self.assertRaisesRegex(ValueError, "archived for the reviewed v3 pack"):
            evaluate_salvation_semantic_calibration(
                None,
                {},
                model="jev-1.13.0",
                client=_Client(),
            )

    def test_semantic_calibration_selects_fresh_probes_on_both_sides(self) -> None:
        candidates = [
            {
                "candidate_key": f"900{pastor}:{block}",
                "pastor": {"slug": f"pastor-{pastor}"},
            }
            for pastor in range(4)
            for block in range(4)
        ]
        legacy = {}
        for index, candidate in enumerate(candidates):
            legacy[candidate["candidate_key"]] = {
                relationship: round(
                    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS.get(
                        relationship,
                        0.57,
                    )
                    + (-0.01, 0.01)[index % 2],
                    2,
                )
                for relationship in SEMANTIC_CALIBRATION_RELATIONSHIPS
            }

        probes = _select_semantic_heldout_probes(candidates, legacy)

        self.assertEqual(12, len(probes))
        for relationship in SEMANTIC_CALIBRATION_RELATIONSHIPS:
            relationship_probes = [
                probe
                for probe in probes
                if probe["relationship"] == relationship
            ]
            self.assertEqual(4, len(relationship_probes))
            self.assertEqual(
                {"below": 2, "at_or_above": 2},
                {
                    side: sum(
                        probe["boundary_side"] == side
                        for probe in relationship_probes
                    )
                    for side in ("below", "at_or_above")
                },
            )

    def test_obedience_calibration_selects_fresh_diverse_cue_cases(self) -> None:
        candidates = [
            {
                "candidate_key": f"{pastor_index}:{case_index}",
                "pastor": {"slug": f"pastor-{pastor_index}"},
                "target_text": "obedience " * (5 - case_index),
            }
            for pastor_index in range(1, 5)
            for case_index in range(1, 5)
        ]
        candidates.append(
            {
                "candidate_key": "4430:49",
                "pastor": {"slug": "pastor-1"},
                "target_text": "obedience " * 20,
            }
        )

        selected = select_obedience_consequence_calibration_candidates(
            candidates
        )

        self.assertEqual(12, len(selected))
        self.assertTrue(
            all(
                candidate["candidate_key"] not in ALL_REVIEWED_CANDIDATE_KEYS
                for candidate in selected
            )
        )
        self.assertEqual(
            {f"pastor-{index}": 3 for index in range(1, 5)},
            {
                slug: sum(
                    candidate["pastor"]["slug"] == slug
                    for candidate in selected
                )
                for slug in {candidate["pastor"]["slug"] for candidate in selected}
            },
        )

    def test_sampler_excludes_every_prior_development_case(self) -> None:
        supports = (0.55, 0.6, 0.7, 0.8, 0.9)
        candidates = [
            {
                "candidate_key": key,
                "pastor": {"slug": "pastor"},
                "video_id": 1,
                "block_id": index,
                "route": {"supporting_or_above_probability": support},
            }
            for index, (key, support) in enumerate(
                zip(
                    (
                        "4430:49",
                        "fresh:2",
                        "fresh:3",
                        "fresh:4",
                        "4589:47",
                    ),
                    supports,
                    strict=True,
                ),
                start=1,
            )
        ]

        selected = _select_review_candidates(candidates)

        self.assertEqual(3, len(selected))
        self.assertTrue(
            all(
                candidate["candidate_key"]
                not in PRIOR_REVIEWED_CANDIDATE_KEYS
                for candidate in selected
            )
        )

    def test_bounded_sample_replays_from_per_video_leaf_caches(self) -> None:
        videos = [_video(1), _video(2)]
        database = _Database(videos)
        cohort = {
            "cohort_sha256": "cohort-sha",
            "pastors": [
                {
                    "display_name": f"Pastor {video.id}",
                    "pastor_id": video.id,
                    "slug": f"pastor-{video.id}",
                    "sermons": [{"video_id": video.id}],
                }
                for video in videos
            ],
        }
        analyses = {
            video.id: {
                "question_pack_version": TOPIC_PACK_VERSION,
                "blocks": [
                    _block(video.id * 10 + index, support)
                    for index, support in enumerate(
                        (0.55, 0.65, 0.75, 0.95),
                        start=1,
                    )
                ],
            }
            for video in videos
        }
        client = _Client()
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            gates = {
                video.id: SimpleNamespace(
                    eligible=True,
                    source_path=str(
                        root / str(video.id) / "classification.json"
                    ),
                    topic_analysis_fingerprint=f"topic-{video.id}",
                )
                for video in videos
            }
            with (
                patch(
                    "pastor_transcript_extractor."
                    "sermon_salvation_relationship_review."
                    "assess_topic_stage4_readiness",
                    return_value={
                        "ready": True,
                        "blockers": [],
                        "input_fingerprint": "readiness-sha",
                    },
                ),
                patch(
                    "pastor_transcript_extractor."
                    "sermon_salvation_relationship_review."
                    "assess_topic_profile_projection",
                    side_effect=lambda _database, video: gates[video.id],
                ),
                patch(
                    "pastor_transcript_extractor."
                    "sermon_salvation_relationship_review."
                    "read_topic_analysis_for_gate",
                    side_effect=lambda gate: (
                        analyses[
                            int(Path(gate.source_path).parent.name)
                        ],
                        {},
                    ),
                ),
            ):
                first, first_execution = evaluate_salvation_relationship_review(
                    database,
                    cohort,
                    model="jev-1.13.0",
                    client=client,
                )
                replay, replay_execution = evaluate_salvation_relationship_review(
                    database,
                    cohort,
                    model="jev-1.13.0",
                    client=client,
                )

            output = root / "review.json"
            first_write = write_salvation_relationship_review(output, first)
            replay_write = write_salvation_relationship_review(output, replay)

        self.assertEqual(6, len(first["cases"]))
        self.assertEqual(8, first["routed_candidate_count"])
        self.assertEqual(first["input_fingerprint"], replay["input_fingerprint"])
        self.assertEqual({"hits": 0, "misses": 6, "provider_requests": 2}, first_execution)
        self.assertEqual({"hits": 6, "misses": 0, "provider_requests": 0}, replay_execution)
        self.assertEqual(2, client.calls)
        self.assertFalse(first_write[2])
        self.assertTrue(replay_write[2])


if __name__ == "__main__":
    unittest.main()
