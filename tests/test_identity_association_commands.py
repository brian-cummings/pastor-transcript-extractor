from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from pastor_transcript_extractor.commands.identity import association


class IdentityAssociationCommandTests(unittest.TestCase):
    def test_service_reduces_scope_before_preparation_and_full_scope_is_noop(self):
        from pastor_transcript_extractor import cli
        from pastor_transcript_extractor.speaker_shadow_association import ProfileAssociationReadiness
        from pastor_transcript_extractor.workflows.identity.association import ShadowAssociationRequest
        from pastor_transcript_extractor.workflows.identity.association_preparation import AssociationExemplarPreparationResult
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.db").touch()
            videos = {i: SimpleNamespace(id=i, source_id=i, title="Sermon") for i in (1, 2)}
            observations = {i: SimpleNamespace(id=i, video_id=i) for i in (1, 2)}
            profiles = tuple(ProfileAssociationReadiness(
                profile_id=i, member_observation_ids=(i,), member_fingerprints=(f"o{i}",),
                recording_count=3, source_count=1, normalized_names=(), shadow_ready=True,
                automatic_profile_ready=True, shadow_blockers=(), automatic_blockers=(), review_ready=True,
            ) for i in (1, 2))
            db = Mock()
            db.get_video_by_youtube_id.return_value = videos[1]
            inventory = SimpleNamespace(videos_by_id=videos, observations_by_id=observations,
                current_observation_by_video_id=observations, source_id_by_video_id={1: 1, 2: 2},
                candidate_names_by_observation={})
            setup = SimpleNamespace(database=db, cache_root=root / "cache", verification_cache=Mock(),
                span_cache=Mock(), policy_spec=SimpleNamespace(artifact_sha256="policy"),
                readiness=profiles, backend=None, embedding_cache=None, pair_diagnostic_cache=None,
                activity_selection_cache=SimpleNamespace(hits=0, misses=0))
            empty = AssociationExemplarPreparationResult((), (), {}, {}, {}, {})
            for full, plan_only in ((False, True), (True, True), (False, False)):
                request = ShadowAssociationRequest(
                    youtube_video_id=None if full else "video", all_eligible=full,
                    unattempted_only=False, neighborhood_profile_ids=(), include_profiled=False,
                    limit=None, plan_only=plan_only, minimum_profile_members=3, maximum_exemplars=3,
                    minimum_same_exemplars=2, maximum_global_profiles=1, jobs=1,
                    model_path=root / "model", model_sha256="sha", policy_path=root / "policy",
                    evaluation_root=root / "evaluation", cache_dir=root / "cache",
                    output_root=root / "output", base_dir=root,
                )
                with (patch.object(cli, "initialize_shadow_association", return_value=setup),
                      patch.object(cli, "load_association_corpus_inventory", return_value=inventory),
                      patch.object(cli, "scan_association_candidates", return_value=SimpleNamespace(span_inputs=(), exclusion_counts={})),
                      patch.object(cli, "prepare_association_exemplars", return_value=empty) as prepare):
                    if plan_only:
                        self.assertEqual((), cli.shadow_associate_speakers_service(request))
                        selected = prepare.call_args.args[1]
                        self.assertEqual((1, 2) if full else (1,), tuple(p.profile_id for p in selected))
                    else:
                        import typer
                        with self.assertRaisesRegex(typer.BadParameter, "No eligible"):
                            cli.shadow_associate_speakers_service(request)
                        prepare.assert_not_called()

    def test_command_builds_immutable_association_request(self) -> None:
        requests = []
        previous_invoker = association._shadow_association_invoker
        if previous_invoker is not None:
            self.addCleanup(
                association.configure_shadow_association, previous_invoker
            )
        association.configure_shadow_association(
            lambda request: requests.append(request) or (Path("report.json"),)
        )

        result = association.shadow_associate_speakers_command(
            youtube_video_id=None,
            all_eligible=False,
            unattempted_only=False,
            neighborhood_profile_id=[3, 7],
            include_profiled=True,
            limit=5,
            plan_only=True,
            minimum_profile_members=3,
            maximum_exemplars=4,
            minimum_same_exemplars=2,
            maximum_global_profiles=2,
            jobs=3,
            model_path=Path("model.onnx"),
            model_sha256="model-sha",
            policy_path=Path("policy.json"),
            evaluation_root=Path("evaluation"),
            cache_dir=Path("cache"),
            output_root=Path("output"),
            base_dir=Path("app-data"),
        )

        self.assertEqual((Path("report.json"),), result)
        self.assertEqual(1, len(requests))
        request = requests[0]
        self.assertEqual((3, 7), request.neighborhood_profile_ids)
        self.assertTrue(request.include_profiled)
        self.assertTrue(request.plan_only)
        self.assertEqual(3, request.jobs)
        self.assertEqual(Path("policy.json"), request.policy_path)


if __name__ == "__main__":
    unittest.main()
