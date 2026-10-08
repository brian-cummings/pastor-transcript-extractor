from __future__ import annotations

import unittest

from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIPS,
    SALVATION_RELATIONSHIP_SPECS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
    SALVATION_ROUTE_THRESHOLD,
    salvation_relationship_pack_digest,
    salvation_relationship_pack_inventory,
    salvation_relationship_question_inventory,
    salvation_route_decision,
)
from pastor_transcript_extractor.sermon_topics import TOPICS


def _block(*, support: float, eligible: bool = True) -> dict[str, object]:
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
        "score": 2.0 * support,
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
        "block_id": 7,
        "scores": scores,
        "projection_eligibility": {"eligible": eligible},
    }


class SalvationRelationshipsTests(unittest.TestCase):
    def test_reviewed_route_uses_supporting_mass_and_projection_eligibility(
        self,
    ) -> None:
        self.assertEqual(0.55, SALVATION_ROUTE_THRESHOLD)
        self.assertTrue(salvation_route_decision(_block(support=0.55))["route"])
        self.assertFalse(salvation_route_decision(_block(support=0.54))["route"])
        ineligible = salvation_route_decision(
            _block(support=0.95, eligible=False)
        )
        self.assertFalse(ineligible["route"])
        self.assertIn("projection_ineligible", ineligible["exclusion_reasons"])

    def test_leaf_inventory_is_independent_versioned_and_deterministic(self) -> None:
        inventory = salvation_relationship_pack_inventory()
        replay = salvation_relationship_pack_inventory()
        questions = salvation_relationship_question_inventory(2)

        self.assertEqual(SALVATION_RELATIONSHIPS_PACK_VERSION, inventory["version"])
        self.assertNotIn("routing_threshold", inventory)
        self.assertNotIn("routing_policy_version", inventory)
        self.assertEqual(inventory, replay)
        self.assertEqual(set(SALVATION_RELATIONSHIPS), set(inventory["relationships"]))
        self.assertEqual(len(SALVATION_RELATIONSHIPS), len(questions))
        self.assertTrue(
            all(question["kind"] == "noul" for question in questions.values())
        )
        self.assertTrue(
            all(
                "salvation_blocks[2].target_text"
                in question["instructions"]["task"]
                for question in questions.values()
            )
        )
        self.assertEqual(
            salvation_relationship_pack_digest(),
            salvation_relationship_pack_digest(),
        )

    def test_revised_evidence_boundaries_are_explicit_and_general(self) -> None:
        self.assertIn(
            "bearing people's sins",
            SALVATION_RELATIONSHIP_SPECS["atonement_as_basis"].true_criteria,
        )
        self.assertIn(
            "forgiveness",
            SALVATION_RELATIONSHIP_SPECS[
                "justification_right_standing"
            ].false_criteria,
        )
        self.assertIn(
            "surrender",
            SALVATION_RELATIONSHIP_SPECS[
                "sanctification_transformation"
            ].false_criteria,
        )
        self.assertIn(
            "forgives",
            SALVATION_RELATIONSHIP_SPECS[
                "divine_grace_initiative"
            ].false_criteria,
        )


if __name__ == "__main__":
    unittest.main()
