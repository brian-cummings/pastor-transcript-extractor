"""Deterministic review packets for cached TypeSafe sermon-topic observations."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.caption_normalization import (
    ROLLING_CAPTION_INPUT_POLICY_VERSION,
    normalize_caption_fragments,
    should_normalize_rolling_captions,
)
from pastor_transcript_extractor.sermon_topics import (
    TOPIC_DOMAIN_LABELS,
    TOPIC_SPECS,
    TOPICS,
    resolve_topic_analysis_artifact,
)


TOPIC_REVIEW_SCHEMA_VERSION = 4
TOPIC_REVIEW_GENERATOR_VERSION = "typesafe-topic-review-v4"
TOPIC_REVIEW_DEFAULT_FILENAME = f"{TOPIC_REVIEW_GENERATOR_VERSION}.json"
PROSPECTIVE_REVIEW_POLICY_VERSION = "topic-prospective-sanity-sampler-v1"
KNOWN_REVIEW_POLICY_VERSION = "topic-known-regression-cases-v1"
WHOLE_SERMON_REVIEW_POLICY_VERSION = "topic-whole-sermon-review-v1"
DEFAULT_PROSPECTIVE_REVIEW_CASES = 8
PROSPECTIVE_TOPIC_REVIEW_DEFAULT_FILENAME = (
    f"{PROSPECTIVE_REVIEW_POLICY_VERSION}.json"
)
WHOLE_SERMON_TOPIC_REVIEW_DEFAULT_FILENAME = (
    f"{WHOLE_SERMON_REVIEW_POLICY_VERSION}.json"
)


@dataclass(frozen=True, slots=True)
class TopicReviewCase:
    case_id: str
    label: str
    block_ids: tuple[int, ...]
    review_focus: str
    reviewed_interpretation: str | None


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


def _score_number(score: Mapping[str, Any], key: str) -> float | None:
    value = score.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _supporting_probability(score: Mapping[str, Any]) -> float:
    probabilities = score.get("probabilities")
    if not isinstance(probabilities, Mapping):
        return 0.0
    return sum(
        float(probabilities.get(str(level)) or 0.0) for level in (2, 3, 4)
    )


def build_topic_review_transcript_provenance(
    proposed: Mapping[str, Any],
) -> dict[str, Any]:
    """Describe the transcript representation actually used by reclassification."""
    raw_segments = proposed.get("segments")
    segments = raw_segments if isinstance(raw_segments, list) else []
    fragments = [
        (index, str(segment["text"]))
        for index, segment in enumerate(segments)
        if isinstance(segment, Mapping) and isinstance(segment.get("text"), str)
    ]
    normalization = normalize_caption_fragments(fragments).diagnostics
    artifact_kind = proposed.get("transcript_artifact_kind")
    transformation_version = proposed.get("transcript_transformation_version")
    canonical = artifact_kind == "canonical" and isinstance(
        transformation_version, str
    )
    normalize_legacy_captions = should_normalize_rolling_captions(proposed)
    deduplication_ratio = float(normalization.get("deduplication_ratio") or 0.0)
    warnings: list[str] = []
    if not canonical:
        warnings.append("classification_input_not_versioned_canonical_transcript")
    if deduplication_ratio >= 0.2:
        warnings.append("high_rolling_caption_duplication")
    return {
        "transcript_source": proposed.get("transcript_source"),
        "transcript_artifact_id": proposed.get("transcript_artifact_id"),
        "transcript_artifact_kind": artifact_kind,
        "transcript_transformation_version": transformation_version,
        "transcript_content_sha256": proposed.get("transcript_content_sha256"),
        "source_artifact_canonical": canonical,
        "rolling_caption_normalization_policy_version": (
            ROLLING_CAPTION_INPUT_POLICY_VERSION
        ),
        "rolling_caption_normalization_applied": normalize_legacy_captions,
        "segment_count": (
            int(proposed["segment_count"])
            if isinstance(proposed.get("segment_count"), int)
            and not isinstance(proposed.get("segment_count"), bool)
            else len(segments)
        ),
        "diagnostic_normalization": {
            key: normalization.get(key)
            for key in (
                "normalizer_version",
                "raw_text_hash",
                "normalized_text_hash",
                "raw_token_count",
                "normalized_token_count",
                "deduplication_ratio",
            )
        },
        "warnings": warnings,
    }


def derive_prospective_topic_review_cases(
    classification: Mapping[str, Any],
    *,
    maximum_cases: int = DEFAULT_PROSPECTIVE_REVIEW_CASES,
) -> tuple[TopicReviewCase, ...]:
    """Select a bounded, deterministic sanity-review sample from cached evidence."""
    if maximum_cases < 1:
        raise ValueError("Prospective topic review requires at least one case")
    analysis = resolve_topic_analysis_artifact(classification)
    if not isinstance(analysis.get("sermon_projection"), Mapping):
        raise ValueError(
            "Prospective topic review requires a current deterministic sermon projection"
        )
    raw_blocks = analysis.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ValueError("TypeSafe topic analysis has no block observations")
    blocks = sorted(
        (block for block in raw_blocks if isinstance(block, Mapping)),
        key=lambda block: (
            float(block.get("start_seconds") or 0.0),
            int(block.get("block_id") or 0),
        ),
    )
    if any(
        not isinstance(block.get("projection_eligibility"), Mapping)
        for block in blocks
    ):
        raise ValueError(
            "Prospective topic review requires per-block projection eligibility"
        )
    scores_by_block_id = {
        int(block["block_id"]): _validated_scores(block) for block in blocks
    }

    cases: list[TopicReviewCase] = []
    selected_block_ids: set[int] = set()

    def add_case(case: TopicReviewCase) -> None:
        if len(cases) >= maximum_cases:
            return
        cases.append(case)
        selected_block_ids.update(case.block_ids)

    # First expose changes in deterministic attribution eligibility. These windows
    # are the highest-value places to inspect boundary contamination or lost recall.
    boundary_count = 0
    for left, right in zip(blocks, blocks[1:]):
        left_eligible = bool(left["projection_eligibility"].get("eligible"))
        right_eligible = bool(right["projection_eligibility"].get("eligible"))
        if left_eligible == right_eligible:
            continue
        left_id = int(left["block_id"])
        right_id = int(right["block_id"])
        add_case(
            TopicReviewCase(
                f"prospective-boundary-{left_id}-{right_id}",
                f"Projection boundary at blocks {left_id}-{right_id}",
                (left_id, right_id),
                (
                    "Inspect the adjacent retained-window overlap, density, content "
                    "roles, and topic distributions where projection eligibility changes."
                ),
                None,
            )
        )
        boundary_count += 1
        if len(cases) >= maximum_cases:
            return tuple(cases)
        if boundary_count >= 2:
            break

    # Next surface concentrated-vs-broad distributions only where the topic has
    # meaningful support. Confidence prioritizes review; it never decides truth.
    ambiguous: list[tuple[float, int, str]] = []
    for block in blocks:
        block_id = int(block["block_id"])
        for topic, score in scores_by_block_id[block_id].items():
            expected = float(score["score"])
            support = _supporting_probability(score)
            confidence = _score_number(score, "confidence")
            if confidence is None or (expected < 1.0 and support < 0.25):
                continue
            ambiguous.append((confidence, block_id, topic))
    ambiguity_count = 0
    for confidence, block_id, topic in sorted(ambiguous):
        if block_id in selected_block_ids:
            continue
        add_case(
            TopicReviewCase(
                f"prospective-distribution-{block_id}-{topic}",
                f"Broad {topic} distribution in block {block_id}",
                (block_id,),
                (
                    f"Inspect the complete `{topic}` distribution (concentration "
                    f"{confidence:.3f}) against the target text; do not treat "
                    "concentration as correctness."
                ),
                None,
            )
        )
        ambiguity_count += 1
        if len(cases) >= maximum_cases:
            return tuple(cases)
        if ambiguity_count >= 2:
            break

    # Finally cover the strongest eligible evidence in each broad domain, favoring
    # a different block for each domain so a small packet spans the sermon.
    for domain, domain_label in TOPIC_DOMAIN_LABELS.items():
        domain_topics = tuple(
            topic for topic, spec in TOPIC_SPECS.items() if spec.domain == domain
        )
        candidates: list[tuple[float, float, int, str]] = []
        for block in blocks:
            if not block["projection_eligibility"].get("eligible"):
                continue
            block_id = int(block["block_id"])
            scores = scores_by_block_id[block_id]
            for topic in domain_topics:
                score = scores[topic]
                candidates.append(
                    (
                        float(score["score"]),
                        _supporting_probability(score),
                        block_id,
                        topic,
                    )
                )
        unused = [item for item in candidates if item[2] not in selected_block_ids]
        ranked = unused or candidates
        if not ranked:
            continue
        expected, support, block_id, topic = max(
            ranked,
            key=lambda item: (item[0], item[1], -item[2], item[3]),
        )
        add_case(
            TopicReviewCase(
                f"prospective-domain-{domain}-{block_id}-{topic}",
                f"{domain_label} evidence in block {block_id}",
                (block_id,),
                (
                    f"Inspect the strongest eligible `{topic}` evidence selected "
                    f"for domain coverage (score {expected:.3f}, supporting-or-above "
                    f"probability {support:.3f})."
                ),
                None,
            )
        )
        if len(cases) >= maximum_cases:
            break

    if not cases:
        raise ValueError("No prospective topic review cases could be selected")
    return tuple(cases)


def derive_whole_sermon_topic_review_case(
    classification: Mapping[str, Any],
) -> TopicReviewCase:
    """Select every cached block for missed-episode and boundary review."""
    analysis = resolve_topic_analysis_artifact(classification)
    projection = analysis.get("sermon_projection")
    if not isinstance(projection, Mapping):
        raise ValueError(
            "Whole-sermon topic review requires a current deterministic sermon projection"
        )
    raw_blocks = analysis.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ValueError("TypeSafe topic analysis has no block observations")
    blocks = sorted(
        (block for block in raw_blocks if isinstance(block, Mapping)),
        key=lambda block: (
            float(block.get("start_seconds") or 0.0),
            int(block.get("block_id") or 0),
        ),
    )
    block_ids = tuple(
        int(block["block_id"])
        for block in blocks
        if isinstance(block.get("block_id"), int)
    )
    if not block_ids:
        raise ValueError("TypeSafe topic analysis has no addressable block observations")
    return TopicReviewCase(
        "whole-sermon-topic-review",
        "Whole-sermon topic and projection review",
        block_ids,
        (
            "Review every observed block in sequence. Search for missed topic episodes, "
            "false positive topics, sparse-evidence errors, and projection-boundary "
            "failures without treating confidence as correctness."
        ),
        None,
    )


def build_topic_review_packet(
    classification: Mapping[str, Any],
    *,
    video_id: int,
    youtube_video_id: str,
    title: str,
    cases: Sequence[TopicReviewCase],
    source_artifact_path: Path | None = None,
    profile_projection_gate: Mapping[str, Any] | None = None,
    selection: Mapping[str, Any] | None = None,
    transcript_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded packet without changing or rerunning cached inference."""
    if not cases:
        raise ValueError("At least one topic review case is required")
    analysis = resolve_topic_analysis_artifact(classification)
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
        "profile_projection_gate": dict(profile_projection_gate or {}),
        "selection": dict(selection or {}),
        "transcript_provenance": dict(transcript_provenance or {}),
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
            "transcript_provenance": dict(transcript_provenance or {}),
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
        "selection": dict(selection or {}),
        "profile_projection_gate": dict(profile_projection_gate or {}),
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
    transcript = source.get("transcript_provenance")
    if isinstance(transcript, Mapping) and transcript:
        normalization = transcript.get("diagnostic_normalization")
        normalization = normalization if isinstance(normalization, Mapping) else {}
        lines.extend(
            [
                "## Transcript representation",
                "",
                f"- Source: `{transcript.get('transcript_source')}`",
                f"- Artifact kind: `{transcript.get('transcript_artifact_kind')}`",
                f"- Transformation: `{transcript.get('transcript_transformation_version')}`",
                f"- Canonical source artifact: `{transcript.get('source_artifact_canonical')}`",
                f"- Legacy caption normalization applied: `{transcript.get('rolling_caption_normalization_applied')}`",
                f"- Normalization policy: `{transcript.get('rolling_caption_normalization_policy_version')}`",
                f"- Segment count: `{transcript.get('segment_count')}`",
                f"- Content SHA-256: `{transcript.get('transcript_content_sha256')}`",
                f"- Diagnostic deduplication ratio: `{normalization.get('deduplication_ratio')}`",
                f"- Representation warnings: `{transcript.get('warnings', [])}`",
                "",
            ]
        )
    gate = packet.get("profile_projection_gate")
    if isinstance(gate, Mapping) and gate:
        lines.extend(
            [
                "## Profile projection gate",
                "",
                f"- Eligible: `{gate.get('eligible')}`",
                f"- Profile: `{gate.get('profile_id')}`",
                f"- Reasons: `{gate.get('reason_codes', [])}`",
                f"- Policy: `{gate.get('policy_version')}`",
                f"- Input fingerprint: `{gate.get('input_fingerprint')}`",
                "",
            ]
        )
    selection = packet.get("selection")
    if isinstance(selection, Mapping) and selection:
        lines.extend(
            [
                "## Review selection",
                "",
                f"- Mode: `{selection.get('mode')}`",
                f"- Policy: `{selection.get('policy_version')}`",
                f"- Maximum cases: `{selection.get('maximum_cases')}`",
            ]
        )
        if selection.get("selected_block_count") is not None:
            lines.append(
                f"- Selected blocks: `{selection.get('selected_block_count')}`"
            )
        lines.append("")
    for case in packet.get("cases", []):
        lines.extend([f"## {case['label']}", "", f"Review focus: {case['review_focus']}", ""])
        interpretation = case.get("reviewed_interpretation")
        if interpretation:
            lines.extend([f"Reviewed interpretation: {interpretation}", ""])
        else:
            lines.extend(
                [
                    "Review status: pending; this deterministic selection carries no "
                    "pre-assigned interpretation.",
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
