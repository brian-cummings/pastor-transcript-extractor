"""Prepare/check authored G1 contract examples; no model, corpus, or database access."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = "g1-binding-proof-cases-v1"
RELATIONS = {
    "salvation_acceptance": {"acceptance_knowable_now", "loss_possible", "retention"},
    "city_ramp_requirement": {"public_support", "public_opposition", "public_requirement"},
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def span(case, text, field="target_text"):
    source = case[field]
    matches = list(re.finditer(r"(?<!\w)" + re.escape(text) + r"(?!\w)", source))
    if len(matches) != 1:
        raise ValueError(f"{case['case_id']}: span must match exactly once: {text!r}")
    start = matches[0].start()
    return {"source_field": field, "start": start, "end": start + len(text), "text": text}


def case(case_id, target, reason, leading=""):
    return {"case_id": case_id, "target_text": target, "leading_context": leading,
            "trailing_context": "", "expected_claims": [], "expected_diagnostics": [],
            "reason": reason}


def claim(c, relation, claim_text, subject_text, *, polarity="affirmed", expression="assertion",
          voice="preacher", adoption="own_assertion", subject_field="target_text",
          frame=None, condition=None, uncertainty=None, scope=None):
    subject = "salvation_acceptance" if relation in RELATIONS["salvation_acceptance"] else "city_ramp_requirement"
    c["expected_claims"].append({
        "claim_id": f"{c['case_id']}:claim-{len(c['expected_claims']) + 1}", "case_id": c["case_id"],
        "subject_id": subject, "relation": relation, "polarity": polarity,
        "expression": expression, "voice": voice, "adoption": adoption,
        "claim_span": span(c, claim_text),
        "subject_evidence": span(c, subject_text, subject_field),
        "binding_evidence": [span(c, frame or claim_text)],
        "conditions": [{"kind": "condition", "span": span(c, condition)}] if condition else [],
        "epistemic_status": "expressed_uncertainty" if uncertainty else "not_stated",
        "epistemic_evidence": span(c, uncertainty) if uncertainty else None,
        "scope_text": scope, "scope_evidence": span(c, scope) if scope else None,
    })


def build_packet():
    cases = []
    c = case("A01", "You can know now that you are accepted by God.", "Present knowability is not permanent security.")
    claim(c, "acceptance_knowable_now", c["target_text"], "accepted by God", scope="now")
    cases.append(c)
    c = case("A02", "Salvation can be lost if a person abandons faith in Christ.", "Retain the stated loss condition without inferring a comprehensive mechanism.")
    claim(c, "loss_possible", c["target_text"], "Salvation", condition="if a person abandons faith in Christ")
    cases.append(c)
    c = case("A03", "Salvation cannot be lost.", "Voiced denial of possible loss; no present knowability claim is asserted.")
    claim(c, "loss_possible", c["target_text"], "Salvation", polarity="denied")
    cases.append(c)
    c = case("A04", "I am unsure whether salvation can be lost.", "Expressed uncertainty is an open issue, not affirmation, denial, or model uncertainty.")
    claim(c, "loss_possible", c["target_text"], "salvation", polarity="unsettled", expression="open_issue", adoption="undetermined", uncertainty="I am unsure")
    cases.append(c)
    c = case("A05", "Some teachers say salvation can be lost. I am only reporting their view.", "Record the reported assertion without assigning its position to the preacher.")
    claim(c, "loss_possible", "Some teachers say salvation can be lost.", "salvation", voice="reported_teachers", adoption="reported_not_adopted", frame=c["target_text"])
    cases.append(c)
    c = case("A06", "Now let us continue.", "Context-only assurance assertion cannot become target evidence.", "Salvation cannot be lost.")
    c["expected_diagnostics"] = [{"reason": "no_in_scope_claim", "span": None}]
    cases.append(c)
    c = case("A07", "I teach that salvation can be lost. I also teach that salvation cannot be lost.", "Preserve two apparent opposing assertions for review; do not vote or characterize a pastor's career.")
    claim(c, "loss_possible", "I teach that salvation can be lost.", "salvation can be lost")
    claim(c, "loss_possible", "I also teach that salvation cannot be lost.", "salvation cannot be lost", polarity="denied")
    cases.append(c)
    c = case("A08", "Some teachers say salvation cannot be lost. I reject that claim.", "Keep the quoted denial and its explicit rejection distinct; do not silently synthesize the opposite proposition.")
    claim(c, "loss_possible", "Some teachers say salvation cannot be lost.", "salvation", polarity="denied", voice="reported_teachers", adoption="explicitly_rejected", frame=c["target_text"])
    cases.append(c)
    c = case("A09", "Can salvation be lost?", "An unanswered question asserts neither position nor explicit uncertainty.")
    claim(c, "loss_possible", c["target_text"], "salvation", polarity="unsettled", expression="question", adoption="undetermined")
    cases.append(c)
    c = case("A10", "You remain saved as long as you continue trusting Christ.", "Retain literal conditional retention; do not infer unstated necessary/sufficient salvation mechanics.")
    claim(c, "retention", c["target_text"], "remain saved", condition="as long as you continue trusting Christ")
    cases.append(c)
    c = case("P01", "I support requiring ramps in new public buildings. The city should adopt that requirement.", "Support and prescription are separate relations bound to the same policy; second assertion resolves its object from the target.")
    claim(c, "public_support", "I support requiring ramps in new public buildings.", "requiring ramps in new public buildings")
    claim(c, "public_requirement", "The city should adopt that requirement.", "requiring ramps in new public buildings", frame=c["target_text"])
    c["provenance_note"] = "Target text reproduces an existing authored public-treatment probe; not natural sermon evidence."
    cases.append(c)
    c = case("P02", "I oppose requiring ramps in new public buildings.", "An affirmed opposition relation is not a generic negative public-treatment score.")
    claim(c, "public_opposition", c["target_text"], "requiring ramps in new public buildings")
    cases.append(c)
    c = case("P03", "The mayor supports requiring ramps in new public buildings. I am reporting her view without endorsing it.", "Bind reported support to its speaker; the preacher's support is unavailable.")
    claim(c, "public_support", "The mayor supports requiring ramps in new public buildings.", "requiring ramps in new public buildings", voice="mayor", adoption="reported_not_adopted", frame=c["target_text"])
    cases.append(c)
    c = case("P04", "The mayor says the city should require ramps in new public buildings. I agree with that recommendation.", "Explicit adoption of a reported recommendation is observable without a pastor-wide policy inference.")
    claim(c, "public_requirement", "The mayor says the city should require ramps in new public buildings.", "require ramps in new public buildings", voice="mayor", adoption="explicitly_adopted", frame=c["target_text"])
    cases.append(c)
    c = case("P05", "I support requiring ramps in new public buildings. I oppose increasing parking fees.", "Criticism of a different object must not reverse the ramp position; preserve the other object as a scope diagnostic.")
    claim(c, "public_support", "I support requiring ramps in new public buildings.", "requiring ramps in new public buildings")
    c["expected_diagnostics"] = [{"reason": "out_of_scope_object", "span": span(c, "I oppose increasing parking fees.")}]
    cases.append(c)
    c = case("P06", "I support requiring ramps in new public buildings if an equivalent accessible entrance is permitted.", "Qualification is attached to this support claim, not discarded in an unconditional position.")
    claim(c, "public_support", c["target_text"], "requiring ramps in new public buildings", condition="if an equivalent accessible entrance is permitted")
    cases.append(c)
    c = case("P07", "I support that proposal.", "Do not invent a ramp policy when the referent is absent.")
    c["expected_diagnostics"] = [{"reason": "unresolved_subject", "span": span(c, c["target_text"])}]
    cases.append(c)
    c = case("P08", "I support that requirement.", "Context may resolve the object of target endorsement, but cannot supply endorsement itself.", "The proposal requires ramps in new public buildings.")
    claim(c, "public_support", c["target_text"], "requires ramps in new public buildings", subject_field="leading_context")
    cases.append(c)
    c = case("P09", "I do not yet know whether I support requiring ramps in new public buildings.", "Preserve expressed undecided support rather than treating it as opposition.")
    claim(c, "public_support", c["target_text"], "requiring ramps in new public buildings", polarity="unsettled", expression="open_issue", adoption="undetermined", uncertainty="I do not yet know")
    cases.append(c)
    c = case("P10", "I do not oppose requiring ramps in new public buildings.", "Denied opposition does not establish an affirmed support or prescription relation.")
    claim(c, "public_opposition", c["target_text"], "requiring ramps in new public buildings", polarity="denied")
    cases.append(c)
    for c in cases:
        c["source_fingerprint"] = digest({k: c[k] for k in ("target_text", "leading_context", "trailing_context")})
    payload = {"version": VERSION, "status": "authored_design_expectations_not_model_results",
               "production_effect": "none", "broad_g1_expansion_authorized": False,
               "required_before_expansion": ["G2_design", "G3_design"],
               "scope": {"assurance_relations": sorted(RELATIONS["salvation_acceptance"]),
                         "public_proposition": "city requirement for ramps in new public buildings",
                         "public_relations": sorted(RELATIONS["city_ramp_requirement"])},
               "cases": cases}
    validate(payload)
    return {**payload, "content_fingerprint": digest(payload)}


def validate(packet):
    if packet["production_effect"] != "none" or packet["broad_g1_expansion_authorized"] is not False or packet["required_before_expansion"] != ["G2_design", "G3_design"]:
        raise ValueError("Bounded design/expansion guardrail changed")
    if {c["case_id"] for c in packet["cases"]} != {f"{family}{i:02}" for family in "AP" for i in range(1, 11)} or len(packet["cases"]) != 20:
        raise ValueError("Proof must contain exactly the 20 prepared cases")
    ids = set()
    def validate_span(c, s, target_only=False):
        if s["source_field"] not in {"target_text", "leading_context", "trailing_context"}:
            raise ValueError("Unknown span source")
        if target_only and s["source_field"] != "target_text":
            raise ValueError("A claim must be evidenced in target")
        source = c[s["source_field"]]
        if not (0 <= s["start"] < s["end"] <= len(source)) or source[s["start"]:s["end"]] != s["text"]:
            raise ValueError("Invalid grounded span")
    for c in packet["cases"]:
        if c["source_fingerprint"] != digest({k: c[k] for k in ("target_text", "leading_context", "trailing_context")}):
            raise ValueError("Changed case source")
        for r in c["expected_claims"]:
            if r["claim_id"] in ids or r["case_id"] != c["case_id"]:
                raise ValueError("Duplicate/misbound claim ID")
            ids.add(r["claim_id"])
            if r["relation"] not in RELATIONS.get(r["subject_id"], set()):
                raise ValueError("Out-of-scope relation/subject")
            if r["polarity"] not in {"affirmed", "denied", "unsettled"} or r["expression"] not in {"assertion", "question", "open_issue"}:
                raise ValueError("Unknown polarity/expression")
            if r["adoption"] not in {"own_assertion", "explicitly_adopted", "reported_not_adopted", "explicitly_rejected", "undetermined"}:
                raise ValueError("Unknown adoption")
            validate_span(c, r["claim_span"], target_only=True)
            validate_span(c, r["subject_evidence"])
            if not r["binding_evidence"]:
                raise ValueError("Missing binding evidence")
            for evidence in r["binding_evidence"]:
                validate_span(c, evidence, target_only=True)
            for condition in r["conditions"]:
                if condition["kind"] not in {"condition", "exception"}:
                    raise ValueError("Unknown qualification kind")
                validate_span(c, condition["span"], target_only=True)
            if r["epistemic_status"] == "expressed_uncertainty":
                if r["epistemic_evidence"] is None:
                    raise ValueError("Expressed uncertainty needs evidence")
                validate_span(c, r["epistemic_evidence"], target_only=True)
            elif r["epistemic_status"] != "not_stated" or r["epistemic_evidence"] is not None:
                raise ValueError("Unknown epistemic state/evidence")
            if r["scope_text"] is not None:
                validate_span(c, r["scope_evidence"], target_only=True)
                if r["scope_text"] != r["scope_evidence"]["text"]:
                    raise ValueError("Scope text must be grounded")
            elif r["scope_evidence"] is not None:
                raise ValueError("Unexpected scope evidence")
        for d in c["expected_diagnostics"]:
            if d["span"] is not None:
                validate_span(c, d["span"], target_only=True)
    if "content_fingerprint" in packet and packet["content_fingerprint"] != digest({k: v for k, v in packet.items() if k != "content_fingerprint"}):
        raise ValueError("Packet fingerprint changed")


def render(packet):
    lines = ["# G1 authored proof cases V1", "", "These are prepared contract expectations, not measured sermons or model results.", "",
             f"Fingerprint: `{packet['content_fingerprint']}`", "",
             "Full grounded outputs: [cases-v1.json](cases-v1.json). Semantics and scope: [CONTRACT.md](CONTRACT.md).", ""]
    for c in packet["cases"]:
        lines += [f"## {c['case_id']}", "", f"Target: {c['target_text']}", ""]
        if c["leading_context"]:
            lines += [f"Context only: {c['leading_context']}", ""]
        for r in c["expected_claims"]:
            extra = f"; condition: {r['conditions'][0]['span']['text']}" if r["conditions"] else ""
            lines.append(f"- `{r['relation']}` / {r['polarity']} / {r['expression']}; voice={r['voice']}; adoption={r['adoption']}; epistemic={r['epistemic_status']}{extra}.")
        for d in c["expected_diagnostics"]:
            lines.append(f"- Diagnostic: `{d['reason']}`.")
        lines += ["", f"Interpretation: {c['reason']}", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read/validate artifacts; write nothing")
    args = parser.parse_args()
    packet = build_packet()
    outputs = [(HERE / "cases-v1.json", json.dumps(packet, indent=2, ensure_ascii=False) + "\n"),
               (HERE / "CASES.md", render(packet))]
    if args.check:
        validate(json.loads(outputs[0][0].read_text()))
        for path, content in outputs:
            if path.read_text() != content:
                raise SystemExit(f"Artifact drift: {path.name}; inspect before rebuilding")
        print("PASS: 20 authored cases, grounded spans, scope guardrail and fingerprints; no inference or dataset validation")
    else:
        for path, content in outputs:
            path.write_text(content)
        print("Prepared 20 authored design cases; no inference or dataset validation")


if __name__ == "__main__":
    main()
