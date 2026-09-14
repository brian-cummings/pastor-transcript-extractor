from __future__ import annotations

from dataclasses import asdict
import hashlib
from http.client import HTTPConnection
from http.server import HTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
from types import SimpleNamespace
import unittest

from pastor_transcript_extractor.analytical_caption_review import (
    CASES_PER_SERMON, MAX_SOURCE_INSPECTIONS, ReviewSession, make_handler,
    prepare_bundle, propose_cases, summarize, validate_bundle,
)
from pastor_transcript_extractor.sermon_analysis import (
    ANALYZER_KEY, ANALYZER_VERSION, SermonSegment, canonical_sermon_source,
)


class SavedInputs:
    """A few short saved sources; no database, corpus or model inference."""
    def __init__(self, root: Path):
        self.runs = []
        self.videos = []
        self.evidence_reads = []
        for run_id, source_id in ((145, 1), (146, 1), (147, 2), (148, 3)):
            segments = [SermonSegment(0, 10, 12, "John 3:16 tells us that God loves the world."),
                        SermonSegment(1, 12, 14, "John 3:16 tells us that God loves the world."),
                        SermonSegment(2, 14, 16, "John 3:16 tells us that God loves the world."),
                        SermonSegment(3, 50, 52, "This is a separate thought.")]
            path = root / f"source-{run_id}.json"
            path.write_text(json.dumps({
                "sermon_window": {"start_seconds": 0, "end_seconds": 60,
                                  "included_segment_indexes": [0, 1, 2, 3]},
                "segments": [asdict(segment) for segment in segments],
            }))
            self.runs.append(SimpleNamespace(
                id=run_id, video_id=run_id, analyzer_key=ANALYZER_KEY,
                analyzer_version=ANALYZER_VERSION, source_path=str(path),
                source_content_sha256=hashlib.sha256(canonical_sermon_source([SermonSegment(s.index, float(s.start_seconds), float(s.end_seconds), s.text) for s in segments], 0.0, 60.0)).hexdigest(),
                input_fingerprint=f"synthetic-{run_id}",
            ))
            self.videos.append(SimpleNamespace(id=run_id, source_id=source_id,
                                               title=f"Synthetic sermon {run_id}", youtube_video_id=f"example-{run_id}"))

    def list_videos(self):
        return self.videos

    def list_sermon_analysis_runs(self):
        return self.runs

    def get_sermon_analysis_run(self, run_id):
        return next((run for run in self.runs if run.id == run_id), None)

    def list_sermon_analysis_evidence(self, run_id):
        self.evidence_reads.append(run_id)
        return [SimpleNamespace(id=run_id * 10 + index, evidence_kind="scripture_reference",
                                segment_index=index, excerpt="John 3:16", payload_json='{"canonical_reference":"John 3:16"}')
                for index in (0, 1, 2)]


class CaptionReviewTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.database = SavedInputs(self.root)
        self.bundle = prepare_bundle(self.database)

    def test_automatic_selection_uses_known_case_and_another_source(self):
        self.assertEqual(145, self.bundle["sources"][0]["run_id"])
        self.assertNotEqual(1, self.bundle["sources"][1]["source_id"])
        self.assertLessEqual(len(self.database.evidence_reads), MAX_SOURCE_INSPECTIONS)
        self.assertLessEqual(len(self.bundle["cases"]), 2 * CASES_PER_SERMON)
        again = prepare_bundle(self.database)
        self.assertEqual(self.bundle["cases"], again["cases"])
        self.assertEqual(self.bundle["sources"], again["sources"])
        self.assertTrue(self.bundle["different_sources_found"])

    def test_proposals_are_short_nonoverlapping_and_never_auto_approved(self):
        by_run = {}
        for case in self.bundle["cases"]:
            self.assertLessEqual(case["end_seconds"] - case["start_seconds"], 20)
            used = by_run.setdefault(case["run_id"], set())
            indexes = {segment["index"] for segment in case["source_segments"]}
            self.assertFalse(used & indexes)
            used.update(indexes)
        report = summarize(self.bundle, [])
        self.assertEqual(len(self.bundle["cases"]), report["pending"])
        self.assertEqual(0, report["approved"])
        self.assertFalse(report["whole_sermon_reviewed"])
        self.assertEqual([], report["certified_features"])

    def test_large_time_gap_is_not_a_rolling_caption_proposal(self):
        segments = [SermonSegment(0, 0, 2, "Romans 3:24 teaches us something."),
                    SermonSegment(1, 50, 52, "Romans 3:24 teaches us something.")]
        self.assertEqual([], propose_cases(segments, {0, 1}))

    def test_approved_minor_edit_is_saved_and_reopening_resumes(self):
        session = ReviewSession(self.root, self.bundle)
        case = self.bundle["cases"][0]
        edit = "John 3:16 tells us that God loves the whole world."
        session.record({"case_id": case["case_id"], "decision": "approve", "text": edit})
        resumed = ReviewSession(self.root, self.bundle)
        self.assertEqual(edit, resumed.state()["decisions"][case["case_id"]]["text"])
        row = resumed.report["cases"][0]
        self.assertEqual(3, row["original_detected_mentions"])
        self.assertEqual(1, row["reviewed_detected_mentions"])
        self.assertTrue(row["reviewer_edited_proposal"])
        self.assertFalse(resumed.report["whole_sermon_reviewed"])
        self.assertEqual([], resumed.report["certified_features"])

    def test_rejection_or_unclear_does_not_apply_a_proposed_edit(self):
        session = ReviewSession(self.root, self.bundle)
        originals = {run.source_path: Path(run.source_path).read_bytes() for run in self.database.runs}
        for index, case in enumerate(self.bundle["cases"]):
            session.record({"case_id": case["case_id"], "decision": "reject" if index == 0 else "unclear", "text": "not applied"})
        self.assertEqual(0, session.report["pending"])
        self.assertEqual(0, session.report["approved"])
        self.assertEqual(0, session.report["citation_count_counterexamples"])
        for row in session.report["cases"]:
            self.assertNotIn("reviewed_detected_mentions", row)
        for path, original in originals.items():
            self.assertEqual(original, Path(path).read_bytes())

    def test_saved_history_keeps_prior_decisions_when_a_review_is_changed(self):
        session = ReviewSession(self.root, self.bundle)
        case = self.bundle["cases"][0]
        session.record({"case_id": case["case_id"], "decision": "approve", "text": case["proposed_text"]})
        session.record({"case_id": case["case_id"], "decision": "reject"})
        self.assertEqual(2, len(session.events_path.read_text().splitlines()))
        self.assertEqual("reject", session.report["cases"][0]["decision"])
        self.assertNotIn("reviewed_detected_mentions", session.report["cases"][0])

    def test_source_drift_is_recorded_and_does_not_masquerade_as_saved_input(self):
        Path(self.database.runs[0].source_path).write_text('{"changed": true}')
        bundle = prepare_bundle(self.database)
        self.assertNotEqual(145, bundle["sources"][0]["run_id"])
        self.assertTrue(any(row["run_id"] == 145 and row["reason"] == "source_unreadable" for row in bundle["source_inspections"]))

    def test_corrupted_bundle_and_invalid_decisions_are_rejected(self):
        session = ReviewSession(self.root, self.bundle)
        with self.assertRaisesRegex(ValueError, "Unknown case"):
            session.record({"case_id": "not-a-case", "decision": "approve", "text": "bad"})
        case = self.bundle["cases"][0]
        with self.assertRaisesRegex(ValueError, "cannot be blank"):
            session.record({"case_id": case["case_id"], "decision": "approve", "text": ""})
        self.bundle["cases"][0]["proposed_text"] = "Modified frozen proposal"
        with self.assertRaisesRegex(ValueError, "modified"):
            validate_bundle(self.bundle)

    def test_no_candidates_is_not_a_validation_pass(self):
        self.database.list_sermon_analysis_evidence = lambda run_id: []
        bundle = prepare_bundle(self.database)
        report = summarize(bundle, [])
        self.assertEqual("no_reviewable_candidates_in_bounded_screen", report["outcome"])
        self.assertEqual([], report["certified_features"])
        self.assertIn("Codex", report["next_action"])

    def test_source_inspections_have_a_hard_limit(self):
        template = self.database.runs[-1]
        video_template = self.database.videos[-1]
        for run_id in range(200, 220):
            self.database.runs.append(SimpleNamespace(**{**vars(template), "id": run_id, "video_id": run_id}))
            self.database.videos.append(SimpleNamespace(**{**vars(video_template), "id": run_id}))
        reads = []
        def no_candidates(run_id):
            reads.append(run_id)
            return []
        self.database.list_sermon_analysis_evidence = no_candidates
        bundle = prepare_bundle(self.database)
        self.assertEqual(MAX_SOURCE_INSPECTIONS, len(reads))
        self.assertEqual(MAX_SOURCE_INSPECTIONS, len(bundle["source_inspections"]))

    def test_local_page_saves_decisions_and_rejects_cross_origin_writes(self):
        session = ReviewSession(self.root, self.bundle)
        server = HTTPServer(("127.0.0.1", 0), make_handler(session, "test-token"))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        conn = HTTPConnection("127.0.0.1", server.server_port)
        self.addCleanup(conn.close)
        conn.request("GET", "/")
        response = conn.getresponse()
        self.assertEqual(200, response.status)
        self.assertIn(b"Matches audio", response.read())
        case = self.bundle["cases"][0]
        body = json.dumps({"case_id": case["case_id"], "decision": "approve", "text": case["proposed_text"]})
        conn.request("POST", "/decision", body, {"Content-Type": "application/json"})
        response = conn.getresponse()
        self.assertEqual(403, response.status)
        response.read()
        conn.request("POST", "/decision", body, {
            "Content-Type": "application/json", "X-Review-Token": "test-token",
            "Origin": f"http://127.0.0.1:{server.server_port}",
        })
        response = conn.getresponse()
        self.assertEqual(200, response.status)
        self.assertEqual(1, json.loads(response.read())["report"]["approved"])


if __name__ == "__main__":
    unittest.main()
