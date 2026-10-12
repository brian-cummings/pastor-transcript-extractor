from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.sermon_salvation_observation_review import (
    SALVATION_BOUNDARY_RECALIBRATION_ANCHORS,
    SALVATION_BOUNDARY_RECALIBRATION_RELATIONSHIPS,
    SALVATION_COLLECTED_OBSERVATION_REVIEW_POLICY_VERSION,
    SALVATION_CONVERSION_RECALIBRATION_ANCHORS,
    SALVATION_CONVERSION_WATCH_FIXTURES,
    SALVATION_FINAL_COLLECTION_CHECK_ANCHORS,
    SALVATION_FINAL_COLLECTION_CHECK_RELATIONSHIPS,
    SALVATION_JUDGMENT_WATCH_KEY,
    SALVATION_COLLECTION_RECALIBRATION_RELATIONSHIPS,
    SALVATION_COLLECTION_REVIEWED_ANCHORS,
    _source_artifact_fingerprints,
    build_salvation_boundary_recalibration,
    build_salvation_collection_recalibration,
    build_salvation_collected_observations_review,
    build_salvation_conversion_recalibration,
    build_salvation_final_collection_check,
    render_salvation_collection_recalibration,
    render_salvation_collected_observations_review,
    render_salvation_conversion_recalibration,
    write_salvation_collection_recalibration,
    write_salvation_collected_observations_review,
    write_salvation_conversion_recalibration,
)
from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIPS_PACK_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
    SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES,
    UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS,
)


def _block(block_id: int, *, collected: bool) -> dict[str, object]:
    probabilities = {
        relationship: round(
            threshold if collected else threshold - 0.01,
            6,
        )
        for relationship, threshold in (
            SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS.items()
        )
    }
    probabilities["repentance_as_receiving_response"] = 0.99
    probabilities["obedience_as_condition_or_means"] = 0.99
    probabilities["obedience_as_consequence_or_evidence"] = 0.99
    return {
        "block_id": block_id,
        "start_seconds": float(block_id * 60),
        "end_seconds": float((block_id + 1) * 60),
        "context": {
            "leading_context": "Leading.",
            "target_text": f"Target {block_id}.",
            "trailing_context": "Trailing.",
        },
        "probabilities": probabilities,
        "observations": (
            [
                {
                    "relationship": relationship,
                    "probability": probabilities[relationship],
                    "threshold": threshold,
                }
                for relationship, threshold in (
                    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS.items()
                )
            ]
            if collected
            else []
        ),
    }


def _source() -> dict[str, object]:
    return {
        "pastor": {"display_name": "Pastor", "slug": "pastor"},
        "video_id": 1,
        "youtube_video_id": "youtube-1",
        "title": "Sermon",
        "stored_artifact_sha256": "stored",
        "artifact": {
            "question_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
            "observation_policy_version": (
                SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
            ),
            "final_projection_reconciled": True,
            "missing_current_routed_block_ids": [],
            "observation_thresholds": dict(
                SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS
            ),
            "measurement_statuses": dict(
                SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES
            ),
            "projection_excluded_relationships": sorted(
                UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS
            ),
            "blocks": [_block(1, collected=False), _block(2, collected=True)],
        },
    }


class SalvationCollectedObservationReviewTests(unittest.TestCase):
    def test_conversion_recalibration_is_fresh_bounded_and_provider_free(self) -> None:
        source = {
            "video_id": 1,
            "stored_artifact_sha256": "stored",
            "artifact": {},
        }

        def judgment(
            key: str,
            relationship: str,
            probability: float,
            pastor: str,
        ) -> dict[str, object]:
            video_id, block_id, _leaf = key.split(":")
            threshold = SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS.get(
                relationship,
                0.60,
            )
            return {
                "judgment_key": key,
                "relationship": relationship,
                "probability": probability,
                "threshold": threshold,
                "collected": probability >= threshold,
                "pastor": {"display_name": pastor, "slug": pastor.lower()},
                "video_id": int(video_id),
                "youtube_video_id": f"youtube-{video_id}",
                "title": f"Sermon {video_id}",
                "block_id": int(block_id),
                "start_seconds": float(block_id),
                "end_seconds": float(block_id) + 1.0,
                "leading_context": "Leading.",
                "target_text": f"Target {key}.",
                "trailing_context": "Trailing.",
            }

        judgments = []
        for key in SALVATION_CONVERSION_RECALIBRATION_ANCHORS:
            judgments.append(
                judgment(
                    key,
                    "conversion_new_birth",
                    0.54 if key.startswith("590:") else 0.55,
                    "Anchor",
                )
            )
        for key in SALVATION_CONVERSION_WATCH_FIXTURES:
            relationship = key.rsplit(":", 1)[1]
            judgments.append(judgment(key, relationship, 0.60, "Watch"))
        for index, probability in enumerate(
            (0.51, 0.52, 0.53, 0.54, 0.55, 0.56, 0.57, 0.58),
            start=1,
        ):
            judgments.append(
                judgment(
                    f"9{index:03d}:1:conversion_new_birth",
                    "conversion_new_birth",
                    probability,
                    f"Fresh {index}",
                )
            )
        prior = {
            "review_policy_version": (
                SALVATION_COLLECTED_OBSERVATION_REVIEW_POLICY_VERSION
            ),
            "question_pack_version": (
                "salvation-relationships-v7-repentance-response-context"
            ),
            "observation_policy_version": (
                SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
            ),
            "input_fingerprint": "prior",
            "source_artifacts": _source_artifact_fingerprints([source]),
            "cases": [],
        }
        with (
            patch(
                "pastor_transcript_extractor.sermon_salvation_observation_review."
                "SALVATION_RELATIONSHIPS_PACK_VERSION",
                "salvation-relationships-v7-repentance-response-context",
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_observation_review."
                "_validated_source_judgments",
                return_value=judgments,
            ),
        ):
            packet = build_salvation_conversion_recalibration(
                [source],
                cohort_sha256="cohort",
                readiness_input_fingerprint="readiness",
                prior_review=prior,
            )

        fresh = [
            probe
            for probe in packet["probes"]
            if probe["probe_role"] == "fresh_cached_neighbor"
        ]
        self.assertEqual(8, len(fresh))
        self.assertEqual(
            {"below": 4, "at_or_above": 4},
            {
                side: sum(probe["boundary_side"] == side for probe in fresh)
                for side in ("below", "at_or_above")
            },
        )
        self.assertEqual(
            {"conversion_new_birth"},
            {probe["relationship"] for probe in fresh},
        )
        self.assertEqual(2, len(packet["regression_anchors"]))
        self.assertEqual(6, len(packet["frozen_watch_fixtures"]))
        self.assertEqual(8, len(packet["frozen_relationships"]))
        self.assertEqual(0, packet["provider_requests"])
        self.assertEqual("none", packet["policy_effect"])
        markdown = render_salvation_conversion_recalibration(packet)
        self.assertIn("eight fresh conversion probes", markdown)
        self.assertIn("cannot authorize changes here", markdown)

        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "conversion.json"
            _json_path, _markdown_path, reused = (
                write_salvation_conversion_recalibration(output, packet)
            )
            self.assertFalse(reused)
            _json_path, _markdown_path, reused = (
                write_salvation_conversion_recalibration(output, packet)
            )
            self.assertTrue(reused)

    def test_conversion_recalibration_is_archived_after_v8(self) -> None:
        with self.assertRaisesRegex(ValueError, "archived after the v8"):
            build_salvation_conversion_recalibration(
                [],
                cohort_sha256="cohort",
                readiness_input_fingerprint="readiness",
                prior_review={},
            )

    def test_final_collection_check_is_bounded_and_provider_free(self) -> None:
        with self.assertRaisesRegex(ValueError, "archived"):
            build_salvation_final_collection_check(
                [],
                cohort_sha256="cohort",
                readiness_input_fingerprint="readiness",
                prior_review={},
            )
        return
        source = {
            "video_id": 1,
            "stored_artifact_sha256": "stored",
            "artifact": {},
        }

        def judgment(key, relationship, probability, pastor):
            video_id, block_id, _leaf = key.split(":")
            threshold = SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[relationship]
            return {
                "judgment_key": key,
                "relationship": relationship,
                "probability": probability,
                "threshold": threshold,
                "collected": probability >= threshold,
                "pastor": {"display_name": pastor, "slug": pastor.lower()},
                "video_id": int(video_id),
                "youtube_video_id": f"youtube-{video_id}",
                "title": f"Sermon {video_id}",
                "block_id": int(block_id),
                "start_seconds": float(block_id),
                "end_seconds": float(block_id) + 1.0,
                "leading_context": "Leading.",
                "target_text": f"Target {key}.",
                "trailing_context": "Trailing.",
            }

        judgments = []
        for key in SALVATION_FINAL_COLLECTION_CHECK_ANCHORS:
            relationship = key.rsplit(":", 1)[1]
            threshold = SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[relationship]
            judgments.append(judgment(key, relationship, threshold, "Anchor"))
        fresh_id = 8000
        for relationship, probabilities in {
            "conversion_new_birth": (0.54, 0.56),
            "forgiveness_pardon": (0.68, 0.69),
            "assurance_security": (0.61, 0.62),
        }.items():
            for probability in probabilities:
                fresh_id += 1
                judgments.append(
                    judgment(
                        f"{fresh_id}:1:{relationship}",
                        relationship,
                        probability,
                        f"Pastor {fresh_id}",
                    )
                )
        repentance = "repentance_as_receiving_response"
        repentance_threshold = SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[
            repentance
        ]
        for direction in (-1, 1):
            for rank in range(3):
                fresh_id += 1
                judgments.append(
                    judgment(
                        f"{fresh_id}:1:{repentance}",
                        repentance,
                        round(repentance_threshold + direction * (rank + 1) / 100, 2),
                        f"Pastor {rank}",
                    )
                )
        prior = {
            "review_policy_version": (
                SALVATION_COLLECTED_OBSERVATION_REVIEW_POLICY_VERSION
            ),
            "input_fingerprint": "prior",
            "source_artifacts": _source_artifact_fingerprints([source]),
            "probes": [
                {"judgment_key": key}
                for key in SALVATION_FINAL_COLLECTION_CHECK_ANCHORS
            ],
        }
        with patch(
            "pastor_transcript_extractor.sermon_salvation_observation_review."
            "_validated_source_judgments",
            return_value=judgments,
        ):
            packet = build_salvation_final_collection_check(
                [source],
                cohort_sha256="cohort",
                readiness_input_fingerprint="readiness",
                prior_review=prior,
            )

        self.assertEqual(
            set(SALVATION_FINAL_COLLECTION_CHECK_RELATIONSHIPS),
            {probe["relationship"] for probe in packet["probes"]},
        )
        self.assertEqual(
            8,
            sum(
                probe["relationship"] == repentance
                for probe in packet["probes"]
            ),
        )
        self.assertEqual(8, len(packet["frozen_relationships"]))
        self.assertEqual(0, packet["provider_requests"])

    def test_boundary_recalibration_combines_anchors_fresh_probes_and_watch(self) -> None:
        source = {
            "video_id": 1,
            "stored_artifact_sha256": "stored",
            "artifact": {},
        }
        judgments = []

        def judgment(key, relationship, probability, collected, pastor):
            video_id, block_id, _leaf = key.split(":")
            return {
                "judgment_key": key,
                "relationship": relationship,
                "probability": probability,
                "threshold": SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS.get(
                    relationship,
                    0.70,
                ),
                "collected": collected,
                "pastor": {"display_name": pastor, "slug": pastor.lower()},
                "video_id": int(video_id),
                "youtube_video_id": f"youtube-{video_id}",
                "title": f"Sermon {video_id}",
                "block_id": int(block_id),
                "start_seconds": float(block_id),
                "end_seconds": float(block_id) + 1.0,
                "leading_context": "Leading.",
                "target_text": f"Target {key}.",
                "trailing_context": "Trailing.",
            }

        for key in SALVATION_BOUNDARY_RECALIBRATION_ANCHORS:
            relationship = key.rsplit(":", 1)[1]
            threshold = SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS.get(
                relationship,
                0.70,
            )
            judgments.append(
                judgment(key, relationship, threshold, True, "Anchor")
            )
        judgments.append(
            judgment(
                SALVATION_JUDGMENT_WATCH_KEY,
                "judgment_final_destiny",
                0.62,
                False,
                "Watch",
            )
        )
        fresh_index = 9000
        for relationship in SALVATION_BOUNDARY_RECALIBRATION_RELATIONSHIPS:
            threshold = SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS.get(
                relationship,
                0.70,
            )
            for side, collected in ((-1, False), (1, True)):
                for rank in range(2):
                    fresh_index += 1
                    judgments.append(
                        judgment(
                            f"{fresh_index}:{rank}:{relationship}",
                            relationship,
                            round(threshold + side * (rank + 1) / 100, 2),
                            collected,
                            f"Pastor {rank}",
                        )
                    )
        prior = {
            "review_policy_version": (
                SALVATION_COLLECTED_OBSERVATION_REVIEW_POLICY_VERSION
            ),
            "input_fingerprint": "prior",
            "source_artifacts": _source_artifact_fingerprints([source]),
            "probes": [
                {"judgment_key": key}
                for key in (
                    *SALVATION_BOUNDARY_RECALIBRATION_ANCHORS,
                    SALVATION_JUDGMENT_WATCH_KEY,
                )
            ],
        }
        with patch(
            "pastor_transcript_extractor.sermon_salvation_observation_review."
            "_validated_source_judgments",
            return_value=judgments,
        ):
            packet = build_salvation_boundary_recalibration(
                [source],
                cohort_sha256="cohort",
                readiness_input_fingerprint="readiness",
                prior_review=prior,
            )

        self.assertEqual(25, len(packet["probes"]))
        self.assertEqual(
            16,
            sum(
                probe["probe_role"] == "fresh_probability_neighbor"
                for probe in packet["probes"]
            ),
        )
        self.assertEqual(
            1,
            sum(probe["probe_role"] == "watch_only" for probe in packet["probes"]),
        )
        self.assertEqual("none", packet["policy_effect"])

    def test_selects_both_policy_sides_for_every_relationship(self) -> None:
        packet = build_salvation_collected_observations_review(
            [_source()],
            cohort_sha256="cohort",
            readiness_input_fingerprint="readiness",
        )

        self.assertEqual(
            2 * len(SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS),
            len(packet["probes"]),
        )
        self.assertEqual(2, packet["routed_block_count"])
        self.assertEqual(2, len(packet["cases"]))
        self.assertTrue(
            all("target_text" not in probe for probe in packet["probes"])
        )
        self.assertTrue(all("case_key" in probe for probe in packet["probes"]))
        self.assertEqual(
            "stored",
            packet["source_artifacts"][0]["stored_artifact_sha256"],
        )
        self.assertIn(
            "effective_artifact_sha256",
            packet["source_artifacts"][0],
        )
        markdown = render_salvation_collected_observations_review(packet)
        assurance = packet["relationship_definitions"]["assurance_security"]
        self.assertIn(assurance["description"], markdown)
        self.assertIn(assurance["true_criteria"], markdown)
        self.assertIn(assurance["false_criteria"], markdown)
        self.assertIn("not the intensity of the doctrine", markdown)
        self.assertEqual(1, markdown.count("> Target 1."))
        self.assertEqual(1, markdown.count("> Target 2."))
        for relationship in SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS:
            self.assertEqual(
                {"strongest_rejected", "weakest_collected"},
                {
                    probe["boundary_side"]
                    for probe in packet["probes"]
                    if probe["relationship"] == relationship
                },
            )

        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "review.json"
            _json_path, _markdown_path, reused = (
                write_salvation_collected_observations_review(output, packet)
            )
            self.assertFalse(reused)
            _json_path, _markdown_path, reused = (
                write_salvation_collected_observations_review(output, packet)
            )
            self.assertTrue(reused)

    def test_rejects_stored_observations_that_disagree_with_policy(self) -> None:
        source = _source()
        source["artifact"]["blocks"][1]["observations"] = []

        with self.assertRaisesRegex(ValueError, "inconsistent"):
            build_salvation_collected_observations_review(
                [source],
                cohort_sha256="cohort",
                readiness_input_fingerprint="readiness",
            )

    def test_rejects_missing_current_route_evidence(self) -> None:
        source = _source()
        source["artifact"]["missing_current_routed_block_ids"] = [9]

        with self.assertRaisesRegex(ValueError, "missing relationship evidence"):
            build_salvation_collected_observations_review(
                [source],
                cohort_sha256="cohort",
                readiness_input_fingerprint="readiness",
            )

    def test_recalibration_selects_only_fresh_unsettled_leaf_probes(self) -> None:
        with self.assertRaisesRegex(ValueError, "archived"):
            build_salvation_collection_recalibration(
                [],
                cohort_sha256="cohort",
                readiness_input_fingerprint="readiness",
                prior_review={},
            )
        return
        source = deepcopy(_source())
        source["artifact"]["blocks"] = [
            *[_block(block_id, collected=False) for block_id in range(1, 7)],
            *[_block(block_id, collected=True) for block_id in range(7, 13)],
        ]
        prior = build_salvation_collected_observations_review(
            [source],
            cohort_sha256="cohort",
            readiness_input_fingerprint="readiness",
        )
        prior["probes"].extend(
            {"judgment_key": judgment_key}
            for judgment_key in SALVATION_COLLECTION_REVIEWED_ANCHORS
        )

        packet = build_salvation_collection_recalibration(
            [source],
            cohort_sha256="cohort",
            readiness_input_fingerprint="readiness",
            prior_review=prior,
        )

        self.assertEqual(18, len(packet["probes"]))
        self.assertEqual(
            set(SALVATION_COLLECTION_RECALIBRATION_RELATIONSHIPS),
            {probe["relationship"] for probe in packet["probes"]},
        )
        self.assertTrue(
            set(SALVATION_COLLECTION_REVIEWED_ANCHORS).isdisjoint(
                {probe["judgment_key"] for probe in packet["probes"]}
            )
        )
        self.assertEqual(
            6,
            sum(
                probe["relationship"] == "repentance_as_receiving_response"
                for probe in packet["probes"]
            ),
        )
        markdown = render_salvation_collection_recalibration(packet)
        self.assertIn("semantic-ordering defect", markdown)
        self.assertIn("eight clean relationship", packet["interpretation"])

        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "recalibration.json"
            _json_path, _markdown_path, reused = (
                write_salvation_collection_recalibration(output, packet)
            )
            self.assertFalse(reused)
            _json_path, _markdown_path, reused = (
                write_salvation_collection_recalibration(output, packet)
            )
            self.assertTrue(reused)


if __name__ == "__main__":
    unittest.main()
