from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from pastor_transcript_extractor.workflows.identity.association import (
    ShadowAssociationRequest,
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


if __name__ == "__main__":
    unittest.main()
