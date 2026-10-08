"""Read-only readiness audit for TypeSafe topic stability evaluation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import statistics
from typing import Any, Mapping

from pastor_transcript_extractor.sermon_topic_profile_analysis import (
    load_topic_sermon_measurements,
    materialize_topic_sermon_analysis,
)
from pastor_transcript_extractor.sermon_topic_projection import (
    assess_topic_profile_projection,
)
from pastor_transcript_extractor.sermon_topics import TOPICS
from pastor_transcript_extractor.sermon_policy import video_is_sermon_eligible
from pastor_transcript_extractor.storage import Database


TOPIC_STAGE4_READINESS_SCHEMA_VERSION = 2
TOPIC_STAGE4_READINESS_POLICY_VERSION = (
    "production-eligible-cache-aware-reviewed-profile-two-series-two-periods-v3"
)
TOPIC_STAGE4_EVALUATION_SCHEMA_VERSION = 1
TOPIC_STAGE4_EVALUATION_POLICY_VERSION = (
    "equal-sermon-series-period-diagnostics-v1"
)
TOPIC_REVIEW_BUNDLE_FORMAT = "topic-review-bundle-v1"
TOPIC_REFRESH_REASON_CODES = frozenset(
    {
        "question_pack_mismatch",
        "topic_analysis_unavailable",
    }
)
TOPIC_REVIEW_REASON_CODES = frozenset(
    {
        "whole_sermon_review_evidence_stale",
        "whole_sermon_review_unavailable",
    }
)
TOPIC_EVIDENCE_REASON_CODES = (
    TOPIC_REFRESH_REASON_CODES | TOPIC_REVIEW_REASON_CODES
)
DEFAULT_TOPIC_STAGE4_COHORT = (
    Path(__file__).resolve().parents[2]
    / "evaluation"
    / "sermon-topics"
    / "stage4-stability-cohort-v1.json"
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


def _validate_topic_stage4_cohort(payload: dict[str, Any]) -> None:
    """Validate the fully resolved cohort, including optional date provenance."""
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
                raise ValueError(
                    "Every topic stability sermon needs an integer video_id"
                )
            if not isinstance(youtube_id, str) or not youtube_id.strip():
                raise ValueError(
                    "Every topic stability sermon needs a youtube_video_id"
                )
            if video_id in seen_video_ids:
                raise ValueError(f"Duplicate topic stability video_id: {video_id}")
            seen_video_ids.add(video_id)
            period_key = sermon.get("period_key")
            if payload.get("require_period_evidence") and isinstance(
                period_key, str
            ) and period_key.strip():
                evidence = sermon.get("period_evidence")
                if not isinstance(evidence, Mapping) or any(
                    not isinstance(evidence.get(key), str)
                    or not str(evidence[key]).strip()
                    for key in ("source_kind", "value", "reference")
                ):
                    raise ValueError(
                        "Every populated Stage 4 period_key needs source_kind, "
                        f"value, and reference evidence (video {video_id})"
                    )


def load_topic_stage4_cohort(path: Path) -> dict[str, Any]:
    """Load and fingerprint one explicit, immutable Stage 4 cohort."""
    resolved = path.expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read topic stability cohort: {resolved}") from error
    if not isinstance(payload, dict):
        raise ValueError("Topic stability cohort must be a JSON object")
    _validate_topic_stage4_cohort(payload)
    source = payload.get("source_cohort")
    if source is not None:
        if not isinstance(source, Mapping):
            raise ValueError("Topic stability source_cohort must be an object")
        source_path = source.get("path")
        expected_sha256 = source.get("cohort_sha256")
        if (
            not isinstance(source_path, str)
            or not source_path.strip()
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
        ):
            raise ValueError(
                "Topic stability source_cohort needs path and cohort_sha256"
            )
        source_resolved = (resolved.parent / source_path).resolve()
        if source_resolved == resolved:
            raise ValueError("Topic stability cohort cannot source itself")
        try:
            source_payload = json.loads(source_resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(
                f"Cannot read source topic cohort: {source_resolved}"
            ) from error
        if not isinstance(source_payload, dict) or _canonical_hash(
            source_payload
        ) != expected_sha256:
            raise ValueError("Source topic cohort fingerprint does not match")
    payload["cohort_path"] = str(resolved)
    payload["cohort_sha256"] = _canonical_hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"cohort_path", "cohort_sha256"}
        }
    )
    return payload


def _identity_review_components(
    sermons: list[Mapping[str, Any]],
) -> list[list[Mapping[str, Any]]]:
    """Group reviewed profiles while keeping every unbound sermon distinct."""
    by_profile: dict[int, list[Mapping[str, Any]]] = {}
    unbound: list[list[Mapping[str, Any]]] = []
    for sermon in sermons:
        profile_id = sermon.get("profile_id")
        if isinstance(profile_id, int) and not isinstance(profile_id, bool):
            by_profile.setdefault(profile_id, []).append(sermon)
        else:
            unbound.append([sermon])
    return [*by_profile.values(), *unbound]


def build_topic_stage4_review_actions(
    pastors: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Derive a minimal, non-adjudicating handoff from readiness evidence.

    The cohort declares which sermons are intended to represent one pastor, but
    that declaration is not identity evidence. Split or absent memberships are
    connected with the minimum number of pair reviews; no relation is assumed
    until the existing review workflows are adjudicated and synchronized.
    """
    topic_actions: list[dict[str, Any]] = []
    topic_review_actions: list[dict[str, Any]] = []
    boundary_actions: list[dict[str, Any]] = []
    identity_actions: list[dict[str, Any]] = []
    metadata_actions: list[dict[str, Any]] = []
    for pastor in pastors:
        sermons = [
            sermon
            for sermon in pastor.get("sermons", [])
            if isinstance(sermon, Mapping)
        ]
        pastor_ref = {
            "display_name": pastor.get("display_name"),
            "pastor_id": pastor.get("pastor_id"),
            "slug": pastor.get("slug"),
        }

        identity_sermons = [
            sermon
            for sermon in sermons
            if isinstance(sermon.get("profile_id"), int)
            or "effective_profile_membership_unavailable"
            in sermon.get("reason_codes", [])
        ]
        components = _identity_review_components(identity_sermons)
        if len(components) > 1 and (
            "split_effective_profile_membership" in pastor.get("blockers", [])
            or any(
                "effective_profile_membership_unavailable"
                in sermon.get("reason_codes", [])
                for sermon in sermons
            )
        ):
            # Prefer the largest already-reviewed component as the anchor. A
            # tie follows frozen cohort order, not a name or title heuristic.
            cohort_order = {
                int(sermon["video_id"]): index
                for index, sermon in enumerate(sermons)
            }
            components.sort(
                key=lambda component: (
                    -len(component),
                    min(cohort_order[int(item["video_id"])] for item in component),
                )
            )
            anchor = components[0][0]
            for component in components[1:]:
                candidate = component[0]
                identity_actions.append(
                    {
                        "action_type": "review_speaker_pair",
                        "pastor": pastor_ref,
                        "video_a": {
                            "profile_id": anchor.get("profile_id"),
                            "video_id": anchor.get("video_id"),
                            "youtube_video_id": anchor.get("youtube_video_id"),
                        },
                        "video_b": {
                            "profile_id": candidate.get("profile_id"),
                            "video_id": candidate.get("video_id"),
                            "youtube_video_id": candidate.get("youtube_video_id"),
                        },
                        "instruction": (
                            "Adjudicate the exact-span pair; do not infer same "
                            "speaker from the cohort, title, or pastor name."
                        ),
                    }
                )

        for sermon in sermons:
            sermon_reason_codes = sermon.get("reason_codes", [])
            pending_topic_reasons = [
                reason
                for reason in sermon_reason_codes
                if reason in TOPIC_EVIDENCE_REASON_CODES
            ]
            refresh_reasons = [
                reason
                for reason in sermon_reason_codes
                if reason in TOPIC_REFRESH_REASON_CODES
            ]
            review_reasons = [
                reason
                for reason in sermon_reason_codes
                if reason in TOPIC_REVIEW_REASON_CODES
            ]
            if (
                "disposition_not_accepted" not in sermon_reason_codes
                and refresh_reasons
            ):
                topic_actions.append(
                    {
                        "action_type": "prepare_topic_evidence",
                        "pastor": pastor_ref,
                        "reason_codes": refresh_reasons,
                        "video_id": sermon.get("video_id"),
                        "youtube_video_id": sermon.get("youtube_video_id"),
                        "instruction": (
                            "Refresh this one currently accepted sermon on the "
                            "frozen TypeSafe pack. Prepare its whole-sermon "
                            "packet only if the refreshed disposition remains "
                            "accepted; otherwise review its boundary first."
                        ),
                    }
                )
            elif (
                "disposition_not_accepted" not in sermon_reason_codes
                and review_reasons
            ):
                topic_review_actions.append(
                    {
                        "action_type": "review_topic_evidence",
                        "pastor": pastor_ref,
                        "packet_path": sermon.get("topic_review_packet_path"),
                        "reason_codes": review_reasons,
                        "video_id": sermon.get("video_id"),
                        "youtube_video_id": sermon.get("youtube_video_id"),
                        "instruction": (
                            "Reuse the current cached topic observations and "
                            "adjudicate their fingerprint-bound whole-sermon "
                            "packet; do not reclassify this sermon."
                        ),
                    }
                )
            if "disposition_not_accepted" in sermon_reason_codes:
                boundary_actions.append(
                    {
                        "action_type": "review_sermon_boundary",
                        "pastor": pastor_ref,
                        "pending_topic_reason_codes": pending_topic_reasons,
                        "video_id": sermon.get("video_id"),
                        "youtube_video_id": sermon.get("youtube_video_id"),
                        "instruction": (
                            "Review and approve the sermon boundary; apply a "
                            "fixture correction only after that human review. "
                            "If topic evidence is pending, prepare it only after "
                            "the correction establishes the final fingerprint."
                        ),
                    }
                )

        missing_periods = [
            {
                "video_id": sermon.get("video_id"),
                "youtube_video_id": sermon.get("youtube_video_id"),
            }
            for sermon in sermons
            if not (
                isinstance(sermon.get("period_key"), str)
                and str(sermon["period_key"]).strip()
            )
        ]
        if missing_periods:
            metadata_actions.append(
                {
                    "action_type": "supply_period_metadata",
                    "pastor": pastor_ref,
                    "sermons": missing_periods,
                    "instruction": (
                        "Populate period_key only from trustworthy recording "
                        "metadata or an explicit recording date; do not infer "
                        "a period from sequence, profile, or an undated title."
                    ),
                }
            )
    # Topic refreshes and boundary corrections can supersede observations.
    # Complete those before exact-span identity review and registry sync.
    return [
        *topic_actions,
        *topic_review_actions,
        *boundary_actions,
        *identity_actions,
        *metadata_actions,
    ]


def _topic_stage4_review_evidence(
    cohort: Mapping[str, Any],
) -> dict[int, dict[str, Any]]:
    if not cohort.get("require_whole_sermon_review_evidence"):
        return {}
    raw_sets = cohort.get("whole_sermon_review_evidence", [])
    if not isinstance(raw_sets, list):
        raise ValueError("whole_sermon_review_evidence must be a list")
    cohort_path = cohort.get("cohort_path")
    if not isinstance(cohort_path, str):
        raise ValueError("Resolved topic stability cohort path is unavailable")
    root = Path(cohort_path).parent
    by_video: dict[int, dict[str, Any]] = {}
    for evidence in raw_sets:
        if not isinstance(evidence, Mapping):
            raise ValueError("Whole-sermon review evidence entries must be objects")
        video_ids = evidence.get("video_ids")
        logical_path = evidence.get("path")
        expected_sha256 = evidence.get("sha256")
        evidence_format = evidence.get("format")
        if (
            not isinstance(video_ids, list)
            or not video_ids
            or any(
                not isinstance(video_id, int) or isinstance(video_id, bool)
                for video_id in video_ids
            )
            or not isinstance(logical_path, str)
            or not logical_path.strip()
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
        ):
            raise ValueError(
                "Whole-sermon review evidence needs video_ids, path, and sha256"
            )
        if evidence_format not in {None, TOPIC_REVIEW_BUNDLE_FORMAT}:
            raise ValueError(
                f"Unsupported whole-sermon review evidence format: {evidence_format}"
            )
        path = (root / logical_path).resolve()
        try:
            content = path.read_bytes()
            actual_sha256 = hashlib.sha256(content).hexdigest()
        except OSError:
            content = None
            actual_sha256 = None
        current = actual_sha256 == expected_sha256
        if current and evidence_format == TOPIC_REVIEW_BUNDLE_FORMAT:
            try:
                bundle = json.loads(content)
            except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"Cannot read topic review evidence bundle: {path}"
                ) from error
            _validate_topic_review_bundle(
                bundle,
                expected_question_pack=cohort.get("question_pack_version"),
                expected_video_ids=video_ids,
            )
        for video_id in video_ids:
            if video_id in by_video:
                raise ValueError(
                    f"Duplicate whole-sermon review evidence for video {video_id}"
                )
            by_video[video_id] = {
                "actual_sha256": actual_sha256,
                "current": current,
                "expected_sha256": expected_sha256,
                "path": logical_path,
            }
    return by_video


def _validate_topic_review_bundle(
    payload: object,
    *,
    expected_question_pack: object,
    expected_video_ids: list[object],
) -> None:
    """Validate finalized review decisions without duplicating model evidence."""
    if not isinstance(payload, Mapping):
        raise ValueError("Topic review evidence bundle must be an object")
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported topic review evidence bundle schema_version")
    if payload.get("workflow_version") != "topic-review-adjudication-v2":
        raise ValueError("Unsupported topic review evidence bundle workflow_version")
    if payload.get("question_pack_version") != expected_question_pack:
        raise ValueError("Topic review evidence bundle question pack does not match")
    reviews = payload.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        raise ValueError("Topic review evidence bundle must contain reviews")

    expected_ids = set(expected_video_ids)
    required_checks = {
        "missed_topic_episode_search_complete",
        "projection_boundary_review_complete",
        "selected_blocks_reviewed",
    }
    reviewed_ids: set[int] = set()
    for review in reviews:
        if not isinstance(review, Mapping):
            raise ValueError("Topic review evidence bundle reviews must be objects")
        video_id = review.get("video_id")
        if not isinstance(video_id, int) or isinstance(video_id, bool):
            raise ValueError("Topic review evidence bundle video_id must be an integer")
        if video_id in reviewed_ids:
            raise ValueError(f"Duplicate topic review evidence for video {video_id}")
        reviewed_ids.add(video_id)
        if review.get("review_status") != "reviewed":
            raise ValueError(f"Topic review evidence for video {video_id} is not reviewed")
        checks = review.get("checks")
        if not isinstance(checks, Mapping) or not all(
            checks.get(check) is True for check in required_checks
        ):
            raise ValueError(
                f"Topic review evidence for video {video_id} has incomplete checks"
            )
        for field in ("reviewed_at", "reviewed_by"):
            value = review.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Topic review evidence for video {video_id} needs {field}"
                )
        for field in (
            "projection_eligibility_corrections",
            "topic_level_corrections",
        ):
            if not isinstance(review.get(field), list):
                raise ValueError(
                    f"Topic review evidence for video {video_id} needs {field}"
                )
        for field in (
            "review_fingerprint",
            "source_packet_fingerprint",
            "source_packet_sha256",
            "source_review_sha256",
        ):
            value = review.get(field)
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(
                    f"Topic review evidence for video {video_id} needs {field}"
                )

    if reviewed_ids != expected_ids:
        raise ValueError(
            "Topic review evidence bundle videos do not match its cohort mapping"
        )


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
    review_evidence = _topic_stage4_review_evidence(cohort)
    review_evidence_fingerprints = []
    production_eligibility_inputs = []

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
            production_eligible = video_is_sermon_eligible(
                video.duration_seconds,
                video.published_at,
            )
            production_eligibility_inputs.append(
                {
                    "duration_seconds": video.duration_seconds,
                    "eligible": production_eligible,
                    "published_at": (
                        video.published_at.isoformat()
                        if hasattr(video.published_at, "isoformat")
                        else video.published_at
                    ),
                    "video_id": video_id,
                }
            )
            if not production_eligible:
                blockers.add("video_ineligible")
                sermon_results.append(
                    {
                        "eligible": False,
                        "profile_id": None,
                        "reason_codes": ["video_ineligible"],
                        "series_key": series_key,
                        "period_key": period_key,
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
            sermon_review = review_evidence.get(video_id)
            if cohort.get("require_whole_sermon_review_evidence"):
                if sermon_review is None:
                    reasons.append("whole_sermon_review_unavailable")
                elif not sermon_review["current"]:
                    reasons.append("whole_sermon_review_evidence_stale")
            review_evidence_fingerprints.append(
                {
                    "actual_sha256": (
                        sermon_review.get("actual_sha256")
                        if sermon_review is not None
                        else None
                    ),
                    "expected_sha256": (
                        sermon_review.get("expected_sha256")
                        if sermon_review is not None
                        else None
                    ),
                    "video_id": video_id,
                }
            )
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
                    "review_evidence": sermon_review,
                    "series_key": series_key,
                    "period_key": period_key,
                    "topic_review_packet_path": (
                        str(
                            Path(getattr(gate, "source_path")).with_name(
                                "topic-whole-sermon-review-v1.json"
                            )
                        )
                        if isinstance(getattr(gate, "source_path", None), str)
                        else None
                    ),
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
            "production_eligibility_inputs": sorted(
                production_eligibility_inputs,
                key=lambda item: int(item["video_id"]),
            ),
            "review_evidence_fingerprints": sorted(
                review_evidence_fingerprints,
                key=lambda item: int(item["video_id"]),
            ),
            "schema_version": TOPIC_STAGE4_READINESS_SCHEMA_VERSION,
        }
    )
    review_actions = build_topic_stage4_review_actions(pastor_results)
    return {
        "schema_version": TOPIC_STAGE4_READINESS_SCHEMA_VERSION,
        "policy_version": TOPIC_STAGE4_READINESS_POLICY_VERSION,
        "input_fingerprint": input_fingerprint,
        "cohort_id": cohort.get("cohort_id"),
        "cohort_sha256": cohort.get("cohort_sha256"),
        "model": cohort.get("model"),
        "ready": not cohort_blockers,
        "blockers": sorted(cohort_blockers),
        "pastors": pastor_results,
        "review_actions": review_actions,
        "interpretation": (
            "Readiness only. A ready result permits a stability evaluation; it "
            "does not establish topic stability or theological stance."
        ),
    }


def _number(value: object, *, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Topic stability {label} is unavailable or malformed")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"Topic stability {label} must be between 0 and 1")
    return result


def _maximum_pairwise_delta(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return round(max(values) - min(values), 6)


def _measurement_diagnostics(
    sermons: list[Mapping[str, Any]],
    *,
    measurement_key: str,
) -> dict[str, Any]:
    values = [
        _number(
            sermon[measurement_key],
            label=f"{measurement_key} for video {sermon['video_id']}",
        )
        for sermon in sermons
    ]
    center = statistics.fmean(values)
    leave_one_out = [
        statistics.fmean(values[:index] + values[index + 1 :])
        for index in range(len(values))
        if len(values) > 1
    ]

    def grouped(key: str) -> list[dict[str, Any]]:
        keys = sorted({str(sermon[key]) for sermon in sermons})
        return [
            {
                "key": group_key,
                "mean": round(
                    statistics.fmean(
                        _number(
                            sermon[measurement_key],
                            label=(
                                f"{measurement_key} for video "
                                f"{sermon['video_id']}"
                            ),
                        )
                        for sermon in sermons
                        if sermon[key] == group_key
                    ),
                    6,
                ),
                "sermon_count": sum(
                    sermon[key] == group_key for sermon in sermons
                ),
            }
            for group_key in keys
        ]

    series = grouped("series_key")
    periods = grouped("period_key")
    return {
        "equal_sermon_mean": round(center, 6),
        "sermon_values": [
            {
                "period_key": sermon["period_key"],
                "series_key": sermon["series_key"],
                "value": value,
                "video_id": sermon["video_id"],
                "youtube_video_id": sermon["youtube_video_id"],
            }
            for sermon, value in zip(sermons, values, strict=True)
        ],
        "minimum_sermon_value": round(min(values), 6),
        "maximum_sermon_value": round(max(values), 6),
        "sermon_range": round(max(values) - min(values), 6),
        "leave_one_sermon_max_absolute_delta": (
            round(max(abs(value - center) for value in leave_one_out), 6)
            if leave_one_out
            else None
        ),
        "series": series,
        "maximum_between_series_delta": _maximum_pairwise_delta(
            [float(item["mean"]) for item in series]
        ),
        "periods": periods,
        "maximum_between_period_delta": _maximum_pairwise_delta(
            [float(item["mean"]) for item in periods]
        ),
    }


def summarize_topic_stage4_pastor(
    pastor: Mapping[str, Any],
    sermons: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize already-materialized sermon values without policy thresholds."""
    if len(sermons) < 2:
        raise ValueError("Topic stability requires at least two sermons per pastor")
    topic_diagnostics = {}
    for topic in TOPICS:
        rows = []
        for sermon in sermons:
            raw_topics = sermon.get("topic_measurements")
            raw = raw_topics.get(topic) if isinstance(raw_topics, Mapping) else None
            if not isinstance(raw, Mapping):
                raise ValueError(
                    f"Topic stability measurement {topic} is unavailable for "
                    f"video {sermon.get('video_id')}"
                )
            rows.append(
                {
                    **sermon,
                    "developed_emphasis_probability": raw.get(
                        "developed_emphasis_probability"
                    ),
                    "normalized_expected_prominence": raw.get(
                        "normalized_expected_prominence"
                    ),
                }
            )
        topic_diagnostics[topic] = {
            "developed_emphasis_probability": _measurement_diagnostics(
                rows,
                measurement_key="developed_emphasis_probability",
            ),
            "normalized_expected_prominence_sensitivity": (
                _measurement_diagnostics(
                    rows,
                    measurement_key="normalized_expected_prominence",
                )
            ),
        }
    return {
        "display_name": pastor.get("display_name"),
        "pastor_id": pastor.get("pastor_id"),
        "profile_id": sermons[0]["profile_id"],
        "sermon_count": len(sermons),
        "series_count": len({sermon["series_key"] for sermon in sermons}),
        "period_count": len({sermon["period_key"] for sermon in sermons}),
        "sermons": [
            {
                key: sermon[key]
                for key in (
                    "period_key",
                    "series_key",
                    "sermon_analysis_input_fingerprint",
                    "sermon_analysis_run_id",
                    "video_id",
                    "youtube_video_id",
                )
            }
            for sermon in sermons
        ],
        "slug": pastor.get("slug"),
        "topics": topic_diagnostics,
    }


def evaluate_topic_stage4(
    database: Database,
    cohort: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate repeatability diagnostics using only current cached topic evidence."""
    readiness = assess_topic_stage4_readiness(database, cohort)
    if not readiness["ready"]:
        raise ValueError(
            "Topic Stage 4 is not ready: " + ", ".join(readiness["blockers"])
        )
    videos_by_id = {video.id: video for video in database.list_videos()}
    pastor_reports = []
    sermon_fingerprints = []
    for pastor, ready_pastor in zip(
        cohort["pastors"], readiness["pastors"], strict=True
    ):
        entries_by_id = {
            int(entry["video_id"]): entry for entry in pastor["sermons"]
        }
        sermons = []
        for ready_sermon in ready_pastor["sermons"]:
            video_id = int(ready_sermon["video_id"])
            video = videos_by_id[video_id]
            outcome = materialize_topic_sermon_analysis(database, video)
            values = load_topic_sermon_measurements(database, outcome.run.id)
            topic_measurements = values.get("topic_measurements")
            if not isinstance(topic_measurements, dict):
                raise ValueError(
                    f"Materialized topic measurements are malformed for video {video_id}"
                )
            entry = entries_by_id[video_id]
            sermon_fingerprints.append(outcome.run.input_fingerprint)
            sermons.append(
                {
                    "period_key": str(entry["period_key"]),
                    "profile_id": ready_sermon["profile_id"],
                    "series_key": str(entry["series_key"]),
                    "sermon_analysis_input_fingerprint": (
                        outcome.run.input_fingerprint
                    ),
                    "sermon_analysis_run_id": outcome.run.id,
                    "topic_measurements": topic_measurements,
                    "video_id": video_id,
                    "youtube_video_id": video.youtube_video_id,
                }
            )
        pastor_reports.append(summarize_topic_stage4_pastor(pastor, sermons))

    input_fingerprint = _canonical_hash(
        {
            "evaluation_policy_version": TOPIC_STAGE4_EVALUATION_POLICY_VERSION,
            "readiness_input_fingerprint": readiness["input_fingerprint"],
            "schema_version": TOPIC_STAGE4_EVALUATION_SCHEMA_VERSION,
            "sermon_analysis_input_fingerprints": sorted(sermon_fingerprints),
        }
    )
    return {
        "schema_version": TOPIC_STAGE4_EVALUATION_SCHEMA_VERSION,
        "policy_version": TOPIC_STAGE4_EVALUATION_POLICY_VERSION,
        "input_fingerprint": input_fingerprint,
        "cohort_id": cohort.get("cohort_id"),
        "cohort_sha256": cohort.get("cohort_sha256"),
        "question_pack_version": cohort.get("question_pack_version"),
        "readiness_input_fingerprint": readiness["input_fingerprint"],
        "status": "diagnostic_only_threshold_not_calibrated",
        "comparative_use_allowed": False,
        "pastors": pastor_reports,
        "interpretation": (
            "These are equal-sermon deletion and stratum diagnostics. They do not "
            "establish a pastor's theological stance, and no automatic stability "
            "threshold has been calibrated or applied."
        ),
    }


def render_topic_stage4_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# TypeSafe topic Stage 4 repeatability diagnostics",
        "",
        f"- Status: `{report['status']}`",
        f"- Comparative use allowed: `{str(report['comparative_use_allowed']).lower()}`",
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
                (
                    f"Profile `{pastor['profile_id']}`; sermons "
                    f"{pastor['sermon_count']}; series {pastor['series_count']}; "
                    f"periods {pastor['period_count']}."
                ),
                "",
                "| Topic | Developed mean | LOO max Δ | Series max Δ | Period max Δ | Expected sensitivity mean |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for topic in TOPICS:
            metrics = pastor["topics"][topic]
            primary = metrics["developed_emphasis_probability"]
            sensitivity = metrics[
                "normalized_expected_prominence_sensitivity"
            ]

            def formatted(value: object) -> str:
                return "—" if value is None else f"{float(value):.3f}"

            lines.append(
                f"| `{topic}` | {formatted(primary['equal_sermon_mean'])} | "
                f"{formatted(primary['leave_one_sermon_max_absolute_delta'])} | "
                f"{formatted(primary['maximum_between_series_delta'])} | "
                f"{formatted(primary['maximum_between_period_delta'])} | "
                f"{formatted(sensitivity['equal_sermon_mean'])} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_topic_stage4_report(
    path: Path,
    report: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    """Write or exactly reuse a fingerprinted JSON/Markdown diagnostic report."""
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
        render_topic_stage4_markdown(report),
        encoding="utf-8",
    )
    return json_path, markdown_path, False
