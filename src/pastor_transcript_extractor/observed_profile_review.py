"""Fixed provider-free consumer acceptance and self-contained human review output."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from pastor_transcript_extractor.observed_profile import FROZEN_PACKET_SHA256, ROOT, STATUS_LABELS, VERSION, consume, load_packet

DEFAULT_OUTPUT = ROOT / "evaluation/observed-profile-consumer-v1"


def acceptance(case: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    """Compare generated decisions with frozen oracles, never edit either side."""
    failures: list[str] = []
    differences: list[dict[str, Any]] = []
    expected = case["expected"]
    fields = {f["characteristic_id"]: f for f in view["fields"]}
    if set(fields) != {f"C{i:02}" for i in range(1, 21)}:
        failures.append("Desired fields were lost from the partial view")
    if view["retained_evidence"] != expected["retained_evidence"]:
        failures.append("A supplied evidence locator was lost")
    if view["unique_utterance_groups"] != expected["unique_utterance_groups"]:
        failures.append("Overlaps/duplicates inflated example groups")
    for original, visible in zip(case["evidence"], view["evidence"]):
        if any(visible.get(k) != v for k, v in original.items()):
            failures.append("Supplied observation/provenance changed: " + original["evidence_id"])
    for f in view["fields"]:
        for held in ("population_rate", "recurring_characterization", "comparison", "quality_score"):
            if f[held] is not None:
                failures.append("Held output became active: " + held)
        if not f["suppression_reasons"]:
            failures.append("Missing field limitation: " + f["characteristic_id"])
        by_id = {e["evidence_id"]: e for e in case["evidence"]}
        for eid in f["supporting"]:
            e = by_id[eid]
            p = e["payload"]
            if (e["eligibility"]["membership"] == "conflict" or e["eligibility"]["content"] == "excluded" or
                e["provenance"]["compatibility"] != "compatible" or e["coverage"]["local_boundary"] != "sufficient" or
                e["observation_state"] != "positive_local"):
                failures.append("Unsupported evidence received field credit: " + eid)
            if p["kind"] == "claim_design_only":
                failures.append("G1 design became measured evidence")
            if p["kind"] == "relation" and (p["decision"] != "linked" or p["adoption"] != "own_or_adopted"):
                failures.append("Unsupported relation/adoption received credit")
            if p["kind"] == "leaf" and f["characteristic_id"] in {"C06", "C10", "C11", "C12", "C13"}:
                failures.append("A narrow leaf substituted for richer observations")
            if p["kind"] == "address" and not (
                "observed" in p["acts"].values() and p["circumstance_relevance"] in {"relevant_in_target", "relevant_context_resolved"} and
                p["recipient_binding"] in {"bound_in_target", "bound_context_resolved"} and
                p["addressee"] == "direct_current_listener" and p["adoption"] == "own_or_adopted"
            ):
                failures.append("Unbound/unadopted address received current-listener credit")
    # Exact source strings are intentionally not forbidden-phrase scanned: a real
    # quotation can contain such language without the consumer adopting it.
    for oracle in expected["fields"]:
        f = fields[oracle["characteristic_id"]]
        for key in ("availability", "supporting", "counter", "unresolved"):
            actual = f[key]
            wanted = oracle[key]
            equal = set(actual) == set(wanted) if isinstance(actual, list) else actual == wanted
            if not equal:
                differences.append(dict(characteristic_id=f["characteristic_id"], property=key,
                                        expected=wanted, actual=actual))
        if not set(oracle["supporting"] + oracle["counter"] + oracle["unresolved"]) <= set(view["retained_evidence"]):
            failures.append("Expected source examples are not visible")
    return dict(case_id=case["case_id"], invariant_status="PASS" if not failures else "FAIL",
                frozen_oracle_match=not differences, failures=failures, oracle_differences=differences,
                prose_review="Human assessment required; generated prose is not compared by phrase matching.")


def build_review(packet: dict[str, Any] | None = None) -> dict[str, Any]:
    packet = load_packet() if packet is None else packet
    cases = []
    for case in packet["cases"]:
        # Expected prose, outcomes and case identifiers are not consumer inputs.
        view = consume(case["evidence"], packet["field_contracts"], packet["estimands"])
        cases.append(dict(case_id=case["case_id"], purpose=case["purpose"], origin=case["origin"],
                          view=view, acceptance=acceptance(case, view)))
    return dict(version=VERSION, status="rendered_pending_human_review", provider_requests=0,
                packet_sha256=FROZEN_PACKET_SHA256, packet_sources=packet["sources"], case_count=len(cases),
                invariant_passes=sum(c["acceptance"]["invariant_status"] == "PASS" for c in cases),
                exact_oracle_matches=sum(c["acceptance"]["frozen_oracle_match"] for c in cases),
                cases=cases)


def _md(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", value).replace("\n", " ")


def _fenced(value: str, language: str = "text") -> str:
    # Source text is literal evidence, including any Markdown-looking content.
    fence = "`" * max(3, 1 + max((len(x) for x in re.findall(r"`+", value)), default=0))
    return fence + language + "\n" + value + "\n" + fence


def _source_link(path: str, label: str, output_dir: Path) -> str:
    target = (ROOT / path).resolve()
    if not target.is_relative_to(ROOT):
        return _md(label) + " (source outside this checkout)"
    href = os.path.relpath(target, output_dir.resolve())
    return "[" + _md(label) + "](<" + href + ">)"


def render_markdown(review: dict[str, Any], output_dir: Path) -> str:
    lines = ["# Observed passage profiles", "",
             "Supplied passage examples only, including synthetic designs and frozen pilot outputs. These views describe observed evidence and its limits; they do not characterize or compare pastors.", "",
             f"{review['case_count']} acceptance cases; {review['invariant_passes']} invariant passes; {review['exact_oracle_matches']} exact frozen state/link matches; zero provider requests.", "",
             "Start with A01 for a partial view, A05 for withheld binding, A08 for supported local address, A11 for duplicates, A12 for exclusions, or A15 for separate examples.", ""]
    lines += [f"- [{c['case_id']}](#{c['case_id'].lower()}): {_md(c['purpose'])}" for c in review["cases"]]
    for c in review["cases"]:
        cid, view = c["case_id"], c["view"]
        lines += ["", f"## {cid}", "", _md(c["purpose"]), "",
                  "**Input origin:** " + _md(c["origin"].replace("_", " ")) + ". Synthetic inputs are design-only; frozen pilot inputs do not certify real pastor ownership/content eligibility.", "",
                  "### Supplied observations and limits", ""]
        anchors = {}
        by_id = {e["evidence_id"]: e for e in view["evidence"]}
        for number, ids in enumerate(view["utterance_groups"].values(), 1):
            anchors.update({eid: f"{cid.lower()}-evidence-{number}" for eid in ids})
        for ids in view["utterance_groups"].values():
            e = by_id[ids[0]]
            lines += [f"- [{_md(e['evidence_id'])}](#{anchors[e['evidence_id']]}): " + _md(" ".join(e["visible_facts"]))]
        lines += ["", "### All 20 desired fields", "",
                  "Observed means a supplied local example. Missing, unavailable and withheld fields remain visible; no negative characteristic follows from missing evidence.", "",
                  "| Field | Question | Availability |", "| --- | --- | --- |"]
        lines += [f"| [{f['characteristic_id']}](#{cid.lower()}-{f['characteristic_id'].lower()}) | {_md(f['question'])} | {_md(f['status_label'])} |" for f in view["fields"]]
        for f in view["fields"]:
            lines += ["", f"### {cid} {f['characteristic_id']}", "", f"**{_md(f['question'])}** — {_md(f['status_label'])}", "",
                      "Desired field: " + _md(f["target_statement"]) + ".", ""]
            if not f["assessments"]:
                lines += ["No compatible observation is supplied. No negative characteristic is inferred.", ""]
            for a in f["assessments"]:
                label = {"supporting": "Supports this local observation", "counter": "Counterexample in this unit", "unresolved": STATUS_LABELS[a["availability"]], "related": "Related material; richer field not established"}[a["role"]]
                lines += [f"**{_md(label)}:** [{_md(a['evidence_id'])}](#{anchors[a['evidence_id']]}).", ""]
                lines += ["- " + _md(reason) for reason in a["reasons"]]
                lines += [""]
            if f["missing_information"]:
                lines += ["**Still missing or unestablished:**", ""]
                lines += ["- " + _md(item) for item in f["missing_information"]]
                lines += [""]
            lines += ["**Why stronger claims are withheld:**", ""]
            lines += ["- " + _md(reason) for reason in f["suppression_reasons"]]
        lines += ["", "### Passages and source decisions", ""]
        for number, ids in enumerate(view["utterance_groups"].values(), 1):
            lines += [f"### {cid} evidence {number}", "", f"{len(ids)} source locator(s) in this utterance group.", ""]
            for eid in ids:
                e = by_id[eid]
                lines += [f"**{_md(eid)}** — {_md(e['provenance']['origin'].replace('_', ' '))}", "",
                          _fenced(e["source"]["target_text"]), ""]
                if e["payload"]["kind"] == "address":
                    lines += ["**Assessed address utterance:**", "", _fenced(e["spans"][0]["text"]), ""]
                lines += [_md(e["reading_note"]), ""]
                lines += ["- " + _md(fact) for fact in e["visible_facts"]]
                if e["payload"]["kind"] == "address":
                    lines += ["", "| Independent act | Supplied decision |", "| --- | --- |"]
                    lines += [f"| {_md(act.replace('_', ' '))} | {_md(state.replace('_', ' '))} |" for act, state in e["payload"]["acts"].items()]
                lines += ["", "**Exact evidence spans:**", ""]
                for span in e["spans"]:
                    lines += [f"{_md(span['role'])} [{span['start']},{span['end']}):", "", _fenced(span["text"]), ""]
                for role in ("leading_context", "trailing_context"):
                    if e["source"][role]:
                        lines += [f"**{_md(role.replace('_', ' '))} — reference resolution only:**", "", _fenced(e["source"][role]), ""]
                for key, label, pointer in (("input_path", "Original input and recording/block locator", "input_pointer"), ("result_path", "Frozen result", "result_pointer")):
                    if e["provenance"][key]:
                        lines += [_source_link(e["provenance"][key], label, output_dir) + " at " + _md(e["provenance"][pointer] or "") + ".", ""]
                lines += ["Raw decisions and reuse provenance: " + _md(e["provenance"]["raw_output_ref"] or "not applicable: synthetic design") + "; " + _md(e["provenance"]["answer_provenance_ref"] or "not applicable") + ".", "",
                          "Recording: " + _md(e["source"]["recording_id"]) + "; sermon date: " + _md(e["source"]["sermon_date"] or "unknown") + "; series: " + _md(e["source"]["series_id"] or "unknown") + "; repeated material: " + _md(e["independence"]["repeated_material_group"] or "not supplied") + ".", "",
                          "Ownership: " + _md(e["eligibility"]["membership"]) + "; content: " + _md(e["eligibility"]["content"]) + "; compatibility: " + _md(e["provenance"]["compatibility"]) + "; local boundary: " + _md(e["coverage"]["local_boundary"]) + "; candidate discovery: " + _md(e["coverage"]["candidate_discovery"]) + ".", ""]
        lines += [f"{len(view['retained_evidence'])} source locators / {view['unique_utterance_groups']} utterance groups. " + _md(view["independence_note"]), "",
                  "### Proposed estimands and later constructs", ""]
        lines += [f"- {e['estimand_id']}: {_md(e['target'])} — {_md(e['status'].replace('_', ' '))}" for e in view["estimands"]]
        lines += ["", "D01–D06 remain held. G1, broader collection, pastor projection/comparison, clustering, G4 and quality scoring remain held.", ""]
        if c["acceptance"]["oracle_differences"]:
            lines += ["**Frozen expectation differs from consumer output:**", "", _fenced(json.dumps(c["acceptance"]["oracle_differences"], indent=2), "json"), "",
                      "The original packet is unchanged. No additional semantic inference is used to close this difference.", ""]
    return "\n".join(lines).rstrip() + "\n"


def write_review(review: dict[str, Any], output_dir: Path = DEFAULT_OUTPUT) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, markdown_path = output_dir / "consumer-results.json", output_dir / "observed-profiles.md"
    json_path.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n")
    markdown_path.write_text(render_markdown(review, output_dir))
    return json_path, markdown_path


def console_preview(review: dict[str, Any], case_id: str) -> str:
    case = next((c for c in review["cases"] if c["case_id"] == case_id), None)
    if case is None:
        raise ValueError("--case must be one of " + ", ".join(c["case_id"] for c in review["cases"]))
    view = case["view"]
    lines = [f"{case_id}: {case['purpose']}", view["scope"]]
    for e in view["evidence"]:
        lines += ["", f"Passage [{e['evidence_id']}]: {e['source']['target_text']}", e["reading_note"], *["  " + fact for fact in e["visible_facts"]]]
    lines += ["", "Desired fields:"]
    for f in view["fields"]:
        lines.append(f"  {f['characteristic_id']} {f['question']} — {f['status_label']}")
        if f["assessments"]:
            lines += ["    " + a["evidence_id"] + ": " + a["role"] + "; " + " ".join(a["reasons"]) for a in f["assessments"]]
    lines += ["", "Rates, recurring pastor traits, comparisons and scores are withheld. Open the Markdown report for full missing inputs, suppression reasons and source links."]
    return "\n".join(lines)
