from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pastor_transcript_extractor.workflows.identity import association
from pastor_transcript_extractor.workflows.identity.association import (
    AssociationCentroidCandidateInput,
    AssociationSpanExclusion,
    AssociationSpanInput,
    ShadowAssociationRequest,
    assess_association_candidate,
    load_association_corpus_inventory,
    plan_association_profile_route,
    plan_pending_confirmation_routing,
    prepare_association_centroids,
    prepare_association_candidate_spans,
    resolve_association_scope,
    scan_association_candidates,
    validate_shadow_association_request,
)


class IdentityAssociationWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = ShadowAssociationRequest(
            youtube_video_id="video-1",
            all_eligible=False,
            unattempted_only=False,
            neighborhood_profile_ids=(),
            include_profiled=False,
            limit=None,
            plan_only=True,
            minimum_profile_members=3,
            maximum_exemplars=3,
            minimum_same_exemplars=2,
            maximum_global_profiles=1,
            jobs=2,
            model_path=Path("model.onnx"),
            model_sha256="model-sha",
            policy_path=Path("policy.json"),
            evaluation_root=Path("evaluation"),
            cache_dir=Path("cache"),
            output_root=Path("output"),
            base_dir=None,
        )

    def test_exactly_one_selection_mode_is_required(self) -> None:
        invalid = (
            replace(self.request, youtube_video_id=None),
            replace(self.request, all_eligible=True),
            replace(self.request, neighborhood_profile_ids=(3,)),
        )
        for request in invalid:
            with self.subTest(request=request), self.assertRaisesRegex(
                ValueError, "exactly one"
            ):
                validate_shadow_association_request(request)

    def test_unattempted_only_requires_all_eligible(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires --all-eligible"):
            validate_shadow_association_request(
                replace(self.request, unattempted_only=True)
            )

    def test_same_exemplar_requirement_cannot_exceed_comparison_cap(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            validate_shadow_association_request(
                replace(
                    self.request,
                    maximum_exemplars=2,
                    minimum_same_exemplars=3,
                )
            )

    def test_corpus_scope_reports_inventory_and_observed_videos(self) -> None:
        videos = {
            1: SimpleNamespace(id=1),
            2: SimpleNamespace(id=2),
        }
        result = resolve_association_scope(
            replace(
                self.request,
                youtube_video_id=None,
                all_eligible=True,
            ),
            database=SimpleNamespace(),
            videos_by_id=videos,
            current_observation_by_video_id={2: SimpleNamespace(video_id=2)},
        )

        self.assertEqual((videos[2],), result.videos)
        self.assertEqual(2, result.database_video_count)
        self.assertEqual(1, result.observed_video_count)
        self.assertTrue(result.inventory_reported)

    def test_corpus_inventory_keeps_latest_observation_and_explicit_names(
        self,
    ) -> None:
        videos = (
            SimpleNamespace(id=1, source_id=10),
            SimpleNamespace(id=2, source_id=20),
        )
        observations = (
            SimpleNamespace(id=3, video_id=1),
            SimpleNamespace(id=5, video_id=1),
            SimpleNamespace(id=4, video_id=2),
        )
        claims = (
            SimpleNamespace(
                observation_id=5,
                explicit_speaker_attribution=True,
                normalized_name=" pastor ",
            ),
            SimpleNamespace(
                observation_id=4,
                explicit_speaker_attribution=False,
                normalized_name="ignored",
            ),
        )
        database = SimpleNamespace(
            list_videos=lambda: videos,
            list_speaker_observations=lambda: observations,
            list_speaker_name_claims=lambda: claims,
        )

        inventory = load_association_corpus_inventory(database)

        self.assertEqual(5, inventory.current_observation_by_video_id[1].id)
        self.assertEqual({1: 10, 2: 20}, inventory.source_id_by_video_id)
        self.assertEqual(
            frozenset({"pastor"}),
            inventory.candidate_names_by_observation[5],
        )
        self.assertNotIn(4, inventory.candidate_names_by_observation)

    def test_neighborhood_scope_preserves_resolver_order(self) -> None:
        videos = {
            3: SimpleNamespace(id=3),
            7: SimpleNamespace(id=7),
        }
        with patch.object(
            association,
            "profile_neighborhood_video_ids",
            return_value=(7, 3),
        ):
            result = resolve_association_scope(
                replace(
                    self.request,
                    youtube_video_id=None,
                    neighborhood_profile_ids=(11,),
                ),
                database=SimpleNamespace(),
                videos_by_id=videos,
                current_observation_by_video_id={},
            )

        self.assertEqual((videos[7], videos[3]), result.videos)
        self.assertFalse(result.inventory_reported)

    def test_unattempted_scope_collects_persisted_fingerprints(self) -> None:
        video = SimpleNamespace(id=3)
        database = SimpleNamespace(get_video_by_youtube_id=lambda _value: video)
        with patch.object(
            association,
            "load_identity_association_attempts",
            return_value={
                3: (
                    {"observation_fingerprint": "attempted"},
                    {"observation_fingerprint": None},
                )
            },
        ):
            result = resolve_association_scope(
                replace(
                    self.request,
                    youtube_video_id=None,
                    all_eligible=True,
                    unattempted_only=True,
                ),
                database=database,
                videos_by_id={3: video},
                current_observation_by_video_id={3: SimpleNamespace()},
            )

        self.assertEqual(
            frozenset({"attempted"}),
            result.attempted_observation_fingerprints,
        )

    def test_attempted_candidate_is_excluded_before_eligibility(self) -> None:
        observation = SimpleNamespace(input_fingerprint="attempted")
        database = SimpleNamespace(
            get_latest_speaker_observation_for_video=lambda _id: observation
        )
        with patch.object(
            association, "assess_automatic_speaker_observation"
        ) as assess:
            result = assess_association_candidate(
                database,
                SimpleNamespace(id=7),
                unattempted_only=True,
                attempted_observation_fingerprints=frozenset({"attempted"}),
                include_profiled=False,
                verification_cache=object(),
            )

        self.assertEqual("association_already_attempted", result.exclusion_reason)
        self.assertIsNone(result.admission_stage)
        assess.assert_not_called()

    def test_reviewed_exclusion_retains_admission_evidence(self) -> None:
        observation = SimpleNamespace(id=11)
        media = SimpleNamespace(content_sha256="media-sha")
        eligibility = SimpleNamespace(
            eligible=True,
            observation=observation,
            media_artifact=media,
            reason_code="eligible",
        )
        database = SimpleNamespace(
            list_effective_profile_ids_for_observation=lambda _id: (),
            get_effective_observation_review_action=lambda _id: "multi_speaker",
        )
        with patch.object(
            association,
            "assess_automatic_speaker_observation",
            return_value=eligibility,
        ):
            result = assess_association_candidate(
                database,
                SimpleNamespace(id=7),
                unattempted_only=False,
                attempted_observation_fingerprints=frozenset(),
                include_profiled=False,
                verification_cache=object(),
            )

        self.assertEqual("reviewed_multi_speaker", result.exclusion_reason)
        self.assertEqual("observation_review_filter", result.admission_stage)
        self.assertEqual("media-sha", result.admission_media_sha256)

    def test_candidate_requires_second_verified_media_assessment(self) -> None:
        observation = SimpleNamespace(id=11)
        media = SimpleNamespace(
            content_sha256="verified-sha",
            artifact_path="audio.wav",
        )
        metadata = SimpleNamespace(
            eligible=True,
            observation=observation,
            media_artifact=None,
            reason_code="eligible",
        )
        verified = SimpleNamespace(
            eligible=True,
            observation=observation,
            media_artifact=media,
            reason_code="eligible",
        )
        database = SimpleNamespace(
            list_effective_profile_ids_for_observation=lambda _id: (),
            get_effective_observation_review_action=lambda _id: None,
        )
        with patch.object(
            association,
            "assess_automatic_speaker_observation",
            side_effect=(metadata, verified),
        ) as assess:
            result = assess_association_candidate(
                database,
                SimpleNamespace(id=7),
                unattempted_only=False,
                attempted_observation_fingerprints=frozenset(),
                include_profiled=False,
                verification_cache=object(),
            )

        self.assertTrue(result.admitted)
        self.assertEqual(Path("audio.wav"), result.audio_path)
        self.assertEqual(2, assess.call_count)
        self.assertFalse(assess.call_args_list[0].kwargs["verify_media"])
        self.assertTrue(assess.call_args_list[1].kwargs["verify_media"])

    def test_candidate_scan_preserves_order_reasons_and_progress(self) -> None:
        videos = tuple(SimpleNamespace(id=value) for value in (1, 2, 3))
        excluded = association.AssociationCandidateAssessment(
            videos[0], None, None, "reviewed_multi_speaker", None, None
        )
        eligibility_two = SimpleNamespace(
            observation=SimpleNamespace(id=2),
            media_artifact=SimpleNamespace(content_sha256="sha-2"),
        )
        eligibility_three = SimpleNamespace(
            observation=SimpleNamespace(id=3),
            media_artifact=SimpleNamespace(content_sha256="sha-3"),
        )
        admitted = (
            association.AssociationCandidateAssessment(
                videos[1], eligibility_two, Path("2.wav"), None, None, None
            ),
            association.AssociationCandidateAssessment(
                videos[2], eligibility_three, Path("3.wav"), None, None, None
            ),
        )
        exclusions = []
        remembered = []
        progress = []
        with patch.object(
            association,
            "assess_association_candidate",
            side_effect=(excluded, *admitted),
        ):
            result = scan_association_candidates(
                SimpleNamespace(),
                videos,
                unattempted_only=False,
                attempted_observation_fingerprints=frozenset(),
                include_profiled=False,
                verification_cache=object(),
                remember_verified_source=lambda path, sha: remembered.append(
                    (path, sha)
                ),
                exclusion_callback=exclusions.append,
                progress_callback=lambda *values: progress.append(values),
            )

        self.assertEqual([2, 3], [item.video.id for item in result.span_inputs])
        self.assertEqual({"reviewed_multi_speaker": 1}, result.exclusion_counts)
        self.assertEqual([excluded], exclusions)
        self.assertEqual(
            [(Path("2.wav"), "sha-2"), (Path("3.wav"), "sha-3")],
            remembered,
        )
        self.assertEqual([(1, 3, 0, 0), (3, 3, 1, 1)], progress)

    def test_span_preparation_preserves_order_and_target_limit(self) -> None:
        inputs = tuple(
            AssociationSpanInput(
                SimpleNamespace(id=value),
                SimpleNamespace(observation=SimpleNamespace(id=value)),
                Path(f"{value}.wav"),
            )
            for value in (1, 2, 3)
        )
        progress = []
        result = prepare_association_candidate_spans(
            inputs,
            jobs=2,
            target_count=2,
            prepare_spans=lambda item: ((f"span-{item.video.id}",), None),
            progress_callback=lambda completed, total, eligible: progress.append(
                (completed, total, eligible)
            ),
        )

        self.assertEqual(
            [1, 2],
            [candidate.input.video.id for candidate in result.candidates],
        )
        self.assertEqual([], list(result.exclusions))
        self.assertEqual([(2, 3, 2)], progress)

    def test_span_preparation_keeps_failure_reasons_and_order(self) -> None:
        inputs = tuple(
            AssociationSpanInput(
                SimpleNamespace(id=value),
                SimpleNamespace(observation=SimpleNamespace(id=value)),
                Path(f"{value}.wav"),
            )
            for value in (1, 2, 3)
        )

        def prepare(item):
            if item.video.id == 1:
                return (), None
            if item.video.id == 2:
                raise RuntimeError("activity failed")
            return (("span-3",), {"selected": True})

        result = prepare_association_candidate_spans(
            inputs,
            jobs=3,
            target_count=None,
            prepare_spans=prepare,
        )

        self.assertEqual(
            ["speech_grounded_spans_unavailable", "activity failed"],
            [exclusion.reason for exclusion in result.exclusions],
        )
        self.assertEqual(
            [3], [candidate.input.video.id for candidate in result.candidates]
        )
        self.assertEqual(
            [1, 2, 3], [outcome.input.video.id for outcome in result.outcomes]
        )
        self.assertEqual(
            [True, True, False],
            [
                isinstance(outcome, AssociationSpanExclusion)
                for outcome in result.outcomes
            ],
        )
        self.assertEqual(
            {"selected": True}, result.candidates[0].span_selection
        )

    def test_profile_route_plan_preserves_inputs_and_evidence(self) -> None:
        profile = SimpleNamespace(
            profile_id=8,
            review_ready=True,
            shadow_blockers=(),
        )
        exemplar = SimpleNamespace(
            profile_id=8,
            observation=SimpleNamespace(id=80, video_id=800),
        )
        usable_profiles = ((profile, (exemplar,)),)
        routing = SimpleNamespace(
            profiles=usable_profiles,
            route="source_local",
            exhaustive=False,
            priority_profile_ids=(8,),
            shortlisted_profile_ids=(8,),
            total_routable_profiles=1,
            confirmation_priority_profile_ids=(8,),
            candidate_funnel={"retrieval_candidates": []},
        )
        database = SimpleNamespace(
            list_effective_profile_ids_for_observation=lambda _id: (),
            resolve_speaker_profile_id=lambda profile_id: profile_id,
        )
        video = SimpleNamespace(id=7, source_id=3, title="A title")
        observation = SimpleNamespace(id=11)

        with (
            patch.object(
                association,
                "title_byline_selection_hint",
                return_value="title name",
            ),
            patch.object(
                association,
                "select_routed_association_profiles",
                return_value=usable_profiles,
            ) as legacy_route,
            patch.object(
                association,
                "select_staged_association_profiles",
                return_value=routing,
            ) as staged_route,
        ):
            plan = plan_association_profile_route(
                database,
                video=video,
                observation=observation,
                readiness=(profile,),
                usable_profiles=usable_profiles,
                eligible_exemplars=(exemplar,),
                videos_by_id={7: video},
                observations_by_id={11: observation},
                source_id_by_video_id={800: 3},
                candidate_names_by_observation={11: ("zeta", "alpha")},
                minimum_profile_members=3,
                maximum_exemplars=3,
                minimum_same_exemplars=2,
                maximum_global_profiles=1,
                candidate_centroid=(1.0,),
                exemplar_centroids={80: (1.0,)},
                confirmation_profile_ids=frozenset({8}),
            )

        self.assertEqual(("alpha", "zeta"), plan.explicit_candidate_names)
        self.assertEqual(1, plan.exhaustive_profile_comparison_count)
        self.assertEqual(usable_profiles, plan.candidate_usable_profiles)
        legacy_route.assert_called_once()
        self.assertEqual(
            ["alpha", "title name", "zeta"],
            legacy_route.call_args.kwargs["candidate_normalized_names"],
        )
        self.assertEqual(
            frozenset({8}),
            staged_route.call_args.kwargs[
                "confirmation_priority_profile_ids"
            ],
        )
        payload = plan.routing_payload
        self.assertEqual([8], payload["confirmation_priority_profile_ids"])
        self.assertEqual(
            {
                "leave_one_out_applied": False,
                "hidden_effective_profile_ids": [],
                "membership_used_as_routing_evidence": False,
            },
            payload["candidate_funnel"]["retrospective_evaluation"],
        )
        self.assertEqual(
            ["alpha", "zeta"],
            payload["candidate_funnel"]["candidate_routing_inputs"][
                "explicit_normalized_names"
            ],
        )

    def test_profile_route_plan_reselects_leave_one_out_exemplars(self) -> None:
        profile = SimpleNamespace(profile_id=8, review_ready=True)
        adjusted = SimpleNamespace(
            profile_id=8,
            review_ready=True,
            shadow_blockers=(),
        )
        exemplar = SimpleNamespace(
            profile_id=8,
            observation=SimpleNamespace(id=80, video_id=800),
        )
        routing = SimpleNamespace(
            profiles=((adjusted, (exemplar,)),),
            route="global",
            exhaustive=True,
            priority_profile_ids=(),
            shortlisted_profile_ids=(8,),
            total_routable_profiles=1,
            confirmation_priority_profile_ids=(),
            candidate_funnel=None,
        )
        database = SimpleNamespace(
            list_effective_profile_ids_for_observation=lambda _id: (18,),
            resolve_speaker_profile_id=lambda _id: 8,
        )
        with (
            patch.object(
                association,
                "leave_one_out_profile_readiness",
                return_value=adjusted,
            ) as leave_one_out,
            patch.object(
                association,
                "select_profile_exemplars",
                return_value=(exemplar, exemplar),
            ) as select_exemplars,
            patch.object(
                association,
                "select_routed_association_profiles",
                return_value=(),
            ),
            patch.object(
                association,
                "select_staged_association_profiles",
                return_value=routing,
            ),
        ):
            plan = plan_association_profile_route(
                database,
                video=SimpleNamespace(id=7, source_id=3, title="Title"),
                observation=SimpleNamespace(id=11),
                readiness=(profile,),
                usable_profiles=(),
                eligible_exemplars=(exemplar,),
                videos_by_id={},
                observations_by_id={},
                source_id_by_video_id={},
                candidate_names_by_observation={},
                minimum_profile_members=3,
                maximum_exemplars=3,
                minimum_same_exemplars=2,
                maximum_global_profiles=1,
                candidate_centroid=(1.0,),
                exemplar_centroids={80: (1.0,)},
            )

        leave_one_out.assert_called_once()
        select_exemplars.assert_called_once()
        self.assertEqual(
            ((adjusted, (exemplar, exemplar)),),
            plan.candidate_usable_profiles,
        )
        self.assertEqual(
            {
                "leave_one_out_applied": True,
                "hidden_effective_profile_ids": [8],
                "membership_used_as_routing_evidence": False,
            },
            plan.routing_payload["candidate_funnel"][
                "retrospective_evaluation"
            ],
        )

    def test_centroid_preparation_deduplicates_and_isolates_failures(self) -> None:
        exemplar_one = SimpleNamespace(
            observation=SimpleNamespace(id=80),
        )
        exemplar_one_duplicate = SimpleNamespace(
            observation=SimpleNamespace(id=80),
        )
        exemplar_two = SimpleNamespace(
            observation=SimpleNamespace(id=81),
        )
        candidates = tuple(
            AssociationCentroidCandidateInput(
                SimpleNamespace(id=value),
                SimpleNamespace(
                    observation=SimpleNamespace(id=value, video_id=value * 10),
                    media_artifact=SimpleNamespace(),
                ),
            )
            for value in (1, 2, 3)
        )
        progress = []

        def build_candidate(candidate):
            if candidate.video.id == 2:
                raise ValueError("bad centroid")
            return (float(candidate.video.id),)

        result = prepare_association_centroids(
            (exemplar_one, exemplar_one_duplicate, exemplar_two),
            candidates,
            jobs=2,
            build_exemplar_centroid=lambda exemplar: (
                float(exemplar.observation.id),
            ),
            build_candidate_centroid=build_candidate,
            candidate_progress=lambda index, total: progress.append(
                (index, total)
            ),
        )

        self.assertEqual(
            {80: (80.0,), 81: (81.0,)},
            result.exemplar_centroids,
        )
        self.assertEqual(
            [1, 2, 3],
            [outcome.observation_id for outcome in result.candidate_outcomes],
        )
        self.assertEqual(
            [None, "ValueError:bad centroid", None],
            [outcome.failure for outcome in result.candidate_outcomes],
        )
        self.assertEqual((3.0,), result.candidate_outcomes[2].centroid)
        self.assertEqual([(1, 3), (2, 3), (3, 3)], progress)

    def test_centroid_preparation_skips_incomplete_candidate(self) -> None:
        candidate = AssociationCentroidCandidateInput(
            SimpleNamespace(id=1),
            SimpleNamespace(observation=None, media_artifact=None),
        )
        build_candidate = Mock()

        result = prepare_association_centroids(
            (),
            (candidate,),
            jobs=1,
            build_exemplar_centroid=lambda _exemplar: (),
            build_candidate_centroid=build_candidate,
        )

        build_candidate.assert_not_called()
        self.assertIsNone(result.candidate_outcomes[0].observation_id)
        self.assertIsNone(result.candidate_outcomes[0].failure)

    def test_pending_confirmation_routing_requires_persisted_promotion(
        self,
    ) -> None:
        eligible = SimpleNamespace(
            profile_id=8,
            automatic_blockers=("discovery_candidate_unconfirmed",),
        )
        wrong_reason = SimpleNamespace(
            profile_id=9,
            automatic_blockers=("discovery_candidate_unconfirmed",),
        )
        already_confirmed = SimpleNamespace(
            profile_id=10,
            automatic_blockers=(),
        )
        usable_profiles = (
            (eligible, ("eligible-exemplar",)),
            (wrong_reason, ("wrong-exemplar",)),
            (already_confirmed, ("confirmed-exemplar",)),
        )
        database = SimpleNamespace(
            get_speaker_profile=lambda profile_id: SimpleNamespace(
                created_reason=(
                    association.DISCOVERY_PROFILE_REASON
                    if profile_id == 8
                    else "manual"
                )
            ),
            get_speaker_profile_discovery_promotion=lambda profile_id: (
                object() if profile_id == 8 else None
            ),
        )
        with patch.object(
            association,
            "plan_pending_discovery_confirmation_routes",
            return_value={21: (8,), 22: (8,)},
        ) as plan_routes:
            plan = plan_pending_confirmation_routing(
                database,
                usable_profiles,
                candidate_centroids={21: (1.0,)},
                candidate_video_ids={21: 210},
                exemplar_centroids={80: (1.0,)},
                candidates_per_profile=2,
            )

        self.assertEqual(((eligible, ("eligible-exemplar",)),), plan.profiles)
        self.assertEqual(frozenset({8}), plan.pending_profile_ids)
        self.assertEqual(frozenset({8}), plan.routed_profile_ids)
        self.assertEqual(2, plan.route_count)
        self.assertEqual(plan.profiles, plan_routes.call_args.args[0])
        self.assertEqual(
            2, plan_routes.call_args.kwargs["candidates_per_profile"]
        )


if __name__ == "__main__":
    unittest.main()
