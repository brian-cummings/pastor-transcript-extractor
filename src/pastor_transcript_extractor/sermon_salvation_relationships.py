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


SALVATION_RELATIONSHIPS_PACK_VERSION = "salvation-relationships-v1"
SALVATION_ROUTE_POLICY_VERSION = "salvation-route-supporting-mass-v1"
SALVATION_ROUTE_THRESHOLD = 0.55


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
            "The target explicitly relates salvation or a saving benefit to God's "
            "unearned grace, mercy, initiative, or gift."
        ),
        false_criteria=(
            "The target merely mentions God, grace, mercy, or a gift; attributes "
            "general help or growth to God; or does not assert this saving relationship."
        ),
    ),
    "atonement_as_basis": SalvationRelationshipSpec(
        description=(
            "Christ's death, blood, resurrection, sacrifice, or mediation as a basis "
            "of salvation, reconciliation, forgiveness, or right standing with God"
        ),
        true_criteria=(
            "The target explicitly connects Christ's saving work to salvation, "
            "reconciliation, forgiveness, or right standing with God."
        ),
        false_criteria=(
            "The target only mentions the cross, death, resurrection, sacrifice, or "
            "Jesus without asserting that saving relationship."
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
            "The target meaningfully presents justification, credited righteousness, "
            "acquittal, acceptance, or right standing with God."
        ),
        false_criteria=(
            "The target discusses moral conduct, righteousness as character, or divine "
            "approval without asserting right standing as a saving benefit."
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
            "The target explicitly relates holiness, deliverance from sin, or transformed "
            "life to salvation or God's saving work."
        ),
        false_criteria=(
            "The target discusses generic growth, character, discipline, or obedience "
            "without relating it to salvation or saving work."
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
            "The target explicitly relates faith, belief, or trust to receiving salvation "
            "or a saving benefit."
        ),
        false_criteria=(
            "The target discusses faith or trust as general discipleship, confidence, or "
            "loyalty without relating it to receiving salvation."
        ),
    ),
    "repentance_as_receiving_response": SalvationRelationshipSpec(
        description=(
            "repentance, confession, turning, or surrender as a human response related "
            "to receiving salvation or a saving benefit"
        ),
        true_criteria=(
            "The target explicitly relates repentance, confession, turning, or surrender "
            "to receiving salvation, forgiveness, or restored relationship with God."
        ),
        false_criteria=(
            "The target calls for generic change, surrender, honesty, or renewed practice "
            "without relating that response to a saving benefit."
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
            "The target explicitly presents obedience, works, holiness, or transformed "
            "conduct as a result, fruit, sign, or evidence of salvation or grace."
        ),
        false_criteria=(
            "The target merely commands good conduct, discusses formation without "
            "salvation, or presents conduct only as a condition or means of salvation."
        ),
    ),
}

SALVATION_RELATIONSHIPS = tuple(SALVATION_RELATIONSHIP_SPECS)


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
