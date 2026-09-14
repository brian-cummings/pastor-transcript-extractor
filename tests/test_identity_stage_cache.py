from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pastor_transcript_extractor.cli import run_identity_workflow_service
from pastor_transcript_extractor.identity_stage_cache import (
    build_identity_stage_fingerprint,
    load_identity_stage_checkpoint,
    write_identity_stage_checkpoint,
)
from pastor_transcript_extractor.models import SourceType
from pastor_transcript_extractor.storage import Database


class IdentityStageCacheTests(unittest.TestCase):
    def test_fingerprint_changes_for_database_and_review_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            database_path = root / "app.db"
            database = Database(database_path)
            database.initialize()
            review = root / "reviews" / "pair.json"
            review.parent.mkdir()
            review.write_text('{"decision":"same"}\n', encoding="utf-8")

            initial = build_identity_stage_fingerprint(
                database_path,
                stage="association",
                parameters={"policy": "v1"},
                input_paths=(review,),
            )
            source = database.add_source(
                "https://www.youtube.com/@identity-cache",
                SourceType.CHANNEL,
                pastor_id=None,
            )
            database.add_video(
                source.id,
                None,
                "new-video",
                "New video",
                "https://www.youtube.com/watch?v=new-video",
            )
            database_changed = build_identity_stage_fingerprint(
                database_path,
                stage="association",
                parameters={"policy": "v1"},
                input_paths=(review,),
            )
            review.write_text('{"decision":"different"}\n', encoding="utf-8")
            review_changed = build_identity_stage_fingerprint(
                database_path,
                stage="association",
                parameters={"policy": "v1"},
                input_paths=(review,),
            )

        self.assertNotEqual(initial, database_changed)
        self.assertNotEqual(database_changed, review_changed)

    def test_checkpoint_reuses_only_checksum_verified_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            output = root / "association.json"
            output.write_text('{"outcome":"no_match"}\n', encoding="utf-8")
            cache_root = root / "cache"
            write_identity_stage_checkpoint(
                cache_root,
                stage="association",
                input_fingerprint="inputs-a",
                outputs=(output,),
            )

            reused = load_identity_stage_checkpoint(
                cache_root,
                stage="association",
                input_fingerprint="inputs-a",
            )
            wrong_inputs = load_identity_stage_checkpoint(
                cache_root,
                stage="association",
                input_fingerprint="inputs-b",
            )
            output.write_text('{"outcome":"proposed_match"}\n', encoding="utf-8")
            tampered = load_identity_stage_checkpoint(
                cache_root,
                stage="association",
                input_fingerprint="inputs-a",
            )

        self.assertEqual((output.resolve(),), reused)
        self.assertIsNone(wrong_inputs)
        self.assertIsNone(tampered)

    def test_empty_completed_stage_is_a_cache_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            cache_root = Path(tempdir) / "cache"
            write_identity_stage_checkpoint(
                cache_root,
                stage="discovery",
                input_fingerprint="empty-inputs",
                outputs=(),
            )

            reused = load_identity_stage_checkpoint(
                cache_root,
                stage="discovery",
                input_fingerprint="empty-inputs",
            )

        self.assertEqual((), reused)

    def test_unchanged_workflow_skips_association_and_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            database = Database(root / "app.db")
            database.initialize()
            association_report = root / "association.json"
            association_report.write_text("{}\n", encoding="utf-8")
            discovery_report = root / "discovery.json"
            discovery_report.write_text("{}\n", encoding="utf-8")
            reconciliation = SimpleNamespace(
                confirmed=0,
                revoked=0,
                circuit_breaker_revoked=0,
                unchanged=0,
            )
            machine_plan = SimpleNamespace(
                candidates=(),
                skipped_counts={},
                tripped_policy_fingerprints=frozenset(),
            )
            machine_apply = SimpleNamespace(
                evidence_recorded=0,
                evidence_reused=0,
                assignments_activated=0,
                activation_blocked=0,
            )
            with (
                patch(
                    "pastor_transcript_extractor.cli.load_reviewed_speaker_evidence",
                    return_value=SimpleNamespace(),
                ),
                patch("pastor_transcript_extractor.cli.sync_reviewed_speaker_evidence"),
                patch("pastor_transcript_extractor.cli._print_reviewed_evidence_summary"),
                patch("pastor_transcript_extractor.cli.identity_backfill"),
                patch(
                    "pastor_transcript_extractor.cli.reconcile_machine_assignments",
                    return_value=reconciliation,
                ),
                patch(
                    "pastor_transcript_extractor.cli.shadow_associate_speakers_command",
                    return_value=(association_report,),
                ) as associate,
                patch(
                    "pastor_transcript_extractor.cli.latest_association_reports",
                    return_value=(association_report,),
                ),
                patch(
                    "pastor_transcript_extractor.cli."
                    "ExemplarPreparationStateCache.pending_automatic_repairs",
                    return_value=(),
                ),
                patch(
                    "pastor_transcript_extractor.cli.assess_profile_association_readiness",
                    return_value=(),
                ),
                patch(
                    "pastor_transcript_extractor.cli.plan_machine_assignments",
                    return_value=machine_plan,
                ),
                patch(
                    "pastor_transcript_extractor.cli.apply_machine_assignment_plan",
                    return_value=machine_apply,
                ),
                patch("pastor_transcript_extractor.cli.confirm_discovered_profiles_command"),
                patch(
                    "pastor_transcript_extractor.cli.shadow_discover_profiles_command",
                    return_value=discovery_report,
                ) as discover,
                patch("pastor_transcript_extractor.cli.promote_discovered_profiles_command"),
                patch("pastor_transcript_extractor.cli.coordinate_identity_command"),
                patch("pastor_transcript_extractor.cli._archive_normalized_after_identity"),
            ):
                for _ in range(2):
                    run_identity_workflow_service(
                        youtube_video_id=None,
                        all_extractions=True,
                        plan_only=False,
                        skip_discovery=False,
                        apply_automatic=False,
                        apply_confirmations=False,
                        apply_promotions=False,
                        review_prewarm_limit=0,
                        base_dir=root,
                        jobs=2,
                    )
                source = database.add_source(
                    "https://www.youtube.com/@new-identity-input",
                    SourceType.CHANNEL,
                    pastor_id=None,
                )
                database.add_video(
                    source.id,
                    None,
                    "new-identity-input",
                    "New identity input",
                    "https://www.youtube.com/watch?v=new-identity-input",
                )
                run_identity_workflow_service(
                    youtube_video_id=None,
                    all_extractions=True,
                    plan_only=False,
                    skip_discovery=False,
                    apply_automatic=False,
                    apply_confirmations=False,
                    apply_promotions=False,
                    review_prewarm_limit=0,
                    base_dir=root,
                    jobs=2,
                )

        self.assertEqual(2, associate.call_count)
        self.assertEqual(2, discover.call_count)


if __name__ == "__main__":
    unittest.main()
