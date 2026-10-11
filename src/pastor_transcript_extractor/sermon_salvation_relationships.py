"""Versioned routing and TypeSafe questions for salvation relationships."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Mapping

from pastor_transcript_extractor.sermon_topics import (
    topic_supporting_or_above_probability,
    validated_topic_scores,
)


SALVATION_RELATIONSHIPS_PACK_VERSION = (
    "salvation-relationships-v4-repentant-surrender-boundary"
)
SALVATION_ROUTE_POLICY_VERSION = "salvation-route-supporting-mass-v1"
SALVATION_ROUTE_THRESHOLD = 0.55
SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION = (
    "salvation-relationship-observation-thresholds-v2-assurance"
)


@dataclass(frozen=True, slots=True)
class SalvationRelationshipSpec:
    description: str
    true_criteria: str
    false_criteria: str


SALVATION_RELATIONSHIP_SPECS: dict[str, SalvationRelationshipSpec] = {
    "divine_grace_initiative": SalvationRelationshipSpec(
        description=(
            "salvation as originating in God's unearned grace, mercy, initiative, "
            "or gift rather than human earning"
        ),
        true_criteria=(
            "The target explicitly relates salvation or a saving benefit to grace, "
            "mercy, God's initiative or gift, or a contrast with human earning."
        ),
        false_criteria=(
            "The target merely says that God or Jesus forgives, helps, heals, accepts, "
            "or changes someone without asserting unearned grace, mercy, gift, divine "
            "initiative, or a contrast with human earning."
        ),
    ),
    "atonement_as_basis": SalvationRelationshipSpec(
        description=(
            "Christ's death, blood, resurrection, sacrifice, or mediation as a basis "
            "of salvation, reconciliation, forgiveness, or right standing with God"
        ),
        true_criteria=(
            "The target explicitly connects Christ's saving work to salvation, "
            "reconciliation, forgiveness, or right standing with God, or presents "
            "Christ as bearing people's sins, guilt, or penalty in his death."
        ),
        false_criteria=(
            "The target only mentions the cross, death, resurrection, sacrifice, or "
            "Jesus without connecting that work to people's sins or a saving benefit."
        ),
    ),
    "forgiveness_pardon": SalvationRelationshipSpec(
        description=(
            "forgiveness, pardon, cleansing from guilt, or remission of sins as a "
            "saving benefit"
        ),
        true_criteria=(
            "The target meaningfully presents divine forgiveness, pardon, cleansing "
            "from guilt, or remission of sins as part of salvation."
        ),
        false_criteria=(
            "The target mentions interpersonal forgiveness, uses forgiveness only in "
            "passing, or does not develop it as a saving benefit."
        ),
    ),
    "justification_right_standing": SalvationRelationshipSpec(
        description=(
            "justification, credited righteousness, acquittal, acceptance, or right "
            "standing with God as a saving benefit"
        ),
        true_criteria=(
            "The target meaningfully presents people as declared or counted righteous, "
            "credited with righteousness, acquitted, justified, or explicitly placed "
            "in right standing with God."
        ),
        false_criteria=(
            "The target discusses forgiveness, grace, mercy, acceptance, cleansing, "
            "righteous conduct, or salvation apart from works without asserting "
            "acquittal, credited or declared righteousness, or right standing with God."
        ),
    ),
    "conversion_new_birth": SalvationRelationshipSpec(
        description=(
            "conversion, new birth, reconciliation, adoption, or passage from lost to "
            "saved as entry into saving life"
        ),
        true_criteria=(
            "The target meaningfully presents conversion, new birth, reconciliation, "
            "adoption, or movement from lost to saved as entry into saving life."
        ),
        false_criteria=(
            "The target uses conversion figuratively, recounts a changed opinion, or "
            "discusses later growth without asserting entry into saving life."
        ),
    ),
    "sanctification_transformation": SalvationRelationshipSpec(
        description=(
            "sanctification, deliverance from sin, holiness, or transformation as part, "
            "result, or lived experience of God's saving work"
        ),
        true_criteria=(
            "The target explicitly relates holiness, deliverance from sin's power, "
            "cleansing from unrighteousness, or transformed life to salvation or God's "
            "saving work."
        ),
        false_criteria=(
            "The target discusses repentance, surrender, forgiveness, physical or social "
            "healing, generic growth, character, discipline, or obedience without "
            "asserting holiness, deliverance, cleansing, or transformation as saving work."
        ),
    ),
    "assurance_security": SalvationRelationshipSpec(
        description=(
            "assurance, confidence, security, or present certainty concerning salvation "
            "or acceptance by God"
        ),
        true_criteria=(
            "The target meaningfully asserts that salvation or acceptance by God can be "
            "known, trusted, secured, doubted, lost, or retained."
        ),
        false_criteria=(
            "The target expresses generic hope, confidence, or trust without making a "
            "claim about assurance or security of salvation."
        ),
    ),
    "judgment_final_destiny": SalvationRelationshipSpec(
        description=(
            "judgment, condemnation, eternal life, heaven, destruction, or final destiny "
            "as an outcome or dimension of salvation"
        ),
        true_criteria=(
            "The target meaningfully relates judgment or final destiny to being saved, "
            "lost, accepted, condemned, or granted eternal life."
        ),
        false_criteria=(
            "The target merely mentions heaven, judgment, death, or an end-time event "
            "without relating it to salvation or final saving destiny."
        ),
    ),
    "faith_as_receiving_response": SalvationRelationshipSpec(
        description=(
            "faith, belief, or trust as the human response by which salvation or a "
            "saving benefit is received"
        ),
        true_criteria=(
            "The target explicitly presents faith, belief, trust, or an unmistakable "
            "equivalent as the means by which a person receives salvation or a saving "
            "benefit."
        ),
        false_criteria=(
            "The target merely says yes to Jesus, seeks God, follows Jesus, surrenders, "
            "or describes faith, trust, confidence, or loyalty in Christian life after "
            "conversion without making faith or trust the receiving response."
        ),
    ),
    "repentance_as_receiving_response": SalvationRelationshipSpec(
        description=(
            "repentance, confession, turning, or surrender as a human response related "
            "to receiving salvation or a saving benefit"
        ),
        true_criteria=(
            "The target explicitly presents repentance, confession of sin, or turning "
            "from sin toward God as the response by which a person receives salvation, "
            "forgiveness, or restored relationship with God. Surrender or yielding to "
            "God also counts when the target contrasts it with surrender to sin or "
            "explicitly connects it to entering God's kingdom, receiving God's "
            "indwelling presence, or another saving benefit."
        ),
        false_criteria=(
            "The target merely calls for a decision, generic surrender, following Jesus, "
            "honesty, renewed practice, perseverance, or transformation after forgiveness "
            "without presenting repentance, confession, turning from sin, or "
            "salvation-linked surrender as the receiving response."
        ),
    ),
    "obedience_as_condition_or_means": SalvationRelationshipSpec(
        description=(
            "obedience, works, law-keeping, merit, or transformed conduct as a condition, "
            "means, cause, or requirement for obtaining or retaining salvation"
        ),
        true_criteria=(
            "The target explicitly presents obedience, works, law-keeping, merit, or "
            "conduct as a condition, means, cause, or requirement for obtaining or "
            "retaining salvation."
        ),
        false_criteria=(
            "The target merely commands obedience, describes judgment according to deeds, "
            "or presents conduct as fruit or evidence without making it a condition or "
            "means of salvation."
        ),
    ),
    "obedience_as_consequence_or_evidence": SalvationRelationshipSpec(
        description=(
            "obedience, works, holiness, or transformed conduct as a consequence, fruit, "
            "sign, or evidence of salvation rather than its earning cause"
        ),
        true_criteria=(
            "The target explicitly identifies obedience, works, conduct, holiness, or "
            "changed behavior as a result, fruit, sign, or evidence produced by salvation "
            "or grace."
        ),
        false_criteria=(
            "The target merely commands good conduct; describes repentance, surrender, a "
            "decision, conversion, or generic transformation; discusses formation without "
            "salvation; or presents conduct only as a condition or means of salvation."
        ),
    ),
}

SALVATION_RELATIONSHIPS = tuple(SALVATION_RELATIONSHIP_SPECS)
SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS: dict[str, float] = {
    "divine_grace_initiative": 0.65,
    "atonement_as_basis": 0.70,
    "forgiveness_pardon": 0.70,
    "justification_right_standing": 0.70,
    "conversion_new_birth": 0.70,
    "sanctification_transformation": 0.70,
    "assurance_security": 0.62,
    "judgment_final_destiny": 0.65,
    "faith_as_receiving_response": 0.65,
    "repentance_as_receiving_response": 0.70,
    "obedience_as_condition_or_means": 0.70,
    "obedience_as_consequence_or_evidence": 0.55,
}
UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS: frozenset[str] = frozenset()


def salvation_relationship_observation_threshold(
    relationship: str,
) -> float:
    if relationship not in SALVATION_RELATIONSHIP_SPECS:
        raise ValueError(f"Unknown salvation relationship: {relationship}")
    return SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[relationship]


def collected_salvation_relationships(
    probabilities: Mapping[str, Any],
) -> tuple[str, ...]:
    """Apply the frozen per-leaf collection policy to reusable raw judgments."""
    if set(probabilities) != set(SALVATION_RELATIONSHIPS):
        raise ValueError("Salvation relationship probabilities have the wrong inventory")
    collected: list[str] = []
    for relationship in SALVATION_RELATIONSHIPS:
        probability = float(probabilities[relationship])
        if not 0.0 <= probability <= 1.0:
            raise ValueError(
                f"Salvation relationship probability is out of range: {relationship}"
            )
        if probability >= salvation_relationship_observation_threshold(relationship):
            collected.append(relationship)
    return tuple(collected)


def resolve_salvation_relationship_analysis_artifact(
    classification: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return cached relationship evidence from either classifier layout."""
    search = classification.get("search")
    search = search if isinstance(search, Mapping) else {}
    direct = search.get("salvation_relationship_analysis")
    if isinstance(direct, Mapping):
        return direct
    discovery = search.get("discovery")
    discovery = discovery if isinstance(discovery, Mapping) else {}
    attempt = discovery.get("typesafe_first_attempt")
    attempt = attempt if isinstance(attempt, Mapping) else {}
    fallback = attempt.get("salvation_relationship_analysis")
    if isinstance(fallback, Mapping):
        return fallback
    raise ValueError(
        "Classification has no cached TypeSafe salvation relationship analysis"
    )


def refresh_salvation_relationship_projection(
    artifact: dict[str, Any],
    topic_analysis: Mapping[str, Any],
) -> None:
    """Reconcile cached leaf evidence with the final broad-topic projection."""
    raw_topic_blocks = topic_analysis.get("blocks")
    raw_leaf_blocks = artifact.get("blocks")
    if not isinstance(raw_topic_blocks, list) or not isinstance(raw_leaf_blocks, list):
        raise ValueError("Salvation relationship projection artifacts are malformed")
    topic_blocks = {
        int(block["block_id"]): block
        for block in raw_topic_blocks
        if isinstance(block, Mapping) and block.get("block_id") is not None
    }
    current_routes = {
        block_id: salvation_route_decision(block)
        for block_id, block in topic_blocks.items()
    }
    current_routed_ids = {
        block_id for block_id, route in current_routes.items() if route["route"]
    }
    evaluated_ids: set[int] = set()
    active_evaluated_ids: set[int] = set()
    observation_count = 0
    for block in raw_leaf_blocks:
        if not isinstance(block, dict) or block.get("block_id") is None:
            raise ValueError("Salvation relationship leaf block is malformed")
        block_id = int(block["block_id"])
        route = current_routes.get(block_id)
        if route is None:
            raise ValueError(
                f"Salvation relationship block {block_id} has no topic evidence"
            )
        probabilities = block.get("probabilities")
        if not isinstance(probabilities, Mapping):
            raise ValueError(
                f"Salvation relationship block {block_id} has no probabilities"
            )
        collected = collected_salvation_relationships(probabilities)
        block["route"] = route
        block["observations"] = (
            [
                {
                    "relationship": relationship,
                    "probability": round(float(probabilities[relationship]), 6),
                    "threshold": salvation_relationship_observation_threshold(
                        relationship
                    ),
                }
                for relationship in collected
            ]
            if route["route"]
            else []
        )
        evaluated_ids.add(block_id)
        if route["route"]:
            active_evaluated_ids.add(block_id)
            observation_count += len(block["observations"])
    missing = sorted(current_routed_ids - evaluated_ids)
    inactive = sorted(evaluated_ids - current_routed_ids)
    topic_projection = topic_analysis.get("sermon_projection")
    topic_projection = (
        topic_projection if isinstance(topic_projection, Mapping) else {}
    )
    artifact.update(
        {
            "status": (
                "incomplete_current_route_evidence"
                if missing
                else "observations_only"
                if active_evaluated_ids
                else "not_routed"
            ),
            "final_projection_reconciled": True,
            "evaluated_block_count": len(evaluated_ids),
            "routed_block_count": len(active_evaluated_ids),
            "current_routed_block_count": len(current_routed_ids),
            "observation_count": observation_count,
            "missing_current_routed_block_ids": missing,
            "inactive_evaluated_block_ids": inactive,
            "topic_projection_policy_version": topic_projection.get(
                "policy_version"
            ),
            "final_disposition_status": topic_projection.get(
                "final_disposition_status"
            ),
            "window_source": topic_projection.get("window_source"),
        }
    )


def salvation_relationship_question_id(position: int, relationship: str) -> str:
    if relationship not in SALVATION_RELATIONSHIP_SPECS:
        raise ValueError(f"Unknown salvation relationship: {relationship}")
    return f"salvation_relationship_{position}_{relationship}"


def salvation_relationship_question_inventory(
    position: int,
) -> dict[str, dict[str, Any]]:
    target = f"salvation_blocks[{position}].target_text"
    return {
        salvation_relationship_question_id(position, name): {
            "kind": "noul",
            "relationship": name,
            "instructions": {
                "task": f"Decide whether `{target}` meaningfully presents {spec.description}.",
                "evidence_boundary": (
                    f"Only language in `{target}` is evidence. `salvation_blocks["
                    f"{position}].leading_context` and `salvation_blocks[{position}]."
                    "trailing_context` may clarify the target but cannot independently "
                    "establish the relationship."
                ),
                "independence": (
                    "Judge this relationship independently. Several relationships may "
                    "be present, and a nearby theological topic does not establish this one."
                ),
                "artifacts": (
                    "Do not treat a quoted term, rhetorical question, rejected view, "
                    "narrative setup, caption repetition, or general discipleship language "
                    "as an asserted salvation relationship."
                ),
            },
            "criteria": {
                "true": spec.true_criteria,
                "false": spec.false_criteria,
            },
        }
        for name, spec in SALVATION_RELATIONSHIP_SPECS.items()
    }


def salvation_relationship_pack_inventory() -> dict[str, Any]:
    return {
        "version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "relationships": {
            name: asdict(spec)
            for name, spec in SALVATION_RELATIONSHIP_SPECS.items()
        },
    }


def salvation_relationship_pack_digest() -> str:
    encoded = json.dumps(
        salvation_relationship_pack_inventory(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def salvation_route_decision(block: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the reviewed deterministic route to one cached broad-topic block."""
    eligibility = block.get("projection_eligibility")
    eligible = bool(
        isinstance(eligibility, Mapping) and eligibility.get("eligible")
    )
    support = topic_supporting_or_above_probability(
        validated_topic_scores(block)["salvation_gospel"]
    )
    reasons: list[str] = []
    if not eligible:
        reasons.append("projection_ineligible")
    if support < SALVATION_ROUTE_THRESHOLD:
        reasons.append("below_supporting_mass_threshold")
    return {
        "policy_version": SALVATION_ROUTE_POLICY_VERSION,
        "signal": "salvation_gospel_supporting_or_above_probability",
        "threshold": SALVATION_ROUTE_THRESHOLD,
        "supporting_or_above_probability": round(support, 6),
        "eligible": eligible,
        "route": eligible and support >= SALVATION_ROUTE_THRESHOLD,
        "exclusion_reasons": reasons,
    }
