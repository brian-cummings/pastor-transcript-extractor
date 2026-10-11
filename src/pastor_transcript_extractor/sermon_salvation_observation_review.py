"""Provider-free review of collected salvation relationship observations."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIPS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
    SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES,
    UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS,
    collected_salvation_relationships,
    refresh_salvation_relationship_projection,
    resolve_salvation_relationship_analysis_artifact,
    salvation_relationship_pack_inventory,
)
from pastor_transcript_extractor.sermon_topic_profile_analysis import (
    read_classification_for_gate,
)
from pastor_transcript_extractor.sermon_topic_projection import (
    assess_topic_profile_projection,
)
from pastor_transcript_extractor.sermon_topic_stage4 import (
    assess_topic_stage4_readiness,
)
from pastor_transcript_extractor.sermon_topics import resolve_topic_analysis_artifact
from pastor_transcript_extractor.storage import Database


SALVATION_COLLECTED_OBSERVATION_REVIEW_SCHEMA_VERSION = 2
SALVATION_COLLECTED_OBSERVATION_REVIEW_POLICY_VERSION = (
    "salvation-collected-observation-boundaries-v2-deduplicated-evidence"
)
DEFAULT_SALVATION_COLLECTED_OBSERVATION_REVIEW_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-collected-observations-review-v2.json"
)
DEFAULT_SALVATION_CONVERSION_RECALIBRATION_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-conversion-recalibration-v1.json"
)
SALVATION_CONVERSION_RECALIBRATION_SCHEMA_VERSION = 1
SALVATION_CONVERSION_RECALIBRATION_POLICY_VERSION = (
    "salvation-conversion-local-ordering-recalibration-v1"
)
SALVATION_CONVERSION_RECALIBRATION_SOURCE_PACK_VERSION = (
    "salvation-relationships-v7-repentance-response-context"
)
SALVATION_CONVERSION_RECALIBRATION_WINDOW = (0.45, 0.65)
SALVATION_CONVERSION_RECALIBRATION_ANCHORS = {
    "590:34:conversion_new_birth": "affirmative_rejected",
    "350:42:conversion_new_birth": "negative_collected",
}
SALVATION_CONVERSION_WATCH_FIXTURES = {
    "350:36:divine_grace_initiative": "false_positive_watch",
    "350:61:atonement_as_basis": "affirmative_miss_watch",
    "4458:72:sanctification_transformation": "affirmative_miss_watch",
    "4394:51:judgment_final_destiny": "false_positive_borderline_watch",
    "590:35:faith_as_receiving_response": "affirmative_miss_watch",
    "4394:50:obedience_as_consequence_or_evidence": "false_positive_watch",
}
SALVATION_COLLECTION_RECALIBRATION_SCHEMA_VERSION = 1
SALVATION_COLLECTION_RECALIBRATION_POLICY_VERSION = (
    "salvation-collection-four-leaf-recalibration-v1"
)
DEFAULT_SALVATION_COLLECTION_RECALIBRATION_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-collection-recalibration-v1.json"
)
SALVATION_BOUNDARY_RECALIBRATION_SCHEMA_VERSION = 1
SALVATION_BOUNDARY_RECALIBRATION_POLICY_VERSION = (
    "salvation-four-leaf-boundary-recalibration-v1"
)
DEFAULT_SALVATION_BOUNDARY_RECALIBRATION_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-boundary-recalibration-v1.json"
)
SALVATION_FINAL_COLLECTION_CHECK_POLICY_VERSION = (
    "salvation-final-collection-boundary-check-v1"
)
DEFAULT_SALVATION_FINAL_COLLECTION_CHECK_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-final-collection-check-v1.json"
)
SALVATION_FINAL_COLLECTION_CHECK_RELATIONSHIPS = (
    "conversion_new_birth",
    "forgiveness_pardon",
    "assurance_security",
    "repentance_as_receiving_response",
)
SALVATION_FINAL_COLLECTION_CHECK_ANCHORS = {
    "4394:45:repentance_as_receiving_response": "affirmative_rejected",
    "350:50:repentance_as_receiving_response": "negative_collected",
    "350:46:conversion_new_birth": "appropriate_rejection",
    "4394:51:conversion_new_birth": "questionable_collected",
    "4430:44:forgiveness_pardon": "affirmative_rejected",
    "350:41:forgiveness_pardon": "affirmative_collected",
    "4458:69:assurance_security": "affirmative_rejected",
    "1037:58:assurance_security": "affirmative_collected",
}
SALVATION_FINAL_COLLECTION_NUMERIC_WINDOWS = {
    "conversion_new_birth": (0.54, 0.58),
    "forgiveness_pardon": (0.68, 0.70),
    "assurance_security": (0.61, 0.62),
}
SALVATION_BOUNDARY_RECALIBRATION_RELATIONSHIPS = (
    "divine_grace_initiative",
    "conversion_new_birth",
    "obedience_as_condition_or_means",
    "obedience_as_consequence_or_evidence",
)
SALVATION_BOUNDARY_RECALIBRATION_ANCHORS = {
    "590:43:divine_grace_initiative": "affirmative_rejected",
    "4430:47:divine_grace_initiative": "questionable_collected",
    "4394:50:conversion_new_birth": "affirmative_rejected",
    "281:124:conversion_new_birth": "questionable_collected",
    "1037:58:obedience_as_condition_or_means": "questionable_rejected",
    "3973:99:obedience_as_condition_or_means": "questionable_collected",
    "4589:47:obedience_as_consequence_or_evidence": "affirmative_rejected",
    "4589:40:obedience_as_consequence_or_evidence": "questionable_collected",
}
SALVATION_JUDGMENT_WATCH_KEY = "4589:51:judgment_final_destiny"
SALVATION_COLLECTION_RECALIBRATION_RELATIONSHIPS = (
    "assurance_security",
    "faith_as_receiving_response",
    "repentance_as_receiving_response",
    "obedience_as_consequence_or_evidence",
)
SALVATION_COLLECTION_REVIEWED_ANCHORS: dict[str, dict[str, str]] = {
    "4589:25:assurance_security": {
        "verdict": "appropriate_rejection",
        "reason": "Power over sin is not assurance or security of salvation.",
    },
    "4052:100:assurance_security": {
        "verdict": "false_positive",
        "reason": "Experiencing gospel power is not assurance of salvation.",
    },
    "4458:70:faith_as_receiving_response": {
        "verdict": "appropriate_rejection",
        "reason": "The target does not relate faith to receiving a saving benefit.",
    },
    "4589:42:faith_as_receiving_response": {
        "verdict": "false_positive",
        "reason": "Faith in lived discipleship is not faith as a receiving response.",
    },
    "4589:48:repentance_as_receiving_response": {
        "verdict": "material_false_negative",
        "reason": "Submission and surrender are related to receiving Christ's righteousness.",
    },
    "350:61:repentance_as_receiving_response": {
        "verdict": "false_positive",
        "reason": (
            "The target asks about the cost of forgiveness but does not assert "
            "repentance as the receiving response."
        ),
    },
    "4430:48:obedience_as_consequence_or_evidence": {
        "verdict": "appropriate_rejection",
        "reason": (
            "Repentance and surrender are not themselves obedient conduct as fruit "
            "or evidence."
        ),
    },
    "4430:21:obedience_as_consequence_or_evidence": {
        "verdict": "false_positive",
        "reason": "Repentance as a result of forgiveness is not obedience or transformed conduct.",
    },
}

_CASE_FIELDS = (
    "pastor",
    "video_id",
    "youtube_video_id",
    "title",
    "block_id",
    "start_seconds",
    "end_seconds",
    "leading_context",
    "target_text",
    "trailing_context",
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


def _deduplicate_review_probes(
    selected_probes: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cases_by_key: dict[str, dict[str, Any]] = {}
    probes: list[dict[str, Any]] = []
    for raw_probe in selected_probes:
        probe = dict(raw_probe)
        case_key = f"{int(probe['video_id'])}:{int(probe['block_id'])}"
        case = {field: probe[field] for field in _CASE_FIELDS}
        previous = cases_by_key.setdefault(case_key, case)
        if previous != case:
            raise ValueError(f"Conflicting salvation review case: {case_key}")
        probes.append(
            {
                key: value
                for key, value in probe.items()
                if key not in _CASE_FIELDS
            }
            | {"case_key": case_key}
        )
    cases = [
        {"case_key": case_key, **case}
        for case_key, case in sorted(
            cases_by_key.items(),
            key=lambda item: (
                int(item[1]["video_id"]),
                int(item[1]["block_id"]),
            ),
        )
    ]
    return cases, probes


def _source_artifact_fingerprints(
    sources: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "video_id": int(source["video_id"]),
            "stored_artifact_sha256": str(
                source.get("stored_artifact_sha256")
                or _canonical_hash(source["artifact"])
            ),
            "effective_artifact_sha256": _canonical_hash(source["artifact"]),
        }
        for source in sources
    ]


def _validated_source_judgments(
    source: Mapping[str, Any],
) -> list[dict[str, Any]]:
    artifact = source.get("artifact")
    if not isinstance(artifact, Mapping):
        raise ValueError("Salvation relationship source artifact is malformed")
    if artifact.get("question_pack_version") != SALVATION_RELATIONSHIPS_PACK_VERSION:
        raise ValueError(
            f"Video {source['video_id']} uses a different relationship question pack"
        )
    if (
        artifact.get("observation_policy_version")
        != SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
    ):
        raise ValueError(
            f"Video {source['video_id']} uses a different observation policy"
        )
    if artifact.get("final_projection_reconciled") is not True:
        raise ValueError(
            f"Video {source['video_id']} relationship evidence is not reconciled "
            "to the final sermon projection"
        )
    missing_routes = artifact.get("missing_current_routed_block_ids")
    if missing_routes not in ([], ()):
        raise ValueError(
            f"Video {source['video_id']} is missing relationship evidence for "
            f"current routed blocks: {missing_routes}"
        )
    raw_thresholds = artifact.get("observation_thresholds")
    if raw_thresholds != SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS:
        raise ValueError(
            f"Video {source['video_id']} has inconsistent observation thresholds"
        )
    if artifact.get("measurement_statuses") != SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES:
        raise ValueError(
            f"Video {source['video_id']} has inconsistent relationship measurement statuses"
        )
    if artifact.get("projection_excluded_relationships") != sorted(
        UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS
    ):
        raise ValueError(
            f"Video {source['video_id']} has inconsistent projection exclusions"
        )
    raw_blocks = artifact.get("blocks")
    if not isinstance(raw_blocks, list):
        raise ValueError(f"Video {source['video_id']} has malformed relationship blocks")
    judgments: list[dict[str, Any]] = []
    for block in raw_blocks:
        if not isinstance(block, Mapping):
            raise ValueError(
                f"Video {source['video_id']} has a malformed relationship block"
            )
        probabilities = block.get("probabilities")
        if not isinstance(probabilities, Mapping):
            raise ValueError(
                f"Video {source['video_id']} block {block.get('block_id')} has the "
                "wrong relationship inventory"
            )
        raw_observations = block.get("observations")
        if not isinstance(raw_observations, list):
            raise ValueError(
                f"Video {source['video_id']} block {block.get('block_id')} has "
                "malformed collected observations"
            )
        stored = {
            str(item.get("relationship"))
            for item in raw_observations
            if isinstance(item, Mapping)
        }
        try:
            expected = set(collected_salvation_relationships(probabilities))
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Video {source['video_id']} block {block.get('block_id')} has "
                "invalid relationship probabilities"
            ) from error
        if stored != expected:
            raise ValueError(
                f"Video {source['video_id']} block {block.get('block_id')} has "
                "observations inconsistent with the frozen threshold policy"
            )
        context = block.get("context")
        context = context if isinstance(context, Mapping) else {}
        target = context.get("target_text")
        if not isinstance(target, str) or not target.strip():
            raise ValueError(
                f"Video {source['video_id']} block {block.get('block_id')} has no "
                "relationship target text"
            )
        for relationship in SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS:
            probability = round(float(probabilities[relationship]), 6)
            judgments.append(
                {
                    "judgment_key": (
                        f"{int(source['video_id'])}:{int(block['block_id'])}:"
                        f"{relationship}"
                    ),
                    "relationship": relationship,
                    "probability": probability,
                    "threshold": (
                        SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[relationship]
                    ),
                    "collected": relationship in expected,
                    "pastor": dict(source["pastor"]),
                    "video_id": int(source["video_id"]),
                    "youtube_video_id": str(source["youtube_video_id"]),
                    "title": str(source["title"]),
                    "block_id": int(block["block_id"]),
                    "start_seconds": float(block["start_seconds"]),
                    "end_seconds": float(block["end_seconds"]),
                    "leading_context": str(context.get("leading_context") or ""),
                    "target_text": target,
                    "trailing_context": str(context.get("trailing_context") or ""),
                }
            )
    return judgments


def build_salvation_collected_observations_review(
    sources: Sequence[Mapping[str, Any]],
    *,
    cohort_sha256: str | None,
    readiness_input_fingerprint: str,
) -> dict[str, Any]:
    """Select the closest collected and rejected judgment for every leaf."""
    judgments = [
        judgment
        for source in sources
        for judgment in _validated_source_judgments(source)
    ]
    if not judgments:
        raise ValueError("No routed salvation relationship blocks are available")
    selected_probes: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {}
    for relationship in SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS:
        candidates = [
            item for item in judgments if item["relationship"] == relationship
        ]
        collected = [item for item in candidates if item["collected"]]
        rejected = [item for item in candidates if not item["collected"]]
        counts[relationship] = {
            "collected": len(collected),
            "rejected": len(rejected),
        }
        if rejected:
            selected_probes.append(
                {
                    **max(
                        rejected,
                        key=lambda item: (
                            float(item["probability"]),
                            str(item["judgment_key"]),
                        ),
                    ),
                    "boundary_side": "strongest_rejected",
                }
            )
        if collected:
            selected_probes.append(
                {
                    **min(
                        collected,
                        key=lambda item: (
                            float(item["probability"]),
                            str(item["judgment_key"]),
                        ),
                    ),
                    "boundary_side": "weakest_collected",
                }
            )
    cases, probes = _deduplicate_review_probes(selected_probes)
    source_fingerprints = _source_artifact_fingerprints(sources)
    identity = {
        "schema_version": SALVATION_COLLECTED_OBSERVATION_REVIEW_SCHEMA_VERSION,
        "review_policy_version": (
            SALVATION_COLLECTED_OBSERVATION_REVIEW_POLICY_VERSION
        ),
        "cohort_sha256": cohort_sha256,
        "readiness_input_fingerprint": readiness_input_fingerprint,
        "question_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "observation_policy_version": (
            SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
        ),
        "observation_thresholds": dict(
            SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS
        ),
        "measurement_statuses": dict(SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES),
        "projection_excluded_relationships": sorted(
            UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS
        ),
        "relationship_definitions": {
            relationship: salvation_relationship_pack_inventory()["relationships"][
                relationship
            ]
            for relationship in SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS
        },
        "source_artifacts": source_fingerprints,
        "source_video_count": len(sources),
        "routed_block_count": len(judgments)
        // len(SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS),
        "judgment_count": len(judgments),
        "counts_by_relationship": counts,
        "cases": cases,
        "probes": probes,
    }
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "collected_observations_pending_review",
        "policy_effect": "none",
        "interpretation": (
            "This provider-free packet checks the actual ordinary-classification "
            "observation layer. It verifies every stored observation against the "
            "frozen per-leaf policy, then shows the strongest rejected and weakest "
            "collected judgment for each relationship. It does not alter inference, "
            "thresholds, or profile claims."
        ),
    }


def _select_nearest_diverse_judgments(
    candidates: Sequence[Mapping[str, Any]],
    *,
    count: int,
) -> list[dict[str, Any]]:
    ordered = sorted(
        (dict(item) for item in candidates),
        key=lambda item: (
            abs(float(item["probability"]) - float(item["threshold"])),
            str(item["judgment_key"]),
        ),
    )
    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    represented_pastors: set[str] = set()
    for require_new_pastor in (True, False):
        for item in ordered:
            key = str(item["judgment_key"])
            pastor = str(item["pastor"].get("display_name") or "")
            if key in selected_keys:
                continue
            if require_new_pastor and pastor in represented_pastors:
                continue
            selected.append(item)
            selected_keys.add(key)
            represented_pastors.add(pastor)
            if len(selected) == count:
                return selected
    raise ValueError(
        f"Salvation recalibration requires {count} fresh judgments on each side"
    )


def build_salvation_conversion_recalibration(
    sources: Sequence[Mapping[str, Any]],
    *,
    cohort_sha256: str | None,
    readiness_input_fingerprint: str,
    prior_review: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a provider-free conversion-only ordering check from cached judgments."""
    if (
        SALVATION_RELATIONSHIPS_PACK_VERSION
        != SALVATION_CONVERSION_RECALIBRATION_SOURCE_PACK_VERSION
    ):
        raise ValueError(
            "Conversion-only recalibration is archived after the v8 semantic revision"
        )
    if (
        prior_review.get("review_policy_version")
        != SALVATION_COLLECTED_OBSERVATION_REVIEW_POLICY_VERSION
        or prior_review.get("question_pack_version")
        != SALVATION_CONVERSION_RECALIBRATION_SOURCE_PACK_VERSION
        or prior_review.get("observation_policy_version")
        != SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
    ):
        raise ValueError("Conversion recalibration requires the current collection review")
    if prior_review.get("source_artifacts") != _source_artifact_fingerprints(sources):
        raise ValueError("Conversion recalibration inputs changed after collection review")

    judgments = [
        judgment
        for source in sources
        for judgment in _validated_source_judgments(source)
    ]
    by_key = {str(item["judgment_key"]): item for item in judgments}
    required_keys = set(SALVATION_CONVERSION_RECALIBRATION_ANCHORS) | set(
        SALVATION_CONVERSION_WATCH_FIXTURES
    )
    missing = sorted(required_keys - set(by_key))
    if missing:
        raise ValueError(
            "Conversion recalibration is missing required fixtures: "
            + ", ".join(missing)
        )

    from pastor_transcript_extractor.sermon_salvation_relationship_review import (
        ALL_REVIEWED_CANDIDATE_KEYS,
        RECALIBRATION_REVIEWED_CANDIDATE_KEYS,
    )

    excluded_case_keys = set(ALL_REVIEWED_CANDIDATE_KEYS) | set(
        RECALIBRATION_REVIEWED_CANDIDATE_KEYS
    )
    excluded_case_keys.update(
        str(case.get("case_key"))
        for case in prior_review.get("cases", [])
        if isinstance(case, Mapping)
    )
    excluded_case_keys.update(
        key.rsplit(":", 1)[0]
        for key in SALVATION_CONVERSION_RECALIBRATION_ANCHORS
    )
    relationship = "conversion_new_birth"
    threshold = SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[relationship]
    lower, upper = SALVATION_CONVERSION_RECALIBRATION_WINDOW
    fresh_candidates = [
        item
        for item in judgments
        if item["relationship"] == relationship
        and lower <= float(item["probability"]) <= upper
        and str(item["judgment_key"]).rsplit(":", 1)[0]
        not in excluded_case_keys
    ]
    fresh: list[dict[str, Any]] = []
    for side, predicate in (
        ("below", lambda value: value < threshold),
        ("at_or_above", lambda value: value >= threshold),
    ):
        selected = _select_nearest_diverse_judgments(
            [item for item in fresh_candidates if predicate(float(item["probability"]))],
            count=4,
        )
        fresh.extend(
            {
                **item,
                "probe_role": "fresh_cached_neighbor",
                "boundary_side": side,
            }
            for item in selected
        )
    anchors = [
        {
            **by_key[key],
            "probe_role": "reviewed_ordering_anchor",
            "review_label": label,
        }
        for key, label in SALVATION_CONVERSION_RECALIBRATION_ANCHORS.items()
    ]
    watches = [
        {
            **by_key[key],
            "probe_role": "frozen_leaf_watch_only",
            "review_label": label,
        }
        for key, label in SALVATION_CONVERSION_WATCH_FIXTURES.items()
    ]
    cases, probes = _deduplicate_review_probes([*anchors, *fresh, *watches])
    identity = {
        "schema_version": SALVATION_CONVERSION_RECALIBRATION_SCHEMA_VERSION,
        "review_policy_version": SALVATION_CONVERSION_RECALIBRATION_POLICY_VERSION,
        "cohort_sha256": cohort_sha256,
        "readiness_input_fingerprint": readiness_input_fingerprint,
        "prior_review_fingerprint": prior_review.get("input_fingerprint"),
        "question_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "observation_policy_version": SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
        "relationship": relationship,
        "current_threshold": threshold,
        "review_window": list(SALVATION_CONVERSION_RECALIBRATION_WINDOW),
        "relationship_definition": salvation_relationship_pack_inventory()[
            "relationships"
        ][relationship],
        "regression_anchors": dict(SALVATION_CONVERSION_RECALIBRATION_ANCHORS),
        "frozen_watch_fixtures": dict(SALVATION_CONVERSION_WATCH_FIXTURES),
        "frozen_relationships": sorted(
            set(SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS) - {relationship}
        ),
        "excluded_reviewed_case_keys": sorted(excluded_case_keys),
        "judgment_count": len(judgments),
        "source_artifacts": _source_artifact_fingerprints(sources),
        "cases": cases,
        "probes": probes,
        "provider_requests": 0,
    }
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "bounded_recalibration_required_conversion_only",
        "policy_effect": "none",
        "interpretation": (
            "Only conversion_new_birth is reopened. The current 0.55 threshold and "
            "all question definitions remain unchanged. Two reviewed ordering anchors "
            "are shown with eight fresh cached neighbors, four on each policy side. "
            "The other ten validated leaves are frozen; their isolated errors are "
            "watch fixtures and cannot authorize changes in this packet."
        ),
    }


def build_salvation_collection_recalibration(
    sources: Sequence[Mapping[str, Any]],
    *,
    cohort_sha256: str | None,
    readiness_input_fingerprint: str,
    prior_review: Mapping[str, Any],
) -> dict[str, Any]:
    """Select fresh cached boundary probes only for the four unsettled leaves."""
    if UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS.intersection(
        SALVATION_COLLECTION_RECALIBRATION_RELATIONSHIPS
    ):
        raise ValueError(
            "Salvation collection recalibration is archived after repentance was "
            "excluded from observation projection"
        )
    if (
        prior_review.get("review_policy_version")
        != SALVATION_COLLECTED_OBSERVATION_REVIEW_POLICY_VERSION
    ):
        raise ValueError("Prior salvation collection review has the wrong policy")
    prior_review_fingerprint = prior_review.get("input_fingerprint")
    if not isinstance(prior_review_fingerprint, str):
        raise ValueError("Prior salvation collection review has no fingerprint")
    current_source_artifacts = _source_artifact_fingerprints(sources)
    if prior_review.get("source_artifacts") != current_source_artifacts:
        raise ValueError(
            "Prior salvation collection review does not match current artifacts"
        )
    prior_probe_keys = {
        str(probe.get("judgment_key"))
        for probe in prior_review.get("probes", [])
        if isinstance(probe, Mapping)
    }
    if not set(SALVATION_COLLECTION_REVIEWED_ANCHORS).issubset(prior_probe_keys):
        raise ValueError("Prior salvation collection review lacks reviewed anchors")
    judgments = [
        judgment
        for source in sources
        for judgment in _validated_source_judgments(source)
    ]
    reviewed_keys = set(SALVATION_COLLECTION_REVIEWED_ANCHORS)
    selected: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {}
    for relationship in SALVATION_COLLECTION_RECALIBRATION_RELATIONSHIPS:
        candidates = [
            item
            for item in judgments
            if item["relationship"] == relationship
            and item["judgment_key"] not in reviewed_keys
        ]
        rejected = [item for item in candidates if not item["collected"]]
        collected = [item for item in candidates if item["collected"]]
        side_count = 3 if relationship == "repentance_as_receiving_response" else 2
        counts[relationship] = {
            "fresh_collected_available": len(collected),
            "fresh_rejected_available": len(rejected),
            "selected_per_side": side_count,
        }
        for boundary_side, side_candidates in (
            ("fresh_rejected", rejected),
            ("fresh_collected", collected),
        ):
            for rank, item in enumerate(
                _select_nearest_diverse_judgments(
                    side_candidates,
                    count=side_count,
                ),
                start=1,
            ):
                selected.append(
                    {
                        **item,
                        "boundary_side": boundary_side,
                        "side_rank": rank,
                        "distance_from_current_threshold": round(
                            abs(
                                float(item["probability"])
                                - float(item["threshold"])
                            ),
                            6,
                        ),
                    }
                )
    cases, probes = _deduplicate_review_probes(selected)
    identity = {
        "schema_version": SALVATION_COLLECTION_RECALIBRATION_SCHEMA_VERSION,
        "review_policy_version": SALVATION_COLLECTION_RECALIBRATION_POLICY_VERSION,
        "cohort_sha256": cohort_sha256,
        "readiness_input_fingerprint": readiness_input_fingerprint,
        "prior_review_fingerprint": prior_review_fingerprint,
        "question_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "observation_policy_version": (
            SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
        ),
        "current_thresholds": {
            relationship: SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[
                relationship
            ]
            for relationship in SALVATION_COLLECTION_RECALIBRATION_RELATIONSHIPS
        },
        "relationship_definitions": {
            relationship: salvation_relationship_pack_inventory()["relationships"][
                relationship
            ]
            for relationship in SALVATION_COLLECTION_RECALIBRATION_RELATIONSHIPS
        },
        "reviewed_anchors": dict(SALVATION_COLLECTION_REVIEWED_ANCHORS),
        "settled_relationships": [
            relationship
            for relationship in SALVATION_RELATIONSHIPS
            if relationship not in SALVATION_COLLECTION_RECALIBRATION_RELATIONSHIPS
        ],
        "watch_fixtures": {
            "sanctification_transformation": {
                "judgment_key": "4589:50:sanctification_transformation",
                "probability": 0.69,
                "verdict": "material_false_negative_watch",
                "policy_change": "none",
            }
        },
        "selection_counts": counts,
        "source_artifacts": current_source_artifacts,
        "source_video_count": len(sources),
        "judgment_count": len(judgments),
        "cases": cases,
        "probes": probes,
    }
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "four_leaf_recalibration_pending_review",
        "policy_effect": "none",
        "interpretation": (
            "This provider-free follow-up freezes the eight clean relationship "
            "boundaries, retains the sanctification boundary with one watch fixture, "
            "and presents fresh cached judgments only for the four unsettled leaves. "
            "It changes no questions, thresholds, observations, or profile claims."
        ),
    }


def build_salvation_boundary_recalibration(
    sources: Sequence[Mapping[str, Any]],
    *,
    cohort_sha256: str | None,
    readiness_input_fingerprint: str,
    prior_review: Mapping[str, Any],
) -> dict[str, Any]:
    """Select current cached anchors and fresh probes for four disputed leaves."""
    if (
        prior_review.get("review_policy_version")
        != SALVATION_COLLECTED_OBSERVATION_REVIEW_POLICY_VERSION
    ):
        raise ValueError("Prior salvation collection review has the wrong policy")
    prior_fingerprint = prior_review.get("input_fingerprint")
    if not isinstance(prior_fingerprint, str):
        raise ValueError("Prior salvation collection review has no fingerprint")
    current_sources = _source_artifact_fingerprints(sources)
    if prior_review.get("source_artifacts") != current_sources:
        raise ValueError(
            "Prior salvation collection review does not match current artifacts"
        )
    prior_probe_keys = {
        str(probe.get("judgment_key"))
        for probe in prior_review.get("probes", [])
        if isinstance(probe, Mapping)
    }
    required = set(SALVATION_BOUNDARY_RECALIBRATION_ANCHORS) | {
        SALVATION_JUDGMENT_WATCH_KEY
    }
    if not required.issubset(prior_probe_keys):
        raise ValueError(
            "Prior salvation collection review lacks required boundary anchors"
        )
    judgments = [
        judgment
        for source in sources
        for judgment in _validated_source_judgments(source)
    ]
    by_key = {str(item["judgment_key"]): item for item in judgments}
    missing = sorted(required - set(by_key))
    if missing:
        raise ValueError(
            "Current salvation evidence lacks required boundary anchors: "
            + ", ".join(missing)
        )
    selected: list[dict[str, Any]] = []
    for judgment_key, review_label in (
        SALVATION_BOUNDARY_RECALIBRATION_ANCHORS.items()
    ):
        selected.append(
            {
                **by_key[judgment_key],
                "probe_role": "reviewed_boundary_anchor",
                "review_label": review_label,
            }
        )
    fresh_counts: dict[str, dict[str, int]] = {}
    for relationship in SALVATION_BOUNDARY_RECALIBRATION_RELATIONSHIPS:
        candidates = [
            item
            for item in judgments
            if item["relationship"] == relationship
            and item["judgment_key"] not in prior_probe_keys
        ]
        rejected = [item for item in candidates if not item["collected"]]
        collected = [item for item in candidates if item["collected"]]
        fresh_counts[relationship] = {
            "rejected_available": len(rejected),
            "collected_available": len(collected),
            "selected_per_side": 2,
        }
        for boundary_side, side_candidates in (
            ("fresh_rejected", rejected),
            ("fresh_collected", collected),
        ):
            for side_rank, item in enumerate(
                _select_nearest_diverse_judgments(side_candidates, count=2),
                start=1,
            ):
                selected.append(
                    {
                        **item,
                        "probe_role": "fresh_probability_neighbor",
                        "boundary_side": boundary_side,
                        "side_rank": side_rank,
                        "distance_from_current_threshold": round(
                            abs(
                                float(item["probability"])
                                - float(item["threshold"])
                            ),
                            6,
                        ),
                    }
                )
    selected.append(
        {
            **by_key[SALVATION_JUDGMENT_WATCH_KEY],
            "probe_role": "watch_only",
            "review_label": "likely_affirmative_rejected",
        }
    )
    cases, probes = _deduplicate_review_probes(selected)
    identity = {
        "schema_version": SALVATION_BOUNDARY_RECALIBRATION_SCHEMA_VERSION,
        "review_policy_version": SALVATION_BOUNDARY_RECALIBRATION_POLICY_VERSION,
        "cohort_sha256": cohort_sha256,
        "readiness_input_fingerprint": readiness_input_fingerprint,
        "prior_review_fingerprint": prior_fingerprint,
        "question_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "observation_policy_version": (
            SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
        ),
        "unchanged_thresholds": {
            relationship: SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[
                relationship
            ]
            for relationship in (
                *SALVATION_BOUNDARY_RECALIBRATION_RELATIONSHIPS,
                "judgment_final_destiny",
            )
        },
        "relationship_definitions": {
            relationship: salvation_relationship_pack_inventory()["relationships"][
                relationship
            ]
            for relationship in (
                *SALVATION_BOUNDARY_RECALIBRATION_RELATIONSHIPS,
                "judgment_final_destiny",
            )
        },
        "reviewed_boundary_anchors": dict(
            SALVATION_BOUNDARY_RECALIBRATION_ANCHORS
        ),
        "judgment_watch_key": SALVATION_JUDGMENT_WATCH_KEY,
        "fresh_selection_counts": fresh_counts,
        "source_artifacts": current_sources,
        "source_video_count": len(sources),
        "judgment_count": len(judgments),
        "cases": cases,
        "probes": probes,
    }
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "four_leaf_boundary_calibration_pending_review",
        "policy_effect": "none",
        "interpretation": (
            "This provider-free packet keeps every v4 question and final threshold "
            "unchanged. It combines eight disputed ordinary-classification boundary "
            "anchors with four fresh cached probability neighbors per affected leaf. "
            "Judgment/final-destiny is included as one watch-only probe and cannot "
            "authorize a policy change by itself."
        ),
    }


def _select_probability_window(
    candidates: Sequence[Mapping[str, Any]],
    *,
    low: float,
    high: float,
    limit: int = 8,
) -> list[dict[str, Any]]:
    ordered = sorted(
        (
            dict(item)
            for item in candidates
            if low <= float(item["probability"]) <= high
        ),
        key=lambda item: (float(item["probability"]), str(item["judgment_key"])),
    )
    if len(ordered) <= limit:
        return ordered
    indexes = [round(index * (len(ordered) - 1) / (limit - 1)) for index in range(limit)]
    return [ordered[index] for index in indexes]


def build_salvation_final_collection_check(
    sources: Sequence[Mapping[str, Any]],
    *,
    cohort_sha256: str | None,
    readiness_input_fingerprint: str,
    prior_review: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one final provider-free check for four localized boundaries."""
    if UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS.intersection(
        SALVATION_FINAL_COLLECTION_CHECK_RELATIONSHIPS
    ):
        raise ValueError(
            "Salvation final collection check is archived after repentance was "
            "excluded from observation projection"
        )
    if (
        prior_review.get("review_policy_version")
        != SALVATION_COLLECTED_OBSERVATION_REVIEW_POLICY_VERSION
    ):
        raise ValueError("Prior salvation collection review has the wrong policy")
    prior_fingerprint = prior_review.get("input_fingerprint")
    if not isinstance(prior_fingerprint, str):
        raise ValueError("Prior salvation collection review has no fingerprint")
    current_sources = _source_artifact_fingerprints(sources)
    if prior_review.get("source_artifacts") != current_sources:
        raise ValueError(
            "Prior salvation collection review does not match current artifacts"
        )
    prior_probe_keys = {
        str(probe.get("judgment_key"))
        for probe in prior_review.get("probes", [])
        if isinstance(probe, Mapping)
    }
    if not set(SALVATION_FINAL_COLLECTION_CHECK_ANCHORS).issubset(prior_probe_keys):
        raise ValueError("Prior salvation collection review lacks final-check anchors")
    judgments = [
        judgment
        for source in sources
        for judgment in _validated_source_judgments(source)
    ]
    by_key = {str(item["judgment_key"]): item for item in judgments}
    missing = sorted(set(SALVATION_FINAL_COLLECTION_CHECK_ANCHORS) - set(by_key))
    if missing:
        raise ValueError(
            "Current salvation evidence lacks final-check anchors: "
            + ", ".join(missing)
        )

    selected: list[dict[str, Any]] = [
        {
            **by_key[judgment_key],
            "probe_role": "reviewed_boundary_anchor",
            "review_label": review_label,
        }
        for judgment_key, review_label in (
            SALVATION_FINAL_COLLECTION_CHECK_ANCHORS.items()
        )
    ]
    selection_counts: dict[str, dict[str, int]] = {}
    for relationship, (low, high) in SALVATION_FINAL_COLLECTION_NUMERIC_WINDOWS.items():
        candidates = [
            item
            for item in judgments
            if item["relationship"] == relationship
            and item["judgment_key"] not in prior_probe_keys
        ]
        in_window = [
            item
            for item in candidates
            if low <= float(item["probability"]) <= high
        ]
        chosen = _select_probability_window(
            candidates,
            low=low,
            high=high,
        )
        selection_counts[relationship] = {
            "available_in_window": len(in_window),
            "selected_in_window": len(chosen),
        }
        selected.extend(
            {
                **item,
                "probe_role": "fresh_numeric_window",
                "review_window": [low, high],
            }
            for item in chosen
        )

    repentance = "repentance_as_receiving_response"
    repentance_candidates = [
        item
        for item in judgments
        if item["relationship"] == repentance
        and item["judgment_key"] not in prior_probe_keys
    ]
    repentance_counts = {
        "fresh_rejected_available": sum(
            not bool(item["collected"]) for item in repentance_candidates
        ),
        "fresh_collected_available": sum(
            bool(item["collected"]) for item in repentance_candidates
        ),
        "selected_per_side": 3,
    }
    for boundary_side, side_candidates in (
        (
            "fresh_rejected",
            [item for item in repentance_candidates if not item["collected"]],
        ),
        (
            "fresh_collected",
            [item for item in repentance_candidates if item["collected"]],
        ),
    ):
        for side_rank, item in enumerate(
            _select_nearest_diverse_judgments(side_candidates, count=3),
            start=1,
        ):
            selected.append(
                {
                    **item,
                    "probe_role": "fresh_semantic_neighbor",
                    "boundary_side": boundary_side,
                    "side_rank": side_rank,
                }
            )

    cases, probes = _deduplicate_review_probes(selected)
    identity = {
        "schema_version": 1,
        "review_policy_version": SALVATION_FINAL_COLLECTION_CHECK_POLICY_VERSION,
        "cohort_sha256": cohort_sha256,
        "readiness_input_fingerprint": readiness_input_fingerprint,
        "prior_review_fingerprint": prior_fingerprint,
        "question_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "observation_policy_version": (
            SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
        ),
        "current_thresholds": {
            relationship: SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[
                relationship
            ]
            for relationship in SALVATION_FINAL_COLLECTION_CHECK_RELATIONSHIPS
        },
        "relationship_definitions": {
            relationship: salvation_relationship_pack_inventory()["relationships"][
                relationship
            ]
            for relationship in SALVATION_FINAL_COLLECTION_CHECK_RELATIONSHIPS
        },
        "reviewed_anchors": dict(SALVATION_FINAL_COLLECTION_CHECK_ANCHORS),
        "numeric_windows": {
            relationship: list(window)
            for relationship, window in (
                SALVATION_FINAL_COLLECTION_NUMERIC_WINDOWS.items()
            )
        },
        "selection_counts": selection_counts,
        "repentance_selection_counts": repentance_counts,
        "frozen_relationships": [
            relationship
            for relationship in SALVATION_RELATIONSHIPS
            if relationship not in SALVATION_FINAL_COLLECTION_CHECK_RELATIONSHIPS
        ],
        "watch_fixtures": {
            "justification_right_standing": "4589:48",
            "sanctification_transformation": "3973:75",
            "obedience_as_consequence_or_evidence": "4430:47",
        },
        "source_artifacts": current_sources,
        "source_video_count": len(sources),
        "judgment_count": len(judgments),
        "cases": cases,
        "probes": probes,
    }
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "final_collection_boundary_check_pending_review",
        "policy_effect": "none",
        "provider_requests": 0,
        "interpretation": (
            "This final provider-free check keeps eight relationships frozen. It "
            "tests repentance semantic ordering on two reviewed anchors plus six "
            "fresh neighbors, and tests only numeric boundaries for conversion, "
            "forgiveness, and assurance in their named narrow windows."
        ),
    }


def _load_salvation_observation_sources(
    database: Database,
    cohort: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], Mapping[str, Any]]:
    if readiness is None:
        readiness = assess_topic_stage4_readiness(database, cohort)
    if not readiness["ready"]:
        raise ValueError(
            "Salvation observation review requires ready Stage 4 inputs: "
            + ", ".join(readiness["blockers"])
        )
    videos = {video.id: video for video in database.list_videos()}
    sources: list[dict[str, Any]] = []
    missing: list[int] = []
    for pastor in cohort["pastors"]:
        for sermon in pastor["sermons"]:
            video_id = int(sermon["video_id"])
            video = videos.get(video_id)
            if video is None:
                raise ValueError(f"Unknown salvation observation video: {video_id}")
            gate = assess_topic_profile_projection(database, video)
            if not gate.eligible:
                raise ValueError(
                    f"Video {video_id} is not eligible for salvation observation review"
                )
            classification = read_classification_for_gate(gate)
            try:
                stored_artifact = resolve_salvation_relationship_analysis_artifact(
                    classification
                )
                topic_analysis = resolve_topic_analysis_artifact(classification)
            except ValueError:
                missing.append(video_id)
                continue
            artifact = deepcopy(dict(stored_artifact))
            refresh_salvation_relationship_projection(
                artifact,
                topic_analysis,
            )
            sources.append(
                {
                    "pastor": {
                        "display_name": pastor.get("display_name"),
                        "pastor_id": pastor.get("pastor_id"),
                        "slug": pastor.get("slug"),
                    },
                    "video_id": video_id,
                    "youtube_video_id": video.youtube_video_id,
                    "title": video.title,
                    "artifact": artifact,
                    "stored_artifact_sha256": _canonical_hash(stored_artifact),
                }
            )
    if missing:
        raise ValueError(
            "Cohort classifications have no current salvation relationship analysis: "
            + ", ".join(str(video_id) for video_id in missing)
        )
    return sources, readiness


def evaluate_salvation_collected_observations_review(
    database: Database,
    cohort: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    sources, readiness = _load_salvation_observation_sources(
        database,
        cohort,
        readiness=readiness,
    )
    return build_salvation_collected_observations_review(
        sources,
        cohort_sha256=(
            str(cohort["cohort_sha256"])
            if cohort.get("cohort_sha256") is not None
            else None
        ),
        readiness_input_fingerprint=str(readiness["input_fingerprint"]),
    )


def evaluate_salvation_conversion_recalibration(
    database: Database,
    cohort: Mapping[str, Any],
    prior_review: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    sources, readiness = _load_salvation_observation_sources(
        database,
        cohort,
        readiness=readiness,
    )
    return build_salvation_conversion_recalibration(
        sources,
        cohort_sha256=(
            str(cohort["cohort_sha256"])
            if cohort.get("cohort_sha256") is not None
            else None
        ),
        readiness_input_fingerprint=str(readiness["input_fingerprint"]),
        prior_review=prior_review,
    )


def load_salvation_collected_observations_review(
    path: Path,
) -> Mapping[str, Any]:
    try:
        value = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read prior salvation collection review: {path}") from error
    if not isinstance(value, Mapping):
        raise ValueError("Prior salvation collection review must be a JSON object")
    return value


def evaluate_salvation_collection_recalibration(
    database: Database,
    cohort: Mapping[str, Any],
    prior_review: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    sources, readiness = _load_salvation_observation_sources(
        database,
        cohort,
        readiness=readiness,
    )
    return build_salvation_collection_recalibration(
        sources,
        cohort_sha256=(
            str(cohort["cohort_sha256"])
            if cohort.get("cohort_sha256") is not None
            else None
        ),
        readiness_input_fingerprint=str(readiness["input_fingerprint"]),
        prior_review=prior_review,
    )


def evaluate_salvation_boundary_recalibration(
    database: Database,
    cohort: Mapping[str, Any],
    prior_review: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    sources, readiness = _load_salvation_observation_sources(
        database,
        cohort,
        readiness=readiness,
    )
    return build_salvation_boundary_recalibration(
        sources,
        cohort_sha256=(
            str(cohort["cohort_sha256"])
            if cohort.get("cohort_sha256") is not None
            else None
        ),
        readiness_input_fingerprint=str(readiness["input_fingerprint"]),
        prior_review=prior_review,
    )


def evaluate_salvation_final_collection_check(
    database: Database,
    cohort: Mapping[str, Any],
    prior_review: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    sources, readiness = _load_salvation_observation_sources(
        database,
        cohort,
        readiness=readiness,
    )
    return build_salvation_final_collection_check(
        sources,
        cohort_sha256=(
            str(cohort["cohort_sha256"])
            if cohort.get("cohort_sha256") is not None
            else None
        ),
        readiness_input_fingerprint=str(readiness["input_fingerprint"]),
        prior_review=prior_review,
    )


def render_salvation_collected_observations_review(
    packet: Mapping[str, Any],
) -> str:
    lines = [
        "# Salvation collected observations review",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Question pack: `{packet['question_pack_version']}`",
        f"- Observation policy: `{packet['observation_policy_version']}`",
        f"- Source videos: `{packet['source_video_count']}`",
        f"- Routed blocks: `{packet['routed_block_count']}`",
        f"- Raw judgments: `{packet['judgment_count']}`",
        f"- Boundary probes: `{len(packet['probes'])}`",
        f"- Unique evidence cases: `{len(packet['cases'])}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "Review whether each weakest collected judgment is a useful affirmative "
        "observation and whether each strongest rejected judgment reveals a material "
        "miss. Context may clarify the target but cannot independently establish the "
        "relationship.",
        "",
        "Each probability is the Noul probability that the named yes/no relationship "
        "is asserted; it is not the intensity of the doctrine and has no separate "
        "confidence score. Apply the relationship-specific true/false boundary below "
        "to the target text, using adjacent context only for clarification.",
        "",
        "## How to return the review",
        "",
        "For every `weakest_collected` probe, say whether it is a useful affirmative "
        "observation or a false positive. For every `strongest_rejected` probe, say "
        "whether rejection is appropriate or loses a material affirmative observation. "
        "Then give one overall verdict: approve the frozen collection policy, or name "
        "the specific relationship boundary that needs another bounded calibration. "
        "Do not infer a sermon-level or pastor-level theological claim from this packet.",
        "",
        "## Collection counts",
        "",
        "| Relationship | Threshold | Collected | Rejected |",
        "| --- | ---: | ---: | ---: |",
    ]
    cases_by_key = {
        str(case["case_key"]): case for case in packet["cases"]
    }
    for relationship in SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS:
        counts = packet["counts_by_relationship"][relationship]
        lines.append(
            f"| {relationship} | "
            f"{float(packet['observation_thresholds'][relationship]):.2f} | "
            f"{counts['collected']} | {counts['rejected']} |"
        )
    for relationship in SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS:
        definition = packet["relationship_definitions"][relationship]
        counts = packet["counts_by_relationship"][relationship]
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
                f"Collection threshold: "
                f"`{float(packet['observation_thresholds'][relationship]):.2f}`; "
                f"collected: `{counts['collected']}`; rejected: "
                f"`{counts['rejected']}`.",
                "",
            ]
        )
        for probe in packet["probes"]:
            if probe["relationship"] != relationship:
                continue
            case = cases_by_key[str(probe["case_key"])]
            lines.extend(
                [
                    f"### {probe['boundary_side']} / "
                    f"{float(probe['probability']):.3f}",
                    "",
                    f"- Threshold: `{float(probe['threshold']):.2f}`",
                    f"- Evidence case: `{probe['case_key']}` — "
                    f"{case['pastor']['display_name']}",
                    f"- Recording: `{case['youtube_video_id']}` — {case['title']}",
                    f"- Time: `{case['start_seconds']}`–`{case['end_seconds']}`",
                    "",
                ]
            )
    lines.extend(["", "## Deduplicated evidence cases", ""])
    for case in packet["cases"]:
        lines.extend(
            [
                f"### {case['case_key']} — {case['pastor']['display_name']}",
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
    return "\n".join(lines).rstrip() + "\n"


def write_salvation_collected_observations_review(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    return _write_review_packet(
        path,
        packet,
        render_salvation_collected_observations_review,
    )


def render_salvation_conversion_recalibration(packet: Mapping[str, Any]) -> str:
    definition = packet["relationship_definition"]
    cases = {str(case["case_key"]): case for case in packet["cases"]}
    lines = [
        "# Salvation conversion-only recalibration",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Prior review: `{packet['prior_review_fingerprint']}`",
        f"- Current threshold: `{float(packet['current_threshold']):.2f}`",
        f"- Review window: `{packet['review_window'][0]:.2f}`–"
        f"`{packet['review_window'][1]:.2f}`",
        f"- Cached raw judgments: `{packet['judgment_count']}`",
        f"- Provider requests: `{packet['provider_requests']}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        f"**Meaning:** {definition['description']}",
        "",
        f"**Count as yes:** {definition['true_criteria']}",
        "",
        f"**Count as no:** {definition['false_criteria']}",
        "",
        "Label only the eight fresh conversion probes affirmative, negative, or "
        "ambiguous. Decide whether they reproduce a systematic semantic ordering "
        "failure around 0.55. Do not change the threshold from the two anchors alone. "
        "The watch-only probes document isolated errors in frozen leaves and cannot "
        "authorize changes here.",
        "",
        "## Probes",
        "",
        "| Case | Relationship | Role | Probability | Prior label / side |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for probe in packet["probes"]:
        detail = str(
            probe.get("review_label") or probe.get("boundary_side") or "—"
        )
        lines.append(
            f"| {probe['case_key']} | {probe['relationship']} | "
            f"{probe['probe_role']} | {float(probe['probability']):.3f} | "
            f"{detail} |"
        )
    lines.extend(["", "## Deduplicated evidence cases", ""])
    for case_key in sorted(
        cases,
        key=lambda value: tuple(int(part) for part in value.split(":")),
    ):
        case = cases[case_key]
        lines.extend(
            [
                f"### {case_key} — {case['pastor']['display_name']}",
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
    return "\n".join(lines).rstrip() + "\n"


def write_salvation_conversion_recalibration(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    return _write_review_packet(
        path,
        packet,
        render_salvation_conversion_recalibration,
    )


def render_salvation_final_collection_check(packet: Mapping[str, Any]) -> str:
    cases = {str(case["case_key"]): case for case in packet["cases"]}
    lines = [
        "# Salvation final collection boundary check",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Prior review: `{packet['prior_review_fingerprint']}`",
        f"- Question pack: `{packet['question_pack_version']}`",
        f"- Observation policy: `{packet['observation_policy_version']}`",
        f"- Cached raw judgments: `{packet['judgment_count']}`",
        f"- Review probes: `{len(packet['probes'])}`",
        f"- Unique evidence cases: `{len(packet['cases'])}`",
        f"- Provider requests: `{packet['provider_requests']}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "Label every probe affirmative, negative, or ambiguous for its named leaf. "
        "For repentance, decide whether the fresh cases reproduce the semantic "
        "ordering defect; do not choose a threshold across a confirmed inversion. "
        "For conversion, forgiveness, and assurance, keep the frozen wording and "
        "recommend only a numeric boundary. Do not reopen the eight frozen leaves "
        "or infer pastor-level theology.",
        "",
        "Frozen relationships: "
        + ", ".join(f"`{item}`" for item in packet["frozen_relationships"])
        + ".",
        "",
        "Watch only: justification `4589:48`, sanctification `3973:75`, and "
        "obedience-consequence `4430:47`. These cannot authorize changes here.",
    ]
    for relationship in SALVATION_FINAL_COLLECTION_CHECK_RELATIONSHIPS:
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
                "Current threshold: "
                f"`{float(packet['current_thresholds'][relationship]):.2f}`.",
                "",
                "| Case | Role | Probability | Prior label / selection |",
                "| --- | --- | ---: | --- |",
            ]
        )
        for probe in packet["probes"]:
            if probe["relationship"] != relationship:
                continue
            detail = str(
                probe.get("review_label")
                or probe.get("boundary_side")
                or probe.get("review_window")
                or "fresh"
            )
            lines.append(
                f"| {probe['case_key']} | {probe['probe_role']} | "
                f"{float(probe['probability']):.3f} | {detail} |"
            )
    lines.extend(["", "## Deduplicated evidence cases", ""])
    for case_key in sorted(
        cases,
        key=lambda value: tuple(int(part) for part in value.split(":")),
    ):
        case = cases[case_key]
        lines.extend(
            [
                f"### {case_key} — {case['pastor']['display_name']}",
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
    return "\n".join(lines).rstrip() + "\n"


def write_salvation_final_collection_check(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    return _write_review_packet(
        path,
        packet,
        render_salvation_final_collection_check,
    )


def _write_review_packet(
    path: Path,
    packet: Mapping[str, Any],
    renderer: Callable[[Mapping[str, Any]], str],
) -> tuple[Path, Path, bool]:
    json_path = path.expanduser().resolve()
    markdown_path = json_path.with_suffix(".md")
    expected_json = (
        json.dumps(packet, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    expected_markdown = renderer(packet)
    if json_path.exists() and markdown_path.exists():
        try:
            existing_json = json_path.read_text(encoding="utf-8")
            existing_markdown = markdown_path.read_text(encoding="utf-8")
            existing = json.loads(existing_json)
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing = existing_json = existing_markdown = None
        if (
            isinstance(existing, Mapping)
            and existing.get("input_fingerprint") == packet.get("input_fingerprint")
            and existing_json == expected_json
            and existing_markdown == expected_markdown
        ):
            return json_path, markdown_path, True
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(expected_json, encoding="utf-8")
    markdown_path.write_text(expected_markdown, encoding="utf-8")
    return json_path, markdown_path, False


def render_salvation_collection_recalibration(
    packet: Mapping[str, Any],
) -> str:
    lines = [
        "# Salvation collection four-leaf recalibration",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Prior review: `{packet['prior_review_fingerprint']}`",
        f"- Question pack: `{packet['question_pack_version']}`",
        f"- Cached raw judgments: `{packet['judgment_count']}`",
        f"- Fresh probes: `{len(packet['probes'])}`",
        f"- Unique evidence cases: `{len(packet['cases'])}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "Each probability is the Noul probability of yes for one relationship. "
        "It is not doctrinal intensity and has no separate confidence score. "
        "Judge the target text; use adjacent context only to clarify it.",
        "",
        "## Review request",
        "",
        "For every fresh probe, label the target a useful affirmative observation "
        "or a negative for that relationship. Then, for each of the four leaves, "
        "recommend exactly one outcome: keep the current boundary, change only the "
        "numeric boundary, or revise the evidence wording. Repentance has a reviewed "
        "0.69 affirmative below a reviewed 0.71 negative, so explicitly say whether "
        "the fresh cases confirm a semantic-ordering defect. Do not revisit the eight "
        "settled leaves or infer sermon- or pastor-level theology.",
        "",
        "## Settled and watch-only leaves",
        "",
        "Frozen from the prior ordinary-classification review: "
        + ", ".join(f"`{item}`" for item in packet["settled_relationships"])
        + ".",
        "",
        "Sanctification remains at `0.70`; `4589:50` at `0.69` is retained as a "
        "material false-negative watch fixture, not a policy change.",
        "",
        "## Reviewed boundary anchors",
        "",
        "| Judgment | Verdict | Reason |",
        "| --- | --- | --- |",
    ]
    for judgment_key, review in packet["reviewed_anchors"].items():
        lines.append(
            f"| `{judgment_key}` | `{review['verdict']}` | {review['reason']} |"
        )
    cases_by_key = {
        str(case["case_key"]): case for case in packet["cases"]
    }
    for relationship in SALVATION_COLLECTION_RECALIBRATION_RELATIONSHIPS:
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
                f"Current threshold: "
                f"`{float(packet['current_thresholds'][relationship]):.2f}`.",
                "",
            ]
        )
        for probe in packet["probes"]:
            if probe["relationship"] != relationship:
                continue
            case = cases_by_key[str(probe["case_key"])]
            lines.extend(
                [
                    f"### {probe['boundary_side']} {probe['side_rank']} / "
                    f"{float(probe['probability']):.3f}",
                    "",
                    f"- Evidence case: `{probe['case_key']}` — "
                    f"{case['pastor']['display_name']}",
                    f"- Recording: `{case['youtube_video_id']}` — {case['title']}",
                    f"- Time: `{case['start_seconds']}`–`{case['end_seconds']}`",
                    "",
                ]
            )
    lines.extend(["", "## Deduplicated evidence cases", ""])
    for case in packet["cases"]:
        lines.extend(
            [
                f"### {case['case_key']} — {case['pastor']['display_name']}",
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
    return "\n".join(lines).rstrip() + "\n"


def write_salvation_collection_recalibration(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    return _write_review_packet(
        path,
        packet,
        render_salvation_collection_recalibration,
    )


def render_salvation_boundary_recalibration(
    packet: Mapping[str, Any],
) -> str:
    cases = {str(case["case_key"]): case for case in packet["cases"]}
    lines = [
        "# Salvation four-leaf boundary recalibration",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Prior review: `{packet['prior_review_fingerprint']}`",
        f"- Question pack: `{packet['question_pack_version']}`",
        f"- Observation policy: `{packet['observation_policy_version']}`",
        f"- Cached raw judgments: `{packet['judgment_count']}`",
        f"- Probes: `{len(packet['probes'])}`",
        f"- Unique evidence cases: `{len(packet['cases'])}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "For each affected leaf, review the two named boundary anchors and four fresh "
        "neighbors. Decide whether the evidence shows a semantic-ordering defect, a "
        "numeric-boundary issue, or no material problem. Do not change a threshold "
        "merely to collect both sides of an ordering inversion.",
        "",
        "The final-destiny case is watch-only. It may justify another bounded sample, "
        "but this packet alone cannot change that question or threshold.",
    ]
    for relationship in SALVATION_BOUNDARY_RECALIBRATION_RELATIONSHIPS:
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
                "Current threshold: "
                f"`{float(packet['unchanged_thresholds'][relationship]):.2f}`.",
                "",
            ]
        )
        for probe in packet["probes"]:
            if probe["relationship"] != relationship:
                continue
            case = cases[str(probe["case_key"])]
            role = str(probe["probe_role"])
            detail = str(
                probe.get("review_label")
                or f"{probe.get('boundary_side')} {probe.get('side_rank')}"
            )
            lines.extend(
                [
                    f"### {role} / {detail} / {float(probe['probability']):.3f}",
                    "",
                    f"- Evidence case: `{probe['case_key']}` — "
                    f"{case['pastor']['display_name']}",
                    f"- Recording: `{case['youtube_video_id']}` — {case['title']}",
                    f"- Time: `{case['start_seconds']}`–`{case['end_seconds']}`",
                    "",
                ]
            )
    watch = next(
        probe for probe in packet["probes"] if probe["probe_role"] == "watch_only"
    )
    watch_case = cases[str(watch["case_key"])]
    watch_definition = packet["relationship_definitions"][
        "judgment_final_destiny"
    ]
    lines.extend(
        [
            "",
            "## judgment_final_destiny — watch only",
            "",
            f"**Meaning:** {watch_definition['description']}",
            "",
            f"**Count as yes:** {watch_definition['true_criteria']}",
            "",
            f"**Count as no:** {watch_definition['false_criteria']}",
            "",
            f"### {float(watch['probability']):.3f} / {watch['case_key']}",
            "",
            f"- Pastor: {watch_case['pastor']['display_name']}",
            f"- Recording: `{watch_case['youtube_video_id']}` — {watch_case['title']}",
            f"- Time: `{watch_case['start_seconds']}`–`{watch_case['end_seconds']}`",
            "",
            "## Deduplicated evidence cases",
            "",
        ]
    )
    for case in packet["cases"]:
        lines.extend(
            [
                f"### {case['case_key']} — {case['pastor']['display_name']}",
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
    return "\n".join(lines).rstrip() + "\n"


def write_salvation_boundary_recalibration(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    return _write_review_packet(
        path,
        packet,
        render_salvation_boundary_recalibration,
    )
