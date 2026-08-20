from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.benchmark import (
    COMPARISON_FEATURE_NAMES,
    EligibilityPolicy,
    build_snapshot,
    create_panel,
    effective_membership,
    record_membership,
    snapshot_document,
)
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.profile_analysis import (
    PROFILE_ANALYZER_KEY,
    PROFILE_ANALYZER_VERSION,
    PROFILE_FEATURE_ORDER,
)
from pastor_transcript_extractor.storage import Database


class ReferencePanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tempdir.name)
        paths = build_paths(self.base_dir)
        ensure_directories(paths)
        self.database = Database(paths.database)
        self.database.initialize()
        self.panel, _ = create_panel(
            self.database,
            key="prominent-pastors-v1",
            name="Prominent pastors",
            description="Reviewed comparison anchors",
        )
        self.lenient = EligibilityPolicy(
            minimum_analyzed_sermons=1,
            minimum_total_sermon_words=1,
            minimum_analysis_coverage=0.0,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _profile(self, key: str, label: str | None = None):
        return self.database.ensure_speaker_profile(
            stable_key=f"person:{key}",
            display_label=label or key.title(),
            lifecycle_state="active",
            created_reason="reviewed test profile",
        )

    def _analysis(self, profile_id: int, fingerprint: str, *, missing: str | None = None):
        by_name = {
            name: (None if name == missing else float(index + 1))
            for index, name in enumerate(PROFILE_FEATURE_ORDER)
        }
        measurements = {
            "sermons_attached": 4,
            "sermons_analyzed": 4,
            "sermons_missing_analysis": 0,
            "total_sermon_words": 20_000,
            "structural_coverage_diagnostics": {"sermons_analyzed": 4},
            "deterministic_profile_feature_vector": {
                "schema_version": 2,
                "feature_names": list(PROFILE_FEATURE_ORDER),
                "values": [by_name[name] for name in PROFILE_FEATURE_ORDER],
                "by_name": by_name,
            },
        }
        run, created = self.database.add_speaker_profile_analysis_run(
            profile_id=profile_id,
            analyzer_key=PROFILE_ANALYZER_KEY,
            analyzer_version=PROFILE_ANALYZER_VERSION,
            membership_fingerprint=f"membership-{fingerprint}",
            input_fingerprint=fingerprint,
            inputs=[],
            measurements=[
                (key, json.dumps(value, sort_keys=True), None)
                for key, value in measurements.items()
            ],
        )
        self.assertTrue(created)
        return run

    def _attach(self, profile_id: int, reason: str = "selected"):
        return record_membership(
            self.database,
            panel_key=self.panel.key,
            profile_id=profile_id,
            action="attach",
            reviewer="Brian",
            rationale=reason,
        )

    def test_panel_creation_and_duplicate_events_are_idempotent(self) -> None:
        reused, created = create_panel(
            self.database,
            key=self.panel.key,
            name=self.panel.display_name,
            description=self.panel.description,
        )
        profile = self._profile("one")
        first = self._attach(profile.id)
        duplicate = self._attach(profile.id)

        self.assertFalse(created)
        self.assertEqual(self.panel.id, reused.id)
        self.assertTrue(first.created)
        self.assertFalse(duplicate.created)
        self.assertEqual(first.event.id, duplicate.event.id)

    def test_append_only_attach_and_detach_control_effective_membership(self) -> None:
        profile = self._profile("one")
        self._attach(profile.id)
        detached = record_membership(
            self.database,
            panel_key=self.panel.key,
            profile_id=profile.id,
            action="detach",
            reviewer="Brian",
            rationale="removed",
        )
        self.assertTrue(detached.created)
        self.assertEqual([], effective_membership(self.database, self.panel))
        with self.database.connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM reference_panel_membership_events"
            ).fetchone()[0]
        self.assertEqual(2, count)

    def test_redirects_are_resolved_and_labels_are_frozen(self) -> None:
        old = self._profile("old", "Old Label")
        canonical = self._profile("canonical", "Shane Anderson")
        self.database.add_profile_redirect_event(
            from_profile_id=old.id,
            to_profile_id=canonical.id,
            action="redirect",
            reviewer="Brian",
            reason="same reviewed speaker",
            event_fingerprint="redirect-old-canonical",
        )
        self._attach(old.id)
        run = self._analysis(canonical.id, "canonical-run")

        outcome = build_snapshot(self.database, self.panel.key, policy=self.lenient)
        member = self.database.list_reference_panel_snapshot_members(outcome.snapshot.id)[0]
        self.assertEqual([old.id], json.loads(member.requested_profile_ids_json))
        self.assertEqual(canonical.id, member.resolved_profile_id)
        self.assertEqual("Shane Anderson", member.resolved_display_label)
        self.assertEqual(run.id, member.profile_analysis_run_id)

    def test_snapshot_reuse_and_changes_to_membership_or_runs(self) -> None:
        first_profile = self._profile("one")
        self._attach(first_profile.id)
        self._analysis(first_profile.id, "run-one")
        first = build_snapshot(self.database, self.panel.key, policy=self.lenient)
        reused = build_snapshot(self.database, self.panel.key, policy=self.lenient)
        self.assertTrue(first.created)
        self.assertFalse(reused.created)
        self.assertEqual(first.snapshot.id, reused.snapshot.id)

        second_profile = self._profile("two")
        self._attach(second_profile.id, "second selected")
        self._analysis(second_profile.id, "run-two")
        membership_changed = build_snapshot(
            self.database, self.panel.key, policy=self.lenient
        )
        self.assertNotEqual(first.snapshot.id, membership_changed.snapshot.id)

        self._analysis(first_profile.id, "run-one-new")
        analysis_changed = build_snapshot(
            self.database, self.panel.key, policy=self.lenient
        )
        self.assertNotEqual(membership_changed.snapshot.id, analysis_changed.snapshot.id)

    def test_diagnostics_missingness_matrix_and_feature_statistics(self) -> None:
        eligible = self._profile("eligible", "Eligible Reference")
        missing_feature = self._profile("missing-feature")
        missing_analysis = self._profile("missing-analysis")
        for profile in (eligible, missing_feature, missing_analysis):
            self._attach(profile.id, f"select {profile.id}")
        run = self._analysis(eligible.id, "eligible-run")
        self._analysis(
            missing_feature.id,
            "missing-feature-run",
            missing=COMPARISON_FEATURE_NAMES[0],
        )

        outcome = build_snapshot(self.database, self.panel.key, policy=self.lenient)
        document = snapshot_document(self.database, self.panel, outcome.snapshot)
        members = {member["resolved_profile_id"]: member for member in document["members"]}

        self.assertEqual("eligible", members[eligible.id]["eligibility_status"])
        self.assertEqual(run.id, members[eligible.id]["profile_analysis_run_id"])
        self.assertIn(
            "missing_required_comparison_features",
            members[missing_feature.id]["exclusion_reasons"],
        )
        self.assertIsNone(
            members[missing_feature.id]["comparison_values"][COMPARISON_FEATURE_NAMES[0]]
        )
        self.assertEqual(
            ["missing_analysis"], members[missing_analysis.id]["exclusion_reasons"]
        )
        self.assertEqual(list(COMPARISON_FEATURE_NAMES), document["feature_matrix"]["feature_names"])
        self.assertEqual(1, len(document["feature_matrix"]["rows"]))
        self.assertNotIn(
            "analysis_coverage_fraction", document["feature_matrix"]["feature_names"]
        )
        self.assertIn(
            "analysis_coverage_fraction",
            document["snapshot"]["feature_family_assignments"]["diagnostic_only"],
        )
        stats = document["snapshot"]["panel_feature_statistics"]["features"]
        first_stats = stats[COMPARISON_FEATURE_NAMES[0]]
        self.assertEqual(1, first_stats["eligible_count"])
        self.assertEqual(0, first_stats["missing_count"])
        self.assertEqual(first_stats["median"], first_stats["minimum"])
        self.assertEqual(0.0, first_stats["median_absolute_deviation"])

    def test_default_policy_explains_insufficient_corpus(self) -> None:
        profile = self._profile("small")
        self._attach(profile.id)
        by_name = {name: 1.0 for name in PROFILE_FEATURE_ORDER}
        by_name["analysis_coverage_fraction"] = 0.1
        run, _ = self.database.add_speaker_profile_analysis_run(
            profile_id=profile.id,
            analyzer_key=PROFILE_ANALYZER_KEY,
            analyzer_version=PROFILE_ANALYZER_VERSION,
            membership_fingerprint="small-membership",
            input_fingerprint="small-run",
            inputs=[],
            measurements=[
                ("sermons_attached", "10", None),
                ("sermons_analyzed", "1", None),
                ("sermons_missing_analysis", "9", None),
                ("total_sermon_words", "500", None),
                (
                    "deterministic_profile_feature_vector",
                    json.dumps(
                        {
                            "schema_version": 2,
                            "feature_names": list(PROFILE_FEATURE_ORDER),
                            "values": [by_name[name] for name in PROFILE_FEATURE_ORDER],
                            "by_name": by_name,
                        }
                    ),
                    None,
                ),
            ],
        )
        self.assertIsNotNone(run)
        outcome = build_snapshot(self.database, self.panel.key)
        member = self.database.list_reference_panel_snapshot_members(outcome.snapshot.id)[0]
        reasons = json.loads(member.exclusion_reasons_json)
        self.assertIn("insufficient_analyzed_sermons", reasons)
        self.assertIn("insufficient_total_sermon_words", reasons)
        self.assertIn("insufficient_analysis_coverage", reasons)

    def test_snapshot_persistence_is_atomic_on_member_failure(self) -> None:
        with self.assertRaises(Exception):
            self.database.add_reference_panel_snapshot(
                panel_id=self.panel.id,
                profile_analyzer_key=PROFILE_ANALYZER_KEY,
                profile_analyzer_version=PROFILE_ANALYZER_VERSION,
                feature_schema_version="test",
                comparison_feature_names_json="[]",
                coverage_feature_names_json="[]",
                feature_family_assignments_json="{}",
                panel_feature_statistics_json="{}",
                eligibility_policy_version="test",
                eligibility_policy_json="{}",
                snapshot_analyzer_version="test",
                input_fingerprint="atomic-failure",
                members=[
                    ("[]", "[]", 999_999, "Missing", None, "invalid", "[]", "{}", "{}")
                ],
            )
        self.assertIsNone(
            self.database.get_reference_panel_snapshot_by_fingerprint("atomic-failure")
        )

    def test_cli_create_membership_build_and_inspection(self) -> None:
        cli_base = self.base_dir / "cli"
        paths = build_paths(cli_base)
        ensure_directories(paths)
        database = Database(paths.database)
        database.initialize()
        profile = database.ensure_speaker_profile(
            stable_key="person:cli",
            display_label="CLI Reference",
            lifecycle_state="active",
            created_reason="test",
        )
        self._add_cli_analysis(database, profile.id)
        runner = CliRunner()
        create = runner.invoke(
            app,
            [
                "benchmark", "create", "--key", "cli-panel", "--name", "CLI Panel",
                "--description", "CLI test panel", "--base-dir", str(cli_base),
            ],
        )
        self.assertEqual(0, create.exit_code, create.output)
        add = runner.invoke(
            app,
            [
                "benchmark", "add-profile", "cli-panel", "--profile-id", str(profile.id),
                "--reviewer", "Brian", "--reason", "selected", "--base-dir", str(cli_base),
            ],
        )
        self.assertEqual(0, add.exit_code, add.output)
        build = runner.invoke(
            app,
            [
                "benchmark", "build", "cli-panel", "--min-analyzed-sermons", "1",
                "--min-total-words", "1", "--min-coverage", "0", "--base-dir", str(cli_base),
            ],
        )
        self.assertEqual(0, build.exit_code, build.output)
        shown = runner.invoke(
            app,
            ["benchmark", "show-snapshot", "cli-panel", "--json", "--base-dir", str(cli_base)],
        )
        self.assertEqual(0, shown.exit_code, shown.output)
        self.assertIn("CLI Reference", shown.output)
        self.assertIn("panel_feature_statistics", shown.output)

    def _add_cli_analysis(self, database: Database, profile_id: int) -> None:
        by_name = {name: float(index + 1) for index, name in enumerate(PROFILE_FEATURE_ORDER)}
        database.add_speaker_profile_analysis_run(
            profile_id=profile_id,
            analyzer_key=PROFILE_ANALYZER_KEY,
            analyzer_version=PROFILE_ANALYZER_VERSION,
            membership_fingerprint="cli-membership",
            input_fingerprint="cli-run",
            inputs=[],
            measurements=[
                ("sermons_attached", "2", None),
                ("sermons_analyzed", "2", None),
                ("sermons_missing_analysis", "0", None),
                ("total_sermon_words", "20000", None),
                (
                    "deterministic_profile_feature_vector",
                    json.dumps(
                        {
                            "schema_version": 2,
                            "feature_names": list(PROFILE_FEATURE_ORDER),
                            "values": [by_name[name] for name in PROFILE_FEATURE_ORDER],
                            "by_name": by_name,
                        }
                    ),
                    None,
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
