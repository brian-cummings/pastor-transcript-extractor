"""Focused checks for the provider-free broader rollout inventory."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
    UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS,
)
from pastor_transcript_extractor.sermon_salvation_rollout_inventory import (
    _database_snapshot,
    _file_signature,
    _inspect_video,
    build_rollout_inventory,
    reusable_inventory,
    write_rollout_inventory,
)
from pastor_transcript_extractor.sermon_topic_stage4 import _canonical_hash
from pastor_transcript_extractor.sermon_topics import TOPIC_PACK_VERSION


def decision():
    identity = {
        "policy_version": "salvation-nine-leaf-stage-gate-v1",
        "salvation_relationship_questions": "ready_for_broader_analysis",
        "observation_policy_version": SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
        "approved_relationships": list(SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS),
        "excluded_unresolved_relationships": sorted(UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS),
    }
    return {**identity, "input_fingerprint": _canonical_hash(identity)}


class RolloutInventoryTest(unittest.TestCase):
    def test_coverage_and_bounded_missing_work(self):
        records = [
            {"video_id": 1, "status": "ready_cached_leaf_artifact", "profile_gate_eligible": True,
             "profile_gate_reason_codes": []},
            {"video_id": 2, "status": "ready_zero_routed_blocks", "profile_gate_eligible": False,
             "profile_gate_reason_codes": ["effective_profile_membership_unavailable"]},
            {"video_id": 3, "status": "missing_leaf_artifact", "profile_gate_eligible": True,
             "profile_gate_reason_codes": [],
             "missing_routed_block_count": 7, "missing_target_text_chars": 300},
            {"video_id": 4, "status": "upstream_content_gate_blocked", "profile_gate_eligible": False,
             "profile_gate_reason_codes": ["effective_profile_membership_unavailable"],
             "content_gate_reason_codes": ["topic_analysis_unavailable"]},
        ]
        report = build_rollout_inventory(records, total_videos=5,
                                         production_ineligible_count=1,
                                         decision=decision(), snapshot={}, source_files=[])
        self.assertEqual(report["counts"]["nine_leaf_ready"], 2)
        self.assertEqual(report["counts"]["content_gate_eligible"], 3)
        self.assertEqual(report["counts"]["profile_gate_eligible"], 2)
        self.assertEqual(report["work_estimate"]["missing_routed_block_count"], 7)
        self.assertEqual(report["work_estimate"]["provider_requests_if_all_packs_miss_before_token_splitting"], 2)
        self.assertEqual(report["work_estimate"]["structural_provider_request_range_including_unknown_pack_cache"], [0, 12])
        self.assertEqual(report["provider_requests"], 0)

    def test_report_cache_invalidates_on_source_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = root / "app.db"
            source = root / "proposed.json"
            db.write_text("db")
            source.write_text("first")
            now = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
            report = build_rollout_inventory([], total_videos=0,
                                             production_ineligible_count=0,
                                             decision=decision(),
                                             snapshot=_database_snapshot(db, now),
                                             source_files=[_file_signature(source)])
            path = root / "inventory.json"
            write_rollout_inventory(path, report)
            self.assertIsNotNone(reusable_inventory(path, db, decision(), now))
            source.write_text("second and changed")
            self.assertIsNone(reusable_inventory(path, db, decision(), now))

    def test_unapproved_decision_rejected(self):
        unapproved = decision()
        unapproved["salvation_relationship_questions"] = "pending"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            build_rollout_inventory([], total_videos=0,
                                    production_ineligible_count=0,
                                    decision=unapproved, snapshot={}, source_files=[])

    def test_profile_linkage_does_not_block_question_level_zero_route(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "proposed.json"
            source.write_text("{}")
            topic = {"blocks": []}
            gate = SimpleNamespace(
                eligible=False,
                reason_codes=("effective_profile_membership_unavailable",),
                input_fingerprint="gate", profile_id=None,
                source_path=str(source), topic_analysis_fingerprint=_canonical_hash(topic),
                topic_question_pack_version=TOPIC_PACK_VERSION,
            )
            video = SimpleNamespace(id=8, youtube_video_id="youtube", title="Sermon",
                                    source_id=2, pastor_id=None)
            with (patch("pastor_transcript_extractor.sermon_salvation_rollout_inventory.assess_topic_profile_projection", return_value=gate),
                  patch("pastor_transcript_extractor.sermon_salvation_rollout_inventory.read_classification_for_gate", return_value={}),
                  patch("pastor_transcript_extractor.sermon_salvation_rollout_inventory.resolve_topic_analysis_artifact", return_value=topic)):
                row = _inspect_video(SimpleNamespace(), video)
            self.assertEqual(row["status"], "ready_zero_routed_blocks")
            self.assertTrue(row["content_gate_eligible"])
            self.assertFalse(row["profile_gate_eligible"])


if __name__ == "__main__":
    unittest.main()
