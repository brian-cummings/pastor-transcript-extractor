from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from typer.testing import CliRunner

from pastor_transcript_extractor.cli import (
    ActionableReviewAudioPreparation,
    _actionable_review_fingerprints,
    _archive_normalized_after_identity,
    _held_out_speaker_fixture_fingerprints,
    _load_actionable_review_prewarm,
    _prepare_actionable_review_audio,
    app,
    review_next_speaker_pair,
    run_identity_workflow_service,
    validate_source_families,
)
from pastor_transcript_extractor.config import AppPaths


class IdentityRunTests(unittest.TestCase):
    def test_hidden_prewarm_fallback_parameter_belongs_to_review_command(self):
        self.assertIn(
            "ignore_prewarm",
            inspect.signature(review_next_speaker_pair).parameters,
        )
        self.assertNotIn(
            "ignore_prewarm",
            inspect.signature(validate_source_families).parameters,
        )

    def test_held_out_fixture_observations_are_reserved_from_machine_use(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            fixture_dir = Path(tempdir)
            (fixture_dir / "held-out.json").write_text(
                """{
                  "evaluation_partition": "held_out",
                  "observations": {
                    "a": {"input_fingerprint": "fingerprint-a"},
                    "b": {"input_fingerprint": "fingerprint-b"}
                  }
                }""",
                encoding="utf-8",
            )
            (fixture_dir / "development.json").write_text(
                """{
                  "evaluation_partition": "development",
                  "observations": {
                    "a": {"input_fingerprint": "fingerprint-c"},
                    "b": {"input_fingerprint": "fingerprint-d"}
                  }
                }""",
                encoding="utf-8",
            )

            reserved = _held_out_speaker_fixture_fingerprints(fixture_dir)

        self.assertEqual(
            frozenset(("fingerprint-a", "fingerprint-b")),
            reserved,
        )

    def test_all_run_chains_backfill_association_confirmation_and_discovery(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            database_path = Path(tempdir) / "app.db"
            database_path.touch()
            root = Path(tempdir)
            paths = AppPaths(
                root=root,
                database=database_path,
                artifacts=root / "artifacts",
                logs=root / "logs",
                exports=root / "exports",
                pastors=root / "pastors",
            )
            with (
                patch(
                    "pastor_transcript_extractor.cli.build_paths",
                    return_value=paths,
                ),
                patch("pastor_transcript_extractor.cli.Database"),
                patch(
                    "pastor_transcript_extractor.cli.load_reviewed_speaker_evidence"
                ) as load_evidence,
                patch(
                    "pastor_transcript_extractor.cli.sync_reviewed_speaker_evidence"
                ) as sync_evidence,
                patch(
                    "pastor_transcript_extractor.cli._print_reviewed_evidence_summary"
                ),
                patch(
                    "pastor_transcript_extractor.cli.identity_backfill"
                ) as backfill,
                patch(
                    "pastor_transcript_extractor.cli.shadow_associate_speakers_command"
                ) as associate,
                patch(
                    "pastor_transcript_extractor.cli.plan_machine_assignments",
                    return_value=SimpleNamespace(
                        candidates=(),
                        skipped_counts={},
                        tripped_policy_fingerprints=frozenset(),
                    ),
                ) as plan_machine,
                patch(
                    "pastor_transcript_extractor.cli.apply_machine_assignment_plan",
                    return_value=SimpleNamespace(
                        evidence_recorded=0,
                        evidence_reused=0,
                        assignments_activated=0,
                        activation_blocked=0,
                    ),
                ) as apply_machine,
                patch(
                    "pastor_transcript_extractor.cli.confirm_discovered_profiles_command"
                ) as confirm,
                patch(
                    "pastor_transcript_extractor.cli.shadow_discover_profiles_command"
                ) as discover,
                patch(
                    "pastor_transcript_extractor.cli.promote_discovered_profiles_command"
                ) as promote,
                patch(
                    "pastor_transcript_extractor.cli.coordinate_identity_command"
                ) as coordinate,
                patch(
                    "pastor_transcript_extractor.cli._prepare_actionable_review_audio",
                    return_value=ActionableReviewAudioPreparation(
                        requested=4,
                        prepared=2,
                        already_cached=2,
                        excluded=0,
                        failed=0,
                    ),
                ) as prewarm,
                patch(
                    "pastor_transcript_extractor.cli._archive_normalized_after_identity"
                ) as archive_normalized,
                patch.object(Path, "glob", return_value=[]),
            ):
                current_report = Path(tempdir) / "current-association.json"
                associate.return_value = (current_report,)
                run_identity_workflow_service(
                    youtube_video_id=None,
                    all_extractions=True,
                    plan_only=False,
                    skip_discovery=False,
                    apply_automatic=False,
                    apply_confirmations=False,
                    apply_promotions=False,
                    base_dir=Path(tempdir),
                )

        backfill.assert_called_once_with(
            video_id=None,
            base_dir=Path(tempdir),
        )
        load_evidence.assert_called_once()
        sync_evidence.assert_called_once()
        self.assertFalse(associate.call_args.kwargs["plan_only"])
        self.assertTrue(associate.call_args.kwargs["all_eligible"])
        self.assertEqual(
            (current_report,),
            plan_machine.call_args.args[1],
        )
        self.assertFalse(apply_machine.call_args.kwargs["activate_canary"])
        self.assertFalse(confirm.call_args.kwargs["apply"])
        self.assertFalse(discover.call_args.kwargs["plan_only"])
        promote.assert_not_called()
        self.assertTrue(coordinate.call_args.kwargs["all_extractions"])
        prewarm.assert_called_once_with(
            unittest.mock.ANY,
            paths,
            discovery_report=None,
            association_reports=(current_report,),
            limit=24,
            automatic_profile_ready_ids=frozenset(),
        )
        archive_normalized.assert_called_once_with(
            unittest.mock.ANY,
            paths,
            video_ids=None,
            all_eligible=True,
        )

    def test_actionable_review_fingerprints_prioritize_and_deduplicate(self) -> None:
        association = SimpleNamespace(
            candidate_fingerprint="candidate",
            exemplar_fingerprint="shared",
            profile_id=7,
        )
        ready_association = SimpleNamespace(
            candidate_fingerprint="ready-candidate",
            exemplar_fingerprint="ready-exemplar",
            profile_id=99,
        )
        resolution = SimpleNamespace(
            fingerprint_a="shared",
            fingerprint_b="frontier",
        )
        acoustic = SimpleNamespace(
            fingerprint_a="acoustic-a",
            fingerprint_b="acoustic-b",
        )
        with (
            patch(
                "pastor_transcript_extractor.cli."
                "load_shadow_association_confirmation_pairs",
                return_value=(association, ready_association),
            ),
            patch(
                "pastor_transcript_extractor.cli."
                "load_discovery_resolution_pairs",
                return_value=(resolution,),
            ),
            patch(
                "pastor_transcript_extractor.cli."
                "load_discovery_acoustic_ranking_pairs",
                return_value=(acoustic,),
            ),
        ):
            fingerprints = _actionable_review_fingerprints(
                discovery_report=Path("discovery.json"),
                association_reports=(Path("association.json"),),
                automatic_profile_ready_ids=frozenset((99,)),
            )

        self.assertEqual(
            (
                "candidate",
                "shared",
                "frontier",
                "acoustic-a",
                "acoustic-b",
            ),
            fingerprints,
        )

    def test_actionable_review_audio_prepares_only_current_eligible_inputs(
        self,
    ) -> None:
        root = Path("/tmp/actionable-review-prewarm-test")
        paths = AppPaths(
            root=root,
            database=root / "app.db",
            artifacts=root / "artifacts",
            logs=root / "logs",
            exports=root / "exports",
            pastors=root / "pastors",
        )
        observations = {
            "current": SimpleNamespace(
                video_id=1,
                input_fingerprint="current",
            ),
            "stale": SimpleNamespace(
                video_id=2,
                input_fingerprint="stale",
            ),
        }
        videos = {
            1: SimpleNamespace(id=1, youtube_video_id="video-current"),
            2: SimpleNamespace(id=2, youtube_video_id="video-stale"),
        }
        database = SimpleNamespace(
            get_speaker_observation_by_fingerprint=observations.get,
            get_video_by_id=videos.get,
        )
        media = SimpleNamespace(artifact_path="/tmp/current.wav")
        prepared = SimpleNamespace(
            spans=(
                SimpleNamespace(
                    wav_path="/tmp/current-clip.wav",
                    cache_hit=False,
                ),
            )
        )

        def eligibility(_database, video_id, **_kwargs):
            if video_id == 2:
                return SimpleNamespace(eligible=False)
            return SimpleNamespace(
                eligible=True,
                observation=observations["current"],
                media_artifact=media,
            )

        with (
            patch(
                "pastor_transcript_extractor.cli."
                "_actionable_review_fingerprints",
                return_value=("current", "stale"),
            ),
            patch(
                "pastor_transcript_extractor.cli."
                "assess_automatic_speaker_observation",
                side_effect=eligibility,
            ),
            patch(
                "pastor_transcript_extractor.cli.prepare_review_observation",
                return_value=prepared,
            ) as prepare,
            patch(
                "pastor_transcript_extractor.cli."
                "write_canonical_clip_preparation_manifest"
            ) as write_manifest,
        ):
            cache_dir = root / "cache"
            result = _prepare_actionable_review_audio(
                database,
                paths,
                discovery_report=Path("discovery.json"),
                association_reports=(),
                cache_dir=cache_dir,
                limit=24,
            )

        self.assertEqual(
            ActionableReviewAudioPreparation(
                2,
                1,
                0,
                1,
                0,
                ("current",),
            ),
            result,
        )
        prepare.assert_called_once()
        self.assertEqual(
            Path("/tmp/current.wav"),
            prepare.call_args.kwargs["audio_path"],
        )
        write_manifest.assert_called_once_with(
            paths,
            media,
            observations["current"],
            clip_paths=(Path("/tmp/current-clip.wav"),),
        )
        self.assertEqual(
            ("current",),
            _load_actionable_review_prewarm(cache_dir),
        )

    def test_identity_archive_waits_for_lock_and_reports_unavailable_as_deferred(
        self,
    ) -> None:
        lifecycle_order = []
        database = SimpleNamespace(
            get_active_media_archive_destination=lambda: SimpleNamespace(id=1)
        )
        paths = AppPaths(
            root=Path("/tmp/identity-archive-test"),
            database=Path("/tmp/identity-archive-test/app.db"),
            artifacts=Path("/tmp/identity-archive-test/artifacts"),
            logs=Path("/tmp/identity-archive-test/logs"),
            exports=Path("/tmp/identity-archive-test/exports"),
            pastors=Path("/tmp/identity-archive-test/pastors"),
        )
        archive_result = SimpleNamespace(
            counts={
                "archived": 0,
                "already_archived": 0,
                "destination_unavailable": 2,
                "failed": 0,
                "would_archive": 0,
            },
            eligible=2,
            eligibility=(SimpleNamespace(eligible=True), SimpleNamespace(eligible=True)),
        )
        with (
            patch(
                "pastor_transcript_extractor.cli.prepare_canonical_audio",
                return_value=SimpleNamespace(
                    items=(),
                    counts={
                        "prepared": 2,
                        "would_prepare": 0,
                        "already_prepared": 0,
                        "deferred": 0,
                        "blocked": 0,
                        "failed": 0,
                    },
                ),
            ) as prepare,
            patch(
                "pastor_transcript_extractor.cli.archive_normalized_media",
                return_value=archive_result,
            ) as archive,
            patch("pastor_transcript_extractor.cli.console.print") as output,
        ):
            prepare.side_effect = lambda *args, **kwargs: (
                lifecycle_order.append("prepare")
                or SimpleNamespace(
                    items=(),
                    counts={
                        "prepared": 2,
                        "would_prepare": 0,
                        "already_prepared": 0,
                        "deferred": 0,
                        "blocked": 0,
                        "failed": 0,
                    },
                )
            )
            archive.side_effect = lambda *args, **kwargs: (
                lifecycle_order.append("archive") or archive_result
            )
            _archive_normalized_after_identity(
                database,
                paths,
                video_ids={7, 8},
                all_eligible=False,
            )

        prepare.assert_called_once_with(
            database,
            paths,
            cache_root=Path("evaluation/speaker-pairs/cache"),
            video_ids={7, 8},
            all_eligible=False,
            wait_for_lock=True,
            progress_callback=unittest.mock.ANY,
        )
        self.assertTrue(archive.call_args.kwargs["wait_for_lock"])
        self.assertTrue(callable(archive.call_args.kwargs["progress_callback"]))
        self.assertTrue(callable(archive.call_args.kwargs["preflight_callback"]))
        self.assertEqual({7, 8}, archive.call_args.kwargs["video_ids"])
        self.assertEqual(["prepare", "archive"], lifecycle_order)
        self.assertIn("deferred=2", output.call_args_list[-1].args[0])

    def test_standalone_normalized_archive_prints_item_progress(self) -> None:
        paths = AppPaths(
            root=Path("/tmp/normalized-progress-test"),
            database=Path("/tmp/normalized-progress-test/app.db"),
            artifacts=Path("/tmp/normalized-progress-test/artifacts"),
            logs=Path("/tmp/normalized-progress-test/logs"),
            exports=Path("/tmp/normalized-progress-test/exports"),
            pastors=Path("/tmp/normalized-progress-test/pastors"),
        )
        archive_result = SimpleNamespace(
            destination=SimpleNamespace(archive_root="/archive"),
            eligible=1,
            eligibility=(),
            counts={
                "archived": 1,
                "already_archived": 0,
                "destination_unavailable": 0,
                "failed": 0,
                "would_archive": 0,
            },
        )

        def fake_archive(*_args, **kwargs):
            kwargs["preflight_callback"](
                SimpleNamespace(
                    check="eligibility", status="passed", detail="1 artifact"
                )
            )
            kwargs["progress_callback"](
                SimpleNamespace(
                    index=1,
                    total=1,
                    media_artifact_id=99,
                    source_path=Path("normalized.wav"),
                    archive_path=Path("/archive/normalized.wav"),
                    stage="complete",
                    outcome="archived",
                    detail=None,
                )
            )
            return archive_result

        with (
            patch("pastor_transcript_extractor.cli.get_database", return_value=object()),
            patch("pastor_transcript_extractor.cli.build_paths", return_value=paths),
            patch(
                "pastor_transcript_extractor.cli.archive_normalized_media",
                side_effect=fake_archive,
            ),
        ):
            result = CliRunner().invoke(
                app,
                [
                    "media",
                    "archive-normalized",
                    "--all-eligible",
                    "--base-dir",
                    str(paths.root),
                ],
            )

        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn("[1/1] normalized artifact #99: archived", result.output)

    def test_single_identity_finalization_reports_offline_preparation_retry(self) -> None:
        database = SimpleNamespace(
            get_active_media_archive_destination=lambda: SimpleNamespace(id=1)
        )
        paths = AppPaths(
            root=Path("/tmp/identity-offline-test"),
            database=Path("/tmp/identity-offline-test/app.db"),
            artifacts=Path("/tmp/identity-offline-test/artifacts"),
            logs=Path("/tmp/identity-offline-test/logs"),
            exports=Path("/tmp/identity-offline-test/exports"),
            pastors=Path("/tmp/identity-offline-test/pastors"),
        )
        preparation = SimpleNamespace(
            items=(
                SimpleNamespace(
                    outcome="deferred", youtube_video_id="offline001"
                ),
            ),
            counts={
                "prepared": 0,
                "would_prepare": 0,
                "already_prepared": 0,
                "deferred": 1,
                "blocked": 0,
                "failed": 0,
            },
        )
        with (
            patch(
                "pastor_transcript_extractor.cli.prepare_canonical_audio",
                return_value=preparation,
            ),
            patch(
                "pastor_transcript_extractor.cli.archive_normalized_media"
            ) as archive,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "pte media prepare-canonical-audio --youtube-video-id offline001",
            ):
                _archive_normalized_after_identity(
                    database,
                    paths,
                    video_ids={7},
                    all_eligible=False,
                )

        archive.assert_not_called()

    def test_plan_only_rejects_registry_mutation_flags(self) -> None:
        with self.assertRaisesRegex(ValueError, "plan-only"):
            run_identity_workflow_service(
                youtube_video_id=None,
                all_extractions=True,
                plan_only=True,
                skip_discovery=False,
                apply_automatic=False,
                apply_confirmations=True,
                apply_promotions=False,
                base_dir=None,
            )

    def test_apply_automatic_enables_confirmations_and_promotions(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            database_path = Path(tempdir) / "app.db"
            database_path.touch()
            discovery_path = Path(tempdir) / "discovery.json"
            discovery_path.touch()
            paths = SimpleNamespace(
                database=database_path,
                logs=Path(tempdir) / "logs",
            )
            with (
                patch(
                    "pastor_transcript_extractor.cli.build_paths",
                    return_value=paths,
                ),
                patch("pastor_transcript_extractor.cli.Database"),
                patch(
                    "pastor_transcript_extractor.cli.load_reviewed_speaker_evidence"
                ),
                patch(
                    "pastor_transcript_extractor.cli.sync_reviewed_speaker_evidence"
                ),
                patch(
                    "pastor_transcript_extractor.cli._print_reviewed_evidence_summary"
                ),
                patch("pastor_transcript_extractor.cli.identity_backfill"),
                patch(
                    "pastor_transcript_extractor.cli.shadow_associate_speakers_command"
                ),
                patch(
                    "pastor_transcript_extractor.cli.plan_machine_assignments",
                    return_value=SimpleNamespace(
                        candidates=(),
                        skipped_counts={},
                        tripped_policy_fingerprints=frozenset(),
                    ),
                ),
                patch(
                    "pastor_transcript_extractor.cli.apply_machine_assignment_plan",
                    return_value=SimpleNamespace(
                        evidence_recorded=0,
                        evidence_reused=0,
                        assignments_activated=0,
                        activation_blocked=0,
                    ),
                ) as apply_machine,
                patch(
                    "pastor_transcript_extractor.cli.confirm_discovered_profiles_command"
                ) as confirm,
                patch(
                    "pastor_transcript_extractor.cli.shadow_discover_profiles_command"
                ),
                patch(
                    "pastor_transcript_extractor.cli.promote_discovered_profiles_command"
                ) as promote,
                patch(
                    "pastor_transcript_extractor.cli.coordinate_identity_command"
                ),
                patch.object(Path, "glob", return_value=[discovery_path]),
            ):
                run_identity_workflow_service(
                    youtube_video_id=None,
                    all_extractions=True,
                    plan_only=False,
                    skip_discovery=False,
                    apply_automatic=True,
                    apply_confirmations=False,
                    apply_promotions=False,
                    review_prewarm_limit=0,
                    base_dir=Path(tempdir),
                )

        self.assertTrue(confirm.call_args.kwargs["apply"])
        self.assertTrue(promote.call_args.kwargs["apply"])
        self.assertTrue(apply_machine.call_args.kwargs["activate_canary"])

    def test_requires_exactly_one_scope(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            run_identity_workflow_service(
                youtube_video_id=None,
                all_extractions=False,
                plan_only=True,
                skip_discovery=False,
                apply_automatic=False,
                apply_confirmations=False,
                apply_promotions=False,
                base_dir=None,
            )


if __name__ == "__main__":
    unittest.main()
