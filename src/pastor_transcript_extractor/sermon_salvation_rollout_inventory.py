"""Read-only, cache-first inventory for broader use of the frozen nine leaves."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.analysis_artifact_cache import (
    database_snapshot as _database_snapshot,
    file_signature as _file_signature,
)
from pastor_transcript_extractor.sermon_classifier_typesafe import (
    BATCH_SIZE,
    MAX_FINE_QUESTION_BUDGET,
)
from pastor_transcript_extractor.sermon_policy import video_is_sermon_eligible
from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
    SALVATION_RELATIONSHIPS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
    UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS,
    refresh_salvation_relationship_projection,
    resolve_salvation_relationship_analysis_artifact,
    salvation_relationship_pack_digest,
    salvation_route_decision,
)
from pastor_transcript_extractor.sermon_topic_profile_analysis import read_classification_for_gate
from pastor_transcript_extractor.sermon_topic_projection import assess_topic_profile_projection
from pastor_transcript_extractor.sermon_topic_stage4 import _canonical_hash
from pastor_transcript_extractor.sermon_topics import (
    TOPIC_PACK_VERSION,
    resolve_topic_analysis_artifact,
    resolve_topic_block_context,
)
from pastor_transcript_extractor.storage import Database


POLICY_VERSION = "salvation-broader-rollout-inventory-v1"
DEFAULT_OUTPUT = Path("evaluation/sermon-topics/salvation-broader-rollout-inventory-v1.json")
DEFAULT_DECISION = Path("evaluation/sermon-topics/salvation-nine-leaf-stage-gate-v1.json")
LEAF_BATCH_SIZE = max(1, min(BATCH_SIZE, MAX_FINE_QUESTION_BUDGET // len(SALVATION_RELATIONSHIPS)))
PROFILE_ONLY_REASON_CODES = frozenset({
    "current_speaker_observation_unavailable",
    "effective_profile_membership_unavailable",
    "membership_review_provenance_missing",
    "ambiguous_effective_profile_membership",
    "canonical_profile_unavailable",
    "profile_lifecycle_ineligible",
})


def _validate_decision(decision: Mapping[str, Any]) -> None:
    identity = {key: value for key, value in decision.items() if key != "input_fingerprint"}
    if _canonical_hash(identity) != decision.get("input_fingerprint"):
        raise ValueError("Salvation stage-gate decision fingerprint does not match")
    if (decision.get("policy_version") != "salvation-nine-leaf-stage-gate-v1"
            or decision.get("salvation_relationship_questions") != "ready_for_broader_analysis"
            or decision.get("observation_policy_version") != SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
            or decision.get("approved_relationships") != list(SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS)
            or set(decision.get("excluded_unresolved_relationships", [])) !=
            set(UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS)):
        raise ValueError("Broader rollout requires the approved frozen nine-leaf decision")


class _CachedGateDatabase:
    """Avoid repeatedly loading global review ledgers during per-video gate checks."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.observations_by_video: dict[int, list[Any]] = {}
        observation_video: dict[int, int] = {}
        for observation in database.list_speaker_observations():
            self.observations_by_video.setdefault(observation.video_id, []).append(observation)
            observation_video[observation.id] = observation.video_id
        self.events_by_video: dict[int, list[Any]] = {}
        for event in database.list_effective_profile_observation_events():
            video_id = observation_video.get(event[2])
            if video_id is not None:
                self.events_by_video.setdefault(video_id, []).append(event)
        self.current_video_id: int | None = None
        self.profiles: dict[int, Any] = {}
        self.canonical: dict[int, int] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self.database, name)

    def list_speaker_observations(self) -> list[Any]:
        return self.observations_by_video.get(self.current_video_id, [])

    def list_effective_profile_observation_events(self) -> list[Any]:
        return self.events_by_video.get(self.current_video_id, [])

    def set_current_video(self, video_id: int) -> None:
        self.current_video_id = video_id

    def get_speaker_profile(self, profile_id: int) -> Any:
        if profile_id not in self.profiles:
            self.profiles[profile_id] = self.database.get_speaker_profile(profile_id)
        return self.profiles[profile_id]

    def resolve_speaker_profile_id(self, profile_id: int) -> int:
        if profile_id not in self.canonical:
            self.canonical[profile_id] = self.database.resolve_speaker_profile_id(profile_id)
        return self.canonical[profile_id]


def _inspect_video(database: Database, video: Any) -> dict[str, Any]:
    gate = assess_topic_profile_projection(database, video)
    content_reasons = [reason for reason in gate.reason_codes
                       if reason not in PROFILE_ONLY_REASON_CODES]
    if (gate.topic_analysis_fingerprint is not None
            and gate.topic_question_pack_version != TOPIC_PACK_VERSION):
        content_reasons.append("topic_question_pack_mismatch")
    item: dict[str, Any] = {
        "video_id": video.id, "youtube_video_id": video.youtube_video_id,
        "title": video.title, "source_id": video.source_id,
        "configured_pastor_id": video.pastor_id,
        "content_gate_eligible": not content_reasons,
        "content_gate_reason_codes": content_reasons,
        "profile_gate_eligible": gate.eligible,
        "profile_gate_reason_codes": list(gate.reason_codes),
        "gate_input_fingerprint": gate.input_fingerprint,
        "canonical_profile_id": gate.profile_id,
        "classification_path": gate.source_path,
        "classification_sha256": None,
        "topic_artifact_sha256": gate.topic_analysis_fingerprint,
        "leaf_artifact_sha256": None,
        "routed_topic_block_count": None,
        "missing_routed_block_ids": [],
        "missing_routed_block_count": None,
        "missing_target_text_chars": None,
        "status": "upstream_content_gate_blocked",
    }
    if content_reasons:
        return item
    source_before = _file_signature(gate.source_path)
    classification = read_classification_for_gate(gate)
    item["classification_sha256"] = _canonical_hash(classification)
    topic = resolve_topic_analysis_artifact(classification)
    if (_canonical_hash(topic) != gate.topic_analysis_fingerprint
            or _file_signature(gate.source_path) != source_before):
        raise ValueError(f"Video {video.id} classification changed during inventory; rerun")
    topic_blocks = topic.get("blocks")
    if not isinstance(topic_blocks, list):
        raise ValueError(f"Video {video.id} has malformed topic blocks")
    routed = {int(block["block_id"]): block for block in topic_blocks
              if isinstance(block, Mapping) and salvation_route_decision(block)["route"]}
    item["routed_topic_block_count"] = len(routed)
    if not routed:
        item.update(status="ready_zero_routed_blocks", missing_routed_block_count=0,
                    missing_target_text_chars=0)
        return item
    try:
        stored = resolve_salvation_relationship_analysis_artifact(classification)
    except ValueError as error:
        if "no cached TypeSafe salvation relationship analysis" not in str(error):
            raise
        stored = None
    if stored is None:
        missing = sorted(routed)
        item["status"] = "missing_leaf_artifact"
    else:
        item["leaf_artifact_sha256"] = _canonical_hash(stored)
        if (stored.get("question_pack_version") != SALVATION_RELATIONSHIPS_PACK_VERSION
                or stored.get("question_pack_digest") != salvation_relationship_pack_digest()):
            missing = sorted(routed)
            item["status"] = "stale_leaf_pack"
        else:
            artifact = deepcopy(dict(stored))
            try:
                refresh_salvation_relationship_projection(artifact, topic)
            except (KeyError, TypeError, ValueError):
                missing = sorted(routed)
                item["status"] = "invalid_leaf_artifact"
            else:
                missing = sorted(int(value) for value in artifact["missing_current_routed_block_ids"])
                item["status"] = ("partial_leaf_artifact" if missing else "ready_cached_leaf_artifact")
    item["missing_routed_block_ids"] = missing
    item["missing_routed_block_count"] = len(missing)
    item["missing_target_text_chars"] = sum(
        len(str(resolve_topic_block_context(routed[block_id]).get("target_text") or ""))
        for block_id in missing
    )
    return item


def build_rollout_inventory(
    records: Sequence[Mapping[str, Any]],
    *,
    total_videos: int,
    production_ineligible_count: int,
    decision: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    source_files: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate exact cached coverage and bounded missing-work units."""
    _validate_decision(decision)
    rows = sorted((dict(row) for row in records), key=lambda row: int(row["video_id"]))
    if len({int(row["video_id"]) for row in rows}) != len(rows):
        raise ValueError("Rollout inventory contains duplicate videos")
    if total_videos != production_ineligible_count + len(rows):
        raise ValueError("Rollout inventory video totals do not reconcile")
    ready = [row for row in rows if row["status"].startswith("ready_")]
    missing = [row for row in rows if row["status"] in {
        "missing_leaf_artifact", "stale_leaf_pack", "invalid_leaf_artifact", "partial_leaf_artifact"}]
    upstream = [row for row in rows if row["status"] == "upstream_content_gate_blocked"]
    blocked_reasons = Counter(reason for row in upstream for reason in row["content_gate_reason_codes"])
    profile_reasons = Counter(reason for row in rows for reason in row["profile_gate_reason_codes"]
                              if reason in PROFILE_ONLY_REASON_CODES)
    status_counts = Counter(str(row["status"]) for row in rows)
    missing_blocks = sum(int(row["missing_routed_block_count"]) for row in missing)
    requests_if_all_cache_miss_min = sum(
        math.ceil(int(row["missing_routed_block_count"]) / LEAF_BATCH_SIZE) for row in missing
    )
    identity = {
        "schema_version": 1, "policy_version": POLICY_VERSION,
        "decision_fingerprint": decision["input_fingerprint"],
        "topic_pack_version": TOPIC_PACK_VERSION,
        "observation_policy_version": SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
        "observation_thresholds": dict(SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS),
        "leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "leaf_pack_digest": salvation_relationship_pack_digest(),
        "snapshot": dict(snapshot), "source_files": list(source_files),
        "counts": {"all_videos": total_videos,
                   "production_ineligible": production_ineligible_count,
                   "production_eligible": len(rows),
                   "content_gate_eligible": len(ready) + len(missing),
                   "profile_gate_eligible": sum(bool(row["profile_gate_eligible"]) for row in rows),
                   "nine_leaf_ready": len(ready),
                   "nine_leaf_ready_cached_artifact": sum(row["status"] == "ready_cached_leaf_artifact" for row in ready),
                   "nine_leaf_ready_zero_route": sum(row["status"] == "ready_zero_routed_blocks" for row in ready),
                   "eligible_missing_or_stale_leaf_evidence": len(missing),
                   "upstream_content_gate_blocked": len(upstream)},
        "status_counts": dict(sorted(status_counts.items())),
        "upstream_content_gate_reason_counts": dict(sorted(blocked_reasons.items())),
        "profile_gate_reason_counts": dict(sorted(profile_reasons.items())),
        "work_estimate": {
            "missing_leaf_video_count": len(missing),
            "missing_routed_block_count": missing_blocks,
            "leaf_questions_per_missing_block": len(SALVATION_RELATIONSHIPS),
            "leaf_question_evaluations_if_no_cache": missing_blocks * len(SALVATION_RELATIONSHIPS),
            "missing_target_text_chars": sum(int(row["missing_target_text_chars"]) for row in missing),
            "leaf_batch_size_before_provider_splitting": LEAF_BATCH_SIZE,
            "structural_provider_request_range_including_unknown_pack_cache":
                [0, max(0, 2 * missing_blocks - requests_if_all_cache_miss_min)],
            "provider_requests_if_all_packs_miss_before_token_splitting": requests_if_all_cache_miss_min,
            "upstream_content_gate_blocked_video_count_not_costed": len(upstream),
            "estimate_scope": "Missing routed leaf blocks on production-eligible, content-gate-eligible recordings, regardless of pastor profile linkage. The request range allows recursive token-limit splitting under one attempt per node; transport retries, other failures, and upstream work are not priced. Exact local per-block cache hits are unknown until replay.",
        },
        "videos": rows,
    }
    return {**identity, "input_fingerprint": _canonical_hash(identity),
            "provider_requests": 0,
            "status": "provider_free_rollout_inventory",
            "interpretation": "Content readiness describes reusable cached question evidence regardless of pastor linkage. Profile gate status is separate and does not establish pastor-level theology or approval to run provider calls. Upstream content failures are separate from missing leaf work."}


def evaluate_rollout_inventory(database: Database, decision: Mapping[str, Any], now: datetime | None = None) -> dict[str, Any]:
    _validate_decision(decision)
    current = now or datetime.now(timezone.utc)
    snapshot = _database_snapshot(database.database_path, current)
    cached_database = _CachedGateDatabase(database)
    videos = database.list_videos()
    eligible = [video for video in videos if video_is_sermon_eligible(
        video.duration_seconds, video.published_at, now=current)]
    records = []
    for video in eligible:
        cached_database.set_current_video(video.id)
        records.append(_inspect_video(cached_database, video))
    source_files = [_file_signature(path) for path in sorted({row["classification_path"]
                                                            for row in records if row["classification_path"]})]
    if _database_snapshot(database.database_path, current) != snapshot:
        raise ValueError("Application database changed during rollout inventory; rerun on a stable snapshot")
    return build_rollout_inventory(records, total_videos=len(videos),
                                   production_ineligible_count=len(videos) - len(eligible),
                                   decision=decision, snapshot=snapshot,
                                   source_files=source_files)


def reusable_inventory(path: Path, database_path: Path, decision: Mapping[str, Any],
                       now: datetime | None = None) -> dict[str, Any] | None:
    """Reuse only when DB, policy, decision, and every source-file stat match."""
    _validate_decision(decision)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if (report.get("policy_version") != POLICY_VERSION
                or report.get("decision_fingerprint") != decision.get("input_fingerprint")
                or report.get("topic_pack_version") != TOPIC_PACK_VERSION
                or report.get("observation_thresholds") != SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS
                or report.get("leaf_pack_version") != SALVATION_RELATIONSHIPS_PACK_VERSION
                or report.get("leaf_pack_digest") != salvation_relationship_pack_digest()
                or report.get("snapshot") != _database_snapshot(database_path, now or datetime.now(timezone.utc))):
            return None
        files = report.get("source_files")
        if not isinstance(files, list) or any(_file_signature(item.get("path")) != item for item in files):
            return None
        identity = {key: value for key, value in report.items() if key not in {
            "input_fingerprint", "provider_requests", "status", "interpretation"}}
        return report if _canonical_hash(identity) == report.get("input_fingerprint") else None
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, AttributeError):
        return None


def render_rollout_inventory(report: Mapping[str, Any]) -> str:
    counts = report["counts"]
    work = report["work_estimate"]
    lines = ["# Nine-leaf salvation broader-corpus rollout inventory", "",
             f"- Fingerprint: `{report['input_fingerprint']}`",
             f"- Approved stage gate: `{report['decision_fingerprint']}`",
             "- Provider requests: 0", "",
             "| Corpus gate | Videos |", "| --- | ---: |",
             f"| All known videos | {counts['all_videos']} |",
             f"| Production eligible | {counts['production_eligible']} |",
             f"| Content gate eligible | {counts['content_gate_eligible']} |",
             f"| Profile gate eligible (separate) | {counts['profile_gate_eligible']} |",
             f"| Nine-leaf evidence ready | {counts['nine_leaf_ready']} |",
             f"| Ready from cached leaf artifact | {counts['nine_leaf_ready_cached_artifact']} |",
             f"| Ready with zero routed blocks | {counts['nine_leaf_ready_zero_route']} |",
             f"| Eligible but leaf evidence missing/stale | {counts['eligible_missing_or_stale_leaf_evidence']} |",
             f"| Upstream content gate blocked | {counts['upstream_content_gate_blocked']} |", "",
             "## Bounded missing leaf work", "",
             f"- Videos: {work['missing_leaf_video_count']}",
             f"- Routed blocks lacking reusable stored leaf evidence: {work['missing_routed_block_count']}",
             f"- Twelve-question pack evaluations if every missing block misses local cache: {work['leaf_question_evaluations_if_no_cache']}",
             f"- Missing routed target text characters: {work['missing_target_text_chars']}",
             f"- Structural provider request range before exact cache replay: 0–{work['structural_provider_request_range_including_unknown_pack_cache'][1]}",
             f"- If all packs miss, at least {work['provider_requests_if_all_packs_miss_before_token_splitting']} batches before token-driven splitting (batch size {LEAF_BATCH_SIZE}).", "",
             "The request range covers batching and recursive token-limit splits under one",
             "attempt per node; it excludes transport retries and other failures. It is not a",
             "token or dollar quote. Existing per-block cache answers may eliminate calls. Videos",
             "blocked upstream are excluded from the leaf-work estimate. Exact video IDs, gate",
             "reasons, artifact hashes, and missing block IDs are in the JSON report.",
             "Pastor profile linkage is reported separately from question-level content readiness.", "",
             "## Next iteration", "",
             "Review the inventory for current cache coverage and named upstream blockers. Prepare",
             "a bounded rollout batch and first-run request-shape checks before any provider run.",
             "Keep the three unresolved leaves excluded and pastor-level sample-size policy separate.", ""]
    return "\n".join(lines)


def write_rollout_inventory(path: Path, report: Mapping[str, Any]) -> tuple[Path, Path, bool]:
    path = path.expanduser().resolve()
    markdown = path.with_suffix(".md")
    rendered = render_rollout_inventory(report)
    if path.is_file() and markdown.is_file():
        try:
            if (json.loads(path.read_text(encoding="utf-8")).get("input_fingerprint") == report["input_fingerprint"]
                    and markdown.read_text(encoding="utf-8") == rendered):
                return path, markdown, True
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown.write_text(rendered, encoding="utf-8")
    return path, markdown, False
