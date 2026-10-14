"""Source grounding and bounded-scope invariants, not semantic/model evaluation."""
from copy import deepcopy
from pathlib import Path
import runpy
import unittest

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "docs/review-proposals/g1-binding-v1/build_cases.py"))


class G1BindingContractCasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = MODULE["build_packet"]()

    def unsigned(self):
        packet = deepcopy(self.packet)
        packet.pop("content_fingerprint")
        return packet

    def test_invalid_source_slice_rejected(self):
        packet = self.unsigned()
        packet["cases"][0]["expected_claims"][0]["claim_span"]["start"] += 1
        with self.assertRaisesRegex(ValueError, "Invalid grounded span"):
            MODULE["validate"](packet)

    def test_context_only_assertion_rejected(self):
        packet = self.unsigned()
        c = packet["cases"][0]
        c["leading_context"] = c["target_text"]
        c["source_fingerprint"] = MODULE["digest"]({k: c[k] for k in ("target_text", "leading_context", "trailing_context")})
        c["expected_claims"][0]["claim_span"]["source_field"] = "leading_context"
        with self.assertRaisesRegex(ValueError, "evidenced in target"):
            MODULE["validate"](packet)

    def test_unproved_uncertainty_rejected(self):
        packet = self.unsigned()
        packet["cases"][0]["expected_claims"][0]["epistemic_status"] = "expressed_uncertainty"
        with self.assertRaisesRegex(ValueError, "needs evidence"):
            MODULE["validate"](packet)

    def test_expansion_and_extra_relation_rejected(self):
        packet = self.unsigned()
        packet["broad_g1_expansion_authorized"] = True
        with self.assertRaisesRegex(ValueError, "guardrail"):
            MODULE["validate"](packet)
        packet = self.unsigned()
        packet["cases"][0]["expected_claims"][0]["relation"] = "predestination"
        with self.assertRaisesRegex(ValueError, "Out-of-scope"):
            MODULE["validate"](packet)

    def test_g2_g3_design_prerequisites_cannot_be_removed(self):
        packet = self.unsigned()
        packet["required_before_expansion"] = []
        with self.assertRaisesRegex(ValueError, "guardrail"):
            MODULE["validate"](packet)


if __name__ == "__main__":
    unittest.main()
