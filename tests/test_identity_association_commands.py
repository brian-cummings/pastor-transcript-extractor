from __future__ import annotations

from pathlib import Path
import unittest

from pastor_transcript_extractor.commands.identity import association


class IdentityAssociationCommandTests(unittest.TestCase):
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
