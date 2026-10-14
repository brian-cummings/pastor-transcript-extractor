"""Isolated source-span G3 feasibility pilot; never a production collector."""
from __future__ import annotations

import json
from pathlib import Path

from pastor_transcript_extractor.analysis_artifact_cache import write_json_markdown
from pastor_transcript_extractor.sermon_g2_feasibility_review import ROOT, MODEL, Provider, fp, file_fp, decision
from pastor_transcript_extractor.sermon_g2_feasibility_revision import validate_answers

HERE = ROOT / "docs/review-proposals/g3-feasibility-v1"
INPUT = HERE / "input-v1.json"
RESULT = ROOT / "evaluation/g3-address/feasibility-v1.results.json"
CACHE = ROOT / "evaluation/g3-address/cache-v1"
VERSION = "g3-independent-address-and-circumstance-choice-v1"
BUILDER = "g3-curated-exact-span-candidate-catalog-v1"
ACTS = {
    "acknowledgment": "Explicit recognition of an addressed person's difficulty or experience; topic mention and self-description do not suffice.",
    "perspective_taking": "Explicitly voices a possible perspective, constraint or concern of the addressed person; do not imagine their feelings.",
    "reassurance": "Offers comfort, support or reassuring assurance to a person; no assessment of accuracy or effect.",
    "challenge": "Calls a person to reconsider or change specified conduct or response.",
    "warning": "Addresses a stated consequence or risk as reason for attention or action.",
    "invitation": "Offers a person an opening to respond, seek help or participate; mere activity description does not suffice.",
    "concrete_care": "Offers or directs a specified act of care; generic service vocabulary and claims to care do not suffice. Delivery is not established.",
}


def questions():
    boundary = (
        "Judge only candidate.utterance in target_text, using the surrounding target to interpret it. "
        "Other target sentences do not supply an act absent from this utterance. Leading/trailing context "
        "may identify a referent but cannot supply an act or circumstance connection. Reported/rejected "
        "person-directed acts can exist without preacher adoption. Address to God is not address to a person. "
        "No opposite act is synthesized from rejection. Each question is independent; no empathy, outcome, "
        "pastor trait or quality judgment. Preserve conditions and limits in the source, not as inferred benefit."
    )
    q = {act: {"instructions": {"task": f"Does candidate.utterance express this person-directed address act: {definition} Judge act existence independently of preacher adoption and the proposed circumstance binding.", "boundary": boundary},
               "criteria": {"observed": "This act is explicitly expressed, including reported or rejected address to a person.", "not_observed": "This act is absent from the specified utterance.", "incomplete": "Missing local evidence prevents determining this act.", "unclear": "Multiple reasonable readings remain; withhold."}}
         for act, definition in ACTS.items()}
    q.update({
        "binding": {"instructions": {"task": "Does the target actually address candidate.circumstance through candidate.utterance? An experience mentioned nearby or advice to another person does not bind. A null circumstance cannot be bound. Context may resolve 'this loss' or an addressee only if the target itself states the connection.", "boundary": boundary}, "criteria": {"bound_in_target": "The target identifies the circumstance and demonstrates the utterance's connection to it.", "bound_context_resolved": "Target demonstrates the connection; only circumstance/addressee identity is resolved by context.", "not_bound": "No demonstrated connection to the specified circumstance, including no circumstance candidate.", "incomplete": "The connection requires omitted treatment.", "unclear": "The particular circumstance connection remains ambiguous."}},
        "addressee": {"instructions": {"task": "Who is addressed by candidate.utterance itself? Do not substitute the sermon audience for a reported speaker's addressee.", "boundary": boundary}, "criteria": {"direct_current_listener": "Current listeners, including a conditional subset ('if you are grieving').", "general_hypothetical": "A general or imagined person without present listener application.", "reported_person": "A person in quoted, narrated, historical or retold speech.", "God": "God in prayer.", "no_address": "Description or topic discussion without address.", "unresolved": "Addressee cannot be resolved."}},
        "voice": {"instructions": {"task": "What is the source voice of candidate.utterance? Source voice is distinct from adoption.", "boundary": boundary}, "criteria": {"preacher": "Preacher's own present words, including prayer.", "quoted_or_reported": "Words attributed to another speaker, Scripture, or a retold conversation, including the preacher's past speech.", "mixed": "Specified utterance includes both voices.", "unresolved": "Voice ambiguous."}},
        "adoption": {"instructions": {"task": "What stance does the preacher take toward the address expressed in candidate.utterance? Retelling one's past conversation is not present listener application; it remains reported unless explicitly adopted now. Do not infer an opposite address from rejection.", "boundary": boundary}, "criteria": {"own_or_adopted": "Own present address or explicitly adopted reported address.", "not_adopted_report": "Reported address without explicit present adoption.", "explicitly_rejected": "Target explicitly rejects that address.", "unresolved": "Stance unresolved or no definite address to adopt."}},
        "boundary": {"instructions": {"task": "Is enough local target treatment supplied to judge this utterance and circumstance connection? Context cannot supply omitted address. This does not certify complete episode boundaries.", "boundary": boundary}, "criteria": {"local_sufficient": "Enough local evidence to decide, including definite absence of address/binding.", "continuation_required": "Required act, connection or referent remains outside target evidence.", "unclear": "Local sufficiency unresolved."}},
    })
    return q


def span(c, text, field="target_text"):
    start = c[field].index(text)
    return {"source_field": field, "start": start, "end": start + len(text), "text": text}


def pair(c, circumstance, utterance, expected, reason, *, field="target_text"):
    return {"candidate_id": f"{c['case_id']}:candidate-{len(c['candidates'])}",
            "circumstance": span(c, circumstance, field) if circumstance else None,
            "utterance": span(c, utterance), "expected": expected, "review_reason": reason}


def prepare():
    authored_path = ROOT / "docs/review-proposals/g2-g3-v1/cases-v1.json"
    cases = []
    for original in json.loads(authored_path.read_text())["cases"]:
        if original["family"] != "G3":
            continue
        c = {k: original[k] for k in ("case_id", "target_text", "leading_context", "trailing_context")}
        c.update(origin="authored", source={"path": str(authored_path.relative_to(ROOT)), "case_id": c["case_id"]}, candidates=[])
        nodes = {n["node_id"]: n for n in original["nodes"]}
        for act in original["address_acts"]:
            node = nodes[act["utterance_node_id"]]
            existing = next((p for p in c["candidates"] if p["utterance"] == node["span"]), None)
            if existing:
                existing["expected"][act["kind"]] = "observed"
                continue
            circ = nodes[act["circumstance_node_id"]]["span"]
            reported = c["case_id"] in {"G3-08", "G3-10"}
            expected = {act["kind"]: "observed", "binding": "bound_context_resolved" if circ["source_field"] != "target_text" else "bound_in_target", "addressee": "reported_person" if reported else "direct_current_listener", "voice": "quoted_or_reported" if reported else "preacher", "adoption": "explicitly_rejected" if c["case_id"] == "G3-08" else "not_adopted_report" if reported else "own_or_adopted", "boundary": "local_sufficient"}
            if c["case_id"] in {"G3-08", "G3-10"}:
                expected.update(reassurance="not_observed", concrete_care="not_observed")
            c["candidates"].append(pair(c, circ["text"], node["span"]["text"], expected, original["reason"], field=circ["source_field"]))
        if not c["candidates"]:
            circumstances = {"G3-02": "Grief", "G3-09": "grieving", "G3-12": "grieving"}
            expected = {a: "not_observed" for a in ACTS} if c["case_id"] != "G3-13" else {"binding": ["not_bound", "unclear", "incomplete"], "boundary": ["continuation_required", "unclear"]}
            if c["case_id"] != "G3-13":
                expected.update(binding="not_bound", addressee="God" if c["case_id"] == "G3-09" else "direct_current_listener" if c["case_id"] == "G3-12" else "no_address")
            c["candidates"].append(pair(c, circumstances.get(c["case_id"]), c["target_text"], expected, original["reason"], field="leading_context" if c["case_id"] == "G3-12" else "target_text"))
        cases.append(c)

    controls = [
        ("G3-proximity", "Some listeners are grieving. Volunteers, join the parking team on Sunday.", "grieving", "Volunteers, join the parking team on Sunday.", {"invitation": "observed", "binding": "not_bound", "acknowledgment": "not_observed", "concrete_care": "not_observed"}, "Invitation to volunteers does not address the adjacent grief circumstance."),
        ("G3-wrong-object", "To those grieving, you need not face this alone. To those organizing parking, ask the office for cones.", "grieving", "ask the office for cones", {"binding": "not_bound", "reassurance": "not_observed", "concrete_care": "not_observed"}, "Reassurance elsewhere and guidance for another group cannot transfer to this utterance."),
        ("G3-cut-off", "To those grieving, the help I want to offer you is", "grieving", "the help I want to offer you is", {"concrete_care": ["incomplete", "unclear", "not_observed"], "boundary": "continuation_required"}, "The help is cut off; no specific care can be credited."),
        ("G3-report-only", "A counselor told the mourner, 'You need not face this alone.'", "mourner", "You need not face this alone", {"reassurance": "observed", "binding": "bound_in_target", "addressee": "reported_person", "voice": "quoted_or_reported", "adoption": "not_adopted_report"}, "Reported reassurance exists without present preacher adoption."),
    ]
    for cid, text, circumstance, utterance, expected, reason in controls:
        c = dict(case_id=cid, target_text=text, leading_context="", trailing_context="", origin="authored_control", source={"path": str(Path(__file__).relative_to(ROOT)), "control": cid}, candidates=[])
        c["candidates"].append(pair(c, circumstance, utterance, expected, reason)); cases.append(c)

    natural_specs = [
        ("source-material-review-v1.json", 1200, 32, [
            ("when you got children", "Especially when you got children, life is very busy, right?", {"acknowledgment": "observed", "binding": "bound_in_target", "voice": "preacher", "addressee": "direct_current_listener"}, "Natural constraint acknowledgment, not proof of internal empathy; rhetorical reading remains adjudicable."),
            ("when you got children", "let's just keep them busy", {"binding": "not_bound", "voice": "quoted_or_reported", "adoption": "not_adopted_report", "acknowledgment": "not_observed"}, "Reported adversarial plan is not pastoral acknowledgment of parents.")]),
        ("source-material-review-v1.json", 4430, 57, [
            ("I don't think God can forgive me", "if you confess your sins, he is faithful and just to forgive your sins and to cleanse you from all unrighteousness", {"reassurance": "observed", "binding": "bound_in_target", "addressee": "reported_person", "voice": "quoted_or_reported", "adoption": ["not_adopted_report", "unresolved"]}, "Preacher retells past Scripture-based reassurance to a man; no present-listener address or verified effect. Present adoption is contestable, so retain report."),
            ("I don't think God can forgive me", "And I encouraged him and we prayed together.", {"concrete_care": "not_observed", "acknowledgment": "not_observed", "addressee": "no_address"}, "Narration of encouragement/prayer does not supply the actual addressed utterance or evidence of benefit.")]),
        ("listener-directives-review-v3.json", 590, 64, [
            ("dire need of the gospel", "I'd encourage you to pray for our\nmissionaries, pray for evangelism,\nand participate in it", {"invitation": "observed", "acknowledgment": "not_observed", "concrete_care": "not_observed", "addressee": "direct_current_listener"}, "Generic participation is a real invitation; not acknowledgment/care for missionaries or proof of empathy. Need/mission relation not labeled as unambiguous circumstance binding."),
            ("dire need of the gospel", "Heavenly Father, Lord, I just want to pray a prayer of\nsubmission before you just now", {"addressee": "God", "binding": "not_bound", **{a: "not_observed" for a in ACTS}}, "Transition into prayer must not inherit the preceding listener invitation.")]),
    ]
    sources = {str(authored_path.relative_to(ROOT)): file_fp(authored_path), str(Path(__file__).relative_to(ROOT)): file_fp(Path(__file__))}
    for filename, video, block, specs in natural_specs:
        path = ROOT / "evaluation/sermon-topics" / filename
        sources[str(path.relative_to(ROOT))] = file_fp(path)
        original = next(c for c in json.loads(path.read_text())["cases"] if c.get("video_id") == video and c.get("block_id") == block)
        c = {k: original[k] for k in ("target_text", "leading_context", "trailing_context")}
        c.update(case_id=f"natural-{video}-{block}", origin="natural", source={"path": str(path.relative_to(ROOT)), "video_id": video, "block_id": block, "segment_indexes": original.get("segment_indexes"), "start_seconds": original.get("start_seconds"), "end_seconds": original.get("end_seconds")}, candidates=[])
        for circumstance, utterance, expected, reason in specs:
            c["candidates"].append(pair(c, circumstance, utterance, expected, reason))
        cases.append(c)
    packet = {"version": VERSION, "builder_version": BUILDER, "status": "prepared_not_evaluated", "production_effect": "none", "model": MODEL, "threshold": .8, "questions": questions(), "question_digest": fp(questions()), "sources": sources, "cases": cases, "candidate_scope": "Curated grounded catalog, not automatic extraction; completeness only against this frozen catalog, not a sermon/corpus recall claim.", "holds": ["G1 implementation/expansion", "G2 tuning", "full G3 collection", "G4", "broader collection", "pastor projection/comparison/scoring"], "budget": {"provider_request_ceiling": sum(len(c["candidates"]) for c in cases), "question_count": sum(len(c["candidates"]) * len(questions()) for c in cases), "sdk_retries": 0, "candidates_per_request": 1}}
    packet["content_fingerprint"] = fp(packet)
    return packet


def validate_packet(packet):
    if packet != prepare():
        raise ValueError("Frozen G3 packet or sources changed; regenerate and review before validation")
    for c in packet["cases"]:
        for p in c["candidates"]:
            for s in (p["circumstance"], p["utterance"]):
                if s is not None and c[s["source_field"]][s["start"]:s["end"]] != s["text"]:
                    raise ValueError("Ungrounded candidate")
            if p["utterance"]["source_field"] != "target_text":
                raise ValueError("Utterance outside target")


def state_for(c, candidate):
    return {"target_text": c["target_text"], "leading_context": c["leading_context"], "trailing_context": c["trailing_context"], "candidate": {k: candidate[k] for k in ("circumstance", "utterance")}}


def provisional(decisions):
    eligible = decisions["binding"] in {"bound_in_target", "bound_context_resolved"} and decisions["addressee"] == "direct_current_listener" and decisions["adoption"] == "own_or_adopted" and decisions["boundary"] == "local_sufficient"
    return [a for a in ACTS if eligible and decisions[a] == "observed"]


def evaluate(packet, *, provider_factory=Provider, cache_dir=CACHE):
    validate_packet(packet)
    rows = []; provider = None; requests = hits = 0
    for c in packet["cases"]:
        for p in c["candidates"]:
            state = state_for(c, p)
            identity = {"state": state, "questions": questions(), "model": packet["model"], "version": VERSION, "source_fingerprints": packet["sources"]}
            key = fp(identity); path = cache_dir / f"{key}.json"; response = None
            if path.exists():
                try:
                    cached = json.loads(path.read_text())
                    if cached["identity"] != identity or cached["content_fingerprint"] != fp({k: v for k, v in cached.items() if k != "content_fingerprint"}):
                        raise ValueError("Invalid cache")
                    validate_answers(cached["response"]["answers"], questions())
                    if cached["response"]["resolved_model"] != packet["model"]:
                        raise ValueError("Cached model mismatch")
                    response = cached["response"]; hits += 1
                except (ValueError, KeyError, TypeError):
                    response = None
            if response is None:
                if requests >= packet["budget"]["provider_request_ceiling"]:
                    raise ValueError("Provider request ceiling exceeded")
                if provider is None:
                    provider = provider_factory()
                requests += 1; response = provider.assess(state, questions())
                validate_answers(response["answers"], questions())
                if response["resolved_model"] != packet["model"]:
                    raise ValueError("Resolved model mismatch")
                cached = {"identity": identity, "response": response}; cached["content_fingerprint"] = fp(cached)
                cache_dir.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(cached, indent=2) + "\n")
            decisions = {k: decision(v) for k, v in response["answers"].items()}
            checks = []
            for field, expected in p["expected"].items():
                allowed = expected if isinstance(expected, list) else [expected]
                observed = decisions[field]
                status = "direct_match" if observed in allowed else "withheld_or_missed" if observed in {"unclear", "unresolved", "incomplete", "continuation_required"} or (field in ACTS and observed == "not_observed" and "observed" in allowed) else "conflicting_judgment_requires_A_B_C_review"
                checks.append({"field": field, "expected": allowed, "observed": observed, "status": status})
            rows.append({"case_id": c["case_id"], "candidate_id": p["candidate_id"], "candidate": {k: p[k] for k in ("circumstance", "utterance")}, "raw_answers": response["answers"], "decisions": decisions, "provisional_current_listener_acts": provisional(decisions), "checks": checks, "review_reason": p["review_reason"], "cache_key": key, "usage": response.get("usage", {})})
    validate_packet(packet)
    report = {"version": VERSION, "status": "evaluated_pending_PTE_interpretation_and_Brian_decision", "production_effect": "none", "input_fingerprint": packet["content_fingerprint"], "question_digest": packet["question_digest"], "execution": {"provider_requests": requests, "cache_hits": hits}, "candidate_omissions_against_frozen_catalog": [], "automatic_sermon_candidate_recall": "not_tested", "rows": rows}
    report["content_fingerprint"] = fp(report)
    return report


def render_input(packet):
    lines = ["# G3 bounded inputs V1", "", f"Input: `{packet['content_fingerprint']}`", "", f"{len(packet['cases'])} cases; {packet['budget']['provider_request_ceiling']} candidate requests; {packet['budget']['question_count']} judgments maximum. Prepared, not evaluated.", "", packet["candidate_scope"]]
    for c in packet["cases"]:
        lines.extend(["", f"## {c['case_id']} ({c['origin']})", "", c["target_text"], "", f"Leading context: {c['leading_context']}", f"Trailing context: {c['trailing_context']}"])
        for p in c["candidates"]:
            lines.extend(["", f"Candidate `{p['candidate_id']}`: `{json.dumps(p, ensure_ascii=False)}`"])
    return "\n".join(lines) + "\n"


def render_results(report, packet):
    cases = {c["case_id"]: c for c in packet["cases"]}
    lines = ["# G3 bounded feasibility results V1", "", report["status"], "", f"Input `{report['input_fingerprint']}`; execution `{json.dumps(report['execution'])}`.", "", "No collection, projection, empathy or quality score. Candidate completeness refers only to the prepared catalog. All observed acts and provisional bindings require semantic review; no automatic PASS."]
    for row in report["rows"]:
        c = cases[row["case_id"]]
        lines.extend(["", f"## {row['candidate_id']}", "", c["target_text"], "", f"Context: {c['leading_context']} / {c['trailing_context']}", "", f"Candidate: `{json.dumps(row['candidate'], ensure_ascii=False)}`", "", row["review_reason"], "", f"Decisions: `{json.dumps(row['decisions'])}`", f"Provisional listener acts: `{row['provisional_current_listener_acts']}`", "", "| Check | Expected | Observed | Screen |", "| --- | --- | --- | --- |"])
        lines.extend(f"| {x['field']} | {', '.join(x['expected'])} | {x['observed']} | {x['status']} |" for x in row["checks"])
    return "\n".join(lines) + "\n"


def run(mode="evaluate"):
    if mode not in {"prepare", "check", "evaluate"}:
        raise ValueError("Unsupported G3 mode")
    if mode == "prepare":
        packet = prepare(); validate_packet(packet)
        write_json_markdown(INPUT, packet, render_input(packet))
        (HERE / "questions-v1.json").write_text(json.dumps({"version": VERSION, "digest": fp(questions()), "questions": questions()}, indent=2) + "\n")
        print(f"Prepared {len(packet['cases'])} G3 cases; provider_requests=0")
        return
    packet = json.loads(INPUT.read_text()); validate_packet(packet)
    inventory = json.loads((HERE / "questions-v1.json").read_text())
    if inventory != {"version": VERSION, "digest": fp(questions()), "questions": questions()}:
        raise ValueError("Question artifact changed")
    if mode == "check":
        print("G3 proposal integrity checked; provider_requests=0"); return
    try:
        report = evaluate(packet)
    except Exception as error:
        failure = {"status": "execution_failed_no_semantic_decision", "input_fingerprint": packet["content_fingerprint"], "error_type": type(error).__name__, "successful_caches_retained": True}
        write_json_markdown(RESULT.with_name("feasibility-v1.execution-failure.json"), failure, "# G3 execution failure\n\nNo semantic decision; successful caches retained.\n")
        raise
    write_json_markdown(RESULT, report, render_results(report, packet))
    print(f"G3 results: {RESULT}; {report['execution']}; pending interpretation and Brian decision")
