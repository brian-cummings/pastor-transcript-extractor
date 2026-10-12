from __future__ import annotations

import unittest

from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIPS,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
    SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
    SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES,
    SALVATION_RELATIONSHIP_SPECS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
    SALVATION_ROUTE_THRESHOLD,
    UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS,
    collected_salvation_relationships,
    refresh_salvation_relationship_projection,
    salvation_relationship_pack_digest,
    salvation_relationship_observation_threshold,
    salvation_relationship_pack_inventory,
    salvation_relationship_question_inventory,
    salvation_route_decision,
    resolve_salvation_relationship_analysis_artifact,
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
    def test_resolves_direct_and_fallback_relationship_artifacts(self) -> None:
        artifact = {"status": "observations_only"}

        self.assertIs(
            artifact,
            resolve_salvation_relationship_analysis_artifact(
                {"search": {"salvation_relationship_analysis": artifact}}
            ),
        )
        self.assertIs(
            artifact,
            resolve_salvation_relationship_analysis_artifact(
                {
                    "search": {
                        "discovery": {
                            "typesafe_first_attempt": {
                                "salvation_relationship_analysis": artifact
                            }
                        }
                    }
                }
            ),
        )

    def test_reviewed_observation_thresholds_cover_every_relationship(
        self,
    ) -> None:
        self.assertEqual(
            frozenset(
                {
                    "repentance_as_receiving_response",
                    "obedience_as_condition_or_means",
                }
            ),
            UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS,
        )
        self.assertEqual(
            set(SALVATION_RELATIONSHIPS)
            - UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS,
            set(SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS),
        )
        self.assertEqual(
            "block_level_unresolved",
            SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES[
                "repentance_as_receiving_response"
            ],
        )
        self.assertEqual(
            "block_level_unresolved",
            SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES[
                "obedience_as_condition_or_means"
            ],
        )
        self.assertEqual(
            0.65,
            salvation_relationship_observation_threshold(
                "divine_grace_initiative"
            ),
        )
        self.assertEqual(
            0.61,
            salvation_relationship_observation_threshold("assurance_security"),
        )
        self.assertEqual(
            0.68,
            salvation_relationship_observation_threshold("atonement_as_basis"),
        )
        self.assertEqual(
            0.60,
            salvation_relationship_observation_threshold(
                "obedience_as_consequence_or_evidence"
            ),
        )
        self.assertEqual(
            0.55,
            salvation_relationship_observation_threshold("conversion_new_birth"),
        )
        with self.assertRaisesRegex(ValueError, "no frozen observation threshold"):
            salvation_relationship_observation_threshold(
                "repentance_as_receiving_response"
            )
        with self.assertRaisesRegex(ValueError, "no frozen observation threshold"):
            salvation_relationship_observation_threshold(
                "obedience_as_condition_or_means"
            )

    def test_collection_policy_is_shared_and_validates_raw_inventory(self) -> None:
        self.assertEqual(
            "salvation-relationship-observation-thresholds-v9-ten-leaf-final",
            SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
        )
        probabilities = {
            relationship: threshold - 0.01
            for relationship, threshold in (
                SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS.items()
            )
        }
        probabilities["repentance_as_receiving_response"] = 1.0
        probabilities["obedience_as_condition_or_means"] = 1.0
        probabilities["assurance_security"] = 0.62
        probabilities["atonement_as_basis"] = 0.68

        self.assertEqual(
            ("atonement_as_basis", "assurance_security"),
            collected_salvation_relationships(probabilities),
        )

        probabilities.pop("atonement_as_basis")
        with self.assertRaisesRegex(ValueError, "wrong inventory"):
            collected_salvation_relationships(probabilities)

    def test_collection_policy_rejects_out_of_range_probability(self) -> None:
        probabilities = {
            relationship: 0.0 for relationship in SALVATION_RELATIONSHIPS
        }
        probabilities["assurance_security"] = 1.01

        with self.assertRaisesRegex(ValueError, "out of range"):
            collected_salvation_relationships(probabilities)

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

    def test_final_projection_reconciles_observations_without_changing_raw_values(
        self,
    ) -> None:
        probabilities = {
            relationship: 0.0 for relationship in SALVATION_RELATIONSHIPS
        }
        probabilities["assurance_security"] = 0.62
        artifact = {
            "blocks": [
                {
                    "block_id": 7,
                    "probabilities": probabilities,
                    "observations": [],
                    "route": {"route": True},
                }
            ]
        }

        refresh_salvation_relationship_projection(
            artifact,
            {"blocks": [_block(support=0.8)]},
        )

        self.assertEqual(probabilities, artifact["blocks"][0]["probabilities"])
        self.assertEqual(
            ["assurance_security"],
            [
                item["relationship"]
                for item in artifact["blocks"][0]["observations"]
            ],
        )
        self.assertEqual("observations_only", artifact["status"])
        self.assertTrue(artifact["final_projection_reconciled"])
        self.assertEqual([], artifact["missing_current_routed_block_ids"])
        self.assertEqual(
            "block_level_unresolved",
            artifact["measurement_statuses"][
                "repentance_as_receiving_response"
            ],
        )
        self.assertEqual(
            [
                "obedience_as_condition_or_means",
                "repentance_as_receiving_response",
            ],
            artifact["projection_excluded_relationships"],
        )

        refresh_salvation_relationship_projection(
            artifact,
            {"blocks": [_block(support=0.8, eligible=False)]},
        )

        self.assertEqual([], artifact["blocks"][0]["observations"])
        self.assertEqual("not_routed", artifact["status"])
        self.assertEqual([7], artifact["inactive_evaluated_block_ids"])

    def test_final_projection_reports_new_route_without_leaf_evidence(self) -> None:
        artifact = {"blocks": []}

        refresh_salvation_relationship_projection(
            artifact,
            {"blocks": [_block(support=0.8)]},
        )

        self.assertEqual("incomplete_current_route_evidence", artifact["status"])
        self.assertEqual([7], artifact["missing_current_routed_block_ids"])

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
        self.assertEqual(
            "salvation-relationships-v9-consequence-conduct-boundary",
            SALVATION_RELATIONSHIPS_PACK_VERSION,
        )
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
        self.assertIn(
            "means by which",
            SALVATION_RELATIONSHIP_SPECS[
                "faith_as_receiving_response"
            ].true_criteria,
        )
        self.assertIn(
            "human response within",
            SALVATION_RELATIONSHIP_SPECS[
                "repentance_as_receiving_response"
            ].true_criteria,
        )
        self.assertIn(
            "Do not infer repentance",
            SALVATION_RELATIONSHIP_SPECS[
                "repentance_as_receiving_response"
            ].false_criteria,
        )
        self.assertIn(
            "generic transformation",
            SALVATION_RELATIONSHIP_SPECS[
                "obedience_as_consequence_or_evidence"
            ].false_criteria,
        )
        self.assertIn(
            "already at work before",
            SALVATION_RELATIONSHIP_SPECS[
                "divine_grace_initiative"
            ].true_criteria,
        )
        self.assertIn(
            "already saved or justified",
            SALVATION_RELATIONSHIP_SPECS["conversion_new_birth"].false_criteria,
        )
        self.assertIn(
            "saving-state transition",
            SALVATION_RELATIONSHIP_SPECS["conversion_new_birth"].true_criteria,
        )
        self.assertIn(
            "word converted",
            SALVATION_RELATIONSHIP_SPECS["conversion_new_birth"].false_criteria,
        )
        self.assertIn(
            "causally necessary",
            SALVATION_RELATIONSHIP_SPECS[
                "obedience_as_condition_or_means"
            ].true_criteria,
        )
        self.assertIn(
            "non-conduct event",
            SALVATION_RELATIONSHIP_SPECS[
                "obedience_as_consequence_or_evidence"
            ].false_criteria,
        )
        self.assertIn(
            "walking or living in newness of life",
            SALVATION_RELATIONSHIP_SPECS[
                "obedience_as_consequence_or_evidence"
            ].true_criteria,
        )
        self.assertIn(
            "changed status",
            SALVATION_RELATIONSHIP_SPECS[
                "obedience_as_consequence_or_evidence"
            ].false_criteria,
        )


if __name__ == "__main__":
    unittest.main()
