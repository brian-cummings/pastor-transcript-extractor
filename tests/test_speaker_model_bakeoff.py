from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.speaker_model_bakeoff import (
    audit_model_files,
    audit_fixture_partitions,
    build_bakeoff_preflight,
    build_bakeoff_plan,
    evaluate_bakeoff,
    evaluate_experimental_policy_candidate,
    execute_bakeoff_plan,
    fixture_set_fingerprint,
    load_experimental_policy_candidate,
    load_bakeoff_manifest,
    stamp_bakeoff_result,
)


def fixture(
    pair_id: str,
    observation_a: str,
    observation_b: str,
    expected: str,
    *,
    partition: str | None = None,
    stratum: str = "coverage",
) -> dict:
    payload = {
        "schema_version": 1,
        "pair_id": pair_id,
        "review_status": "approved",
        "reviewer": "human",
        "reviewed_at": "2026-07-26T12:00:00Z",
        "expected_outcome": expected,
        "variation_tags": ["different_date"],
        "selection_manifest": {
            "selection_stratum": stratum,
            "source_relation": "same_source_family",
        },
        "observations": {
            "a": {
                "input_fingerprint": observation_a,
                "reviewed_spans": [
                    {"wav_sha256": "a" * 64},
                    {"wav_sha256": "b" * 64},
                ],
            },
            "b": {
                "input_fingerprint": observation_b,
                "reviewed_spans": [
                    {"wav_sha256": "c" * 64},
                    {"wav_sha256": "d" * 64},
                ],
            },
        },
    }
    if partition is not None:
        payload["evaluation_partition"] = partition
    return payload


def manifest_entry(stable_key: str, checksum_character: str, model_name: str) -> dict:
    return {
        "stable_key": stable_key,
        "backend": "fake-backend",
        "model_path": f"models/{model_name}",
        "model_sha256": checksum_character * 64,
        "runtime": {"package": "fake-runtime", "version": "1.2.3"},
        "source": {"url": "https://example.test/model"},
        "license": {
            "name": "Test-only",
            "url": "https://example.test/license",
            "verified": True,
        },
        "preprocessing": {
            "sample_rate_hz": 16000,
            "channels": 1,
            "span_duration_seconds": 12.0,
        },
    }


def result(model, pair_fixture: dict, outcome: str) -> dict:
    diagnostic = {
        "observations": {
            side: pair_fixture["observations"][side]["input_fingerprint"]
            for side in ("a", "b")
        },
        "spans": {
            side: list(pair_fixture["observations"][side]["reviewed_spans"])
            for side in ("a", "b")
        },
        "model": {
            "backend": model.backend,
            "model_name": model.model_name,
            "model_sha256": model.model_sha256,
            "runtime_version": model.runtime_version,
        },
        "policy": {"version": "reviewed-test-policy"},
        "outcome": outcome,
    }
    return stamp_bakeoff_result(diagnostic, model)


class SpeakerModelBakeoffTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def _write_manifest(self, entries: list[dict]) -> Path:
        path = self.root / "manifest.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "selection_status": "experimental_candidates",
                    "models": entries,
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_repository_manifest_is_valid_and_remains_experimental(self):
        repository_root = Path(__file__).resolve().parents[1]
        models = load_bakeoff_manifest(
            repository_root / "evaluation/speaker-pairs/bakeoff-models.json"
        )

        self.assertEqual(
            {
                "3dspeaker-campplus-en-voxceleb",
                "3dspeaker-eres2net-en-voxceleb",
                "wespeaker-resnet34-lm-en-voxceleb",
            },
            {model.stable_key for model in models},
        )

    def test_manifest_requires_license_provenance_and_exact_execution_inputs(self):
        entry = manifest_entry("model-a", "1", "model.onnx")
        models = load_bakeoff_manifest(self._write_manifest([entry]))

        self.assertEqual(1, len(models))
        self.assertEqual(64, len(models[0].execution_fingerprint))

        entry["license"]["verified"] = False
        with self.assertRaisesRegex(ValueError, "verified license"):
            load_bakeoff_manifest(self._write_manifest([entry]))

    def test_manifest_rejects_duplicate_acoustic_executions(self):
        first = manifest_entry("model-a", "1", "model.onnx")
        second = {**first, "stable_key": "model-alias"}

        with self.assertRaisesRegex(ValueError, "same acoustic execution"):
            load_bakeoff_manifest(self._write_manifest([first, second]))

    def test_plan_is_deterministic_and_model_fingerprint_qualified(self):
        models = load_bakeoff_manifest(
            self._write_manifest(
                [
                    manifest_entry("model-a", "1", "a.onnx"),
                    manifest_entry("model-b", "2", "b.onnx"),
                ]
            )
        )
        fixtures = [fixture("pair-1", "obs-a", "obs-b", "same_speaker")]

        first = build_bakeoff_plan(fixtures, models, result_root=Path("runs"))
        second = build_bakeoff_plan(fixtures, models, result_root=Path("runs"))
        result_paths = [job["result_path"] for job in first["jobs"]]

        self.assertEqual(first, second)
        self.assertEqual(2, len(set(result_paths)))
        self.assertTrue(all("--" in path for path in result_paths))
        self.assertFalse(first["registry_mutation_allowed"])
        self.assertFalse(first["winner_selection_allowed"])

    def test_model_file_audit_distinguishes_missing_mismatch_and_verified(self):
        model_directory = self.root / "models"
        model_directory.mkdir()
        verified_bytes = b"verified model"
        (model_directory / "a.onnx").write_bytes(verified_bytes)
        (model_directory / "b.onnx").write_bytes(b"wrong model")
        entries = [
            {
                **manifest_entry("model-a", "1", "a.onnx"),
                "model_path": "models/a.onnx",
                "model_sha256": hashlib.sha256(verified_bytes).hexdigest(),
            },
            {
                **manifest_entry("model-b", "2", "b.onnx"),
                "model_path": "models/b.onnx",
            },
            {
                **manifest_entry("model-c", "3", "c.onnx"),
                "model_path": "models/c.onnx",
            },
        ]
        models = load_bakeoff_manifest(self._write_manifest(entries))

        audit = audit_model_files(models, repository_root=self.root)

        self.assertEqual(
            ["verified", "checksum_mismatch", "missing"],
            [entry["status"] for entry in audit["models"]],
        )
        self.assertFalse(audit["all_models_verified"])

    def test_preflight_combines_model_runtime_partition_and_plan_checks(self):
        model_bytes = b"verified model"
        model_path = self.root / "models" / "a.onnx"
        model_path.parent.mkdir()
        model_path.write_bytes(model_bytes)
        entry = {
            **manifest_entry("model-a", "1", "a.onnx"),
            "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
        }
        models = load_bakeoff_manifest(self._write_manifest([entry]))
        fixtures = [
            fixture(
                "pair-1",
                "obs-a",
                "obs-b",
                "same_speaker",
                partition="development",
            )
        ]

        preflight = build_bakeoff_preflight(
            fixtures,
            models,
            repository_root=self.root,
            result_root=self.root / "runs",
            installed_versions={"fake-runtime": "1.2.3"},
        )

        self.assertTrue(preflight["execution_allowed"])
        self.assertEqual([], preflight["blocking_reasons"])
        self.assertEqual(1, len(preflight["plan"]["jobs"]))

    def test_execute_plan_reuses_checksum_verified_namespaced_result(self):
        models = load_bakeoff_manifest(
            self._write_manifest([manifest_entry("model-a", "1", "a.onnx")])
        )
        reviewed = fixture("pair-1", "obs-a", "obs-b", "same_speaker")
        plan = build_bakeoff_plan(
            [reviewed],
            models,
            result_root=self.root / "runs",
        )
        calls = 0

        def analyze(pair_fixture, model):
            nonlocal calls
            calls += 1
            diagnostic = result(model, pair_fixture, "insufficient_evidence")
            diagnostic.pop("bakeoff_execution")
            diagnostic["metrics"] = {
                "cross": {"median": 0.8},
            }
            return diagnostic

        first = execute_bakeoff_plan(
            [reviewed],
            models,
            plan=plan,
            analyze_fixture=analyze,
        )
        second = execute_bakeoff_plan(
            [reviewed],
            models,
            plan=plan,
            analyze_fixture=analyze,
        )

        self.assertEqual(1, calls)
        self.assertEqual(1, first["jobs_completed"])
        self.assertEqual(0, first["jobs_replayed"])
        self.assertEqual(0, second["jobs_completed"])
        self.assertEqual(1, second["jobs_replayed"])
        self.assertEqual(
            1,
            second["report"]["models"]["model-a"]["raw_similarity"][
                "cross_median_by_expected_outcome"
            ]["same_speaker"]["count"],
        )

    def test_experimental_policy_is_fixture_bound_and_cannot_imply_approval(self):
        models = load_bakeoff_manifest(
            self._write_manifest([manifest_entry("model-a", "1", "a.onnx")])
        )
        same = fixture("pair-1", "obs-a", "obs-b", "same_speaker")
        different = fixture("pair-2", "obs-c", "obs-d", "different_speaker")
        fixtures = [same, different]
        policy_path = self.root / "candidate.json"
        policy_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "review_status": "experimental_candidate",
                    "approval_allowed": False,
                    "registry_mutation_allowed": False,
                    "candidate_id": "candidate-v1",
                    "model": {
                        "stable_key": models[0].stable_key,
                        "execution_fingerprint": models[0].execution_fingerprint,
                    },
                    "derivation": {
                        "scope": "development_with_legacy_unassigned",
                        "fixture_fingerprint": fixture_set_fingerprint(fixtures),
                    },
                    "policy": {
                        "version": "candidate-v1",
                        "min_valid_spans": 2,
                        "min_within_median": 0.7,
                        "same_min_cross_p10": 0.6,
                        "same_min_cross_median": 0.7,
                        "different_max_cross_p90": 0.3,
                    },
                }
            ),
            encoding="utf-8",
        )
        candidate, model = load_experimental_policy_candidate(
            policy_path,
            fixtures=fixtures,
            models=models,
        )
        same_result = result(model, same, "insufficient_evidence")
        same_result["metrics"] = {
            "within_a": {"median": 0.9},
            "within_b": {"median": 0.9},
            "cross": {"p10": 0.8, "median": 0.8, "p90": 0.9},
        }
        different_result = result(model, different, "insufficient_evidence")
        different_result["metrics"] = {
            "within_a": {"median": 0.9},
            "within_b": {"median": 0.9},
            "cross": {"p10": 0.1, "median": 0.1, "p90": 0.2},
        }

        report = evaluate_experimental_policy_candidate(
            fixtures,
            [same_result, different_result],
            candidate,
            model,
        )

        self.assertEqual(1, report["evaluation"]["counts"]["true_same"])
        self.assertEqual(1, report["evaluation"]["counts"]["true_different"])
        self.assertFalse(report["evaluation"]["gates"]["promotion_ready"])
        self.assertTrue(
            report["evaluation"]["gates"]["experimental_policy_unapproved"]
        )
        self.assertFalse(report["approval_allowed"])
        self.assertFalse(report["registry_mutation_allowed"])
        with self.assertRaisesRegex(ValueError, "fixture set has changed"):
            load_experimental_policy_candidate(
                policy_path,
                fixtures=[same],
                models=models,
            )

    def test_comparison_keeps_errors_abstention_and_slices_visible(self):
        models = load_bakeoff_manifest(
            self._write_manifest(
                [
                    manifest_entry("model-a", "1", "a.onnx"),
                    manifest_entry("model-b", "2", "b.onnx"),
                ]
            )
        )
        same = fixture(
            "pair-1",
            "obs-a",
            "obs-b",
            "same_speaker",
            partition="development",
            stratum="same_candidate",
        )
        different = fixture(
            "pair-2",
            "obs-a",
            "obs-c",
            "different_speaker",
            partition="development",
            stratum="hard_negative",
        )
        results = [
            result(models[0], same, "same_speaker"),
            result(models[0], different, "different_speaker"),
            result(models[1], same, "insufficient_evidence"),
            result(models[1], different, "same_speaker"),
        ]

        report = evaluate_bakeoff(
            [same, different],
            results,
            models,
            required_decisions_per_outcome=1,
            required_variation_tags=("different_date",),
        )

        model_a = report["models"]["model-a"]["evaluation"]
        model_b = report["models"]["model-b"]["evaluation"]
        self.assertEqual(1, model_a["counts"]["true_same"])
        self.assertEqual(1, model_a["counts"]["true_different"])
        self.assertEqual(1, model_b["counts"]["insufficient_evidence"])
        self.assertEqual(1, model_b["counts"]["false_same"])
        self.assertEqual(1, report["fixture_inventory"]["reused_observation_count"])
        self.assertEqual(
            {"correct": 1},
            report["models"]["model-a"]["slices"]["by_selection_stratum"]["hard_negative"],
        )
        self.assertEqual(
            {"correct": 2},
            report["models"]["model-a"]["slices"]["by_source_relation"][
                "same_source_family"
            ],
        )
        self.assertFalse(report["comparison"]["winner_selected"])
        self.assertFalse(report["registry_mutation_allowed"])

    def test_partition_audit_detects_observation_leakage_and_missing_assignments(self):
        development = fixture(
            "pair-1", "obs-a", "obs-b", "same_speaker", partition="development"
        )
        held_out = fixture(
            "pair-2", "obs-a", "obs-c", "different_speaker", partition="held_out"
        )
        unassigned = fixture("pair-3", "obs-d", "obs-e", "same_speaker")

        audit = audit_fixture_partitions([development, held_out, unassigned])

        self.assertEqual(["pair-3"], audit["unassigned_pairs"])
        self.assertEqual("obs-a", audit["observation_leaks"][0]["observation_fingerprint"])
        self.assertFalse(audit["held_out_evaluation_safe"])

    def test_unmanifested_model_result_is_rejected(self):
        models = load_bakeoff_manifest(
            self._write_manifest([manifest_entry("model-a", "1", "a.onnx")])
        )
        reviewed = fixture("pair-1", "obs-a", "obs-b", "same_speaker")
        unmanifested = result(models[0], reviewed, "same_speaker")
        unmanifested["model"]["model_sha256"] = "f" * 64

        with self.assertRaisesRegex(ValueError, "match exactly one"):
            evaluate_bakeoff([reviewed], [unmanifested], models)


if __name__ == "__main__":
    unittest.main()
