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


SALVATION_REPEATABILITY_EXPANSION_SCHEMA_VERSION = 2
SALVATION_REPEATABILITY_EXPANSION_POLICY_VERSION = (
    "salvation-repeatability-expansion-candidates-v2-period-provenance"
)
DEFAULT_SALVATION_REPEATABILITY_EXPANSION_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-repeatability-expansion-candidates-v2.json"
)
TARGET_SERMONS_PER_PASTOR = 12
TARGET_MINIMUM_SERIES = 3
TARGET_MINIMUM_SERMONS_PER_SERIES = 2
TARGET_MINIMUM_PERIODS = 2
TARGET_MINIMUM_SERMONS_PER_PERIOD = 3
CONVERGENCE_SAMPLE_SIZES = (3, 4, 5, 6, 8, 10, 12)
SALVATION_CANDIDATE_DISCOVERY_AUDIT_SCHEMA_VERSION = 1
SALVATION_CANDIDATE_DISCOVERY_AUDIT_POLICY_VERSION = (
    "salvation-candidate-discovery-audit-v1"
)
DEFAULT_SALVATION_CANDIDATE_DISCOVERY_AUDIT_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-candidate-discovery-audit-v1.json"
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
    baseline_metadata: dict[int, Mapping[str, Any]] = {}
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
        for sermon in pastor["sermons"]:
            video_id = int(sermon["video_id"])
            baseline_video_ids.add(video_id)
            baseline_metadata[video_id] = sermon
    grouped: dict[int, list[dict[str, Any]]] = {
        profile_id: [] for profile_id in target_profiles
    }
    for raw in candidates:
        profile_id = int(raw["profile_id"])
        if profile_id not in grouped:
            continue
        candidate = dict(raw)
        video_id = int(candidate["video_id"])
        candidate["already_in_baseline"] = video_id in baseline_video_ids
        baseline = baseline_metadata.get(video_id)
        candidate["period_provenance"] = (
            "database_published_at"
            if candidate.get("period_key") is not None
            else "unavailable"
        )
        if (
            candidate.get("period_key") is None
            and baseline is not None
            and baseline.get("period_key") is not None
        ):
            candidate["period_key"] = baseline.get("period_key")
            candidate["period_evidence"] = baseline.get("period_evidence")
            candidate["period_provenance"] = "reviewed_baseline_cohort"
        if baseline is not None:
            candidate["reviewed_baseline_series_key"] = baseline.get("series_key")
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
                "period_evidenced_candidate_count": len(dated),
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
                f"`{pastor['eligible_candidate_count']}`; period-evidenced "
                f"`{pastor['period_evidenced_candidate_count']}`.",
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


def load_salvation_repeatability_expansion_plan(
    path: Path,
) -> Mapping[str, Any]:
    try:
        value = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read salvation expansion inventory: {path}") from error
    if not isinstance(value, Mapping):
        raise ValueError("Salvation expansion inventory must be a JSON object")
    return value


def _discovery_category(record: Mapping[str, Any], profile_id: int) -> str:
    configured = bool(record.get("configured_for_target_pastor"))
    linked = profile_id in record.get("canonical_effective_profile_ids", [])
    if record.get("production_eligible") is not True:
        return "production_ineligible"
    if linked and record.get("gate_eligible") is True:
        return "current_inventory_candidate"
    if linked:
        return "profile_linked_analytical_gate_blocked"
    if configured and record.get("canonical_effective_profile_ids"):
        return "configured_pastor_linked_elsewhere"
    return "configured_pastor_identity_unlinked"


def build_salvation_candidate_discovery_audit(
    records: Sequence[Mapping[str, Any]],
    cohort: Mapping[str, Any],
    readiness: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> dict[str, Any]:
    """Explain candidate scarcity without granting eligibility or metadata credit."""
    if readiness.get("ready") is not True:
        raise ValueError("Candidate discovery audit requires ready baseline inputs")
    inventory_by_profile = {
        int(pastor["profile_id"]): pastor
        for pastor in inventory.get("pastors", [])
        if isinstance(pastor, Mapping) and pastor.get("profile_id") is not None
    }
    pastor_reports = []
    for pastor, ready_pastor in zip(
        cohort["pastors"], readiness["pastors"], strict=True
    ):
        profile_ids = ready_pastor.get("effective_profile_ids")
        if not isinstance(profile_ids, list) or len(profile_ids) != 1:
            raise ValueError(
                f"{pastor.get('display_name')} has no single effective profile"
            )
        profile_id = int(profile_ids[0])
        baseline = {
            int(sermon["video_id"]): sermon for sermon in pastor["sermons"]
        }
        relevant = []
        for raw in records:
            configured = raw.get("configured_pastor_id") == pastor.get("pastor_id")
            linked = profile_id in raw.get("canonical_effective_profile_ids", [])
            if not configured and not linked:
                continue
            item = dict(raw)
            item["configured_for_target_pastor"] = configured
            item["category"] = _discovery_category(item, profile_id)
            baseline_entry = baseline.get(int(item["video_id"]))
            item["already_in_baseline"] = baseline_entry is not None
            item["period_provenance"] = (
                "database_published_at"
                if item.get("published_at") is not None
                else "unavailable"
            )
            if item.get("published_at") is None and baseline_entry is not None:
                item["reviewed_period_key"] = baseline_entry.get("period_key")
                item["reviewed_period_evidence"] = baseline_entry.get(
                    "period_evidence"
                )
                item["period_provenance"] = "reviewed_baseline_cohort"
            relevant.append(item)
        relevant.sort(key=lambda item: int(item["video_id"]))
        counts: dict[str, int] = {}
        blocker_counts: dict[str, int] = {}
        for item in relevant:
            category = str(item["category"])
            counts[category] = counts.get(category, 0) + 1
            for reason in item.get("gate_reason_codes", []):
                blocker_counts[str(reason)] = blocker_counts.get(str(reason), 0) + 1
        current_ids = sorted(
            int(item["video_id"])
            for item in relevant
            if item["category"] == "current_inventory_candidate"
        )
        inventory_pastor = inventory_by_profile.get(profile_id, {})
        inventory_ids = sorted(
            int(item["video_id"])
            for item in inventory_pastor.get("candidates", [])
            if isinstance(item, Mapping)
        )
        missing_from_inventory = sorted(set(current_ids) - set(inventory_ids))
        extra_in_inventory = sorted(set(inventory_ids) - set(current_ids))
        pastor_reports.append(
            {
                "display_name": pastor.get("display_name"),
                "pastor_id": pastor.get("pastor_id"),
                "profile_id": profile_id,
                "slug": pastor.get("slug"),
                "ingested_associated_count": len(relevant),
                "category_counts": counts,
                "gate_blocker_counts": dict(sorted(blocker_counts.items())),
                "current_candidate_video_ids": current_ids,
                "inventory_candidate_video_ids": inventory_ids,
                "inventory_query_matches": (
                    not missing_from_inventory and not extra_in_inventory
                ),
                "missing_from_inventory": missing_from_inventory,
                "extra_in_inventory": extra_in_inventory,
                "identity_review_video_ids": [
                    int(item["video_id"])
                    for item in relevant
                    if item["category"]
                    in {
                        "configured_pastor_identity_unlinked",
                        "configured_pastor_linked_elsewhere",
                    }
                    and item["production_eligible"]
                ],
                "analytical_gate_review_video_ids": [
                    int(item["video_id"])
                    for item in relevant
                    if item["category"]
                    == "profile_linked_analytical_gate_blocked"
                ],
                "metadata_backfill_video_ids": [
                    int(item["video_id"])
                    for item in relevant
                    if item["category"] == "current_inventory_candidate"
                    and item.get("published_at") is None
                    and not item["already_in_baseline"]
                ],
                "videos": relevant,
            }
        )
    identity = {
        "schema_version": SALVATION_CANDIDATE_DISCOVERY_AUDIT_SCHEMA_VERSION,
        "policy_version": SALVATION_CANDIDATE_DISCOVERY_AUDIT_POLICY_VERSION,
        "cohort_id": cohort.get("cohort_id"),
        "cohort_sha256": cohort.get("cohort_sha256"),
        "readiness_input_fingerprint": readiness.get("input_fingerprint"),
        "inventory_input_fingerprint": inventory.get("input_fingerprint"),
        "pastors": pastor_reports,
    }
    blockers = []
    if any(not pastor["inventory_query_matches"] for pastor in pastor_reports):
        blockers.append("candidate_query_mismatch")
    if any(
        len(pastor["current_candidate_video_ids"]) < TARGET_SERMONS_PER_PASTOR
        for pastor in pastor_reports
    ):
        blockers.append("insufficient_current_candidate_inventory")
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "blocked" if blockers else "candidate_inventory_sufficient",
        "blockers": blockers,
        "provider_requests": 0,
        "interpretation": (
            "This audit separates ingested association, canonical profile linkage, "
            "production eligibility, analytical gate readiness, inventory-query "
            "parity, and date provenance. It does not infer dates or series from "
            "titles and does not authorize reclassification or identity changes."
        ),
    }


def evaluate_salvation_candidate_discovery_audit(
    database: Database,
    cohort: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> dict[str, Any]:
    readiness = assess_topic_stage4_readiness(database, cohort)
    if not readiness["ready"]:
        raise ValueError(
            "Candidate discovery audit requires ready baseline inputs: "
            + ", ".join(readiness["blockers"])
        )
    target_pastor_ids = {
        int(pastor["pastor_id"])
        for pastor in cohort["pastors"]
        if pastor.get("pastor_id") is not None
    }
    target_profile_ids = {
        int(profile_id)
        for pastor in readiness["pastors"]
        for profile_id in pastor["effective_profile_ids"]
    }
    linked_video_ids: set[int] = set()
    for profile_id in target_profile_ids:
        for observation_id in database.list_effective_observation_ids_for_profile(
            profile_id
        ):
            observation = database.get_speaker_observation(observation_id)
            if observation is not None:
                linked_video_ids.add(observation.video_id)
    records = []
    for video in database.list_videos():
        if video.pastor_id not in target_pastor_ids and video.id not in linked_video_ids:
            continue
        gate = assess_topic_profile_projection(database, video)
        canonical_ids = sorted(
            {
                database.resolve_speaker_profile_id(profile_id)
                for profile_id in gate.effective_profile_ids
            }
        )
        records.append(
            {
                "canonical_effective_profile_ids": canonical_ids,
                "channel_name": video.channel_name,
                "configured_pastor_id": video.pastor_id,
                "duration_seconds": video.duration_seconds,
                "gate_eligible": gate.eligible,
                "gate_input_fingerprint": gate.input_fingerprint,
                "gate_reason_codes": list(gate.reason_codes),
                "production_eligible": video_is_sermon_eligible(
                    video.duration_seconds,
                    video.published_at,
                ),
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
    return build_salvation_candidate_discovery_audit(
        records,
        cohort,
        readiness,
        inventory,
    )


def render_salvation_candidate_discovery_audit(report: Mapping[str, Any]) -> str:
    lines = [
        "# Salvation repeatability candidate-discovery audit",
        "",
        f"- Status: `{report['status']}`",
        f"- Blockers: `{', '.join(report['blockers']) or 'none'}`",
        f"- Provider requests: `{report['provider_requests']}`",
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
                f"Profile `{pastor['profile_id']}`; associated ingested videos "
                f"`{pastor['ingested_associated_count']}`; current candidates "
                f"`{len(pastor['current_candidate_video_ids'])}`; inventory parity "
                f"`{str(pastor['inventory_query_matches']).lower()}`.",
                "",
                "Category counts: "
                + ", ".join(
                    f"`{key}={value}`"
                    for key, value in pastor["category_counts"].items()
                )
                + ".",
                "",
                "Gate blocker counts: "
                + (
                    ", ".join(
                        f"`{key}={value}`"
                        for key, value in pastor["gate_blocker_counts"].items()
                    )
                    or "none"
                )
                + ".",
                "",
                "| Video | Category | Production eligible | DB date | Date provenance | Gate blockers | Title |",
                "| ---: | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for video in pastor["videos"]:
            title = str(video["title"]).replace("|", "\\|")
            lines.append(
                f"| {video['video_id']} | `{video['category']}` | "
                f"{'yes' if video['production_eligible'] else 'no'} | "
                f"{video.get('published_at') or '—'} | "
                f"`{video['period_provenance']}` | "
                f"{', '.join(video['gate_reason_codes']) or '—'} | {title} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_salvation_candidate_discovery_audit(
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
        render_salvation_candidate_discovery_audit(report),
        encoding="utf-8",
    )
    return json_path, markdown_path, False
