"""Read-only readiness audit for TypeSafe topic stability evaluation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from pastor_transcript_extractor.sermon_topic_projection import (
    assess_topic_profile_projection,
)
from pastor_transcript_extractor.storage import Database


TOPIC_STAGE4_READINESS_SCHEMA_VERSION = 1
TOPIC_STAGE4_READINESS_POLICY_VERSION = (
    "reviewed-profile-two-series-two-periods-v1"
)
DEFAULT_TOPIC_STAGE4_COHORT = (
    Path(__file__).resolve().parents[2]
    / "evaluation"
    / "sermon-topics"
    / "stage3-whole-sermon-cohort-v1.json"
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


def load_topic_stage4_cohort(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read topic stability cohort: {resolved}") from error
    if not isinstance(payload, dict):
        raise ValueError("Topic stability cohort must be a JSON object")
    pastors = payload.get("pastors")
    if not isinstance(pastors, list) or not pastors:
        raise ValueError("Topic stability cohort must contain pastors")
    seen_video_ids: set[int] = set()
    for pastor in pastors:
        if not isinstance(pastor, Mapping):
            raise ValueError("Topic stability pastor entries must be objects")
        sermons = pastor.get("sermons")
        if not isinstance(sermons, list) or not sermons:
            raise ValueError("Every topic stability pastor needs sermons")
        for sermon in sermons:
            if not isinstance(sermon, Mapping):
                raise ValueError("Topic stability sermon entries must be objects")
            video_id = sermon.get("video_id")
            youtube_id = sermon.get("youtube_video_id")
            if not isinstance(video_id, int) or isinstance(video_id, bool):
                raise ValueError("Every topic stability sermon needs an integer video_id")
            if not isinstance(youtube_id, str) or not youtube_id.strip():
                raise ValueError("Every topic stability sermon needs a youtube_video_id")
            if video_id in seen_video_ids:
                raise ValueError(f"Duplicate topic stability video_id: {video_id}")
            seen_video_ids.add(video_id)
    payload["cohort_path"] = str(resolved)
    payload["cohort_sha256"] = _canonical_hash(
        {key: value for key, value in payload.items() if key != "cohort_path"}
    )
    return payload


def assess_topic_stage4_readiness(
    database: Database,
    cohort: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify reviewed identity, current projections, and independent strata."""
    videos_by_id = {video.id: video for video in database.list_videos()}
    expected_pack = cohort.get("question_pack_version")
    pastor_results = []
    cohort_blockers: set[str] = set()
    gate_fingerprints = []

    for pastor in cohort["pastors"]:
        sermons = pastor["sermons"]
        sermon_results = []
        effective_profile_ids: set[int] = set()
        series_keys: set[str] = set()
        period_keys: set[str] = set()
        missing_series = 0
        missing_period = 0
        blockers: set[str] = set()

        for entry in sermons:
            video_id = int(entry["video_id"])
            video = videos_by_id.get(video_id)
            series_key = entry.get("series_key")
            period_key = entry.get("period_key")
            if isinstance(series_key, str) and series_key.strip():
                series_keys.add(series_key.strip())
            else:
                missing_series += 1
            if isinstance(period_key, str) and period_key.strip():
                period_keys.add(period_key.strip())
            else:
                missing_period += 1
            if video is None:
                blockers.add("video_unavailable")
                sermon_results.append(
                    {
                        "eligible": False,
                        "reason_codes": ["video_unavailable"],
                        "video_id": video_id,
                        "youtube_video_id": entry["youtube_video_id"],
                    }
                )
                continue
            if video.youtube_video_id != entry["youtube_video_id"]:
                blockers.add("video_identity_mismatch")
                sermon_results.append(
                    {
                        "eligible": False,
                        "reason_codes": ["video_identity_mismatch"],
                        "video_id": video_id,
                        "youtube_video_id": video.youtube_video_id,
                    }
                )
                continue
            gate = assess_topic_profile_projection(database, video)
            gate_fingerprints.append(
                {"fingerprint": gate.input_fingerprint, "video_id": video_id}
            )
            reasons = list(gate.reason_codes)
            if gate.topic_question_pack_version != expected_pack:
                reasons.append("question_pack_mismatch")
            eligible = gate.eligible and not reasons
            if gate.profile_id is not None:
                effective_profile_ids.add(gate.profile_id)
            if not eligible:
                blockers.update(reasons)
            sermon_results.append(
                {
                    "eligible": eligible,
                    "profile_id": gate.profile_id,
                    "reason_codes": reasons,
                    "series_key": series_key,
                    "period_key": period_key,
                    "video_id": video_id,
                    "youtube_video_id": video.youtube_video_id,
                }
            )

        if len(effective_profile_ids) > 1:
            blockers.add("split_effective_profile_membership")
        if missing_series:
            blockers.add("series_metadata_missing")
        elif len(series_keys) < 2:
            blockers.add("insufficient_independent_series")
        if missing_period:
            blockers.add("period_metadata_missing")
        elif len(period_keys) < 2:
            blockers.add("insufficient_independent_periods")
        if sum(bool(item["eligible"]) for item in sermon_results) < len(sermons):
            blockers.add("incomplete_eligible_sermon_set")
        cohort_blockers.update(blockers)
        pastor_results.append(
            {
                "blockers": sorted(blockers),
                "display_name": pastor.get("display_name"),
                "effective_profile_ids": sorted(effective_profile_ids),
                "pastor_id": pastor.get("pastor_id"),
                "period_keys": sorted(period_keys),
                "ready": not blockers,
                "series_keys": sorted(series_keys),
                "sermons": sermon_results,
                "slug": pastor.get("slug"),
            }
        )

    input_fingerprint = _canonical_hash(
        {
            "cohort_sha256": cohort.get("cohort_sha256")
            or _canonical_hash(cohort),
            "gate_fingerprints": sorted(
                gate_fingerprints,
                key=lambda item: int(item["video_id"]),
            ),
            "policy_version": TOPIC_STAGE4_READINESS_POLICY_VERSION,
            "schema_version": TOPIC_STAGE4_READINESS_SCHEMA_VERSION,
        }
    )
    return {
        "schema_version": TOPIC_STAGE4_READINESS_SCHEMA_VERSION,
        "policy_version": TOPIC_STAGE4_READINESS_POLICY_VERSION,
        "input_fingerprint": input_fingerprint,
        "cohort_id": cohort.get("cohort_id"),
        "cohort_sha256": cohort.get("cohort_sha256"),
        "ready": not cohort_blockers,
        "blockers": sorted(cohort_blockers),
        "pastors": pastor_results,
        "interpretation": (
            "Readiness only. A ready result permits a stability evaluation; it "
            "does not establish topic stability or theological stance."
        ),
    }
