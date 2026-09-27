from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import Mock

from pastor_transcript_extractor.workflows.identity.finalization import (
    CoordinationStageRequest,
    run_coordination_stage,
)


class IdentityFinalizationWorkflowTests(unittest.TestCase):
    def test_coordination_is_always_shadow_only_with_pinned_inputs(self) -> None:
        coordinator = Mock(return_value="report")
        request = CoordinationStageRequest(
            youtube_video_id="video-1",
            all_extractions=False,
            discovery_report=Path("discovery.json"),
            discovery_root=Path("discovery"),
            model_sha256="model-sha",
            base_dir=Path("app-data"),
        )

        result = run_coordination_stage(request, coordinator=coordinator)

        self.assertEqual("report", result)
        options = coordinator.call_args.kwargs
        self.assertFalse(options["execute_shadow"])
        self.assertEqual("video-1", options["youtube_video_id"])
        self.assertEqual(Path("discovery.json"), options["discovery_report"])
        self.assertEqual("model-sha", options["model_sha256"])
        self.assertIsNone(options["output_root"])


if __name__ == "__main__":
    unittest.main()
