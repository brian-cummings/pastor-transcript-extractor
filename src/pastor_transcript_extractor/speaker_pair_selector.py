from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping, Sequence


SELECTOR_VERSION = "speaker_pair_selector_v1"


class SelectionStratum(StrEnum):
    SHARED_ATTRIBUTION = "shared_attribution"
    CONTRADICTING_ATTRIBUTION = "contradicting_attribution"
    UNATTRIBUTED = "unattributed"


STRATUM_ROTATION = (
    SelectionStratum.SHARED_ATTRIBUTION,
    SelectionStratum.CONTRADICTING_ATTRIBUTION,
    SelectionStratum.UNATTRIBUTED,
)


@dataclass(frozen=True, slots=True)
class PairCandidateObservation:
    input_fingerprint: str
    video_id: str
    recording_date: datetime | None
    explicit_attributions: frozenset[str] = frozenset()
    quality_signature: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class PairSelectionHistory:
    excluded_pairs: frozenset[frozenset[str]] = frozenset()
    excluded_source_pairs: frozenset[frozenset[str]] = frozenset()
    observation_use: Mapping[str, int] | None = None
    source_use: Mapping[str, int] | None = None
    disfavored_observations: Mapping[str, int] | None = None
    disfavored_sources: Mapping[str, int] | None = None
    automatic_selection_count: int = 0
    objective_condition_counts: Mapping[str, int] | None = None


@dataclass(frozen=True, slots=True)
class PairSelection:
    observation_a: PairCandidateObservation
    observation_b: PairCandidateObservation
    manifest: dict[str, object]


def selection_history_from_artifacts(
    *,
    drafts: Sequence[dict[str, Any]],
    reviews: Sequence[dict[str, Any]],
    fixtures: Sequence[dict[str, Any]],
) -> PairSelectionHistory:
    """Derive selector state from append-only review artifacts, without new lifecycle state."""
    drafts_by_pair = {
        str(draft.get("pair_id")): draft for draft in drafts if draft.get("pair_id")
    }
    excluded_pairs: set[frozenset[str]] = set()
    excluded_source_pairs: set[frozenset[str]] = set()
    observation_use: dict[str, int] = {}
    source_use: dict[str, int] = {}
    disfavored: dict[str, int] = {}
    disfavored_sources: dict[str, int] = {}
    objective_counts: dict[str, int] = {}
    automatic_pair_ids: set[str] = set()
    sources_by_pair: dict[str, list[str]] = {}

    for index, draft in enumerate(drafts):
        fingerprints = _draft_fingerprints(draft)
        if len(fingerprints) == 2:
            excluded_pairs.add(frozenset(fingerprints))
        sources = _draft_sources(draft)
        if len(sources) == 2:
            excluded_source_pairs.add(frozenset(sources))
            sources_by_pair[str(draft.get("pair_id") or f"draft-{index}")] = sources
        _record_automatic_pair(draft, automatic_pair_ids)

    for index, fixture in enumerate(fixtures):
        fingerprints = _fixture_fingerprints(fixture)
        if len(fingerprints) == 2:
            excluded_pairs.add(frozenset(fingerprints))
            for fingerprint in fingerprints:
                observation_use[fingerprint] = observation_use.get(fingerprint, 0) + 1
        sources = _fixture_sources(fixture)
        if len(sources) == 2:
            excluded_source_pairs.add(frozenset(sources))
            sources_by_pair.setdefault(
                str(fixture.get("pair_id") or f"fixture-{index}"), sources
            )
        manifest = fixture.get("selection_manifest")
        if isinstance(manifest, dict):
            for reason in manifest.get("reason_codes", []):
                if isinstance(reason, str):
                    objective_counts[reason] = objective_counts.get(reason, 0) + 1
        _record_automatic_pair(fixture, automatic_pair_ids)

    for review in reviews:
        pair_id = str(review.get("pair_id", ""))
        draft = drafts_by_pair.get(pair_id)
        if draft is not None:
            fingerprints = _draft_fingerprints(draft)
            if len(fingerprints) == 2:
                excluded_pairs.add(frozenset(fingerprints))
            for label in ("A", "B"):
                qualification = review.get("qualification", {}).get(label)
                if qualification not in {"invalid_audio", "multiple_speakers"}:
                    continue
                source_key = draft.get("presentation", {}).get(label, {}).get("source_key")
                source = draft.get("observations", {}).get(source_key, {})
                fingerprint = source.get("input_fingerprint")
                if isinstance(fingerprint, str):
                    disfavored[fingerprint] = disfavored.get(fingerprint, 0) + 1
                video_id = source.get("youtube_video_id")
                if isinstance(video_id, str) and video_id:
                    disfavored_sources[video_id] = disfavored_sources.get(video_id, 0) + 1
        _record_automatic_pair(review, automatic_pair_ids)

    for sources in sources_by_pair.values():
        for source in sources:
            source_use[source] = source_use.get(source, 0) + 1

    return PairSelectionHistory(
        excluded_pairs=frozenset(excluded_pairs),
        excluded_source_pairs=frozenset(excluded_source_pairs),
        observation_use=observation_use,
        source_use=source_use,
        disfavored_observations=disfavored,
        disfavored_sources=disfavored_sources,
        automatic_selection_count=len(automatic_pair_ids),
        objective_condition_counts=objective_counts,
    )


def select_next_speaker_pair(
    observations: Sequence[PairCandidateObservation],
    history: PairSelectionHistory,
) -> PairSelection:
    """Select the next pair deterministically without assigning identity truth."""
    candidates = sorted(observations, key=lambda item: item.input_fingerprint)
    if len({item.input_fingerprint for item in candidates}) != len(candidates):
        raise ValueError("candidate observation fingerprints must be unique")

    pairs: list[tuple[PairCandidateObservation, PairCandidateObservation, SelectionStratum]] = []
    for index, observation_a in enumerate(candidates):
        for observation_b in candidates[index + 1 :]:
            pair_key = frozenset((observation_a.input_fingerprint, observation_b.input_fingerprint))
            source_pair_key = frozenset((observation_a.video_id, observation_b.video_id))
            if (
                pair_key in history.excluded_pairs
                or source_pair_key in history.excluded_source_pairs
            ):
                continue
            pairs.append((observation_a, observation_b, _pair_stratum(observation_a, observation_b)))
    if not pairs:
        raise ValueError("no unreviewed or undrafted eligible speaker pairs remain")

    start = history.automatic_selection_count % len(STRATUM_ROTATION)
    rotated = STRATUM_ROTATION[start:] + STRATUM_ROTATION[:start]
    chosen_stratum = next(
        stratum for stratum in rotated if any(pair[2] == stratum for pair in pairs)
    )
    stratum_pairs = [pair for pair in pairs if pair[2] == chosen_stratum]
    observation_use = history.observation_use or {}
    source_use = history.source_use or {}
    disfavored = history.disfavored_observations or {}
    disfavored_sources = history.disfavored_sources or {}
    condition_counts = history.objective_condition_counts or {}
    observation_a, observation_b, _ = min(
        stratum_pairs,
        key=lambda pair: _rank_pair(
            pair[0],
            pair[1],
            observation_use,
            source_use,
            disfavored,
            disfavored_sources,
            condition_counts,
        ),
    )

    prior_a = max(
        int(source_use.get(observation_a.video_id, 0)),
        int(observation_use.get(observation_a.input_fingerprint, 0)),
    )
    prior_b = max(
        int(source_use.get(observation_b.video_id, 0)),
        int(observation_use.get(observation_b.input_fingerprint, 0)),
    )
    reason_codes = _reason_codes(observation_a, observation_b, prior_a, prior_b)
    snapshot = [
        {
            "input_fingerprint": item.input_fingerprint,
            "video_id": item.video_id,
            "recording_date": item.recording_date.isoformat() if item.recording_date else None,
            "explicit_attributions": sorted(item.explicit_attributions),
            "quality_signature": item.quality_signature,
        }
        for item in candidates
    ]
    manifest: dict[str, object] = {
        "selector_version": SELECTOR_VERSION,
        "selection_origin": "automatic",
        "selection_stratum": chosen_stratum,
        "corpus_snapshot_fingerprint": _sha256_json(snapshot),
        "observation_prior_use": {"a": prior_a, "b": prior_b},
        "reason_codes": reason_codes,
    }
    return PairSelection(observation_a, observation_b, manifest)


def _pair_stratum(
    observation_a: PairCandidateObservation,
    observation_b: PairCandidateObservation,
) -> SelectionStratum:
    names_a = observation_a.explicit_attributions
    names_b = observation_b.explicit_attributions
    if not names_a or not names_b:
        return SelectionStratum.UNATTRIBUTED
    if names_a & names_b:
        return SelectionStratum.SHARED_ATTRIBUTION
    return SelectionStratum.CONTRADICTING_ATTRIBUTION


def _draft_fingerprints(payload: Mapping[str, Any]) -> list[str]:
    return [
        str(item["input_fingerprint"])
        for item in payload.get("observations", {}).values()
        if isinstance(item, dict) and item.get("input_fingerprint")
    ]


def _fixture_fingerprints(payload: Mapping[str, Any]) -> list[str]:
    return [
        str(payload.get("observations", {}).get(side, {}).get("input_fingerprint"))
        for side in ("a", "b")
        if payload.get("observations", {}).get(side, {}).get("input_fingerprint")
    ]


def _draft_sources(payload: Mapping[str, Any]) -> list[str]:
    return [
        str(item["youtube_video_id"])
        for item in payload.get("observations", {}).values()
        if isinstance(item, dict) and item.get("youtube_video_id")
    ]


def _fixture_sources(payload: Mapping[str, Any]) -> list[str]:
    return [
        str(payload.get("observations", {}).get(side, {}).get("youtube_video_id"))
        for side in ("a", "b")
        if payload.get("observations", {}).get(side, {}).get("youtube_video_id")
    ]


def _record_automatic_pair(payload: Mapping[str, Any], pair_ids: set[str]) -> None:
    manifest = payload.get("selection_manifest")
    pair_id = payload.get("pair_id")
    if isinstance(manifest, dict) and manifest.get("selection_origin") == "automatic" and pair_id:
        pair_ids.add(str(pair_id))


def _rank_pair(
    observation_a: PairCandidateObservation,
    observation_b: PairCandidateObservation,
    observation_use: Mapping[str, int],
    source_use: Mapping[str, int],
    disfavored: Mapping[str, int],
    disfavored_sources: Mapping[str, int],
    condition_counts: Mapping[str, int],
) -> tuple[object, ...]:
    source_use_a = int(source_use.get(observation_a.video_id, 0))
    source_use_b = int(source_use.get(observation_b.video_id, 0))
    observation_use_a = int(observation_use.get(observation_a.input_fingerprint, 0))
    observation_use_b = int(observation_use.get(observation_b.input_fingerprint, 0))
    dates_differ = (
        observation_a.recording_date is not None
        and observation_b.recording_date is not None
        and observation_a.recording_date.date() != observation_b.recording_date.date()
    )
    separation = _date_separation_days(observation_a, observation_b)
    quality_differs = (
        bool(observation_a.quality_signature)
        and bool(observation_b.quality_signature)
        and observation_a.quality_signature != observation_b.quality_signature
    )
    objective_count = condition_counts.get("varied_audio_quality", 0) if quality_differs else 10**9
    pair_hash = _sha256_json(
        sorted((observation_a.input_fingerprint, observation_b.input_fingerprint))
    )
    return (
        int(source_use_a > 0) + int(source_use_b > 0),
        source_use_a + source_use_b,
        max(source_use_a, source_use_b),
        int(observation_use_a > 0) + int(observation_use_b > 0),
        observation_use_a + observation_use_b,
        int(disfavored.get(observation_a.input_fingerprint, 0))
        + int(disfavored.get(observation_b.input_fingerprint, 0))
        + int(disfavored_sources.get(observation_a.video_id, 0))
        + int(disfavored_sources.get(observation_b.video_id, 0)),
        0 if dates_differ else 1,
        -separation,
        objective_count,
        pair_hash,
    )


def _date_separation_days(
    observation_a: PairCandidateObservation,
    observation_b: PairCandidateObservation,
) -> int:
    if observation_a.recording_date is None or observation_b.recording_date is None:
        return -1
    return abs((observation_a.recording_date.date() - observation_b.recording_date.date()).days)


def _reason_codes(
    observation_a: PairCandidateObservation,
    observation_b: PairCandidateObservation,
    prior_a: int,
    prior_b: int,
) -> list[str]:
    reasons: list[str] = []
    if prior_a == 0 and prior_b == 0:
        reasons.append("both_observations_unused")
    elif prior_a == 0 or prior_b == 0:
        reasons.append("one_observation_unused")
    else:
        reasons.append("least_used_observations")
    if _date_separation_days(observation_a, observation_b) > 0:
        reasons.append("different_date")
    if (
        observation_a.quality_signature
        and observation_b.quality_signature
        and observation_a.quality_signature != observation_b.quality_signature
    ):
        reasons.append("varied_audio_quality")
    return reasons


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
