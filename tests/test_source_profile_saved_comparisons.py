from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.source_profile_consolidation import (
    load_saved_source_profile_comparisons,
    source_profile_candidates,
)
from pastor_transcript_extractor.speaker_pair_diagnostics import DecisionPolicy, ModelSpec
from pastor_transcript_extractor.speaker_registry import create_anonymous_profile, attach_reviewed_observation
from pastor_transcript_extractor.reviewed_speaker_evidence import ReviewedSpeakerEvidence
from pastor_transcript_extractor.storage import Database


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SavedSourceProfileComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = build_paths(Path(self.temp.name) / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.source = self.database.add_source("https://example.test/source", SourceType.CHANNEL, pastor_id=None)
        self.observations = {}
        self.profile_members = []
        for p in range(2):
            profile = create_anonymous_profile(self.database, reviewer="brian", reason="Reviewed", review_event_key=f"profile-{p}")
            members = []
            for i in range(2):
                key = f"p{p}-v{i}"
                video = self.database.add_video(
                    source_id=self.source.id, pastor_id=None, youtube_video_id=key,
                    title=key, url=f"https://example.test/{key}", status=VideoStatus.EXTRACTED,
                )
                extraction = self.database.add_extraction_result(
                    video_id=video.id, version=1, proposed_text_path=f"{key}.md", proposed_json_path=f"{key}.json",
                )
                observation = self.database.add_speaker_observation(
                    video_id=video.id, extraction_result_id=extraction.id,
                    role="principal_speaker_candidate", multiplicity_state="unknown",
                    start_seconds=100, end_seconds=1000, artifact_path=f"{key}.speaker.json",
                    content_sha256=digest(key), extractor_version="speaker_evidence_v1", input_fingerprint=digest(f"observation-{key}"),
                )
                attach_reviewed_observation(
                    self.database, profile_id=profile.id, observation_id=observation.id,
                    reviewer="brian", reason="Reviewed", review_event_key=f"attach-{key}",
                )
                self.observations[observation.id] = observation
                members.append(observation)
            self.profile_members.append(members)
        evidence = ReviewedSpeakerEvidence({}, {}, {}, {}, 0)
        self.candidates, _ = source_profile_candidates(self.database, evidence, source_id=self.source.id, exemplars_per_profile=2)
        self.model = ModelSpec("sherpa-onnx", "model.onnx", "f" * 64, "test")
        self.policy = DecisionPolicy("test-policy", 5, 0.7, 0.6, 0.7, 0.3)
        self.policy_path = self.paths.root / "policy.json"
        self.policy_path.write_text(json.dumps({**asdict(self.policy), "review_status": "approved"}))
        self.policy_fingerprint = hashlib.sha256(self.policy_path.read_bytes()).hexdigest()
        self.association_root = self.paths.evaluation / "speaker-associations/shadow-runs"

    def _eligibility(self, database, video_id, *, observation_id, verify_media):
        self.assertFalse(verify_media)
        observation = self.observations[observation_id]
        return SimpleNamespace(
            eligible=True, reason_code="eligible", observation=observation,
            media_artifact=SimpleNamespace(content_sha256=digest(f"audio-{observation.id}")),
        )

    def _comparison(self, a, b, outcome="same_speaker"):
        cross = {"p10": 0.75, "median": 0.8, "p90": 0.85}
        if outcome == "different_speaker":
            cross = {"p10": 0.1, "median": 0.15, "p90": 0.2}
        spans = {}
        for label, observation in (("a", a), ("b", b)):
            spans[label] = [
                {"start_seconds": 100 + i * 12, "end_seconds": 112 + i * 12,
                 "observation_fingerprint": observation.input_fingerprint,
                 "wav_sha256": digest(f"span-{observation.id}-{i}")}
                for i in range(5)
            ]
        return {
            "schema_version": 1, "registry_mutation_allowed": False,
            "analyzer_version": "speaker_pair_diagnostic_v1", "model": asdict(self.model),
            "policy": asdict(self.policy), "policy_version": self.policy.version,
            "observations": {"a": a.input_fingerprint, "b": b.input_fingerprint},
            "spans": spans,
            "metrics": {"within_a": {"median": 0.8}, "within_b": {"median": 0.8}, "cross": cross},
            "outcome": outcome, "reason": "approved_policy_same_band" if outcome == "same_speaker" else "approved_policy_different_band",
            "exemplar_observation_id": b.id, "exemplar_fingerprint": b.input_fingerprint,
            "exemplar_normalized_audio_sha256": digest(f"audio-{b.id}"),
        }

    def _payload(self, a, comparisons):
        return {
            "schema_version": 1,
            "artifact_kind": "speaker_profile_shadow_association", "shadow_mode": True,
            "registry_mutation_allowed": False, "model_fingerprint": self.model.fingerprint,
            "policy": {"artifact_sha256": self.policy_fingerprint},
            "candidate": {"observation_id": a.id, "input_fingerprint": a.input_fingerprint,
                          "normalized_audio_sha256": digest(f"audio-{a.id}")},
            # The pack version/snapshot is deliberately old; the compatible
            # individual diagnostic retains its own exact contract.
            "association_version": "historical-pack", "profiles": [{"comparisons": comparisons}],
        }

    def _write(self, a, payload, name="snapshot"):
        payload = deepcopy(payload)
        payload["result_sha256"] = digest(payload)
        directory = self.association_root / a.input_fingerprint[:16]
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.json"
        path.write_text(json.dumps(payload))
        return path

    def _load(self):
        with patch("pastor_transcript_extractor.source_profile_consolidation.assess_automatic_speaker_observation", side_effect=self._eligibility):
            return load_saved_source_profile_comparisons(
                self.database, self.candidates, association_root=self.association_root,
                model=asdict(self.model), policy=self.policy, policy_fingerprint=self.policy_fingerprint,
            )

    def test_historical_pack_leaf_reuses_exact_diagnostic_with_receipts(self):
        a, b = self.profile_members[0][0], self.profile_members[1][0]
        path = self._write(a, self._payload(a, [self._comparison(a, b)]))
        loaded = self._load()
        result = loaded.comparisons[(a.id, b.id)]
        self.assertEqual("same_speaker", result["outcome"])
        self.assertEqual(str(path), result["saved_evidence"][0]["artifact_path"])
        self.assertEqual(1, loaded.inspected_artifact_count)

    def test_incompatible_constituents_are_rejected_without_changing_policy(self):
        a, b = self.profile_members[0][0], self.profile_members[1][0]
        original = self._payload(a, [self._comparison(a, b)])
        mutations = [
            lambda d: d["candidate"].update(normalized_audio_sha256="0" * 64),
            lambda d: d["policy"].update(artifact_sha256="0" * 64),
            lambda d: d["profiles"][0]["comparisons"][0]["model"].update(runtime_version="other"),
            lambda d: d["profiles"][0]["comparisons"][0].update(exemplar_normalized_audio_sha256="0" * 64),
            lambda d: d["profiles"][0]["comparisons"][0]["observations"].update(b="stale"),
            lambda d: d["profiles"][0]["comparisons"][0]["spans"]["b"][0].update(end_seconds=2000),
            lambda d: d["profiles"][0]["comparisons"][0]["policy"].update(same_min_cross_median=0.5),
            lambda d: d["profiles"][0]["comparisons"][0].update(outcome="different_speaker"),
            lambda d: d["profiles"][0]["comparisons"][0]["metrics"]["within_a"].update(median=float("nan")),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                payload = deepcopy(original)
                mutate(payload)
                self._write(a, payload)
                self.assertFalse(self._load().comparisons)

    def test_tampered_receipt_and_current_ineligible_observation_are_rejected(self):
        a, b = self.profile_members[0][0], self.profile_members[1][0]
        path = self._write(a, self._payload(a, [self._comparison(a, b)]))
        content = json.loads(path.read_text())
        content["candidate"]["normalized_audio_sha256"] = "0" * 64
        path.write_text(json.dumps(content))
        self.assertFalse(self._load().comparisons)
        self._write(a, self._payload(a, [self._comparison(a, b)]))
        with patch("pastor_transcript_extractor.source_profile_consolidation.assess_automatic_speaker_observation", return_value=SimpleNamespace(eligible=False, reason_code="reviewed_invalid")):
            result = load_saved_source_profile_comparisons(
                self.database, self.candidates, association_root=self.association_root,
                model=asdict(self.model), policy=self.policy, policy_fingerprint=self.policy_fingerprint,
            )
        self.assertFalse(result.comparisons)

    def test_conflicting_saved_diagnostics_remain_unresolved(self):
        a, b = self.profile_members[0][0], self.profile_members[1][0]
        self._write(a, self._payload(a, [self._comparison(a, b)]), "same")
        self._write(a, self._payload(a, [self._comparison(a, b, "different_speaker")]), "different")
        result = self._load().comparisons[(a.id, b.id)]
        self.assertEqual("insufficient_evidence", result["outcome"])
        self.assertEqual("conflicting_saved_comparisons", result["reason"])
        self.assertEqual(2, len(result["saved_evidence"]))

    def test_one_malformed_leaf_does_not_hide_compatible_constituents(self):
        a, b = self.profile_members[0][0], self.profile_members[1][0]
        self._write(a, self._payload(a, [None, self._comparison(a, b)]))
        result = self._load()
        self.assertEqual("same_speaker", result.comparisons[(a.id, b.id)]["outcome"])
        self.assertEqual(1, result.rejection_counts["malformed_saved_comparison"])

    def _run_offline_cli(self):
        with (
            patch("pastor_transcript_extractor.cli.SherpaOnnxEmbeddingBackend", return_value=SimpleNamespace(spec=self.model)),
            patch("pastor_transcript_extractor.source_profile_consolidation.assess_automatic_speaker_observation", side_effect=self._eligibility),
            patch("pastor_transcript_extractor.cli.speaker_pair_eligibility.assess_automatic_speaker_observation", return_value=SimpleNamespace(eligible=False, reason_code="archived_media_unavailable")),
            patch("pastor_transcript_extractor.cli.analyze_observation_pair") as analyze,
        ):
            result = CliRunner().invoke(app, [
                "identity", "consolidate-source-profiles", "--source-id", str(self.source.id),
                "--exemplars-per-profile", "2", "--no-open-packet", "--base-dir", str(self.paths.root),
                "--evaluation-root", str(self.paths.evaluation / "speaker-pairs"), "--policy-path", str(self.policy_path),
            ])
        analyze.assert_not_called()
        self.assertEqual(0, result.exit_code, f"{result.output}\n{result.exception}")
        reports = list((self.paths.evaluation / "source-profile-consolidation/runs").glob("*/*.json"))
        self.assertEqual(1, len(reports))
        self.assertTrue(reports[0].with_suffix(".md").exists())
        return json.loads(reports[0].read_text()), result.output

    def test_cli_completes_from_saved_pairs_without_archive_or_new_analysis(self):
        for a in self.profile_members[0]:
            self._write(a, self._payload(a, [self._comparison(a, b) for b in self.profile_members[1]]))
        report, output = self._run_offline_cli()
        self.assertEqual(4, report["saved_evidence_reuse"]["reused_pair_count"])
        self.assertEqual(0, report["saved_evidence_reuse"]["new_comparison_count"])
        self.assertEqual(1, len(report["proposals"]))
        self.assertFalse(report["preparation_failures"])
        self.assertIn("MERGE PROPOSAL", output)

    def test_cli_keeps_partial_cohort_and_generates_exact_missing_pair_reviews(self):
        a, b = self.profile_members[0][0], self.profile_members[1][0]
        self._write(a, self._payload(a, [self._comparison(a, b)]))
        report, output = self._run_offline_cli()
        self.assertEqual(2, len(report["candidates"]))
        self.assertFalse(report["proposals"])
        self.assertEqual(1, report["saved_evidence_reuse"]["reused_pair_count"])
        self.assertEqual(3, len(report["review_suggestions"]))
        self.assertIn("archived_media_unavailable", output)
        self.assertIn("EXACT PAIR REVIEW", output)
        self.assertTrue(all("--observation-fingerprint-a" in item["review_command"] for item in report["review_suggestions"]))
        self.assertTrue(all(self.database.resolve_speaker_profile_id(candidate.profile_id) == candidate.profile_id for candidate in self.candidates))

    def test_cli_with_no_reusable_evidence_still_writes_unknowns_and_review_report(self):
        report, _ = self._run_offline_cli()
        self.assertFalse(report["comparisons"])
        self.assertFalse(report["proposals"])
        self.assertEqual(4, len(report["review_suggestions"]))
        self.assertEqual(2, len(report["candidates"]))


if __name__ == "__main__":
    unittest.main()
