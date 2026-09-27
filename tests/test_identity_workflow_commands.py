from __future__ import annotations

from pathlib import Path
import unittest

import typer

from pastor_transcript_extractor.commands.identity import workflow


class IdentityWorkflowCommandTests(unittest.TestCase):
    def test_command_builds_typed_workflow_request(self) -> None:
        requests = []
        workflow.configure_identity_workflow(requests.append)

        workflow.identity_run_command(
            youtube_video_id="video-1",
            all_extractions=False,
            plan_only=True,
            skip_discovery=False,
            apply_automatic=False,
            apply_confirmations=False,
            apply_promotions=False,
            apply_machine_canary=False,
            machine_assignment_policy=Path("policy.json"),
            review_prewarm_limit=0,
            jobs=3,
            base_dir=Path("app-data"),
        )

        self.assertEqual(1, len(requests))
        request = requests[0]
        self.assertEqual("video-1", request.youtube_video_id)
        self.assertTrue(request.plan_only)
        self.assertEqual(Path("policy.json"), request.machine_assignment_policy_path)
        self.assertEqual(0, request.review_prewarm_limit)
        self.assertEqual(3, request.jobs)

    def test_workflow_value_error_becomes_cli_parameter_error(self) -> None:
        def reject(_request) -> None:
            raise ValueError("unsafe combination")

        workflow.configure_identity_workflow(reject)

        with self.assertRaisesRegex(typer.BadParameter, "unsafe combination"):
            workflow.identity_run_command(
                youtube_video_id=None,
                all_extractions=True,
                plan_only=False,
                skip_discovery=False,
                apply_automatic=False,
                apply_confirmations=False,
                apply_promotions=False,
                apply_machine_canary=False,
                machine_assignment_policy=None,
                review_prewarm_limit=24,
                jobs=2,
                base_dir=None,
            )


if __name__ == "__main__":
    unittest.main()
