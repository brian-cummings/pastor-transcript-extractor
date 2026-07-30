from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_association_audit import (
    audit_speaker_association_coverage,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    SHADOW_ASSOCIATION_VERSION,
    write_shadow_association,
)
from pastor_transcript_extractor.storage import Database


class SpeakerAssociationAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = build_paths(self.root / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.source = self.database.add_source(
            "https://www.youtube.com/@association-audit",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        self.association_root = self.root / "associations"
        self.output_root = self.root / "audits"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _extraction(
        self,
        key: str,
        status: str,
        *,
        observation: bool = False,
        malformed: bool = False,
        speech_grounded: bool = True,
    ):
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=None,
            youtube_video_id=f"audit-{key}",
            title=f"Audit {key}",
            url=f"https://www.youtube.com/watch?v=audit-{key}",
            status=VideoStatus.EXTRACTED,
        )
        artifact_root = self.root / "artifacts" / key
        artifact_root.mkdir(parents=True, exist_ok=True)
        proposed_json = artifact_root / "proposed.json"
        if malformed:
            proposed_json.write_text("{", encoding="utf-8")
        else:
            proposed_json.write_text(
                json.dumps(
                    {
                        "final_disposition": {"status": status},
                        "sermon_window": {
                            "start_seconds": 100.0,
                            "end_seconds": 1000.0,
                        },
                        "segments": [
                            {
                                "start_seconds": start,
                                "end_seconds": start + 15.0,
                                "label": "sermon",
                                "text": (
                                    "This sustained sermon sentence contains "
                                    "enough distinct words for speaker evidence."
                                ),
                            }
                            for start in (150.0, 300.0, 450.0, 600.0, 750.0)
                        ]
                        if speech_grounded
                        else [],
                    }
                ),
                encoding="utf-8",
            )
        extraction = self.database.add_extraction_result(
            video_id=video.id,
            version=1,
            proposed_text_path=str(artifact_root / "proposed.md"),
            proposed_json_path=str(proposed_json),
        )
        speaker_observation = None
        if observation:
            speaker_observation = self.database.add_speaker_observation(
                video_id=video.id,
                extraction_result_id=extraction.id,
                role="principal_speaker_candidate",
                multiplicity_state="unknown",
                start_seconds=100.0,
                end_seconds=1000.0,
                artifact_path=str(artifact_root / "speaker.json"),
                content_sha256=f"content-{key}",
                extractor_version="speaker_evidence_v1",
                input_fingerprint=f"observation-{key}",
            )
        return video, extraction, speaker_observation

    def _association_attempt(
        self,
        observation,
        *,
        outcome: str,
        association_version: str = SHADOW_ASSOCIATION_VERSION,
    ) -> Path:
        report = {
            "schema_version": 1,
            "association_version": association_version,
            "artifact_kind": "speaker_profile_shadow_association",
            "shadow_mode": True,
            "registry_mutation_allowed": False,
            "automatic_assignment_allowed": False,
            "candidate": {
                "observation_id": observation.id,
                "video_id": observation.video_id,
                "input_fingerprint": observation.input_fingerprint,
                "normalized_names": [],
            },
            "model_fingerprint": "test-model",
            "policy": {
                "version": "test-policy",
                "review_status": "experimental_candidate",
                "artifact_sha256": "a" * 64,
                "automatic_use_allowed": False,
            },
            "minimum_same_exemplars": 2,
            "span_selection": {
                "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
            },
            "outcome": outcome,
            "reason": "test",
            "proposed_profile_id": None,
            "profiles": [],
            "input_fingerprint": f"attempt-{observation.input_fingerprint}-{outcome}",
        }
        report["result_sha256"] = _sha256_json(report)
        return write_shadow_association(self.association_root, report)

    def _verified_media(self, video, key: str) -> None:
        audio_path = self.root / "media" / f"{key}.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        content = f"verified-media-{key}".encode("utf-8")
        audio_path.write_bytes(content)
        self.database.add_media_artifact(
            video_id=video.id,
            parent_media_artifact_id=None,
            artifact_kind="normalized_audio",
            provenance_kind="derived",
            artifact_path=str(audio_path),
            manifest_path=str(audio_path.with_suffix(".json")),
            content_sha256=hashlib.sha256(content).hexdigest(),
            byte_size=len(content),
            duration_seconds=1200.0,
            format_name="wav",
            sample_rate_hz=16000,
            channel_count=1,
            acquisition_tool="test",
            acquisition_tool_version="1",
            input_fingerprint=f"media-{key}",
        )

    def test_audit_accounts_for_terminal_blocked_evaluated_and_associated_cases(
        self,
    ) -> None:
        self._extraction("review", "review_required")
        self._extraction("rejected", "rejected_no_sermon")
        self._extraction("missing", "accepted_sermon")
        unevaluated_video, _, _ = self._extraction(
            "unevaluated",
            "accepted_sermon",
            observation=True,
        )
        self._verified_media(unevaluated_video, "unevaluated")
        _, _, blocked = self._extraction(
            "blocked",
            "accepted_sermon",
            observation=True,
        )
        _, _, evaluated = self._extraction(
            "evaluated",
            "accepted_sermon",
            observation=True,
        )
        self._association_attempt(evaluated, outcome="no_match")
        _, _, associated = self._extraction(
            "associated",
            "accepted_sermon",
            observation=True,
        )
        profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="reviewed identity",
            review_event_key="audit-profile",
        )
        attach_reviewed_observation(
            self.database,
            profile_id=profile.id,
            observation_id=associated.id,
            reviewer="reviewer",
            reason="reviewed identity",
            review_event_key="audit-membership",
        )
        self._extraction(
            "malformed",
            "accepted_sermon",
            malformed=True,
        )

        result = audit_speaker_association_coverage(
            self.database,
            association_root=self.association_root,
            output_root=self.output_root,
        )
        repeated = audit_speaker_association_coverage(
            self.database,
            association_root=self.association_root,
            output_root=self.output_root,
        )

        self.assertEqual(result.report_path, repeated.report_path)
        self.assertEqual(8, result.payload["counts"]["extractions"])
        self.assertEqual(5, result.payload["counts"]["accounted"])
        self.assertEqual(3, result.payload["counts"]["unaccounted"])
        self.assertFalse(result.ok)
        self.assertEqual(
            {
                "associated": 1,
                "blocked": 1,
                "content_terminal": 2,
                "evaluated": 1,
                "unaccounted": 3,
            },
            result.payload["coverage_state_counts"],
        )
        cases = {
            case["youtube_video_id"]: case for case in result.payload["cases"]
        }
        self.assertEqual(
            "verified_normalized_media_unavailable",
            cases["audit-blocked"]["reason_code"],
        )
        self.assertEqual(
            "association_attempt_missing",
            cases["audit-unevaluated"]["reason_code"],
        )
        self.assertEqual(
            "observation_unavailable",
            cases["audit-missing"]["reason_code"],
        )
        self.assertEqual(
            "extraction_artifact_unreadable",
            cases["audit-malformed"]["reason_code"],
        )
        self.assertEqual(
            "versioned_association_attempt",
            cases["audit-evaluated"]["reason_code"],
        )
        self.assertEqual(
            [profile.id],
            cases["audit-associated"]["effective_profile_ids"],
        )

    def test_failed_association_attempt_requires_retry(self) -> None:
        _, _, observation = self._extraction(
            "failed-attempt",
            "accepted_sermon",
            observation=True,
        )
        self._association_attempt(observation, outcome="analysis_failed")

        result = audit_speaker_association_coverage(
            self.database,
            association_root=self.association_root,
            output_root=self.output_root,
        )

        self.assertEqual(1, result.unaccounted_count)
        self.assertEqual(
            "association_attempt_requires_retry",
            result.payload["cases"][0]["reason_code"],
        )

    def test_attempt_from_a_different_policy_is_stale(self) -> None:
        _, _, observation = self._extraction(
            "stale-attempt",
            "accepted_sermon",
            observation=True,
        )
        self._association_attempt(observation, outcome="no_match")

        result = audit_speaker_association_coverage(
            self.database,
            association_root=self.association_root,
            output_root=self.output_root,
            required_policy_sha256="b" * 64,
        )

        self.assertEqual(1, result.unaccounted_count)
        self.assertEqual(
            "association_attempt_stale",
            result.payload["cases"][0]["reason_code"],
        )
        self.assertEqual(
            1,
            len(result.payload["cases"][0]["stale_association_attempts"]),
        )

    def test_legacy_sampling_attempt_is_stale(self) -> None:
        _, _, observation = self._extraction(
            "legacy-attempt",
            "accepted_sermon",
            observation=True,
        )
        self._association_attempt(
            observation,
            outcome="no_match",
            association_version="speaker_shadow_association_v1",
        )

        result = audit_speaker_association_coverage(
            self.database,
            association_root=self.association_root,
            output_root=self.output_root,
        )

        self.assertEqual(1, result.unaccounted_count)
        self.assertEqual(
            "association_attempt_stale",
            result.payload["cases"][0]["reason_code"],
        )

    def test_missing_speech_grounded_spans_is_an_accounted_blocker(self) -> None:
        video, _, _ = self._extraction(
            "non-speech",
            "accepted_sermon",
            observation=True,
            speech_grounded=False,
        )
        self._verified_media(video, "non-speech")

        result = audit_speaker_association_coverage(
            self.database,
            association_root=self.association_root,
            output_root=self.output_root,
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            "speech_grounded_spans_unavailable",
            result.payload["cases"][0]["reason_code"],
        )

    def test_invalid_association_artifact_fails_audit_integrity(self) -> None:
        self._extraction("review", "review_required")
        self.association_root.mkdir(parents=True, exist_ok=True)
        (self.association_root / "broken.json").write_text("{", encoding="utf-8")

        result = audit_speaker_association_coverage(
            self.database,
            association_root=self.association_root,
            output_root=self.output_root,
        )

        self.assertEqual(0, result.unaccounted_count)
        self.assertEqual(1, result.invalid_artifact_count)
        self.assertFalse(result.ok)

    def test_cli_is_strict_by_default_and_can_report_with_gaps(self) -> None:
        video, _, _ = self._extraction(
            "missing",
            "accepted_sermon",
            observation=True,
        )
        self._verified_media(video, "missing")
        runner = CliRunner()
        common = [
            "identity",
            "association-audit",
            "--association-root",
            str(self.association_root),
            "--cache-dir",
            str(self.root / "cache"),
            "--output-root",
            str(self.output_root),
            "--base-dir",
            str(self.paths.root),
        ]

        strict = runner.invoke(app, common)
        allowed = runner.invoke(app, [*common, "--allow-gaps"])

        self.assertEqual(1, strict.exit_code)
        self.assertEqual(0, allowed.exit_code)
        self.assertIn("unaccounted=1", allowed.stdout)
        self.assertIn("association_attempt_missing=1", allowed.stdout)


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    unittest.main()
