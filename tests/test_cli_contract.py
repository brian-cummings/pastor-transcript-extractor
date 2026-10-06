from __future__ import annotations

from importlib.metadata import distribution
import unittest

from typer.core import TyperGroup
from typer.main import get_command
from typer.testing import CliRunner

from pastor_transcript_extractor.__main__ import main as package_main
from pastor_transcript_extractor.cli import app, main


ROOT_COMMANDS = {
    "add",
    "apply-fixture-correction",
    "diagnose",
    "diagnose-compare",
    "diagnose-interaction",
    "diagnose-recording-verifier",
    "diagnose-system",
    "discover",
    "doctor",
    "evaluate",
    "extract",
    "fetch",
    "import-church-db",
    "init",
    "migrate-evaluation-storage",
    "reclassify",
    "review",
    "review-ground-truth",
    "review-next-ground-truth",
    "run",
    "status",
    "source-processing-report",
    "sync-imported-sources",
    "sync-source-families",
    "transcribe",
    "validate-baseline",
    "validate-fixtures",
    "validate-source-families",
}

GROUP_COMMANDS = {
    "analysis": {
        "backfill",
        "evaluate-scripture-alignment",
        "evaluate-scripture-detector",
        "evaluate-style",
        "evaluate-style-boundaries",
        "evaluate-topic-behavior",
        "population-build",
        "population-show",
        "refresh-profiles",
        "run",
        "show",
        "show-profile",
        "status",
        "structure-backfill",
        "structure-population-build",
        "structure-population-show",
        "structure-readiness",
        "structure-run",
        "structure-show",
        "style-review-create",
        "style-review-finalize",
        "style-run",
        "style-show",
        "style-show-profile",
        "style-summarize-profile",
        "summarize-profile",
        "topic-review",
        "topic-review-draft",
        "topic-review-finalize",
    },
    "benchmark": {
        "add-profile",
        "build",
        "recording-verifier-typesafe",
        "compare",
        "create",
        "list",
        "remove-profile",
        "show",
        "show-snapshot",
    },
    "identity": {
        "association-audit",
        "association-work-plan",
        "association-work-status",
        "audit-speaker-negative-windows",
        "audit-speaker-review-selection",
        "backfill",
        "compare-speakers",
        "confirm-discovered-profiles",
        "consolidate-source-profiles",
        "coordinate",
        "detach-speaker-observation",
        "dispatch-associations",
        "enrich-metadata",
        "evaluate-observation-consistency",
        "evaluate-pair-results",
        "evaluate-profile-promotions",
        "evaluate-speaker-policy-candidate",
        "export-profile",
        "machine-assignment-status",
        "prepare-actionable-review-audio",
        "prepare-speaker-review-audio",
        "profile-leverage-snapshot",
        "profile-status",
        "promote-discovered-profiles",
        "reconcile-current-proposals",
        "record-speaker-difference",
        "repair-association-prerequisites",
        "review-next-speaker-negative-window",
        "review-next-speaker-pair",
        "review-next-superseded-profile-member",
        "review-observation",
        "review-profile-attribution",
        "review-speaker-pair",
        "rollback-machine-assignments",
        "run",
        "run-speaker-model-bakeoff",
        "shadow-associate-speakers",
        "shadow-association-status",
        "shadow-discover-profiles",
        "sync-reviewed-speaker-evidence",
        "validate-pair-fixtures",
        "analyze-profile-metadata",
    },
    "media": {
        "archive-normalized",
        "archive-sources",
        "archive-status",
        "audit",
        "audit-normalized-provenance",
        "backfill",
        "ensure-audio",
        "prepare-canonical-audio",
        "repair-normalized-provenance",
        "sweep-audio",
    },
    "organization": {
        "add",
        "claims",
        "list",
        "reject-affiliation-claim",
        "review",
    },
    "pastor": {"add", "affiliate", "affiliate-claim", "list"},
    "source": {
        "add",
        "clear-organization",
        "delete",
        "disable",
        "enable",
        "list",
        "set-organization",
    },
    "source-ownership": {"audit", "migrate"},
    "storage": {"compact", "restore", "verify"},
    "video": {"exclude", "excluded", "list", "unexclude"},
}


class CliContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.root = get_command(app)

    def test_root_command_and_group_names_are_stable(self) -> None:
        self.assertEqual(
            ROOT_COMMANDS | set(GROUP_COMMANDS),
            set(self.root.commands),
        )

    def test_every_command_group_has_the_expected_commands(self) -> None:
        for group_name, expected_commands in GROUP_COMMANDS.items():
            with self.subTest(group=group_name):
                group = self.root.commands[group_name]
                self.assertIsInstance(group, TyperGroup)
                self.assertEqual(expected_commands, set(group.commands))

    def test_root_help_describes_the_app_and_representative_commands(self) -> None:
        result = self.runner.invoke(app, ["--help"])

        self.assertEqual(0, result.exit_code, msg=result.output)
        self.assertIn("Pastor Transcript Extractor CLI", result.output)
        self.assertIn("validate-fixtures", result.output)
        self.assertIn("identity", result.output)
        self.assertIn("benchmark", result.output)

    def test_group_help_preserves_command_scope_and_descriptions(self) -> None:
        result = self.runner.invoke(app, ["benchmark", "--help"])

        self.assertEqual(0, result.exit_code, msg=result.output)
        self.assertIn("Manage reviewed profile reference panels.", result.output)
        self.assertIn("create", result.output)
        self.assertIn("show-snapshot", result.output)
        self.assertIn("compare", result.output)

    def test_representative_validation_failure_remains_a_usage_error(self) -> None:
        result = self.runner.invoke(app, ["identity", "shadow-associate-speakers"])

        self.assertEqual(2, result.exit_code, msg=result.output)
        self.assertIn(
            "Pass exactly one of --youtube-video-id, --all-eligible, or",
            result.output,
        )
        self.assertIn("--neighborhood-profile-id", result.output)

    def test_source_profile_consolidation_exposes_all_eligible_mode(self) -> None:
        help_result = self.runner.invoke(
            app, ["identity", "consolidate-source-profiles", "--help"]
        )
        self.assertEqual(0, help_result.exit_code, msg=help_result.output)
        self.assertIn("--all-eligible", help_result.output)

        conflict_result = self.runner.invoke(
            app,
            [
                "identity",
                "consolidate-source-profiles",
                "--source-id",
                "1",
                "--all-eligible",
            ],
        )
        self.assertEqual(2, conflict_result.exit_code, msg=conflict_result.output)
        self.assertIn(
            "Pass exactly one of --source-id, --list-sources, or",
            conflict_result.output,
        )
        self.assertIn("--all-eligible", conflict_result.output)

    def test_topic_review_draft_exposes_fingerprint_bound_proposals(self) -> None:
        result = self.runner.invoke(
            app, ["analysis", "topic-review-draft", "--help"]
        )

        self.assertEqual(0, result.exit_code, msg=result.output)
        self.assertIn("--proposal", result.output)
        self.assertIn("fingerprint-bound", result.output)

    def test_package_and_installed_entry_points_resolve_the_cli(self) -> None:
        self.assertIs(package_main, main)
        entry_points = {
            entry_point.name: entry_point.value
            for entry_point in distribution(
                "pastor-transcript-extractor"
            ).entry_points
            if entry_point.group == "console_scripts"
        }
        self.assertEqual("pastor_transcript_extractor.cli:app", entry_points["pte"])


if __name__ == "__main__":
    unittest.main()
