from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.workflows.identity import association
from pastor_transcript_extractor.workflows.identity.association import (
    AssociationSpanExclusion,
    AssociationSpanInput,
    ShadowAssociationRequest,
    assess_association_candidate,
    prepare_association_candidate_spans,
    resolve_association_scope,
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


if __name__ == "__main__":
    unittest.main()
