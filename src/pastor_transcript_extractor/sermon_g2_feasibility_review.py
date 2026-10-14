"""Isolated G2 feasibility packet/harness. Evaluation is explicitly opt-in for Brian."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from pastor_transcript_extractor.analysis_artifact_cache import write_json_markdown

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "docs/review-proposals/g2-feasibility-v1"
PACKET_PATH = HERE / "input-v1.json"
RESULT_PATH = ROOT / "evaluation/g2-binding/feasibility-v1.results.json"
CACHE_PATH = ROOT / "evaluation/g2-binding/cache-v1"
MODEL = "jev-1.13.0"
QUESTION_VERSION = "g2-local-semantic-edges-choice-v1"
BUILDER_VERSION = "g2-source-clause-neighbor-pairs-v1"
POLICY_VERSION = "g2-feasibility-decision-v1"
MAX_CASES, MAX_UNITS, MAX_PAIRS = 16, 40, 48
BATCH_PAIRS = 4
THRESHOLD = .80
FACETS = {
    "explains_text": "The first endpoint is specific biblical wording/a textual anchor and the second actually explains that very text's meaning, wording, context, argument or implication. Reading, citing or retelling followed by unrelated material is not explanation.",
    "reason_supports_claim": "The first endpoint supplies a stated reason/premise explicitly used to support the particular teaching statement in the second endpoint. Related subjects or assertions placed nearby are insufficient.",
    "grounds_response": "The first endpoint supplies a stated text/reason/claim explicitly grounding the particular lived response requested in the second endpoint. Do not infer an unstated rationale from an adjacent doctrine or circumstance.",
    "qualifies_claim": "The first endpoint states a condition, exception or limit that actually modifies the specific claim/response in the second endpoint. A qualification of a different statement does not count.",
    "specifies_response_step": "The first endpoint requests a response and the second supplies a specific step, time, method or guidance for carrying out that response. Repetition or another unrelated command does not count.",
    "addresses_response_obstacle": "The first endpoint states an obstacle/constraint to a response and the second offers guidance that actually addresses that obstacle for that response. Merely acknowledging an obstacle without a remedy is insufficient.",
}
EDGE_OPTIONS = {
    "linked": "Both endpoint roles and their specified directed relation are demonstrated in target evidence; keep whether the relation is reported/adopted separate.",
    "not_linked": "Target evidence supplies no relation of this specified kind/direction between these endpoints, including merely proximal or unrelated material, wrong roles, or a different object/claim.",
    "incomplete": "A relation of this kind may be intended but a required premise, response, referent or connecting explanation is missing from target evidence; context cannot supply it.",
    "unclear": "The supplied target supports multiple interpretations or insufficiently resolves the specified endpoint binding; do not invent an edge.",
}


def fp(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def file_fp(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def questions(position=0):
    path = f"pairs[{position}]"
    boundary = ("Use only `target_text` for endpoint roles and semantic relation. Leading/trailing context may resolve references but cannot supply a missing explanation, premise, response, guidance, obstacle or qualification. Judge exactly the endpoints and directed relation; topic overlap, temporal adjacency, lexical cues, citation counts and eloquence are not proof. Preserve quoted/reported/rejected reasoning without attributing it to the preacher. These are local sermon observations, never pastor traits or quality judgments. Each question is independent.")
    result = {f"p{position}_{facet}": {"instructions": {"task": f"For `{path}.left` -> `{path}.right`, decide whether this specified facet is actually evidenced: {definition}", "boundary": boundary}, "criteria": EDGE_OPTIONS} for facet, definition in FACETS.items()}
    result[f"p{position}_adoption"] = {"instructions": {"task": f"For the reasoning/response potentially expressed by the exact endpoint pair `{path}`, how is its voice/adoption framed in `target_text`? Judge adoption separately from whether any specified relation exists.", "boundary": boundary}, "criteria": {
        "own_or_adopted": "The preacher personally asserts/applies this reasoning/response or explicitly adopts a quoted one.",
        "reported": "The reasoning/response belongs to a narrated/reported/quoted speaker without explicit present adoption by the preacher.",
        "rejected": "The target explicitly rejects this reported reasoning/response; do not infer the adopted opposite.",
        "unclear": "Voice/adoption differs between endpoints, is ambiguous, or no definite reasoning/response can be attributed."}}
    result[f"p{position}_boundary"] = {"instructions": {"task": f"Does the target contain enough of the local treatment around `{path}` to decide its semantic relations without borrowing omitted material? A complete local pair does not certify a complete episode or sermon.", "boundary": boundary}, "criteria": {
        "local_sufficient": "Target contains the required local endpoint meaning/connection, even if outer episode boundaries remain unknown.",
        "continuation_required": "A needed premise, response, referent or explanation lies outside target evidence or is cut off.",
        "unclear": "Local sufficiency is not resolved; preserve partial knowledge and do not certify an episode."}}
    return result


def candidates(text, focus=None):
    # Source-coordinate slicing only: no role or semantic edge is assigned here.
    lower, upper = (focus["start"],focus["end"]) if focus else (0,len(text))
    if not 0 <= lower < upper <= len(text): raise ValueError("Invalid focus bounds")
    boundary = re.compile(r"(?<=[.!?;])\s+|(?<=[.!?;][\"'])\s+|\n+|,\s+(?=(?:if|but|then|begin|therefore|why)\b)|\s+(?=(?:because|today|this week)\b)", re.I)
    starts, units = lower, []
    for match in [*boundary.finditer(text,lower,upper), None]:
        stop = match.start() if match else upper
        a, b = starts, stop
        while a < b and text[a].isspace(): a += 1
        while b > a and text[b-1].isspace(): b -= 1
        if a < b: units.append({"start": a, "end": b, "text": text[a:b]})
        if match: starts = match.end()
    retained = units[:MAX_UNITS]
    # Adjacent and next-nearest pairs, both directions; closest distance first.
    all_pairs = [(i,j) for d in (1,2) for i in range(len(retained)) for j in (i+d,i-d) if 0 <= j < len(retained)]
    pairs = [{"pair_id": f"edge-{n}", "left": retained[i], "right": retained[j]} for n,(i,j) in enumerate(all_pairs[:MAX_PAIRS])]
    return pairs, {"unit_count":len(units),"retained_unit_count":len(retained),"possible_local_pair_count":len(all_pairs),"retained_pair_count":len(pairs),"omitted_units":len(units)-len(retained),"omitted_pairs":len(all_pairs)-len(pairs),"coverage":"bounded_local_candidates_not_exhaustive","episode_boundary":"unreviewed_no_duration_credit","focus_bounds":{"start":lower,"end":upper}}


def contains(span, needle):
    return needle in span["text"]


def review_target(facet,left,right,expected,*,adoption=None,reason):
    return {"facet":facet,"left_phrase":left,"right_phrase":right,"expected":expected,
            "allowed_adoption":adoption,"interpretation":reason}


def prepare():
    authored_path=ROOT/"docs/review-proposals/g2-g3-v1/cases-v1.json"
    authored=json.loads(authored_path.read_text())
    selected={"G2-01","G2-02","G2-04","G2-05","G2-07","G2-09","G2-10","G2-11"}
    cases=[]; sources={str(authored_path.relative_to(ROOT)):file_fp(authored_path)}
    for c in authored["cases"]:
        if c["case_id"] not in selected: continue
        targets=[]; nodes={n["node_id"]:n for n in c["nodes"]}
        for r in c["relations"]:
            if r["kind"] in FACETS:
                targets.append(review_target(r["kind"],nodes[r["from_node_id"]]["span"]["text"],nodes[r["to_node_id"]]["span"]["text"],"linked",adoption=["rejected"] if r["adoption"]=="explicitly_rejected" else ["own_or_adopted"],reason=c["reason"]))
        if c["case_id"]=="G2-02": targets=[review_target("explains_text","Romans 12:15", "city should", "not_linked",reason=c["reason"])]
        if c["case_id"]=="G2-04": targets.append(review_target("grounds_response","Call your lonely neighbor","today","not_linked",reason="No separate reason is stated; a concrete response is not its own rationale."))
        if c["case_id"]=="G2-11": targets=[review_target("grounds_response","Therefore share", "this week", ["not_linked","incomplete"],reason=c["reason"])]
        cases.append({"case_id":c["case_id"],"origin":"authored","target_text":c["target_text"],"leading_context":c["leading_context"],"trailing_context":c["trailing_context"],"review_targets":targets,"case_check":"no_positive_edges" if c["case_id"]=="G2-09" else None,"source":{"path":str(authored_path.relative_to(ROOT)),"case_id":c["case_id"]},"reused_evidence":[]})
    # Explicit, immutable archived cases: no new cohort selection or live classification.
    wanted=[("source-material-review-v1.json",4430,25),("source-material-review-v1.json",1200,45),
            ("public-life-treatment-review-v2.json",1200,25),("source-material-review-v1.json",1200,32),
            ("source-material-review-v1.json",4430,37),("source-material-review-v1.json",590,40),
            ("source-material-review-v1.json",1200,23),("listener-directives-review-v3.json",590,64)]
    for name,video,block in wanted:
        path=ROOT/"evaluation/sermon-topics"/name; source=json.loads(path.read_text()); sources[str(path.relative_to(ROOT))]=file_fp(path)
        c=next(c for c in source["cases"] if c["video_id"]==video and c["block_id"]==block)
        case_id=f"natural-{video}-{block}"
        targets=[]
        if (video,block)==(4430,25): targets=[review_target("explains_text","Whatever I tell you in the dark", "He implies that he whispers", "linked",adoption=["own_or_adopted"],reason="Explicit interpretation of the just-quoted dark/ear language; not interpretive fidelity.")]
        if (video,block)==(1200,25): targets=[review_target("reason_supports_claim","what we ought to be promoting", "Alexander Graham Bell", "not_linked",reason="A transition to unrelated biography is not support for that biographical claim.")]
        if (video,block)==(1200,32): targets=[review_target("addresses_response_obstacle","Life is busy", "Especially when you got children", "not_linked",reason="Elaborates the constraint, not a remedy or guidance for overcoming it.")]
        if (video,block)==(4430,37): targets=[review_target("grounds_response","Do penance", "And what should I do", ["not_linked","unclear"],adoption=["reported","unclear","rejected"],reason="Narrated film/story advice; adoption is not established by the ironic/ambiguous commentary. Preserve the uncertainty.")]
        if (video,block)==(590,40): targets=[review_target("explains_text","it says this", "For since the creation", ["not_linked","incomplete"],reason="The quoted text is truncated; introducing/reading it is not its developed explanation.")]
        if (video,block)==(1200,23): targets=[review_target("explains_text","The kingdom of heaven is not", "kingdom of heaven is the kingdom of grace", "not_linked",adoption=["own_or_adopted"],reason="Two interpretations/distinctions are not a text-anchor → explanation pair; do not let richer untargeted development manufacture this particular edge.")]
        if (video,block)==(1200,45): targets=[review_target("grounds_response","He gave all", "Can't we spend time", "linked",adoption=["own_or_adopted"],reason="The target links Christ's giving to an applied appeal to give time; grounded rationale is observable, not the adequacy of the argument.")]
        if (video,block)==(590,64): targets=[review_target("grounds_response","pray for our", "missionaries, pray for evangelism", "not_linked",reason="Specifying prayer recipients is not a distinct rationale for the response.")]
        cases.append({"case_id":case_id,"origin":"natural_archived","target_text":c["target_text"],"leading_context":c.get("leading_context",""),"trailing_context":c.get("trailing_context",""),"review_targets":targets,"case_check":None,"source":{"path":str(path.relative_to(ROOT)),"review_fingerprint":source["input_fingerprint"],"video_id":video,"block_id":block,"segment_indexes":c["segment_indexes"],"start_seconds":c["start_seconds"],"end_seconds":c["end_seconds"],"projection_eligibility_at_saved_review":c.get("projection_eligibility"),"context_diagnostics":c.get("context_diagnostics",{})},"reused_evidence":[{"kind":"saved_target_and_source_span","recollection":False},{"kind":"saved_pack_locator_only","pack_version":source.get("question_pack_version"),"probabilities":c.get("leaf_answer",{}).get("probabilities",{}),"sent_to_provider":False}]})
    focus_phrases = {
        "natural-4430-25": ("Whatever I tell you in the dark", "When does that happen?"),
        "natural-1200-45": ("He gave all", "Allow God to transform us."),
        "natural-1200-25": ("Remember, our citizenship is in heaven.", "Edinburgh, Scotland in 1847."),
        "natural-1200-32": ("Life is busy.", "You may or may not relate with that."),
        "natural-4430-37": ("Finally, Father Gabriel", "this is a big enough sin."),
        "natural-590-40": ("Go back to Romans", "attributes are clearly"),
        "natural-1200-23": ("The kingdom of heaven is not", "even now. Amen?"),
        "natural-590-64": ("I'd encourage you to pray", "in dire need of the gospel."),
    }
    for c in cases:
        if c['case_id'] in focus_phrases:
            first,last=focus_phrases[c['case_id']]; start=c['target_text'].index(first); end=c['target_text'].index(last,start)+len(last)
            c['candidate_focus']={"start":start,"end":end,"selection":"PTE-authored fixed review window, not automatic full-sermon retrieval"}
        else: c['candidate_focus']=None
        if c['case_id']=='G2-04':
            for t in c['review_targets']: t['left_phrase']='Call your lonely neighbor'
        if c['case_id']=='G2-11':
            c['review_targets'][0]['right_phrase']='this week'
        if c['case_id']=='G2-05':
            for t in c['review_targets']:
                if t['facet']=='grounds_response': t['right_phrase']='begin with a five-minute call'
        if c['case_id']=='G2-09':
            c['target_text']='Let us continue. We will consider the next point.'
            c['source']['authored_variant']='Two nonexplanatory target sentences ensure the context-only control receives real pair judgments; not a natural edit.'
        directed=[]
        for t in c['review_targets']:
            directed.append(t)
            if t['expected']=='linked' and t['facet'] in {'explains_text','grounds_response'}:
                directed.append(review_target(t['facet'],t['right_phrase'],t['left_phrase'],'not_linked',reason='Directed endpoint roles reversed: a relation somewhere in the block cannot establish this opposite directed edge.'))
        c['review_targets']=directed
        c["pairs"],c["candidate_diagnostics"]=candidates(c["target_text"],c['candidate_focus'])
        for t in c["review_targets"]:
            t["matching_pair_ids"]=[p["pair_id"] for p in c["pairs"] if contains(p["left"],t["left_phrase"]) and contains(p["right"],t["right_phrase"])]
        c["source_text_fingerprint"]=fp({k:c[k] for k in ("target_text","leading_context","trailing_context")})
    packet={"version":"g2-bounded-feasibility-input-v1","status":"prepared_not_evaluated","production_effect":"none","question_version":QUESTION_VERSION,"question_inventory_at_position_zero":questions(),"question_digest":fp(questions()),"builder_version":BUILDER_VERSION,"policy_version":POLICY_VERSION,"model":MODEL,"threshold":THRESHOLD,"sources":sources,"cases":cases,"reused_grounded_scripture_style":{"status":"not_available_for_selected_three_videos_in_read_only_analysis_inventory","checked_video_ids":[1200,590,4430],"available_runs":"typesafe-topic-projection only; exact frozen source excerpts and pack locators reused","no_recollection":True},"holds":{"G1_implementation":True,"G1_expansion":True,"G3_implementation":True,"G4":True,"broader_collection":True},"budget":{"maximum_cases":MAX_CASES,"maximum_pairs_per_case":MAX_PAIRS,"question_count":sum(len(c['pairs'])*8 for c in cases),"provider_request_ceiling":sum(math.ceil(len(c['pairs'])/BATCH_PAIRS) for c in cases),"sdk_retries":0,"batch_pairs":BATCH_PAIRS}}
    packet["content_fingerprint"]=fp(packet)
    validate_packet(packet)
    return packet


def validate_packet(packet):
    if packet["content_fingerprint"]!=fp({k:v for k,v in packet.items() if k!="content_fingerprint"}): raise ValueError("Input fingerprint mismatch")
    if packet["model"]!=MODEL or packet["threshold"]!=THRESHOLD or packet["policy_version"]!=POLICY_VERSION: raise ValueError("Pinned experiment policy/model drift")
    if packet["question_digest"]!=fp(questions()) or packet["question_inventory_at_position_zero"]!=questions() or packet["builder_version"]!=BUILDER_VERSION: raise ValueError("Frozen question/builder drift")
    if packet["status"]!="prepared_not_evaluated" or packet["production_effect"]!="none" or not all(packet["holds"].values()): raise ValueError("Experiment scope changed")
    if len(packet["cases"])!=MAX_CASES or len({c['case_id'] for c in packet['cases']})!=MAX_CASES: raise ValueError("Fixed case inventory changed")
    for path,sha in packet["sources"].items():
        if file_fp(ROOT/path)!=sha: raise ValueError(f"Changed frozen source: {path}")
    for c in packet["cases"]:
        pairs,diagnostics=candidates(c["target_text"],c["candidate_focus"])
        if c["pairs"]!=pairs or c["candidate_diagnostics"]!=diagnostics: raise ValueError("Candidate drift/invalid source offsets")
        if c["source_text_fingerprint"]!=fp({k:c[k] for k in ("target_text","leading_context","trailing_context")}): raise ValueError("Source text changed")


def state_for(c,pairs):
    # No proposed labels, old probabilities, title, pastor identity or candidate coverage gold.
    return {"target_text":c["target_text"],"leading_context":c["leading_context"],"trailing_context":c["trailing_context"],"pairs":pairs}


def validate_answers(raw,inventory):
    if set(raw)!=set(inventory): raise ValueError("Incomplete answer inventory")
    for key,value in raw.items():
        options=inventory[key]["criteria"]
        probs=value["probabilities"]
        if set(probs)!=set(options) or value["choice"] not in options or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in probs.values()) or abs(sum(probs.values())-1)>.01: raise ValueError("Malformed Choice answer")


def decision(answer):
    return answer["choice"] if answer["probabilities"][answer["choice"]]>=THRESHOLD else "unclear"


class Provider:
    def __init__(self):
        from typesafe_sdk import TypeSafeClient,Choice,RetryPolicy
        self.Choice=Choice
        self.client=TypeSafeClient(model=MODEL,timeout=45,retry=RetryPolicy(max_retries=0))
    def assess(self,state,inventory):
        result=self.client.system_one(state,{k:self.Choice(**q) for k,q in inventory.items()},model=MODEL,timeout=45)
        raw={k:{"choice":str(a.choice),"probabilities":dict(a.probabilities),"confidence":getattr(a,"confidence",None)} for k,a in result.choices.items()}
        return {"answers":raw,"resolved_model":str(result.model),"usage":{"input_tokens":getattr(result.usage,"input_tokens",None),"output_tokens":getattr(result.usage,"output_tokens",None)}}


def evaluate(packet,*,provider_factory=Provider,cache_dir=CACHE_PATH):
    validate_packet(packet)
    provider=None; requests=hits=0; results=[]
    for c in packet["cases"]:
        loaded={}; identities={}; paths={}; missing=[]
        for pair in c["pairs"]:
            # Normalize question position to zero; batch membership is not cache identity.
            identity={"state":state_for(c,[pair]),"questions":questions(0),"model":packet["model"],"question_version":QUESTION_VERSION}
            key=fp(identity); path=cache_dir/f"{key}.json"
            identities[pair['pair_id']]=identity; paths[pair['pair_id']]=(key,path)
            response=None
            if path.exists():
                try:
                    cached=json.loads(path.read_text())
                    if cached["identity"]!=identity or cached["fingerprint"]!=fp({k:v for k,v in cached.items() if k!='fingerprint'}): raise ValueError("Corrupt cache identity")
                    validate_answers(cached["response"]["answers"],questions(0))
                    if cached["response"]["resolved_model"]!=packet["model"]: raise ValueError("Cached model mismatch")
                    response=cached["response"]; hits+=1
                except (ValueError,KeyError,TypeError,json.JSONDecodeError): response=None
            if response is None: missing.append(pair)
            else: loaded[pair['pair_id']]=response
        for offset in range(0,len(missing),BATCH_PAIRS):
            pairs=missing[offset:offset+BATCH_PAIRS]; state=state_for(c,pairs)
            inventory={k:v for i in range(len(pairs)) for k,v in questions(i).items()}
            if requests>=packet["budget"]["provider_request_ceiling"]: raise ValueError("Provider budget exceeded")
            if provider is None: provider=provider_factory()
            requests+=1; response=provider.assess(state,inventory)
            validate_answers(response["answers"],inventory)
            if response["resolved_model"]!=packet["model"]: raise ValueError("Resolved model differs from pinned model")
            request_key=fp({"state":state,"questions":inventory,"model":packet["model"]})
            for i,pair in enumerate(pairs):
                normalized={f"p0_{field}":response['answers'][f"p{i}_{field}"] for field in (*FACETS,'adoption','boundary')}
                local={"answers":normalized,"resolved_model":response['resolved_model'],"request_provenance":{"request_key":request_key,"batch_pair_count":len(pairs),"usage":response.get('usage',{})}}
                key,path=paths[pair['pair_id']]
                cached={"identity":identities[pair['pair_id']],"response":local}; cached['fingerprint']=fp(cached)
                cache_dir.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(cached,indent=2)+'\n')
                loaded[pair['pair_id']]=local
        rows=[]
        for pair in c['pairs']:
            response=loaded[pair['pair_id']]
            answers={field:response['answers'][f"p0_{field}"] for field in (*FACETS,'adoption','boundary')}
            decisions={k:decision(v) for k,v in answers.items()}
            rows.append({"pair":pair,"raw_answers":answers,"decisions":decisions,"provisional_adopted_local_facets":[f for f in FACETS if decisions[f]=='linked' and decisions['adoption']=='own_or_adopted' and decisions['boundary']=='local_sufficient'],"cache_key":paths[pair['pair_id']][0],"request_provenance":response.get('request_provenance',{})})
        results.append({"case_id":c['case_id'],"rows":rows})
    validate_packet(packet)
    report={"version":"g2-feasibility-results-v1","status":"evaluated_pending_PTE_interpretation_and_Brian_decision","input_fingerprint":packet['content_fingerprint'],"question_digest":packet['question_digest'],"production_effect":"none","execution":{"provider_requests":requests,"cache_hits":hits},"cases":results}
    report['diagnostics']=diagnose(packet,results)
    report['content_fingerprint']=fp(report)
    return report


def diagnose(packet,results):
    indexed={c['case_id']:c for c in results}; checks=[]; positive_review=[]
    for c in packet['cases']:
        rows={r['pair']['pair_id']:r for r in indexed[c['case_id']]['rows']}
        for t in c['review_targets']:
            matches=[rows[k] for k in t['matching_pair_ids']]
            expected=t['expected'] if isinstance(t['expected'],list) else [t['expected']]
            if not matches: status='candidate_omission'
            elif 'linked' not in expected and any(r['decisions'][t['facet']]=='linked' for r in matches): status='false_semantic_edge'
            elif t['allowed_adoption'] and 'own_or_adopted' not in t['allowed_adoption'] and any(r['decisions']['adoption']=='own_or_adopted' for r in matches): status='voice_adoption_failure'
            elif t['allowed_adoption'] and not any(r['decisions']['adoption'] in t['allowed_adoption'] for r in matches): status='voice_adoption_failure'
            elif not any(r['decisions'][t['facet']] in expected for r in matches):
                status='false_semantic_edge' if any(r['decisions'][t['facet']]=='linked' for r in matches) and t['expected']!='linked' else 'unclear_or_missed_relation'
            else: status='matches_proposal'
            checks.append({'case_id':c['case_id'],'origin':c['origin'],'target':t,'status':status})
        for row in rows.values():
            if any(row['decisions'][f]=='linked' for f in FACETS): positive_review.append({'case_id':c['case_id'],'pair_id':row['pair']['pair_id'],'decisions':row['decisions'],'review_required':True})
        if c['case_check']=='no_positive_edges' and any(any(r['decisions'][f]=='linked' for f in FACETS) for r in rows.values()): checks.append({'case_id':c['case_id'],'status':'context_leakage_failure'})
    failures=[c for c in checks if c['status']!='matches_proposal']
    return {'checks':checks,'positive_edges_requiring_PTE_review':positive_review,'provisional_numeric_screen':'all_prepared_checks_match' if not failures else 'partial_or_failure_requires_interpretation','all_candidate_omissions':[c for c in checks if c['status']=='candidate_omission'],'limitations':'No automatic PASS; PTE interprets all positives, directional false edges, candidate/boundary gaps and disputed natural proposals before recommending pass/partial/failure. No scalar depth/quality value.'}


def render_input(packet):
    lines=['# G2 bounded feasibility inputs V1','',f"Fingerprint: `{packet['content_fingerprint']}`",'',f"Cases: {len(packet['cases'])}; maximum uncached requests: {packet['budget']['provider_request_ceiling']}; questions: {packet['budget']['question_count']}. No validation has run.",'']
    for c in packet['cases']:
        lines += [f"## {c['case_id']} ({c['origin']})",'',c['target_text'],'',f"Candidate diagnostics: `{json.dumps(c['candidate_diagnostics'])}`",'']
        for t in c['review_targets']: lines += [f"- {t['facet']}: {t['left_phrase']} → {t['right_phrase']}; proposed {t['expected']}; matching candidates {t['matching_pair_ids']}. {t['interpretation']}"]
        lines.append('')
    return '\n'.join(lines)


def render_results(report,packet):
    lines=['# G2 bounded feasibility results','',report['status'],'',f"Input: `{report['input_fingerprint']}`; execution: `{json.dumps(report['execution'])}`",'', 'No profile projection, depth score or collection credit.','']
    for item in report['diagnostics']['checks']: lines += [f"- {item['case_id']}: {item['status']} {item.get('target',{}).get('facet','')}"]
    for case in report['cases']:
        source=next(c for c in packet['cases'] if c['case_id']==case['case_id'])
        lines += ['',f"## {case['case_id']}",'',source['target_text'],'']
        for row in case['rows']:
            if any(row['decisions'][f]=='linked' for f in FACETS): lines += [f"- {row['pair']['pair_id']}: `{json.dumps(row['decisions'])}`",f"  Left: {row['pair']['left']['text']}",f"  Right: {row['pair']['right']['text']}"]
    return '\n'.join(lines)+'\n'


def run(mode="evaluate"):
    """Run one bounded mode; default is the Brian-owned validation command."""
    if mode not in {"prepare", "check", "evaluate"}:
        raise ValueError("Unsupported G2 review mode")
    if mode == "prepare":
        packet=prepare();write_json_markdown(PACKET_PATH,packet,render_input(packet));(HERE/'questions-v1.json').write_text(json.dumps(questions(),indent=2)+'\n')
        print(f"Prepared {len(packet['cases'])} fixed cases; provider requests=0")
    elif mode == "check":
        packet=json.loads(PACKET_PATH.read_text());validate_packet(packet)
        if packet!=prepare(): raise ValueError('Prepared proposal drift')
        if json.loads((HERE/'questions-v1.json').read_text())!=questions(): raise ValueError('Published questions drift')
        print('PASS: local packet/question/candidate integrity only; no provider or dataset validation')
    else:
        packet=json.loads(PACKET_PATH.read_text())
        # Provider errors keep successful pair caches; never publish partial data as semantic success.
        try:
            report=evaluate(packet)
        except Exception as error:
            failure={"version":"g2-feasibility-execution-failure-v1","status":"execution_failed_incomplete_not_a_semantic_verdict","input_fingerprint":packet.get('content_fingerprint'),"error_type":type(error).__name__,"production_effect":"none","successful_pair_caches_retained":True}
            write_json_markdown(RESULT_PATH.with_name('feasibility-v1.execution-failure.json'),failure,"# G2 execution failure\n\nIncomplete execution; no semantic decision. Inspect the command error and reuse successful caches.\n")
            raise
        write_json_markdown(RESULT_PATH,report,render_results(report,packet))
        print(f"Wrote {RESULT_PATH}; pending PTE interpretation; {report['execution']}")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true')
    group.add_argument('--check',action='store_true')
    group.add_argument('--evaluate',action='store_true')
    args=parser.parse_args()
    run('prepare' if args.prepare else 'check' if args.check else 'evaluate')

