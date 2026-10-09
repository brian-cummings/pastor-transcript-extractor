"""Provider-free review of collected salvation relationship observations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIPS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
    resolve_salvation_relationship_analysis_artifact,
)
from pastor_transcript_extractor.sermon_topic_profile_analysis import (
    read_classification_for_gate,
)
from pastor_transcript_extractor.sermon_topic_projection import (
    assess_topic_profile_projection,
)
from pastor_transcript_extractor.sermon_topic_stage4 import (
    assess_topic_stage4_readiness,
)
from pastor_transcript_extractor.storage import Database


SALVATION_COLLECTED_OBSERVATION_REVIEW_SCHEMA_VERSION = 1
SALVATION_COLLECTED_OBSERVATION_REVIEW_POLICY_VERSION = (
    "salvation-collected-observation-boundaries-v1"
)
DEFAULT_SALVATION_COLLECTED_OBSERVATION_REVIEW_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-collected-observations-review-v1.json"
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


def _validated_source_judgments(
    source: Mapping[str, Any],
) -> list[dict[str, Any]]:
    artifact = source.get("artifact")
    if not isinstance(artifact, Mapping):
        raise ValueError("Salvation relationship source artifact is malformed")
    if artifact.get("question_pack_version") != SALVATION_RELATIONSHIPS_PACK_VERSION:
        raise ValueError(
            f"Video {source['video_id']} uses a different relationship question pack"
        )
    if (
        artifact.get("observation_policy_version")
        != SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
    ):
        raise ValueError(
            f"Video {source['video_id']} uses a different observation policy"
        )
    raw_thresholds = artifact.get("observation_thresholds")
    if raw_thresholds != SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS:
        raise ValueError(
            f"Video {source['video_id']} has inconsistent observation thresholds"
        )
    raw_blocks = artifact.get("blocks")
    if not isinstance(raw_blocks, list):
        raise ValueError(f"Video {source['video_id']} has malformed relationship blocks")
    judgments: list[dict[str, Any]] = []
    for block in raw_blocks:
        if not isinstance(block, Mapping):
            raise ValueError(
                f"Video {source['video_id']} has a malformed relationship block"
            )
        probabilities = block.get("probabilities")
        if not isinstance(probabilities, Mapping) or set(probabilities) != set(
            SALVATION_RELATIONSHIPS
        ):
            raise ValueError(
                f"Video {source['video_id']} block {block.get('block_id')} has the "
                "wrong relationship inventory"
            )
        raw_observations = block.get("observations")
        if not isinstance(raw_observations, list):
            raise ValueError(
                f"Video {source['video_id']} block {block.get('block_id')} has "
                "malformed collected observations"
            )
        stored = {
            str(item.get("relationship"))
            for item in raw_observations
            if isinstance(item, Mapping)
        }
        expected = {
            relationship
            for relationship in SALVATION_RELATIONSHIPS
            if float(probabilities[relationship])
            >= SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[relationship]
        }
        if stored != expected:
            raise ValueError(
                f"Video {source['video_id']} block {block.get('block_id')} has "
                "observations inconsistent with the frozen threshold policy"
            )
        context = block.get("context")
        context = context if isinstance(context, Mapping) else {}
        target = context.get("target_text")
        if not isinstance(target, str) or not target.strip():
            raise ValueError(
                f"Video {source['video_id']} block {block.get('block_id')} has no "
                "relationship target text"
            )
        for relationship in SALVATION_RELATIONSHIPS:
            probability = round(float(probabilities[relationship]), 6)
            judgments.append(
                {
                    "judgment_key": (
                        f"{int(source['video_id'])}:{int(block['block_id'])}:"
                        f"{relationship}"
                    ),
                    "relationship": relationship,
                    "probability": probability,
                    "threshold": (
                        SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[relationship]
                    ),
                    "collected": relationship in expected,
                    "pastor": dict(source["pastor"]),
                    "video_id": int(source["video_id"]),
                    "youtube_video_id": str(source["youtube_video_id"]),
                    "title": str(source["title"]),
                    "block_id": int(block["block_id"]),
                    "start_seconds": float(block["start_seconds"]),
                    "end_seconds": float(block["end_seconds"]),
                    "leading_context": str(context.get("leading_context") or ""),
                    "target_text": target,
                    "trailing_context": str(context.get("trailing_context") or ""),
                }
            )
    return judgments


def build_salvation_collected_observations_review(
    sources: Sequence[Mapping[str, Any]],
    *,
    cohort_sha256: str | None,
    readiness_input_fingerprint: str,
) -> dict[str, Any]:
    """Select the closest collected and rejected judgment for every leaf."""
    judgments = [
        judgment
        for source in sources
        for judgment in _validated_source_judgments(source)
    ]
    if not judgments:
        raise ValueError("No routed salvation relationship blocks are available")
    probes: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {}
    for relationship in SALVATION_RELATIONSHIPS:
        candidates = [
            item for item in judgments if item["relationship"] == relationship
        ]
        collected = [item for item in candidates if item["collected"]]
        rejected = [item for item in candidates if not item["collected"]]
        counts[relationship] = {
            "collected": len(collected),
            "rejected": len(rejected),
        }
        if rejected:
            probes.append(
                {
                    **max(
                        rejected,
                        key=lambda item: (
                            float(item["probability"]),
                            str(item["judgment_key"]),
                        ),
                    ),
                    "boundary_side": "strongest_rejected",
                }
            )
        if collected:
            probes.append(
                {
                    **min(
                        collected,
                        key=lambda item: (
                            float(item["probability"]),
                            str(item["judgment_key"]),
                        ),
                    ),
                    "boundary_side": "weakest_collected",
                }
            )
    source_fingerprints = [
        {
            "video_id": int(source["video_id"]),
            "artifact_sha256": _canonical_hash(source["artifact"]),
        }
        for source in sources
    ]
    identity = {
        "schema_version": SALVATION_COLLECTED_OBSERVATION_REVIEW_SCHEMA_VERSION,
        "review_policy_version": (
            SALVATION_COLLECTED_OBSERVATION_REVIEW_POLICY_VERSION
        ),
        "cohort_sha256": cohort_sha256,
        "readiness_input_fingerprint": readiness_input_fingerprint,
        "question_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "observation_policy_version": (
            SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
        ),
        "observation_thresholds": dict(
            SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS
        ),
        "source_artifacts": source_fingerprints,
        "source_video_count": len(sources),
        "routed_block_count": len(judgments) // len(SALVATION_RELATIONSHIPS),
        "judgment_count": len(judgments),
        "counts_by_relationship": counts,
        "probes": probes,
    }
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "collected_observations_pending_review",
        "policy_effect": "none",
        "interpretation": (
            "This provider-free packet checks the actual ordinary-classification "
            "observation layer. It verifies every stored observation against the "
            "frozen per-leaf policy, then shows the strongest rejected and weakest "
            "collected judgment for each relationship. It does not alter inference, "
            "thresholds, or profile claims."
        ),
    }


def evaluate_salvation_collected_observations_review(
    database: Database,
    cohort: Mapping[str, Any],
) -> dict[str, Any]:
    readiness = assess_topic_stage4_readiness(database, cohort)
    if not readiness["ready"]:
        raise ValueError(
            "Salvation observation review requires ready Stage 4 inputs: "
            + ", ".join(readiness["blockers"])
        )
    videos = {video.id: video for video in database.list_videos()}
    sources: list[dict[str, Any]] = []
    missing: list[int] = []
    for pastor in cohort["pastors"]:
        for sermon in pastor["sermons"]:
            video_id = int(sermon["video_id"])
            video = videos.get(video_id)
            if video is None:
                raise ValueError(f"Unknown salvation observation video: {video_id}")
            gate = assess_topic_profile_projection(database, video)
            if not gate.eligible:
                raise ValueError(
                    f"Video {video_id} is not eligible for salvation observation review"
                )
            classification = read_classification_for_gate(gate)
            try:
                artifact = resolve_salvation_relationship_analysis_artifact(
                    classification
                )
            except ValueError:
                missing.append(video_id)
                continue
            sources.append(
                {
                    "pastor": {
                        "display_name": pastor.get("display_name"),
                        "pastor_id": pastor.get("pastor_id"),
                        "slug": pastor.get("slug"),
                    },
                    "video_id": video_id,
                    "youtube_video_id": video.youtube_video_id,
                    "title": video.title,
                    "artifact": artifact,
                }
            )
    if missing:
        raise ValueError(
            "Cohort classifications have no current salvation relationship analysis: "
            + ", ".join(str(video_id) for video_id in missing)
        )
    return build_salvation_collected_observations_review(
        sources,
        cohort_sha256=(
            str(cohort["cohort_sha256"])
            if cohort.get("cohort_sha256") is not None
            else None
        ),
        readiness_input_fingerprint=str(readiness["input_fingerprint"]),
    )


def render_salvation_collected_observations_review(
    packet: Mapping[str, Any],
) -> str:
    lines = [
        "# Salvation collected observations review",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Question pack: `{packet['question_pack_version']}`",
        f"- Observation policy: `{packet['observation_policy_version']}`",
        f"- Source videos: `{packet['source_video_count']}`",
        f"- Routed blocks: `{packet['routed_block_count']}`",
        f"- Raw judgments: `{packet['judgment_count']}`",
        f"- Boundary probes: `{len(packet['probes'])}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "Review whether each weakest collected judgment is a useful affirmative "
        "observation and whether each strongest rejected judgment reveals a material "
        "miss. Context may clarify the target but cannot independently establish the "
        "relationship.",
        "",
        "## Collection counts",
        "",
        "| Relationship | Threshold | Collected | Rejected |",
        "| --- | ---: | ---: | ---: |",
    ]
    for relationship in SALVATION_RELATIONSHIPS:
        counts = packet["counts_by_relationship"][relationship]
        lines.append(
            f"| {relationship} | "
            f"{float(packet['observation_thresholds'][relationship]):.2f} | "
            f"{counts['collected']} | {counts['rejected']} |"
        )
    for relationship in SALVATION_RELATIONSHIPS:
        lines.extend(["", f"## {relationship}", ""])
        for probe in packet["probes"]:
            if probe["relationship"] != relationship:
                continue
            lines.extend(
                [
                    f"### {probe['boundary_side']} / "
                    f"{float(probe['probability']):.3f}",
                    "",
                    f"- Threshold: `{float(probe['threshold']):.2f}`",
                    f"- Case: `{probe['video_id']}:{probe['block_id']}` — "
                    f"{probe['pastor']['display_name']}",
                    f"- Recording: `{probe['youtube_video_id']}` — {probe['title']}",
                    f"- Time: `{probe['start_seconds']}`–`{probe['end_seconds']}`",
                    "",
                    "Leading context:",
                    "",
                    f"> {str(probe['leading_context']).replace(chr(10), ' ')}",
                    "",
                    "Target text:",
                    "",
                    f"> {str(probe['target_text']).replace(chr(10), ' ')}",
                    "",
                    "Trailing context:",
                    "",
                    f"> {str(probe['trailing_context']).replace(chr(10), ' ')}",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def write_salvation_collected_observations_review(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    json_path = path.expanduser().resolve()
    markdown_path = json_path.with_suffix(".md")
    expected_json = (
        json.dumps(packet, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    expected_markdown = render_salvation_collected_observations_review(packet)
    if json_path.exists() and markdown_path.exists():
        try:
            existing_json = json_path.read_text(encoding="utf-8")
            existing_markdown = markdown_path.read_text(encoding="utf-8")
            existing = json.loads(existing_json)
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing = existing_json = existing_markdown = None
        if (
            isinstance(existing, Mapping)
            and existing.get("input_fingerprint") == packet.get("input_fingerprint")
            and existing_json == expected_json
            and existing_markdown == expected_markdown
        ):
            return json_path, markdown_path, True
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(expected_json, encoding="utf-8")
    markdown_path.write_text(expected_markdown, encoding="utf-8")
    return json_path, markdown_path, False
