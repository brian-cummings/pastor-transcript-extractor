from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.workflows.identity import association
from pastor_transcript_extractor.workflows.identity.association import (
    ShadowAssociationRequest,
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


if __name__ == "__main__":
    unittest.main()
