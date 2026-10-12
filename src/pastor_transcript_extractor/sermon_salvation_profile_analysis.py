"""Provider-free repeatability diagnostics for collected salvation observations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.sermon_salvation_observation_review import (
    load_salvation_observation_sources,
)
from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES,
    SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
    UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS,
)
from pastor_transcript_extractor.sermon_topic_stage4 import (
    measurement_repeatability_diagnostics,
)
from pastor_transcript_extractor.storage import Database


SALVATION_PROFILE_REPEATABILITY_SCHEMA_VERSION = 1
SALVATION_PROFILE_REPEATABILITY_POLICY_VERSION = (
    "salvation-profile-repeatability-v1-equal-sermon"
)
APPROVED_SALVATION_COLLECTION_REVIEW_FINGERPRINT = (
    "7865d2213837191ea50764fddfa93df591434e19911e13d6a6c097a5a16aa8fd"
)
DEFAULT_SALVATION_PROFILE_REPEATABILITY_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-profile-repeatability-v1.json"
)
SALVATION_PROFILE_WATCH_FIXTURES = {
    "590:34:faith_as_receiving_response": "isolated_false_negative_watch",
}


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _validate_approved_review(review: Mapping[str, Any]) -> None:
    if review.get("input_fingerprint") != APPROVED_SALVATION_COLLECTION_REVIEW_FINGERPRINT:
        raise ValueError(
            "Salvation profile repeatability requires the approved nine-leaf "
            "collection review fingerprint"
        )
    if review.get("observation_policy_version") != SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION:
        raise ValueError("Approved salvation review uses a different observation policy")
    if review.get("question_pack_version") != SALVATION_RELATIONSHIPS_PACK_VERSION:
        raise ValueError("Approved salvation review uses a different question pack")
    if review.get("observation_thresholds") != SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS:
        raise ValueError("Approved salvation review has different observation thresholds")
    if review.get("measurement_statuses") != SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES:
        raise ValueError("Approved salvation review has different measurement statuses")


def _sermon_measurements(
    source: Mapping[str, Any],
    cohort_sermon: Mapping[str, Any],
    *,
    profile_id: int,
) -> dict[str, Any]:
    artifact = source["artifact"]
    blocks = artifact.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError(f"Video {source['video_id']} has malformed relationship blocks")
    routed_blocks = [
        block
        for block in blocks
        if isinstance(block, Mapping)
        and isinstance(block.get("route"), Mapping)
        and block["route"].get("route") is True
    ]
    routed_count = int(artifact.get("routed_block_count", -1))
    if routed_count <= 0 or routed_count != len(routed_blocks):
        raise ValueError(
            f"Video {source['video_id']} has inconsistent routed salvation blocks"
        )
    relationships: dict[str, Any] = {}
    for relationship in SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS:
        evidence = []
        for block in routed_blocks:
            observations = block.get("observations")
            if not isinstance(observations, list):
                raise ValueError(
                    f"Video {source['video_id']} has malformed salvation observations"
                )
            if any(
                isinstance(item, Mapping)
                and item.get("relationship") == relationship
                for item in observations
            ):
                evidence.append(
                    {
                        "block_id": int(block["block_id"]),
                        "case_key": f"{int(source['video_id'])}:{int(block['block_id'])}",
                    }
                )
        relationships[relationship] = {
            "evidence": evidence,
            "observation_count": len(evidence),
            "observed": bool(evidence),
            "routed_block_fraction": round(len(evidence) / routed_count, 6),
        }
    return {
        "period_key": str(cohort_sermon["period_key"]),
        "profile_id": profile_id,
        "relationships": relationships,
        "routed_block_count": routed_count,
        "series_key": str(cohort_sermon["series_key"]),
        "source_artifact_sha256": str(source["stored_artifact_sha256"]),
        "title": str(source["title"]),
        "video_id": int(source["video_id"]),
        "youtube_video_id": str(source["youtube_video_id"]),
    }


def build_salvation_profile_repeatability(
    sources: Sequence[Mapping[str, Any]],
    cohort: Mapping[str, Any],
    readiness: Mapping[str, Any],
    approved_review: Mapping[str, Any],
) -> dict[str, Any]:
    """Build descriptive equal-sermon diagnostics without provider calls."""
    _validate_approved_review(approved_review)
    if readiness.get("ready") is not True:
        raise ValueError("Salvation profile repeatability requires ready Stage 4 inputs")
    if approved_review.get("cohort_sha256") != cohort.get("cohort_sha256"):
        raise ValueError("Approved salvation review uses a different cohort")
    if approved_review.get("readiness_input_fingerprint") != readiness.get(
        "input_fingerprint"
    ):
        raise ValueError("Stage 4 readiness changed after the approved salvation review")
    approved_sources = approved_review.get("source_artifacts")
    current_sources = sorted(
        (
            {
                "stored_artifact_sha256": str(source["stored_artifact_sha256"]),
                "video_id": int(source["video_id"]),
            }
            for source in sources
        ),
        key=lambda item: item["video_id"],
    )
    if not isinstance(approved_sources, list) or current_sources != sorted(
        (
            {
                "stored_artifact_sha256": str(item["stored_artifact_sha256"]),
                "video_id": int(item["video_id"]),
            }
            for item in approved_sources
            if isinstance(item, Mapping)
        ),
        key=lambda item: item["video_id"],
    ):
        raise ValueError(
            "Salvation relationship artifacts changed after the approved collection review"
        )
    sources_by_video = {int(source["video_id"]): source for source in sources}
    pastor_reports = []
    for pastor, ready_pastor in zip(
        cohort["pastors"], readiness["pastors"], strict=True
    ):
        profile_ids = ready_pastor.get("effective_profile_ids")
        if not isinstance(profile_ids, list) or len(profile_ids) != 1:
            raise ValueError(
                f"{pastor.get('display_name')} has no single effective profile"
            )
        sermons = []
        for cohort_sermon in pastor["sermons"]:
            video_id = int(cohort_sermon["video_id"])
            source = sources_by_video.get(video_id)
            if source is None:
                raise ValueError(f"Missing salvation source for video {video_id}")
            sermons.append(
                _sermon_measurements(
                    source,
                    cohort_sermon,
                    profile_id=int(profile_ids[0]),
                )
            )
        relationships = {}
        for relationship in SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS:
            rows = [
                {
                    **sermon,
                    "routed_block_fraction": sermon["relationships"][relationship][
                        "routed_block_fraction"
                    ],
                }
                for sermon in sermons
            ]
            diagnostics = measurement_repeatability_diagnostics(
                rows,
                measurement_key="routed_block_fraction",
            )
            diagnostics["sermons_with_observation"] = sum(
                sermon["relationships"][relationship]["observed"]
                for sermon in sermons
            )
            diagnostics["total_observation_count"] = sum(
                sermon["relationships"][relationship]["observation_count"]
                for sermon in sermons
            )
            relationships[relationship] = diagnostics
        pastor_reports.append(
            {
                "display_name": pastor.get("display_name"),
                "pastor_id": pastor.get("pastor_id"),
                "profile_id": int(profile_ids[0]),
                "sermon_count": len(sermons),
                "series_count": len({sermon["series_key"] for sermon in sermons}),
                "period_count": len({sermon["period_key"] for sermon in sermons}),
                "slug": pastor.get("slug"),
                "sermons": sermons,
                "relationships": relationships,
            }
        )
    source_artifacts = current_sources
    identity = {
        "schema_version": SALVATION_PROFILE_REPEATABILITY_SCHEMA_VERSION,
        "policy_version": SALVATION_PROFILE_REPEATABILITY_POLICY_VERSION,
        "approved_collection_review_fingerprint": (
            APPROVED_SALVATION_COLLECTION_REVIEW_FINGERPRINT
        ),
        "cohort_id": cohort.get("cohort_id"),
        "cohort_sha256": cohort.get("cohort_sha256"),
        "readiness_input_fingerprint": readiness.get("input_fingerprint"),
        "question_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "observation_policy_version": SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
        "observation_thresholds": dict(SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS),
        "measurement_statuses": dict(SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES),
        "measured_relationships": list(SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS),
        "unresolved_relationships": sorted(
            UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS
        ),
        "watch_fixtures": dict(SALVATION_PROFILE_WATCH_FIXTURES),
        "source_artifacts": source_artifacts,
        "pastors": pastor_reports,
    }
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "diagnostic_only_repeatability_threshold_not_calibrated",
        "comparative_use_allowed": False,
        "provider_requests": 0,
        "interpretation": (
            "Equal-sermon observation-rate diagnostics only. They measure sample "
            "repeatability, not a pastor's theological stance. The three unresolved "
            "relationships remain unavailable and are not represented as zero."
        ),
    }


def evaluate_salvation_profile_repeatability(
    database: Database,
    cohort: Mapping[str, Any],
    approved_review: Mapping[str, Any],
) -> dict[str, Any]:
    sources, readiness = load_salvation_observation_sources(database, cohort)
    return build_salvation_profile_repeatability(
        sources,
        cohort,
        readiness,
        approved_review,
    )


def render_salvation_profile_repeatability(report: Mapping[str, Any]) -> str:
    def formatted(value: object) -> str:
        return "—" if value is None else f"{float(value):.3f}"

    lines = [
        "# Salvation relationship profile repeatability",
        "",
        f"- Status: `{report['status']}`",
        f"- Comparative use allowed: `{str(report['comparative_use_allowed']).lower()}`",
        f"- Provider requests: `{report['provider_requests']}`",
        f"- Approved collection review: `{report['approved_collection_review_fingerprint']}`",
        f"- Input fingerprint: `{report['input_fingerprint']}`",
        "",
        str(report["interpretation"]),
        "",
        "Unresolved (retained as raw judgments, excluded here): "
        + ", ".join(f"`{item}`" for item in report["unresolved_relationships"])
        + ".",
        "",
    ]
    for pastor in report["pastors"]:
        lines.extend(
            [
                f"## {pastor['display_name']}",
                "",
                (
                    f"Profile `{pastor['profile_id']}`; sermons "
                    f"{pastor['sermon_count']}; series {pastor['series_count']}; "
                    f"periods {pastor['period_count']}."
                ),
                "",
                "| Relationship | Mean routed-block fraction | Sermons observed | Observations | LOO max Δ | Series max Δ | Period max Δ |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for relationship in report["measured_relationships"]:
            metrics = pastor["relationships"][relationship]
            lines.append(
                f"| `{relationship}` | {formatted(metrics['equal_sermon_mean'])} | "
                f"{metrics['sermons_with_observation']}/{pastor['sermon_count']} | "
                f"{metrics['total_observation_count']} | "
                f"{formatted(metrics['leave_one_sermon_max_absolute_delta'])} | "
                f"{formatted(metrics['maximum_between_series_delta'])} | "
                f"{formatted(metrics['maximum_between_period_delta'])} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_salvation_profile_repeatability(
    path: Path,
    report: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    """Write or exactly reuse one fingerprinted JSON/Markdown report."""
    json_path = path.expanduser().resolve()
    markdown_path = json_path.with_suffix(".md")
    reused = False
    if json_path.exists() and markdown_path.exists():
        try:
            existing = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing = None
        reused = (
            isinstance(existing, Mapping)
            and existing.get("input_fingerprint") == report.get("input_fingerprint")
        )
    if reused:
        return json_path, markdown_path, True
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        render_salvation_profile_repeatability(report),
        encoding="utf-8",
    )
    return json_path, markdown_path, False
