"""Fixed provider-free consumer acceptance and self-contained human review output."""
from __future__ import annotations

from html import escape
import json
import os
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


def _list(items: list[str]) -> str:
    return "<ul>" + "".join("<li>" + escape(s) + "</li>" for s in items) + "</ul>" if items else ""


def _link(path: str | None, label: str, output_dir: Path) -> str:
    if not path:
        return ""
    target = (ROOT / path).resolve()
    if not target.is_relative_to(ROOT):
        return escape(label) + " (source outside this checkout)"
    href = os.path.relpath(target, output_dir.resolve())
    return '<a href="' + escape(href, quote=True) + '">' + escape(label) + "</a>"


def _evidence_cards(case: dict[str, Any], output_dir: Path) -> str:
    view = case["view"]
    by_id = {e["evidence_id"]: e for e in view["evidence"]}
    parts = []
    for number, (group, ids) in enumerate(view["utterance_groups"].items(), 1):
        e = by_id[ids[0]]
        parts.append(f'<article class="evidence"><h3>Passage {number}</h3><p class="muted">{len(ids)} source locator(s) · {escape(e["provenance"]["origin"].replace("_", " "))}</p>')
        parts.append("<blockquote>" + escape(e["source"]["target_text"]) + "</blockquote>")
        if e["payload"]["kind"] == "address":
            parts.append("<p><strong>Assessed address utterance:</strong> “" + escape(e["spans"][0]["text"]) + "”</p>")
        parts.append("<p>" + escape(e["reading_note"]) + "</p>")
        for eid in ids:
            entry = by_id[eid]
            anchor = case["case_id"] + ":" + eid
            parts.append(f'<details id="{escape(anchor, quote=True)}"><summary>Source and decisions: {escape(eid)}</summary>')
            # Duplicate aliases can differ; never hide their original target or decisions.
            if entry["source"]["target_text"] != e["source"]["target_text"]:
                parts.append("<blockquote>" + escape(entry["source"]["target_text"]) + "</blockquote>")
            parts.append(_list(entry["visible_facts"]))
            p = entry["payload"]
            if p["kind"] == "address":
                parts.append('<table><caption>Independent act decisions</caption><tr><th>Act</th><th>Supplied decision</th></tr>')
                parts += ["<tr><td>" + escape(a.replace("_", " ")) + "</td><td>" + escape(state.replace("_", " ")) + "</td></tr>" for a, state in p["acts"].items()]
                parts.append("</table>")
            parts.append("<p><strong>Exact evidence spans:</strong></p>" + _list([f"{s['role']} [{s['start']},{s['end']}): {s['text']}" for s in entry["spans"]]))
            for role in ("leading_context", "trailing_context"):
                if entry["source"][role]:
                    parts.append("<p><strong>" + escape(role.replace("_", " ")) + " (reference resolution only)</strong></p><blockquote>" + escape(entry["source"][role]) + "</blockquote>")
            for key, label, pointer in (("input_path", "Original input and recording/block locator", "input_pointer"), ("result_path", "Frozen result", "result_pointer")):
                if entry["provenance"][key]:
                    parts.append("<p>" + _link(entry["provenance"][key], label, output_dir) + " at <code>" + escape(entry["provenance"][pointer] or "") + "</code></p>")
            parts.append("<p>Raw decisions and reuse provenance: <code>" + escape(entry["provenance"]["raw_output_ref"] or "not applicable: synthetic design") + "</code>; <code>" + escape(entry["provenance"]["answer_provenance_ref"] or "not applicable") + "</code>.</p>")
            parts.append("<p>Recording: " + escape(entry["source"]["recording_id"]) + "; sermon date: " + escape(entry["source"]["sermon_date"] or "unknown") + "; series: " + escape(entry["source"]["series_id"] or "unknown") + "; repeated material: " + escape(entry["independence"]["repeated_material_group"] or "not supplied") + ".</p>")
            parts.append("<p>Ownership: " + escape(entry["eligibility"]["membership"]) + "; content: " + escape(entry["eligibility"]["content"]) + "; compatibility: " + escape(entry["provenance"]["compatibility"]) + "; local boundary: " + escape(entry["coverage"]["local_boundary"]) + "; candidate discovery: " + escape(entry["coverage"]["candidate_discovery"]) + ".</p>")
            parts.append("</details>")
        parts.append("</article>")
    return "".join(parts)


def _field_card(case_id: str, f: dict[str, Any]) -> str:
    refs = f["supporting"] + f["counter"] + f["unresolved"] + f["related"]
    css = "observed" if f["availability"] == "local_examples" else "unknown"
    content = [f'<details class="field {css}"><summary><span class="field-title">{escape(f["characteristic_id"])} · {escape(f["question"])}</span><span class="badge">{escape(f["status_label"])}</span></summary>']
    content += ["<p>Desired field: " + escape(f["target_statement"]) + ".</p>"]
    for assessment in f["assessments"]:
        eid = assessment["evidence_id"]
        role_label = {"supporting": "Supports this local observation", "counter": "Counterexample in this unit", "unresolved": STATUS_LABELS[assessment["availability"]], "related": "Related material; richer field not established"}[assessment["role"]]
        content += ['<p><strong>' + escape(role_label) + ':</strong> <a href="#' + escape(case_id + ":" + eid, quote=True) + '">' + escape(eid) + "</a></p>", _list(assessment["reasons"])]
    if not refs:
        content += ["<p>No compatible observation is supplied for this field. No negative characteristic is inferred.</p>"]
    if f["missing_information"]:
        content += ["<h4>Still missing or unestablished</h4>", _list(f["missing_information"])]
    content += ["<h4>Why stronger claims are withheld</h4>", _list(f["suppression_reasons"]), "</details>"]
    return "".join(content)


def render_html(review: dict[str, Any], output_dir: Path) -> str:
    css = """body{font:16px/1.55 system-ui,sans-serif;margin:0;color:#202c3c;background:#f5f6f8}main{max-width:1080px;margin:auto;padding:30px 24px 80px}h1{font-size:30px;line-height:1.2}h2{font-size:23px}h3{font-size:18px}h4{margin-bottom:4px}.intro,.notice{border-left:4px solid #567094;padding:12px 18px;background:#eaf0f8}.muted{color:#536278;font-size:14px}nav{display:flex;flex-wrap:wrap;gap:8px;margin:20px 0}nav a{padding:6px 10px;border:1px solid #9aaac0;border-radius:6px;color:#244b7b;background:white}a{color:#164e91;overflow-wrap:anywhere}.case{margin:25px 0 45px;border-top:2px solid #8da0b9;padding-top:10px}.evidence{background:white;border:1px solid #cdd5df;border-radius:8px;padding:16px;margin:14px 0}blockquote{margin:12px 0;padding:12px 16px;border-left:3px solid #8da0b9;background:#f6f8fb;white-space:pre-wrap}details{margin:10px 0}summary{cursor:pointer;font-weight:600}details[open]>summary{margin-bottom:12px}.field{background:white;border:1px solid #ccd5df;border-radius:6px;padding:13px 16px}.field summary{display:flex;justify-content:space-between;gap:12px;align-items:center}.field-title{flex:1}.badge{font-size:12px;font-weight:600;border-radius:5px;padding:4px 7px;background:#edf0f4;color:#394b61;max-width:235px}.observed .badge{background:#dceee6;color:#20503d}code{overflow-wrap:anywhere;font-size:13px}table{border-collapse:collapse;width:100%}th,td{text-align:left;border-bottom:1px solid #ddd;padding:7px}caption{text-align:left;font-weight:600}.facts li{margin-bottom:6px}@media(max-width:650px){main{padding:18px 12px}.field summary{display:block}.badge{display:inline-block;margin-top:8px}h1{font-size:25px}}@media print{nav,.chooser{display:none}.case{display:block!important}details:not([open])> *{display:block}details>summary{display:block}}
"""
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Observed passage profiles — bounded consumer review</title><style>', css, '</style><main><h1>Observed passage profiles</h1><p class="intro">These are supplied passage examples, including synthetic designs and frozen pilot outputs. They describe what is observed and what remains unknown. They do not characterize or compare pastors.</p>']
    parts.append(f'<p class="muted">{review["case_count"]} acceptance cases · {review["invariant_passes"]} invariant passes · {review["exact_oracle_matches"]} exact frozen state/link matches · zero provider requests</p>')
    parts.append('<label class="chooser" for="case">Choose an example: </label><select class="chooser" id="case"><option value="all">All examples</option>')
    parts += [f'<option value="{c["case_id"]}" {"selected" if c["case_id"] == "A01" else ""}>{escape(c["case_id"] + " — " + c["purpose"])}</option>' for c in review["cases"]]
    parts.append('</select><p>Start with A01 for a partial view, A05 for withheld binding, A08 for a supported local address, A11 for duplicate passages, A12 for exclusion, or A15 for separate example panels.</p>')
    for c in review["cases"]:
        view = c["view"]
        parts.append(f'<section class="case" id="{c["case_id"]}"><h2>{escape(c["case_id"] + " — " + c["purpose"])}</h2>')
        parts.append('<p class="notice">' + ("Synthetic design only; no real pastor evidence." if c["origin"] == "synthetic_design" else "Frozen provider output and/or synthetic design. Real pastor ownership/content eligibility is not certified.") + " All displayed claims concern supplied passages.</p>")
        parts.append("<h3>What the supplied passages show</h3><ul class=\"facts\">")
        seen = set()
        for e in view["evidence"]:
            key = e["independence"]["utterance_group"]
            if key in seen:
                continue
            seen.add(key)
            # Evidence decisions remain visible even when a richer field is withheld.
            parts.append("<li><strong>" + escape(e["evidence_id"]) + "</strong> — " + escape(" ".join(e["visible_facts"])) + "</li>")
        parts.append("</ul><h3>Passages and source decisions</h3>" + _evidence_cards(c, output_dir))
        parts.append(f'<p class="muted">{len(view["retained_evidence"])} source locators / {view["unique_utterance_groups"]} utterance groups. {escape(view["independence_note"])}</p>')
        parts.append("<h3>All 20 desired fields</h3><p>Observed means a supplied local example. Missing and withheld fields remain visible. Open a field for its evidence links and the reason stronger claims are unavailable.</p>")
        parts += [_field_card(c["case_id"], f) for f in view["fields"]]
        parts.append("<details><summary>Proposed estimands and later constructs</summary>" + _list([e["estimand_id"] + ": " + e["target"] + " — " + e["status"].replace("_", " ") for e in view["estimands"]]) + "<p>D01–D06 remain held. G1, broader collection, pastor projection/comparison, clustering, G4 and quality scoring remain held.</p></details>")
        if c["acceptance"]["oracle_differences"]:
            parts.append('<details class="notice"><summary>Frozen expectation differs from consumer output</summary><pre>' + escape(json.dumps(c["acceptance"]["oracle_differences"], indent=2)) + "</pre><p>The original packet is unchanged. No additional semantic inference is used to close this difference.</p></details>")
        parts.append("</section>")
    parts.append('''<script>
const chooser=document.querySelector('#case');
function show(){document.querySelectorAll('.case').forEach(e=>e.hidden=chooser.value!=='all'&&e.id!==chooser.value);}
chooser.addEventListener('change',show);
document.addEventListener('click',e=>{const a=e.target.closest('a[href^="#"]');if(!a)return;const target=document.getElementById(a.hash.slice(1));if(target&&target.tagName==='DETAILS')target.open=true;});
show();
</script></main></html>''')
    return "".join(parts)


def write_review(review: dict[str, Any], output_dir: Path = DEFAULT_OUTPUT) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, html_path = output_dir / "consumer-results.json", output_dir / "observed-profiles.html"
    json_path.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n")
    html_path.write_text(render_html(review, output_dir))
    return json_path, html_path


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
    lines += ["", "Rates, recurring pastor traits, comparisons and scores are withheld. Open the HTML for full missing inputs, suppression reasons and source links."]
    return "\n".join(lines)
