"""Deterministic review packets for cached TypeSafe sermon-topic observations."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.sermon_topics import TOPICS


TOPIC_REVIEW_SCHEMA_VERSION = 1
TOPIC_REVIEW_GENERATOR_VERSION = "typesafe-topic-review-v1"


@dataclass(frozen=True, slots=True)
class TopicReviewCase:
    case_id: str
    label: str
    block_ids: tuple[int, ...]
    review_focus: str
    reviewed_interpretation: str


@dataclass(frozen=True, slots=True)
class TopicReviewPacketResult:
    json_path: Path
    markdown_path: Path
    input_fingerprint: str
    reused: bool
    case_count: int
    block_count: int


VIDEO_4548_REVIEW_CASES = (
    TopicReviewCase(
        "video-4548-lyrics-52-55",
        "Performed lyrics with theological subjects",
        (52, 53, 54, 55),
        (
            "Verify that raw topic observations may describe God, Jesus, or "
            "salvation in lyrics while projection excludes the music-role blocks."
        ),
        (
            "The theological subjects in the lyrics are real text topics, but they "
            "are not evidence of the preacher's topical emphasis. Performing the "
            "song does not by itself establish church or corporate worship as a topic."
        ),
    ),
    TopicReviewCase(
        "video-4548-prodigal-illustration-69",
        "Prodigal-son illustration",
        (69,),
        (
            "Inspect whether narrative relationships and compassion are subordinate "
            "to the block's organizing salvation and acceptance point."
        ),
        (
            "Salvation and acceptance organize the block. Relationship and compassion "
            "signals reflect narrative material and should not trigger a taxonomy change."
        ),
    ),
    TopicReviewCase(
        "video-4548-closing-prayer-77-81",
        "Closing prayer across sparse caption fragments",
        (77, 78, 79, 80, 81),
        (
            "Inspect the sparse separator captions, integrated-prayer role probabilities, "
            "and final retained-sermon overlap together."
        ),
        (
            "Blocks 80-81 continue the sermon's closing prayer. Sparse blocks 77-79 "
            "must not split that component unless they contain a strong non-sermon separator."
        ),
    ),
)


KNOWN_TOPIC_REVIEW_CASES: Mapping[str, tuple[TopicReviewCase, ...]] = {
    "ClJI4jeCL2E": VIDEO_4548_REVIEW_CASES,
}


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _topic_analysis(classification: Mapping[str, Any]) -> Mapping[str, Any]:
    search = classification.get("search")
    search = search if isinstance(search, Mapping) else {}
    direct = search.get("topic_analysis")
    if isinstance(direct, Mapping):
        return direct
    discovery = search.get("discovery")
    discovery = discovery if isinstance(discovery, Mapping) else {}
    attempt = discovery.get("typesafe_first_attempt")
    attempt = attempt if isinstance(attempt, Mapping) else {}
    fallback = attempt.get("topic_analysis")
    if isinstance(fallback, Mapping):
        return fallback
    raise ValueError("Classification has no cached TypeSafe topic analysis")


def _validated_scores(block: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw_scores = block.get("scores")
    if not isinstance(raw_scores, Mapping):
        raise ValueError(f"Topic block {block.get('block_id')} has no score inventory")
    missing = [topic for topic in TOPICS if topic not in raw_scores]
    if missing:
        raise ValueError(
            f"Topic block {block.get('block_id')} is missing scores: {', '.join(missing)}"
        )
    scores: dict[str, dict[str, Any]] = {}
    for topic in TOPICS:
        raw = raw_scores[topic]
        if not isinstance(raw, Mapping):
            raise ValueError(f"Topic block {block.get('block_id')} has invalid {topic} score")
        probabilities = raw.get("probabilities")
        if not isinstance(probabilities, Mapping) or any(
            str(level) not in probabilities for level in range(5)
        ):
            raise ValueError(
                f"Topic block {block.get('block_id')} has incomplete {topic} distribution"
            )
        scores[topic] = {
            "score": float(raw.get("score") or 0.0),
            "probabilities": {
                str(level): float(probabilities[str(level)]) for level in range(5)
            },
            "confidence": (
                float(raw["confidence"])
                if isinstance(raw.get("confidence"), (int, float))
                else None
            ),
        }
    return scores


def build_topic_review_packet(
    classification: Mapping[str, Any],
    *,
    video_id: int,
    youtube_video_id: str,
    title: str,
    cases: Sequence[TopicReviewCase],
    source_artifact_path: Path | None = None,
) -> dict[str, Any]:
    """Build a bounded packet without changing or rerunning cached inference."""
    if not cases:
        raise ValueError("At least one topic review case is required")
    analysis = _topic_analysis(classification)
    raw_blocks = analysis.get("blocks")
    if not isinstance(raw_blocks, list):
        raise ValueError("TypeSafe topic analysis has no block observations")
    blocks_by_id = {
        int(block["block_id"]): block
        for block in raw_blocks
        if isinstance(block, Mapping) and isinstance(block.get("block_id"), int)
    }
    selected_ids = tuple(
        dict.fromkeys(block_id for case in cases for block_id in case.block_ids)
    )
    missing = [block_id for block_id in selected_ids if block_id not in blocks_by_id]
    if missing:
        raise ValueError(
            "Requested topic review blocks are absent: "
            + ", ".join(str(block_id) for block_id in missing)
        )
    reviewed_blocks = []
    for block_id in selected_ids:
        block = blocks_by_id[block_id]
        context = block.get("context")
        context = dict(context) if isinstance(context, Mapping) else {}
        reviewed_blocks.append(
            {
                "block_id": block_id,
                "start_seconds": block.get("start_seconds"),
                "end_seconds": block.get("end_seconds"),
                "segment_indexes": list(block.get("segment_indexes") or []),
                "content_role": block.get("content_role"),
                "content_role_probabilities": dict(
                    block.get("content_role_probabilities") or {}
                ),
                "content_role_confidence": block.get("content_role_confidence"),
                "sermon_probability": block.get("sermon_probability"),
                "leading_context": context.get("leading_context", ""),
                "target_text": context.get("target_text", ""),
                "trailing_context": context.get("trailing_context", ""),
                "context_diagnostics": context.get("diagnostics", {}),
                "reliability": dict(block.get("reliability") or {}),
                "projection_eligibility": dict(
                    block.get("projection_eligibility") or {}
                ),
                "scores": _validated_scores(block),
                "resolved_model_id": block.get("resolved_model_id"),
                "request_key": block.get("request_key"),
            }
        )
    disposition = classification.get("final_disposition")
    disposition_status = (
        disposition.get("status") if isinstance(disposition, Mapping) else None
    )
    identity = {
        "generator_version": TOPIC_REVIEW_GENERATOR_VERSION,
        "video_id": video_id,
        "youtube_video_id": youtube_video_id,
        "title": title,
        "classification_method": classification.get("method"),
        "final_disposition_status": disposition_status,
        "question_pack_version": analysis.get("question_pack_version"),
        "question_pack_digest": analysis.get("question_pack_digest"),
        "projection_policy_version": (
            analysis.get("sermon_projection", {}).get("policy_version")
            if isinstance(analysis.get("sermon_projection"), Mapping)
            else None
        ),
        "cases": [asdict(case) for case in cases],
        "blocks": reviewed_blocks,
    }
    input_fingerprint = _canonical_hash(identity)
    return {
        "schema_version": TOPIC_REVIEW_SCHEMA_VERSION,
        "generator_version": TOPIC_REVIEW_GENERATOR_VERSION,
        "input_fingerprint": input_fingerprint,
        "source": {
            "video_id": video_id,
            "youtube_video_id": youtube_video_id,
            "title": title,
            "classification_artifact_path": (
                str(source_artifact_path) if source_artifact_path is not None else None
            ),
            "classification_method": classification.get("method"),
            "final_disposition_status": disposition_status,
            "requested_model_id": analysis.get("requested_model_id"),
            "question_pack_version": analysis.get("question_pack_version"),
            "question_pack_digest": analysis.get("question_pack_digest"),
            "context_policy_version": analysis.get("context_policy_version"),
            "reliability_policy_version": analysis.get(
                "reliability_policy_version"
            ),
        },
        "interpretation_contract": {
            "score": "Probability-weighted position on ordered prominence levels 0-4.",
            "probabilities": "The complete probability distribution over levels 0-4.",
            "confidence": (
                "Distribution concentration, not topic presence, correctness, or "
                "permission to attribute the block to the preacher."
            ),
            "attribution": (
                "Content role, topic meaning, and projection eligibility are separate."
            ),
        },
        "cases": [asdict(case) for case in cases],
        "blocks": reviewed_blocks,
    }


def render_topic_review_markdown(packet: Mapping[str, Any]) -> str:
    """Render every cached distribution in a compact, auditable review document."""
    source = packet["source"]
    blocks = {
        int(block["block_id"]): block for block in packet.get("blocks", [])
    }
    lines = [
        f"# TypeSafe Topic Review: {source['title']}",
        "",
        f"- Video: database #{source['video_id']} / `{source['youtube_video_id']}`",
        f"- Classification: `{source['classification_method']}`",
        f"- Disposition: `{source['final_disposition_status']}`",
        f"- Topic pack: `{source['question_pack_version']}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        "Confidence describes how concentrated a Score distribution is. It is not "
        "a correctness score or a topic-presence threshold. Content role, raw topic "
        "meaning, and projection eligibility remain separate.",
        "",
    ]
    for case in packet.get("cases", []):
        lines.extend(
            [
                f"## {case['label']}",
                "",
                f"Review focus: {case['review_focus']}",
                "",
                f"Reviewed interpretation: {case['reviewed_interpretation']}",
                "",
            ]
        )
        for block_id in case["block_ids"]:
            block = blocks[int(block_id)]
            reliability = block["reliability"]
            eligibility = block["projection_eligibility"]
            role_probabilities = block["content_role_probabilities"]
            lines.extend(
                [
                    f"### Block {block_id} ({block['start_seconds']}-{block['end_seconds']}s)",
                    "",
                    f"- Content role: `{block['content_role']}`",
                    f"- Content-role confidence: `{block['content_role_confidence']}`",
                    "- Content-role probabilities: "
                    + (
                        ", ".join(
                            f"`{role}`={float(probability):.3f}"
                            for role, probability in sorted(role_probabilities.items())
                        )
                        or "not persisted in this source artifact"
                    ),
                    f"- Sermon probability: `{block['sermon_probability']}`",
                    (
                        "- Reliability: "
                        f"words={reliability.get('analyzable_lexical_word_count')}, "
                        f"sparse={reliability.get('sparse')}, "
                        f"final overlap={reliability.get('final_sermon_overlap_seconds')}s"
                    ),
                    (
                        "- Projection: "
                        f"eligible={eligibility.get('eligible')}, "
                        f"reasons={eligibility.get('exclusion_reasons', [])}"
                    ),
                    "",
                    "Leading context:",
                    "",
                    f"> {str(block['leading_context']).replace(chr(10), ' ')}",
                    "",
                    "Target text:",
                    "",
                    f"> {str(block['target_text']).replace(chr(10), ' ')}",
                    "",
                    "Trailing context:",
                    "",
                    f"> {str(block['trailing_context']).replace(chr(10), ' ')}",
                    "",
                    "| Topic | Score | P0 | P1 | P2 | P3 | P4 | Confidence |",
                    "|---|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            for topic in TOPICS:
                score = block["scores"][topic]
                probabilities = score["probabilities"]
                confidence = score["confidence"]
                row = (
                    f"| `{topic}` | {score['score']:.3f} | "
                    + " | ".join(
                        f"{probabilities[str(level)]:.3f}" for level in range(5)
                    )
                )
                row += f" | {confidence:.3f} |" if confidence is not None else " | n/a |"
                lines.append(row)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_topic_review_packet(
    output_json_path: Path,
    packet: Mapping[str, Any],
) -> TopicReviewPacketResult:
    """Write or reuse a content-addressed JSON/Markdown review packet."""
    output_json_path = output_json_path.expanduser().resolve()
    markdown_path = output_json_path.with_suffix(".md")
    fingerprint = str(packet["input_fingerprint"])
    expected_json = (
        json.dumps(packet, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    expected_markdown = render_topic_review_markdown(packet)
    if output_json_path.exists() and markdown_path.exists():
        try:
            existing_json = output_json_path.read_text(encoding="utf-8")
            existing = json.loads(existing_json)
            existing_markdown = markdown_path.read_text(encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            existing = existing_json = existing_markdown = None
        if (
            isinstance(existing, Mapping)
            and existing.get("input_fingerprint") == fingerprint
            and existing_json == expected_json
            and existing_markdown == expected_markdown
        ):
            return TopicReviewPacketResult(
                output_json_path,
                markdown_path,
                fingerprint,
                True,
                len(packet.get("cases", [])),
                len(packet.get("blocks", [])),
            )
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(expected_json, encoding="utf-8")
    markdown_path.write_text(expected_markdown, encoding="utf-8")
    return TopicReviewPacketResult(
        output_json_path,
        markdown_path,
        fingerprint,
        False,
        len(packet.get("cases", [])),
        len(packet.get("blocks", [])),
    )
