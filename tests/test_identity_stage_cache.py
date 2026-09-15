from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pastor_transcript_extractor.cli import run_identity_workflow_service
from pastor_transcript_extractor.identity_stage_cache import (
    ASSOCIATION_INPUT_STATE_VERSION,
    association_refresh_mode,
    build_association_input_state,
    build_identity_stage_fingerprint,
    load_identity_stage_checkpoint,
    load_identity_stage_input_state,
    write_identity_stage_checkpoint,
)
from pastor_transcript_extractor.models import SourceType
from pastor_transcript_extractor.storage import Database


class IdentityStageCacheTests(unittest.TestCase):
    def test_association_refresh_is_incremental_only_for_new_observations(self) -> None:
        def state(recordings, *, global_fingerprint="global"):
            return {
                "version": ASSOCIATION_INPUT_STATE_VERSION,
                "global_fingerprint": global_fingerprint,
                "recordings": recordings,
            }

        original = state(
            {
                "video-a": {
                    "fingerprint": "recording-a",
                    "current_observation_fingerprint": "observation-a",
                }
            }
        )
        added = state(
            {
                **original["recordings"],
                "video-b": {
                    "fingerprint": "recording-b",
                    "current_observation_fingerprint": "observation-b",
                },
            }
        )
        replaced = state(
            {
                "video-a": {
                    "fingerprint": "recording-a-v2",
                    "current_observation_fingerprint": "observation-a-v2",
                }
            }
        )
        metadata_only = state(
            {
                "video-a": {
                    "fingerprint": "recording-a-v2",
                    "current_observation_fingerprint": "observation-a",
                }
            }
        )

        self.assertEqual("incremental", association_refresh_mode(original, added))
        self.assertEqual("incremental", association_refresh_mode(original, replaced))
        self.assertEqual("full", association_refresh_mode(original, metadata_only))
        self.assertEqual(
            "full",
            association_refresh_mode(
                original,
                state(
                    original["recordings"],
                    global_fingerprint="changed",
                ),
            ),
        )
        self.assertEqual("full", association_refresh_mode(added, original))

    def test_checkpoint_round_trips_verified_association_input_state(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            database = Database(root / "app.db")
            database.initialize()
            state = build_association_input_state(
                root / "app.db",
                parameters={"policy": "v1"},
            )
            output = root / "association.json"
            output.write_text("{}\n", encoding="utf-8")
            cache_root = root / "cache"
            write_identity_stage_checkpoint(
                cache_root,
                stage="association",
                input_fingerprint="inputs",
                outputs=(output,),
                input_state=state,
            )

            loaded = load_identity_stage_input_state(
                cache_root,
                stage="association",
            )

        self.assertEqual(state, loaded)

    def test_association_input_state_tracks_latest_observation_per_video(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            database = Database(root / "app.db")
            database.initialize()
            source = database.add_source(
                "https://www.youtube.com/@state-test",
                SourceType.CHANNEL,
                pastor_id=None,
            )
            video = database.add_video(
                source.id,
                None,
                "state-test-video",
                "State test",
                "https://www.youtube.com/watch?v=state-test-video",
            )
            proposed = root / "proposed.json"
            proposed.write_text("{}\n", encoding="utf-8")
            extraction = database.add_extraction_result(
                video.id,
                1,
                str(root / "proposed.md"),
                str(proposed),
            )
            database.add_speaker_observation(
                video_id=video.id,
                extraction_result_id=extraction.id,
                role="principal_speaker_candidate",
                multiplicity_state="unknown",
                start_seconds=1.0,
                end_seconds=10.0,
                artifact_path=str(root / "speaker.json"),
                content_sha256="content",
                extractor_version="test",
                input_fingerprint="observation-v1",
            )

            state = build_association_input_state(
                root / "app.db",
                parameters={"policy": "v1"},
            )

        self.assertEqual(
            "observation-v1",
            state["recordings"]["state-test-video"][
                "current_observation_fingerprint"
            ],
        )

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

            with patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("unchanged output was rehashed"),
            ):
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
        self.assertFalse(associate.call_args_list[0].kwargs["unattempted_only"])
        self.assertTrue(associate.call_args_list[1].kwargs["unattempted_only"])


if __name__ == "__main__":
    unittest.main()
