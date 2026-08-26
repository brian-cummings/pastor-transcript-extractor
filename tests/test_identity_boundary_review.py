from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.exporting import (
    export_pastor_review_markdown,
)
from pastor_transcript_extractor.identity_boundary_review import (
    apply_identity_boundary_review,
    persist_association_boundary_evidence,
    review_identity_boundaries,
)
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.storage import Database


def segments() -> list[dict[str, object]]:
    return [
        {
            "start_seconds": float(start),
            "end_seconds": float(start + 60),
            "text": "coherent teaching about grace and faithful Christian life",
            "label": "sermon",
        }
        for start in range(0, 1800, 60)
    ]


def evidence(edge: str, proposed: float) -> dict[str, object]:
    return {
        "association_version": "association-v7",
        "model_fingerprint": "model-sha256",
        "automatic_use_allowed": True,
        "sermon_speaker_spans": [
            {"start_seconds": 120.0, "end_seconds": 132.0, "speaker_key": "sermon"},
            {"start_seconds": 900.0, "end_seconds": 912.0, "speaker_key": "sermon"},
            {"start_seconds": 1500.0, "end_seconds": 1512.0, "speaker_key": "sermon"},
        ],
        "edges": [
            {
                "edge": edge,
                "materially_inconsistent": True,
                "removes_coherent_exposition": False,
                "allowed_interruption": False,
                "brief_pastoral_handoff": False,
                "edge_speaker_spans": [
                    {"start_seconds": 0.0 if edge == "start" else 1740.0, "end_seconds": 12.0 if edge == "start" else 1752.0, "speaker_key": "other"},
                    {"start_seconds": 24.0 if edge == "start" else 1760.0, "end_seconds": 36.0 if edge == "start" else 1772.0, "speaker_key": "other"},
                ],
                "proposed_boundary": proposed,
                "transcript_transition_evidence": {
                    "boundary_seconds": proposed,
                    "transition_kind": "speaker_change_at_segment_boundary",
                    "confidence": "high",
                },
            }
        ],
    }


class IdentityBoundaryReviewTests(unittest.TestCase):
    def test_different_introductory_speaker_is_trimmed(self) -> None:
        result = review_identity_boundaries(
            {"start_seconds": 0.0, "end_seconds": 1800.0, "source": "detected"},
            segments(),
            evidence("start", 120.0),
        )
        self.assertEqual(120.0, result.sermon_window["start_seconds"])
        self.assertEqual("auto_trim", result.records[0]["decision"])

    def test_different_closing_speaker_is_trimmed(self) -> None:
        result = review_identity_boundaries(
            {"start_seconds": 0.0, "end_seconds": 1800.0},
            segments(),
            evidence("end", 1680.0),
        )
        self.assertEqual(1680.0, result.sermon_window["end_seconds"])
        self.assertEqual("auto_trim", result.records[1]["decision"])

    def test_brief_guest_prayer_requires_review(self) -> None:
        transcript = segments()
        transcript[0]["text"] = "Heavenly Father, bless the preaching of your word"
        result = review_identity_boundaries(
            {"start_seconds": 0.0, "end_seconds": 1800.0}, transcript,
            evidence("start", 60.0),
        )
        self.assertEqual("review_required", result.records[0]["decision"])
        self.assertEqual(0.0, result.sermon_window["start_seconds"])

    def test_same_speaker_with_acoustic_variation_retains_boundary(self) -> None:
        value = evidence("start", 120.0)
        value["edges"][0]["supports_current_boundary"] = True  # type: ignore[index]
        result = review_identity_boundaries(
            {"start_seconds": 0.0, "end_seconds": 1800.0}, segments(), value
        )
        self.assertEqual("retain_boundary", result.records[0]["decision"])

    def test_insufficient_identity_evidence_takes_no_action(self) -> None:
        result = review_identity_boundaries(
            {"start_seconds": 0.0, "end_seconds": 1800.0}, segments(), None
        )
        self.assertTrue(all(record["decision"] == "no_action" for record in result.records))

    def test_excessive_trim_requires_review(self) -> None:
        value = evidence("start", 600.0)
        value["sermon_speaker_spans"][0]["start_seconds"] = 660.0  # type: ignore[index]
        result = review_identity_boundaries(
            {"start_seconds": 0.0, "end_seconds": 1800.0}, segments(), value
        )
        self.assertIn("automatic_trim_limit_exceeded", result.records[0]["reason_codes"])

    def test_explicit_sermon_anchor_is_protected(self) -> None:
        transcript = segments()
        transcript[1]["text"] = "Open your Bibles to the sermon text for this morning"
        result = review_identity_boundaries(
            {"start_seconds": 0.0, "end_seconds": 1800.0}, transcript,
            evidence("start", 120.0),
        )
        self.assertIn("protected_sermon_anchor_present", result.records[0]["reason_codes"])

    def test_accepted_trim_is_the_exported_excerpt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_paths(root)
            database = Database(paths.database)
            database.initialize()
            pastor = database.add_pastor("speaker", "Sermon Speaker")
            source = database.add_source(
                "https://www.youtube.com/watch?v=identity-edge",
                SourceType.VIDEO,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="identity-edge",
                title="Identity Edge",
                url="https://www.youtube.com/watch?v=identity-edge",
                status=VideoStatus.EXTRACTED,
            )
            transcript = segments()
            transcript[0]["text"] = "INTRO SPEAKER ONE"
            transcript[1]["text"] = "INTRO SPEAKER TWO"
            proposed_md = root / "proposed.md"
            proposed_json = root / "proposed.json"
            proposed_md.write_text("fallback", encoding="utf-8")
            proposed_json.write_text(json.dumps({
                "sermon_window": {"start_seconds": 0.0, "end_seconds": 1800.0},
                "segments": transcript,
                "identity_boundary_evidence": evidence("start", 120.0),
                "final_disposition": {"status": "accepted_sermon"},
            }), encoding="utf-8")
            database.add_extraction_result(
                video_id=video.id,
                version=1,
                proposed_text_path=str(proposed_md),
                proposed_json_path=str(proposed_json),
            )

            exported = export_pastor_review_markdown(database, paths, pastor.slug)
            markdown = exported.export_path.read_text(encoding="utf-8")
            manifest = json.loads(exported.manifest_path.read_text(encoding="utf-8"))
            persisted = json.loads(proposed_json.read_text(encoding="utf-8"))

        self.assertNotIn("INTRO SPEAKER", markdown)
        self.assertEqual(120.0, manifest["videos"][0]["sermon_window"]["start_seconds"])
        self.assertEqual(120.0, persisted["sermon_window"]["start_seconds"])
        self.assertEqual("auto_trim", persisted["identity_boundary_review"]["records"][0]["decision"])

    def test_causal_record_is_persisted_and_idempotent(self) -> None:
        payload = {
            "sermon_window": {"start_seconds": 0.0, "end_seconds": 1800.0},
            "segments": segments(),
            "identity_boundary_evidence": evidence("start", 120.0),
        }
        once = apply_identity_boundary_review(payload)
        twice = apply_identity_boundary_review(once)
        self.assertEqual(once, twice)
        record = once["identity_boundary_review"]["records"][0]
        self.assertEqual("association-v7", record["speaker_association_version"])
        self.assertEqual({"start_seconds": 0.0, "end_seconds": 1800.0}, record["boundary_before_review"])

    def test_fixture_fields_do_not_enter_runtime_policy_record(self) -> None:
        value = evidence("start", 120.0)
        baseline = review_identity_boundaries(
            {"start_seconds": 0.0, "end_seconds": 1800.0}, segments(), value
        )
        value["edges"][0]["edge_speaker_spans"][0].update({  # type: ignore[index]
            "expected_speaker": "fixture pastor",
            "contamination_score": 0.99,
            "reviewed_boundary": 120.0,
        })
        result = review_identity_boundaries(
            {"start_seconds": 0.0, "end_seconds": 1800.0}, segments(), value
        )
        encoded = json.dumps(result.records)
        self.assertNotIn("expected_speaker", encoded)
        self.assertNotIn("contamination_score", encoded)
        self.assertNotIn("reviewed_boundary", encoded)
        self.assertEqual(
            baseline.records[0]["input_fingerprint"],
            result.records[0]["input_fingerprint"],
        )

    def test_association_adapter_persists_review_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.json"
            path.write_text(json.dumps({"sermon_window": {"start_seconds": 0.0, "end_seconds": 1800.0}, "segments": segments()}))
            report = {
                "association_version": "association-v7",
                "model_fingerprint": "model",
                "result_sha256": "artifact",
                "span_selection": {"candidate_selection": {"coherent_sermon_speaker_spans": evidence("start", 120.0)["sermon_speaker_spans"]}},
                "sermon_window_quality_flags": [{"flag": "speaker_inconsistent_edge", "edge": "start", "start_seconds": 0.0, "end_seconds": 60.0, "reason_codes": ["distributed_clip_inconsistent"]}],
            }
            self.assertTrue(persist_association_boundary_evidence(path, report))
            persisted = json.loads(path.read_text())
        self.assertIn("identity_boundary_evidence", persisted)
        self.assertEqual("review_required", persisted["identity_boundary_review"]["records"][0]["decision"])

    def test_approved_association_can_drive_automatic_production_trim(self) -> None:
        report = {
            "association_version": "association-v7",
            "model_fingerprint": "model",
            "result_sha256": "artifact",
            "policy": {"automatic_use_allowed": True},
            "span_selection": {
                "candidate_selection": {
                    "coherent_sermon_speaker_spans": evidence("start", 120.0)[
                        "sermon_speaker_spans"
                    ]
                }
            },
            "sermon_window_quality_flags": [{
                "flag": "speaker_inconsistent_edge",
                "edge": "start",
                "start_seconds": 0.0,
                "end_seconds": 60.0,
                "reason_codes": [
                    "distributed_clip_inconsistent",
                    "coherent_replacement_found",
                ],
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.json"
            path.write_text(json.dumps({
                "sermon_window": {"start_seconds": 0.0, "end_seconds": 1800.0},
                "segments": segments(),
            }))
            self.assertTrue(persist_association_boundary_evidence(path, report))
            persisted = json.loads(path.read_text())

        self.assertEqual(60.0, persisted["sermon_window"]["start_seconds"])
        self.assertEqual(
            "auto_trim",
            persisted["identity_boundary_review"]["records"][0]["decision"],
        )


if __name__ == "__main__":
    unittest.main()
