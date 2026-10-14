"""Deterministically author a review packet from fixed designs and frozen results.

Never invokes a provider, reads a database, or computes pastor projections.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from contract import Packet

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ACTS = ("acknowledgment", "perspective_taking", "reassurance", "challenge", "warning", "invitation", "concrete_care")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads((ROOT / path).read_text())


def span(text, start=0, role="target"):
    return dict(role=role, start=start, end=start + len(text), text=text,
                segment_id=None, start_seconds=None, end_seconds=None)


def evidence(eid, text, payload):
    return dict(
        evidence_id=eid, capability={"leaf": "registry", "claim_design_only": "G1_design",
                                      "relation": "G2", "address": "G3"}[payload["kind"]],
        source=dict(recording_id="design-recording-1", transcript_sha256=None, target_sha256=sha(text.encode()),
                    target_text=text, leading_context="", trailing_context="", source_path=None,
                    source_pointer=None, sermon_id="design-sermon-1", sermon_date=None,
                    date_basis="unknown", series_id="design-series-1", period_id=None),
        spans=[span(text)], unit_id=eid + ":unit",
        eligibility=dict(membership="reviewed_member", content="eligible", policy_version="authored-design-v1",
                         review_ref="synthetic-only: no real pastor membership certified"),
        provenance=dict(origin="synthetic_design", input_path=None, input_pointer=None, result_path=None,
                        result_pointer=None, question_semantics="Authored wire-shape example; no measured answer",
                        question_version="design-v1", question_digest=None, candidate_builder="authored-v1",
                        requested_model=None, resolved_model=None, model_resolution="not_applicable",
                        decision_policy="authored-design-only", raw_output_ref=None, answer_provenance_ref=None,
                        semantic_review="authored_expectation", compatibility="compatible", reused_from=[]),
        independence=dict(utterance_group=eid, episode_group=None, recording_group="design-recording-1",
                          sermon_group="design-sermon-1", repeated_material_group=None, group_review="authored"),
        coverage=dict(local_boundary="sufficient", episode_boundary="proposed", candidate_discovery="unknown",
                      sermon_assessment="partial", opportunities="unknown"),
        observation_state="positive_local", payload=payload)


def address(**overrides):
    x=dict(kind="address", acts={a: "not_observed" for a in ACTS},
           circumstance_relevance="relevant_in_target", recipient_binding="bound_in_target",
           addressee="direct_current_listener", voice="preacher", adoption="own_or_adopted", qualifications=[])
    x["acts"]["invitation"] = "observed"
    x.update(overrides)
    return x


def field(cid, wording, supporting=(), unresolved=(), counter=(), availability="local_examples",
          reasons=(), missing=(), estimand="E0"):
    return dict(characteristic_id=cid, subject_scope="supplied_passage", estimand_id=estimand, interpretation_version="consumer-design-v1",
                availability=availability, claim_level="local_example" if supporting or (counter and availability == "negative_in_unit") else "unavailable",
                supporting=list(supporting), counter=list(counter), unresolved=list(unresolved),
                required_missing=list(missing), suppression_reasons=list(reasons), visible_wording=wording,
                uncertainty_wording="Selected local evidence only; sermon coverage, opportunities and recurring pattern are unestablished.",
                population_rate=None, recurring_characterization=None, comparison=None, quality_score=None)


def case(cid, purpose, rows, fields, groups=None, origin="synthetic_design", forbidden=()):
    return dict(case_id=cid, purpose=purpose, origin=origin, evidence=rows,
                expected=dict(fields=fields, retained_evidence=[e["evidence_id"] for e in rows],
                              unique_utterance_groups=groups if groups is not None else len({e["independence"]["utterance_group"] for e in rows}),
                              independently_eligible_sermons=None if origin != "synthetic_design" else len({e["independence"]["sermon_group"] for e in rows if e["eligibility"]["membership"] == "reviewed_member" and e["eligibility"]["content"] == "eligible" and e["provenance"]["compatibility"] == "compatible"}),
                              series_period_note="Series dependence retained; no recurrence or effective-sample-size estimate.",
                              forbidden_wording=list(forbidden)))


def field_contracts():
    # Product question first; compatible inputs never replace that question.
    rows = [
        ("C01", "Which subjects organize teaching?", "Measured topic attention within a named corpus", ["E0", "E2"], ["T:* canonical prominence"], [], "Topic attention does not establish a position."),
        ("C02", "How are saving action, reception and benefits related?", "Explicit saving relationships with conditions and stance", ["E0", "E1", "E6"], ["nine usable S:*", "G1 design"], ["three unresolved S leaves", "detailed mechanisms and adopted opposing claims"], "Nine leaves do not complete salvation theology."),
        ("C03", "Can salvation be known, lost or retained?", "Qualified assurance/security propositions", ["E0", "E6"], ["G1 design", "S:assurance_security as locator only"], ["G1 held; no observed position"], "Assurance treatment is not assurance polarity."),
        ("C04", "What other theological propositions are affirmed?", "Object-bound theological positions and qualifications", ["E0", "E6"], ["G1 design", "T:* as locators only"], ["G1 held; question-specific positions missing"], "Topic prominence does not supply doctrine."),
        ("C05", "Which modes, appeals and materials occur?", "Specified explanatory/narrative/application modes and requested actions", ["E0", "E1"], ["H:*", "L:*", "M:*"], [], "Mode presence is not developed treatment or quality."),
        ("C06", "How and why are listeners asked to respond?", "Specific response/reason/step/obstacle examples", ["E0", "E1", "E3"], ["G2 response relations", "L:*", "H:practical_application"], ["opportunity coverage", "adequacy unassessed"], "An imperative alone is not developed application."),
        ("C07", "How are public affairs treated?", "Specified reporting/evaluation/mobilization functions", ["E0", "E1", "E3"], ["P:*", "T:society_public_life", "L:civic_action"], ["routing and treatment opportunities"], "Evaluation function is not object-bound ideology."),
        ("C08", "Which public propositions are supported or opposed?", "Bound public object/proposition/stance and reasons", ["E0", "E6"], ["G1 design", "P:* as locators only"], ["G1 held; objects and positions missing"], "Negative public treatment does not identify the opposed proposition."),
        ("C09", "Which Scripture references are detected?", "Detected references with source/detection scope", ["E0", "E1"], ["sermon-basics@4 anchors after compatibility review"], ["anchor adapter not supplied in this packet"], "No detections is not no engagement."),
        ("C10", "How do texts carry teaching and application?", "Directed text/explanation/grounded-response examples", ["E0", "E1", "E3"], ["G2 explains_text and grounds_response", "compatible Scripture anchors"], ["episode coverage", "fidelity unassessed"], "Quotation proximity is not explanation or fidelity."),
        ("C11", "Which interpretive operations are demonstrated?", "Named demonstrated operations, with missing operations visible", ["E0", "E1", "E3"], ["bounded G2 text relations"], ["full operations inventory not validated", "correctness unassessed"], "Self-described method is not demonstrated method."),
        ("C12", "How are people in particular circumstances addressed?", "Independent acts, relevance, recipients, adoption and qualifications", ["E0", "E1", "E3"], ["G3 V2 independent decisions"], ["address opportunities", "conservative binding recall"], "Relevance alone is not current-listener address or empathy."),
        ("C13", "How is a specified subject developed?", "Observed reasons, distinctions, qualifications and implications", ["E0", "E3"], ["bounded G2 facets"], ["full development inventory", "subject/episode adequacy review"], "Relation presence is not depth or quality."),
        ("C14", "How do qualified claims fit together?", "Reviewed cross-claim relations within comparable scopes", ["E0"], ["future G4 after separate authorization"], ["G4 held", "G1 missing"], "Different scopes or stable distributions do not establish incoherence/coherence."),
        ("C15", "Which inventory subjects receive treatment?", "Coverage across the finite topic inventory in a declared corpus", ["E0", "E4"], ["T:*"], ["defined treatment criterion", "exposure sensitivity"], "Overlapping topic scores are not exclusive proportions or theological completeness."),
        ("C16", "Which canonical areas are detected?", "Detected-reference breadth in a declared corpus", ["E0", "E4"], ["compatible Scripture anchors"], ["anchor adapter", "exposure/detection sensitivity"], "Reference breadth is not faithful exposition breadth."),
        ("C17", "Do measured patterns recur across series/periods?", "Feature-specific recurrence and variation", ["E0", "E5"], ["compatible registry observations", "reviewed dates and series"], ["recurrence/sufficiency policy", "coverage and sensitivity"], "Repeated uploads or one series do not establish usual pastor behavior."),
        ("C18", "Do qualified positions vary or change over time?", "Dated matched propositions with counterevidence", ["E0", "E6"], ["G1 design", "narrow usable S relationships"], ["G1 held", "dated opposing/qualified claims"], "Different objects or unknown dates do not establish change or contradiction."),
        ("C19", "What material is used and with what authority?", "Named material use; authority/adoption separately bound", ["E0", "E1", "E6"], ["M:*", "G1 design for authority function"], ["bound authority role"], "Quotation is not endorsement, affiliation or authority."),
        ("C20", "Where are limits or unresolved questions expressed?", "Explicit uncertainty/qualification attached to a proposition", ["E0", "E6"], ["G1 design", "G2 qualification edges as partial examples"], ["G1 held; epistemic stance not collected"], "Model withholding is not the preacher expressing uncertainty."),
    ]
    return [dict(characteristic_id=c, question=q, target_statement=t, estimand_ids=es, compatible_inputs=inputs,
                 required_gates=["exact semantic compatibility", "reviewed ownership/content eligibility",
                                 "source grounding and appropriate local boundary", "original registry allowed-use gates",
                                 "scope/coverage and independence retained"], missing_information=missing,
                 maximum_packet_claim="unavailable" if c in {"C03", "C04", "C08", "C14", "C18", "C20"} else "local_example",
                 forbidden_inference=forbid) for c,q,t,es,inputs,missing,forbid in rows]


def estimands():
    rows = [
        ("E0", "Evidence-linked local examples", "Supplied reviewed units only", "Distinct source examples, no population numerator", "None: example catalog", "No weighting or rates", "Negative only within specified assessed unit", "descriptive_examples_only"),
        ("E1", "Whole-measured-sermon occurrence", "Eligible independent sermons fully assessed for the named construct", "Sermons with at least one supported occurrence", "All construct-completely assessed eligible independent sermons", "Equal sermon; multiple episodes cap at one", "Whole-sermon reviewed absence; candidate non-detection insufficient", "proposed_inactive"),
        ("E2", "Mean topic attention", "Eligible independent sermons with compatible measured eligible time and separately stated analyzed/eligible coverage", "Sum of per-sermon duration-weighted normalized expected canonical Score/4", "Within sermon: measured eligible duration; across sermons: independent measured sermon count", "Equal sermon after duration weighting within each sermon, per registry; retain overlapping topics", "Canonical distributions on measured blocks; unmeasured eligible time remains unknown", "proposed_inactive"),
        ("E3", "Opportunity-conditional act/facet occurrence", "All reviewed opportunities for a named subject/circumstance and recipient type", "Opportunities containing the specified bound adopted act/facet", "All eligible fully assessed opportunities, including act/facet-negative ones", "Report episode-weighted rate plus proposed equal-sermon sensitivity separately", "Explicit act/facet-negative opportunity assessments", "proposed_inactive"),
        ("E4", "Finite-inventory breadth", "Fixed corpus and inventory with sufficient per-item assessment", "Inventory items meeting a separately reviewed treatment/detection criterion", "Fixed inventory size, only if all items assessable; else partial catalog", "Report item identities, corpus exposure and saturation sensitivity", "Assess all inventory items; unknowns remain unknown", "proposed_inactive"),
        ("E5", "Series/period recurrence and variation", "Fully assessed sermons partitioned by reviewed series and actual sermon periods", "Per-stratum occurrences or prominence summaries", "Per-stratum construct-completely assessed independent sermons", "Sermon-first summaries; leave-one-series-out and time sensitivity; no universal cutoff", "Same negative requirements as underlying estimand", "proposed_inactive"),
        ("E6", "Qualified position/uncertainty catalog and dated variation", "Object/proposition-matched adopted claims in stated conditions and time scope", "No scalar numerator: retain affirmed/rejected/qualified/explicitly-uncertain records", "No frequency denominator without separately defined claim opportunities", "No pooled polarity average; dates and scopes remain attached", "Missing claim is not denial or expressed uncertainty", "proposed_inactive"),
    ]
    return [dict(estimand_id=i,target=t,population=p,numerator=n,denominator=d,weighting=w,negatives_required=neg,
                 missingness="Unassessed units, unknown opportunities and incompatible measurements are separately reported; never zero-filled or silently dropped from a target population.",
                 independence="Collapse duplicate uploads/overlaps within sermons; retain repeated-material, series and period dependence without treating all as one sermon.",
                 activation_requirements=[] if i == "E0" else ["separate implementation decision", "candidate discovery/assessment coverage validation", "production calibration", "reviewed eligibility and denominators", "feature-specific sufficiency and uncertainty policy", "request economics review"],status=status)
            for i,t,p,n,d,w,neg,status in rows]


def frozen(cap, case_id, row_index=0):
    folder = "g2-binding" if cap == "G2" else "g3-address"
    base = f"docs/review-proposals/{cap.lower()}-feasibility-v2/input-v2.json"
    result = f"evaluation/{folder}/feasibility-v2.results.json"
    inp, out = read(base), read(result)
    ci = next(i for i,c in enumerate(inp["cases"]) if c["case_id"] == case_id)
    src = inp["cases"][ci]
    if cap == "G2":
        ri = next(i for i,c in enumerate(out["cases"]) if c["case_id"] == case_id)
        row = out["cases"][ri]["rows"][row_index]
        ptr = f"/cases/{ri}/rows/{row_index}"
        pair = row["pair"]
        payload=dict(kind="relation",relation="explains_text",left_span=0,right_span=1,
                     decision=row["decisions"]["explains_text"],left_voice=row["decisions"]["left_voice"],
                     right_voice=row["decisions"]["right_voice"],adoption=row["decisions"]["adoption"])
        spans=[span(pair[k]["text"],pair[k]["start"]) for k in ["left","right"]]
        raw_ref=ptr+"/raw_answers"
        answer_ref=ptr+"/answer_provenance"
    else:
        ri = next(i for i,r in enumerate(out["rows"]) if r["case_id"] == case_id)
        row = out["rows"][ri]
        ptr=f"/rows/{ri}"
        d=row["decisions"]
        payload=address(acts={a:d[a] for a in ACTS},circumstance_relevance=d["circumstance_relevance"],
                        recipient_binding=d["recipient_circumstance_binding"],addressee=d["addressee"],
                        voice=d["voice"],adoption=d["adoption"])
        spans=[]
        for k in ["utterance","circumstance"]:
            s=row["candidate"][k]
            if s:
                role={"target_text":"target","leading_context":"leading_context","trailing_context":"trailing_context"}[s["source_field"]]
                spans.append(span(s["text"],s["start"],role))
        raw_ref=ptr+"/raw_answers"
        answer_ref=ptr+"/reuse_provenance"
    e=evidence("frozen:"+case_id,src["target_text"],payload)
    e["spans"]=spans
    e["source"].update(recording_id="frozen:"+case_id, source_path=base,source_pointer=f"/cases/{ci}",
                        leading_context=src["leading_context"], trailing_context=src["trailing_context"],
                        sermon_id=None,series_id=None)
    e["eligibility"].update(membership="unknown",content="unknown",policy_version="pilot-not-membership-certification",review_ref=None)
    e["independence"].update(utterance_group="frozen:"+case_id,recording_group="frozen:"+case_id,
                             sermon_group=None,group_review="unreviewed")
    e["coverage"].update(candidate_discovery="frozen_catalog_only",local_boundary="sufficient" if row["decisions"]["boundary"] == "local_sufficient" else "unknown")
    e["provenance"].update(origin="frozen_provider_output",input_path=base,input_pointer=f"/cases/{ci}",
        result_path=result,result_pointer=ptr,question_semantics="Independent frozen "+cap+" V2 decisions; per-answer reuse semantics stay at answer_provenance_ref",
        question_version=out.get("question_version",out["version"]),question_digest=out["question_digest"],
        candidate_builder=out.get("builder_version","frozen-grounded-catalog-v2"),requested_model="jev-1.13.0",
        resolved_model=None,model_resolution="unresolved",decision_policy=out.get("policy_version","g3-v2-frozen-0.80-choice-policy"),
        raw_output_ref=raw_ref,answer_provenance_ref=answer_ref,semantic_review="bounded_feasibility_review",reused_from=[base,result])
    if cap == "G2" and payload["decision"] != "linked":
        e["observation_state"] = "negative_in_unit" if payload["decision"] == "not_linked" and e["coverage"]["local_boundary"] == "sufficient" else "judgment_withheld"
    # Full per-answer provenance is referenced, not flattened into a falsely resolved model.
    return e


def cases():
    rows=[]
    leaves=[evidence("leaf:"+c,"Authored example: "+label,dict(kind="leaf",contract_id=c,observed_statement=label))
            for c,label in [("T:suffering_adversity_death","Suffering receives attention in this design example."),
                            ("H:exegetical_exposition","This design example contains explanation of biblical text."),
                            ("L:serve","This design example asks listeners to help people in need.")]]
    rows.append(case("A01","Useful partial profile with registry leaves and missing richer constructs",leaves,[
        field("C01","This supplied example attends to suffering.",["leaf:T:suffering_adversity_death"]),
        field("C05","The supplied examples include text explanation and a request to help people.",["leaf:H:exegetical_exposition","leaf:L:serve"]),
        field("C03","Assurance position is not characterized: G1 has not been collected.",availability="not_collected",missing=["G1 propositions"]),
        field("C06","Application development is not characterized: the action request alone does not establish reasons or steps.",availability="not_collected",missing=["G2 response relations"]),
        field("C12","Circumstance-bound address is not characterized: thematic and action evidence alone do not establish it.",availability="not_collected",missing=["G3 address bindings"])],forbidden=["complete profile","empathetic pastor"]))
    for cid,label,why in [("G2-01","A02","Supported directed text explanation"),("G2-02","A03","Adjacent unrelated assertion is not a text edge")]:
        e=frozen("G2",cid)
        good=cid=="G2-01"
        rows.append(case(label,why,[e],[field("C10",
            "The frozen passage links Romans 12:15 to an explanation of weeping with mourners; fidelity is unassessed." if good else "The adjacent parking assertion is not linked as an explanation of Romans 12:15.",
            supporting=[e["evidence_id"]] if good else [],counter=[] if good else [e["evidence_id"]],
            availability="local_examples" if good else "judgment_withheld",reasons=["pastor attribution unavailable: pilot eligibility unknown"],missing=["reviewed pastor ownership and eligibility"])],origin="frozen_provider_output",forbidden=["deep pastor","faithful interpretation"]))
    for label,cid,wording in [
        ("A04","G3-09","The frozen prayer concerns grief and addresses God; human-recipient binding is negative. It supplies no current-listener address evidence."),
        ("A05","G3-06","The frozen care act and relevance remain visible; recipient binding is withheld. Grief-sensitive current-listener care is unresolved."),
        ("A06","G3-01","The frozen acknowledgment and perspective-taking acts remain visible; circumstance relevance is unclear even though recipient binding is positive."),
        ("A07","G3-08","The frozen reported/rejected address remains visible; it does not become adopted current-listener address or an invented opposite act."),
        ("A08","G3-14","The frozen passage supports local current-listener challenge and warning. Pilot ownership is unknown; recurring posture is unestablished."),
        ("A09","natural-1200-32","The source-linked busy-parent passage retains relevance and its act decisions; recipient binding is withheld. No current-listener posture is confirmed."),
    ]:
        e=frozen("G3",cid)
        purpose={"A04":"Prayer relevance without human address", "A05":"Known care act with withheld recipient binding", "A06":"Known acknowledgment with unclear relevance", "A07":"Reported/rejected address without adoption transfer", "A08":"Positive local challenge and warning", "A09":"Natural busy-parent evidence with withheld binding"}[label]
        rows.append(case(label,purpose,[e],[field("C12",wording,supporting=[e["evidence_id"]] if label=="A08" else [],
            unresolved=[] if label=="A08" else [e["evidence_id"]],availability="local_examples" if label=="A08" else "judgment_withheld",
            reasons=["recurring posture held", "pilot eligibility unknown"],missing=["reviewed pastor ownership and eligibility","opportunity denominator"])],
            origin="frozen_provider_output",forbidden=["empathetic pastor","uncaring pastor","usually comforts"]))
    resolved=evidence("context:resolved","If you need company through this loss, come speak with us.",address(circumstance_relevance="relevant_context_resolved",recipient_binding="bound_context_resolved"))
    resolved["source"]["leading_context"]="Some of you are grieving a loss."
    resolved["spans"].append(span("grieving a loss",16,"leading_context"))
    leak=evidence("context:only","Please turn to the next page.",address(acts={a:"not_observed" for a in ACTS},circumstance_relevance="not_relevant",recipient_binding="not_bound"))
    leak["source"]["leading_context"]="If you are grieving, come speak with us."
    rows.append(case("A10","Context resolves identity but cannot import an absent target act",[resolved,leak],[field("C12","The first target invites company through the context-identified loss. The second target supplies no grief address; its context invitation is not imported.",[resolved["evidence_id"]],counter=[leak["evidence_id"]])]))
    dup=deepcopy(resolved);dup["evidence_id"]="duplicate:upload";dup["unit_id"]="duplicate:candidate"
    overlap=deepcopy(resolved);overlap["evidence_id"]="duplicate:overlap";overlap["unit_id"]="overlap:candidate"
    repeat=deepcopy(resolved);repeat["evidence_id"]="repeat:series";repeat["source"].update(recording_id="design-recording-2",sermon_id="design-sermon-2")
    repeat["independence"].update(utterance_group="second-sermon-utterance",recording_group="design-recording-2",sermon_group="design-sermon-2")
    for e in [resolved,dup,overlap,repeat]: e["independence"]["repeated_material_group"]="shared-invitation"
    rows.append(case("A11","Duplicates and overlaps share an occurrence; series repetition remains dependent",[resolved,dup,overlap,repeat],[field("C12","Four locators represent two utterance groups in two design sermons from one series, sharing repeated material; no recurring pastor characterization.",[e["evidence_id"] for e in [resolved,dup,overlap,repeat]])],groups=2))
    conflict=deepcopy(leaves[0]);conflict["evidence_id"]="conflict:ownership";conflict["eligibility"]["membership"]="conflict"
    incompatible=deepcopy(leaves[1]);incompatible["evidence_id"]="conflict:version";incompatible["provenance"]["compatibility"]="incompatible"
    excluded=deepcopy(leaves[2]);excluded["evidence_id"]="excluded:content";excluded["eligibility"]["content"]="excluded"
    rows.append(case("A12","Ownership conflict, incompatible semantics and excluded content remain distinct",[conflict,incompatible,excluded],[
        field("C01","Pastor attribution is excluded pending ownership review.",unresolved=[conflict["evidence_id"]],availability="excluded",reasons=["ownership conflict"]),
        field("C10","The existing version is incompatible for this text-development field.",unresolved=[incompatible["evidence_id"]],availability="incompatible",reasons=["semantic version mismatch"]),
        field("C05","The supplied content is excluded by eligibility policy.",unresolved=[excluded["evidence_id"]],availability="excluded",reasons=["content excluded"]) ]))
    rows.append(case("A13","Unknown recall/opportunities forbid apparent rates",[leaves[2]],[field("C05","A selected passage requests service. Sermon occurrence, conditional rate and recurring tendency are withheld.",[leaves[2]["evidence_id"]],reasons=["candidate recall unknown","opportunities unknown"],estimand="E1")],forbidden=["100% of sermons","usually asks"]))
    claims=[evidence("claim:scope-1","Assistance is appropriate for families in this emergency.",dict(kind="claim_design_only",object="emergency assistance",relation="appropriate_for",expression="affirmed",conditions=["families in this emergency"],voice="preacher",adoption="own_or_adopted")),
            evidence("claim:scope-2","Permanent subsidy is not appropriate for this unrelated program.",dict(kind="claim_design_only",object="unrelated permanent subsidy",relation="appropriate_for",expression="rejected",conditions=["this unrelated program"],voice="preacher",adoption="own_or_adopted"))]
    rows.append(case("A14","Design-only contrary claims preserve different objects/scopes; no G1 activation",claims,[field("C08","Two synthetic claim records concern different objects and conditions. Real public positions remain uncollected.",unresolved=[e["evidence_id"] for e in claims],availability="not_collected",missing=["G1 implementation decision and observations"]),field("C14","Coherence is unavailable; these scoped differences are not an automatic contradiction.",availability="downstream_held",missing=["separately authorized G4"])],forbidden=["incoherent pastor","changed position"]))
    other=deepcopy(leaves[0]);other["evidence_id"]="other:topic";other["source"].update(recording_id="design-other",sermon_id="design-other")
    other_text="Illness can isolate people. Please bring a meal to your sick neighbor."
    other["source"].update(target_text=other_text,target_sha256=sha(other_text.encode()))
    other["spans"]=[span(other_text)]
    other["independence"].update(utterance_group="other-utterance",recording_group="design-other",sermon_group="design-other")
    explanation=frozen("G2","G2-01")
    rows.append(case("A15","Two same-theme example panels; no pastor comparison computation",[explanation,other],[field("C10","Panel A links a text to an explanation of weeping with mourners. Panel B names illness and requests a meal. These supplied examples illustrate different treatments of suffering; recurrence, position agreement and relative merit are unestablished.",[explanation["evidence_id"],other["evidence_id"]],reasons=["panel examples only; no pastor attribution"])],origin="mixed",forbidden=["more caring","same theology","cluster exemplar"]))
    partial=deepcopy(resolved);partial["evidence_id"]="boundary:partial";partial["coverage"]["local_boundary"]="incomplete";partial["observation_state"]="boundary_incomplete"
    rows.append(case("A16","Incomplete evidence and unavailable salvation leaves never become negatives",[partial],[field("C12","The local address connection needs continuation; it is withheld, not a negative occurrence.",unresolved=[partial["evidence_id"]],availability="boundary_incomplete",reasons=["continuation required"]),field("C02","Repentance reception, obedience condition/means and obedience consequence/evidence remain measurement-unresolved.",availability="measurement_unresolved",missing=["S:repentance_as_receiving_response","S:obedience_as_condition_or_means","S:obedience_as_consequence_or_evidence"]) ]))
    negative=evidence("negative:unit","Please turn to page seven.",address(acts={a:"not_observed" for a in ACTS},circumstance_relevance="not_relevant",recipient_binding="not_bound"))
    negative["observation_state"]="negative_in_unit"
    rows.append(case("A17","Reviewed negative in one unit is distinct from missingness and sermon absence",[negative],[field("C12","No specified pastoral address act is observed in this complete target utterance. This establishes no absence elsewhere in the sermon.",counter=[negative["evidence_id"]],availability="negative_in_unit")],forbidden=["never comforts","no pastoral care in the sermon"]))
    return rows


def build():
    paths=["docs/review-proposals/pastor-contracts-v1/registry-v1.json",
           "docs/PASTOR_PROFILE_GAP_ANALYSIS.md",
           "evaluation/sermon-topics/source-material-review-v1.json",
           "evaluation/g2-binding/feasibility-stage-gate-v2.json",
           "evaluation/g3-address/feasibility-stage-gate-v2.json"]
    for cap,folder in [("g2","g2-binding"),("g3","g3-address")]:
        paths += [f"docs/review-proposals/{cap}-feasibility-v2/input-v2.json",f"evaluation/{folder}/feasibility-v2.results.json"]
    packet=dict(version="profile-evidence-consumer-v1",status="prepared_for_design_review",production_effect="none",
                holds=["G1 implementation/expansion", "G2/G3 construct retuning", "full capability collection", "G4", "pastor projection/comparison", "quality scores"],
                sources=[dict(path=p,sha256=sha((ROOT/p).read_bytes())) for p in paths],
                field_contracts=field_contracts(),downstream_holds={f"D{i:02}":"Unavailable: separate downstream design, coverage and implementation authorization required" for i in range(1,7)},
                estimands=estimands(),cases=cases())
    return Packet.model_validate(packet).model_dump()


if __name__ == "__main__":
    packet=build()
    (HERE/"packet-v1.json").write_text(json.dumps(packet,indent=2,ensure_ascii=False)+"\n")
    (HERE/"schema-v1.json").write_text(json.dumps(Packet.model_json_schema(),indent=2)+"\n")
    lines=["# Prepared consumer expectations V1", "", "Generated from the fixed authored packet. These are expected views for a future consumer, not executed consumer results. Frozen provider outputs are distinguished from synthetic design inputs. No real pastor attribution is certified.", ""]
    for c in packet["cases"]:
        lines += [f"## {c['case_id']}: {c['purpose']}", "", f"Input origin: `{c['origin']}`.", ""]
        for e in c["evidence"]:
            lines += [f"- `{e['evidence_id']}` — {e['source']['target_text']}"]
            if e["provenance"]["origin"] == "frozen_provider_output":
                p=e["provenance"]
                lines += [f"  Frozen result: [{p['result_path']}](../../../{p['result_path']}) at `{p['result_pointer']}`; original case/source locator: [{p['input_path']}](../../../{p['input_path']}) at `{p['input_pointer']}/source`."]
            lines += ["  Payload: `"+json.dumps(e["payload"],ensure_ascii=False)+"`."]
        lines += ["", "Expected visible fields:", ""]
        for f in c["expected"]["fields"]:
            lines += [f"- **{f['characteristic_id']} / {f['availability']}**: {f['visible_wording']}"]
        ex=c["expected"]
        count=json.dumps(ex['independently_eligible_sermons'])
        lines += ["",f"Retain {len(ex['retained_evidence'])} evidence locators; {ex['unique_utterance_groups']} distinct utterance groups in this packet. Independently eligible sermon count: `{count}` (synthetic counts are design-only; null means unestablished). {ex['series_period_note']}","","All rates, recurring characterizations, comparisons and quality scores remain null. Exact evidence links, required missing inputs and suppression reasons are in `packet-v1.json`.",""]
    (HERE/"CASES.md").write_text("\n".join(lines))
    lines=["# C01–C20 field contract catalog V1", "", "Target meanings precede input selection. All fields retain source grounding, semantic compatibility, reviewed ownership/content eligibility and original registry use gates. The packet permits passage examples only; inactive estimands do not activate projection.", "", "| ID | Product question / target | Compatible inputs | Required missing information | Proposed estimands | Prohibited inference |", "| --- | --- | --- | --- | --- | --- |"]
    for f in packet["field_contracts"]:
        lines += [f"| {f['characteristic_id']} | {f['question']} {f['target_statement']} | {'; '.join(f['compatible_inputs'])} | {'; '.join(f['missing_information']) or 'No new observable type for the narrow target; coverage/projection gates remain.'} | {', '.join(f['estimand_ids'])} | {f['forbidden_inference']} |"]
    lines += ["", "D01–D06 remain unavailable downstream constructs. No distance, cluster, rank, exemplar or noteworthy-pastor computation is defined or activated here.", ""]
    (HERE/"FIELD_CATALOG.md").write_text("\n".join(lines))
    print("Authored packet-v1.json and schema-v1.json; no provider or dataset operations.")
