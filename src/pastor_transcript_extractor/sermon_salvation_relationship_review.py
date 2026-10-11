"""Bounded review workflow for the first conditional salvation leaf pack."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.sermon_classification import TranscriptBlock
from pastor_transcript_extractor.sermon_classifier_typesafe import (
    SALVATION_RELATIONSHIPS_PACK,
    TypeSafeBlockCache,
    TypeSafeBlockClient,
)
from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIPS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
    SALVATION_ROUTE_POLICY_VERSION,
    salvation_relationship_pack_digest,
    salvation_relationship_pack_inventory,
    salvation_route_decision,
    resolve_salvation_relationship_analysis_artifact,
)
from pastor_transcript_extractor.sermon_topic_profile_analysis import (
    read_classification_for_gate,
    read_topic_analysis_for_gate,
)
from pastor_transcript_extractor.sermon_topic_projection import (
    assess_topic_profile_projection,
)
from pastor_transcript_extractor.sermon_topic_stage4 import (
    assess_topic_stage4_readiness,
)
from pastor_transcript_extractor.sermon_topics import (
    TOPIC_PACK_VERSION,
    TopicBlockContext,
    resolve_topic_block_context,
)
from pastor_transcript_extractor.storage import Database


SALVATION_RELATIONSHIP_REVIEW_SCHEMA_VERSION = 1
SALVATION_RELATIONSHIP_REVIEW_POLICY_VERSION = (
    "salvation-relationships-out-of-sample-v3"
)
DEFAULT_SALVATION_RELATIONSHIP_REVIEW_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-relationships-review-v3.json"
)
DEFAULT_SALVATION_OBEDIENCE_CALIBRATION_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-obedience-consequence-calibration-v1.json"
)
DEFAULT_SALVATION_SEMANTIC_CALIBRATION_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-semantic-calibration-v1.json"
)
DEFAULT_SALVATION_FINAL_CALIBRATION_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-final-calibration-v1.json"
)
DEFAULT_SALVATION_V5_CALIBRATION_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-v5-calibration-v1.json"
)
PRIOR_SALVATION_RELATIONSHIPS_PACK_VERSION = (
    "salvation-relationships-v2-evidence-boundaries"
)
SEMANTIC_CALIBRATION_RELATIONSHIPS = (
    "faith_as_receiving_response",
    "repentance_as_receiving_response",
    "obedience_as_consequence_or_evidence",
)
SEMANTIC_CALIBRATION_REVISED_PACK_VERSION = (
    "salvation-relationships-v3-receiving-and-fruit-boundaries"
)
FINAL_CALIBRATION_OBSERVATION_POLICY_VERSION = (
    "salvation-relationship-observation-thresholds-v2-assurance"
)
PRIOR_V4_SALVATION_RELATIONSHIPS_PACK_VERSION = (
    "salvation-relationships-v4-repentant-surrender-boundary"
)
V5_CALIBRATION_RELATIONSHIPS = (
    "divine_grace_initiative",
    "conversion_new_birth",
    "obedience_as_condition_or_means",
    "obedience_as_consequence_or_evidence",
)
V5_REVIEW_LABELS = {
    "281:113:divine_grace_initiative": "negative",
    "1037:72:divine_grace_initiative": "negative",
    "590:43:divine_grace_initiative": "affirmative",
    "4430:47:divine_grace_initiative": "negative",
    "350:34:divine_grace_initiative": "affirmative",
    "590:52:divine_grace_initiative": "affirmative",
    "281:115:conversion_new_birth": "affirmative",
    "350:50:conversion_new_birth": "negative",
    "4394:50:conversion_new_birth": "affirmative",
    "281:124:conversion_new_birth": "affirmative_provisional",
    "4589:47:conversion_new_birth": "affirmative",
    "590:35:conversion_new_birth": "negative",
    "1200:45:obedience_as_condition_or_means": "ambiguous",
    "590:31:obedience_as_condition_or_means": "affirmative",
    "1037:58:obedience_as_condition_or_means": "ambiguous",
    "3973:99:obedience_as_condition_or_means": "negative",
    "4394:39:obedience_as_condition_or_means": "negative",
    "4394:44:obedience_as_condition_or_means": "negative",
    "4589:32:obedience_as_consequence_or_evidence": "negative",
    "4430:47:obedience_as_consequence_or_evidence": "negative",
    "4589:47:obedience_as_consequence_or_evidence": "affirmative",
    "4589:40:obedience_as_consequence_or_evidence": "negative",
    "350:36:obedience_as_consequence_or_evidence": "negative",
    "4394:50:obedience_as_consequence_or_evidence": "negative",
}
SEMANTIC_REGRESSION_CASES = {
    "faith_as_receiving_response": frozenset(
        {"281:115", "281:124", "4394:37", "4394:50"}
    ),
    "repentance_as_receiving_response": frozenset(
        {"350:47", "350:65", "3973:89", "3974:66", "3974:91", "4589:28"}
    ),
    "obedience_as_consequence_or_evidence": frozenset(
        {"350:58", "3973:99", "4052:100", "1200:44"}
    ),
}
SEMANTIC_REGRESSION_CANDIDATE_KEYS = frozenset().union(
    *SEMANTIC_REGRESSION_CASES.values()
)
RECALIBRATION_REVIEWED_CANDIDATE_KEYS = SEMANTIC_REGRESSION_CANDIDATE_KEYS | frozenset(
    {"4430:31", "590:44", "4589:41", "4430:44"}
)
FAITH_POSITIVE_RECALL_ANCHORS = frozenset({"281:123", "4430:48"})
FAITH_REVIEWED_NEGATIVE_KEYS = frozenset(
    {
        "281:115",
        "281:124",
        "350:31",
        "4394:37",
        "4394:47",
        "4394:50",
        "4394:52",
        "4589:42",
    }
)
REPENTANCE_FINAL_REGRESSION_LABELS = {
    "350:47": "affirmative",
    "3973:89": "affirmative",
    "3974:91": "affirmative",
    "350:65": "negative",
    "3974:66": "negative",
    "4589:28": "negative",
}
PRIOR_REVIEW_FINGERPRINT = (
    "e6ef7c6b8e8e6ee92588c3a7a045794694dac1941546043b1e0b0f6f92ce2980"
)
PRIOR_REVIEWED_CANDIDATE_KEYS = frozenset(
    {
        "281:124",
        "350:44",
        "1200:35",
        "3974:81",
        "4052:103",
        "4394:46",
        "4394:49",
        "4430:49",
        "4430:57",
        "4458:70",
        "4589:38",
        "4589:47",
    }
)
ALL_REVIEWED_CANDIDATE_KEYS = PRIOR_REVIEWED_CANDIDATE_KEYS | frozenset(
    {
        "281:123",
        "3973:81",
        "3974:91",
        "4394:44",
        "4394:45",
        "4430:27",
        "4430:31",
        "4430:48",
        "4458:66",
        "4458:68",
        "4589:30",
        "1200:44",
    }
)
OBEDIENCE_CONSEQUENCE_CALIBRATION_WINDOW = (0.55, 0.65)
OBEDIENCE_CONSEQUENCE_CALIBRATION_CANDIDATE_LIMIT = 12
OBEDIENCE_CONSEQUENCE_CALIBRATION_PER_PASTOR_LIMIT = 3
OBEDIENCE_CONSEQUENCE_CALIBRATION_CUES = (
    "works in you",
    "worketh in you",
    "living through",
    "lives through",
    "good works",
    "changed life",
    "righteousness",
    "obedience",
    "obey",
    "fruit",
    "evidence",
    "holy",
    "holiness",
    "transform",
    "born again",
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


def _routed_candidates(
    database: Database,
    cohort: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    readiness = assess_topic_stage4_readiness(database, cohort)
    if not readiness["ready"]:
        raise ValueError(
            "Salvation relationship review requires ready Stage 4 inputs: "
            + ", ".join(readiness["blockers"])
        )
    videos = {video.id: video for video in database.list_videos()}
    candidates: list[dict[str, Any]] = []
    for pastor in cohort["pastors"]:
        for sermon in pastor["sermons"]:
            video_id = int(sermon["video_id"])
            video = videos.get(video_id)
            if video is None:
                raise ValueError(f"Unknown salvation relationship video: {video_id}")
            gate = assess_topic_profile_projection(database, video)
            if (
                not gate.eligible
                or gate.source_path is None
                or gate.topic_analysis_fingerprint is None
            ):
                raise ValueError(
                    f"Video {video_id} is not eligible for salvation relationships"
                )
            analysis, _projection = read_topic_analysis_for_gate(gate)
            if analysis.get("question_pack_version") != TOPIC_PACK_VERSION:
                raise ValueError(
                    f"Video {video_id} uses a different broad topic pack"
                )
            raw_blocks = analysis.get("blocks")
            if not isinstance(raw_blocks, list):
                raise ValueError(f"Video {video_id} has no topic blocks")
            for raw_block in raw_blocks:
                if not isinstance(raw_block, Mapping):
                    continue
                route = salvation_route_decision(raw_block)
                if not route["route"]:
                    continue
                context = resolve_topic_block_context(raw_block)
                target = context.get("target_text")
                if not isinstance(target, str) or not target.strip():
                    raise ValueError(
                        f"Topic block {raw_block.get('block_id')} has no leaf target text"
                    )
                segment_indexes = raw_block.get("segment_indexes")
                if not isinstance(segment_indexes, list):
                    raise ValueError(
                        f"Topic block {raw_block.get('block_id')} has no segment indexes"
                    )
                candidates.append(
                    {
                        "candidate_key": f"{video_id}:{int(raw_block['block_id'])}",
                        "pastor": {
                            "display_name": pastor.get("display_name"),
                            "pastor_id": pastor.get("pastor_id"),
                            "slug": pastor.get("slug"),
                        },
                        "video_id": video_id,
                        "youtube_video_id": video.youtube_video_id,
                        "title": video.title,
                        "block_id": int(raw_block["block_id"]),
                        "start_seconds": float(raw_block["start_seconds"]),
                        "end_seconds": float(raw_block["end_seconds"]),
                        "segment_indexes": [int(value) for value in segment_indexes],
                        "leading_context": str(context.get("leading_context") or ""),
                        "target_text": target,
                        "trailing_context": str(context.get("trailing_context") or ""),
                        "context_diagnostics": dict(
                            context.get("diagnostics")
                            if isinstance(context.get("diagnostics"), Mapping)
                            else {}
                        ),
                        "route": route,
                        "topic_analysis_fingerprint": (
                            gate.topic_analysis_fingerprint
                        ),
                        "cache_dir": str(
                            Path(gate.source_path).parent / "inference-cache"
                        ),
                    }
                )
    if not candidates:
        raise ValueError("No blocks satisfy the reviewed salvation route")
    return candidates, str(readiness["input_fingerprint"])


def _select_review_candidates(
    candidates: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    fresh_candidates = [
        candidate
        for candidate in candidates
        if str(candidate["candidate_key"])
        not in PRIOR_REVIEWED_CANDIDATE_KEYS
    ]
    selected: list[dict[str, Any]] = []
    for pastor_slug in sorted(
        {
            str(candidate["pastor"].get("slug"))
            for candidate in fresh_candidates
        }
    ):
        pastor_candidates = sorted(
            (
                candidate
                for candidate in fresh_candidates
                if str(candidate["pastor"].get("slug")) == pastor_slug
            ),
            key=lambda candidate: (
                float(candidate["route"]["supporting_or_above_probability"]),
                int(candidate["video_id"]),
                int(candidate["block_id"]),
            ),
        )
        if len(pastor_candidates) < 3:
            raise ValueError(
                "Salvation relationship review requires at least three routed "
                f"blocks for pastor {pastor_slug}"
            )
        positions = (0, len(pastor_candidates) // 2, len(pastor_candidates) - 1)
        used: set[str] = set()
        for stratum, position in zip(
            ("threshold", "median", "strongest"),
            positions,
            strict=True,
        ):
            candidate = pastor_candidates[position]
            key = str(candidate["candidate_key"])
            if key in used:
                candidate = next(
                    (
                        item
                        for item in pastor_candidates
                        if str(item["candidate_key"]) not in used
                    ),
                    candidate,
                )
                key = str(candidate["candidate_key"])
            used.add(key)
            selected.append({**candidate, "review_stratum": stratum})
    return selected


def select_obedience_consequence_calibration_candidates(
    candidates: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Select a small fresh, diverse set using only deterministic text cues."""
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for candidate in candidates:
        key = str(candidate["candidate_key"])
        if key in ALL_REVIEWED_CANDIDATE_KEYS:
            continue
        text = str(candidate["target_text"]).lower()
        cue_score = sum(text.count(cue) for cue in OBEDIENCE_CONSEQUENCE_CALIBRATION_CUES)
        if cue_score:
            ranked.append((cue_score, key, candidate))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected: list[dict[str, Any]] = []
    pastor_counts: dict[str, int] = {}
    for cue_score, _key, candidate in ranked:
        pastor_slug = str(candidate["pastor"].get("slug"))
        if (
            pastor_counts.get(pastor_slug, 0)
            >= OBEDIENCE_CONSEQUENCE_CALIBRATION_PER_PASTOR_LIMIT
        ):
            continue
        selected.append({**candidate, "selection_cue_score": cue_score})
        pastor_counts[pastor_slug] = pastor_counts.get(pastor_slug, 0) + 1
        if len(selected) == OBEDIENCE_CONSEQUENCE_CALIBRATION_CANDIDATE_LIMIT:
            break
    if len(selected) < OBEDIENCE_CONSEQUENCE_CALIBRATION_CANDIDATE_LIMIT:
        raise ValueError(
            "Obedience-consequence calibration could not select twelve fresh "
            "cue-bearing routed blocks"
        )
    return selected


def evaluate_salvation_relationship_review(
    database: Database,
    cohort: Mapping[str, Any],
    *,
    model: str,
    client: TypeSafeBlockClient,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Run the bounded leaf sample through independent per-video caches."""
    candidates, readiness_fingerprint = _routed_candidates(database, cohort)
    selected = _select_review_candidates(candidates)
    evaluated, execution = evaluate_salvation_relationship_candidates(
        selected,
        model=model,
        client=client,
    )
    evaluated.sort(
        key=lambda item: (
            str(item["pastor"].get("slug")),
            ("threshold", "median", "strongest").index(item["review_stratum"]),
        )
    )
    identity = {
        "schema_version": SALVATION_RELATIONSHIP_REVIEW_SCHEMA_VERSION,
        "review_policy_version": SALVATION_RELATIONSHIP_REVIEW_POLICY_VERSION,
        "cohort_sha256": cohort.get("cohort_sha256"),
        "readiness_input_fingerprint": readiness_fingerprint,
        "broad_question_pack_version": TOPIC_PACK_VERSION,
        "route_policy_version": SALVATION_ROUTE_POLICY_VERSION,
        "leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "leaf_pack_digest": salvation_relationship_pack_digest(),
        "requested_model_id": model,
        "routed_candidate_count": len(candidates),
        "prior_review": {
            "input_fingerprint": PRIOR_REVIEW_FINGERPRINT,
            "excluded_candidate_keys": sorted(
                PRIOR_REVIEWED_CANDIDATE_KEYS
            ),
        },
        "cases": evaluated,
    }
    packet = {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "observations_pending_review",
        "policy_effect": "none",
        "cache": {
            "identity": "per_video_versioned_answer_pack",
            "location": "beside_source_classification",
        },
        "interpretation": (
            "This out-of-sample packet keeps the accepted leaf questions and route "
            "unchanged while excluding every development case. It does not activate "
            "leaf collection during ordinary reclassification or authorize "
            "profile-level theological claims."
        ),
    }
    return packet, execution


def evaluate_salvation_relationship_candidates(
    selected: Sequence[Mapping[str, Any]],
    *,
    model: str,
    client: TypeSafeBlockClient,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Evaluate selected candidates through the shared per-video leaf caches."""
    evaluated: list[dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0
    provider_requests = 0
    for video_id in sorted({int(item["video_id"]) for item in selected}):
        video_candidates = [
            item for item in selected if int(item["video_id"]) == video_id
        ]
        blocks = [
            TranscriptBlock(
                block_id=int(item["block_id"]),
                segment_indexes=list(item["segment_indexes"]),
                start_seconds=float(item["start_seconds"]),
                end_seconds=float(item["end_seconds"]),
                text=str(item["target_text"]),
            )
            for item in video_candidates
        ]
        contexts = {
            int(item["block_id"]): TopicBlockContext(
                leading_context=str(item["leading_context"]),
                target_text=str(item["target_text"]),
                trailing_context=str(item["trailing_context"]),
                diagnostics=dict(item["context_diagnostics"]),
            )
            for item in video_candidates
        }
        cache = TypeSafeBlockCache(
            Path(str(video_candidates[0]["cache_dir"])),
            model=model,
        )
        answers = cache.assess_packs(
            client,
            {},
            blocks,
            requested_packs=frozenset({SALVATION_RELATIONSHIPS_PACK}),
            topic_contexts=contexts,
        )
        cache_hits += cache.hits
        cache_misses += cache.misses
        provider_requests += cache.provider_requests
        for item in video_candidates:
            answer = answers[int(item["block_id"])]
            provenance = answer.request_provenance.get(
                SALVATION_RELATIONSHIPS_PACK, {}
            )
            evaluated.append(
                {
                    **{
                        key: value
                        for key, value in item.items()
                        if key not in {"cache_dir", "context_diagnostics"}
                    },
                    "leaf_probabilities": {
                        relationship: round(
                            float(
                                answer.salvation_relationship_probabilities[
                                    relationship
                                ]
                            ),
                            6,
                        )
                        for relationship in SALVATION_RELATIONSHIPS
                    },
                    "resolved_model_id": answer.resolved_model_id,
                    "source_request_key": (
                        provenance.get("request_key")
                        if isinstance(provenance, Mapping)
                        else None
                    ),
                }
            )
    return evaluated, {
        "hits": cache_hits,
        "misses": cache_misses,
        "provider_requests": provider_requests,
    }


def _relationship_probabilities_for_pack(
    database: Database,
    cohort: Mapping[str, Any],
    *,
    expected_pack_version: str,
) -> dict[str, dict[str, float]]:
    """Load cached raw probabilities for an exact historical question pack."""
    videos = {video.id: video for video in database.list_videos()}
    probabilities: dict[str, dict[str, float]] = {}
    for pastor in cohort["pastors"]:
        for sermon in pastor["sermons"]:
            video_id = int(sermon["video_id"])
            video = videos.get(video_id)
            if video is None:
                raise ValueError(f"Unknown semantic calibration video: {video_id}")
            gate = assess_topic_profile_projection(database, video)
            if not gate.eligible:
                raise ValueError(
                    f"Video {video_id} is not eligible for semantic calibration"
                )
            classification = read_classification_for_gate(gate)
            artifact = resolve_salvation_relationship_analysis_artifact(classification)
            if (
                artifact.get("question_pack_version") != expected_pack_version
            ):
                raise ValueError(
                    f"Video {video_id} does not contain salvation relationship "
                    f"evidence for {expected_pack_version}; run this bounded "
                    "calibration before reclassifying the cohort"
                )
            blocks = artifact.get("blocks")
            if not isinstance(blocks, list):
                raise ValueError(
                    f"Video {video_id} has malformed relationship evidence"
                )
            for block in blocks:
                if not isinstance(block, Mapping):
                    continue
                raw = block.get("probabilities")
                if not isinstance(raw, Mapping):
                    continue
                key = f"{video_id}:{int(block['block_id'])}"
                probabilities[key] = {
                    relationship: float(raw[relationship])
                    for relationship in SALVATION_RELATIONSHIPS
                }
    return probabilities


def _legacy_relationship_probabilities(
    database: Database,
    cohort: Mapping[str, Any],
) -> dict[str, dict[str, float]]:
    return _relationship_probabilities_for_pack(
        database,
        cohort,
        expected_pack_version=PRIOR_SALVATION_RELATIONSHIPS_PACK_VERSION,
    )


def _select_semantic_heldout_probes(
    candidates: Sequence[Mapping[str, Any]],
    legacy: Mapping[str, Mapping[str, float]],
) -> list[dict[str, Any]]:
    excluded = ALL_REVIEWED_CANDIDATE_KEYS | RECALIBRATION_REVIEWED_CANDIDATE_KEYS
    probes: list[dict[str, Any]] = []
    for relationship in SEMANTIC_CALIBRATION_RELATIONSHIPS:
        threshold = SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[relationship]
        available = [
            item
            for item in candidates
            if str(item["candidate_key"]) not in excluded
            and str(item["candidate_key"]) in legacy
        ]
        for side, filtered in (
            (
                "below",
                [
                    item
                    for item in available
                    if legacy[str(item["candidate_key"])][relationship] < threshold
                ],
            ),
            (
                "at_or_above",
                [
                    item
                    for item in available
                    if legacy[str(item["candidate_key"])][relationship] >= threshold
                ],
            ),
        ):
            ordered = sorted(
                filtered,
                key=lambda item: (
                    abs(
                        legacy[str(item["candidate_key"])][relationship]
                        - threshold
                    ),
                    str(item["candidate_key"]),
                ),
            )
            selected: list[Mapping[str, Any]] = []
            represented: set[str] = set()
            for require_new_pastor in (True, False):
                for item in ordered:
                    key = str(item["candidate_key"])
                    pastor = str(item["pastor"].get("slug"))
                    if any(str(chosen["candidate_key"]) == key for chosen in selected):
                        continue
                    if require_new_pastor and pastor in represented:
                        continue
                    selected.append(item)
                    represented.add(pastor)
                    if len(selected) == 2:
                        break
                if len(selected) == 2:
                    break
            if len(selected) < 2:
                raise ValueError(
                    f"Semantic calibration lacks two fresh {side} probes for "
                    f"{relationship}"
                )
            for item in selected:
                probes.append(
                    {
                        "candidate_key": str(item["candidate_key"]),
                        "relationship": relationship,
                        "boundary_side": side,
                        "prior_probability": round(
                            legacy[str(item["candidate_key"])][relationship], 6
                        ),
                    }
                )
    return probes


def evaluate_salvation_semantic_calibration(
    database: Database,
    cohort: Mapping[str, Any],
    *,
    model: str,
    client: TypeSafeBlockClient,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Compare revised semantics on regressions and fresh held-out boundaries."""
    if SALVATION_RELATIONSHIPS_PACK_VERSION != SEMANTIC_CALIBRATION_REVISED_PACK_VERSION:
        raise ValueError(
            "Semantic calibration v1 is archived for the reviewed v3 pack; use "
            "salvation-final-calibration for the current pack"
        )
    candidates, readiness_fingerprint = _routed_candidates(database, cohort)
    by_key = {str(item["candidate_key"]): item for item in candidates}
    missing = sorted(SEMANTIC_REGRESSION_CANDIDATE_KEYS - set(by_key))
    if missing:
        raise ValueError(
            "Semantic calibration regression cases are no longer routed: "
            + ", ".join(missing)
        )
    legacy = _legacy_relationship_probabilities(database, cohort)
    heldout_probes = _select_semantic_heldout_probes(candidates, legacy)
    heldout_keys = {str(probe["candidate_key"]) for probe in heldout_probes}
    evaluation_keys = sorted(SEMANTIC_REGRESSION_CANDIDATE_KEYS | heldout_keys)
    evaluated, execution = evaluate_salvation_relationship_candidates(
        [by_key[key] for key in evaluation_keys],
        model=model,
        client=client,
    )
    evaluated_by_key = {
        str(item["candidate_key"]): item for item in evaluated
    }
    regression_probes = [
        {
            "candidate_key": key,
            "relationship": relationship,
            "prior_probability": round(legacy[key][relationship], 6),
            "revised_probability": round(
                float(evaluated_by_key[key]["leaf_probabilities"][relationship]), 6
            ),
        }
        for relationship in SEMANTIC_CALIBRATION_RELATIONSHIPS
        for key in sorted(SEMANTIC_REGRESSION_CASES[relationship])
    ]
    for probe in heldout_probes:
        key = str(probe["candidate_key"])
        probe["revised_probability"] = round(
            float(
                evaluated_by_key[key]["leaf_probabilities"][probe["relationship"]]
            ),
            6,
        )
    assurance_candidates = sorted(
        (
            {
                "candidate_key": key,
                "probability": round(values["assurance_security"], 6),
            }
            for key, values in legacy.items()
            if values["assurance_security"] > 0.59
            and key not in ALL_REVIEWED_CANDIDATE_KEYS
            and key not in RECALIBRATION_REVIEWED_CANDIDATE_KEYS
            and key in by_key
        ),
        key=lambda item: (float(item["probability"]), str(item["candidate_key"])),
    )[:6]
    case_keys = {
        str(probe["candidate_key"])
        for probe in [*regression_probes, *heldout_probes, *assurance_candidates]
    }
    cases = [
        {
            key: value
            for key, value in by_key[candidate_key].items()
            if key not in {"cache_dir", "context_diagnostics", "segment_indexes"}
        }
        for candidate_key in sorted(case_keys)
    ]
    identity = {
        "schema_version": 1,
        "review_policy_version": "salvation-semantic-calibration-v1",
        "cohort_sha256": cohort.get("cohort_sha256"),
        "readiness_input_fingerprint": readiness_fingerprint,
        "prior_leaf_pack_version": PRIOR_SALVATION_RELATIONSHIPS_PACK_VERSION,
        "revised_leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "revised_leaf_pack_digest": salvation_relationship_pack_digest(),
        "requested_model_id": model,
        "unchanged_thresholds": dict(SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS),
        "regression_probes": regression_probes,
        "heldout_probes": heldout_probes,
        "assurance_upward_probes": assurance_candidates,
        "cases": cases,
    }
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "semantic_calibration_pending_review",
        "policy_effect": "none",
        "interpretation": (
            "The three revised questions are compared against their reviewed regression "
            "cases and a separate fresh held-out boundary set. Assurance is unchanged "
            "and uses only prior cached judgments above 0.59. No threshold or production "
            "observation policy changes in this packet."
        ),
    }, execution


def evaluate_salvation_final_calibration(
    database: Database,
    cohort: Mapping[str, Any],
    *,
    model: str,
    client: TypeSafeBlockClient,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Run the last bounded faith-recall and repentance-ordering check."""
    if (
        SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
        != FINAL_CALIBRATION_OBSERVATION_POLICY_VERSION
    ):
        raise ValueError(
            "Final salvation calibration v1 is archived for the reviewed pre-freeze "
            "policy; reclassify the cohort with the frozen policy"
        )
    candidates, readiness_fingerprint = _routed_candidates(database, cohort)
    by_key = {str(item["candidate_key"]): item for item in candidates}
    legacy = _legacy_relationship_probabilities(database, cohort)
    required = FAITH_POSITIVE_RECALL_ANCHORS | frozenset(
        REPENTANCE_FINAL_REGRESSION_LABELS
    )
    missing = sorted(required - set(by_key) | required - set(legacy))
    if missing:
        raise ValueError(
            "Final salvation calibration cases are unavailable: "
            + ", ".join(missing)
        )
    strongest_faith = [
        key
        for key, _values in sorted(
            legacy.items(),
            key=lambda item: (
                -float(item[1]["faith_as_receiving_response"]),
                item[0],
            ),
        )
        if key in by_key
        and key not in FAITH_POSITIVE_RECALL_ANCHORS
        and key not in FAITH_REVIEWED_NEGATIVE_KEYS
    ][:4]
    if len(strongest_faith) < 4:
        raise ValueError("Final calibration requires four strong faith candidates")
    faith_keys = sorted(FAITH_POSITIVE_RECALL_ANCHORS | set(strongest_faith))
    evaluation_keys = sorted(set(faith_keys) | set(REPENTANCE_FINAL_REGRESSION_LABELS))
    evaluated, execution = evaluate_salvation_relationship_candidates(
        [by_key[key] for key in evaluation_keys],
        model=model,
        client=client,
    )
    evaluated_by_key = {
        str(item["candidate_key"]): item for item in evaluated
    }
    faith_probes = [
        {
            "candidate_key": key,
            "selection": (
                "reviewed_affirmative_anchor"
                if key in FAITH_POSITIVE_RECALL_ANCHORS
                else "strongest_prior_candidate"
            ),
            "prior_probability": round(
                legacy[key]["faith_as_receiving_response"], 6
            ),
            "revised_probability": round(
                float(
                    evaluated_by_key[key]["leaf_probabilities"][
                        "faith_as_receiving_response"
                    ]
                ),
                6,
            ),
        }
        for key in faith_keys
    ]
    repentance_probes = [
        {
            "candidate_key": key,
            "review_label": label,
            "v2_probability": round(
                legacy[key]["repentance_as_receiving_response"], 6
            ),
            "revised_probability": round(
                float(
                    evaluated_by_key[key]["leaf_probabilities"][
                        "repentance_as_receiving_response"
                    ]
                ),
                6,
            ),
        }
        for key, label in sorted(REPENTANCE_FINAL_REGRESSION_LABELS.items())
    ]
    cases = [
        {
            key: value
            for key, value in evaluated_by_key[candidate_key].items()
            if key not in {"cache_dir", "context_diagnostics", "segment_indexes"}
        }
        for candidate_key in evaluation_keys
    ]
    identity = {
        "schema_version": 1,
        "review_policy_version": "salvation-final-calibration-v1",
        "cohort_sha256": cohort.get("cohort_sha256"),
        "readiness_input_fingerprint": readiness_fingerprint,
        "prior_leaf_pack_version": PRIOR_SALVATION_RELATIONSHIPS_PACK_VERSION,
        "revised_leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "revised_leaf_pack_digest": salvation_relationship_pack_digest(),
        "requested_model_id": model,
        "observation_policy_version": (
            SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
        ),
        "unchanged_except_assurance_thresholds": dict(
            SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS
        ),
        "faith_probes": faith_probes,
        "repentance_probes": repentance_probes,
        "cases": cases,
    }
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "final_leaf_calibration_pending_review",
        "policy_effect": "assurance_threshold_only",
        "interpretation": (
            "Assurance is now collected at 0.62 and obedience-as-consequence is "
            "frozen at 0.55. This packet makes no further threshold change. It checks "
            "faith positive recall on two reviewed anchors plus four strongest prior "
            "candidates, and reruns the six decisive repentance regressions under the "
            "revised salvation-linked surrender boundary."
        ),
    }, execution


def _select_v5_heldout_probes(
    candidates: Sequence[Mapping[str, Any]],
    prior_probabilities: Mapping[str, Mapping[str, float]],
    *,
    excluded_case_keys: set[str],
) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for relationship in V5_CALIBRATION_RELATIONSHIPS:
        threshold = SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[relationship]
        available = [
            item
            for item in candidates
            if str(item["candidate_key"]) not in excluded_case_keys
            and str(item["candidate_key"]) in prior_probabilities
        ]
        ordered_by_side: dict[str, list[Mapping[str, Any]]] = {}
        for side, predicate in (
            ("below", lambda value: value < threshold),
            ("at_or_above", lambda value: value >= threshold),
        ):
            ordered_by_side[side] = sorted(
                (
                    item
                    for item in available
                    if predicate(
                        prior_probabilities[str(item["candidate_key"])][relationship]
                    )
                ),
                key=lambda item: (
                    abs(
                        prior_probabilities[str(item["candidate_key"])][relationship]
                        - threshold
                    ),
                    str(item["candidate_key"]),
                ),
            )

        selected: list[tuple[Mapping[str, Any], str]] = []
        selected_keys: set[str] = set()

        def select_diverse(
            ordered: Sequence[Mapping[str, Any]],
            *,
            limit: int,
            selection_mode: str,
            represented: set[str],
        ) -> None:
            """Append nearby unused cases, preferring pastors not yet represented."""
            for require_new_pastor in (True, False):
                for item in ordered:
                    key = str(item["candidate_key"])
                    pastor = str(item["pastor"].get("slug"))
                    if key in selected_keys:
                        continue
                    if require_new_pastor and pastor in represented:
                        continue
                    selected.append((item, selection_mode))
                    selected_keys.add(key)
                    represented.add(pastor)
                    if len(selected) == limit:
                        return

        # Preserve the intended two-per-side boundary sample whenever the cached
        # evidence supports it. Sparse leaves may not have two fresh observations
        # on both sides, so the second pass fills the fixed four-case quota from
        # the nearest unused evidence on either side.
        for side in ("below", "at_or_above"):
            represented: set[str] = set()
            side_limit = len(selected) + min(2, len(ordered_by_side[side]))
            select_diverse(
                ordered_by_side[side],
                limit=side_limit,
                selection_mode="balanced_side",
                represented=represented,
            )

        if len(selected) < 4:
            nearest_unused = sorted(
                available,
                key=lambda item: (
                    abs(
                        prior_probabilities[str(item["candidate_key"])][relationship]
                        - threshold
                    ),
                    str(item["candidate_key"]),
                ),
            )
            select_diverse(
                nearest_unused,
                limit=4,
                selection_mode="quota_fill",
                represented={
                    str(item["pastor"].get("slug")) for item, _mode in selected
                },
            )
        if len(selected) < 4:
            raise ValueError(
                f"V5 calibration requires four fresh probes for {relationship}"
            )

        side_ranks = {"below": 0, "at_or_above": 0}
        for item, selection_mode in selected:
            key = str(item["candidate_key"])
            probability = prior_probabilities[key][relationship]
            side = "at_or_above" if probability >= threshold else "below"
            side_ranks[side] += 1
            probes.append(
                {
                    "candidate_key": key,
                    "relationship": relationship,
                    "prior_probability": round(probability, 6),
                    "prior_boundary_side": side,
                    "side_rank": side_ranks[side],
                    "selection_mode": selection_mode,
                }
            )
    return probes


def evaluate_salvation_v5_calibration(
    database: Database,
    cohort: Mapping[str, Any],
    boundary_review: Mapping[str, Any],
    collection_review: Mapping[str, Any],
    *,
    model: str,
    client: TypeSafeBlockClient,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Evaluate the four revised v5 questions on regressions and held-out cases."""
    if (
        boundary_review.get("review_policy_version")
        != "salvation-four-leaf-boundary-recalibration-v1"
        or boundary_review.get("question_pack_version")
        != PRIOR_V4_SALVATION_RELATIONSHIPS_PACK_VERSION
    ):
        raise ValueError("V5 calibration requires the reviewed v4 boundary packet")
    reviewed_probe_keys = {
        str(probe.get("judgment_key"))
        for probe in boundary_review.get("probes", [])
        if isinstance(probe, Mapping)
        and probe.get("relationship") in V5_CALIBRATION_RELATIONSHIPS
    }
    if reviewed_probe_keys != set(V5_REVIEW_LABELS):
        raise ValueError("V4 boundary packet does not match the reviewed probe set")
    candidates, readiness_fingerprint = _routed_candidates(database, cohort)
    by_key = {str(item["candidate_key"]): item for item in candidates}
    prior_probabilities = _relationship_probabilities_for_pack(
        database,
        cohort,
        expected_pack_version=PRIOR_V4_SALVATION_RELATIONSHIPS_PACK_VERSION,
    )
    reviewed_case_keys = {
        str(case.get("case_key"))
        for packet in (boundary_review, collection_review)
        for case in packet.get("cases", [])
        if isinstance(case, Mapping)
    }
    regression_case_keys = {
        judgment_key.rsplit(":", 1)[0] for judgment_key in V5_REVIEW_LABELS
    }
    missing = sorted(regression_case_keys - set(by_key))
    if missing:
        raise ValueError(
            "V5 calibration regression cases are no longer routed: "
            + ", ".join(missing)
        )
    heldout = _select_v5_heldout_probes(
        candidates,
        prior_probabilities,
        excluded_case_keys=reviewed_case_keys,
    )
    evaluation_keys = sorted(
        regression_case_keys
        | {str(probe["candidate_key"]) for probe in heldout}
    )
    evaluated, execution = evaluate_salvation_relationship_candidates(
        [by_key[key] for key in evaluation_keys],
        model=model,
        client=client,
    )
    evaluated_by_key = {
        str(item["candidate_key"]): item for item in evaluated
    }
    regression_probes = []
    for judgment_key, review_label in V5_REVIEW_LABELS.items():
        case_key, relationship = judgment_key.rsplit(":", 1)
        regression_probes.append(
            {
                "judgment_key": judgment_key,
                "candidate_key": case_key,
                "relationship": relationship,
                "review_label": review_label,
                "prior_probability": round(
                    prior_probabilities[case_key][relationship], 6
                ),
                "revised_probability": round(
                    float(
                        evaluated_by_key[case_key]["leaf_probabilities"][relationship]
                    ),
                    6,
                ),
            }
        )
    for probe in heldout:
        key = str(probe["candidate_key"])
        probe["revised_probability"] = round(
            float(
                evaluated_by_key[key]["leaf_probabilities"][probe["relationship"]]
            ),
            6,
        )
    cases = [
        {
            key: value
            for key, value in evaluated_by_key[candidate_key].items()
            if key not in {"cache_dir", "context_diagnostics", "segment_indexes"}
        }
        for candidate_key in evaluation_keys
    ]
    identity = {
        "schema_version": 1,
        "review_policy_version": "salvation-v5-causal-boundaries-calibration-v1",
        "cohort_sha256": cohort.get("cohort_sha256"),
        "readiness_input_fingerprint": readiness_fingerprint,
        "prior_boundary_review_fingerprint": boundary_review.get("input_fingerprint"),
        "prior_collection_review_fingerprint": collection_review.get(
            "input_fingerprint"
        ),
        "prior_leaf_pack_version": PRIOR_V4_SALVATION_RELATIONSHIPS_PACK_VERSION,
        "revised_leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "revised_leaf_pack_digest": salvation_relationship_pack_digest(),
        "requested_model_id": model,
        "unchanged_thresholds": {
            relationship: SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[
                relationship
            ]
            for relationship in V5_CALIBRATION_RELATIONSHIPS
        },
        "relationship_definitions": {
            relationship: {
                key: value
                for key, value in salvation_relationship_pack_inventory()[
                    "relationships"
                ][relationship].items()
            }
            for relationship in V5_CALIBRATION_RELATIONSHIPS
        },
        "regression_probes": regression_probes,
        "heldout_probes": heldout,
        "cases": cases,
    }
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "v5_question_calibration_pending_review",
        "policy_effect": "none",
        "interpretation": (
            "Only four relationship questions changed. This bounded packet reruns all "
            "twenty-four human-labeled v4 probes and adds sixteen fresh held-out "
            "probability neighbors. All thresholds remain unchanged, and the shared "
            "per-video pack cache makes an unchanged replay provider-free."
        ),
    }, execution


def evaluate_obedience_consequence_calibration(
    database: Database,
    cohort: Mapping[str, Any],
    *,
    model: str,
    client: TypeSafeBlockClient,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Evaluate a final bounded sample for the unresolved consequence leaf."""
    candidates, readiness_fingerprint = _routed_candidates(database, cohort)
    selected = select_obedience_consequence_calibration_candidates(candidates)
    evaluated, execution = evaluate_salvation_relationship_candidates(
        selected,
        model=model,
        client=client,
    )
    relationship = "obedience_as_consequence_or_evidence"
    evaluated.sort(
        key=lambda item: (
            float(item["leaf_probabilities"][relationship]),
            str(item["candidate_key"]),
        )
    )
    lower, upper = OBEDIENCE_CONSEQUENCE_CALIBRATION_WINDOW
    in_window = [
        item
        for item in evaluated
        if lower <= float(item["leaf_probabilities"][relationship]) <= upper
    ]
    probes = sorted(
        sorted(
            in_window,
            key=lambda item: (
                abs(float(item["leaf_probabilities"][relationship]) - 0.60),
                str(item["candidate_key"]),
            ),
        )[:6],
        key=lambda item: (
            float(item["leaf_probabilities"][relationship]),
            str(item["candidate_key"]),
        ),
    )
    identity = {
        "schema_version": SALVATION_RELATIONSHIP_REVIEW_SCHEMA_VERSION,
        "review_policy_version": "salvation-obedience-consequence-calibration-v1",
        "cohort_sha256": cohort.get("cohort_sha256"),
        "readiness_input_fingerprint": readiness_fingerprint,
        "broad_question_pack_version": TOPIC_PACK_VERSION,
        "route_policy_version": SALVATION_ROUTE_POLICY_VERSION,
        "leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "leaf_pack_digest": salvation_relationship_pack_digest(),
        "observation_policy_version": (
            SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
        ),
        "settled_thresholds": dict(
            SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS
        ),
        "relationship": relationship,
        "calibration_window": [lower, upper],
        "prior_boundary_review_fingerprint": (
            "7f76957f5ff89fe010a943713c8092353ded4fe69e1ad501c149308b55ee4d2e"
        ),
        "excluded_candidate_keys": sorted(ALL_REVIEWED_CANDIDATE_KEYS),
        "selection": {
            "candidate_limit": OBEDIENCE_CONSEQUENCE_CALIBRATION_CANDIDATE_LIMIT,
            "per_pastor_limit": (
                OBEDIENCE_CONSEQUENCE_CALIBRATION_PER_PASTOR_LIMIT
            ),
            "cues": list(OBEDIENCE_CONSEQUENCE_CALIBRATION_CUES),
        },
        "attempted_cases": evaluated,
        "probes": probes,
    }
    enough_probes = len(probes) >= 4
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": (
            "observations_pending_review"
            if enough_probes
            else "insufficient_boundary_probes"
        ),
        "policy_effect": "none",
        "interpretation": (
            "This cache-first calibration evaluates twelve fresh, cue-bearing routed "
            "blocks but presents at most six whose obedience-as-consequence "
            "probability falls from 0.55 through 0.65. It changes no question, route, "
            "threshold, or production collection policy."
        ),
    }, execution


def render_obedience_consequence_calibration(packet: Mapping[str, Any]) -> str:
    relationship = str(packet["relationship"])
    lines = [
        "# Salvation obedience-as-consequence calibration",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Leaf pack: `{packet['leaf_pack_version']}`",
        f"- Attempted fresh cases: `{len(packet['attempted_cases'])}`",
        f"- Boundary probes: `{len(packet['probes'])}`",
        "- Calibration window: "
        f"`{float(packet['calibration_window'][0]):.2f}`–"
        f"`{float(packet['calibration_window'][1]):.2f}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "The other eleven relationship boundaries are settled and out of scope. "
        "For each probe, decide only whether the target asserts obedience, works, "
        "holiness, or transformed conduct as a consequence, fruit, sign, or evidence "
        "of salvation or grace.",
        "",
        "## Attempted cases",
        "",
        "| Case | Pastor | Cue score | Probability | In review window |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    probe_keys = {str(item["candidate_key"]) for item in packet["probes"]}
    for case in packet["attempted_cases"]:
        probability = float(case["leaf_probabilities"][relationship])
        lines.append(
            f"| {case['candidate_key']} | {case['pastor']['display_name']} | "
            f"{case['selection_cue_score']} | {probability:.3f} | "
            f"{'yes' if str(case['candidate_key']) in probe_keys else 'no'} |"
        )
    lines.extend(["", "## Boundary probes", ""])
    if not packet["probes"]:
        lines.extend(
            [
                "No attempted case fell inside the calibration window. The packet is "
                "diagnostic only and cannot settle this leaf.",
                "",
            ]
        )
    for case in packet["probes"]:
        probability = float(case["leaf_probabilities"][relationship])
        lines.extend(
            [
                f"### {probability:.3f} / {case['candidate_key']}",
                "",
                f"- Pastor: {case['pastor']['display_name']}",
                f"- Recording: `{case['youtube_video_id']}` — {case['title']}",
                f"- Time: `{case['start_seconds']}`–`{case['end_seconds']}`",
                f"- Selection cue score: `{case['selection_cue_score']}`",
                "",
                "Leading context:",
                "",
                f"> {str(case['leading_context']).replace(chr(10), ' ')}",
                "",
                "Target text:",
                "",
                f"> {str(case['target_text']).replace(chr(10), ' ')}",
                "",
                "Trailing context:",
                "",
                f"> {str(case['trailing_context']).replace(chr(10), ' ')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_salvation_semantic_calibration(packet: Mapping[str, Any]) -> str:
    cases = {str(item["candidate_key"]): item for item in packet["cases"]}
    lines = [
        "# Salvation semantic calibration",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Prior leaf pack: `{packet['prior_leaf_pack_version']}`",
        f"- Revised leaf pack: `{packet['revised_leaf_pack_version']}`",
        f"- Regression probes: `{len(packet['regression_probes'])}`",
        f"- Fresh held-out probes: `{len(packet['heldout_probes'])}`",
        f"- Assurance upward probes: `{len(packet['assurance_upward_probes'])}`",
        f"- Unique evidence cases: `{len(packet['cases'])}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "Review the three revised leaves semantically before considering any numeric "
        "threshold change. For regressions, confirm that known positives now rank above "
        "known negatives. For held-out probes, label each target affirmative or negative. "
        "For assurance, inspect the cached cases in ascending order and identify the first "
        "genuine assertion of assurance or security.",
        "",
        "## Revised-question regression probes",
        "",
        "| Relationship | Case | Prior p | Revised p |",
        "| --- | --- | ---: | ---: |",
    ]
    for probe in packet["regression_probes"]:
        lines.append(
            f"| {probe['relationship']} | {probe['candidate_key']} | "
            f"{float(probe['prior_probability']):.3f} | "
            f"{float(probe['revised_probability']):.3f} |"
        )
    lines.extend(
        [
            "",
            "## Fresh held-out boundary probes",
            "",
            "| Relationship | Side under prior policy | Case | Prior p | Revised p |",
            "| --- | --- | --- | ---: | ---: |",
        ]
    )
    for probe in packet["heldout_probes"]:
        lines.append(
            f"| {probe['relationship']} | {probe['boundary_side']} | "
            f"{probe['candidate_key']} | {float(probe['prior_probability']):.3f} | "
            f"{float(probe['revised_probability']):.3f} |"
        )
    lines.extend(
        [
            "",
            "## Assurance upward search (cached v2 judgments)",
            "",
            "| Order | Case | Probability |",
            "| ---: | --- | ---: |",
        ]
    )
    for index, probe in enumerate(packet["assurance_upward_probes"], start=1):
        lines.append(
            f"| {index} | {probe['candidate_key']} | "
            f"{float(probe['probability']):.3f} |"
        )
    lines.extend(_render_deduplicated_evidence_cases(cases))
    return "\n".join(lines).rstrip() + "\n"


def _render_deduplicated_evidence_cases(
    cases: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    lines = ["", "## Deduplicated evidence cases", ""]
    for candidate_key in sorted(cases):
        case = cases[candidate_key]
        lines.extend(
            [
                f"### {candidate_key} — {case['pastor']['display_name']}",
                "",
                f"- Recording: `{case['youtube_video_id']}` — {case['title']}",
                f"- Time: `{case['start_seconds']}`–`{case['end_seconds']}`",
                "",
                "Leading context:",
                "",
                f"> {str(case['leading_context']).replace(chr(10), ' ')}",
                "",
                "Target text:",
                "",
                f"> {str(case['target_text']).replace(chr(10), ' ')}",
                "",
                "Trailing context:",
                "",
                f"> {str(case['trailing_context']).replace(chr(10), ' ')}",
                "",
            ]
        )
    return lines


def render_salvation_final_calibration(packet: Mapping[str, Any]) -> str:
    cases = {str(item["candidate_key"]): item for item in packet["cases"]}
    lines = [
        "# Salvation final leaf calibration",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Revised leaf pack: `{packet['revised_leaf_pack_version']}`",
        f"- Observation policy: `{packet['observation_policy_version']}`",
        f"- Faith probes: `{len(packet['faith_probes'])}`",
        f"- Repentance probes: `{len(packet['repentance_probes'])}`",
        f"- Unique evidence cases: `{len(packet['cases'])}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "Faith acceptance criterion: the reviewed affirmative anchors must remain "
        "affirmative under the narrowed receiving-faith wording. Review the four "
        "strong prior candidates independently; a high prior score does not pre-approve "
        "them.",
        "",
        "Repentance acceptance criterion: the three reviewed affirmatives must rank "
        "above the three reviewed negatives. Do not repair an ordering failure by "
        "changing the threshold.",
        "",
        "## Faith positive-recall probes",
        "",
        "| Case | Selection | Prior v2 p | Revised p |",
        "| --- | --- | ---: | ---: |",
    ]
    for probe in packet["faith_probes"]:
        lines.append(
            f"| {probe['candidate_key']} | {probe['selection']} | "
            f"{float(probe['prior_probability']):.3f} | "
            f"{float(probe['revised_probability']):.3f} |"
        )
    lines.extend(
        [
            "",
            "## Repentance ordering regressions",
            "",
            "| Case | Reviewed label | Prior v2 p | Revised p |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for probe in packet["repentance_probes"]:
        lines.append(
            f"| {probe['candidate_key']} | {probe['review_label']} | "
            f"{float(probe['v2_probability']):.3f} | "
            f"{float(probe['revised_probability']):.3f} |"
        )
    lines.extend(_render_deduplicated_evidence_cases(cases))
    return "\n".join(lines).rstrip() + "\n"


def render_salvation_v5_calibration(packet: Mapping[str, Any]) -> str:
    cases = {str(item["candidate_key"]): item for item in packet["cases"]}
    lines = [
        "# Salvation v5 causal-boundaries calibration",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Prior leaf pack: `{packet['prior_leaf_pack_version']}`",
        f"- Revised leaf pack: `{packet['revised_leaf_pack_version']}`",
        f"- Reviewed regression probes: `{len(packet['regression_probes'])}`",
        f"- Fresh held-out probes: `{len(packet['heldout_probes'])}`",
        f"- Unique evidence cases: `{len(packet['cases'])}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "Review ordering before thresholds. For each relationship, affirmative "
        "regressions should generally rank above negatives; ambiguous probes do not "
        "establish either side. Then label every fresh held-out probe affirmative, "
        "negative, or ambiguous. Do not change thresholds unless semantic ordering "
        "passes on both regression and held-out evidence.",
    ]
    for relationship in V5_CALIBRATION_RELATIONSHIPS:
        definition = packet["relationship_definitions"][relationship]
        lines.extend(
            [
                "",
                f"## {relationship}",
                "",
                f"**Meaning:** {definition['description']}",
                "",
                f"**Count as yes:** {definition['true_criteria']}",
                "",
                f"**Count as no:** {definition['false_criteria']}",
                "",
                "Unchanged threshold: "
                f"`{float(packet['unchanged_thresholds'][relationship]):.2f}`.",
                "",
                "| Set | Case | Human label / prior side | V4 p | V5 p |",
                "| --- | --- | --- | ---: | ---: |",
            ]
        )
        for probe in packet["regression_probes"]:
            if probe["relationship"] == relationship:
                lines.append(
                    f"| regression | {probe['candidate_key']} | "
                    f"{probe['review_label']} | "
                    f"{float(probe['prior_probability']):.3f} | "
                    f"{float(probe['revised_probability']):.3f} |"
                )
        for probe in packet["heldout_probes"]:
            if probe["relationship"] == relationship:
                lines.append(
                    f"| held_out | {probe['candidate_key']} | "
                    f"{probe['prior_boundary_side']} | "
                    f"{float(probe['prior_probability']):.3f} | "
                    f"{float(probe['revised_probability']):.3f} |"
                )
    lines.extend(_render_deduplicated_evidence_cases(cases))
    return "\n".join(lines).rstrip() + "\n"


def render_salvation_relationship_review(packet: Mapping[str, Any]) -> str:
    lines = [
        "# Salvation relationships review",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Route policy: `{packet['route_policy_version']}`",
        f"- Leaf pack: `{packet['leaf_pack_version']}`",
        f"- Routed cached blocks: `{packet['routed_candidate_count']}`",
        f"- Review cases: `{len(packet['cases'])}`",
        "- Prior review: "
        f"`{packet['prior_review']['input_fingerprint']}` "
        f"(`{len(packet['prior_review']['excluded_candidate_keys'])}` cases excluded)",
        f"- Cache identity: `{packet['cache']['identity']}`",
        f"- Cache location: `{packet['cache']['location']}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "For each case, review whether high-probability relationships are actually "
        "asserted by the target and whether important asserted relationships were "
        "missed. Context may clarify the target but cannot supply the relationship.",
        "",
    ]
    for case in packet["cases"]:
        probabilities = case["leaf_probabilities"]
        lines.extend(
            [
                f"## {case['pastor']['display_name']} / video {case['video_id']} / "
                f"block {case['block_id']} / {case['review_stratum']}",
                "",
                f"- Recording: `{case['youtube_video_id']}` — {case['title']}",
                f"- Time: `{case['start_seconds']}`–`{case['end_seconds']}`",
                "- Broad route probability: "
                f"`{float(case['route']['supporting_or_above_probability']):.3f}`",
                "- Leaf relationships: "
                + ", ".join(
                    f"{name}={float(probability):.3f}"
                    for name, probability in sorted(
                        probabilities.items(),
                        key=lambda item: (-float(item[1]), item[0]),
                    )
                ),
                "",
                "Leading context:",
                "",
                f"> {str(case['leading_context']).replace(chr(10), ' ')}",
                "",
                "Target text:",
                "",
                f"> {str(case['target_text']).replace(chr(10), ' ')}",
                "",
                "Trailing context:",
                "",
                f"> {str(case['trailing_context']).replace(chr(10), ' ')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _write_review_artifact(
    path: Path,
    packet: Mapping[str, Any],
    render: Callable[[Mapping[str, Any]], str],
) -> tuple[Path, Path, bool]:
    json_path = path.expanduser().resolve()
    markdown_path = json_path.with_suffix(".md")
    expected_json = (
        json.dumps(packet, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    expected_markdown = render(packet)
    if json_path.exists() and markdown_path.exists():
        try:
            existing_json = json_path.read_text(encoding="utf-8")
            existing_markdown = markdown_path.read_text(encoding="utf-8")
            existing = json.loads(existing_json)
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing = existing_json = existing_markdown = None
        if (
            isinstance(existing, Mapping)
            and existing.get("input_fingerprint")
            == packet.get("input_fingerprint")
            and existing_json == expected_json
            and existing_markdown == expected_markdown
        ):
            return json_path, markdown_path, True
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(expected_json, encoding="utf-8")
    markdown_path.write_text(expected_markdown, encoding="utf-8")
    return json_path, markdown_path, False


def write_salvation_relationship_review(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    return _write_review_artifact(path, packet, render_salvation_relationship_review)


def write_obedience_consequence_calibration(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    return _write_review_artifact(
        path,
        packet,
        render_obedience_consequence_calibration,
    )


def write_salvation_semantic_calibration(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    return _write_review_artifact(
        path,
        packet,
        render_salvation_semantic_calibration,
    )


def write_salvation_final_calibration(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    return _write_review_artifact(
        path,
        packet,
        render_salvation_final_calibration,
    )


def write_salvation_v5_calibration(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    return _write_review_artifact(
        path,
        packet,
        render_salvation_v5_calibration,
    )
