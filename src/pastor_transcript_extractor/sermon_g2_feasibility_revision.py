"""One frozen-case G2 revision: manual adjudication and cache-preserving pilot only."""
from __future__ import annotations
from copy import deepcopy
import json
import math
from pathlib import Path
import re
from pastor_transcript_extractor import sermon_g2_feasibility_review as v1
from pastor_transcript_extractor.analysis_artifact_cache import write_json_markdown

HERE=v1.ROOT/'docs/review-proposals/g2-feasibility-v2'
INPUT=HERE/'input-v2.json'
BASE_RESULT=v1.ROOT/'evaluation/g2-binding/feasibility-v1.results.json'
RESULT=v1.ROOT/'evaluation/g2-binding/feasibility-v2.results.json'
CACHE=v1.ROOT/'evaluation/g2-binding/cache-v2'
BASE_RESULT_FP='eecb70409e6101511330cad5f3dc065cf04bc5e9047df312ea5a7777d0364cab'
BASE_INPUT_FP='39cb96235678619407b1f8725228444f19fdb00f41d065bdf0629da91d090143'
VERSION='g2-semantic-edges-and-independent-voice-v2'
BUILDER='g2-v1-pairs-plus-bounded-sentence-bundles-v2'
POLICY='g2-one-cycle-adjudicated-feasibility-v2'
FIELDS=(*v1.FACETS,'adoption','boundary','left_voice','right_voice')

# Primary bucket for every displayed mismatch. Subcomponent uncertainty is retained in the rationale.
MISMATCHES={
 3:('A','Intrinsic timing was split out of a single directive; this is not a second guidance assertion. Adoption of the utterance was top-ranked own (.60), withheld by the gate, not wrongly attributed to a reported speaker.','Expect no relational step edge; observe intrinsic timing separately in a future node contract, not this experiment.'),
 5:('C','Call -> begin with a five-minute call is a clear method/initial step. Linked was top-ranked (.54) but not discriminated at .80; own adoption was top-ranked (.78), not false reported attribution.','Clarify that concrete manner/limited initial action counts; separate voice from relation existence.'),
 7:('C','That small contact can interrupt isolation states a benefit of the just-requested call. The reason may follow the request; directed roles need not follow source chronology. .40 linked versus .58 not-linked remains a genuine judgment uncertainty.','Clarify explicit anaphoric benefit and reverse chronology, retaining .80.'),
 8:('A','The reverse edge had not-linked as the top choice (.62), and was withheld. The diagnostic confuses a conservative abstention with a demonstrated reversed semantic edge.','Keep the negative expectation; report withheld rather than confirmed-correct or wrong-edge.'),
 9:('A','Only in the context of restoring a relationship scopes the speaker\'s current distinguishing activity; it need not qualify the proposition that these are different responses. The forced positive expectation was too strong.','Expect not-linked or unclear for this particular claim qualification; add explicit qualification and wrong-object controls.'),
 10:('A','Reported origin and explicit rejection are simultaneously true. The one exclusive adoption question mixes provenance and stance. The .80 reported result did withhold adopted credit; it did not manufacture the pastor\'s opposite belief.','Separate endpoint voices from preacher stance; retain explicit rejection as its own field.'),
 11:('A','The pair is an instruction plus its timing fragment, not a premise-response pair. A conservative not-linked top answer (.64) became unclear, which is safe withholding, not context leakage.','Retain not-linked/incomplete/unclear as non-evidence; keep the negative target distinct from successful discrimination.'),
 14:('B','He gave all was separated from why shouldn\'t we? The omitted rhetorical bridge is in the target but absent from the reason endpoint; the later appeal is then too weakly bound (.57 linked).','Add a mechanically reconstructed whole-sentence reason node including the bridge, retaining the original pair.'),
 20:('A','The first endpoint includes both the biblical term and its negative gloss. Treating it as a definitely nontextual node overstates its granularity. Not-linked is top-ranked (.65); unclear is a defensible unresolved role decision, not evidence of a false edge.','Retain not-linked/unclear, record the overbroad-role limitation; require the clear text controls to remain discriminating.'),
 21:('B','A caption newline splits pray for our from its grammatical object missionaries. Zero omissions only meant substrings existed. Neither endpoint is a complete semantic unit.','Add the intact wrapped sentence, keep fragment pair as a not-linked/unclear control; never treat fragments as independent rationale.'),
}
# Every V1 linked cell is also reviewed, so successes cannot hide unscored false edges.
POSITIVE_JUDGMENTS={
 ('G2-01','edge-0','explains_text'):('supported',None,'The supplied wording is explicitly explained.'),
 ('G2-01','edge-0','grounds_response'):('revision_required','C','Second endpoint explains weeping; it does not independently request a lived response. Wrong endpoint role.'),
 ('G2-05','edge-1','reason_supports_claim'):('revision_required','C','Conditional setup -> imperative remedy is not the premise -> teaching assertion relation as specified.'),
 ('G2-05','edge-1','grounds_response'):('revision_required','A','Condition/constraint and stated rationale were insufficiently separated in the contract. Obstacle mitigation is evidenced; a stated motivating benefit is separate.'),
 ('G2-05','edge-1','qualifies_claim'):('supported',None,'If schedule is tight qualifies the requested short-call guidance.'),
 ('G2-05','edge-1','addresses_response_obstacle'):('supported',None,'The short call addresses the tight-schedule constraint.'),
 ('G2-07','edge-6','reason_supports_claim'):('revision_required','B','The first definition alone is not the complete premise bundle for the distinction; the trust definition is a needed endpoint component.'),
 ('G2-10','edge-0','grounds_response'):('supported_unadopted',None,'Quoted premise grounds the quoted blame instruction; reported/rejected material must remain unadopted.'),
 ('G2-10','edge-0','reason_supports_claim'):('supported_unadopted',None,'The reported normative argument is present; rejecting it does not erase its structure or create the opposite claim.'),
 ('natural-4430-25','edge-6','explains_text'):('supported',None,'The dark/ear quotation is explained using its particular wording.'),
 ('natural-1200-45','edge-0','reason_supports_claim'):('supported',None,'The rhetorical why-should-not-we expresses an adopted normative conclusion inheriting give-all from its antecedent.'),
 ('natural-1200-45','edge-0','grounds_response'):('supported',None,'The rhetorical appeal inherits the requested giving response; this is not the separately missed time-in-Scripture pair.'),
 ('natural-1200-25','edge-16','reason_supports_claim'):('supported',None,'Our king supplies an explicitly connected reason for the stated focus/promotion conclusion.'),
 ('natural-4430-37','edge-7','qualifies_claim'):('revision_required','C','Penance size -> causal reason about sin is not a directed condition/exception/scope qualification.'),
 ('natural-4430-37','edge-9','qualifies_claim'):('revision_required','C','Causal because explanation supplies a reason, not a limiting applicability qualifier. Reported status prevents adopted credit but raw kind is wrong.'),
}


def validate_answers(raw, inventory):
    """Keep V1's .01 mass tolerance, with epsilon for serialized hundredths (.99)."""
    if set(raw)!=set(inventory):raise ValueError('Incomplete answer inventory')
    for key,value in raw.items():
        probabilities=value['probabilities'];options=inventory[key]['criteria']
        if (set(probabilities)!=set(options) or value['choice'] not in options
                or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in probabilities.values())
                or abs(sum(probabilities.values())-1)>.010000001):raise ValueError('Malformed Choice answer')


def load_baseline():
    packet=json.loads(v1.PACKET_PATH.read_text()); result=json.loads(BASE_RESULT.read_text())
    v1.validate_packet(packet)
    if packet['content_fingerprint']!=BASE_INPUT_FP or result['content_fingerprint']!=BASE_RESULT_FP or v1.fp({k:v for k,v in result.items() if k!='content_fingerprint'})!=BASE_RESULT_FP or result['input_fingerprint']!=BASE_INPUT_FP:
        raise ValueError('Requires immutable completed V1 packet/results')
    rows={c['case_id']:{r['pair']['pair_id']:r for r in c['rows']} for c in result['cases']}
    for c in packet['cases']:
        if set(rows[c['case_id']])!={p['pair_id'] for p in c['pairs']}: raise ValueError('V1 result pair inventory mismatch')
        for p in c['pairs']:
            row=rows[c['case_id']][p['pair_id']]
            if row['pair']!=p: raise ValueError('V1 pair mismatch')
            row['_baseline_state_fingerprint']=v1.fp(v1.state_for(c,[p]))
            validate_answers({f'p0_{f}':a for f,a in row['raw_answers'].items()},v1.questions())
    return packet,result,rows


def audit():
    packet,result,rows=load_baseline(); mismatches=[]
    for index,check in enumerate(result['diagnostics']['checks']):
        if check['status']=='matches_proposal':continue
        if index not in MISMATCHES: raise ValueError('Unadjudicated mismatch')
        bucket,why,action=MISMATCHES[index]
        t=check['target']; pair_rows=[rows[check['case_id']][p] for p in t['matching_pair_ids']]
        mismatches.append({'check_index':index,'case_id':check['case_id'],'facet':t['facet'],'original_status':check['status'],'bucket':bucket,'rationale':why,'proposed_resolution':action,'original_check':check,'evidence':pair_rows})
    if {m['check_index'] for m in mismatches}!=set(MISMATCHES): raise ValueError('Audit no longer covers exactly all mismatches')
    positives=[]
    for c in result['cases']:
        for row in c['rows']:
            for f in v1.FACETS:
                if row['decisions'][f]!='linked':continue
                key=(c['case_id'],row['pair']['pair_id'],f)
                if key not in POSITIVE_JUDGMENTS: raise ValueError('Unadjudicated positive')
                status,bucket,why=POSITIVE_JUDGMENTS[key]
                positives.append({'case_id':key[0],'pair_id':key[1],'facet':key[2],'assessment':status,'bucket':bucket,'rationale':why,'voice_adoption_v1':row['decisions']['adoption'],'source_pair':row['pair'],'raw_answer':row['raw_answers'][f]})
    if len(positives)!=len(POSITIVE_JUDGMENTS): raise ValueError('Audit positive inventory drift')
    out={'version':'g2-v1-manual-A-B-C-audit-v1','reviewed_on':'2026-10-14','reviewed_by':'Codex/PTE development','Brian_decision':'PARTIAL PASS','provider_requests':0,'baseline_input':BASE_INPUT_FP,'baseline_result':BASE_RESULT_FP,'mismatches':mismatches,'positive_cell_review':positives,'scope':'Manual bounded interpretation; no provider inference or population accuracy estimate; V1 unchanged'}
    out['content_fingerprint']=v1.fp(out);return out


def questions(position=0):
    q=deepcopy(v1.questions(position)); path=f'pairs[{position}]'
    revisions={
      'reason_supports_claim':'The first endpoint states a premise used to support the second endpoint\'s teaching/normative assertion. A bare condition attached to an imperative does not itself establish this claim-reasoning facet. A rhetorical question may express a normative conclusion only when its intended conclusion/referent is clear in target evidence. Preserve reported arguments without adopting them.',
      'grounds_response':'The first endpoint states a motivating reason, principle or benefit actually tied to the particular action requested in the second. The reason may FOLLOW the request in transcript order; an explicit anaphor such as that small contact can bind a stated benefit to that call. A pure conditional guard/obstacle is not by itself a stated rationale. The second endpoint must request a response, not merely describe/explain words or narrate a benefit. Preserve quoted requests with separate adoption.',
      'qualifies_claim':'The first endpoint explicitly restricts applicability, scope, condition or exception of the second endpoint\'s particular claim/response. A causal explanation of why a claim is made is not automatically an applicability qualifier. A restriction on the speaker\'s current explanation activity is not automatically a restriction on the explained claim. Both directions must be judged by their distinct roles, not proximity.',
      'specifies_response_step':'The first endpoint requests an action; the second is a DISTINCT utterance specifying how, when or by what concrete initial step that same action should be performed. Begin with a five-minute call after a request to call is a concrete method/initial step, not mere repetition; multiple procedural steps are not required. A timing fragment split from a single directive is an intrinsic node detail, not a separate guidance assertion or a new relational edge. Guidance for a different action is not linked.',
    }
    for facet,text in revisions.items():
        q[f'p{position}_{facet}']['instructions']['task']=f'For `{path}.left` -> `{path}.right`, decide this exact independent directed facet: {text}'
    q[f'p{position}_adoption']={'instructions':{'task':f'Using target attribution/rejection frames, how does the preacher treat the CONTENT quoted or expressed by the endpoints in `{path}`? Assess source stance independently of whether any tested edge exists. A preacher\'s own directive remains own speech even if it lacks a second guidance statement. Reported origin and explicit rejection can both be true: origin is recorded separately by endpoint voice. Never synthesize an opposite belief. Context cannot supply absent endorsement/rejection.'},'criteria':{
       'own_or_adopted':'The content is the preacher\'s own assertion/directive, or is explicitly adopted/applied. For quoted text followed by the preacher\'s actual explanation, that explanation is their own treatment; this does not assign every quoted claim to them.',
       'not_adopted_report':'The content is reported without explicit adoption or rejection in target evidence.',
       'explicitly_rejected':'The target explicitly rejects this reported content/argument. Keep reported voice and the rejection together; do not replace rejection with plain reporting.',
       'unresolved':'Stance is ambiguous, mixed across endpoints, or insufficiently supported. Do not infer endorsement from topic/form.'}}
    for side in ('left','right'):
        q[f'p{position}_{side}_voice']={'instructions':{'task':f'Who voices the exact `{path}.{side}` content, using only target attribution and bounded context for referents? Voice origin is independent of endorsement/rejection and independent of edge existence.'},'criteria':{
          'preacher':'Own asserted/directive/explanatory language of the preacher, including a clearly applied present instruction.',
          'quoted_or_reported':'Words/proposition of Scripture, another speaker, narrated person or reported argument, whether adopted or rejected.',
          'mixed':'The endpoint contains both an attribution/own statement and substantial quoted/reported content.',
          'unresolved':'The voice is not adequately resolved.'}}
    return q


def bundles(c):
    """Add intact sentence nodes only for four adjudicated decomposition problems."""
    if c['case_id'] not in {'G2-05','G2-07','natural-1200-45','natural-590-64'}:return []
    text=c['target_text']; focus=c.get('candidate_focus');a=focus['start'] if focus else 0;b=focus['end'] if focus else len(text)
    units=[];cursor=a
    boundary=re.compile(r'(?<=[.!?])\s+|(?<=[.!?][\"\u0027])\s+')
    for match in [*boundary.finditer(text,a,b),None]:
        stop=match.start() if match else b;start=cursor
        while start<stop and text[start].isspace():start+=1
        while stop>start and text[stop-1].isspace():stop-=1
        if start<stop:units.append({'start':start,'end':stop,'text':text[start:stop]})
        if match:cursor=match.end()
    if c['case_id']=='natural-590-64':
        # Repair wrapped imperative objects; commas introduce another complete prayer/action clause.
        # This supplies source nodes, not an inferred rationale or endorsement.
        units=[];cursor=a
        split=re.compile(r',\s*(?=(?:pray for|and participate)\b)',re.I)
        for match in [*split.finditer(text,a,b),None]:
            stop=match.start() if match else b;start=cursor
            while start<stop and text[start].isspace():start+=1
            while stop>start and text[stop-1].isspace():stop-=1
            if start<stop:units.append({'start':start,'end':stop,'text':text[start:stop]})
            if match:cursor=match.end()
    existing={(v1.fp(p['left']),v1.fp(p['right'])) for p in c['pairs']};added=[]
    for i,left in enumerate(units):
        for j,right in enumerate(units):
            if i==j or abs(i-j)>2:continue
            key=(v1.fp(left),v1.fp(right))
            if key not in existing:
                added.append({'pair_id':f'bundle-{len(added)}','left':left,'right':right});existing.add(key)
    return added


def added_case(case_id,text,reason):
    pairs,diagnostics=v1.candidates(text)
    return {'case_id':case_id,'origin':'authored_narrow_revision_control','target_text':text,'leading_context':'','trailing_context':'','pairs':pairs,'candidate_diagnostics':diagnostics,'candidate_focus':None,'review_targets':[],'case_check':None,'source':{'authored_for':reason},'reused_evidence':[]}


def prepare():
    base,result,rows=load_baseline();cases=deepcopy(base['cases'])
    for c in cases:
        c['pairs']+=bundles(c)
        for t in c['review_targets']:
            if t.get('allowed_adoption'):
                t['allowed_adoption']=[value for a in t['allowed_adoption'] for value in (['unresolved','unclear'] if a=='unclear' else [{'rejected':'explicitly_rejected','reported':'not_adopted_report'}.get(a,a)])]
            if c['case_id']=='G2-04' and t['facet']=='specifies_response_step':
                t['expected']='not_linked';t['interpretation']='A: today is an intrinsic modifier of one directive, not a distinct guidance assertion.'
            if c['case_id']=='G2-07' and t['facet']=='qualifies_claim':
                t['expected']=['not_linked','unclear'];t['interpretation']='A: method-activity scope need not qualify the unqualified distinction claim.'
            if c['case_id']=='G2-11':t['expected']=['not_linked','incomplete','unclear']
            if c['case_id']=='natural-1200-23':t['expected']=['not_linked','unclear']
            if c['case_id']=='natural-590-64':t['expected']=['not_linked','unclear']
        if c['case_id']=='natural-590-64':
            c['review_targets'].append(v1.review_target('grounds_response','pray for our\nmissionaries','pray for evangelism','not_linked',adoption=['own_or_adopted'],reason='B: complete sibling prayer requests are not a reason-response pair; caption wrapping does not define semantic units.'))
        if c['case_id']=='natural-1200-45':
            c['review_targets'].append(v1.review_target('grounds_response',"He gave all, why shouldn't we?","Can't we spend time",'linked',adoption=['own_or_adopted'],reason='B: intact reason plus rhetorical bridge, retaining the old fragmented pair as a regression.'))
    additions=[
      added_case('revision-step-positive','Call your lonely neighbor. Start with a five-minute conversation.','Direct concrete initial method, contrasted with the same-topic unrelated duration.'),
      added_case('revision-step-proximity','Call your lonely neighbor. The office staff meeting lasts five minutes.','Same time quantity but different activity; no guidance binding.'),
      added_case('revision-qualification-positive','Call your neighbor. This invitation applies only if the neighbor welcomes contact.','Explicit restriction of this invitation, not scope of explaining a concept.'),
      added_case('revision-qualification-proximity','Call your neighbor. The church office opens only on weekdays.','Only restricts a different object; not the neighbor response.'),
      added_case('revision-report-only',"Some argue, 'Pain always proves guilt; therefore blame every sufferer.' I am reporting this view without endorsing it.",'Same reported argument without rejection, isolating origin versus stance.'),
    ]
    for c in additions:
        positive='positive' in c['case_id']
        if 'step-' in c['case_id']: c['review_targets']=[v1.review_target('specifies_response_step','Call your lonely neighbor','five-minute' if positive else 'five minutes','linked' if positive else 'not_linked',adoption=['own_or_adopted'],reason=c['source']['authored_for'])]
        elif 'qualification-' in c['case_id']:c['review_targets']=[v1.review_target('qualifies_claim','This invitation' if positive else 'church office','Call your neighbor','linked' if positive else 'not_linked',adoption=['own_or_adopted'],reason=c['source']['authored_for'])]
        else:c['review_targets']=[v1.review_target('reason_supports_claim','Pain always proves guilt','therefore blame','linked',adoption=['not_adopted_report'],reason=c['source']['authored_for'])]
    cases+=additions
    for c in cases:
        for t in c['review_targets']:t['matching_pair_ids']=[p['pair_id'] for p in c['pairs'] if v1.contains(p['left'],t['left_phrase']) and v1.contains(p['right'],t['right_phrase'])]
    reused=missing=0;requests=0
    for c in cases:
        case_missing=0
        for p in c['pairs']:
            saved=reusable(c,p,rows)
            reused+=len(saved);missing+=len(FIELDS)-len(saved)
            if len(saved)!=len(FIELDS):case_missing+=1
        requests+=math.ceil(case_missing/v1.BATCH_PAIRS)
    out={'version':'g2-one-cycle-feasibility-input-v2','status':'prepared_not_evaluated','production_effect':'none','model':v1.MODEL,'threshold':v1.THRESHOLD,'question_version':VERSION,'question_inventory_at_position_zero':questions(),'question_digest':v1.fp(questions()),'builder_version':BUILDER,'policy_version':POLICY,'baseline_input':BASE_INPUT_FP,'baseline_result':BASE_RESULT_FP,'audit_fingerprint':audit()['content_fingerprint'],'cases':cases,'holds':base['holds'],'budget':{'case_count':len(cases),'pair_count':sum(len(c['pairs']) for c in cases),'reused_V1_question_answers':reused,'maximum_new_question_answers':missing,'maximum_uncached_requests':requests,'sdk_retries':0,'batch_pairs':v1.BATCH_PAIRS},'scope':'Same 16 frozen targets/context/focus and all V1 pairs; whole-sentence overlays for four B controls; exactly five authored controls; no candidate pruning or cost tuning.'}
    out['content_fingerprint']=v1.fp(out);return out


def reusable(c,p,rows):
    row=rows.get(c['case_id'],{}).get(p['pair_id'])
    if row is None or row['pair']!=p or row.get('_baseline_state_fingerprint')!=v1.fp(v1.state_for(c,[p])):return {}
    q1,q2=v1.questions(),questions()
    return {f:{'answer':row['raw_answers'][f],'source':'frozen_V1_result','baseline_result':BASE_RESULT_FP,'request_provenance':row.get('request_provenance',{}),'source_question_version':v1.QUESTION_VERSION,'source_question_digest':v1.fp(v1.questions()[f'p0_{f}']),'requested_model':v1.MODEL} for f in row['raw_answers'] if f in FIELDS and q1.get(f'p0_{f}')==q2.get(f'p0_{f}')}


def validate_packet(packet):
    if packet!=prepare():raise ValueError('V2 packet/source/question/adjudication drift; prepare explicit revision before evaluating')
    if any(not t['matching_pair_ids'] for c in packet['cases'] for t in c['review_targets']):raise ValueError('Missing reviewed endpoint candidates')


def evaluate(packet,*,provider_factory=v1.Provider,cache_dir=CACHE):
    validate_packet(packet);_,_,baseline_rows=load_baseline();provider=None;requests=hits=reused=0;results=[]
    for c in packet['cases']:
        resolved={};pending=[]
        for pair in c['pairs']:
            answers=reusable(c,pair,baseline_rows);reused+=len(answers);identity_state=v1.state_for(c,[pair])
            for field,q in questions().items():
                name=field.removeprefix('p0_')
                if name in answers:continue
                identity={'state':identity_state,'question':q,'field':name,'model':packet['model']};key=v1.fp(identity);path=cache_dir/f'{key}.json'
                try:
                    entry=json.loads(path.read_text())
                    if entry['identity']!=identity or entry['fingerprint']!=v1.fp({k:v for k,v in entry.items() if k!='fingerprint'}):raise ValueError('Cache drift')
                    validate_answers({'p0_'+name:entry['answer']},{'p0_'+name:q})
                    if entry['resolved_model']!=packet['model']:raise ValueError('Cache model mismatch')
                    answers[name]={'answer':entry['answer'],'source':'V2_cache','request_provenance':entry['request_provenance'],'cache_key':key,'source_question_version':VERSION,'source_question_digest':v1.fp(q),'resolved_model':entry['resolved_model']};hits+=1
                except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):pass
            resolved[pair['pair_id']]=answers
            if len(answers)<len(FIELDS):pending.append(pair)
        for offset in range(0,len(pending),v1.BATCH_PAIRS):
            pairs=pending[offset:offset+v1.BATCH_PAIRS];inventory={}
            for i,pair in enumerate(pairs):
                inventory.update({k:q for k,q in questions(i).items() if k.removeprefix(f'p{i}_') not in resolved[pair['pair_id']]})
            if requests>=packet['budget']['maximum_uncached_requests']:raise ValueError('V2 budget exceeded')
            if provider is None:provider=provider_factory()
            requests+=1;state=v1.state_for(c,pairs);response=provider.assess(state,inventory)
            validate_answers(response['answers'],inventory)
            if response['resolved_model']!=packet['model']:raise ValueError('Pinned model mismatch')
            provenance={'request_key':v1.fp({'state':state,'questions':inventory,'model':packet['model']}),'usage':response.get('usage',{}),'batch_pair_count':len(pairs)}
            for i,pair in enumerate(pairs):
                for key,q in questions(i).items():
                    if key not in inventory:continue
                    field=key.removeprefix(f'p{i}_');answer=response['answers'][key]
                    identity={'state':v1.state_for(c,[pair]),'question':questions()[f'p0_{field}'],'field':field,'model':packet['model']}
                    entry={'identity':identity,'answer':answer,'resolved_model':response['resolved_model'],'request_provenance':provenance};entry['fingerprint']=v1.fp(entry)
                    cache_dir.mkdir(parents=True,exist_ok=True);(cache_dir/f'{v1.fp(identity)}.json').write_text(json.dumps(entry,indent=2)+'\n')
                    resolved[pair['pair_id']][field]={'answer':answer,'source':'V2_request','request_provenance':provenance,'cache_key':v1.fp(identity),'source_question_version':VERSION,'source_question_digest':v1.fp(questions()[f'p0_{field}']),'resolved_model':response['resolved_model']}
        rows=[]
        for pair in c['pairs']:
            provenance=resolved[pair['pair_id']];raw={f:v['answer'] for f,v in provenance.items()};decisions={f:v1.decision(a) for f,a in raw.items()}
            rows.append({'pair':pair,'raw_answers':raw,'decisions':decisions,'answer_provenance':provenance,'baseline_raw_answers':baseline_rows.get(c['case_id'],{}).get(pair['pair_id'],{}).get('raw_answers'),'baseline_decisions':baseline_rows.get(c['case_id'],{}).get(pair['pair_id'],{}).get('decisions'),'provisional_adopted_local_facets':[f for f in v1.FACETS if decisions[f]=='linked' and decisions['adoption']=='own_or_adopted' and decisions['boundary']=='local_sufficient']})
        results.append({'case_id':c['case_id'],'rows':rows})
    validate_packet(packet)
    out={'version':'g2-feasibility-results-v2','status':'evaluated_pending_PTE_interpretation_and_Brian_decision','input_fingerprint':packet['content_fingerprint'],'baseline_result':BASE_RESULT_FP,'question_version':VERSION,'question_digest':packet['question_digest'],'builder_version':BUILDER,'policy_version':POLICY,'requested_model':packet['model'],'execution':{'provider_requests':requests,'reused_V1_answers':reused,'V2_cache_hits':hits},'production_effect':'none','cases':results,'diagnostics':v1.diagnose(packet,results)}
    # Separate conservative withholding from demonstrated wrong edges in the screen.
    for check in out['diagnostics']['checks']:
        if check['status']=='unclear_or_missed_relation':check['status']='withheld_or_missed_relation_not_confirmed_wrong_edge'
        elif check['status']=='voice_adoption_failure':
            rows=next(c['rows'] for c in results if c['case_id']==check['case_id'])
            matched=[r for r in rows if r['pair']['pair_id'] in check['target']['matching_pair_ids']]
            if matched and all(r['decisions']['adoption'] in {'unclear','unresolved'} for r in matched):
                check['status']='source_stance_withheld_not_false_adoption'
    out['content_fingerprint']=v1.fp(out);return out


def render_audit(report):
    lines=['# G2 V1 manual error analysis — 2026-10-14','','Brian verdict: **PARTIAL PASS**. V1 input/results remain immutable.','','| Check | Case / facet | Bucket | Interpretation | Revision |','| --- | --- | --- | --- | --- |']
    for m in report['mismatches']:lines.append(f"| {m['check_index']} | {m['case_id']} / {m['facet']} | {m['bucket']} | {m['rationale']} | {m['proposed_resolution']} |")
    lines+=['','## All 15 linked cells reviewed','','| Case / pair / facet | Assessment | Bucket if problematic | Rationale |','| --- | --- | --- | --- |']
    for p in report['positive_cell_review']:lines.append(f"| {p['case_id']} / {p['pair_id']} / {p['facet']} | {p['assessment']} | {p['bucket'] or '—'} | {p['rationale']} |")
    lines+=['','A = contract/expected-label/reporting problem; B = candidate/boundary problem; C = judgment problem on a clear intended relation. Each mismatch has one primary bucket; its raw subcomponent uncertainty remains recorded in audit-v1.json. Correct argmax below .80 is withholding, not a wrong adopted belief. No threshold is lowered.','']
    return '\n'.join(lines)


def run(mode='evaluate'):
    if mode=='prepare':
        review=audit();write_json_markdown(HERE/'audit-v1.json',review,render_audit(review));packet=prepare()
        text=f"# G2 V2 prepared packet\n\nFingerprint: `{packet['content_fingerprint']}`\n\nBudget: `{json.dumps(packet['budget'])}`\n\nSee REVIEW.md and input-v2.json. No provider validation has run.\n"
        write_json_markdown(INPUT,packet,text);(HERE/'questions-v2.json').write_text(json.dumps(questions(),indent=2)+'\n');print(f"Prepared V2, provider_requests=0; {packet['budget']}")
    elif mode=='check':
        packet=json.loads(INPUT.read_text());validate_packet(packet)
        if json.loads((HERE/'audit-v1.json').read_text())!=audit() or json.loads((HERE/'questions-v2.json').read_text())!=questions():raise ValueError('Audit/question artifact drift')
        print('PASS: V2 frozen-case/audit/reuse integrity; no provider validation')
    elif mode=='evaluate':
        packet=json.loads(INPUT.read_text())
        try:report=evaluate(packet)
        except Exception as error:
            failure={'status':'execution_failed_incomplete_not_a_semantic_verdict','error_type':type(error).__name__,'input_fingerprint':packet.get('content_fingerprint'),'successful_question_caches_retained':True,'production_effect':'none'}
            write_json_markdown(RESULT.with_name('feasibility-v2.execution-failure.json'),failure,'# V2 execution failure\n\nIncomplete execution, no semantic verdict. Successful question caches retained.\n');raise
        write_json_markdown(RESULT,report,v1.render_results(report,packet));print(f"Wrote {RESULT}; {report['execution']}; pending interpretation")
    else:raise ValueError('Unsupported V2 mode')
