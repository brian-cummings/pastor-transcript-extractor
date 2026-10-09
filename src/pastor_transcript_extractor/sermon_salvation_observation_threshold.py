"""Calibrate the code-owned threshold for salvation leaf observations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIPS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
)


SALVATION_OBSERVATION_THRESHOLD_REVIEW_SCHEMA_VERSION = 1
SALVATION_OBSERVATION_THRESHOLD_REVIEW_POLICY_VERSION = (
    "salvation-leaf-observation-threshold-boundary-v1"
)
DEFAULT_SALVATION_OBSERVATION_THRESHOLD = 0.70
DEFAULT_SALVATION_OBSERVATION_THRESHOLD_REVIEW_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-observation-threshold-review-v1.json"
)
DEFAULT_SALVATION_RELATIONSHIP_REVIEW_INPUTS = (
    Path("evaluation/sermon-topics/salvation-relationships-review-v2.json"),
    Path("evaluation/sermon-topics/salvation-relationships-review-v3.json"),
)
COMPARISON_THRESHOLDS = (0.50, 0.60, 0.65, 0.70, 0.75, 0.80)


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _load_review_packet(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Could not read salvation relationship review {resolved}"
        ) from error
    if not isinstance(value, dict):
        raise ValueError(f"Salvation relationship review is not an object: {resolved}")
    if value.get("leaf_pack_version") != SALVATION_RELATIONSHIPS_PACK_VERSION:
        raise ValueError(
            f"Salvation relationship review uses a different leaf pack: {resolved}"
        )
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"Salvation relationship review has no cases: {resolved}")
    return value


def _flatten_leaf_judgments(
    packets: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    judgments: list[dict[str, Any]] = []
    for packet_index, packet in enumerate(packets):
        for case in packet["cases"]:
            if not isinstance(case, Mapping):
                raise ValueError("Salvation relationship review case is not an object")
            probabilities = case.get("leaf_probabilities")
            if not isinstance(probabilities, Mapping):
                raise ValueError("Salvation relationship review case has no leaf probabilities")
            missing = set(SALVATION_RELATIONSHIPS) - set(probabilities)
            if missing:
                raise ValueError(
                    "Salvation relationship review case is missing leaves: "
                    + ", ".join(sorted(missing))
                )
            for relationship in SALVATION_RELATIONSHIPS:
                judgments.append(
                    {
                        "judgment_key": (
                            f"{int(case['video_id'])}:{int(case['block_id'])}:"
                            f"{relationship}"
                        ),
                        "source_packet_index": packet_index,
                        "source_packet_fingerprint": packet["input_fingerprint"],
                        "relationship": relationship,
                        "probability": round(float(probabilities[relationship]), 6),
                        "pastor": dict(case["pastor"]),
                        "video_id": int(case["video_id"]),
                        "youtube_video_id": str(case["youtube_video_id"]),
                        "title": str(case["title"]),
                        "block_id": int(case["block_id"]),
                        "start_seconds": float(case["start_seconds"]),
                        "end_seconds": float(case["end_seconds"]),
                        "leading_context": str(case["leading_context"]),
                        "target_text": str(case["target_text"]),
                        "trailing_context": str(case["trailing_context"]),
                    }
                )
    return judgments


def _boundary_probes(
    judgments: Sequence[Mapping[str, Any]],
    threshold: float,
) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for relationship in SALVATION_RELATIONSHIPS:
        candidates = [
            judgment
            for judgment in judgments
            if judgment["relationship"] == relationship
        ]
        below = [
            judgment
            for judgment in candidates
            if float(judgment["probability"]) < threshold
        ]
        at_or_above = [
            judgment
            for judgment in candidates
            if float(judgment["probability"]) >= threshold
        ]
        if below:
            lower = max(
                below,
                key=lambda item: (
                    float(item["probability"]),
                    str(item["judgment_key"]),
                ),
            )
            probes.append(
                {
                    **lower,
                    "boundary_side": (
                        "below" if at_or_above else "strongest_available_below"
                    ),
                }
            )
        if at_or_above:
            upper = min(
                at_or_above,
                key=lambda item: (
                    float(item["probability"]),
                    str(item["judgment_key"]),
                ),
            )
            probes.append(
                {
                    **upper,
                    "boundary_side": (
                        "at_or_above" if below else "weakest_available_at_or_above"
                    ),
                }
            )
    return probes


def build_salvation_observation_threshold_review(
    input_paths: Sequence[Path] = DEFAULT_SALVATION_RELATIONSHIP_REVIEW_INPUTS,
    *,
    candidate_threshold: float = DEFAULT_SALVATION_OBSERVATION_THRESHOLD,
) -> dict[str, Any]:
    """Build a provider-free boundary packet from persisted leaf probabilities."""
    if not 0.0 < candidate_threshold < 1.0:
        raise ValueError("Candidate observation threshold must be between zero and one")
    packets = [_load_review_packet(path) for path in input_paths]
    fingerprints = [str(packet["input_fingerprint"]) for packet in packets]
    if len(set(fingerprints)) != len(fingerprints):
        raise ValueError("Salvation relationship review inputs must be distinct")
    judgments = _flatten_leaf_judgments(packets)
    probes = _boundary_probes(judgments, candidate_threshold)
    probe_sides = {
        relationship: sorted(
            str(probe["boundary_side"])
            for probe in probes
            if probe["relationship"] == relationship
        )
        for relationship in SALVATION_RELATIONSHIPS
    }
    counts_by_threshold = {
        f"{threshold:.2f}": sum(
            float(judgment["probability"]) >= threshold
            for judgment in judgments
        )
        for threshold in COMPARISON_THRESHOLDS
    }
    counts_by_relationship = {
        relationship: {
            f"{threshold:.2f}": sum(
                judgment["relationship"] == relationship
                and float(judgment["probability"]) >= threshold
                for judgment in judgments
            )
            for threshold in COMPARISON_THRESHOLDS
        }
        for relationship in SALVATION_RELATIONSHIPS
    }
    identity = {
        "schema_version": SALVATION_OBSERVATION_THRESHOLD_REVIEW_SCHEMA_VERSION,
        "review_policy_version": (
            SALVATION_OBSERVATION_THRESHOLD_REVIEW_POLICY_VERSION
        ),
        "leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "candidate_threshold": candidate_threshold,
        "source_packets": [
            {
                "artifact": path.name,
                "input_fingerprint": fingerprint,
            }
            for path, fingerprint in zip(input_paths, fingerprints, strict=True)
        ],
        "judgment_count": len(judgments),
        "counts_by_threshold": counts_by_threshold,
        "counts_by_relationship": counts_by_relationship,
        "probe_sides_by_relationship": probe_sides,
        "probes": probes,
    }
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "observation_threshold_pending_review",
        "policy_effect": "none",
        "interpretation": (
            "This provider-free packet calibrates only the code-owned collection "
            "threshold. It does not change or rerun the frozen leaf questions, change "
            "the broad route, or activate ordinary collection. For each relationship, "
            "it pairs the nearest cached judgment below the candidate boundary with "
            "the nearest judgment at or above it when both exist, and exposes a "
            "one-sided coverage gap otherwise."
        ),
    }


def render_salvation_observation_threshold_review(
    packet: Mapping[str, Any],
) -> str:
    thresholds = list(packet["counts_by_threshold"])
    lines = [
        "# Salvation leaf observation threshold review",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Leaf pack: `{packet['leaf_pack_version']}`",
        f"- Candidate threshold: `{float(packet['candidate_threshold']):.2f}`",
        f"- Cached leaf judgments: `{packet['judgment_count']}`",
        f"- Boundary probes: `{len(packet['probes'])}`",
        "- One-sided leaves: `"
        + str(
            sum(
                len(sides) < 2
                for sides in packet["probe_sides_by_relationship"].values()
            )
        )
        + "`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "Review each pair as a collection-policy decision: should the named leaf be "
        "stored as an affirmative observation from the target text? Context may "
        "clarify the target but cannot independently establish the leaf. A rejected "
        "probe changes threshold policy, not the frozen question.",
        "",
        "## Threshold impact",
        "",
        "| Threshold | Collected judgments | Share |",
        "| --- | ---: | ---: |",
    ]
    total = int(packet["judgment_count"])
    for threshold in thresholds:
        count = int(packet["counts_by_threshold"][threshold])
        lines.append(f"| {threshold} | {count} | {count / total:.1%} |")
    lines.extend(
        [
            "",
            "Counts describe only the two reviewed packets, not corpus prevalence.",
            "",
            "## Per-relationship impact",
            "",
            "| Relationship | " + " | ".join(thresholds) + " |",
            "| --- | " + " | ".join("---:" for _ in thresholds) + " |",
        ]
    )
    for relationship, counts in packet["counts_by_relationship"].items():
        lines.append(
            f"| {relationship} | "
            + " | ".join(str(counts[threshold]) for threshold in thresholds)
            + " |"
        )
    for relationship in SALVATION_RELATIONSHIPS:
        lines.extend(["", f"## {relationship}", ""])
        for probe in packet["probes"]:
            if probe["relationship"] != relationship:
                continue
            lines.extend(
                [
                    f"### {probe['boundary_side']} / {float(probe['probability']):.3f}",
                    "",
                    f"- Case: `{probe['video_id']}:{probe['block_id']}` — "
                    f"{probe['pastor']['display_name']}",
                    f"- Recording: `{probe['youtube_video_id']}` — {probe['title']}",
                    f"- Time: `{probe['start_seconds']}`–`{probe['end_seconds']}`",
                    f"- Source packet: `{probe['source_packet_fingerprint']}`",
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


def write_salvation_observation_threshold_review(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    json_path = path.expanduser().resolve()
    markdown_path = json_path.with_suffix(".md")
    expected_json = (
        json.dumps(packet, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    expected_markdown = render_salvation_observation_threshold_review(packet)
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
