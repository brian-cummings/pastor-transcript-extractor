"""Deterministic supplied-passage consumer; no provider, database or pastor estimator.

The public consumer accepts evidence and product contracts only. Acceptance oracles
are deliberately confined to observed_profile_review.py.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PACKET_DIR = ROOT / "docs/review-proposals/profile-evidence-v1"
VERSION = "observed-passage-consumer-v1"
FROZEN_PACKET_SHA256 = "f9a9d2d3db7fe06650af4cd4f1f5cbcf582d40f75171c9eea95620f79e6824e4"
UNRESOLVED_SALVATION = [
    "S:repentance_as_receiving_response", "S:obedience_as_condition_or_means",
    "S:obedience_as_consequence_or_evidence",
]
ADDRESS_ACTS = (
    "acknowledgment", "perspective_taking", "reassurance", "challenge", "warning",
    "invitation", "concrete_care",
)
STATUS_LABELS = {
    "local_examples": "Observed in supplied passage",
    "negative_in_unit": "Not observed in this assessed unit",
    "not_collected": "Missing: not collected",
    "measurement_unresolved": "Unavailable: measurement unresolved",
    "judgment_withheld": "Unresolved: judgment withheld",
    "boundary_incomplete": "Insufficient local evidence",
    "incompatible": "Unavailable: incompatible evidence",
    "excluded": "Excluded by ownership/content policy",
    "downstream_held": "Unavailable: later construct held",
}


def packet_models():
    """Use the frozen schema without changing it or importing proposal builders."""
    name = "_pte_profile_evidence_contract_v1"
    if name not in sys.modules:
        path = PACKET_DIR / "contract.py"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ValueError("The observed-profile consumer requires the V1 packet in the repository checkout.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


def load_packet() -> dict[str, Any]:
    raw = (PACKET_DIR / "packet-v1.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_PACKET_SHA256:
        raise ValueError("The authorized frozen V1 packet changed; consumer review requires the original decisions/withholdings.")
    packet = packet_models().Packet.model_validate_json(raw).model_dump()
    for source in packet["sources"]:
        if hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"Frozen source hash mismatch: {source['path']}")
    return packet


def _words(value: str) -> str:
    return value.replace("_", " ")


def _validate_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    models = packet_models()
    rows = [models.Evidence.model_validate(row).model_dump() for row in rows]
    if len({e["evidence_id"] for e in rows}) != len(rows):
        raise ValueError("Duplicate evidence ID in supplied case")
    for e in rows:
        s = e["source"]
        if hashlib.sha256(s["target_text"].encode()).hexdigest() != s["target_sha256"]:
            raise ValueError("Target hash mismatch")
        for span in e["spans"]:
            text = s[{"target": "target_text", "leading_context": "leading_context", "trailing_context": "trailing_context"}[span["role"]]]
            if not 0 <= span["start"] < span["end"] <= len(text) or text[span["start"]:span["end"]] != span["text"]:
                raise ValueError("Ungrounded source span")
        p = e["payload"]
        if p["kind"] == "relation":
            for key in ("left_span", "right_span"):
                if not 0 <= p[key] < len(e["spans"]) or e["spans"][p[key]]["role"] != "target":
                    raise ValueError("Relation endpoints must be target-grounded")
        if p["kind"] == "address" and (e["spans"][0]["role"] != "target" or set(p["acts"]) != set(ADDRESS_ACTS)):
            raise ValueError("Address requires a target utterance and all independent act decisions")
    return rows


def _facts(e: dict[str, Any]) -> list[str]:
    """Surface supplied decisions verbatim in plain labels; never rejudge text."""
    p = e["payload"]
    if p["kind"] == "leaf":
        return [p["observed_statement"]]
    if p["kind"] == "claim_design_only":
        return [f"Design-only claim: {p['object']} / {_words(p['relation'])} / {p['expression']}.",
                "Conditions: " + ("; ".join(p["conditions"]) or "none supplied; universal scope unestablished"),
                f"Voice: {_words(p['voice'])}; adoption: {_words(p['adoption'])}."]
    if p["kind"] == "relation":
        return [f"{_words(p['relation']).capitalize()}: {_words(p['decision'])}.",
                f"Left voice: {_words(p['left_voice'])}; right voice: {_words(p['right_voice'])}; adoption: {_words(p['adoption'])}."]
    observed = [_words(a) for a, state in p["acts"].items() if state == "observed"]
    return ["Observed act decisions: " + (", ".join(observed) or "none"),
            "Circumstance relevance: " + _words(p["circumstance_relevance"]),
            "Human-recipient binding: " + _words(p["recipient_binding"]),
            f"Addressee: {_words(p['addressee'])}; voice: {_words(p['voice'])}; adoption: {_words(p['adoption'])}.",
            "Qualifications: " + ("; ".join(p["qualifications"]) or "none supplied; unconditional scope unestablished")]


def _related(cid: str, p: dict[str, Any]) -> bool:
    kind = p["kind"]
    if kind == "address":
        return cid == "C12"
    if kind == "claim_design_only":
        return cid in {"C02", "C03", "C04", "C08", "C14", "C18", "C20"}
    if kind == "relation":
        if cid == "C06":
            return p["relation"] in {"grounds_response", "specifies_response_step", "addresses_response_obstacle"}
        return cid in {"C10", "C11", "C13", "C14", "C20"}
    leaf = p["contract_id"]
    family = leaf.split(":")[0]
    return (
        (cid in {"C01", "C15"} and family == "T") or
        (cid in {"C02", "C18"} and family == "S") or
        (cid == "C03" and leaf == "S:assurance_security") or
        (cid in {"C04", "C08"} and family in {"T", "P"}) or
        (cid == "C05" and family in {"H", "L", "M"}) or
        (cid == "C06" and (family == "L" or leaf == "H:practical_application")) or
        (cid == "C07" and (family == "P" or leaf == "L:civic_action")) or
        (cid in {"C10", "C11", "C13"} and family == "H") or
        (cid == "C17") or (cid == "C19" and family == "M")
    )


def _assessment(cid: str, e: dict[str, Any]) -> dict[str, Any]:
    p = e["payload"]
    reasons: list[str] = []
    if e["provenance"]["origin"] == "synthetic_design":
        reasons.append("Synthetic design input: no real pastor attribution.")
    if e["eligibility"]["membership"] == "unknown" or e["eligibility"]["content"] == "unknown":
        reasons.append("Pastor attribution withheld: reviewed ownership/content eligibility is unknown.")
    state, role = "not_collected", "related"
    if e["eligibility"]["membership"] == "conflict" or e["eligibility"]["content"] == "excluded":
        state, role = "excluded", "unresolved"
        reasons.append("Ownership conflict or excluded content prevents field credit.")
    elif e["provenance"]["compatibility"] != "compatible":
        state, role = "incompatible", "unresolved"
        reasons.append("Question/source semantics are incompatible or unresolved; pooling is withheld.")
    elif cid == "C14" or cid == "C17":
        state = "downstream_held"
        reasons.append("Coherence/recurrence is a later held construct; local occurrences cannot establish it.")
    elif p["kind"] == "claim_design_only":
        role = "unresolved"
        reasons.append("G1 remains unimplemented; this design shape supplies no measured position.")
    elif e["coverage"]["local_boundary"] != "sufficient":
        state, role = "boundary_incomplete", "unresolved"
        reasons.append("Sufficient local evidence is incomplete or unknown; continuation/review is needed.")
        # A frozen negative relation remains a counterexample without claiming sermon absence.
        if p["kind"] == "relation" and p["decision"] == "not_linked":
            state, role = "judgment_withheld", "counter"
    elif p["kind"] == "leaf" and p["contract_id"] in UNRESOLVED_SALVATION:
        state, role = "measurement_unresolved", "unresolved"
        reasons.append("This salvation measurement remains unavailable; it cannot support a positive or negative.")
    elif e["observation_state"] == "judgment_withheld":
        state, role = "judgment_withheld", "unresolved"
        reasons.append("The supplied observation is withheld; a raw answer does not override that decision.")
    elif e["observation_state"] == "boundary_incomplete":
        state, role = "boundary_incomplete", "unresolved"
        reasons.append("The supplied observation requires continuation even if a narrower boundary flag is sufficient.")
    elif p["kind"] == "leaf" and e["observation_state"] == "negative_in_unit":
        state, role = "negative_in_unit", "counter"
        reasons.append("Negative applies only to the specified assessed target; nothing is concluded elsewhere.")
    elif p["kind"] == "address":
        positive = [a for a, value in p["acts"].items() if value == "observed"]
        gates = {
            "Circumstance relevance": p["circumstance_relevance"] in {"relevant_in_target", "relevant_context_resolved"},
            "Human-recipient circumstance binding": p["recipient_binding"] in {"bound_in_target", "bound_context_resolved"},
            "Current-listener addressee": p["addressee"] == "direct_current_listener",
            "Own/adopted stance": p["adoption"] == "own_or_adopted",
        }
        if e["observation_state"] == "negative_in_unit" and all(v == "not_observed" for v in p["acts"].values()):
            state, role = "negative_in_unit", "counter"
            reasons.append("Negative applies only to the specified assessed target; nothing is concluded elsewhere.")
        elif positive and all(gates.values()):
            state, role = "local_examples", "supporting"
        else:
            state, role = "judgment_withheld", "unresolved"
            if not positive:
                reasons.append("No specified address act has an observed decision in this target.")
                if all(v == "not_observed" for v in p["acts"].values()):
                    role = "counter"
            reasons += [name + " gate is not established; preserve its supplied decision." for name, passed in gates.items() if not passed]
    elif p["kind"] == "relation":
        if cid in {"C20"}:
            reasons.append("A relation is not an observation of expressed epistemic uncertainty; G1 is missing.")
        elif p["decision"] == "linked" and p["adoption"] == "own_or_adopted":
            state, role = "local_examples", "supporting"
        else:
            state, role = "judgment_withheld", "counter" if p["decision"] == "not_linked" else "unresolved"
            reasons.append("The supplied directed relation or adoption is not established; no opposite is synthesized.")
    elif p["kind"] == "leaf":
        leaf = p["contract_id"]
        if leaf in UNRESOLVED_SALVATION:
            state, role = "measurement_unresolved", "unresolved"
            reasons.append("This salvation measurement remains unavailable; it cannot support a positive or negative.")
        elif cid in {"C01", "C05", "C07", "C19"} or (cid == "C02" and leaf.startswith("S:")):
            state, role = "local_examples", "supporting"
        else:
            reasons.append("This narrow leaf locates material but does not supply the richer field observation.")
    return dict(evidence_id=e["evidence_id"], availability=state, role=role, reasons=reasons)


def _reading_note(e: dict[str, Any]) -> str:
    p = e["payload"]
    cid = "C12" if p["kind"] == "address" else "C10" if p["kind"] == "relation" else "C08" if p["kind"] == "claim_design_only" else "C05"
    a = _assessment(cid, e)
    if a["availability"] in {"excluded", "incompatible", "boundary_incomplete"}:
        return STATUS_LABELS[a["availability"]] + ". " + " ".join(a["reasons"]) + " The supplied decisions are retained below without promoting them."
    if p["kind"] == "claim_design_only":
        return "This is a synthetic claim shape, not a measured position. Different objects and conditions remain attached; no opposite claim or coherence verdict is inferred."
    if p["kind"] == "leaf":
        return "This is a narrow supplied observation. It does not supply missing positions, development or circumstance-bound address."
    if p["kind"] == "relation":
        if a["availability"] == "local_examples":
            return "The supplied decision links the two target spans in the stated direction. This supports a local example, with adequacy, depth and fidelity unassessed."
        return "The supplied relation/stance is not established. Adjacency alone receives no development credit; no absence elsewhere is inferred."
    if a["availability"] == "local_examples":
        return "The observed acts meet the supplied local current-listener address gates. This is a passage example; pastor attribution and recurring posture remain unestablished."
    if a["availability"] == "negative_in_unit":
        return "The specified acts were not observed in this assessed utterance. This is a local negative only; nothing is concluded about the rest of the sermon or the pastor."
    return "The separate act decisions remain visible, but circumstance-bound current-listener address is not established. " + " ".join(a["reasons"])


def consume(
    evidence: list[dict[str, Any]], field_contracts: list[dict[str, Any]], estimands: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a partial passage view without access to case IDs or expected outputs."""
    evidence = _validate_evidence(evidence)
    models = packet_models()
    field_contracts = [models.FieldContract.model_validate(f).model_dump() for f in field_contracts]
    estimands = [models.Estimand.model_validate(e).model_dump() for e in estimands]
    if [f["characteristic_id"] for f in field_contracts] != [f"C{i:02}" for i in range(1, 21)]:
        raise ValueError("Consumer requires the 20 V1 field contracts")
    if {e["estimand_id"] for e in estimands} != {f"E{i}" for i in range(7)}:
        raise ValueError("Consumer requires the seven V1 estimands")
    fields = []
    for contract in field_contracts:
        cid = contract["characteristic_id"]
        assessments = [_assessment(cid, e) for e in evidence if _related(cid, e["payload"])]
        states = {a["availability"] for a in assessments}
        default = "measurement_unresolved" if cid == "C02" else "downstream_held" if cid in {"C14", "C17"} else "not_collected"
        availability = next((s for s in ("local_examples", "negative_in_unit", "excluded", "incompatible", "boundary_incomplete", "judgment_withheld", "measurement_unresolved", "downstream_held") if s in states), default)
        links = {role: [a["evidence_id"] for a in assessments if a["role"] == role] for role in ("supporting", "counter", "unresolved", "related")}
        gaps = list(contract["missing_information"])
        if cid == "C02":
            gaps += UNRESOLVED_SALVATION
        if availability == "not_collected":
            gaps.append("Required compatible observation is not supplied; absence of evidence is not a negative finding.")
        reasons = list(dict.fromkeys(reason for a in assessments for reason in a["reasons"]))
        reasons += ["Rates and recurring pastor characteristics are withheld: candidate recall, sermon assessment and opportunities are unestablished.", contract["forbidden_inference"]]
        fields.append(dict(
            characteristic_id=cid, question=contract["question"], target_statement=contract["target_statement"],
            subject_scope="supplied_passage", availability=availability, status_label=STATUS_LABELS[availability],
            assessments=assessments, **links, missing_information=list(dict.fromkeys(gaps)),
            suppression_reasons=reasons, active_estimand="E0", proposed_estimands=contract["estimand_ids"],
            population_rate=None, recurring_characterization=None, comparison=None, quality_score=None,
        ))
    groups: dict[str, list[str]] = {}
    for e in evidence:
        groups.setdefault(e["independence"]["utterance_group"], []).append(e["evidence_id"])
    return dict(
        version=VERSION, scope="Supplied passages only; no pastor characterization or comparison.",
        fields=fields, evidence=[dict(**deepcopy(e), visible_facts=_facts(e), reading_note=_reading_note(e)) for e in evidence],
        utterance_groups=groups, unique_utterance_groups=len(groups), retained_evidence=[e["evidence_id"] for e in evidence],
        independently_eligible_sermons=None,
        independence_note="Aliases/overlapping candidates share a group. Repeated material, series and periods remain attached; no recurrence or effective sample size is estimated.",
        estimands=[dict(estimand_id=e["estimand_id"], target=e["target"], status="local_examples_only" if e["estimand_id"] == "E0" else "held_no_estimate") for e in estimands],
        downstream={f"D{i:02}": "held" for i in range(1, 7)},
        holds=["G1 implementation", "broader collection", "pastor projection/comparison", "clustering", "G4", "quality/exceptional-pastor scoring"],
    )
