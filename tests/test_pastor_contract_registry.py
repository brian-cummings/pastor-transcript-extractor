"""Focused rejection tests for the review-only contract registry's safety gates."""
from copy import deepcopy
from pathlib import Path
import runpy
import unittest

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "docs/review-proposals/pastor-contracts-v1/build_registry.py"))
build_registry = MODULE["build_registry"]
validate_registry = MODULE["validate_registry"]


class PastorContractRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = build_registry()

    def proposal(self):
        result = deepcopy(self.registry)
        result.pop("content_fingerprint")
        return result

    def test_omitted_or_duplicate_leaf_rejected(self):
        for operation in (lambda rows: rows.pop(), lambda rows: rows.append(deepcopy(rows[0]))):
            with self.subTest(operation=operation):
                registry = self.proposal()
                operation(registry["records"])
                with self.assertRaisesRegex(ValueError, "exactly the canonical inventory"):
                    validate_registry(registry)

    def test_question_rewording_and_threshold_drift_rejected(self):
        registry = self.proposal()
        record = next(r for r in registry["records"] if r["contract_id"] == "S:faith_as_receiving_response")
        record["collection"]["canonical_question"]["instructions"]["task"] = "Infer the pastor's overall theology"
        # Even a locally recomputed digest cannot legitimize noncanonical question semantics.
        record["collection"]["question_digest"] = MODULE["digest"](record["collection"]["canonical_question"])
        with self.assertRaisesRegex(ValueError, "canonical question drift"):
            validate_registry(registry)
        registry = self.proposal()
        record = next(r for r in registry["records"] if r["contract_id"] == "S:faith_as_receiving_response")
        record["collection"]["observation_decision"]["threshold"] = .70
        with self.assertRaisesRegex(ValueError, "threshold drift"):
            validate_registry(registry)

    def test_unresolved_cannot_be_zero_or_positive(self):
        for field in ("numerator", "threshold", "statement"):
            with self.subTest(field=field):
                registry = self.proposal()
                r = next(r for r in registry["records"] if r["contract_id"] == "S:obedience_as_condition_or_means")
                if field == "numerator":
                    r["projection"]["numerator"] = 0
                elif field == "threshold":
                    r["collection"]["observation_decision"]["threshold"] = .5
                else:
                    r["downstream_statement"]["observed_statement"] = "The pastor rejects works"
                with self.assertRaisesRegex(ValueError, "Unresolved detector"):
                    validate_registry(registry)

    def test_premature_activation_or_comparison_rejected(self):
        registry = self.proposal()
        registry["broader_collection_authorized"] = True
        with self.assertRaisesRegex(ValueError, "cannot activate collection"):
            validate_registry(registry)
        registry = self.proposal()
        registry["records"][0]["downstream_statement"]["allowed_uses"]["clustering"] = "allowed"
        with self.assertRaisesRegex(ValueError, "remain gated"):
            validate_registry(registry)

    def test_missing_denominator_and_unknown_policy_rejected(self):
        registry = self.proposal()
        registry["records"][0]["projection"]["denominator"] = ""
        with self.assertRaisesRegex(ValueError, "Missing projection denominator"):
            validate_registry(registry)
        registry = self.proposal()
        registry["records"][0]["projection"]["shared_policy"] = "invented"
        with self.assertRaisesRegex(ValueError, "Unknown shared policy"):
            validate_registry(registry)

    def test_unsigned_artifact_modification_rejected(self):
        registry = deepcopy(self.registry)
        registry["records"][0]["downstream_statement"]["subject"] = "changed without fingerprint update"
        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            validate_registry(registry)


if __name__ == "__main__":
    unittest.main()
