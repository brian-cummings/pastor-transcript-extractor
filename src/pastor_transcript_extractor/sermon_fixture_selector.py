from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping, Sequence


SELECTOR_VERSION = "sermon_fixture_selector_v2"

SIGNAL_WEIGHTS = {
    "rule_llm_disagreement": 9,
    "likelihood_rescue_activation": 8,
    "rule_fallback_activation": 8,
    "retained_block_fragmentation": 7,
    "long_continuity_expansion": 6,
    "low_transcript_coverage": 6,
    "candidate_near_recording_boundary": 5,
    "multiple_similarly_ranked_candidates": 4,
    "extreme_caption_deduplication": 4,
}


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
    source_family_id: str | None = None
    recording_condition_group_id: str | None = None
    partition: str = "development"
    nomination_signals: tuple[str, ...] = ()
    signal_metrics: Mapping[str, object] | None = None

    @property
    def effective_source_family_id(self) -> str:
        return self.source_family_id or self.corpus_group

    @property
    def effective_condition_group_id(self) -> str:
        return self.recording_condition_group_id or self.effective_source_family_id

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
    source_family_use: Mapping[str, int] | None = None
    recording_condition_group_use: Mapping[str, int] | None = None
    nomination_signal_use: Mapping[str, int] | None = None


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
    source_family_id: str | None = None,
    recording_condition_group_id: str | None = None,
    partition: str = "development",
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
    nomination_signals, signal_metrics = _nomination_diagnostics(
        proposal=proposal,
        classification=classification,
        duration_seconds=duration_seconds,
    )
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
        source_family_id=source_family_id,
        recording_condition_group_id=recording_condition_group_id,
        partition=partition,
        nomination_signals=nomination_signals,
        signal_metrics=signal_metrics,
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
            "source_family_id": item.effective_source_family_id,
            "recording_condition_group_id": item.effective_condition_group_id,
            "partition": item.partition,
            "nomination_signals": list(item.nomination_signals),
            "signal_metrics": dict(item.signal_metrics or {}),
        }
        for item in eligible
    ]
    manifest: dict[str, object] = {
        "selector_version": SELECTOR_VERSION,
        "selection_origin": "automatic",
        "selection_stratum": chosen_stratum,
        "evaluation_partition": chosen.partition,
        "source_family_id": chosen.effective_source_family_id,
        "recording_condition_group_id": chosen.effective_condition_group_id,
        "nomination_signals": list(chosen.nomination_signals),
        "signal_metrics": dict(chosen.signal_metrics or {}),
        "corpus_snapshot_fingerprint": _sha256_json(snapshot),
        "reason_codes": _reason_codes(chosen, history),
    }
    return SermonFixtureSelection(chosen, manifest)


def _rank_candidate(
    candidate: SermonFixtureCandidate,
    history: SermonSelectionHistory,
) -> tuple[object, ...]:
    group_use = history.corpus_group_use or {}
    family_use = history.source_family_use or group_use
    condition_use = history.recording_condition_group_use or {}
    signal_use = history.nomination_signal_use or {}
    source_use = history.proposal_source_use or {}
    bucket_use = history.duration_bucket_use or {}
    date_separation = _minimum_date_separation(candidate.recording_date, history.prior_recording_dates)
    return (
        int(family_use.get(candidate.effective_source_family_id, 0)),
        int(condition_use.get(candidate.effective_condition_group_id, 0)),
        min(
            (int(signal_use.get(signal, 0)) for signal in candidate.nomination_signals),
            default=1_000_000,
        ),
        -sum(SIGNAL_WEIGHTS.get(signal, 0) for signal in candidate.nomination_signals),
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
    family_use = history.source_family_use or history.corpus_group_use or {}
    if int(family_use.get(candidate.effective_source_family_id, 0)) == 0:
        reasons.append("source_family_unrepresented")
    if int(
        (history.recording_condition_group_use or {}).get(
            candidate.effective_condition_group_id, 0
        )
    ) == 0:
        reasons.append("recording_condition_unrepresented")
    signal_use = history.nomination_signal_use or {}
    reasons.extend(
        f"signal_{signal}_unrepresented"
        for signal in candidate.nomination_signals
        if int(signal_use.get(signal, 0)) == 0
    )
    if int((history.proposal_source_use or {}).get(candidate.proposal_source, 0)) == 0:
        reasons.append("proposal_source_unrepresented")
    if candidate.recording_date is not None and history.prior_recording_dates:
        reasons.append("date_separation")
    return reasons


def _nomination_diagnostics(
    *,
    proposal: Mapping[str, Any],
    classification: Mapping[str, Any],
    duration_seconds: float | None,
) -> tuple[tuple[str, ...], dict[str, object]]:
    signals: set[str] = set()
    metrics: dict[str, object] = {}
    search = classification.get("search")
    search = search if isinstance(search, dict) else {}
    candidates = search.get("candidates")
    candidates = [item for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []
    selected_rank = search.get("selected_rank")
    selected = next(
        (item for item in candidates if item.get("rank") == selected_rank),
        candidates[0] if candidates else None,
    )

    agreement = _confidence_reason_value(classification, "rule_llm_agreement", "value")
    if agreement is not None:
        metrics["rule_llm_agreement"] = round(agreement, 6)
        if agreement < 0.5:
            signals.add("rule_llm_disagreement")

    discovery = search.get("discovery")
    discovery = discovery if isinstance(discovery, dict) else {}
    if discovery.get("rescue_triggered") is True:
        signals.add("likelihood_rescue_activation")
    if selected is not None and selected.get("source") == "rule_fallback":
        signals.add("rule_fallback_activation")

    if selected is not None:
        recovery = selected.get("boundary_recovery")
        recovery = recovery if isinstance(recovery, dict) else {}
        probe_count = sum(
            len(edge.get("probed_block_ids", []))
            for direction in ("start", "end")
            if isinstance((edge := recovery.get(direction)), dict)
            and isinstance(edge.get("probed_block_ids"), list)
        )
        metrics["continuity_probe_block_count"] = probe_count
        if probe_count >= 6:
            signals.add("long_continuity_expansion")
        discarded = recovery.get("discarded_component_block_ids")
        discarded_count = len(discarded) if isinstance(discarded, list) else 0
        metrics["discarded_retained_component_count"] = discarded_count
        if discarded_count:
            signals.add("retained_block_fragmentation")

    if len(candidates) >= 2:
        scores = [float(item["score"]) for item in candidates[:2] if isinstance(item.get("score"), (int, float))]
        if len(scores) == 2:
            margin = (scores[0] - scores[1]) / max(abs(scores[0]), 1.0)
            metrics["top_candidate_relative_margin"] = round(margin, 6)
            if margin <= 0.15:
                signals.add("multiple_similarly_ranked_candidates")

    segments = proposal.get("segments")
    segments = segments if isinstance(segments, list) else []
    timed_ranges = _timed_ranges(segments)
    recording_end = duration_seconds or max((end for _, end in timed_ranges), default=0.0)
    if selected is not None and recording_end > 0:
        start = selected.get("start_seconds")
        end = selected.get("end_seconds")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            boundary_distance = min(float(start), max(0.0, recording_end - float(end)))
            metrics["candidate_recording_edge_distance_seconds"] = round(boundary_distance, 3)
            if boundary_distance <= 60.0:
                signals.add("candidate_near_recording_boundary")
    if recording_end > 0:
        coverage = _covered_duration(timed_ranges, recording_end) / recording_end
        metrics["transcript_time_coverage"] = round(coverage, 6)
        if coverage < 0.5:
            signals.add("low_transcript_coverage")

    blocks = classification.get("blocks")
    ratios = [
        float(normalization["deduplication_ratio"])
        for block in blocks
        if isinstance(block, dict)
        and isinstance((normalization := block.get("normalization")), dict)
        and isinstance(normalization.get("deduplication_ratio"), (int, float))
    ] if isinstance(blocks, list) else []
    if ratios:
        mean_ratio = sum(ratios) / len(ratios)
        metrics["mean_caption_deduplication_ratio"] = round(mean_ratio, 6)
        if mean_ratio >= 0.75:
            signals.add("extreme_caption_deduplication")
    return tuple(sorted(signals)), metrics


def _confidence_reason_value(
    classification: Mapping[str, Any], code: str, field: str
) -> float | None:
    reasons = classification.get("confidence_reasons")
    if not isinstance(reasons, list):
        return None
    for reason in reasons:
        if (
            isinstance(reason, dict)
            and reason.get("code") == code
            and isinstance(reason.get(field), (int, float))
        ):
            return float(reason[field])
    return None


def _timed_ranges(segments: Sequence[object]) -> list[tuple[float, float]]:
    ranges = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = segment.get("start_seconds")
        end = segment.get("end_seconds")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
            ranges.append((max(0.0, float(start)), float(end)))
    return sorted(ranges)


def _covered_duration(ranges: Sequence[tuple[float, float]], recording_end: float) -> float:
    covered = 0.0
    current_start: float | None = None
    current_end = 0.0
    for start, end in ranges:
        start = min(start, recording_end)
        end = min(end, recording_end)
        if end <= start:
            continue
        if current_start is None:
            current_start, current_end = start, end
        elif start <= current_end:
            current_end = max(current_end, end)
        else:
            covered += current_end - current_start
            current_start, current_end = start, end
    if current_start is not None:
        covered += current_end - current_start
    return covered


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
