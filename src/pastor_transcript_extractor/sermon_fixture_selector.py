from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping, Sequence


SELECTOR_VERSION = "sermon_fixture_selector_v1"


class SermonSelectionStratum(StrEnum):
    BOUNDARY_RISK = "boundary_risk"
    NO_CANDIDATE = "no_candidate"
    STANDARD_CANDIDATE = "standard_candidate"


STRATUM_ROTATION = (
    SermonSelectionStratum.BOUNDARY_RISK,
    SermonSelectionStratum.NO_CANDIDATE,
    SermonSelectionStratum.STANDARD_CANDIDATE,
)


@dataclass(frozen=True, slots=True)
class SermonFixtureCandidate:
    video_id: str
    corpus_group: str
    recording_date: datetime | None
    duration_seconds: float | None
    proposal_source: str
    confidence_tier: str | None
    has_candidate: bool
    suspicious_boundary: bool
    has_warnings: bool

    @property
    def stratum(self) -> SermonSelectionStratum:
        if not self.has_candidate:
            return SermonSelectionStratum.NO_CANDIDATE
        if self.suspicious_boundary or self.has_warnings or self.confidence_tier in {"low", "medium"}:
            return SermonSelectionStratum.BOUNDARY_RISK
        return SermonSelectionStratum.STANDARD_CANDIDATE


@dataclass(frozen=True, slots=True)
class SermonSelectionHistory:
    excluded_video_ids: frozenset[str] = frozenset()
    automatic_selection_count: int = 0
    corpus_group_use: Mapping[str, int] | None = None
    proposal_source_use: Mapping[str, int] | None = None
    duration_bucket_use: Mapping[str, int] | None = None
    prior_recording_dates: tuple[datetime, ...] = ()


@dataclass(frozen=True, slots=True)
class SermonFixtureSelection:
    candidate: SermonFixtureCandidate
    manifest: dict[str, object]


def sermon_candidate_from_proposal(
    *,
    video_id: str,
    corpus_group: str,
    recording_date: datetime | None,
    duration_seconds: float | None,
    proposal: Mapping[str, Any],
) -> SermonFixtureCandidate:
    classification = proposal.get("classification")
    classification = classification if isinstance(classification, dict) else {}
    retained = classification.get("retained_segment_indexes")
    segments = proposal.get("segments")
    segments = segments if isinstance(segments, list) else []
    has_retained = isinstance(retained, list) and any(
        isinstance(index, int)
        and 0 <= index < len(segments)
        and isinstance(segments[index], dict)
        and isinstance(segments[index].get("start_seconds"), (int, float))
        and isinstance(segments[index].get("end_seconds"), (int, float))
        for index in retained
    )
    window = proposal.get("sermon_window")
    window = window if isinstance(window, dict) else {}
    has_window = (
        isinstance(window.get("start_seconds"), (int, float))
        and isinstance(window.get("end_seconds"), (int, float))
        and float(window["end_seconds"]) > float(window["start_seconds"])
    )
    has_candidate = has_retained or has_window
    proposal_source = (
        str(classification.get("method", "classification"))
        if has_retained
        else str(window.get("method", "rule_window"))
        if has_window
        else "no_candidate_full_video"
    )
    warnings = classification.get("warnings")
    uncertain = classification.get("uncertain_block_ids")
    return SermonFixtureCandidate(
        video_id=video_id,
        corpus_group=corpus_group,
        recording_date=recording_date,
        duration_seconds=duration_seconds,
        proposal_source=proposal_source,
        confidence_tier=(
            str(classification["confidence_tier"])
            if classification.get("confidence_tier") is not None
            else None
        ),
        has_candidate=has_candidate,
        suspicious_boundary=window.get("suspicious_boundary") is True,
        has_warnings=(isinstance(warnings, list) and bool(warnings))
        or (isinstance(uncertain, list) and bool(uncertain)),
    )


def select_next_sermon_fixture(
    candidates: Sequence[SermonFixtureCandidate],
    history: SermonSelectionHistory,
) -> SermonFixtureSelection:
    """Nominate one review item deterministically without assigning sermon truth."""
    eligible = sorted(
        (item for item in candidates if item.video_id not in history.excluded_video_ids),
        key=lambda item: item.video_id,
    )
    if len({item.video_id for item in eligible}) != len(eligible):
        raise ValueError("candidate video IDs must be unique")
    if not eligible:
        raise ValueError("no undrafted, unreviewed sermon fixture candidates remain")

    start = history.automatic_selection_count % len(STRATUM_ROTATION)
    rotation = STRATUM_ROTATION[start:] + STRATUM_ROTATION[:start]
    chosen_stratum = next(stratum for stratum in rotation if any(item.stratum == stratum for item in eligible))
    stratum_candidates = [item for item in eligible if item.stratum == chosen_stratum]
    chosen = min(stratum_candidates, key=lambda item: _rank_candidate(item, history))

    snapshot = [
        {
            "video_id": item.video_id,
            "corpus_group": item.corpus_group,
            "recording_date": item.recording_date.isoformat() if item.recording_date else None,
            "duration_seconds": item.duration_seconds,
            "proposal_source": item.proposal_source,
            "confidence_tier": item.confidence_tier,
            "has_candidate": item.has_candidate,
            "suspicious_boundary": item.suspicious_boundary,
            "has_warnings": item.has_warnings,
        }
        for item in eligible
    ]
    manifest: dict[str, object] = {
        "selector_version": SELECTOR_VERSION,
        "selection_origin": "automatic",
        "selection_stratum": chosen_stratum,
        "corpus_snapshot_fingerprint": _sha256_json(snapshot),
        "reason_codes": _reason_codes(chosen, history),
    }
    return SermonFixtureSelection(chosen, manifest)


def _rank_candidate(
    candidate: SermonFixtureCandidate,
    history: SermonSelectionHistory,
) -> tuple[object, ...]:
    group_use = history.corpus_group_use or {}
    source_use = history.proposal_source_use or {}
    bucket_use = history.duration_bucket_use or {}
    date_separation = _minimum_date_separation(candidate.recording_date, history.prior_recording_dates)
    return (
        int(group_use.get(candidate.corpus_group, 0)),
        int(source_use.get(candidate.proposal_source, 0)),
        int(bucket_use.get(sermon_duration_bucket(candidate.duration_seconds), 0)),
        -date_separation,
        _sha256_json(candidate.video_id),
    )


def _reason_codes(
    candidate: SermonFixtureCandidate,
    history: SermonSelectionHistory,
) -> list[str]:
    reasons = [f"stratum_{candidate.stratum}"]
    if int((history.corpus_group_use or {}).get(candidate.corpus_group, 0)) == 0:
        reasons.append("corpus_group_unrepresented")
    if int((history.proposal_source_use or {}).get(candidate.proposal_source, 0)) == 0:
        reasons.append("proposal_source_unrepresented")
    if candidate.recording_date is not None and history.prior_recording_dates:
        reasons.append("date_separation")
    return reasons


def sermon_duration_bucket(duration_seconds: float | None) -> str:
    if duration_seconds is None:
        return "unknown"
    if duration_seconds < 20 * 60:
        return "short"
    if duration_seconds < 75 * 60:
        return "standard"
    return "long"


def _minimum_date_separation(recording_date: datetime | None, prior_dates: Sequence[datetime]) -> int:
    if recording_date is None or not prior_dates:
        return -1
    return min(abs((recording_date.date() - item.date()).days) for item in prior_dates)


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
