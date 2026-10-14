"""Grounding/link/hold checks for design fixtures; not semantic validation."""
from copy import deepcopy
from pathlib import Path
import runpy
import unittest

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "docs/review-proposals/g2-g3-v1/build_cases.py"))


class G2G3ContractCasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = MODULE["build_packet"]()

    def unsigned(self):
        packet = deepcopy(self.packet)
        packet.pop("content_fingerprint")
        return packet

    def test_dangling_relation_endpoint_rejected(self):
        packet = self.unsigned()
        packet["cases"][0]["relations"][0]["to_node_id"] = "missing-node"
        with self.assertRaisesRegex(ValueError, "endpoints"):
            MODULE["validate"](packet)

    def test_context_only_relation_evidence_rejected(self):
        packet = self.unsigned()
        c = packet["cases"][0]
        c["leading_context"] = c["target_text"]
        c["source_fingerprint"] = MODULE["digest"]({k: c[k] for k in ("target_text", "leading_context", "trailing_context")})
        c["relations"][0]["evidence_span"]["source_field"] = "leading_context"
        with self.assertRaisesRegex(ValueError, "target-grounded"):
            MODULE["validate"](packet)

    def test_certified_operation_quality_rejected(self):
        packet = self.unsigned()
        packet["cases"][0]["operations"][0]["correctness"] = "faithful"
        with self.assertRaisesRegex(ValueError, "correctness invalid"):
            MODULE["validate"](packet)

    def test_empathy_and_listener_effect_rejected(self):
        for field in ("inner_empathy", "listener_effect"):
            packet = self.unsigned()
            c = next(c for c in packet["cases"] if c["case_id"] == "G3-01")
            c["address_acts"][0][field] = "positive"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "cannot certify"):
                MODULE["validate"](packet)

    def test_misbound_address_role_rejected(self):
        packet = self.unsigned()
        c = next(c for c in packet["cases"] if c["case_id"] == "G3-01")
        c["address_acts"][0]["circumstance_node_id"] = c["address_acts"][0]["utterance_node_id"]
        with self.assertRaisesRegex(ValueError, "Misbound address"):
            MODULE["validate"](packet)

    def test_implementation_and_g4_holds_rejected(self):
        for field, value in (("g1_implementation_authorized", True), ("broad_g1_expansion_authorized", True),
                             ("g4_status", "active"), ("implementation_priority", "G1")):
            packet = self.unsigned()
            packet[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "hold changed"):
                MODULE["validate"](packet)


if __name__ == "__main__":
    unittest.main()
