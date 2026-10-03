"""Immutable adjudications over cached TypeSafe topic review packets."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from pastor_transcript_extractor.sermon_topics import TOPICS


TOPIC_REVIEW_ADJUDICATION_SCHEMA_VERSION = 1
TOPIC_REVIEW_ADJUDICATION_WORKFLOW_VERSION = "topic-review-adjudication-v1"


@dataclass(frozen=True, slots=True)
class TopicReviewDraftResult:
    json_path: Path
    markdown_path: Path
    source_packet_fingerprint: str
    reused: bool


@dataclass(frozen=True, slots=True)
class TopicReviewFinalizationResult:
    json_path: Path
    review_fingerprint: str
    reused: bool
    topic_correction_count: int
    projection_correction_count: int


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read {label}: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label.capitalize()} is not a JSON object: {path}")
    return payload


def _validate_source_packet(packet: Mapping[str, Any]) -> tuple[str, str, list[int]]:
    fingerprint = packet.get("input_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError("Topic review packet has no input_fingerprint")
    generator = packet.get("generator_version")
    if not isinstance(generator, str) or not generator:
        raise ValueError("Topic review packet has no generator_version")
    blocks = packet.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("Topic review packet has no blocks")
    block_ids = [
        int(block["block_id"])
        for block in blocks
        if isinstance(block, Mapping)
        and isinstance(block.get("block_id"), int)
        and not isinstance(block.get("block_id"), bool)
    ]
    if len(block_ids) != len(blocks) or len(set(block_ids)) != len(block_ids):
        raise ValueError("Topic review packet has invalid or duplicate block ids")
    return fingerprint, generator, block_ids


def _required_checks(packet: Mapping[str, Any]) -> list[str]:
    checks = ["selected_blocks_reviewed"]
    selection = packet.get("selection")
    if isinstance(selection, Mapping) and selection.get("mode") == "whole_sermon":
        checks.extend(
            [
                "missed_topic_episode_search_complete",
                "projection_boundary_review_complete",
            ]
        )
    return checks


def _source_packet_descriptor(
    packet: Mapping[str, Any],
    *,
    path: str,
    sha256: str,
) -> dict[str, Any]:
    fingerprint, generator, _ = _validate_source_packet(packet)
    source = packet.get("source")
    selection = packet.get("selection")
    return {
        "path": path,
        "sha256": sha256,
        "input_fingerprint": fingerprint,
        "generator_version": generator,
        "schema_version": packet.get("schema_version"),
        "selection_mode": (
            selection.get("mode") if isinstance(selection, Mapping) else None
        ),
        "video_id": source.get("video_id") if isinstance(source, Mapping) else None,
        "youtube_video_id": (
            source.get("youtube_video_id") if isinstance(source, Mapping) else None
        ),
        "topic_question_pack_version": (
            source.get("question_pack_version")
            if isinstance(source, Mapping)
            else None
        ),
    }


def build_topic_review_adjudication_draft(
    packet: Mapping[str, Any],
    *,
    source_packet_path: str,
    source_packet_sha256: str,
) -> dict[str, Any]:
    """Build a separate review layer without modifying cached observations."""
    _validate_source_packet(packet)
    return {
        "schema_version": TOPIC_REVIEW_ADJUDICATION_SCHEMA_VERSION,
        "workflow_version": TOPIC_REVIEW_ADJUDICATION_WORKFLOW_VERSION,
        "review_status": "unreviewed",
        "source_packet": _source_packet_descriptor(
            packet,
            path=source_packet_path,
            sha256=source_packet_sha256,
        ),
        "required_checks": _required_checks(packet),
        "checks": {
            "selected_blocks_reviewed": False,
            "missed_topic_episode_search_complete": False,
            "projection_boundary_review_complete": False,
        },
        "topic_level_corrections": [],
        "projection_eligibility_corrections": [],
        "notes": "",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_fingerprint": None,
    }


def render_topic_review_adjudication_markdown(draft: Mapping[str, Any]) -> str:
    source = draft["source_packet"]
    checks = draft["required_checks"]
    return "\n".join(
        [
            "# TypeSafe Topic Review Adjudication",
            "",
            f"- Video: database #{source.get('video_id')} / "
            f"`{source.get('youtube_video_id')}`",
            f"- Selection mode: `{source.get('selection_mode')}`",
            f"- Topic pack: `{source.get('topic_question_pack_version')}`",
            f"- Source packet fingerprint: `{source.get('input_fingerprint')}`",
            f"- Source packet SHA-256: `{source.get('sha256')}`",
            "",
            "Review the source packet's Markdown inspection view. This draft stores only "
            "the review decision; it never changes the cached TypeSafe observations.",
            "",
            "## Required confirmations",
            "",
            *[f"- [ ] `{check}`" for check in checks],
            "",
            "If every displayed modal prominence level and projection decision is "
            "acceptable, finalize with `--accept-as-reviewed`. Otherwise edit the JSON "
            "draft first, add only the necessary corrections, and set the required "
            "check fields to `true`.",
            "",
            "A topic correction has `block_ids`, `topic`, `reviewed_level` (0-4), and "
            "non-empty `notes`. A projection correction has `block_id`, `eligible`, "
            "and non-empty `notes`.",
            "",
        ]
    )


def create_topic_review_adjudication_draft(
    packet_path: Path,
    output_path: Path,
) -> TopicReviewDraftResult:
    """Create or reuse a draft bound to the exact source packet bytes."""
    packet_path = packet_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    packet = _read_object(packet_path, "topic review packet")
    fingerprint, _, _ = _validate_source_packet(packet)
    relative_source = os.path.relpath(packet_path, output_path.parent)
    draft = build_topic_review_adjudication_draft(
        packet,
        source_packet_path=relative_source,
        source_packet_sha256=_file_sha256(packet_path),
    )
    expected_json = json.dumps(draft, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    expected_markdown = render_topic_review_adjudication_markdown(draft)
    markdown_path = output_path.with_suffix(".md")
    if output_path.exists():
        existing = _read_object(output_path, "topic review adjudication draft")
        existing_source = existing.get("source_packet")
        if (
            isinstance(existing_source, Mapping)
            and existing_source.get("sha256") == draft["source_packet"]["sha256"]
            and existing != draft
        ):
            raise ValueError(
                "Existing adjudication draft contains review edits; refusing to overwrite it"
            )
        if (
            existing == draft
            and markdown_path.exists()
            and markdown_path.read_text(encoding="utf-8") == expected_markdown
        ):
            return TopicReviewDraftResult(
                output_path, markdown_path, fingerprint, True
            )
        raise ValueError("Adjudication draft output already belongs to another input")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(expected_json, encoding="utf-8")
    markdown_path.write_text(expected_markdown, encoding="utf-8")
    return TopicReviewDraftResult(output_path, markdown_path, fingerprint, False)


def _resolve_source_packet(
    draft_path: Path,
    draft: Mapping[str, Any],
) -> tuple[Path, dict[str, Any], list[int]]:
    source = draft.get("source_packet")
    if not isinstance(source, Mapping):
        raise ValueError("Adjudication draft has no source_packet object")
    raw_path = source.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("Adjudication draft has no source packet path")
    packet_path = Path(raw_path).expanduser()
    if not packet_path.is_absolute():
        packet_path = draft_path.parent / packet_path
    packet_path = packet_path.resolve()
    packet = _read_object(packet_path, "source topic review packet")
    fingerprint, generator, block_ids = _validate_source_packet(packet)
    source_sha256 = _file_sha256(packet_path)
    if source.get("sha256") != source_sha256:
        raise ValueError("Source topic review packet content hash has changed")
    if source.get("input_fingerprint") != fingerprint:
        raise ValueError("Source topic review packet fingerprint has changed")
    if source.get("generator_version") != generator:
        raise ValueError("Source topic review packet generator has changed")
    expected_source = _source_packet_descriptor(
        packet,
        path=raw_path,
        sha256=source_sha256,
    )
    if dict(source) != expected_source:
        raise ValueError("Adjudication draft source metadata does not match its packet")
    return packet_path, packet, block_ids


def _validated_corrections(
    draft: Mapping[str, Any],
    *,
    block_ids: list[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid_blocks = set(block_ids)
    raw_topic = draft.get("topic_level_corrections")
    if not isinstance(raw_topic, list):
        raise ValueError("topic_level_corrections must be a list")
    topic_corrections: list[dict[str, Any]] = []
    seen_topic_blocks: set[tuple[int, str]] = set()
    for item in raw_topic:
        if not isinstance(item, Mapping):
            raise ValueError("Every topic-level correction must be an object")
        corrected_blocks = item.get("block_ids")
        topic = item.get("topic")
        level = item.get("reviewed_level")
        notes = item.get("notes")
        if (
            not isinstance(corrected_blocks, list)
            or not corrected_blocks
            or any(
                not isinstance(block_id, int)
                or isinstance(block_id, bool)
                or block_id not in valid_blocks
                for block_id in corrected_blocks
            )
        ):
            raise ValueError("Topic correction block_ids must name source packet blocks")
        if topic not in TOPICS:
            raise ValueError(f"Unknown topic correction key: {topic!r}")
        if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 4:
            raise ValueError("Topic correction reviewed_level must be an integer from 0 to 4")
        if not isinstance(notes, str) or not notes.strip():
            raise ValueError("Topic corrections require non-empty notes")
        normalized_blocks = list(dict.fromkeys(corrected_blocks))
        for block_id in normalized_blocks:
            identity = (block_id, str(topic))
            if identity in seen_topic_blocks:
                raise ValueError(
                    f"Duplicate topic correction for block {block_id} and {topic}"
                )
            seen_topic_blocks.add(identity)
        topic_corrections.append(
            {
                "block_ids": normalized_blocks,
                "topic": str(topic),
                "reviewed_level": level,
                "notes": notes.strip(),
            }
        )

    raw_projection = draft.get("projection_eligibility_corrections")
    if not isinstance(raw_projection, list):
        raise ValueError("projection_eligibility_corrections must be a list")
    projection_corrections: list[dict[str, Any]] = []
    seen_projection_blocks: set[int] = set()
    for item in raw_projection:
        if not isinstance(item, Mapping):
            raise ValueError("Every projection correction must be an object")
        block_id = item.get("block_id")
        eligible = item.get("eligible")
        notes = item.get("notes")
        if (
            not isinstance(block_id, int)
            or isinstance(block_id, bool)
            or block_id not in valid_blocks
        ):
            raise ValueError("Projection correction block_id must name a source packet block")
        if block_id in seen_projection_blocks:
            raise ValueError(f"Duplicate projection correction for block {block_id}")
        if not isinstance(eligible, bool):
            raise ValueError("Projection correction eligible must be boolean")
        if not isinstance(notes, str) or not notes.strip():
            raise ValueError("Projection corrections require non-empty notes")
        seen_projection_blocks.add(block_id)
        projection_corrections.append(
            {"block_id": block_id, "eligible": eligible, "notes": notes.strip()}
        )
    return topic_corrections, projection_corrections


def finalize_topic_review_adjudication(
    draft_path: Path,
    output_path: Path,
    *,
    reviewer: str,
    accept_as_reviewed: bool = False,
) -> TopicReviewFinalizationResult:
    """Validate review decisions and freeze them separately from model evidence."""
    draft_path = draft_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    draft = _read_object(draft_path, "topic review adjudication draft")
    if draft.get("schema_version") != TOPIC_REVIEW_ADJUDICATION_SCHEMA_VERSION:
        raise ValueError("Unsupported topic review adjudication schema_version")
    if draft.get("workflow_version") != TOPIC_REVIEW_ADJUDICATION_WORKFLOW_VERSION:
        raise ValueError("Unsupported topic review adjudication workflow_version")
    if draft.get("review_status") != "unreviewed":
        raise ValueError("Topic review adjudication draft is already finalized")
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("Reviewer must not be blank")
    packet_path, packet, block_ids = _resolve_source_packet(draft_path, draft)
    checks = draft.get("checks")
    required_checks = draft.get("required_checks")
    if not isinstance(checks, Mapping) or not isinstance(required_checks, list):
        raise ValueError("Adjudication draft has invalid review checks")
    if required_checks != _required_checks(packet):
        raise ValueError("Adjudication draft required checks do not match its source packet")
    normalized_checks = dict(checks)
    if accept_as_reviewed:
        for check in required_checks:
            normalized_checks[str(check)] = True
    incomplete = [
        str(check) for check in required_checks if normalized_checks.get(str(check)) is not True
    ]
    if incomplete:
        raise ValueError("Incomplete required review checks: " + ", ".join(incomplete))
    topic_corrections, projection_corrections = _validated_corrections(
        draft, block_ids=block_ids
    )
    source_sha256 = _file_sha256(packet_path)
    finalized_source = _source_packet_descriptor(
        packet,
        path=os.path.relpath(packet_path, output_path.parent),
        sha256=source_sha256,
    )
    logical_source = {
        key: value for key, value in finalized_source.items() if key != "path"
    }
    logical_review = {
        "workflow_version": TOPIC_REVIEW_ADJUDICATION_WORKFLOW_VERSION,
        "source_packet": logical_source,
        "required_checks": required_checks,
        "checks": normalized_checks,
        "topic_level_corrections": topic_corrections,
        "projection_eligibility_corrections": projection_corrections,
        "notes": str(draft.get("notes") or "").strip(),
        "reviewed_by": reviewer,
    }
    review_fingerprint = _canonical_hash(logical_review)
    if output_path.exists():
        existing = _read_object(output_path, "finalized topic review adjudication")
        if existing.get("review_fingerprint") == review_fingerprint:
            return TopicReviewFinalizationResult(
                output_path,
                review_fingerprint,
                True,
                len(topic_corrections),
                len(projection_corrections),
            )
        raise ValueError("Finalized adjudication output already contains another review")
    finalized = {
        **draft,
        "source_packet": finalized_source,
        "review_status": "reviewed",
        "checks": normalized_checks,
        "topic_level_corrections": topic_corrections,
        "projection_eligibility_corrections": projection_corrections,
        "notes": logical_review["notes"],
        "reviewed_by": reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "review_fingerprint": review_fingerprint,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(finalized, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return TopicReviewFinalizationResult(
        output_path,
        review_fingerprint,
        False,
        len(topic_corrections),
        len(projection_corrections),
    )
