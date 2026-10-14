"""Build/check a review-only registry from frozen questions; no inference or database IO."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from pastor_transcript_extractor.sermon_leaf_packs import (
    LISTENER_DIRECTIVES, LISTENER_DIRECTIVE_ROUTE_VERSION,
    PUBLIC_LIFE_TREATMENT, SOURCE_MATERIAL,
)
from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIPS_PACK_VERSION, SALVATION_RELATIONSHIP_SPECS,
    SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS, SALVATION_ROUTE_POLICY_VERSION,
    SALVATION_ROUTE_THRESHOLD, UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS,
    salvation_relationship_pack_digest, salvation_relationship_question_inventory,
)
from pastor_transcript_extractor.sermon_semantic_dimensions import (
    SEMANTIC_ANALYSIS_QUESTION_VERSION, SEMANTIC_DIMENSION_SPECS,
    semantic_question_inventory,
)
from pastor_transcript_extractor.sermon_topics import (
    TOPIC_PACK_VERSION, TOPIC_SPECS, TOPIC_CONTEXT_POLICY_VERSION,
    TOPIC_PROJECTION_POLICY_VERSION, topic_pack_digest, topic_question_inventory,
)

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
REGISTRY_VERSION = "pastor-leaf-contracts-v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# Authored downstream meanings; canonical definitions/questions are copied, never rewritten.
# Every tuple: permissible object of statement, forbidden stronger interpretation.
SALVATION_STATEMENTS = {
    "divine_grace_initiative": ("divine grace or initiative supplying a saving benefit", "predestination, exclusion of all human agency, or a complete grace theology"),
    "atonement_as_basis": ("Christ's saving work connected to saving benefits or sin-bearing", "a specific atonement theory"),
    "forgiveness_pardon": ("divine forgiveness or pardon as a saving benefit", "all conditions or mechanisms of forgiveness"),
    "justification_right_standing": ("declared/credited righteousness, acquittal, or right standing with God", "a complete forensic versus imparted righteousness position"),
    "conversion_new_birth": ("an asserted transition into saving life", "an exact conversion mechanism or theology of baptism"),
    "sanctification_transformation": ("holiness or transformation connected to saving work", "conduct as a condition of obtaining salvation"),
    "assurance_security": ("assurance or security of salvation as a subject of treatment", "permanent security, loss of salvation, or the conditions of either"),
    "judgment_final_destiny": ("judgment or final destiny connected to salvation", "the precise nature of final destiny"),
    "faith_as_receiving_response": ("faith or trust as receiving a saving benefit", "faith alone or denial of other responses"),
    "repentance_as_receiving_response": ("repentance as a response in entry/restoration of saving relationship", "a supported repentance relationship under the unresolved current detector"),
    "obedience_as_condition_or_means": ("conduct as necessary for obtaining or retaining salvation", "a supported conduct-condition position under the unresolved current detector"),
    "obedience_as_consequence_or_evidence": ("saving benefit leading to or evidenced by subsequent conduct", "a supported consequence/evidence position under the unresolved current detector"),
}
LISTENER_STATEMENTS = {
    "trust": ("trust or rely on God or Christ", "faith as a saving means or mere factual assent"),
    "repent": ("repent, confess personal sin, or turn from sin", "repentance as a means of salvation"),
    "change_behavior": ("change specified personal moral conduct", "an umbrella total of every requested behavioral response"),
    "spiritual_practice": ("undertake personal devotional practice", "corporate participation alone"),
    "witness": ("share faith, proclaim the gospel, or invite someone to faith", "kindness alone as witness"),
    "serve": ("help or beneficially impact people in need", "compassionate posture, or service inferred solely from joining/giving/witnessing"),
    "give": ("donate financial or material resources", "giving time/heart or providing direct care alone"),
    "participate": ("join corporate church, worship, or ministry activity", "personal devotion or service inferred from joining alone"),
    "civic_action": ("take concrete civic action", "political ideology or a specific supported policy"),
}
PUBLIC_STATEMENTS = {
    "descriptive": ("reports or explains public events or other actors' remarks", "endorsement of reported remarks"),
    "illustrative": ("uses public affairs to illuminate another point", "endorsement of the illustrated public actors"),
    "theological": ("explicitly interprets public affairs through theological relationships", "a specific policy position or interpretive method"),
    "moral": ("makes moral evaluations of public affairs", "a specific prescribed remedy"),
    "critical": ("expresses negative evaluations of public objects", "opposition to a named object without object-bound evidence, or an ideology"),
    "supportive": ("expresses approval of public objects", "support for a named object without object-bound evidence, or an ideology"),
    "prescriptive": ("states specified public ought-claims or outcomes", "a consistent policy platform without proposition/condition binding"),
    "advocative": ("calls listeners to civic support, opposition, or action", "a specific policy position without object-bound evidence"),
}
MATERIAL_STATEMENTS = {
    "biblical_narrative": ("developed biblical events or stories as material", "exposition, interpretive fidelity, or Scripture authority"),
    "personal_testimony": ("claimed personal lived-faith experience as material", "verification that the experience occurred"),
    "reported_testimony": ("others' reported lived-faith experience as material", "verified biography or endorsement"),
    "historical_example": ("identifiable extra-biblical episodes presented as historical material", "verified historical truth"),
    "quotation": ("attributed or clearly framed quoted words", "endorsement, source identity, or doctrinal agreement"),
    "denominational_source": ("explicitly attributed denominational source material", "affiliation, identity, endorsement, or agreement"),
}
HOMILETIC_STATEMENTS = {
    "exegetical_exposition": ("explanation of biblical text", "interpretive fidelity, specific hermeneutics, or depth"),
    "narrative_illustration": ("developed concrete stories illuminating a point under the homiletic boundaries", "verified history or interchangeability with all material-use leaves"),
    "doctrinal_argument": ("reasoning in support of Christian doctrinal claims", "logical soundness, depth, or consistency of all doctrine"),
    "practical_application": ("concrete listener-directed lived responses", "empathy, effectiveness, or successful listener response"),
}

SHARED = {
    "collection_boundary": {
        "unit": "One target block in one sermon; adjacent context resolves references only under the canonical question.",
        "prohibition": "Do not infer a pastor's overall position, recurrence, quality, or comparison during collection.",
        "evidence": "Preserve exact source segment IDs, bounds, timestamps, text hashes, target/context roles, and membership/eligibility provenance.",
        "granularity": "Existing answers support a target-block envelope, not necessarily a minimal proposition span. Require grounded selection/review before a finer claim.",
        "states": {
            "observation": ["answered", "uncertain", "unavailable", "detector_unresolved"],
            "execution": ["measured", "not_routed", "missing_analysis", "failed", "excluded"],
            "treatment": ["evidenced_treatment", "evaluated_no_treatment", "unknown"],
        },
        "abstention": "Envelope decisions retain raw answers; no new provider answer option is added. Unknown, failed, unrouted and excluded are not negatives.",
        "negative_semantics": "No detected target observable is not rejection of a theological belief.",
        "raw_reuse": "Projection, routing and display changes do not rewrite raw question answers or invalidate their semantic identity.",
    },
    "projection_boundary": {
        "identity": "Use effective reviewed membership; unbound/ambiguous membership blocks pastor attribution.",
        "duplicates": "One independent sermon per teaching occasion; consolidate duplicate uploads/extracts with provenance. Unknown independence blocks recurrence claims.",
        "episode_reduction": "Until episode localization/merge rules are validated, use sermon-with-evidence and measured block diagnostics. Do not treat adjacent positive blocks as independent episodes.",
        "default_scope": "Only the selected, measured corpus and its stated dates/series; never all ministry or all beliefs.",
        "observed_support": "One grounded supported observation permits an occurrence statement, not a recurring pastor trait. Unresolved detectors permit no positive projected statement.",
        "sufficiency": {
            "recurring_trait": "blocked_pending_claim_specific_coverage_and_recurrence_policy",
            "stable_position": "blocked_pending_proposition_and_contradiction_capability_and_sufficiency_policy",
            "minimum_sermon_count": None,
            "required_review": ["independent support", "within-sermon coverage", "series/period opportunity", "measurement and routing limits", "leave-sermon/series-out sensitivity", "permitted scope"],
        },
        "contradictions": "Require the same proposition, object, conditions and scope; retain genuine oppositions as mixed, qualified, or period-specific. Low positive probability/silence is not counterbelief evidence.",
        "temporal": "Use known sermon dates, never upload dates as substitutes. Retain unknown dates/series; no change claim without independent dated support in each period.",
        "missingness": "Missing analysis/route exclusions/failures remain unknown; policy-relative zero is never theological absence.",
        "uncertainty": "Separate measurement, sampling, series/period, identity and denominator uncertainty. Leave-one-out ranges are sensitivity, not confidence intervals.",
        "versioning": "Partition incompatible meanings/models or use an explicitly validated bridge; changing membership/input/policy creates a new reproducible snapshot.",
        "abstain_when": ["unresolved detector", "unreviewed or ambiguous identity", "unverifiable evidence", "incompatible meanings", "unknown independence for recurrence", "missing required coverage or denominator", "unapproved stable-claim policy", "unobserved object/polarity needed for the requested claim"],
    },
}
PROJECTIONS = {
    "A": {
        "id": "attention-projection-proposal-v1",
        "estimand": "Equal-sermon mean normalized topic prominence over measured eligible time in the selected corpus.",
        "sermon_reduction": "sum(block duration * expected Score / 4) / sum(measured eligible block duration); keep analyzed/eligible coverage separate.",
        "numerator": "Duration-weighted normalized Score, then sum of per-sermon values.",
        "denominator": "Measured eligible time within each sermon; independent analyzed sermons at pastor aggregation.",
        "secondary": "P(Substantial or Dominant) summary with its own denominator; within-topic/cohort-relative values only when explicitly declared.",
        "numeric_encoding": "Continuous [0,1] prominence, not a belief probability or parts of a pie.",
        "silence": "Low/absent measured topic attention is not rejection of a belief; unanalyzed eligible time is unknown.",
    },
    "R": {
        "id": "relationship-occurrence-proposal-v1",
        "estimand": "Independent sermons with frozen-policy observed relationship/treatment among completely route-measured selected sermons.",
        "sermon_reduction": "At least one eligible routed block passing the frozen leaf threshold marks a sermon with observed evidence; retain all supporting blocks and raw values.",
        "numerator": "Independent sermons with at least one frozen-policy observation.",
        "denominator": "Independent selected sermons with all currently routed eligible blocks measured; keep zero-route sermons explicitly policy-relative.",
        "secondary": "Conditional denominator excludes zero-route sermons only; neither estimand establishes complete relationship prevalence outside the route.",
        "numeric_encoding": "Policy-relative observed-sermon fraction [0,1]; raw Noul diagnostics are detector presence probability, not intensity of belief.",
        "silence": "Zero under the router is only policy-relative no detection; not a contrary proposition or exhaustive non-treatment.",
    },
    "D": {
        "id": "listener-appeal-occurrence-proposal-v1",
        "estimand": "Independent sermons with evidenced requested action among completely measured eligible selected sermons.",
        "sermon_reduction": "Use grounded positive blocks under a separately approved decision policy; no production hard-positive policy is approved yet.",
        "numerator": "Independent sermons with at least one evidenced appeal of this action.",
        "denominator": "Independent selected sermons with all eligible blocks measured; incomplete sermons shown separately.",
        "secondary": "Action-conditional denominator is completely measured sermons with at least one evidenced action in the nine-action inventory; all nine decisions must be available. Blocks/episodes use separately named denominators.",
        "numeric_encoding": "Nullable observed-sermon fraction after a decision policy; raw Noul diagnostic means are not amount/intensity of appeal.",
        "silence": "No detected request under complete measurement is non-treatment, not rejected action, behavior, or lack of pastoral care.",
    },
    "F": {
        "id": "treatment-material-occurrence-proposal-v1",
        "estimand": "Independent sermons with evidenced treatment/material among completely measured eligible selected sermons.",
        "sermon_reduction": "Use grounded positive blocks under a separately approved decision policy; no new production hard-positive policy is approved by this registry.",
        "numerator": "Independent sermons with at least one evidenced use/function.",
        "denominator": "Independent selected sermons with all eligible blocks measured; incomplete sermons shown separately.",
        "secondary": "Conditional population must be independently specified/observed; use the per-leaf conditional_population field. Do not construct topic/function attachment from co-occurrence.",
        "numeric_encoding": "Nullable observed-sermon fraction after a decision policy; presence is not depth, truth, quality or belief strength.",
        "silence": "Complete measured non-treatment remains no detected use/function, not denial of a position or quality judgment.",
    },
}


def sources():
    """Return questions and cache digest semantics directly from the canonical modules."""
    rows = [
        ("T", TOPIC_PACK_VERSION, "src/pastor_transcript_extractor/sermon_topics.py", topic_question_inventory(0), topic_pack_digest(), "inventory_digest"),
        ("S", SALVATION_RELATIONSHIPS_PACK_VERSION, "src/pastor_transcript_extractor/sermon_salvation_relationships.py", salvation_relationship_question_inventory(0), salvation_relationship_pack_digest(), "inventory_digest"),
        ("H", SEMANTIC_ANALYSIS_QUESTION_VERSION, "src/pastor_transcript_extractor/sermon_semantic_dimensions.py", semantic_question_inventory(0), None, "no_canonical_pack_digest_function"),
    ]
    for family, pack in [("L", LISTENER_DIRECTIVES), ("P", PUBLIC_LIFE_TREATMENT), ("M", SOURCE_MATERIAL)]:
        rows.append((family, pack.version, "src/pastor_transcript_extractor/sermon_leaf_packs.py", pack.questions(0), pack.digest(), "questions_at_position_zero_digest"))
    return {family: {"version": version, "source": path, "questions": questions,
                     "canonical_pack_digest": cache_digest, "canonical_digest_semantics": semantics,
                     "questions_digest": digest(questions)}
            for family, version, path, questions, cache_digest, semantics in rows}


ROUTES = {
    "T": {"version": TOPIC_PROJECTION_POLICY_VERSION, "signal": "strict current final content projection eligibility", "status": "existing_projection_policy", "limitations": ["Full-block role/density/overlap exclusions can omit valid sermon material; excluded observations remain raw only."]},
    "S": {"version": SALVATION_ROUTE_POLICY_VERSION, "signal": "strict eligibility and P(salvation >= Supporting)", "threshold": SALVATION_ROUTE_THRESHOLD, "status": "accepted_for_policy_relative_observation", "limitations": ["590:26 is a known meaningful below-route miss at .40; route is not exhaustive relationship presence."]},
    "L": {"version": LISTENER_DIRECTIVE_ROUTE_VERSION, "signal": "strict current final content projection eligibility", "status": "accepted_bounded_review", "limitations": ["Bounded PASS is not corpus recall or sample sufficiency."]},
    "P": {"version": "public-life-route-eligible-v2-candidate", "signal": "strict current final content projection eligibility", "status": "proposed_pending_acceptance", "limitations": ["Prior .55 gate misses 4430:34 and 1200:26; candidate recovers both in a ten-case selected comparison, not a corpus recall estimate."]},
    "M": {"version": "source-material-route-eligible-v1-candidate", "signal": "strict current final content projection eligibility", "status": "accepted_bounded_review", "limitations": ["Material as presented is not verified truth; 4430:37 film/story ambiguity remains explicit."]},
    "H": {"version": TOPIC_PROJECTION_POLICY_VERSION, "signal": "strict current final content projection eligibility for TypeSafe block observations", "status": "existing_projection_policy", "limitations": ["Legacy semantic-style evidence/run measurements are separate and cannot be mixed with TypeSafe Noul block observations without a validated bridge."]},
}


def build_registry():
    packs = sources()
    inventories = {
        "T": {k: (v.label, "any belief, affiliation, Scriptural-use pattern, or topic-specific treatment inferred from attention") for k, v in TOPIC_SPECS.items()},
        "S": SALVATION_STATEMENTS, "L": LISTENER_STATEMENTS, "P": PUBLIC_STATEMENTS,
        "M": MATERIAL_STATEMENTS, "H": HOMILETIC_STATEMENTS,
    }
    expected = {"T": set(TOPIC_SPECS), "S": set(SALVATION_RELATIONSHIP_SPECS),
                "L": set(LISTENER_DIRECTIVES.definitions), "P": set(PUBLIC_LIFE_TREATMENT.definitions),
                "M": set(SOURCE_MATERIAL.definitions), "H": set(SEMANTIC_DIMENSION_SPECS)}
    records = []
    for family, meanings in inventories.items():
        if set(meanings) != expected[family]:
            raise ValueError(f"{family}: authored meanings do not exactly match canonical inventory")
        pack = packs[family]
        for leaf, (subject, forbidden) in meanings.items():
            contract_id = f"{family}:{leaf}"
            unresolved = family == "S" and leaf in UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS
            question_id, question = next((k, v) for k, v in pack["questions"].items() if k.endswith(f"_0_{leaf}"))
            projection_family = {"T": "A", "S": "R", "L": "D", "P": "F", "M": "F", "H": "F"}[family]
            kind = "emphasis" if family == "T" or (family == "S" and leaf == "assurance_security") else "listener_directed_behavior" if family == "L" else "position" if family == "S" else "rhetorical_treatment"
            prefix = {"T": "Measured topic attention concerns", "S": "The measured sermon evidence explicitly presents", "L": "The measured sermon evidence asks listeners to", "P": "The measured sermon evidence", "M": "The measured sermon evidence uses", "H": "The measured sermon evidence contains"}[family]
            projection = deepcopy(PROJECTIONS[projection_family])
            projection["family"] = projection_family
            projection["shared_policy"] = "projection_boundary"
            projection["input_pack_version"] = pack["version"]
            projection["input_questions_digest"] = pack["questions_digest"]
            projection["conditional_population"] = {
                "T": "Not applicable to the primary whole-measured-sermon attention estimand.",
                "S": "Completely route-measured sermons with at least one routed block; report both denominators.",
                "L": "Completely measured sermons with any evidenced action in the full nine-action inventory.",
                "P": "Public-treatment episodes/sermons need independent topic/opportunity evidence; treatment-positive-only selection is a separately named observed-function conditional analysis, not all public treatment.",
                "M": "Completely measured sermons with any evidenced use in the six-material inventory; not every possible sermon source.",
                "H": "Completely measured sermons with any evidenced treatment in the four-dimension inventory; not all homiletic activity.",
            }[family]
            projection["conflict_capability"] = "Presence detector does not independently collect all opposing propositions; abstain from exhaustive consistency or contradiction resolution." if family == "S" else "Different functions/objects/actions are not contradictions; preserve overlap. Specific proposition contradictions require separate bound evidence."
            if unresolved:
                projection.update(sermon_reduction="No positive projection; retain raw answers for inspection only.", numeric_encoding="null; never zero", numerator=None, denominator="Not applicable while detector is unresolved.")
            blockers = ["claim-specific recurring/stable sufficiency rules unapproved", "cross-pastor comparison and clustering policy unapproved"]
            if family in "LPMH":
                blockers.append("production evidence/hard-positive decision policy not established for this use")
            if family == "P":
                blockers.append("eligibility-only routing acceptance pending")
            if unresolved:
                blockers.append("detector unresolved")
            threshold = SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS.get(leaf) if family == "S" else None
            characteristic = f"{family.lower()}.{leaf}"
            contributions = {
                "L:civic_action": ["civic_listener_appeal"], "P:advocative": ["civic_listener_appeal"],
                "H:practical_application": ["listener_application"],
                "H:narrative_illustration": ["story_based_treatment"], "M:biblical_narrative": ["story_based_treatment"],
                "M:personal_testimony": ["story_based_treatment"], "M:reported_testimony": ["story_based_treatment"],
                "M:historical_example": ["story_based_treatment"],
            }.get(contract_id, ["listener_application"] if family == "L" else [])
            recurring_verb = {"T": "gives attention to", "S": "presents", "L": "asks listeners to", "P": "uses public treatment that", "M": "uses", "H": "uses"}[family]
            records.append({
                "contract_id": contract_id, "version": REGISTRY_VERSION, "leaf_id": leaf,
                "downstream_statement": {
                    "characteristic_id": characteristic, "possible_shared_characteristics": contributions,
                    "topic_ids": [leaf] if family == "T" else ["salvation_gospel"] if family == "S" else ["society_public_life"] if family == "P" else [],
                    "topic_binding": "Catalog subject assignment only; action/material/homiletic attachment to specific topics requires independent relation evidence.",
                    "kind": kind, "subject": subject,
                    "observed_statement": None if unresolved else f"{prefix} {subject}; cite the supporting sermons and measured-corpus scope.",
                    "desired_statement_if_measurement_resolved": f"Within sufficient independent corpus coverage, the pastor recurrently presents {subject}." if unresolved else None,
                    "recurring_statement": None if unresolved else f"Within the stated measured corpus and approved recurrence scope, this pastor recurrently {recurring_verb} {subject}.",
                    "recurring_statement_status": "blocked_until_claim_specific_policy" if not unresolved else "measurement_unresolved",
                    "inadequate_statement": f"{subject.capitalize()} is not characterized: {'the measurement is unresolved' if unresolved else 'adequate evidence/coverage is unavailable'}.",
                    "forbidden_claims": [forbidden, "all-ministry generalization", "absence means rejection", "a global pastor-quality score"],
                    "scope": "Selected measured independent sermons; dates, series and routing limitations must be stated.",
                    "allowed_uses": {
                        "grounded_occurrence_description": "blocked_measurement_unresolved" if unresolved else "proposed_after_evidence_and_identity_checks",
                        "diagnostic_numeric_summary": "blocked_measurement_unresolved" if unresolved else "existing_frozen_policy_only" if family in "TS" else "raw_probability_diagnostics_only_pending_decision_policy",
                        "recurring_pastor_trait": "blocked", "stable_pastor_position": "blocked",
                        "pastor_comparison": "blocked", "clustering": "blocked",
                        "noteworthy_discovery": "grounded_passage_candidates_only" if not unresolved else "blocked",
                    },
                },
                "collection": {
                    "family": family, "shared_policy": "collection_boundary",
                    "canonical_source": pack["source"], "pack_version": pack["version"],
                    "canonical_pack_digest": pack["canonical_pack_digest"], "canonical_digest_semantics": pack["canonical_digest_semantics"],
                    "pack_questions_digest": pack["questions_digest"],
                    "question_id_at_position_zero": question_id, "question_digest": digest(question),
                    "canonical_question": question, "observable": question["instructions"]["task"],
                    "raw_answer": "expected Score, all level probabilities and confidence; prominence, not belief" if family == "T" else "Noul yes-probability; no separate confidence, intensity or pastor inference",
                    "attribution": "Topic content may include reported/rejected/quoted material; final eligibility decides pastor attribution." if family == "T" else "Material use may include quoted/rejected sources; adoption and truth are not measured." if family == "M" else "Preacher-targeted observable under canonical criteria; reported/context-only speech alone cannot establish an adopted claim/appeal.",
                    "evidence_granularity": "target_block_envelope; finer claim requires grounded selection/review",
                    "route": deepcopy(ROUTES[family]),
                    "observation_decision": {
                        "status": "measurement_unresolved" if unresolved else "existing_frozen_policy" if family == "S" else "not_a_new_hard_positive_policy",
                        "policy_version": SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION if family == "S" else None,
                        "threshold": threshold,
                        "note": "Display cutoffs do not authorize collection or pastor projection. An unresolved value has no threshold and is never zero.",
                    },
                    "exclusivity": {"unit": "specified target observable", "rule": "Independent questions; preserve canonical exclusions, and allow independently evidenced overlap. No sermon-wide single-label selection."},
                    "context_policy": TOPIC_CONTEXT_POLICY_VERSION if family == "T" else "canonical target/context instructions and recorded context-builder identity",
                },
                "projection": projection,
                "diagnostic": {
                    "disposition": "measurement_unresolved" if unresolved else "limited_statement" if family in "SP" else "usable_for_named_statement",
                    "flags": (["semantic_ordering_failure"] if unresolved else []) + (["policy_relative_route_omissions"] if family == "S" else []) + (["object_proposition_binding_missing"] if family == "P" else []) + (["polarity_conditions_missing"] if leaf == "assurance_security" and family == "S" else []) + (["possible_shared_characteristic_no_automatic_merge"] if contributions else []),
                    "blockers": blockers, "broader_collection_authorized": False,
                    "resolution": "Retain raw values, exclude projection; separately version any future measurement redesign." if unresolved else "Approve only the scoped named statement and shared contract; resolve listed evidence/routing/decision/sufficiency prerequisites for stronger use.",
                },
            })
    # Questions are already materialized per leaf; pack manifest retains authoritative digest conventions.
    manifest = {k: {field: value for field, value in v.items() if field != "questions"} for k, v in packs.items()}
    payload = {
        "schema_version": 1, "registry_version": REGISTRY_VERSION,
        "status": "proposed_review_only", "created_date": "2026-10-13",
        "production_effect": "none", "broader_collection_authorized": False,
        "design_document": "docs/TYPESAFE_TOPIC_ANALYSIS_PLAN.md#downstream-pastor-understanding-contract--2026-10-13",
        "digest_definition": "SHA-256 of sorted-key compact JSON; position-zero question digests pin full provider-visible semantics. Canonical cache digests retain each pack's own convention.",
        "shared_policies": deepcopy(SHARED), "pack_manifest": manifest,
        "records": records,
    }
    validate_registry(payload)
    return {**payload, "content_fingerprint": digest(payload)}


def validate_registry(registry):
    """Fail closed on omissions, drift, broken policy references or premature permissions."""
    expected_packs = sources()
    expected = {f"{family}:{key.split('_0_', 1)[1]}" for family, pack in expected_packs.items() for key in pack["questions"]}
    records = registry["records"]
    ids = [r["contract_id"] for r in records]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError("Registry must cover exactly the canonical inventory without duplicates")
    if registry.get("production_effect") != "none" or registry.get("broader_collection_authorized") is not False:
        raise ValueError("Review registry cannot activate collection")
    if registry.get("pack_manifest") != {k: {field: value for field, value in v.items() if field != "questions"} for k, v in expected_packs.items()}:
        raise ValueError("Canonical pack manifest drift")
    for record in records:
        downstream, collection, projection, diagnostic = (record[k] for k in ("downstream_statement", "collection", "projection", "diagnostic"))
        family = collection["family"]
        pack = expected_packs[family]
        question = pack["questions"][collection["question_id_at_position_zero"]]
        provenance_fields = {"pack_version": "version", "canonical_source": "source", "canonical_pack_digest": "canonical_pack_digest", "canonical_digest_semantics": "canonical_digest_semantics", "pack_questions_digest": "questions_digest"}
        if any(collection.get(field) != pack[source] for field, source in provenance_fields.items()):
            raise ValueError("Per-leaf canonical provenance drift")
        if projection["input_pack_version"] != pack["version"] or projection["input_questions_digest"] != pack["questions_digest"]:
            raise ValueError("Projection input provenance drift")
        if collection["canonical_question"] != question or collection["question_digest"] != digest(question):
            raise ValueError(f"{record['contract_id']}: canonical question drift")
        if record["contract_id"] != f"{family}:{record['leaf_id']}" or not collection["question_id_at_position_zero"].endswith(f"_0_{record['leaf_id']}"):
            raise ValueError("Contract leaf does not match canonical question")
        for policy in (collection["shared_policy"], projection["shared_policy"]):
            if policy not in registry["shared_policies"]:
                raise ValueError("Unknown shared policy")
        for field in ("characteristic_id", "kind", "inadequate_statement", "scope", "forbidden_claims"):
            if not downstream.get(field):
                raise ValueError(f"Missing downstream {field}")
        for field in ("estimand", "sermon_reduction", "denominator", "numeric_encoding", "silence", "conflict_capability", "conditional_population"):
            if not projection.get(field):
                raise ValueError(f"Missing projection {field}")
        if diagnostic["broader_collection_authorized"] is not False:
            raise ValueError("Per-leaf collection must remain inactive")
        uses = downstream["allowed_uses"]
        if any(uses[k] != "blocked" for k in ("recurring_pastor_trait", "stable_pastor_position", "pastor_comparison", "clustering")):
            raise ValueError("Stable/comparative uses remain gated in V1")
        unresolved = family == "S" and record["leaf_id"] in UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS
        if unresolved:
            if (downstream["observed_statement"] is not None
                    or collection["observation_decision"]["threshold"] is not None
                    or projection["numerator"] is not None
                    or uses["diagnostic_numeric_summary"] != "blocked_measurement_unresolved"
                    or uses["grounded_occurrence_description"] != "blocked_measurement_unresolved"
                    or uses["noteworthy_discovery"] != "blocked"
                    or diagnostic["disposition"] != "measurement_unresolved"):
                raise ValueError("Unresolved detector cannot produce a positive or zero projection")
        elif not downstream["observed_statement"]:
            raise ValueError("A usable leaf must name a concrete observed statement")
        if family == "S" and not unresolved and collection["observation_decision"]["threshold"] != SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[record["leaf_id"]]:
            raise ValueError("Frozen salvation threshold drift")
    if "content_fingerprint" in registry:
        payload = {k: v for k, v in registry.items() if k != "content_fingerprint"}
        if registry["content_fingerprint"] != digest(payload):
            raise ValueError("Registry fingerprint mismatch")


def render_review(registry):
    lines = ["# Pastor leaf contract registry V1", "", "Status: proposed, review only. Collection remains inactive.", "",
             f"Content fingerprint: `{registry['content_fingerprint']}`", "",
             "Find complete JSON records by searching their unique contract IDs. Shared policies are normative; canonical questions, projection estimands, exceptions and allowed-use gates are materialized per record.", "",
             "| Contract ID | Kind | Permissible observed statement | Disposition |", "| --- | --- | --- | --- |"]
    for r in registry["records"]:
        d = r["downstream_statement"]
        statement = d["observed_statement"] or d["inadequate_statement"]
        lines.append(f"| `{r['contract_id']}` | {d['kind']} | {statement} | {r['diagnostic']['disposition']} |")
    lines += ["", "Full records: [registry-v1.json](registry-v1.json). Decisions and prerequisites: [REVIEW.md](REVIEW.md).", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read/validate committed artifacts and reject drift; write nothing")
    args = parser.parse_args()
    registry = build_registry()
    json_text = json.dumps(registry, indent=2, ensure_ascii=False) + "\n"
    markdown = render_review(registry)
    paths = [(HERE / "registry-v1.json", json_text), (HERE / "REGISTRY.md", markdown)]
    if args.check:
        validate_registry(json.loads(paths[0][0].read_text()))
        for path, expected in paths:
            if path.read_text() != expected:
                raise SystemExit(f"Artifact drift: {path.relative_to(ROOT)}; inspect semantics before rebuilding")
        print(f"PASS: {len(registry['records'])} contracts; canonical digests/thresholds and review gates match; no provider/database access")
    else:
        for path, value in paths:
            path.write_text(value)
        print(f"Prepared {len(registry['records'])} review contracts; no provider/database access")


if __name__ == "__main__":
    main()
