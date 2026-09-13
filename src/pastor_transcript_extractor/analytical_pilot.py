"""Bounded, file-backed E1a falsification audit. Never certifies pastor comparison.

Run with ``python -m pastor_transcript_extractor.analytical_pilot --help``.
Export reads an existing database without migration or inference; evaluate runs only
on the two to four explicitly frozen, human-reviewed sermon packets.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from pastor_transcript_extractor.sermon_analysis import (
    ANALYZER_KEY, ANALYZER_VERSION, SermonSegment, _WORD_PATTERN,
    canonical_sermon_source, detect_scripture_in_segments, load_identified_sermon_source,
)
from pastor_transcript_extractor.scripture_alignment import bible_source_provenance
from pastor_transcript_extractor.storage import Database

PACKET_SCHEMA = "scripture-paired-review@1"
MANIFEST_SCHEMA = "scripture-e1a-manifest@1"
FEATURES = ("references_per_1000_words", "scripture_text_engagement_fraction")


def implementation_hashes() -> dict[str, str]:
    """Pin the audit and detector code as well as their declared versions."""
    return {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("analytical_pilot.py", "sermon_analysis.py", "scripture_alignment.py")
    }


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def write_new(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def export_packet(database: Database, run_id: int, output: Path) -> dict:
    run = database.get_sermon_analysis_run(run_id)
    if run is None or run.analyzer_key != ANALYZER_KEY:
        raise ValueError("An explicit saved Scripture analysis run is required")
    segments, start, duration = load_identified_sermon_source(Path(run.source_path))
    source_hash = hashlib.sha256(canonical_sermon_source(segments, start, duration)).hexdigest()
    if source_hash != run.source_content_sha256:
        raise ValueError("Source no longer matches saved run; locate the original artifact first")
    values = {item.metric_key: json.loads(item.value_json)
              for item in database.list_sermon_analysis_measurements(run.id)}
    evidence = [
        {"id": item.id, "kind": item.evidence_kind,
         "segment_index": item.segment_index, "start_seconds": item.start_seconds,
         "end_seconds": item.end_seconds, "excerpt": item.excerpt,
         "payload": json.loads(item.payload_json)}
        for item in database.list_sermon_analysis_evidence(run.id)
        if item.evidence_kind in {"scripture_reference", "scripture_text_alignment"}
    ]
    video = database.get_video_by_id(run.video_id)
    original = {
        "run_id": run.id, "video_id": run.video_id,
        "source_id": video.source_id if video else None,
        "video_url": video.url if video else None,
        "analyzer_version": run.analyzer_version, "input_fingerprint": run.input_fingerprint,
        "source_path": run.source_path, "source_content_sha256": source_hash,
        "start_seconds": start, "duration_seconds": duration,
        "segments": [asdict(segment) for segment in segments],
        "measurements": values, "evidence": evidence,
    }
    packet = {
        "schema_version": PACKET_SCHEMA, "original": original,
        "review": {
            "status": "unreviewed", "reviewer": None, "reviewed_at": None,
            "profile_id": None, "identity_verified": False,
            "audio_checked": False, "boundaries_verified": False,
            "whole_sermon_reviewed": False, "transcript_method": None,
            "sermon_date": None, "series_id": None, "topic_or_passage": None,
            "translation": None, "notes": "",
            "segments": [
                {"index": i, "text": segment.text, "start_seconds": segment.start_seconds,
                 "end_seconds": segment.end_seconds, "source_segment_indexes": [segment.index]}
                for i, segment in enumerate(segments)
            ],
            "removed_source_segments": [],
            "citation_episodes": [],
            "citation_adjudications": [
                {"evidence_id": item["id"], "judgment": "unreviewed", "episode_id": None}
                for item in evidence if item["kind"] == "scripture_reference"
            ],
            "reviewed_text_spans": [],
        },
    }
    write_new(output, packet)
    return packet


def freeze_manifest(packet_paths: list[Path], output: Path, *, rationale: str,
                    density_iqr: float, span_iqr: float, scale_source: str,
                    maximum_shift_iqr: float = .25) -> dict:
    if not 2 <= len(packet_paths) <= 4:
        raise ValueError("E1a requires two to four distinct original sermons")
    if not rationale.strip() or not scale_source.strip():
        raise ValueError("Selection rationale and frozen scale provenance are required")
    for value in (density_iqr, span_iqr, maximum_shift_iqr):
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Scales and falsification threshold must be finite and positive")
    rows = []
    seen = set()
    for path in packet_paths:
        packet = read_json(path)
        if packet.get("schema_version") != PACKET_SCHEMA:
            raise ValueError("Unsupported packet schema")
        if packet["review"].get("status") != "unreviewed":
            raise ValueError("Freeze the design before reviewing results")
        video_id = packet["original"]["video_id"]
        if video_id in seen:
            raise ValueError("Duplicate original sermon, including alternative runs of one video")
        seen.add(video_id)
        rows.append({"packet_path": str(path.resolve()), "video_id": video_id,
                     "run_id": packet["original"]["run_id"],
                     "original_sha256": digest(packet["original"])})
    manifest = {
        "schema_version": MANIFEST_SCHEMA, "stage": "E1a_falsification",
        "selection_rationale": rationale, "packets": rows,
        "policy": {"version": "e1a-paired-shift@1", "scale_source": scale_source,
                   "population_iqr": dict(zip(FEATURES, (density_iqr, span_iqr), strict=True)),
                   "maximum_absolute_shift_iqr": maximum_shift_iqr,
                   "analyzer_version": ANALYZER_VERSION,
                   "implementation_sha256": implementation_hashes(),
                   "bible_source": bible_source_provenance(),
                   "outcome_without_counterexample": "not_falsified_in_selected_cases_not_certified"},
    }
    write_new(output, manifest)
    return manifest


def finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def validate_review(packet: dict) -> list[SermonSegment]:
    review = packet["review"]
    if review.get("status") != "reviewed":
        raise ValueError("Packet is not reviewed")
    for name in ("identity_verified", "audio_checked", "boundaries_verified", "whole_sermon_reviewed"):
        if review.get(name) is not True:
            raise ValueError(f"Review requires {name}")
    for name in ("reviewer", "reviewed_at", "transcript_method"):
        if not isinstance(review.get(name), str) or not review[name].strip():
            raise ValueError(f"Review requires {name}")
    date.fromisoformat(review["reviewed_at"])
    if type(review.get("profile_id")) is not int or review["profile_id"] <= 0:
        raise ValueError("Reviewed profile ID is required")
    original = packet["original"]
    source_indexes = {item["index"] for item in original["segments"]}
    covered = set()
    result = []
    for i, item in enumerate(review["segments"]):
        origins = item.get("source_segment_indexes")
        if not isinstance(origins, list) or not origins or any(type(v) is not int for v in origins):
            raise ValueError("Each reviewed segment requires source segment provenance")
        if not set(origins) <= source_indexes:
            raise ValueError("Unknown source segment")
        if item.get("index") != i or not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ValueError("Reviewed segments need sequential indexes and nonblank text")
        start = finite_number(item.get("start_seconds"), "segment start")
        end = finite_number(item.get("end_seconds"), "segment end")
        if end <= start or start < original["start_seconds"] or end > original["start_seconds"] + original["duration_seconds"]:
            raise ValueError("E1a representation pairs must retain the frozen sermon window")
        covered.update(origins)
        result.append(SermonSegment(i, start, end, item["text"]))
    for item in review["removed_source_segments"]:
        index = item.get("index")
        if index not in source_indexes or index in covered or not str(item.get("reason", "")).strip():
            raise ValueError("Removed source segments need a unique source index and reason")
        covered.add(index)
    if covered != source_indexes or not result:
        raise ValueError("Every original segment must be mapped or explicitly removed")
    return result


def citation_audit(packet: dict) -> dict:
    review = packet["review"]
    source_indexes = {item["index"] for item in packet["original"]["segments"]}
    episodes = {}
    for episode in review["citation_episodes"]:
        key = episode.get("episode_id")
        if not isinstance(key, str) or not key.strip() or key in episodes:
            raise ValueError("Citation episodes require unique nonblank IDs")
        if not episode.get("canonical_reference") or not episode.get("source_segment_indexes"):
            raise ValueError("Citation episodes require a reference and source segment indexes")
        if not set(episode["source_segment_indexes"]) <= source_indexes:
            raise ValueError("Citation episode has unknown source segments")
        start = finite_number(episode.get("start_seconds"), "episode start")
        end = finite_number(episode.get("end_seconds"), "episode end")
        original = packet["original"]
        if end <= start or start < original["start_seconds"] or end > original["start_seconds"] + original["duration_seconds"]:
            raise ValueError("Citation episode outside frozen sermon window")
        episodes[key] = episode
    evidence_ids = {item["id"] for item in packet["original"]["evidence"] if item["kind"] == "scripture_reference"}
    seen = set()
    recovered = set()
    duplicates = 0
    false_positives = 0
    for item in review["citation_adjudications"]:
        evidence_id = item.get("evidence_id")
        if evidence_id not in evidence_ids or evidence_id in seen:
            raise ValueError("Each original citation detection must be adjudicated exactly once")
        seen.add(evidence_id)
        judgment = item.get("judgment")
        episode_id = item.get("episode_id")
        if judgment in {"episode", "duplicate_caption"}:
            if episode_id not in episodes:
                raise ValueError("Accepted/duplicate detection requires a reviewed episode ID")
            if judgment == "duplicate_caption":
                duplicates += 1
            recovered.add(episode_id)
        elif judgment == "spurious" and episode_id is None:
            false_positives += 1
        else:
            raise ValueError("Citation judgment must be episode, duplicate_caption or spurious")
    if seen != evidence_ids:
        raise ValueError("Unreviewed citation detections remain")
    return {"detected_mentions": len(evidence_ids), "reviewed_distinct_episodes": len(episodes),
            "recovered_distinct_episodes": len(recovered), "duplicate_caption_mentions": duplicates,
            "spurious_mentions": false_positives, "missed_episodes": len(episodes) - len(recovered),
            "distinct_episode_precision": len(recovered) / len(evidence_ids) if evidence_ids else None,
            "episode_recall": len(recovered) / len(episodes) if episodes else None,
            "interpretation": "selected_sermon_audit_no_population_precision_claim"}


def measure_segments(segments: list[SermonSegment]) -> dict:
    references, alignments = detect_scripture_in_segments(segments)
    words = len(_WORD_PATTERN.findall("\n".join(segment.text for segment in segments)))
    chapter_counts = Counter((item["book"], item["chapter"]) for item in references if item["chapter"] is not None)
    sustained = sum(count for count in chapter_counts.values() if count >= 2)
    return {"word_count": words, "detected_references": len(references),
            "references_per_1000_words": 1000 * len(references) / words if words else None,
            "scripture_text_engagement_fraction": sum(int(item["transcript_span_word_count"]) for item in alignments) / words if words else None,
            "sustained_chapter_reference_ratio": sustained / len(references) if references else None}


def evaluate_manifest(manifest_path: Path) -> dict:
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA or manifest.get("stage") != "E1a_falsification":
        raise ValueError("Only a frozen E1a falsification manifest is supported; E1b certification is deferred")
    policy = manifest["policy"]
    if policy.get("implementation_sha256") != implementation_hashes():
        raise ValueError("Audit or detector implementation changed since design freeze")
    if policy["analyzer_version"] != ANALYZER_VERSION or policy["bible_source"] != bible_source_provenance():
        raise ValueError("Detector or Bible artifact changed since design freeze")
    if not 2 <= len(manifest["packets"]) <= 4:
        raise ValueError("E1a supports only two to four explicitly selected sermons")
    for value in [*policy["population_iqr"].values(), policy["maximum_absolute_shift_iqr"]]:
        if finite_number(value, "policy value") <= 0:
            raise ValueError("Policy scales/threshold must be positive")
    rows = []
    seen = set()
    # Validate every packet before any detector work.
    reviewed_inputs = []
    for entry in manifest["packets"]:
        path = Path(entry["packet_path"])
        packet = read_json(path)
        original = packet["original"]
        if packet.get("schema_version") != PACKET_SCHEMA or digest(original) != entry["original_sha256"]:
            raise ValueError("Frozen original packet was modified")
        if original["video_id"] in seen or original["video_id"] != entry["video_id"] or original["run_id"] != entry["run_id"]:
            raise ValueError("Duplicate/mismatched original sermon")
        if original["analyzer_version"] != ANALYZER_VERSION:
            raise ValueError("Original analyzer differs; create a separately versioned audit")
        seen.add(original["video_id"])
        segments = validate_review(packet)
        audit = citation_audit(packet)
        reviewed_inputs.append((path, packet, segments, audit))
    for path, packet, segments, audit in reviewed_inputs:
        original = packet["original"]
        before = measure_segments([SermonSegment(**item) for item in original["segments"]])
        saved = original["measurements"]
        expected = (saved.get("word_count"), saved.get("scripture_reference_mentions"))
        if (before["word_count"], before["detected_references"]) != expected:
            raise ValueError("Current detector does not reconstruct saved counts; investigate version drift")
        saved_span = saved.get("scripture_aligned_transcript_span_words")
        if before["word_count"] == 0:
            raise ValueError("Original transcript has no measurable words")
        if saved_span is None or not math.isclose(before["scripture_text_engagement_fraction"] * before["word_count"], saved_span, abs_tol=1e-6):
            raise ValueError("Current detector does not reconstruct saved aligned-span count")
        after = measure_segments(segments)
        shifts = {}
        for feature in FEATURES:
            delta = after[feature] - before[feature] if before[feature] is not None and after[feature] is not None else None
            scaled = abs(delta) / policy["population_iqr"][feature] if delta is not None else None
            shifts[feature] = {"signed_shift": delta, "absolute_shift_in_frozen_iqr": scaled,
                               "counterexample_to_selected_bound": scaled > policy["maximum_absolute_shift_iqr"] if scaled is not None else None}
        rows.append({"packet_path": str(path), "reviewed_packet_sha256": digest(packet),
                     "run_id": original["run_id"], "video_id": original["video_id"],
                     "reviewed_profile_id": packet["review"]["profile_id"],
                     "original": before, "reviewed": after, "shifts": shifts, "citation_audit": audit})
    feature_outcomes = {}
    for feature in FEATURES:
        results = [row["shifts"][feature]["counterexample_to_selected_bound"] for row in rows]
        feature_outcomes[feature] = ("counterexample_found" if any(value is True for value in results)
                                     else "inconclusive" if any(value is None for value in results)
                                     else "not_falsified_in_selected_cases_not_certified")
    return {"schema_version": "scripture-e1a-report@1", "stage": "E1a_falsification",
            "manifest_sha256": digest(manifest), "policy": policy,
            "certified_features": [], "feature_outcomes": feature_outcomes, "sermons": rows,
            "limitations": ["Purposive counterexamples do not estimate prevalence or certify error bounds.",
                            "No E1b cluster intervals, translation/span ground-truth accuracy or pastor reliability is estimated.",
                            "No automatic normalization or corpus backfill was performed."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Export one exact saved run without analysis")
    export.add_argument("--database", type=Path, required=True)
    export.add_argument("--run-id", type=int, required=True)
    export.add_argument("--output", type=Path, required=True)
    freeze = commands.add_parser("freeze", help="Freeze two to four unreviewed packets before the audit")
    freeze.add_argument("--packet", type=Path, action="append", required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--rationale", required=True)
    freeze.add_argument("--density-iqr", type=float, required=True)
    freeze.add_argument("--span-iqr", type=float, required=True)
    freeze.add_argument("--scale-source", required=True)
    freeze.add_argument("--maximum-shift-iqr", type=float, default=.25)
    evaluate = commands.add_parser("evaluate", help="Run only the frozen E1a packet audit; never certify")
    evaluate.add_argument("manifest", type=Path)
    evaluate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("Output already exists; choose a new path to preserve the prior artifact")
        if args.command == "export":
            export_packet(Database(args.database, readonly=True), args.run_id, args.output)
        elif args.command == "freeze":
            freeze_manifest(args.packet, args.output, rationale=args.rationale,
                            density_iqr=args.density_iqr, span_iqr=args.span_iqr,
                            scale_source=args.scale_source, maximum_shift_iqr=args.maximum_shift_iqr)
        else:
            write_new(args.output, evaluate_manifest(args.manifest))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(args.output.resolve())


if __name__ == "__main__":
    main()
