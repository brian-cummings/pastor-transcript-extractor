from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.observed_profile import consume, load_packet
from pastor_transcript_extractor.observed_profile_review import acceptance, build_review, render_html


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.targets = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "a" and values.get("href", "").startswith("#"):
            self.targets.append(values["href"][1:])


class ObservedProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = load_packet()
        cls.review = build_review(cls.packet)

    def case(self, cid):
        return deepcopy(next(c for c in self.packet["cases"] if c["case_id"] == cid))

    def view(self, case):
        return consume(case["evidence"], self.packet["field_contracts"], self.packet["estimands"])

    def field(self, cid, field):
        return next(f for f in self.view(self.case(cid))["fields"] if f["characteristic_id"] == field)

    def test_all_cases_exercised_and_oracle_differences_are_not_hidden(self):
        self.assertEqual(17, self.review["invariant_passes"])
        self.assertEqual(15, self.review["exact_oracle_matches"])
        differences = {c["case_id"]: c["acceptance"]["oracle_differences"] for c in self.review["cases"] if not c["acceptance"]["frozen_oracle_match"]}
        self.assertEqual({"A12", "A15"}, set(differences))
        self.assertEqual(["frozen:G2-01"], self.field("A15", "C10")["supporting"])

    def test_consumer_cannot_read_expected_wording_or_case_identity(self):
        case = self.case("A05")
        baseline = self.view(case)
        case["expected"] = {"fields": "Pretend this is a complete empathetic pastor profile"}
        case["case_id"] = "unseen-case"
        self.assertEqual(baseline, self.view(case))

    def test_useful_local_leaves_with_missing_richer_fields(self):
        self.assertEqual("local_examples", self.field("A01", "C01")["availability"])
        self.assertEqual("local_examples", self.field("A01", "C05")["availability"])
        for cid in ("C03", "C06", "C12"):
            f = self.field("A01", cid)
            self.assertEqual("not_collected", f["availability"])
            self.assertFalse(f["supporting"])
            self.assertTrue(f["missing_information"])

    def test_partial_address_keeps_known_acts_without_binding_promotion(self):
        view = self.view(self.case("A05"))
        e = view["evidence"][0]
        self.assertEqual("observed", e["payload"]["acts"]["concrete_care"])
        self.assertEqual("unclear", e["payload"]["recipient_binding"])
        self.assertEqual("judgment_withheld", self.field("A05", "C12")["availability"])
        self.assertEqual("local_examples", self.field("A08", "C12")["availability"])
        self.assertIsNone(view["independently_eligible_sermons"])

    def test_prayer_report_context_and_negatives_retain_distinct_decisions(self):
        for case in ("A04", "A07"):
            self.assertFalse(self.field(case, "C12")["supporting"])
        f = self.field("A10", "C12")
        self.assertEqual(["context:resolved"], f["supporting"])
        self.assertEqual(["context:only"], f["counter"])
        self.assertEqual("negative_in_unit", self.field("A17", "C12")["availability"])
        self.assertEqual("boundary_incomplete", self.field("A16", "C12")["availability"])
        self.assertEqual("measurement_unresolved", self.field("A16", "C02")["availability"])

    def test_no_promotion_of_excluded_incompatible_or_withheld_evidence(self):
        for cid, expected in (("C01", "excluded"), ("C10", "incompatible"), ("C05", "excluded")):
            f = self.field("A12", cid)
            self.assertEqual(expected, f["availability"])
            self.assertFalse(f["supporting"])
        case = self.case("A01")
        case["evidence"][0]["observation_state"] = "judgment_withheld"
        f = self.view(case)["fields"][0]
        self.assertEqual("judgment_withheld", f["availability"])
        self.assertFalse(f["supporting"])

    def test_duplicates_do_not_inflate_example_groups_or_hide_aliases(self):
        v = self.view(self.case("A11"))
        self.assertEqual(4, len(v["retained_evidence"]))
        self.assertEqual(2, v["unique_utterance_groups"])
        self.assertIsNone(v["independently_eligible_sermons"])
        self.assertEqual(3, max(len(aliases) for aliases in v["utterance_groups"].values()))

    def test_held_outputs_never_activated_and_bad_link_promotion_is_detected(self):
        case = self.case("A15")
        v = self.view(case)
        for f in v["fields"]:
            for key in ("population_rate", "recurring_characterization", "comparison", "quality_score"):
                self.assertIsNone(f[key])
        next(f for f in v["fields"] if f["characteristic_id"] == "C10")["supporting"].append("other:topic")
        self.assertEqual("FAIL", acceptance(case, v)["invariant_status"])

    def test_ungrounded_context_endpoint_is_rejected(self):
        case = self.case("A02")
        e = case["evidence"][0]
        e["source"]["leading_context"] = e["spans"][0]["text"]
        e["spans"][0]["role"] = "leading_context"
        with self.assertRaisesRegex(ValueError, "endpoints must be target"):
            self.view(case)

    def test_html_preserves_unique_evidence_targets_and_escapes_source_text(self):
        report = deepcopy(self.review)
        report["cases"][0]["view"]["evidence"][0]["source"]["target_text"] = '<script>alert("source")</script>'
        html = render_html(report, Path("/tmp/observed-profile-tests"))
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('<script>alert("source")</script>', html)
        page = Page()
        page.feed(html)
        self.assertEqual(len(page.ids), len(set(page.ids)))
        self.assertTrue(set(page.targets) <= set(page.ids))
        self.assertIn("All 20 desired fields", html)
        self.assertIn("Still missing or unestablished", html)

    def test_cli_checks_without_writes_and_writes_readable_reports(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "review"
            result = runner.invoke(app, ["analysis", "observed-profile-review", "--output-dir", str(target), "--check-only"])
            self.assertEqual(0, result.exit_code, result.output)
            self.assertFalse(target.exists())
            self.assertIn("15/17", result.output)
            result = runner.invoke(app, ["analysis", "observed-profile-review", "--case", "A05", "--output-dir", str(target)])
            self.assertEqual(0, result.exit_code, result.output)
            self.assertIn("recipient binding", result.output.lower())
            self.assertTrue((target / "observed-profiles.html").is_file())
            self.assertTrue((target / "consumer-results.json").is_file())
            invalid = runner.invoke(app, ["analysis", "observed-profile-review", "--case", "unknown", "--output-dir", str(target / "invalid")])
            self.assertNotEqual(0, invalid.exit_code)
            self.assertFalse((target / "invalid").exists())


if __name__ == "__main__":
    unittest.main()
