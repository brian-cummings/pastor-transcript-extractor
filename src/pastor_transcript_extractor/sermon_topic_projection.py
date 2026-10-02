"""Deterministic activation gate for profile-level TypeSafe topic projection."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from pastor_transcript_extractor.analysis_readiness import ELIGIBLE_PROFILE_STATES
from pastor_transcript_extractor.disposition import ACCEPTED_SERMON
from pastor_transcript_extractor.models import Video
from pastor_transcript_extractor.sermon_topics import (
    PROFILE_ANALYSIS_ACTIVATION_REQUIREMENT,
    resolve_topic_analysis_artifact,
)
from pastor_transcript_extractor.storage import Database


TOPIC_PROFILE_PROJECTION_SCHEMA_VERSION = 1
TOPIC_PROFILE_PROJECTION_POLICY_VERSION = (
    "accepted-sermon-effective-reviewed-profile-membership-v1"
)
TOPIC_PROFILE_PROJECTION_ACTIVATION_REQUIREMENT = (
    PROFILE_ANALYSIS_ACTIVATION_REQUIREMENT
)


@dataclass(frozen=True, slots=True)
class TopicProfileProjectionGate:
    schema_version: int
    policy_version: str
    activation_requirement: str
    eligible: bool
    reason_codes: tuple[str, ...]
    video_id: int
    youtube_video_id: str
    extraction_result_id: int | None
    source_path: str | None
    final_disposition_status: str | None
    topic_question_pack_version: str | None
    topic_analysis_fingerprint: str | None
    sermon_projection_policy_version: str | None
    sermon_projection_disposition_status: str | None
    eligible_block_count: int | None
    observation_id: int | None
    observation_input_fingerprint: str | None
    direct_profile_ids: tuple[int, ...]
    inherited_profile_ids: tuple[int, ...]
    effective_profile_ids: tuple[int, ...]
    membership_event_ids: tuple[int, ...]
    membership_reviewers: tuple[str, ...]
    profile_id: int | None
    profile_lifecycle_state: str | None
    input_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _finish_gate(values: dict[str, Any]) -> TopicProfileProjectionGate:
    values["reason_codes"] = tuple(dict.fromkeys(values["reason_codes"]))
    values["eligible"] = not values["reason_codes"]
    identity = {
        key: value
        for key, value in values.items()
        if key not in {"eligible", "input_fingerprint", "source_path"}
    }
    values["input_fingerprint"] = _canonical_hash(identity)
    return TopicProfileProjectionGate(**values)


def assess_topic_profile_projection(
    database: Database,
    video: Video,
) -> TopicProfileProjectionGate:
    """Assess current topic evidence without inference, writes, or aggregation."""
    values: dict[str, Any] = {
        "schema_version": TOPIC_PROFILE_PROJECTION_SCHEMA_VERSION,
        "policy_version": TOPIC_PROFILE_PROJECTION_POLICY_VERSION,
        "activation_requirement": TOPIC_PROFILE_PROJECTION_ACTIVATION_REQUIREMENT,
        "eligible": False,
        "reason_codes": [],
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "extraction_result_id": None,
        "source_path": None,
        "final_disposition_status": None,
        "topic_question_pack_version": None,
        "topic_analysis_fingerprint": None,
        "sermon_projection_policy_version": None,
        "sermon_projection_disposition_status": None,
        "eligible_block_count": None,
        "observation_id": None,
        "observation_input_fingerprint": None,
        "direct_profile_ids": (),
        "inherited_profile_ids": (),
        "effective_profile_ids": (),
        "membership_event_ids": (),
        "membership_reviewers": (),
        "profile_id": None,
        "profile_lifecycle_state": None,
        "input_fingerprint": "",
    }
    reasons: list[str] = values["reason_codes"]
    extraction = database.get_latest_extraction_result_for_video(video.id)
    if extraction is None or not extraction.proposed_json_path:
        reasons.append("extraction_artifact_unavailable")
        return _finish_gate(values)

    values["extraction_result_id"] = extraction.id
    source_path = Path(extraction.proposed_json_path).expanduser().resolve()
    values["source_path"] = str(source_path)
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        reasons.append("extraction_artifact_unreadable")
        return _finish_gate(values)
    if not isinstance(payload, Mapping):
        reasons.append("extraction_artifact_malformed")
        return _finish_gate(values)

    classification = _mapping(payload.get("classification"))
    if classification is None:
        reasons.append("classification_unavailable")
        classification = {}
    disposition = _mapping(payload.get("final_disposition"))
    if disposition is None:
        disposition = _mapping(classification.get("final_disposition"))
    status = disposition.get("status") if disposition is not None else None
    values["final_disposition_status"] = status if isinstance(status, str) else None
    if status != ACCEPTED_SERMON:
        reasons.append("disposition_not_accepted")

    try:
        topic_analysis = resolve_topic_analysis_artifact(classification)
    except ValueError:
        reasons.append("topic_analysis_unavailable")
        topic_analysis = None
    if topic_analysis is not None:
        values["topic_question_pack_version"] = topic_analysis.get(
            "question_pack_version"
        )
        values["topic_analysis_fingerprint"] = _canonical_hash(topic_analysis)
        projection = _mapping(topic_analysis.get("sermon_projection"))
        if projection is None:
            reasons.append("sermon_projection_unavailable")
        else:
            policy_version = projection.get("policy_version")
            values["sermon_projection_policy_version"] = (
                policy_version if isinstance(policy_version, str) else None
            )
            projection_disposition = projection.get("final_disposition_status")
            values["sermon_projection_disposition_status"] = (
                projection_disposition
                if isinstance(projection_disposition, str)
                else None
            )
            if projection_disposition != status:
                reasons.append("sermon_projection_disposition_stale")
            block_count = projection.get("eligible_block_count")
            values["eligible_block_count"] = (
                int(block_count)
                if isinstance(block_count, int) and not isinstance(block_count, bool)
                else None
            )
            if values["eligible_block_count"] is None:
                reasons.append("sermon_projection_malformed")
            elif values["eligible_block_count"] < 1:
                reasons.append("sermon_projection_has_no_eligible_evidence")

    window = _mapping(payload.get("sermon_window"))
    start_seconds = _number(window.get("start_seconds")) if window else None
    end_seconds = _number(window.get("end_seconds")) if window else None
    if (
        start_seconds is None
        or end_seconds is None
        or end_seconds <= start_seconds
    ):
        reasons.append("sermon_window_invalid")
        return _finish_gate(values)

    observation = database.get_speaker_observation_for_extraction_window(
        video.id,
        extraction.id,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )
    if observation is None:
        reasons.append("current_speaker_observation_unavailable")
        return _finish_gate(values)
    values["observation_id"] = observation.id
    values["observation_input_fingerprint"] = observation.input_fingerprint

    lineage_observation_ids = {
        item.id
        for item in database.list_speaker_observations()
        if item.video_id == video.id and item.id <= observation.id
    }
    direct_profile_ids = database.list_effective_profile_ids_for_observation(
        observation.id
    )
    inherited_profile_ids = (
        database.list_effective_profile_ids_for_superseded_observations(
            video_id=video.id,
            current_observation_id=observation.id,
        )
    )
    effective_profile_ids = (
        database.list_effective_profile_ids_for_observation_lineage(
            video_id=video.id,
            current_observation_id=observation.id,
        )
    )
    effective_events = [
        event
        for event in database.list_effective_profile_observation_events()
        if (
            event[2] in lineage_observation_ids
            and event[1] in effective_profile_ids
            and event[3] == "attach"
        )
    ]
    values["direct_profile_ids"] = tuple(sorted(direct_profile_ids))
    values["inherited_profile_ids"] = tuple(sorted(inherited_profile_ids))
    values["effective_profile_ids"] = tuple(sorted(effective_profile_ids))
    values["membership_event_ids"] = tuple(sorted(event[0] for event in effective_events))
    values["membership_reviewers"] = tuple(
        sorted({event[4] for event in effective_events if event[4].strip()})
    )
    if not effective_profile_ids:
        reasons.append("effective_profile_membership_unavailable")
        return _finish_gate(values)
    reviewed_profile_ids = {
        event[1]
        for event in effective_events
        if event[4].strip() and event[5].strip()
    }
    if reviewed_profile_ids != set(effective_profile_ids):
        reasons.append("membership_review_provenance_missing")

    canonical_profile_ids = sorted(
        {database.resolve_speaker_profile_id(profile_id) for profile_id in effective_profile_ids}
    )
    if len(canonical_profile_ids) != 1:
        reasons.append("ambiguous_effective_profile_membership")
        return _finish_gate(values)
    profile_id = canonical_profile_ids[0]
    values["profile_id"] = profile_id
    profile = database.get_speaker_profile(profile_id)
    if profile is None:
        reasons.append("canonical_profile_unavailable")
        return _finish_gate(values)
    values["profile_lifecycle_state"] = profile.lifecycle_state
    if profile.lifecycle_state not in ELIGIBLE_PROFILE_STATES:
        reasons.append("profile_lifecycle_ineligible")
    return _finish_gate(values)
