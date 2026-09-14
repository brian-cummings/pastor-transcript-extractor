"""Prepare and serve a bounded, approval-only caption screen for E1a.

Brian runs one command and reviews prepared edits. This tool owns case selection,
provenance and reporting. It never edits source transcripts or certifies features.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
import json
import math
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import urlencode
import webbrowser

from pastor_transcript_extractor.analytical_pilot import digest, read_json, write_new
from pastor_transcript_extractor.caption_normalization import normalize_caption_fragments
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.sermon_analysis import (
    ANALYZER_KEY, ANALYZER_VERSION, SermonSegment, _reference_evidence, _WORD_PATTERN,
    canonical_sermon_source, load_identified_sermon_source,
)
from pastor_transcript_extractor.storage import Database

POLICY_VERSION = "e1a-caption-screen@1"
MAX_SOURCE_INSPECTIONS = 6
MAX_SERMONS = 2
CASES_PER_SERMON = 3
MAX_WINDOW_SEGMENTS = 4
MAX_WINDOW_SECONDS = 20


def code_provenance() -> dict[str, str]:
    return {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("analytical_caption_review.py", "caption_normalization.py", "sermon_analysis.py")
    }


def _time(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def _reference_count(segments: list[SermonSegment]) -> int:
    # Recompute both arms with the same excerpt context. Never compare a saved
    # context-dependent full-sermon count with a context-free snippet count.
    return len(_reference_evidence(segments))


def propose_cases(segments: list[SermonSegment], reference_indexes: set[int]) -> list[dict]:
    """Find at most three nonoverlapping, short edits; no proposal is approved."""
    proposals = []
    for first in range(len(segments) - 1):
        for length in range(2, MAX_WINDOW_SEGMENTS + 1):
            window = segments[first:first + length]
            if len(window) != length:
                break
            if not any(segment.index in reference_indexes for segment in window):
                continue
            starts = [_time(segment.start_seconds) for segment in window]
            ends = [_time(segment.end_seconds) for segment in window]
            if any(value is None for value in [*starts, *ends]):
                continue
            if any(end < start for start, end in zip(starts, ends, strict=True)):
                continue
            start, end = min(starts), max(ends)
            if end <= start or end - start > MAX_WINDOW_SECONDS:
                continue
            if any(right > left + 2 for left, right in zip(ends, starts[1:])):
                continue
            original_text = "\n".join(segment.text for segment in window)
            normalized = normalize_caption_fragments((segment.index, segment.text) for segment in window)
            before_words = len(_WORD_PATTERN.findall(original_text))
            after_words = len(_WORD_PATTERN.findall(normalized.text))
            if not normalized.text or after_words >= before_words:
                continue
            proposals.append({
                "source_segments": [asdict(segment) for segment in window],
                "context_before": [asdict(segment) for segment in segments[max(0, first - 1):first]],
                "context_after": [asdict(segment) for segment in segments[first + length:first + length + 1]],
                "start_seconds": start, "end_seconds": end,
                "original_text": original_text, "proposed_text": normalized.text,
                "reason": "Adjacent caption fragments repeat or extend the same words near a detected citation. Check whether the audio speaks them once or repeats them.",
                "normalizer_diagnostics": normalized.diagnostics,
                "proposed_words_removed": before_words - after_words,
            })
    # Prefer larger possible caption artifacts, then earlier timestamps. This is
    # explicitly purposive falsification, not a prevalence sample.
    proposals.sort(key=lambda item: (-item["proposed_words_removed"], item["start_seconds"]))
    selected = []
    used = set()
    for proposal in proposals:
        indexes = {segment["index"] for segment in proposal["source_segments"]}
        if used & indexes:
            continue
        selected.append(proposal)
        used.update(indexes)
        if len(selected) == CASES_PER_SERMON:
            break
    return sorted(selected, key=lambda item: item["start_seconds"])


def prepare_bundle(database: Database) -> dict:
    """Read saved artifacts only, with a hard source-inspection limit."""
    videos = {video.id: video for video in database.list_videos()}
    latest = {}
    for run in database.list_sermon_analysis_runs():
        if run.analyzer_key == ANALYZER_KEY and run.analyzer_version == ANALYZER_VERSION:
            if run.video_id not in latest or latest[run.video_id].id < run.id:
                latest[run.video_id] = run
    known = database.get_sermon_analysis_run(145)
    known_valid = known is not None and known.analyzer_key == ANALYZER_KEY and known.analyzer_version == ANALYZER_VERSION
    anchor = videos.get(known.video_id) if known_valid else None
    candidates = sorted(latest.values(), key=lambda run: (
        videos.get(run.video_id) is None or (anchor is not None and videos[run.video_id].source_id == anchor.source_id),
        digest({"policy": POLICY_VERSION, "video_id": run.video_id}),
    ))
    if known_valid:
        candidates = [known, *[run for run in candidates if run.video_id != known.video_id]]
    inspections = []
    cases = []
    sources = []
    selected_sources = set()
    for run in candidates[:MAX_SOURCE_INSPECTIONS]:
        video = videos.get(run.video_id)
        if video is None:
            inspections.append({"run_id": run.id, "reason": "missing_video"})
            continue
        try:
            segments, start, duration = load_identified_sermon_source(Path(run.source_path))
            source_hash = hashlib.sha256(canonical_sermon_source(segments, start, duration)).hexdigest()
            if source_hash != run.source_content_sha256:
                inspections.append({"run_id": run.id, "reason": "source_hash_mismatch"})
                continue
            evidence = database.list_sermon_analysis_evidence(run.id)
            reference_indexes = {item.segment_index for item in evidence if item.evidence_kind == "scripture_reference"}
            proposals = propose_cases(segments, reference_indexes)
        except (OSError, ValueError) as error:
            inspections.append({"run_id": run.id, "reason": "source_unreadable", "detail": str(error)})
            continue
        if not proposals:
            inspections.append({"run_id": run.id, "reason": "no_short_reviewable_candidates"})
            continue
        source = {
            "run_id": run.id, "video_id": run.video_id, "source_id": video.source_id,
            "video_title": video.title, "youtube_video_id": video.youtube_video_id,
            "source_path": run.source_path, "source_content_sha256": source_hash,
            "input_fingerprint": run.input_fingerprint, "analyzer_version": run.analyzer_version,
            "selection_reason": "known_review_counterexample" if run.id == 145 else "fixed_hash_order_preferring_another_source; first_usable_short_candidates",
        }
        sources.append(source)
        selected_sources.add(video.source_id)
        for proposal in proposals:
            query = urlencode({"v": video.youtube_video_id, "t": max(0, int(proposal["start_seconds"]) - 4)})
            case = {
                **proposal, "run_id": run.id, "video_title": video.title,
                "audio_url": f"https://www.youtube.com/watch?{query}",
                "saved_reference_evidence": [
                    {"id": item.id, "segment_index": item.segment_index,
                     "excerpt": item.excerpt, "payload": json.loads(item.payload_json)}
                    for item in evidence if item.evidence_kind == "scripture_reference"
                    and item.segment_index in {segment["index"] for segment in proposal["source_segments"]}
                ],
            }
            case["case_id"] = digest(case)[:16]
            cases.append(case)
        inspections.append({"run_id": run.id, "reason": "selected", "case_count": len(proposals)})
        if len(sources) == MAX_SERMONS:
            break
    payload = {
        "schema_version": POLICY_VERSION,
        "scope": "selected_caption_excerpts_not_whole_sermon_review",
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "known_anchor_run_id": 145, "maximum_source_inspections": MAX_SOURCE_INSPECTIONS,
            "maximum_sermons": MAX_SERMONS, "maximum_cases_per_sermon": CASES_PER_SERMON,
            "maximum_excerpt_seconds": MAX_WINDOW_SECONDS,
            "selection": "known_anchor_then_fixed_hash_order_prefer_different_source; largest_word_reductions_first_nonoverlapping",
            "no_feature_certification": True, "implementation_sha256": code_provenance(),
        },
        "sources": sources, "source_inspections": inspections,
        "different_sources_found": len(selected_sources) > 1,
        "cases": cases,
    }
    payload["bundle_sha256"] = digest(payload)
    return payload


def validate_bundle(bundle: dict) -> None:
    if bundle.get("schema_version") != POLICY_VERSION:
        raise ValueError("Unsupported caption review bundle; Codex needs to update it")
    pinned = bundle.get("bundle_sha256")
    if pinned != digest({key: value for key, value in bundle.items() if key != "bundle_sha256"}):
        raise ValueError("Prepared review was modified; Codex needs to inspect it")
    if bundle["policy"].get("implementation_sha256") != code_provenance():
        raise ValueError("The review code changed after preparation; Codex needs to refresh the prepared review")


def summarize(bundle: dict, events: list[dict]) -> dict:
    validate_bundle(bundle)
    cases = {case["case_id"]: case for case in bundle["cases"]}
    latest = {}
    for event in events:
        if event.get("bundle_sha256") != bundle["bundle_sha256"] or event.get("case_id") not in cases:
            raise ValueError("Review history does not match the prepared cases")
        if event.get("decision") not in {"approve", "reject", "unclear"}:
            raise ValueError("Invalid saved decision")
        if event["decision"] == "approve" and (not isinstance(event.get("text"), str) or not event["text"].strip()):
            raise ValueError("Invalid saved approved text")
        latest[event["case_id"]] = event
    rows = []
    for case_id, case in cases.items():
        event = latest.get(case_id)
        row = {"case_id": case_id, "run_id": case["run_id"],
               "start_seconds": case["start_seconds"], "end_seconds": case["end_seconds"],
               "decision": event["decision"] if event else "pending"}
        if event and event["decision"] == "approve":
            before = [SermonSegment(**item) for item in case["source_segments"]]
            # A single reviewed spoken-text fragment, explicitly limited to this excerpt.
            after = [SermonSegment(before[0].index, case["start_seconds"], case["end_seconds"], event["text"])]
            row.update({
                "original_detected_mentions": _reference_count(before),
                "reviewed_detected_mentions": _reference_count(after),
                "approved_text": event["text"],
                "reviewer_edited_proposal": event["text"] != case["proposed_text"],
            })
        rows.append(row)
    confirmed = [row for row in rows if row.get("original_detected_mentions", 0) > row.get("reviewed_detected_mentions", 0)]
    decisions = [row["decision"] for row in rows]
    pending = decisions.count("pending")
    if not rows:
        outcome = "no_reviewable_candidates_in_bounded_screen"
        next_action = "Codex should inspect the recorded exclusions and prepare a better targeted case."
    elif pending:
        outcome = "review_in_progress"
        next_action = "Finish the remaining cards; no experimental-design decisions are needed."
    elif confirmed:
        outcome = "reviewed_caption_edits_reduce_detected_mentions_in_selected_excerpts"
        next_action = "Codex should investigate an evidence-preserving caption/citation repair before expanding review."
    else:
        outcome = "no_citation_count_counterexample_confirmed_in_selected_excerpts"
        next_action = "Codex should inspect rejected/unclear cases and propose the next bounded check; this is not a pass."
    return {
        "schema_version": "e1a-caption-screen-report@1", "bundle_sha256": bundle["bundle_sha256"],
        "scope": bundle["scope"], "outcome": outcome, "next_action": next_action,
        "case_count": len(rows), "pending": pending, "approved": decisions.count("approve"),
        "rejected": decisions.count("reject"), "unclear": decisions.count("unclear"),
        "citation_count_counterexamples": len(confirmed), "cases": rows,
        "certified_features": [], "whole_sermon_reviewed": False,
        "limitations": [
            "Approval concerns only the displayed excerpt and correction after listening to audio.",
            "Local detector counts do not estimate full-sermon density, alignment fraction, error prevalence or recall.",
            "No identity, sermon-boundary or E1b certification flags are inferred from these approvals.",
        ],
    }


class ReviewSession:
    def __init__(self, directory: Path, bundle: dict):
        validate_bundle(bundle)
        self.directory = directory
        self.bundle = bundle
        self.events_path = directory / "review-events.jsonl"
        self.events = []
        if self.events_path.exists():
            self.events = [json.loads(line) for line in self.events_path.read_text().splitlines() if line.strip()]
        self.report = summarize(bundle, self.events)
        self._write_report()

    def _write_report(self) -> None:
        path = self.directory / "report.json"
        temporary = self.directory / "report.json.tmp"
        temporary.write_text(json.dumps(self.report, indent=2, ensure_ascii=False) + "\n")
        temporary.replace(path)

    def state(self) -> dict:
        latest = {event["case_id"]: event for event in self.events}
        return {"cases": self.bundle["cases"], "decisions": latest, "report": self.report}

    def record(self, payload: dict) -> None:
        case = next((case for case in self.bundle["cases"] if case["case_id"] == payload.get("case_id")), None)
        if case is None:
            raise ValueError("Unknown case")
        decision = payload.get("decision")
        if decision not in {"approve", "reject", "unclear"}:
            raise ValueError("Choose approve, reject or unclear")
        text = payload.get("text", "")
        if not isinstance(text, str) or len(text) > 20000:
            raise ValueError("Correction must be text of at most 20,000 characters")
        if decision == "approve" and not text.strip():
            raise ValueError("An approved correction cannot be blank")
        event = {
            "bundle_sha256": self.bundle["bundle_sha256"], "case_id": case["case_id"],
            "decision": decision, "text": text.strip() if decision == "approve" else None,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        # Calculate successfully before recording the decision. No source or
        # production database mutations occur when a reviewer accepts an edit.
        report = summarize(self.bundle, [*self.events, event])
        with self.events_path.open("a") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.events.append(event)
        self.report = report
        self._write_report()


def make_handler(session: ReviewSession, token: str):
    html = files("pastor_transcript_extractor").joinpath("data/analytical-caption-review.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status: int, content: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def json_response(self, payload: dict, status: int = 200) -> None:
            self.send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def do_GET(self):
            if self.path == "/":
                self.send(200, html, "text/html; charset=utf-8")
            elif self.path == "/state":
                self.json_response({**session.state(), "token": token})
            else:
                self.json_response({"error": "Not found"}, 404)

        def do_POST(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if self.headers.get("Origin") != origin or self.headers.get("X-Review-Token") != token:
                self.json_response({"error": "Review request must come from this local page"}, 403)
                return
            if self.path != "/decision":
                self.json_response({"error": "Not found"}, 404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("Invalid review request size")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Invalid review request")
                session.record(payload)
            except (ValueError, OSError, TypeError) as error:
                self.json_response({"error": str(error)}, 400)
                return
            self.json_response(session.state())
            if session.report["pending"] == 0:
                print(f"Review saved: {session.directory / 'report.json'}", flush=True)
                print("Tell Codex: caption review finished. Codex owns interpretation and next steps.", flush=True)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, help="Override the saved application data directory")
    parser.add_argument("--prepare-only", action="store_true", help="Prepare the same review without opening a browser")
    args = parser.parse_args()
    paths = build_paths(args.base_dir)
    directory = paths.root / "analytical-pilot" / "e1a-caption-screen"
    bundle_path = directory / "bundle.json"
    try:
        if bundle_path.exists():
            bundle = read_json(bundle_path)
        else:
            bundle = prepare_bundle(Database(paths.database, readonly=True))
            write_new(bundle_path, bundle)
        session = ReviewSession(directory, bundle)
        print(f"Prepared {len(bundle['cases'])} short caption edits. Results: {directory / 'report.json'}", flush=True)
        if not bundle["cases"]:
            print("No usable cases in the bounded search. Tell Codex; no additional decisions or labeling are needed.")
            return
        if args.prepare_only:
            return
        server = HTTPServer(("127.0.0.1", 0), make_handler(session, secrets.token_urlsafe(32)))
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Review page: {url}\nApprove or reject each proposed edit after listening to its short clip. Ctrl-C stops the server; decisions are saved.", flush=True)
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"Caption review could not prepare: {error}\nSend this output to Codex; no manual packet repair is needed.\n")


if __name__ == "__main__":
    main()
