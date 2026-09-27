from __future__ import annotations

from dataclasses import replace
import unittest

from pastor_transcript_extractor.workflows.identity.run import (
    IdentityWorkflowRequest,
    validate_identity_workflow_request,
)


class IdentityRunWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = IdentityWorkflowRequest(
            youtube_video_id=None,
            all_extractions=True,
            plan_only=False,
            skip_discovery=False,
            apply_automatic=False,
            apply_confirmations=False,
            apply_promotions=False,
            apply_machine_canary=False,
            machine_assignment_policy_path=None,
            review_prewarm_limit=24,
            base_dir=None,
            jobs=2,
        )

    def test_automatic_apply_enables_each_guarded_mutation(self) -> None:
        policy = validate_identity_workflow_request(
            replace(self.request, apply_automatic=True)
        )

        self.assertTrue(policy.apply_confirmations)
        self.assertTrue(policy.apply_promotions)
        self.assertTrue(policy.apply_machine_assignments)

    def test_plan_only_rejects_every_mutation_flag(self) -> None:
        for field in (
            "apply_automatic",
            "apply_confirmations",
            "apply_promotions",
            "apply_machine_canary",
        ):
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "registry mutation"
            ):
                validate_identity_workflow_request(
                    replace(self.request, plan_only=True, **{field: True})
                )

    def test_single_video_rejects_corpus_only_mutations(self) -> None:
        single_video = replace(
            self.request,
            youtube_video_id="video-1",
            all_extractions=False,
        )
        with self.assertRaisesRegex(ValueError, "promotion requires --all"):
            validate_identity_workflow_request(
                replace(single_video, apply_promotions=True)
            )
        with self.assertRaisesRegex(ValueError, "canary activation requires --all"):
            validate_identity_workflow_request(
                replace(single_video, apply_machine_canary=True)
            )

    def test_scope_and_resource_limits_are_validated(self) -> None:
        invalid = (
            (replace(self.request, youtube_video_id="video-1"), "exactly one"),
            (replace(self.request, review_prewarm_limit=-1), "cannot be negative"),
            (replace(self.request, jobs=0), "at least one"),
        )
        for request, message in invalid:
            with self.subTest(message=message), self.assertRaisesRegex(
                ValueError, message
            ):
                validate_identity_workflow_request(request)


if __name__ == "__main__":
    unittest.main()
