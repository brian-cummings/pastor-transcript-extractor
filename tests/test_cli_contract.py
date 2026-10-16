from __future__ import annotations

from importlib.metadata import distribution
import unittest
from unittest.mock import ANY, patch

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
    "docs",
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
        "evidence-supply-review",
        "evidence-supply-collector-design",
        "evidence-supply-boundary-validation",
        "evidence-supply-boundary-audit",
        "evidence-supply-boundary-repair-proposal",
        "evidence-supply-boundary-revalidation",
        "evidence-supply-boundary-v4-audit",
        "g3-atomic-admission-review",
        "g3-atomic-admission-replay",
        "fresh-discovery-readiness",
        "collector-recall-repair",
        "evidence-supply-source-audit",
        "g1-feasibility-review",
        "g2-feasibility-review",
        "g3-feasibility-review",
        "profile-evidence-check",
        "observed-profile-review",
        "public-life-routing-review",
        "source-material-stage-gate",
        "listener-directives-review",
        "public-life-treatment-review",
        "source-material-review",
        "backfill",
        "evaluate-scripture-alignment",
        "evaluate-scripture-detector",
        "evaluate-style",
        "evaluate-style-boundaries",
        "evaluate-topic-behavior",
        "evaluate-topic-stability",
        "population-build",
        "population-show",
        "refresh-profiles",
        "run",
        "salvation-collection-recalibration",
        "salvation-boundary-recalibration",
        "salvation-candidate-discovery-audit",
        "salvation-exact-cohort-proposal",
        "salvation-nine-leaf-convergence",
        "salvation-pastor-uncertainty",
        "salvation-broader-rollout-inventory",
        "salvation-analytical-backfill-plan",
        "salvation-condition-boundary-review",
        "salvation-consequence-boundary-review",
        "salvation-final-calibration",
        "salvation-final-boundary-calibration",
        "salvation-final-collection-check",
        "salvation-semantic-calibration",
        "salvation-v5-calibration",
        "salvation-v5-threshold-review",
        "salvation-v6-repentance-calibration",
        "salvation-v7-repentance-calibration",
        "salvation-v8-conversion-calibration",
        "salvation-collected-observations-review",
        "salvation-conversion-recalibration",
        "salvation-obedience-calibration",
        "salvation-observation-boundaries-review",
        "salvation-observation-threshold-review",
        "salvation-profile-repeatability",
        "salvation-repeatability-expansion-plan",
        "salvation-relationships-review",
        "salvation-routing-review",
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
        "topic-show-profile",
        "topic-stability-readiness",
        "topic-summarize-profile",
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

    def test_g2_feasibility_modes_dispatch_without_running_provider(self) -> None:
        for options, expected in (([], "evaluate"), (["--check-only"], "check"), (["--prepare-only"], "prepare")):
            with self.subTest(mode=expected), patch("pastor_transcript_extractor.sermon_g2_feasibility_review.run") as run:
                result = self.runner.invoke(app, ["analysis", "g2-feasibility-review", *options])
                self.assertEqual(0, result.exit_code, msg=result.output)
                run.assert_called_once_with(expected)

    def test_g2_revision_v2_dispatch_and_unknown_revision_is_rejected(self) -> None:
        with patch("pastor_transcript_extractor.sermon_g2_feasibility_revision.run") as run:
            result = self.runner.invoke(app, ["analysis", "g2-feasibility-review", "--revision", "v2", "--check-only"])
            self.assertEqual(0, result.exit_code, msg=result.output)
            run.assert_called_once_with("check")
        result = self.runner.invoke(app, ["analysis", "g2-feasibility-review", "--revision", "v3"])
        self.assertEqual(2, result.exit_code, msg=result.output)

    def test_g2_feasibility_conflicting_modes_do_not_run_provider(self) -> None:
        with patch("pastor_transcript_extractor.sermon_g2_feasibility_review.run") as run:
            result = self.runner.invoke(app, ["analysis", "g2-feasibility-review", "--prepare-only", "--check-only"])
            self.assertEqual(2, result.exit_code, msg=result.output)
            run.assert_not_called()

    def test_g3_feasibility_modes_dispatch_without_running_provider(self) -> None:
        for options, expected in (([], "evaluate"), (["--check-only"], "check"), (["--prepare-only"], "prepare")):
            with self.subTest(mode=expected), patch("pastor_transcript_extractor.sermon_g3_feasibility_review.run") as run:
                result = self.runner.invoke(app, ["analysis", "g3-feasibility-review", *options])
                self.assertEqual(0, result.exit_code, msg=result.output)
                run.assert_called_once_with(expected)
        with patch("pastor_transcript_extractor.sermon_g3_feasibility_review.run") as run:
            result = self.runner.invoke(app, ["analysis", "g3-feasibility-review", "--prepare-only", "--check-only"])
            self.assertEqual(2, result.exit_code, msg=result.output)
            run.assert_not_called()

    def test_g3_revision_dispatch_and_invalid_revision(self) -> None:
        for options, expected in (([], "evaluate"), (["--check-only"], "check"), (["--prepare-only"], "prepare")):
            with patch("pastor_transcript_extractor.sermon_g3_feasibility_revision.run") as run:
                result = self.runner.invoke(app, ["analysis", "g3-feasibility-review", "--revision", "v2", *options])
                self.assertEqual(0, result.exit_code, msg=result.output)
                run.assert_called_once_with(expected)
        result = self.runner.invoke(app, ["analysis", "g3-feasibility-review", "--revision", "v3"])
        self.assertEqual(2, result.exit_code, msg=result.output)

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

    def test_blocked_topic_stability_readiness_is_a_successful_audit(self) -> None:
        report = {
            "ready": False,
            "input_fingerprint": "f" * 64,
            "pastors": [],
            "review_actions": [],
        }
        with (
            patch(
                "pastor_transcript_extractor.commands.analysis.content.get_database",
                return_value=object(),
            ),
            patch(
                "pastor_transcript_extractor.commands.analysis.content.load_topic_stage4_cohort",
                return_value={},
            ),
            patch(
                "pastor_transcript_extractor.commands.analysis.content.assess_topic_stage4_readiness",
                return_value=report,
            ),
        ):
            result = self.runner.invoke(
                app, ["analysis", "topic-stability-readiness"]
            )

        self.assertEqual(0, result.exit_code, msg=result.output)
        self.assertIn("Overall: blocked", result.output)

    def test_boundary_readiness_action_includes_dependent_topic_packet(self) -> None:
        report = {
            "ready": False,
            "input_fingerprint": "f" * 64,
            "model": "jev-1.13.0",
            "pastors": [],
            "review_actions": [
                {
                    "action_type": "review_sermon_boundary",
                    "pastor": {"display_name": "Test Pastor"},
                    "pending_topic_reason_codes": [
                        "whole_sermon_review_unavailable"
                    ],
                    "video_id": 3,
                    "youtube_video_id": "youtube-3",
                }
            ],
        }
        with (
            patch(
                "pastor_transcript_extractor.commands.analysis.content.get_database",
                return_value=object(),
            ),
            patch(
                "pastor_transcript_extractor.commands.analysis.content.load_topic_stage4_cohort",
                return_value={},
            ),
            patch(
                "pastor_transcript_extractor.commands.analysis.content.assess_topic_stage4_readiness",
                return_value=report,
            ),
        ):
            result = self.runner.invoke(
                app,
                [
                    "analysis",
                    "topic-stability-readiness",
                    "--base-dir",
                    "/tmp/topic-readiness",
                ],
            )

        self.assertEqual(0, result.exit_code, msg=result.output)
        self.assertIn("apply-fixture-correction youtube-3", result.output)
        self.assertIn("topic-review --video-id 3 --whole-sermon", result.output)
        self.assertLess(
            result.output.index("apply-fixture-correction"),
            result.output.index("topic-review"),
        )

    def test_topic_refresh_makes_packet_generation_conditional(self) -> None:
        report = {
            "ready": False,
            "input_fingerprint": "f" * 64,
            "model": "jev-1.13.0",
            "pastors": [],
            "review_actions": [
                {
                    "action_type": "prepare_topic_evidence",
                    "pastor": {"display_name": "Test Pastor"},
                    "reason_codes": ["topic_analysis_unavailable"],
                    "video_id": 599,
                    "youtube_video_id": "youtube-599",
                }
            ],
        }
        with (
            patch(
                "pastor_transcript_extractor.commands.analysis.content.get_database",
                return_value=object(),
            ),
            patch(
                "pastor_transcript_extractor.commands.analysis.content.load_topic_stage4_cohort",
                return_value={},
            ),
            patch(
                "pastor_transcript_extractor.commands.analysis.content.assess_topic_stage4_readiness",
                return_value=report,
            ),
        ):
            result = self.runner.invoke(
                app,
                [
                    "analysis",
                    "topic-stability-readiness",
                    "--base-dir",
                    "/tmp/topic-readiness",
                ],
            )

        self.assertEqual(0, result.exit_code, msg=result.output)
        self.assertIn("If the refreshed disposition is accepted_sermon", result.output)
        self.assertIn("If it is review_required", result.output)
        self.assertLess(result.output.index("reclassify"), result.output.index("topic-review"))

    def test_topic_review_gap_does_not_reclassify_current_evidence(self) -> None:
        report = {
            "ready": False,
            "input_fingerprint": "f" * 64,
            "model": "jev-1.13.0",
            "pastors": [],
            "review_actions": [
                {
                    "action_type": "review_topic_evidence",
                    "pastor": {"display_name": "Test Pastor"},
                    "packet_path": "/tmp/topic-whole-sermon-review-v1.json",
                    "reason_codes": ["whole_sermon_review_unavailable"],
                    "video_id": 1037,
                    "youtube_video_id": "youtube-1037",
                }
            ],
        }
        with (
            patch(
                "pastor_transcript_extractor.commands.analysis.content.get_database",
                return_value=object(),
            ),
            patch(
                "pastor_transcript_extractor.commands.analysis.content.load_topic_stage4_cohort",
                return_value={},
            ),
            patch(
                "pastor_transcript_extractor.commands.analysis.content.assess_topic_stage4_readiness",
                return_value=report,
            ),
        ):
            result = self.runner.invoke(
                app,
                [
                    "analysis",
                    "topic-stability-readiness",
                    "--base-dir",
                    "/tmp/topic-readiness",
                ],
            )

        self.assertEqual(0, result.exit_code, msg=result.output)
        self.assertIn("Cached TypeSafe observations are current", result.output)
        self.assertIn("topic-review --video-id 1037", result.output)
        self.assertIn("topic-review-draft", result.output)
        self.assertNotIn("pte reclassify", result.output)

    def test_salvation_observation_review_prints_bounded_readiness_actions(self) -> None:
        report = {
            "ready": False,
            "blockers": ["disposition_not_accepted"],
            "input_fingerprint": "f" * 64,
            "model": "jev-1.13.0",
            "pastors": [
                {
                    "display_name": "Test Pastor",
                    "effective_profile_ids": [],
                    "sermons": [{"eligible": False}],
                    "series_keys": ["series"],
                    "period_keys": ["period"],
                    "blockers": ["disposition_not_accepted"],
                }
            ],
            "review_actions": [
                {
                    "action_type": "prepare_topic_evidence",
                    "pastor": {"display_name": "Test Pastor"},
                    "reason_codes": ["disposition_not_accepted"],
                    "video_id": 599,
                    "youtube_video_id": "youtube-599",
                }
            ],
        }
        with (
            patch(
                "pastor_transcript_extractor.commands.analysis.content.get_database",
                return_value=object(),
            ),
            patch(
                "pastor_transcript_extractor.commands.analysis.content.load_topic_stage4_cohort",
                return_value={},
            ),
            patch(
                "pastor_transcript_extractor.commands.analysis.content.assess_topic_stage4_readiness",
                return_value=report,
            ),
            patch(
                "pastor_transcript_extractor.commands.analysis.content.evaluate_salvation_collected_observations_review",
                side_effect=ValueError(
                    "Salvation observation review requires ready Stage 4 inputs: "
                    "disposition_not_accepted"
                ),
            ) as evaluate,
        ):
            result = self.runner.invoke(
                app,
                [
                    "analysis",
                    "salvation-collected-observations-review",
                    "--base-dir",
                    "/tmp/topic-readiness",
                ],
            )

        self.assertNotEqual(0, result.exit_code)
        self.assertIn("Overall: blocked", result.output)
        self.assertIn("reclassify --video-id 599", result.output)
        evaluate.assert_called_once_with(ANY, {}, readiness=report)

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
