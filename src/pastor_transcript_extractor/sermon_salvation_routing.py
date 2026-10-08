"""Provider-free calibration packets for conditional salvation leaf routing."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.sermon_topic_profile_analysis import (
    read_topic_analysis_for_gate,
)
from pastor_transcript_extractor.sermon_topic_projection import (
    assess_topic_profile_projection,
)
from pastor_transcript_extractor.sermon_topic_stage4 import (
    assess_topic_stage4_readiness,
)
from pastor_transcript_extractor.sermon_topics import (
    TOPIC_PACK_VERSION,
    resolve_topic_block_context,
    topic_supporting_or_above_probability,
    validated_topic_scores,
)
from pastor_transcript_extractor.storage import Database


SALVATION_ROUTING_REVIEW_SCHEMA_VERSION = 1
SALVATION_ROUTING_REVIEW_POLICY_VERSION = "salvation-leaf-route-calibration-v2"
SALVATION_ROUTING_SIGNAL = "salvation_gospel_supporting_or_above_probability"
PROPOSED_SALVATION_ROUTE_THRESHOLD = 0.65
PRIOR_CALIBRATION_FINGERPRINT = (
    "3a296603f3500f780440f675b2cf9c0daf9065648ee3e358dc258ccbc4563f15"
)
DEFAULT_SALVATION_ROUTING_REVIEW_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-routing-calibration-v2.json"
)


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _candidate(
    *,
    block: Mapping[str, Any],
    pastor: Mapping[str, Any],
    video: Any,
    topic_analysis_fingerprint: str,
) -> dict[str, Any]:
    scores = validated_topic_scores(block)
    salvation = scores["salvation_gospel"]
    context = resolve_topic_block_context(block)
    target_text = context.get("target_text")
    if not isinstance(target_text, str) or not target_text.strip():
        raise ValueError(
            f"Topic block {block.get('block_id')} has no routing target text"
        )
    support = topic_supporting_or_above_probability(salvation)
    block_id = int(block["block_id"])
    return {
        "candidate_key": f"{video.id}:{block_id}",
        "pastor": {
            "display_name": pastor.get("display_name"),
            "pastor_id": pastor.get("pastor_id"),
            "slug": pastor.get("slug"),
        },
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "title": video.title,
        "block_id": block_id,
        "start_seconds": block.get("start_seconds"),
        "end_seconds": block.get("end_seconds"),
        "content_role": block.get("content_role"),
        "projection_eligibility": dict(block.get("projection_eligibility") or {}),
        "reliability": dict(block.get("reliability") or {}),
        "leading_context": context.get("leading_context", ""),
        "target_text": target_text,
        "trailing_context": context.get("trailing_context", ""),
        "salvation_gospel": salvation,
        "supporting_or_above_probability": round(support, 6),
        "proposed_route": support >= PROPOSED_SALVATION_ROUTE_THRESHOLD,
        "topic_analysis_fingerprint": topic_analysis_fingerprint,
        "source_request_key": block.get("request_key"),
    }


def _select_unique_pastors(
    candidates: Sequence[dict[str, Any]],
    *,
    count: int,
    selected_keys: set[str],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_pastors: set[str] = set()
    for candidate in candidates:
        key = str(candidate["candidate_key"])
        pastor = str(candidate["pastor"].get("slug"))
        if key in selected_keys or pastor in selected_pastors:
            continue
        selected.append(candidate)
        selected_keys.add(key)
        selected_pastors.add(pastor)
        if len(selected) == count:
            return selected
    for candidate in candidates:
        key = str(candidate["candidate_key"])
        if key in selected_keys:
            continue
        selected.append(candidate)
        selected_keys.add(key)
        if len(selected) == count:
            break
    return selected


def _review_cases(candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    selected_keys: set[str] = set()
    cases: list[dict[str, Any]] = []

    def add(stratum: str, rationale: str, candidate: dict[str, Any]) -> None:
        cases.append(
            {
                "case_id": f"{stratum}:{candidate['candidate_key']}",
                "stratum": stratum,
                "selection_rationale": rationale,
                "candidate": candidate,
            }
        )

    above = sorted(
        (
            candidate
            for candidate in candidates
            if float(candidate["supporting_or_above_probability"])
            >= PROPOSED_SALVATION_ROUTE_THRESHOLD
        ),
        key=lambda item: (
            float(item["supporting_or_above_probability"])
            - PROPOSED_SALVATION_ROUTE_THRESHOLD,
            int(item["video_id"]),
            int(item["block_id"]),
        ),
    )
    below = sorted(
        (
            candidate
            for candidate in candidates
            if float(candidate["supporting_or_above_probability"])
            < PROPOSED_SALVATION_ROUTE_THRESHOLD
        ),
        key=lambda item: (
            PROPOSED_SALVATION_ROUTE_THRESHOLD
            - float(item["supporting_or_above_probability"]),
            int(item["video_id"]),
            int(item["block_id"]),
        ),
    )
    for candidate in _select_unique_pastors(
        above,
        count=2,
        selected_keys=selected_keys,
    ):
        add(
            "boundary_route",
            "Closest unused block at or above the proposed route boundary.",
            candidate,
        )
    for candidate in _select_unique_pastors(
        below,
        count=2,
        selected_keys=selected_keys,
    ):
        add(
            "boundary_nonroute",
            "Closest unused block below the proposed route boundary.",
            candidate,
        )
    return cases


def build_salvation_routing_review_packet(
    database: Database,
    cohort: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a bounded route-calibration packet from cached broad evidence."""
    readiness = assess_topic_stage4_readiness(database, cohort)
    if not readiness["ready"]:
        raise ValueError(
            "Salvation routing review requires ready Stage 4 inputs: "
            + ", ".join(readiness["blockers"])
        )
    videos = {video.id: video for video in database.list_videos()}
    candidates: list[dict[str, Any]] = []
    for pastor in cohort["pastors"]:
        for sermon in pastor["sermons"]:
            video_id = int(sermon["video_id"])
            video = videos.get(video_id)
            if video is None:
                raise ValueError(f"Unknown salvation routing video: {video_id}")
            gate = assess_topic_profile_projection(database, video)
            if (
                not gate.eligible
                or gate.source_path is None
                or gate.topic_analysis_fingerprint is None
            ):
                raise ValueError(
                    f"Video {video_id} is not eligible for salvation routing"
                )
            analysis, _projection = read_topic_analysis_for_gate(gate)
            if analysis.get("question_pack_version") != TOPIC_PACK_VERSION:
                raise ValueError(
                    f"Video {video_id} uses a different broad topic pack"
                )
            raw_blocks = analysis.get("blocks")
            if not isinstance(raw_blocks, list):
                raise ValueError(f"Video {video_id} has no topic blocks")
            for block in raw_blocks:
                if not isinstance(block, Mapping):
                    continue
                eligibility = block.get("projection_eligibility")
                if not isinstance(eligibility, Mapping) or not eligibility.get(
                    "eligible"
                ):
                    continue
                candidates.append(
                    _candidate(
                        block=block,
                        pastor=pastor,
                        video=video,
                        topic_analysis_fingerprint=(
                            gate.topic_analysis_fingerprint
                        ),
                    )
                )
    if not candidates:
        raise ValueError("No projection-eligible salvation routing candidates")
    route_count = sum(bool(item["proposed_route"]) for item in candidates)
    cases = _review_cases(candidates)
    identity = {
        "schema_version": SALVATION_ROUTING_REVIEW_SCHEMA_VERSION,
        "policy_version": SALVATION_ROUTING_REVIEW_POLICY_VERSION,
        "cohort_sha256": cohort.get("cohort_sha256"),
        "readiness_input_fingerprint": readiness["input_fingerprint"],
        "broad_question_pack_version": TOPIC_PACK_VERSION,
        "routing_signal": SALVATION_ROUTING_SIGNAL,
        "proposed_route_threshold": PROPOSED_SALVATION_ROUTE_THRESHOLD,
        "prior_calibration": {
            "input_fingerprint": PRIOR_CALIBRATION_FINGERPRINT,
            "decision": "boundary_rejected_signal_retained",
        },
        "candidate_count": len(candidates),
        "proposed_route_count": route_count,
        "cases": cases,
    }
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "proposal_pending_review",
        "route_policy_active": False,
        "interpretation": (
            "The v1 clear strata validated this cached routing signal, but its "
            "0.70 boundary produced two false non-routes. This boundary-only "
            "revision tests 0.65 without repeating the approved clear anchors. "
            "It does not evaluate leaf judgments or authorize provider calls."
        ),
    }


def render_salvation_routing_review(packet: Mapping[str, Any]) -> str:
    lines = [
        "# Salvation leaf routing calibration",
        "",
        f"- Status: `{packet['status']}`",
        f"- Route policy active: `{str(packet['route_policy_active']).lower()}`",
        f"- Broad pack: `{packet['broad_question_pack_version']}`",
        f"- Signal: `{packet['routing_signal']}`",
        f"- Proposed route boundary: `{packet['proposed_route_threshold']:.2f}`",
        "- Prior calibration: "
        f"`{packet['prior_calibration']['input_fingerprint']}` "
        f"(`{packet['prior_calibration']['decision']}`)",
        f"- Eligible cached blocks: `{packet['candidate_count']}`",
        f"- Blocks that would route: `{packet['proposed_route_count']}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "Review only these four boundary targets. Decide whether each contains "
        "enough developed salvation content to justify a separate relationship "
        "pack. Context may clarify the target but cannot independently establish "
        "the route.",
        "",
    ]
    for case in packet["cases"]:
        candidate = case["candidate"]
        score = candidate["salvation_gospel"]
        probabilities = score["probabilities"]
        lines.extend(
            [
                f"## {case['stratum']}: {candidate['pastor']['display_name']} / "
                f"video {candidate['video_id']} / block {candidate['block_id']}",
                "",
                case["selection_rationale"],
                "",
                f"- Recording: `{candidate['youtube_video_id']}` — {candidate['title']}",
                f"- Time: `{candidate['start_seconds']}`–`{candidate['end_seconds']}`",
                f"- Role: `{candidate['content_role']}`",
                f"- Broad salvation Score: `{float(score['score']):.3f}`",
                "- Distribution: "
                + ", ".join(
                    f"P{level}={float(probabilities[str(level)]):.3f}"
                    for level in range(5)
                ),
                (
                    "- Supporting-or-above probability: "
                    f"`{float(candidate['supporting_or_above_probability']):.3f}`"
                ),
                f"- Proposed route: `{str(candidate['proposed_route']).lower()}`",
                "",
                "Leading context:",
                "",
                f"> {str(candidate['leading_context']).replace(chr(10), ' ')}",
                "",
                "Target text:",
                "",
                f"> {str(candidate['target_text']).replace(chr(10), ' ')}",
                "",
                "Trailing context:",
                "",
                f"> {str(candidate['trailing_context']).replace(chr(10), ' ')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_salvation_routing_review(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    json_path = path.expanduser().resolve()
    markdown_path = json_path.with_suffix(".md")
    expected_json = (
        json.dumps(packet, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    expected_markdown = render_salvation_routing_review(packet)
    if json_path.exists() and markdown_path.exists():
        try:
            existing_json = json_path.read_text(encoding="utf-8")
            existing_markdown = markdown_path.read_text(encoding="utf-8")
            existing = json.loads(existing_json)
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing = existing_json = existing_markdown = None
        if (
            isinstance(existing, Mapping)
            and existing.get("input_fingerprint")
            == packet.get("input_fingerprint")
            and existing_json == expected_json
            and existing_markdown == expected_markdown
        ):
            return json_path, markdown_path, True
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(expected_json, encoding="utf-8")
    markdown_path.write_text(expected_markdown, encoding="utf-8")
    return json_path, markdown_path, False
