from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.sermon_salvation_observation_review import (
    build_salvation_collected_observations_review,
    render_salvation_collected_observations_review,
    write_salvation_collected_observations_review,
)
from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIPS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
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
            "blocks": [_block(1, collected=False), _block(2, collected=True)],
        },
    }


class SalvationCollectedObservationReviewTests(unittest.TestCase):
    def test_selects_both_policy_sides_for_every_relationship(self) -> None:
        packet = build_salvation_collected_observations_review(
            [_source()],
            cohort_sha256="cohort",
            readiness_input_fingerprint="readiness",
        )

        self.assertEqual(2 * len(SALVATION_RELATIONSHIPS), len(packet["probes"]))
        self.assertEqual(2, packet["routed_block_count"])
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
        for relationship in SALVATION_RELATIONSHIPS:
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


if __name__ == "__main__":
    unittest.main()
