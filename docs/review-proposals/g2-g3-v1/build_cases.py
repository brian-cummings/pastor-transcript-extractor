"""Prepare authored G2/G3 design examples; no collector, provider or database access."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
RELATIONS = {"explains_text", "reason_supports_claim", "distinguishes_concepts", "addresses_alternative",
             "qualifies_claim", "works_out_implication", "grounds_response", "specifies_response_step", "addresses_response_obstacle"}
ACTS = {"acknowledgment", "perspective_taking", "reassurance", "challenge", "warning", "invitation", "concrete_care"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def span(c, text, source="target_text"):
    matches = list(re.finditer(r"(?<!\w)" + re.escape(text) + r"(?!\w)", c[source]))
    if len(matches) != 1:
        raise ValueError(f"{c['case_id']}: nonunique/missing source phrase {text!r}")
    start = matches[0].start()
    return {"source_field": source, "start": start, "end": start + len(text), "text": text}


def case(case_id, target, reason, context="", completeness="local_complete"):
    return {"case_id": case_id, "family": case_id[:2], "target_text": target,
            "leading_context": context, "trailing_context": "", "reason": reason,
            "episode": {"episode_id": f"{case_id}:episode", "completeness": completeness,
                        "boundary_status": "authored_candidate_not_reviewed_natural_run"},
            "nodes": [], "relations": [], "operations": [], "address_acts": [], "diagnostics": []}


def node(c, role, text, source="target_text", voice="preacher", adoption="own_assertion", reference_status=None):
    node_id = f"{c['case_id']}:node-{len(c['nodes'])+1}"
    c["nodes"].append({"node_id": node_id, "role": role, "span": span(c, text, source), "voice": voice, "adoption": adoption,
                       "reference_status": (reference_status or "source_named_unverified") if role == "text_anchor" else None})
    return node_id


def relation(c, kind, left, right, text=None, adoption="own_assertion"):
    c["relations"].append({"relation_id": f"{c['case_id']}:relation-{len(c['relations'])+1}",
        "kind": kind, "from_node_id": left, "to_node_id": right,
        "evidence_span": span(c, text or c["target_text"]), "voice": "preacher" if adoption == "own_assertion" else "reported_speaker",
        "adoption": adoption, "status": "authored_supported_observation"})


def operation(c, kind, text_node, claim_node, text, demonstration="performed"):
    c["operations"].append({"operation_id": f"{c['case_id']}:operation-{len(c['operations'])+1}",
        "kind": kind, "text_node_id": text_node, "claim_node_id": claim_node,
        "evidence_span": span(c, text), "demonstration": demonstration,
        "voice": "preacher", "adoption": "own_assertion", "correctness": "unassessed"})


def act(c, kind, circumstance, utterance, *, evidence=None, addressee="direct_current_listener",
        adoption="own_assertion", qualifiers=(), voice="preacher"):
    c["address_acts"].append({"act_id": f"{c['case_id']}:act-{len(c['address_acts'])+1}",
        "kind": kind, "circumstance_node_id": circumstance, "utterance_node_id": utterance,
        "relation_evidence_span": span(c, evidence or c["target_text"]),
        "addressee": addressee, "voice": voice, "adoption": adoption,
        "qualifications": [span(c, t) for t in qualifiers],
        "status": "authored_supported_observation", "inner_empathy": None, "listener_effect": None})


def build_packet():
    cases = []
    c = case("G2-01", "Romans 12:15 says, 'Weep with them that weep.' Weeping with mourners means sharing their grief, not telling them to stop.", "Text and explanation are explicitly bound; accuracy/fidelity is not certified.")
    a=node(c,"text_anchor","Romans 12:15 says, 'Weep with them that weep.'")
    b=node(c,"teaching_statement","Weeping with mourners means sharing their grief, not telling them to stop.")
    relation(c,"explains_text",a,b); operation(c,"wording_explanation",a,b,c["target_text"])
    cases.append(c)
    c = case("G2-02", "Romans 12:15 says, 'Weep with them that weep.' The city should revise its parking rules.", "Adjacent Scripture quotation and policy assertion do not establish a text-support/explanation edge.")
    node(c,"text_anchor","Romans 12:15 says, 'Weep with them that weep.'"); node(c,"teaching_statement","The city should revise its parking rules.")
    c["diagnostics"]=["no_supported_text_explanation_or_grounding_in_candidate"]
    cases.append(c)
    c = case("G2-03", "A shared visiting schedule prevents duplicate visits. Therefore coordinate the visits with one calendar.", "Stated reason grounds a response; developing an application is not listener success.")
    a=node(c,"reason","A shared visiting schedule prevents duplicate visits."); b=node(c,"listener_response","Therefore coordinate the visits with one calendar.")
    relation(c,"grounds_response",a,b)
    cases.append(c)
    c = case("G2-04", "Call your lonely neighbor today.", "Concrete instruction is observed; no rationale or addressed obstacle is supplied.")
    a=node(c,"listener_response",c["target_text"]); b=node(c,"guidance","today")
    relation(c,"specifies_response_step",a,b)
    c["diagnostics"]=["no_stated_rationale_in_complete_candidate"]
    cases.append(c)
    c = case("G2-05", "Call your lonely neighbor. If your work schedule is tight, begin with a five-minute call. That small contact can interrupt isolation.", "Response has a stated rationale and guidance addressing a particular obstacle.")
    a=node(c,"listener_response","Call your lonely neighbor."); b=node(c,"guidance","begin with a five-minute call")
    d=node(c,"obstacle","If your work schedule is tight"); e=node(c,"reason","That small contact can interrupt isolation.")
    relation(c,"specifies_response_step",a,b); relation(c,"addresses_response_obstacle",d,b); relation(c,"grounds_response",e,a)
    cases.append(c)
    c = case("G2-06", "Some think forgiveness means denying an injury. But forgiveness need not erase the wrong; it concerns relinquishing retaliation.", "An alternative is actually answered; reporting its existence alone would not establish engagement.")
    a=node(c,"alternative","Some think forgiveness means denying an injury.",voice="reported_people",adoption="reported_not_adopted")
    b=node(c,"teaching_statement","But forgiveness need not erase the wrong; it concerns relinquishing retaliation.")
    relation(c,"addresses_alternative",a,b)
    cases.append(c)
    c = case("G2-07", "Forgiving a person concerns retaliation; trusting them concerns future access. They are different responses. I am distinguishing these responses only in the context of restoring a relationship.", "A demonstrated distinction is retained without a depth score or a verdict that the account is correct.")
    a=node(c,"teaching_statement","Forgiving a person concerns retaliation"); b=node(c,"teaching_statement","trusting them concerns future access")
    relation(c,"distinguishes_concepts",a,b)
    d=node(c,"teaching_statement","They are different responses.")
    q=node(c,"qualification","only in the context of restoring a relationship"); relation(c,"qualifies_claim",q,d)
    cases.append(c)
    c = case("G2-08", "This is a profoundly ontological, epistemological and hermeneutical reality. It is profound.", "Technical vocabulary and repetition do not demonstrate an explanatory facet.")
    node(c,"teaching_statement",c["target_text"]); c["diagnostics"]=["no_supported_development_relation_in_candidate"]
    cases.append(c)
    c = case("G2-09", "Let us continue.", "An explanation supplied only by context does not become target G2 evidence.", "The verse describes shared grief rather than forced cheerfulness.")
    c["diagnostics"]=["context_only_explanation_excluded"]
    cases.append(c)
    c = case("G2-10", "Some argue, 'Pain always proves guilt; therefore blame every sufferer.' I reject that argument.", "Reported reasoning remains visible but is not projected as the preacher's adopted reasoning or its synthesized opposite.")
    a=node(c,"reason","Pain always proves guilt",voice="reported_people",adoption="explicitly_rejected")
    b=node(c,"teaching_statement","therefore blame every sufferer",voice="reported_people",adoption="explicitly_rejected")
    relation(c,"reason_supports_claim",a,b,adoption="explicitly_rejected")
    cases.append(c)
    c = case("G2-11", "Therefore share a meal with your neighbor this week.", "Target contains a concrete response; context-only premise cannot make a complete observed grounding relation.", "A grieving neighbor may struggle to prepare meals.",completeness="partial")
    node(c,"listener_response",c["target_text"]); c["diagnostics"]=["continuation_required_for_premise_response_binding"]
    cases.append(c)
    c = case("G2-12", "I always interpret every verse by studying its immediate context.", "A stated method is not a demonstrated interpretive operation.")
    a=node(c,"teaching_statement",c["target_text"])
    operation(c,"immediate_context_reasoning",None,a,c["target_text"],demonstration="self_described_not_demonstrated")
    cases.append(c)
    c = case("G2-13", "Verse 2 addresses the entire group, so the command in verse 3 is communal rather than private.", "Demonstrated immediate-context reasoning can be observed without an identified verified biblical passage.")
    a=node(c,"text_anchor","Verse 2 addresses the entire group",reference_status="source_unresolved"); b=node(c,"teaching_statement","the command in verse 3 is communal rather than private")
    relation(c,"explains_text",a,b); operation(c,"immediate_context_reasoning",a,b,c["target_text"])
    c["diagnostics"]=["specific_scripture_anchor_unresolved"]
    cases.append(c)
    c = case("G2-14", "Uncoordinated meal visits can leave some homes oversupplied and others without food. Therefore shared care requires an agreed schedule. In practice this means checking that schedule before delivering a meal.", "Stated support and worked implication are linked to a specific claim, without certifying soundness.")
    a=node(c,"reason","Uncoordinated meal visits can leave some homes oversupplied and others without food.")
    b=node(c,"teaching_statement","Therefore shared care requires an agreed schedule.")
    d=node(c,"implication","In practice this means checking that schedule before delivering a meal.")
    relation(c,"reason_supports_claim",a,b); relation(c,"works_out_implication",b,d)
    cases.append(c)
    c = case("G3-01", "To those grieving a loss: your pain can make ordinary tasks feel exhausting.", "Acknowledgment addresses an expressed circumstance; no diagnosis or knowledge of actual listeners is inferred.")
    a=node(c,"circumstance","grieving a loss"); b=node(c,"utterance","your pain can make ordinary tasks feel exhausting")
    act(c,"acknowledgment",a,b)
    cases.append(c)
    c = case("G3-02", "Grief is an important subject in religious literature.", "Topic mention is not listener-directed acknowledgment.")
    node(c,"circumstance","Grief"); c["diagnostics"]=["topic_only_no_bound_address_act"]
    cases.append(c)
    c = case("G3-03", "If you are grieving, you may wonder whether anyone can understand the silence at home.", "Expressed possible perspective is observed without asserting that listeners actually feel it.")
    a=node(c,"circumstance","grieving"); b=node(c,"utterance","you may wonder whether anyone can understand the silence at home")
    act(c,"perspective_taking",a,b)
    cases.append(c)
    c = case("G3-04", "If you are grieving, you do not have to face this alone. I cannot promise that the pain will end tomorrow.", "Reassurance has an explicit limit; neither truth nor actual benefit is certified.")
    a=node(c,"circumstance","grieving"); b=node(c,"utterance","you do not have to face this alone")
    act(c,"reassurance",a,b,qualifiers=("I cannot promise that the pain will end tomorrow.",))
    cases.append(c)
    c = case("G3-05", "If you have hurt a friend, admitting it may feel difficult. Tell them honestly what you did, and apologize today.", "Acknowledgment and challenge coexist; neither cancels the other or creates a global kindness score.")
    a=node(c,"circumstance","have hurt a friend"); b=node(c,"utterance","admitting it may feel difficult"); d=node(c,"utterance","Tell them honestly what you did, and apologize today.")
    act(c,"acknowledgment",a,b); act(c,"challenge",a,d)
    cases.append(c)
    c = case("G3-06", "If you are grieving and want company, ask our care team to visit. We can bring a meal while we sit with you.", "Invitation and specified offered care are observed; no actual visit or delivered meal is claimed.")
    a=node(c,"circumstance","grieving and want company"); b=node(c,"utterance","ask our care team to visit"); d=node(c,"utterance","We can bring a meal while we sit with you.")
    act(c,"invitation",a,b,qualifiers=("If you are grieving and want company",)); act(c,"concrete_care",a,d,qualifiers=("If you are grieving and want company",))
    cases.append(c)
    c = case("G3-07", "I am deeply empathetic and I care about everyone.", "A care self-description supplies no demonstrated circumstance-sensitive address act.")
    node(c,"self_description",c["target_text"]); c["diagnostics"]=["self_description_not_demonstrated_address"]
    cases.append(c)
    c = case("G3-08", "Some people tell mourners, 'Stop crying.' I reject that advice.", "Rejected reported challenge is not the preacher's adopted challenge and does not manufacture reassurance.")
    a=node(c,"circumstance","mourners",voice="reported_people",adoption="reported_not_adopted"); b=node(c,"utterance","Stop crying",voice="reported_people",adoption="explicitly_rejected")
    act(c,"challenge",a,b,addressee="reported_person",adoption="explicitly_rejected",voice="reported_people")
    cases.append(c)
    c = case("G3-09", "God, comfort those who are grieving.", "Prayer addressed to God is not a direct address act toward listeners.")
    node(c,"utterance",c["target_text"]); c["diagnostics"]=["prayer_to_God_not_listener_address"]
    cases.append(c)
    c = case("G3-10", "In the old story, a king told a grieving soldier, 'Stop crying.'", "Narrated address is retained as reported material, not adopted current-listener challenge.")
    a=node(c,"circumstance","grieving soldier",voice="narrator",adoption="reported_not_adopted"); b=node(c,"utterance","Stop crying",voice="king_in_story",adoption="reported_not_adopted")
    act(c,"challenge",a,b,addressee="reported_historical_person",adoption="reported_not_adopted",voice="king_in_story")
    cases.append(c)
    c = case("G3-11", "If you need company through this loss, invite a trusted friend to sit with you.", "Context resolves the loss while the target supplies the circumstance-linked invitation.", "I am speaking to those grieving the death of a loved one.")
    a=node(c,"circumstance","grieving the death of a loved one",source="leading_context"); b=node(c,"utterance","invite a trusted friend to sit with you")
    act(c,"invitation",a,b,qualifiers=("If you need company through this loss",))
    cases.append(c)
    c = case("G3-12", "Let us continue.", "Context-only acknowledgment cannot become target address evidence.", "To those grieving, I know these days may feel heavy.")
    c["diagnostics"]=["context_only_address_excluded"]
    cases.append(c)
    c = case("G3-13", "You should not feel this way.", "Unresolved circumstance and ambiguous address function require abstention from a bound posture characterization.")
    node(c,"utterance",c["target_text"]); c["diagnostics"]=["unresolved_circumstance_and_address_function"]
    cases.append(c)
    c = case("G3-14", "If you have lied to a friend, continuing the lie can damage trust. Tell the truth before the harm grows.", "Warning and challenge share a circumstance; warning alone does not establish condemnation or manipulation.")
    a=node(c,"circumstance","have lied to a friend"); b=node(c,"utterance","continuing the lie can damage trust"); d=node(c,"utterance","Tell the truth before the harm grows.")
    act(c,"warning",a,b); act(c,"challenge",a,d)
    cases.append(c)
    for c in cases:
        c["episode"]["source_target_id"] = f"{c['case_id']}:authored-target"
        c["episode"]["source_span"] = span(c,c["target_text"])
        c["source_fingerprint"]=digest({k:c[k] for k in ("target_text","leading_context","trailing_context")})
    payload={"version":"g2-g3-contract-cases-v1", "status":"authored_design_expectations_not_model_results", "production_effect":"none",
             "g1_implementation_authorized":False, "broad_g1_expansion_authorized":False, "g4_status":"deferred_reuse_G1_G2_evidence",
             "implementation_priority":"undecided_pending_joint_review", "cases":cases}
    validate(payload)
    return {**payload,"content_fingerprint":digest(payload)}


def validate(packet):
    if (packet["production_effect"]!="none" or packet["g1_implementation_authorized"] is not False or packet["broad_g1_expansion_authorized"] is not False
            or packet["g4_status"]!="deferred_reuse_G1_G2_evidence" or packet["implementation_priority"]!="undecided_pending_joint_review"):
        raise ValueError("Design scope/hold changed")
    if len(packet["cases"])!=28 or {c["case_id"] for c in packet["cases"]}!={f"{f}-{i:02}" for f in ("G2","G3") for i in range(1,15)}:
        raise ValueError("Exactly 28 prepared cases required")
    def grounded(c,s,target=False):
        if s["source_field"] not in {"target_text","leading_context","trailing_context"}:
            raise ValueError("Unknown span source")
        if target and s["source_field"]!="target_text":
            raise ValueError("Semantic act/relation must be target-grounded")
        source=c[s["source_field"]]
        if not (0<=s["start"]<s["end"]<=len(source)) or source[s["start"]:s["end"]]!=s["text"]:
            raise ValueError("Invalid grounded span")
    for c in packet["cases"]:
        if c["source_fingerprint"]!=digest({k:c[k] for k in ("target_text","leading_context","trailing_context")}):
            raise ValueError("Source changed")
        grounded(c,c["episode"]["source_span"],True)
        nodes={n["node_id"]:n for n in c["nodes"]}
        if len(nodes)!=len(c["nodes"]):
            raise ValueError("Duplicate node ID")
        for n in nodes.values():
            grounded(c,n["span"])
            if n["role"]=="text_anchor" and n["reference_status"] not in {"source_named_unverified","source_unresolved"}:
                raise ValueError("Authored anchor cannot certify a verified passage")
        for r in c["relations"]:
            if c["family"]!="G2" or r["kind"] not in RELATIONS or r["from_node_id"] not in nodes or r["to_node_id"] not in nodes:
                raise ValueError("Invalid G2 relation/endpoints")
            grounded(c,r["evidence_span"],True)
            grounded(c,nodes[r["from_node_id"]]["span"],True); grounded(c,nodes[r["to_node_id"]]["span"],True)
        for o in c["operations"]:
            if o["claim_node_id"] not in nodes or (o["text_node_id"] is not None and o["text_node_id"] not in nodes):
                raise ValueError("Unknown operation endpoint")
            if o["demonstration"] not in {"performed","self_described_not_demonstrated"} or o["correctness"]!="unassessed":
                raise ValueError("Operation demonstration/correctness invalid")
            if o["demonstration"]=="performed" and o["text_node_id"] is None:
                raise ValueError("Performed operation needs textual endpoint")
            grounded(c,o["evidence_span"],True)
            grounded(c,nodes[o["claim_node_id"]]["span"],True)
            if o["text_node_id"] is not None:
                grounded(c,nodes[o["text_node_id"]]["span"],True)
        for a in c["address_acts"]:
            if c["family"]!="G3" or a["kind"] not in ACTS or a["circumstance_node_id"] not in nodes or a["utterance_node_id"] not in nodes:
                raise ValueError("Invalid G3 act/endpoints")
            if nodes[a["circumstance_node_id"]]["role"]!="circumstance" or nodes[a["utterance_node_id"]]["role"]!="utterance":
                raise ValueError("Misbound address roles")
            grounded(c,nodes[a["utterance_node_id"]]["span"],True); grounded(c,a["relation_evidence_span"],True)
            for q in a["qualifications"]:
                grounded(c,q,True)
            if a["inner_empathy"] is not None or a["listener_effect"] is not None:
                raise ValueError("Address cannot certify empathy or listener effect")
    if "content_fingerprint" in packet and packet["content_fingerprint"]!=digest({k:v for k,v in packet.items() if k!="content_fingerprint"}):
        raise ValueError("Fingerprint changed")


def render(packet):
    lines=["# G2/G3 authored design cases V1","","Prepared expectations, not measured sermons or model outputs.","",
           f"Fingerprint: `{packet['content_fingerprint']}`","","Full structures: [cases-v1.json](cases-v1.json). See [G2](G2_CONTRACT.md), [G3](G3_CONTRACT.md) and [joint review](REVIEW.md).",""]
    for family in ("G2","G3"):
        lines += [f"## {family} cases",""]
        for c in packet["cases"]:
            if c["family"]!=family: continue
            lines += [f"### {c['case_id']}","",f"Target: {c['target_text']}",""]
            if c["leading_context"]: lines += [f"Context only: {c['leading_context']}",""]
            lines += [f"Episode: {c['episode']['completeness']}; boundaries are authored candidates.",""]
            for r in c["relations"]: lines += [f"- Relation: `{r['kind']}`; adoption={r['adoption']}."]
            for o in c["operations"]: lines += [f"- Operation: `{o['kind']}`; {o['demonstration']}; correctness unassessed."]
            for a in c["address_acts"]: lines += [f"- Address: `{a['kind']}`; addressee={a['addressee']}; adoption={a['adoption']}."]
            for d in c["diagnostics"]: lines += [f"- Diagnostic: `{d}`."]
            lines += ["",f"Interpretation: {c['reason']}",""]
    return "\n".join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true",help="Read/validate existing artifacts; write nothing")
    args=parser.parse_args(); packet=build_packet()
    outputs=[(HERE/"cases-v1.json",json.dumps(packet,indent=2,ensure_ascii=False)+"\n"),(HERE/"CASES.md",render(packet))]
    if args.check:
        validate(json.loads(outputs[0][0].read_text()))
        for p,s in outputs:
            if p.read_text()!=s: raise SystemExit(f"Artifact drift: {p.name}")
        print("PASS: 28 authored cases; source spans, endpoints, holds and reproducibility; no semantic validation")
    else:
        for p,s in outputs: p.write_text(s)
        print("Prepared 28 authored design cases; no inference or dataset validation")


if __name__=="__main__": main()
