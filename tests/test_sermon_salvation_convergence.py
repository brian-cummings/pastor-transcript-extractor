"""Focused contract checks for provider-free salvation convergence."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pastor_transcript_extractor.sermon_salvation_convergence import _hash, _load_sermon, build_convergence
from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
)


class ConvergenceTest(unittest.TestCase):
    def _inputs(self, count: int = 10):
        proposal = {"policy_version": "salvation-exact-cohort-proposal-v3-diversity",
                    "provider_requests": 0,
                    "pastors": [{"profile_id": 80, "display_name": "Test",
                                 "included": [{"video_id": index} for index in range(1, count + 1)]}]}
        proposal["input_fingerprint"] = _hash({key: value for key, value in proposal.items()
                                               if key != "provider_requests"})
        sermons = []
        for index in range(1, count + 1):
            sermons.append({"video_id": index, "baseline": index <= 3,
                            "period_key": "2026-h1" if index <= count // 2 else "2026-h2",
                            "series_key": "series-a" if index <= 2 else None,
                            "source_artifact_sha256": str(index),
                            "topic_artifact_sha256": str(index),
                            "projected_artifact_sha256": str(index),
                            "relationships": {leaf: {"routed_block_fraction": index / 100,
                                                     "observed": index % 2 == 0}
                                              for leaf in SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS}})
        return proposal, {80: sermons}

    def test_partial_checkpoints_and_determinism(self):
        proposal, sermons = self._inputs()
        report = build_convergence(proposal, sermons)
        self.assertEqual(report, build_convergence(proposal, sermons))
        self.assertEqual(report["provider_requests"], 0)
        self.assertEqual(len(report["measured_relationships"]), 9)
        self.assertEqual(report["pastors"][0]["sermon_count"], 10)
        leaf = next(iter(report["pastors"][0]["relationships"].values()))
        self.assertEqual([point["status"] for point in leaf["checkpoints"]],
                         ["available"] * 6 + ["unavailable_insufficient_measured_sermons"])
        self.assertEqual(leaf["checkpoints"][0]["primary_video_ids"], [1, 2, 3])
        self.assertEqual(leaf["checkpoints"][0]["order_sensitivity"]["orders"], 129)
        self.assertEqual(len(leaf["series_sensitivity"]), 1)

    def test_frozen_membership_required(self):
        proposal, sermons = self._inputs()
        sermons[80].pop()
        with self.assertRaisesRegex(ValueError, "does not match"):
            build_convergence(proposal, sermons)

    def test_missing_leaf_artifact_is_unmeasured_not_zero(self):
        proposal, sermons = self._inputs(12)
        sermons[80][-1] = {"video_id": 12, "baseline": False,
                           "measurement_status": "unavailable_missing_cached_leaf_artifact",
                           "routed_topic_block_count": 6,
                           "topic_artifact_sha256": "topic", "classification_path": "cached.json"}
        report = build_convergence(proposal, sermons)
        pastor = report["pastors"][0]
        self.assertEqual(pastor["selected_sermon_count"], 12)
        self.assertEqual(pastor["sermon_count"], 11)
        self.assertEqual(pastor["unavailable_sermons"][0]["video_id"], 12)
        leaf = next(iter(pastor["relationships"].values()))
        self.assertEqual(leaf["checkpoints"][-1]["status"],
                         "unavailable_insufficient_measured_sermons")

    def test_zero_routed_sermon_keeps_independent_slot(self):
        database = SimpleNamespace(get_video_by_id=lambda _: SimpleNamespace(
            title="Sermon", youtube_video_id="youtube-id"))
        gate = SimpleNamespace(eligible=True, source_path="cached.json")
        def refresh(artifact, topic):
            artifact.update(routed_block_count=0, missing_current_routed_block_ids=[])
        with (patch("pastor_transcript_extractor.sermon_salvation_convergence.assess_topic_profile_projection", return_value=gate),
              patch("pastor_transcript_extractor.sermon_salvation_convergence.read_classification_for_gate", return_value={}),
              patch("pastor_transcript_extractor.sermon_salvation_convergence.resolve_topic_analysis_artifact", return_value={"blocks": []}),
              patch("pastor_transcript_extractor.sermon_salvation_convergence.resolve_salvation_relationship_analysis_artifact", return_value={"blocks": []}),
              patch("pastor_transcript_extractor.sermon_salvation_convergence.refresh_salvation_relationship_projection", side_effect=refresh)):
            sermon = _load_sermon(database, {"video_id": 4056, "baseline": False,
                                             "period_key": None, "series_key": None}, 117)
        self.assertEqual(sermon["measurement_status"], "zero_routed_blocks")
        self.assertEqual(sermon["routed_block_count"], 0)
        self.assertEqual(len(sermon["relationships"]), 9)
        self.assertTrue(all(row["routed_block_fraction"] == 0 for row in sermon["relationships"].values()))


if __name__ == "__main__":
    unittest.main()
