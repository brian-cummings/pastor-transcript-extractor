"""Reusable independent Noul leaf contracts; routing and thresholds stay in code."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Any, Mapping


@dataclass(frozen=True)
class NoulLeafPack:
    version: str
    state_key: str
    question_prefix: str
    definitions: Mapping[str, str]
    boundary: str
    task_template: str = "Does the preacher ask the listener to {definition} in `{target}`?"
    positive_template: str = "A listener-directed appeal, invitation, recommendation, or obligation to {definition}. {boundary}"
    negative_criteria: str = (
        "Description, narrative, an unendorsed quotation, a rejected instruction, "
        "or a rhetorical question with no endorsed listener response. A theological "
        "claim or topic alone does not request an action. Context-only requests do not count."
    )
    evidence_subject: str = "directive"
    missing_evidence: str = "request"
    independence: str = "Judge each action independently; several may be requested."

    def question_id(self, position: int, leaf: str) -> str:
        if leaf not in self.definitions:
            raise ValueError(f"Unknown leaf: {leaf}")
        return f"{self.question_prefix}_{position}_{leaf}"

    def questions(self, position: int) -> dict[str, dict[str, Any]]:
        target = f"{self.state_key}[{position}].target_text"
        return {
            self.question_id(position, leaf): {
                "kind": "noul",
                "instructions": {
                    "task": self.task_template.format(definition=definition, target=target),
                    "evidence_boundary": (
                        f"Only `{target}` establishes a {self.evidence_subject}. Leading and trailing "
                        f"context may resolve references but cannot supply a missing {self.missing_evidence}."
                    ),
                    "independence": self.independence,
                },
                "criteria": {
                    "true": self.positive_template.format(definition=definition, boundary=self.boundary),
                    "false": self.negative_criteria,
                },
            }
            for leaf, definition in self.definitions.items()
        }

    def digest(self) -> str:
        # Complete provider-visible question semantics participate, not just labels.
        return hashlib.sha256(json.dumps(self.questions(0), sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()

    def validate(self, probabilities: Mapping[str, Any]) -> None:
        if set(probabilities) != set(self.definitions):
            raise ValueError("Leaf probabilities have the wrong inventory")
        for value in probabilities.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Leaf probability must be numeric")
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Leaf probability is out of range")


LISTENER_DIRECTIVES_V1 = NoulLeafPack(
    version="listener-directives-v1-target-appeals",
    state_key="listener_directive_blocks",
    question_prefix="listener_directive",
    definitions={
        "trust": "trust, believe, rely on, or entrust oneself to God or Christ; general assent to a fact alone is excluded",
        "repent": "repent, confess personal sin to God, or turn from sin toward God; no saving-means relationship is implied",
        "change_behavior": "change a concrete moral habit, conduct, or treatment of others; trust, repentance, and religious activities alone are insufficient",
        "spiritual_practice": "pray, study Scripture, fast, meditate, or undertake a personal devotional practice; corporate participation alone is excluded",
        "witness": "share faith, proclaim the gospel, testify about God, or invite someone to faith; general kindness alone is excluded",
        "serve": "help, care for, or meet another person's needs through action; donating alone is excluded",
        "give": "donate money, possessions, or material resources, including tithes and offerings; giving one's heart or time alone is excluded",
        "participate": "join or take part in church, corporate worship, baptism, fellowship, or a communal ministry; private devotion alone is excluded",
        "civic_action": "vote, contact officials, advocate public policy, protest, or take another concrete civic action; discussing public affairs alone is excluded",
    },
    boundary=(
        "An inclusive 'we should' or an endorsed biblical command explicitly applied to today's "
        "listeners counts. A rhetorical question counts only when it functions as a clear appeal. "
        "A request inside the preacher's prayer to God alone is not a request to the listener. "
        "Count overlapping actions only when each is requested. Do not infer salvation conditions, "
        "theological stance, actual compliance, or the preacher's personal behavior."
    ),
)

V2_REVISED_DIRECTIVE_LEAVES = ("change_behavior", "give", "serve")
LISTENER_DIRECTIVES_V2 = replace(
    LISTENER_DIRECTIVES_V1,
    version="listener-directives-v2-conduct-donation-care",
    definitions={
        **LISTENER_DIRECTIVES_V1.definitions,
        "change_behavior": (
            "cease or start a specific personal moral conduct or habit, such as stop lying, "
            "stop cheating, stop retaliating, or speak honestly. Exclude requests whose "
            "action is solely trusting, repenting, donating, providing care, joining or "
            "participating, witnessing, practicing devotion, or taking civic action; these "
            "are separate directives. A request to do one of those actions does not also "
            "count as personal conduct change merely because it changes what a person does"
        ),
        "give": (
            "make a financial or material donation, such as contribute money, tithe, "
            "give an offering, or donate possessions or supplies to a recipient or fund. "
            "Exclude personally providing care or practical help, such as bringing a meal "
            "to a sick neighbor or cleaning their home, unless a distinct donation is "
            "also requested. Giving one's heart or time is excluded"
        ),
        "serve": (
            "personally provide direct help, care, or practical assistance to another "
            "person, such as bring a meal to a sick neighbor, clean their home, visit "
            "someone lonely, or meet their needs through personal action. Exclude merely "
            "donating resources or joining an organized activity or volunteer team. "
            "Joining counts as participation alone unless the target also asks for "
            "direct help or care; independently requested care still counts when it "
            "occurs within an organized ministry"
        ),
    },
)
# A focused rerun evaluates only changed semantics. Unchanged answers remain reusable.
LISTENER_DIRECTIVE_REFINEMENT_V2 = replace(
    LISTENER_DIRECTIVES_V2,
    version="listener-directives-v2-three-leaf-refinement",
    definitions={leaf: LISTENER_DIRECTIVES_V2.definitions[leaf] for leaf in V2_REVISED_DIRECTIVE_LEAVES},
)

REVISED_DIRECTIVE_LEAVES = ("serve",)
LISTENER_DIRECTIVES = replace(
    LISTENER_DIRECTIVES_V2,
    version="listener-directives-v3-help-people-in-need",
    definitions={
        **LISTENER_DIRECTIVES_V2.definitions,
        "serve": (
            "help, care for, meet the needs of, or make a beneficial impact on people "
            "in need. This includes an explicit appeal to help or impact people with "
            "material, social, or spiritual needs, including a world in need of the "
            "gospel; a concrete care task such as meals or cleaning is not required. "
            "Exclude merely donating resources, joining an organization or volunteer "
            "team, participating, praying, or sharing faith. Do not infer service from "
            "those actions alone. Service may coexist with them only when the target "
            "also explicitly calls listeners to help or beneficially impact people "
            "in need. Personally bringing a meal, cleaning a sick neighbor's home, "
            "or visiting someone lonely remains service"
        ),
    },
)
LISTENER_DIRECTIVE_REFINEMENT = replace(
    LISTENER_DIRECTIVES,
    version="listener-directives-v3-serve-only-refinement",
    definitions={leaf: LISTENER_DIRECTIVES.definitions[leaf] for leaf in REVISED_DIRECTIVE_LEAVES},
)

PUBLIC_LIFE_TREATMENT_V1 = NoulLeafPack(
    version="public-life-treatment-v1-target-attribution",
    state_key="public_life_blocks", question_prefix="public_life_treatment",
    definitions={
        "descriptive": "develops a factual or historical account of public events, institutions, actors, or processes; mere naming or an evaluative conclusion alone is insufficient",
        "illustrative": "uses public events, institutions, or civic examples as an illustration or analogy to explain another point; a public-life reference without an illustrative function is insufficient",
        "theological": "explicitly interprets public affairs in relation to God, Scripture, divine authority, or a theological principle; nearby religious language alone is insufficient",
        "moral": "explicitly evaluates public conduct, institutions, or policy in terms of moral right or wrong, justice, human dignity, or ethical responsibility; private personal conduct and pragmatic effectiveness alone are excluded",
        "critical": "expresses the preacher's own negative evaluation of a public actor, institution, policy, or civic practice; narrated conflict, another person's criticism, and rejected accusations alone are excluded",
        "supportive": "expresses the preacher's own approval, endorsement, or commendation of a public actor, institution, policy, or civic practice; neutral description and another person's praise alone are excluded",
        "prescriptive": "recommends a specific public policy, rule, or how government or society ought to act; merely reporting existing rules or giving private discipleship advice is excluded",
        "advocative": "urges listeners to support, oppose, campaign for, or take concrete civic action concerning a public actor, policy, institution, or civic practice; abstract policy recommendations and mentioning public affairs alone are excluded",
    },
    task_template="Does the preacher's treatment of public life in `{target}` {definition}?",
    positive_template="The target {definition}. {boundary}",
    negative_criteria=(
        "No developed public-life treatment of this kind is established in the target. "
        "Exclude private conduct alone, passing civic vocabulary, or context-only evidence. "
        "For evaluation and advocacy, an unendorsed quotation or a rejected view is not "
        "the preacher's position. A narrated event may be descriptive or illustrative "
        "without endorsing the actors or actions."
    ),
    evidence_subject="public-life treatment",
    independence="Judge this treatment independently. Several treatments may coexist, even with different public objects; do not force a single stance.",
    boundary=(
        "Public life includes government, policy, politics, nations, civic institutions, "
        "social structures, church-state relations, and religious liberty. Ground the "
        "treatment in target language and distinguish the preacher's framing from "
        "reported speakers. Do not infer partisan identity, a pastor-level stance, or "
        "listener advocacy from historical description or theological co-occurrence."
    ),
)

PUBLIC_REVISED_LEAVES = ("descriptive", "prescriptive")
PUBLIC_LIFE_TREATMENT = replace(
    PUBLIC_LIFE_TREATMENT_V1,
    version="public-life-treatment-v2-reporting-prescription-boundaries",
    definitions={
        **PUBLIC_LIFE_TREATMENT_V1.definitions,
        "descriptive": (
            "reports or explains public events, institutions, actors, processes, or "
            "what another public actor said, did, or believes. Reporting another "
            "actor's praise, criticism, or position is descriptive information even "
            "when the preacher explicitly withholds endorsement. An informative "
            "report need not be lengthy. Mere naming and the preacher's isolated "
            "evaluative conclusion alone are insufficient"
        ),
        "prescriptive": (
            "explicitly specifies what a government, public institution, church in "
            "its public role, public actor, law, policy, society, or public state of "
            "affairs ought to do or be: a stated rule, conduct, policy change, or "
            "desired public outcome. Moral condemnation, criticism, or approval "
            "alone does not establish this dimension; do not infer an unstated "
            "remedy or ought-claim. Asking listeners to contact officials or support "
            "an unspecified ordinance is advocacy alone, unless the target also "
            "states the desired public rule, change, or outcome. Explicit adoption "
            "of a specified requirement or repeal of a named law can qualify even "
            "when listener action is also requested. Private discipleship advice "
            "and reporting existing rules alone are excluded"
        ),
    },
)
PUBLIC_LIFE_REFINEMENT = replace(
    PUBLIC_LIFE_TREATMENT,
    version="public-life-treatment-v2-two-leaf-refinement",
    definitions={leaf: PUBLIC_LIFE_TREATMENT.definitions[leaf] for leaf in PUBLIC_REVISED_LEAVES},
)

SOURCE_MATERIAL = NoulLeafPack(
    version="source-material-v1-target-evidence",
    state_key="source_material_blocks", question_prefix="source_material",
    definitions={
        "biblical_narrative": "recounts or develops an identifiable biblical event or story as material for the point; naming a biblical character, citing a verse, or stating doctrine alone is insufficient",
        "personal_testimony": "uses the preacher's own claimed lived experience of faith, spiritual struggle, or perceived divine action as material for the point; generic first-person speech and mundane autobiographical details alone are insufficient",
        "reported_testimony": "uses another person's reported lived experience of faith, spiritual struggle, or perceived divine action as material for the point; a biblical story, a fictional or invented account, or a doctrinal quotation alone is insufficient",
        "historical_example": "uses an identifiable extra-biblical past event or historical episode presented as historical material to develop or illustrate the point; dates, names, biblical events, hypothetical or explicitly fictional/dramatized examples, and a personal recollection alone are insufficient",
        "quotation": "presents another speaker's or text's words as a quotation used in developing the point; explicit attribution or a clear quotation frame can establish this without typographic quote marks. Paraphrase, an indirect report, a title alone, and familiar unattributed wording are insufficient",
        "denominational_source": "uses material explicitly attributed to an identifiable denominational writer, publication, or institutional source, such as Ellen White, the Adventist Church Manual, or a named denominational confession. A denomination mentioned as the subject, generic religious language, familiar wording, or an unattributed quotation is insufficient",
    },
    task_template="Does the preacher in `{target}` use material in this way: {definition}?",
    positive_template="The target {definition}. {boundary}",
    negative_criteria=(
        "This source or material is not evidenced in the target as part of developing "
        "the point. Exclude passing names, topic vocabulary, invented attribution, "
        "and material present only in adjacent context. Do not infer source use from "
        "doctrine, affiliation, a topic score, or another source/form dimension."
    ),
    evidence_subject="source or material use", missing_evidence="source or material",
    independence="Judge each source/form independently; multiple dimensions may coexist. Quotation need not imply endorsement.",
    boundary=(
        "Adjacent context may resolve the identity of a target pronoun or explicitly "
        "framed quotation, but cannot supply material absent from the target. "
        "A quotation may overlap with biblical narrative, testimony, or an explicit "
        "denominational source. Quoted or rejected material still counts as material "
        "use if developed in the target; it does not establish endorsement, doctrinal "
        "agreement, preacher identity, or denominational affiliation. Biblical narrative "
        "and extra-biblical historical example remain distinct."
    ),
)


# Extend this registry for subsequent packs; transport/cache machinery stays shared.
LEAF_PACKS = {spec.version: spec for spec in (
    LISTENER_DIRECTIVES_V1, LISTENER_DIRECTIVES_V2, LISTENER_DIRECTIVE_REFINEMENT_V2,
    LISTENER_DIRECTIVES, LISTENER_DIRECTIVE_REFINEMENT, PUBLIC_LIFE_TREATMENT_V1,
    PUBLIC_LIFE_TREATMENT, PUBLIC_LIFE_REFINEMENT, SOURCE_MATERIAL,
)}
LISTENER_DIRECTIVE_ROUTE_VERSION = "listener-directive-route-eligible-v1-candidate"


def listener_directive_route(block: Mapping[str, Any]) -> dict[str, Any]:
    eligibility = block.get("projection_eligibility")
    eligible = isinstance(eligibility, Mapping) and eligibility.get("eligible") is True
    return {"policy_version": LISTENER_DIRECTIVE_ROUTE_VERSION,
            "route": eligible, "eligible": eligible,
            "exclusion_reasons": [] if eligible else ["projection_ineligible"],
            "signal": "final_content_projection_eligibility",
            "status": "approved_bounded_review_2026-10-13"}
