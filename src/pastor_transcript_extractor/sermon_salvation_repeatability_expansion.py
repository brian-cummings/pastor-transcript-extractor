"""Provider-free candidate inventory for expanding salvation repeatability cohorts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.models import Video
from pastor_transcript_extractor.sermon_topic_projection import (
    assess_topic_profile_projection,
)
from pastor_transcript_extractor.sermon_policy import video_is_sermon_eligible
from pastor_transcript_extractor.sermon_topic_stage4 import (
    assess_topic_stage4_readiness,
)
from pastor_transcript_extractor.storage import Database


SALVATION_REPEATABILITY_EXPANSION_SCHEMA_VERSION = 1
SALVATION_REPEATABILITY_EXPANSION_POLICY_VERSION = (
    "salvation-repeatability-expansion-candidates-v1"
)
DEFAULT_SALVATION_REPEATABILITY_EXPANSION_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-repeatability-expansion-candidates-v1.json"
)
TARGET_SERMONS_PER_PASTOR = 12
TARGET_MINIMUM_SERIES = 3
TARGET_MINIMUM_SERMONS_PER_SERIES = 2
TARGET_MINIMUM_PERIODS = 2
TARGET_MINIMUM_SERMONS_PER_PERIOD = 3
CONVERGENCE_SAMPLE_SIZES = (3, 4, 5, 6, 8, 10, 12)


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _period_key(video: Video) -> str | None:
    if video.published_at is None:
        return None
    half = "h1" if video.published_at.month <= 6 else "h2"
    return f"{video.published_at.year}-{half}"


def build_salvation_repeatability_expansion_plan(
    candidates: Sequence[Mapping[str, Any]],
    cohort: Mapping[str, Any],
    readiness: Mapping[str, Any],
) -> dict[str, Any]:
    """Group pre-gated candidates without pretending titles establish a series."""
    if readiness.get("ready") is not True:
        raise ValueError("Expansion planning requires ready baseline Stage 4 inputs")
    target_profiles: dict[int, Mapping[str, Any]] = {}
    baseline_video_ids: set[int] = set()
    for pastor, ready_pastor in zip(
        cohort["pastors"], readiness["pastors"], strict=True
    ):
        profile_ids = ready_pastor.get("effective_profile_ids")
        if not isinstance(profile_ids, list) or len(profile_ids) != 1:
            raise ValueError(
                f"{pastor.get('display_name')} has no single effective profile"
            )
        profile_id = int(profile_ids[0])
        target_profiles[profile_id] = pastor
        baseline_video_ids.update(
            int(sermon["video_id"]) for sermon in pastor["sermons"]
        )
    grouped: dict[int, list[dict[str, Any]]] = {
        profile_id: [] for profile_id in target_profiles
    }
    for raw in candidates:
        profile_id = int(raw["profile_id"])
        if profile_id not in grouped:
            continue
        candidate = dict(raw)
        candidate["already_in_baseline"] = (
            int(candidate["video_id"]) in baseline_video_ids
        )
        grouped[profile_id].append(candidate)
    pastor_plans = []
    for profile_id, pastor in target_profiles.items():
        rows = sorted(
            grouped[profile_id],
            key=lambda item: (
                str(item.get("published_at") or ""),
                int(item["video_id"]),
            ),
        )
        dated = [item for item in rows if item.get("period_key")]
        pastor_plans.append(
            {
                "display_name": pastor.get("display_name"),
                "pastor_id": pastor.get("pastor_id"),
                "profile_id": profile_id,
                "slug": pastor.get("slug"),
                "baseline_video_ids": sorted(
                    int(sermon["video_id"]) for sermon in pastor["sermons"]
                ),
                "eligible_candidate_count": len(rows),
                "dated_candidate_count": len(dated),
                "period_keys": sorted(
                    {str(item["period_key"]) for item in dated}
                ),
                "candidates": rows,
                "selection_status": (
                    "candidate_count_sufficient_series_review_required"
                    if len(rows) >= TARGET_SERMONS_PER_PASTOR
                    else "insufficient_eligible_candidates"
                ),
            }
        )
    identity = {
        "schema_version": SALVATION_REPEATABILITY_EXPANSION_SCHEMA_VERSION,
        "policy_version": SALVATION_REPEATABILITY_EXPANSION_POLICY_VERSION,
        "cohort_id": cohort.get("cohort_id"),
        "cohort_sha256": cohort.get("cohort_sha256"),
        "readiness_input_fingerprint": readiness.get("input_fingerprint"),
        "selection_contract": {
            "target_sermons_per_pastor": TARGET_SERMONS_PER_PASTOR,
            "minimum_series": TARGET_MINIMUM_SERIES,
            "minimum_sermons_per_series": TARGET_MINIMUM_SERMONS_PER_SERIES,
            "minimum_periods": TARGET_MINIMUM_PERIODS,
            "minimum_sermons_per_period": TARGET_MINIMUM_SERMONS_PER_PERIOD,
            "convergence_sample_sizes": list(CONVERGENCE_SAMPLE_SIZES),
            "equal_sermon_weighting": True,
        },
        "pastors": pastor_plans,
    }
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "candidate_inventory_pending_bounded_series_review",
        "provider_requests": 0,
        "interpretation": (
            "This inventory is not a cohort and grants no analytical credit. "
            "Eligibility and dates are code-verified; series membership is left "
            "unassigned because titles alone do not prove a sermon series. The "
            "next implementation step must produce an exact proposed cohort for "
            "review rather than asking the operator to select sermons."
        ),
    }


def evaluate_salvation_repeatability_expansion_plan(
    database: Database,
    cohort: Mapping[str, Any],
) -> dict[str, Any]:
    readiness = assess_topic_stage4_readiness(database, cohort)
    if not readiness["ready"]:
        raise ValueError(
            "Expansion planning requires ready baseline Stage 4 inputs: "
            + ", ".join(readiness["blockers"])
        )
    target_profile_ids = {
        int(profile_id)
        for pastor in readiness["pastors"]
        for profile_id in pastor["effective_profile_ids"]
    }
    candidates = []
    for video in database.list_videos():
        if not video_is_sermon_eligible(
            video.duration_seconds,
            video.published_at,
        ):
            continue
        gate = assess_topic_profile_projection(database, video)
        if not gate.eligible or gate.profile_id not in target_profile_ids:
            continue
        candidates.append(
            {
                "channel_name": video.channel_name,
                "eligible_block_count": gate.eligible_block_count,
                "gate_input_fingerprint": gate.input_fingerprint,
                "period_key": _period_key(video),
                "profile_id": gate.profile_id,
                "published_at": (
                    video.published_at.isoformat()
                    if video.published_at is not None
                    else None
                ),
                "source_id": video.source_id,
                "title": video.title,
                "video_id": video.id,
                "youtube_video_id": video.youtube_video_id,
            }
        )
    return build_salvation_repeatability_expansion_plan(
        candidates,
        cohort,
        readiness,
    )


def render_salvation_repeatability_expansion_plan(
    report: Mapping[str, Any],
) -> str:
    contract = report["selection_contract"]
    lines = [
        "# Salvation repeatability expansion candidates",
        "",
        f"- Status: `{report['status']}`",
        f"- Provider requests: `{report['provider_requests']}`",
        f"- Target sermons per pastor: `{contract['target_sermons_per_pastor']}`",
        f"- Minimum series: `{contract['minimum_series']}` with at least "
        f"`{contract['minimum_sermons_per_series']}` sermons each",
        f"- Minimum periods: `{contract['minimum_periods']}` with at least "
        f"`{contract['minimum_sermons_per_period']}` sermons each",
        "- Convergence sample sizes: `"
        + ", ".join(str(value) for value in contract["convergence_sample_sizes"])
        + "`",
        f"- Input fingerprint: `{report['input_fingerprint']}`",
        "",
        str(report["interpretation"]),
        "",
    ]
    for pastor in report["pastors"]:
        lines.extend(
            [
                f"## {pastor['display_name']}",
                "",
                f"Profile `{pastor['profile_id']}`; status "
                f"`{pastor['selection_status']}`; eligible candidates "
                f"`{pastor['eligible_candidate_count']}`; dated "
                f"`{pastor['dated_candidate_count']}`.",
                "",
                "| Video | Date | Period | Baseline | Eligible blocks | Title |",
                "| ---: | --- | --- | --- | ---: | --- |",
            ]
        )
        for candidate in pastor["candidates"]:
            title = str(candidate["title"]).replace("|", "\\|")
            lines.append(
                f"| {candidate['video_id']} | {candidate.get('published_at') or '—'} | "
                f"{candidate.get('period_key') or '—'} | "
                f"{'yes' if candidate['already_in_baseline'] else 'no'} | "
                f"{candidate.get('eligible_block_count') or 0} | {title} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_salvation_repeatability_expansion_plan(
    path: Path,
    report: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
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
        render_salvation_repeatability_expansion_plan(report),
        encoding="utf-8",
    )
    return json_path, markdown_path, False
