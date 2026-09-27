from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from pastor_transcript_extractor.workflows.identity import association_setup
from pastor_transcript_extractor.workflows.identity.association_setup import (
    initialize_shadow_association,
)


class IdentityAssociationSetupWorkflowTests(unittest.TestCase):
    def request(self, root: Path, *, plan_only: bool) -> SimpleNamespace:
        return SimpleNamespace(
            cache_dir=root / "cache",
            evaluation_root=root / "evaluation",
            policy_path=root / "policy.json",
            minimum_profile_members=3,
            plan_only=plan_only,
            model_path=root / "model.onnx",
            model_sha256="model-sha",
            output_root=root / "output",
        )

    def test_plan_only_setup_does_not_create_acoustic_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(association_setup, "Database", return_value="db"),
                patch.object(
                    association_setup,
                    "load_reviewed_speaker_evidence",
                    return_value="evidence",
                ),
                patch.object(
                    association_setup,
                    "load_shadow_policy",
                    return_value="policy",
                ),
                patch.object(
                    association_setup,
                    "assess_profile_association_readiness",
                    return_value=("ready",),
                ),
                patch.object(
                    association_setup, "SherpaOnnxEmbeddingBackend"
                ) as backend,
                patch.object(association_setup, "EmbeddingCache") as embeddings,
                patch.object(association_setup, "PairDiagnosticCache") as pairs,
            ):
                setup = initialize_shadow_association(
                    self.request(root, plan_only=True),
                    database_path=root / "app.db",
                )

        self.assertEqual(("ready",), setup.readiness)
        self.assertIsNone(setup.backend)
        self.assertIsNone(setup.embedding_cache)
        self.assertIsNone(setup.pair_diagnostic_cache)
        backend.assert_not_called()
        embeddings.assert_not_called()
        pairs.assert_not_called()

    def test_live_setup_primes_missing_pair_cache_with_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_dir = root / "output" / "candidate"
            report_dir.mkdir(parents=True)
            (report_dir / "report.json").write_text("{}", encoding="utf-8")
            pair_cache = Mock(primed=4)
            progress = []
            with (
                patch.object(association_setup, "Database", return_value="db"),
                patch.object(
                    association_setup,
                    "load_reviewed_speaker_evidence",
                    return_value="evidence",
                ),
                patch.object(
                    association_setup,
                    "load_shadow_policy",
                    return_value="policy",
                ),
                patch.object(
                    association_setup,
                    "assess_profile_association_readiness",
                    return_value=(),
                ),
                patch.object(
                    association_setup,
                    "SherpaOnnxEmbeddingBackend",
                    return_value="backend",
                ),
                patch.object(
                    association_setup,
                    "PairDiagnosticCache",
                    return_value=pair_cache,
                ),
            ):
                setup = initialize_shadow_association(
                    self.request(root, plan_only=False),
                    database_path=root / "app.db",
                    pair_cache_progress=lambda stage, count: progress.append(
                        (stage, count)
                    ),
                )

        self.assertEqual("backend", setup.backend)
        reports = pair_cache.prime_from_shadow_associations.call_args.args[0]
        self.assertEqual(1, len(reports))
        self.assertEqual([("starting", 1), ("complete", 4)], progress)


if __name__ == "__main__":
    unittest.main()
