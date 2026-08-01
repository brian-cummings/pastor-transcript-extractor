from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping, Sequence

from pastor_transcript_extractor.models import SpeakerObservation
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    AudioSpanCache,
    CachedSpan,
    DecisionPolicy,
    EmbeddingBackend,
    EmbeddingCache,
    PairOutcome,
    SpanSpec,
    observation_consistency_metrics,
    select_diagnostic_spans,
)
from pastor_transcript_extractor.speaker_shadow_association import ShadowPolicySpec


SHADOW_PROFILE_DISCOVERY_VERSION = "speaker_profile_shadow_discovery_v2"
TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION = (
    "transcript_grounded_sermon_spans_v1"
)


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    observation: SpeakerObservation
    audio_path: Path
    source_id: int
    normalized_names: tuple[str, ...] = ()
    consistency_score: float | None = None
    span_specs: tuple[SpanSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoverySignature:
    candidate: DiscoveryCandidate
    centroid: tuple[float, ...]
    span_evidence: tuple[Mapping[str, Any], ...]
    consistency_metrics: Mapping[str, Any]
    signature_sha256: str


@dataclass(frozen=True, slots=True)
class NominatedPair:
    left: DiscoverySignature
    right: DiscoverySignature
    centroid_similarity: float

    @property
    def observation_ids(self) -> tuple[int, int]:
        return tuple(
            sorted(
                (
                    self.left.candidate.observation.id,
                    self.right.candidate.observation.id,
                )
            )
        )


PairComparer = Callable[
    [SpeakerObservation, SpeakerObservation, Path, Path],
    Mapping[str, Any],
]


def build_discovery_signature(
    candidate: DiscoveryCandidate,
    *,
    span_cache: AudioSpanCache,
    embedding_cache: EmbeddingCache,
    backend: EmbeddingBackend,
    policy: DecisionPolicy,
    span_count: int = 5,
    span_duration_seconds: float = 12.0,
    min_rms_dbfs: float = -52.0,
) -> DiscoverySignature:
    specs = (
        candidate.span_specs
        or select_diagnostic_spans(
            candidate.observation,
            count=span_count,
            duration_seconds=span_duration_seconds,
        )
    )
    if not specs:
        raise ValueError("observation_too_short")
    prepared = tuple(
        span_cache.prepare(
            observation=candidate.observation,
            source_audio_path=candidate.audio_path,
            span=span,
        )
        for span in specs
    )
    valid = tuple(span for span in prepared if span.rms_dbfs >= min_rms_dbfs)
    if len(valid) < policy.min_valid_spans:
        raise ValueError("too_few_valid_spans")
    embeddings = tuple(
        embedding_cache.get_or_compute(span, backend)[0] for span in valid
    )
    centroid = _normalized_centroid(embeddings)
    consistency = observation_consistency_metrics(embeddings)
    evidence = tuple(_span_evidence(span) for span in valid)
    signature_payload = {
        "discovery_version": SHADOW_PROFILE_DISCOVERY_VERSION,
        "observation_fingerprint": candidate.observation.input_fingerprint,
        "model_fingerprint": backend.spec.fingerprint,
        "span_wav_sha256s": [span.wav_sha256 for span in valid],
        "centroid_sha256": _sha256_json(centroid),
    }
    return DiscoverySignature(
        candidate=candidate,
        centroid=centroid,
        span_evidence=evidence,
        consistency_metrics=consistency,
        signature_sha256=_sha256_json(signature_payload),
    )


def select_transcript_grounded_spans(
    payload: Mapping[str, Any],
    observation: SpeakerObservation,
    *,
    count: int = 5,
    duration_seconds: float = 12.0,
    minimum_words: int = 8,
    minimum_unique_words: int = 4,
) -> tuple[SpanSpec, ...]:
    if count < 2 or duration_seconds <= 0:
        raise ValueError("at least two positive-duration spans are required")
    if minimum_words < 1 or minimum_unique_words < 1:
        raise ValueError("speech grounding thresholds must be positive")
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, Sequence) or isinstance(
        raw_segments, (str, bytes)
    ):
        return ()
    segments: list[tuple[float, float, str]] = []
    for raw in raw_segments:
        if not isinstance(raw, Mapping) or raw.get("label") != "sermon":
            continue
        start = _finite_number(raw.get("start_seconds"))
        end = _finite_number(raw.get("end_seconds"))
        text = raw.get("text")
        if (
            start is None
            or end is None
            or end <= start
            or not isinstance(text, str)
            or end < observation.start_seconds
            or start > observation.end_seconds
        ):
            continue
        segments.append((start, end, text))
    if not segments:
        return ()

    latest_start = observation.end_seconds - duration_seconds
    if latest_start <= observation.start_seconds:
        return ()
    candidates: dict[float, tuple[int, int]] = {}
    for start, end, _ in segments:
        midpoint = (start + end) / 2.0
        span_start = round(
            min(
                max(
                    midpoint - (duration_seconds / 2.0),
                    observation.start_seconds,
                ),
                latest_start,
            ),
            3,
        )
        span_end = span_start + duration_seconds
        words = [
            word.casefold()
            for segment_start, segment_end, text in segments
            if segment_start <= span_end and segment_end >= span_start
            for word in re.findall(r"\b[^\W\d_]+\b", text, flags=re.UNICODE)
        ]
        unique_words = len(set(words))
        if len(words) < minimum_words or unique_words < minimum_unique_words:
            continue
        score = (len(words), unique_words)
        if score > candidates.get(span_start, (0, 0)):
            candidates[span_start] = score
    if len(candidates) < count:
        return ()

    available = sorted(candidates)
    selected: list[float] = []
    for index in range(count):
        target = available[round(index * (len(available) - 1) / (count - 1))]
        ranked = sorted(
            (
                start
                for start in available
                if start not in selected
                and all(
                    abs(start - existing) >= duration_seconds
                    for existing in selected
                )
            ),
            key=lambda start: (
                abs(start - target),
                -candidates[start][0],
                -candidates[start][1],
                start,
            ),
        )
        if not ranked:
            return ()
        selected.append(ranked[0])
    return tuple(
        SpanSpec(start, round(start + duration_seconds, 3))
        for start in sorted(selected)
    )


def nominate_discovery_pairs(
    signatures: Sequence[DiscoverySignature],
    *,
    nearest_neighbors: int = 8,
    maximum_pairs: int | None = None,
) -> tuple[NominatedPair, ...]:
    if nearest_neighbors < 2:
        raise ValueError("profile discovery requires at least two nearest neighbors")
    if maximum_pairs is not None and maximum_pairs < 1:
        raise ValueError("maximum_pairs must be positive")
    ordered = sorted(
        signatures,
        key=lambda item: item.candidate.observation.input_fingerprint,
    )
    selected: dict[tuple[int, int], NominatedPair] = {}
    for left in ordered:
        ranked: list[tuple[float, str, DiscoverySignature]] = []
        for right in ordered:
            if left.candidate.observation.id == right.candidate.observation.id:
                continue
            similarity = _cosine(left.centroid, right.centroid)
            ranked.append(
                (
                    similarity,
                    right.candidate.observation.input_fingerprint,
                    right,
                )
            )
        ranked.sort(key=lambda item: (-item[0], item[1]))
        for similarity, _, right in ranked[:nearest_neighbors]:
            nomination = NominatedPair(left, right, similarity)
            key = nomination.observation_ids
            existing = selected.get(key)
            if (
                existing is None
                or nomination.centroid_similarity > existing.centroid_similarity
            ):
                selected[key] = nomination
    nominations = sorted(
        selected.values(),
        key=lambda item: (
            -item.centroid_similarity,
            item.left.candidate.observation.input_fingerprint,
            item.right.candidate.observation.input_fingerprint,
        ),
    )
    if maximum_pairs is not None:
        nominations = nominations[:maximum_pairs]
    return tuple(nominations)


def evaluate_shadow_profile_discovery(
    *,
    signatures: Sequence[DiscoverySignature],
    nominations: Sequence[NominatedPair],
    compare: PairComparer,
    policy_spec: ShadowPolicySpec,
    model_fingerprint: str,
    minimum_component_members: int = 3,
    reviewed_same_pairs: Sequence[tuple[int, int]] = (),
    reviewed_difference_pairs: Sequence[tuple[int, int]] = (),
    consistency_report_sha256: str | None = None,
    minimum_consistency_score: float | None = None,
    signature_failures: Sequence[Mapping[str, Any]] = (),
    nearest_neighbors: int | None = None,
    maximum_pairs: int | None = None,
) -> dict[str, Any]:
    if minimum_component_members < 3:
        raise ValueError("provisional profiles require at least three members")
    reviewed_differences = {
        tuple(sorted(pair)) for pair in reviewed_difference_pairs
    }
    reviewed_same = {tuple(sorted(pair)) for pair in reviewed_same_pairs}
    conflicting_reviewed_pairs = reviewed_same & reviewed_differences
    if conflicting_reviewed_pairs:
        raise ValueError(
            "reviewed same/different constraints conflict for observation pair(s)"
        )
    pair_results: list[dict[str, Any]] = []
    evaluated_pairs: set[tuple[int, int]] = set()
    for nomination in nominations:
        left = nomination.left.candidate
        right = nomination.right.candidate
        pair = nomination.observation_ids
        evaluated_pairs.add(pair)
        if pair in reviewed_differences:
            result: Mapping[str, Any] = {
                "outcome": PairOutcome.DIFFERENT_SPEAKER,
                "reason": "reviewed_different_speaker_constraint",
                "reviewed_constraint": True,
            }
        elif pair in reviewed_same:
            result = {
                "outcome": PairOutcome.SAME_SPEAKER,
                "reason": "reviewed_same_speaker_constraint",
                "reviewed_constraint": True,
            }
        else:
            result = compare(
                left.observation,
                right.observation,
                left.audio_path,
                right.audio_path,
            )
        pair_results.append(
            {
                "observation_ids": list(pair),
                "observation_fingerprints": sorted(
                    (
                        left.observation.input_fingerprint,
                        right.observation.input_fingerprint,
                    )
                ),
                "centroid_similarity": nomination.centroid_similarity,
                **dict(result),
            }
        )
    signatures_by_observation_id = {
        signature.candidate.observation.id: signature
        for signature in signatures
    }
    for pair in sorted((reviewed_same | reviewed_differences) - evaluated_pairs):
        if not all(
            observation_id in signatures_by_observation_id
            for observation_id in pair
        ):
            continue
        left = signatures_by_observation_id[pair[0]]
        right = signatures_by_observation_id[pair[1]]
        outcome = (
            PairOutcome.SAME_SPEAKER
            if pair in reviewed_same
            else PairOutcome.DIFFERENT_SPEAKER
        )
        pair_results.append(
            {
                "observation_ids": list(pair),
                "observation_fingerprints": sorted(
                    (
                        left.candidate.observation.input_fingerprint,
                        right.candidate.observation.input_fingerprint,
                    )
                ),
                "centroid_similarity": _cosine(
                    left.centroid,
                    right.centroid,
                ),
                "outcome": outcome,
                "reason": f"reviewed_{outcome}_constraint",
                "reviewed_constraint": True,
            }
        )

    components = _build_component_proposals(
        signatures,
        pair_results,
        minimum_component_members=minimum_component_members,
        reviewed_differences=reviewed_differences,
    )
    signature_payloads = [
        _signature_payload(signature) for signature in signatures
    ]
    outcome_counts = _counts(
        str(result.get("outcome", "invalid")) for result in pair_results
    )
    component_counts = _counts(
        str(component["outcome"]) for component in components
    )
    report = {
        "schema_version": 1,
        "discovery_version": SHADOW_PROFILE_DISCOVERY_VERSION,
        "artifact_kind": "speaker_profile_shadow_discovery",
        "shadow_mode": True,
        "registry_mutation_allowed": False,
        "automatic_profile_creation_allowed": False,
        "model_fingerprint": model_fingerprint,
        "policy": {
            "version": policy_spec.policy.version,
            "review_status": policy_spec.review_status,
            "artifact_sha256": policy_spec.artifact_sha256,
            "automatic_use_allowed": policy_spec.automatic_use_allowed,
        },
        "minimum_component_members": minimum_component_members,
        "span_selection": {
            "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
            "required_label": "sermon",
            "span_count": 5,
            "duration_seconds": 12.0,
            "minimum_words": 8,
            "minimum_unique_words": 4,
        },
        "retrieval": {
            "method": "observation_centroid_cosine_nearest_neighbors",
            "nearest_neighbors": nearest_neighbors,
            "maximum_pairs": maximum_pairs,
            "identity_evidence": False,
        },
        "consistency_gate": {
            "report_sha256": consistency_report_sha256,
            "minimum_score": minimum_consistency_score,
        },
        "reviewed_constraints": {
            "same_speaker_observation_pairs": [
                list(pair) for pair in sorted(reviewed_same)
            ],
            "different_speaker_observation_pairs": [
                list(pair) for pair in sorted(reviewed_differences)
            ],
        },
        "counts": {
            "eligible_signatures": len(signature_payloads),
            "signature_failures": len(signature_failures),
            "nominated_pairs": len(pair_results),
            "provisional_profile_candidates": component_counts.get(
                "provisional_profile_candidate", 0
            ),
            "blocked_components": component_counts.get("blocked", 0),
        },
        "pair_outcome_counts": outcome_counts,
        "component_outcome_counts": component_counts,
        "observation_signatures": signature_payloads,
        "signature_failures": [dict(item) for item in signature_failures],
        "pair_results": pair_results,
        "components": components,
    }
    report["input_fingerprint"] = _sha256_json(
        {
            "discovery_version": SHADOW_PROFILE_DISCOVERY_VERSION,
            "model_fingerprint": model_fingerprint,
            "policy": report["policy"],
            "minimum_component_members": minimum_component_members,
            "span_selection": report["span_selection"],
            "retrieval": report["retrieval"],
            "consistency_gate": report["consistency_gate"],
            "reviewed_constraints": report["reviewed_constraints"],
            "signatures": [
                {
                    "observation_fingerprint": item[
                        "observation_fingerprint"
                    ],
                    "signature_sha256": item["signature_sha256"],
                }
                for item in signature_payloads
            ],
            "signature_failures": [dict(item) for item in signature_failures],
            "nominations": [
                result["observation_fingerprints"] for result in pair_results
            ],
        }
    )
    report["result_sha256"] = _sha256_json(report)
    return report


def write_shadow_profile_discovery(
    output_root: Path,
    report: Mapping[str, Any],
) -> Path:
    content = dict(report)
    result_sha256 = content.pop("result_sha256", None)
    if (
        not isinstance(result_sha256, str)
        or result_sha256 != _sha256_json(content)
    ):
        raise ValueError("profile discovery result checksum mismatch")
    input_fingerprint = str(report.get("input_fingerprint", ""))
    if not input_fingerprint:
        raise ValueError("profile discovery report requires an input fingerprint")
    destination = (
        output_root.expanduser().resolve()
        / input_fingerprint[:16]
        / f"{input_fingerprint}.json"
    )
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if destination.exists():
        if destination.read_text(encoding="utf-8") != encoded:
            raise ValueError(
                f"profile discovery fingerprint collision: {destination}"
            )
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(encoded, encoding="utf-8")
    return destination


def load_verified_shadow_profile_discovery(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("profile discovery artifact root must be an object")
    expected = payload.get("result_sha256")
    content = dict(payload)
    content.pop("result_sha256", None)
    if not isinstance(expected, str) or expected != _sha256_json(content):
        raise ValueError("profile discovery result checksum mismatch")
    if (
        payload.get("artifact_kind") != "speaker_profile_shadow_discovery"
        or payload.get("discovery_version")
        != SHADOW_PROFILE_DISCOVERY_VERSION
        or payload.get("shadow_mode") is not True
        or payload.get("registry_mutation_allowed") is not False
        or payload.get("automatic_profile_creation_allowed") is not False
        or not isinstance(payload.get("components"), list)
    ):
        raise ValueError("unsupported or unsafe profile discovery artifact")
    return payload


def _build_component_proposals(
    signatures: Sequence[DiscoverySignature],
    pair_results: Sequence[Mapping[str, Any]],
    *,
    minimum_component_members: int,
    reviewed_differences: set[tuple[int, int]],
) -> list[dict[str, Any]]:
    signatures_by_id = {
        signature.candidate.observation.id: signature
        for signature in signatures
    }
    results_by_pair = {
        tuple(sorted(int(value) for value in result["observation_ids"])): result
        for result in pair_results
    }
    adjacency: dict[int, set[int]] = {
        observation_id: set() for observation_id in signatures_by_id
    }
    for pair, result in results_by_pair.items():
        if str(result.get("outcome")) != PairOutcome.SAME_SPEAKER:
            continue
        left, right = pair
        adjacency[left].add(right)
        adjacency[right].add(left)

    cliques = [
        clique
        for clique in _maximal_cliques(adjacency)
        if len(clique) >= minimum_component_members
    ]
    clique_memberships: dict[int, int] = {}
    for clique in cliques:
        for observation_id in clique:
            clique_memberships[observation_id] = (
                clique_memberships.get(observation_id, 0) + 1
            )
    components: list[dict[str, Any]] = []
    covered_ids: set[int] = set()
    for member_ids in cliques:
        covered_ids.update(member_ids)
        components.append(
            _component_payload(
                member_ids,
                signatures_by_id=signatures_by_id,
                results_by_pair=results_by_pair,
                reviewed_differences=reviewed_differences,
                minimum_component_members=minimum_component_members,
                overlapping_member_ids={
                    observation_id
                    for observation_id in member_ids
                    if clique_memberships.get(observation_id, 0) > 1
                },
            )
        )

    unseen = {
        key
        for key, neighbors in adjacency.items()
        if neighbors and key not in covered_ids
    }
    while unseen:
        seed = min(unseen)
        pending = [seed]
        member_ids: set[int] = set()
        while pending:
            current = pending.pop()
            if current in member_ids:
                continue
            member_ids.add(current)
            pending.extend(
                (adjacency[current] - covered_ids) - member_ids
            )
        unseen.difference_update(member_ids)
        components.append(
            _component_payload(
                member_ids,
                signatures_by_id=signatures_by_id,
                results_by_pair=results_by_pair,
                reviewed_differences=reviewed_differences,
                minimum_component_members=minimum_component_members,
                overlapping_member_ids=set(),
            )
        )
    components.sort(key=lambda item: str(item["component_id"]))
    return components


def _component_payload(
    member_ids: set[int],
    *,
    signatures_by_id: Mapping[int, DiscoverySignature],
    results_by_pair: Mapping[tuple[int, int], Mapping[str, Any]],
    reviewed_differences: set[tuple[int, int]],
    minimum_component_members: int,
    overlapping_member_ids: set[int],
) -> dict[str, Any]:
    members = [signatures_by_id[item] for item in sorted(member_ids)]
    required_pairs = {
        tuple(sorted(pair))
        for pair in itertools.combinations(sorted(member_ids), 2)
    }
    same_pairs = {
        pair
        for pair in required_pairs
        if str(results_by_pair.get(pair, {}).get("outcome"))
        == PairOutcome.SAME_SPEAKER
    }
    different_pairs = {
        pair
        for pair in required_pairs
        if (
            str(results_by_pair.get(pair, {}).get("outcome"))
            == PairOutcome.DIFFERENT_SPEAKER
            or pair in reviewed_differences
        )
    }
    unresolved_pairs = required_pairs - same_pairs - different_pairs
    normalized_names = {
        name
        for member in members
        for name in member.candidate.normalized_names
        if name
    }
    video_ids = {
        member.candidate.observation.video_id for member in members
    }
    blockers: list[str] = []
    if len(members) < minimum_component_members:
        blockers.append("fewer_than_minimum_members")
    if len(video_ids) < minimum_component_members:
        blockers.append("fewer_than_minimum_distinct_recordings")
    if different_pairs:
        blockers.append("different_speaker_constraint_inside_component")
    if unresolved_pairs:
        blockers.append("component_not_complete_link")
    if overlapping_member_ids:
        blockers.append("overlapping_complete_link_components")
    if len(normalized_names) > 1:
        blockers.append("conflicting_explicit_attribution")
    outcome = "blocked" if blockers else "provisional_profile_candidate"
    component_fingerprints = sorted(
        member.candidate.observation.input_fingerprint
        for member in members
    )
    return {
        "component_id": _sha256_json(component_fingerprints),
        "outcome": outcome,
        "reason": (
            "complete_link_same_speaker_component"
            if not blockers
            else blockers[0]
        ),
        "blockers": blockers,
        "overlapping_member_ids": sorted(overlapping_member_ids),
        "member_count": len(members),
        "recording_count": len(video_ids),
        "source_count": len(
            {member.candidate.source_id for member in members}
        ),
        "normalized_names": sorted(normalized_names),
        "members": [
            {
                "observation_id": member.candidate.observation.id,
                "video_id": member.candidate.observation.video_id,
                "source_id": member.candidate.source_id,
                "input_fingerprint": (
                    member.candidate.observation.input_fingerprint
                ),
            }
            for member in members
        ],
        "edge_counts": {
            "required": len(required_pairs),
            "same_speaker": len(same_pairs),
            "different_speaker": len(different_pairs),
            "unresolved": len(unresolved_pairs),
        },
        "automatic_profile_creation_allowed": False,
    }


def _maximal_cliques(
    adjacency: Mapping[int, set[int]],
) -> tuple[set[int], ...]:
    cliques: list[set[int]] = []

    def visit(
        current: set[int],
        candidates: set[int],
        excluded: set[int],
    ) -> None:
        if not candidates and not excluded:
            if len(current) >= 2:
                cliques.append(set(current))
            return
        pivot_pool = candidates | excluded
        pivot = (
            max(
                pivot_pool,
                key=lambda item: len(candidates & adjacency[item]),
            )
            if pivot_pool
            else None
        )
        remaining = (
            candidates - adjacency[pivot]
            if pivot is not None
            else set(candidates)
        )
        for vertex in sorted(remaining):
            visit(
                current | {vertex},
                candidates & adjacency[vertex],
                excluded & adjacency[vertex],
            )
            candidates.remove(vertex)
            excluded.add(vertex)

    visit(set(), set(adjacency), set())
    cliques.sort(key=lambda item: tuple(sorted(item)))
    return tuple(cliques)


def _signature_payload(signature: DiscoverySignature) -> dict[str, Any]:
    candidate = signature.candidate
    observation = candidate.observation
    return {
        "observation_id": observation.id,
        "video_id": observation.video_id,
        "source_id": candidate.source_id,
        "observation_fingerprint": observation.input_fingerprint,
        "normalized_names": sorted(candidate.normalized_names),
        "external_consistency_score": candidate.consistency_score,
        "signature_sha256": signature.signature_sha256,
        "centroid_sha256": _sha256_json(signature.centroid),
        "spans": list(signature.span_evidence),
        "consistency_metrics": dict(signature.consistency_metrics),
    }


def _normalized_centroid(
    embeddings: Sequence[Sequence[float]],
) -> tuple[float, ...]:
    if not embeddings:
        raise ValueError("cannot build a centroid without embeddings")
    dimensions = {len(embedding) for embedding in embeddings}
    if len(dimensions) != 1 or not next(iter(dimensions)):
        raise ValueError("embeddings must have equal non-zero dimensions")
    centroid = tuple(
        sum(embedding[index] for embedding in embeddings) / len(embeddings)
        for index in range(next(iter(dimensions)))
    )
    norm = math.sqrt(sum(value * value for value in centroid))
    if norm == 0:
        raise ValueError("zero-norm centroid")
    return tuple(value / norm for value in centroid)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("centroids must have equal non-zero dimensions")
    return sum(a * b for a, b in zip(left, right))


def _span_evidence(span: CachedSpan) -> dict[str, Any]:
    evidence = asdict(span)
    evidence.pop("cache_hit", None)
    evidence.pop("wav_path", None)
    return evidence


def _counts(values: Iterable[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
