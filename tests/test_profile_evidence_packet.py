"""Focused negative controls for the review-only shared evidence packet."""
from copy import deepcopy
from pathlib import Path
import runpy
import sys
import unittest

HERE = Path(__file__).resolve().parents[1] / "docs/review-proposals/profile-evidence-v1"
sys.path.insert(0, str(HERE))
try:
    MODULE = runpy.run_path(str(HERE / "check_packet.py"))
finally:
    sys.path.pop(0)


class ProfileEvidencePacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = MODULE["check"]()

    def packet_case(self, cid):
        p = deepcopy(self.packet)
        return p, next(c for c in p["cases"] if c["case_id"] == cid)

    def test_frozen_withholding_cannot_be_promoted(self):
        p, c = self.packet_case("A05")
        c["evidence"][0]["payload"]["recipient_binding"] = "bound_in_target"
        with self.assertRaisesRegex(ValueError, "frozen G3 decision drift"):
            MODULE["validate"](p)

    def test_prayer_cannot_become_listener_address(self):
        p, c = self.packet_case("A04")
        c["evidence"][0]["payload"]["addressee"] = "direct_current_listener"
        with self.assertRaisesRegex(ValueError, "frozen G3 decision drift"):
            MODULE["validate"](p)

    def test_population_rate_and_quality_outputs_rejected(self):
        for key in ["population_rate", "recurring_characterization", "comparison", "quality_score"]:
            with self.subTest(key=key):
                p, c = self.packet_case("A13")
                c["expected"]["fields"][0][key] = 1.0
                with self.assertRaises(ValueError):
                    MODULE["validate"](p)

    def test_unknown_pilot_membership_cannot_certify_a_sermon(self):
        p, c = self.packet_case("A09")
        c["evidence"][0]["eligibility"]["membership"] = "reviewed_member"
        with self.assertRaisesRegex(ValueError, "pilot cannot certify"):
            MODULE["validate"](p)

    def test_duplicates_cannot_inflate_independent_examples(self):
        p, c = self.packet_case("A11")
        c["expected"]["unique_utterance_groups"] = 4
        with self.assertRaisesRegex(ValueError, "duplicate/overlap inflation"):
            MODULE["validate"](p)

    def test_incompatible_and_incomplete_evidence_cannot_be_credited(self):
        for cid, index in [("A12", 1), ("A16", 0)]:
            p, c = self.packet_case(cid)
            f = c["expected"]["fields"][index]
            f["supporting"] = f["unresolved"][:]
            f["unresolved"] = []
            f["availability"] = "local_examples"
            f["claim_level"] = "local_example"
            with self.subTest(case=cid), self.assertRaisesRegex(ValueError, "incompatible evidence credited|incomplete local evidence credited"):
                MODULE["validate"](p)

    def test_context_cannot_supply_target_relation_endpoint(self):
        p, c = self.packet_case("A02")
        c["evidence"][0]["source"]["leading_context"] = c["evidence"][0]["spans"][0]["text"]
        c["evidence"][0]["spans"][0]["role"] = "leading_context"
        with self.assertRaisesRegex(ValueError, "context cannot supply relation endpoint"):
            MODULE["validate"](p)

    def test_missingness_cannot_be_serialized_as_zero(self):
        p, c = self.packet_case("A16")
        c["expected"]["fields"][1]["availability"] = 0
        with self.assertRaises(ValueError):
            MODULE["validate"](p)

    def test_incomplete_observation_cannot_become_a_local_negative(self):
        p, c = self.packet_case("A16")
        f = c["expected"]["fields"][0]
        f["availability"] = "negative_in_unit"
        f["counter"] = f["unresolved"][:]
        f["unresolved"] = []
        f["claim_level"] = "local_example"
        with self.assertRaisesRegex(ValueError, "local negative cannot use unknown or incomplete evidence"):
            MODULE["validate"](p)

    def test_source_and_reference_corruption_rejected(self):
        p, c = self.packet_case("A01")
        p["sources"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "frozen source hash mismatch"):
            MODULE["validate"](p)
        p, c = self.packet_case("A01")
        c["expected"]["fields"][0]["supporting"] = ["nonexistent"]
        with self.assertRaisesRegex(ValueError, "dangling field evidence link"):
            MODULE["validate"](p)


if __name__ == "__main__":
    unittest.main()
