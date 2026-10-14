"""Isolated bounded G1 proof. Brian owns provider execution and the stop decision."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import runpy

from pastor_transcript_extractor.sermon_g2_feasibility_review import validate_answers

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'docs/review-proposals/g1-feasibility-v1'
PACKET_PATH = HERE / 'input-v1.json'
RESULT_DIR = ROOT / 'evaluation/g1-binding'
RESULT_PATH = RESULT_DIR / 'feasibility-v1.results.json'
CACHE_PATH = RESULT_DIR / 'cache-v1'
MODEL = 'jev-1.13.0'
VERSION = 'g1-bounded-source-binding-v1'
THRESHOLD = .80  # Experimental abstention policy; not production calibration.
RELATIONS = {
    'acceptance_knowable_now': 'The ability to know present acceptance/saving standing with God; not permanence or ordinary knowledge of God.',
    'loss_possible': 'Whether a saving relationship can be lost; not losing possessions or ordinary hardship.',
    'retention': 'Remaining saved/retaining salvation; keep explicit conditions without inferring the opposite.',
    'public_support': 'Support for the specific city requirement for ramps in new public buildings.',
    'public_opposition': 'Opposition to that specific ramp requirement; denial of opposition is not support.',
    'public_requirement': 'A prescription that the city should require ramps in new public buildings.',
    'no_match': 'No proposition/question/open issue in these two proof subjects is expressed by this candidate.',
    'unclear': 'The exact relation or its in-scope object remains unresolved.',
}
BOUNDARY = ('Judge only the exact candidate span in target_text, using other target wording for framing. '
            'Leading/trailing context resolves references only; it cannot supply a missing target claim, stance or qualification. '
            'Questions are independent and cannot see other answers. Preserve reported/rejected wording; never synthesize its opposite. '
            'Topic presence is not a proposition. No pastor belief, contradiction, coherence or quality judgment.')


def fp(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def file_fp(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def span(text, phrase, field='target_text'):
    start = text.index(phrase)
    return dict(source_field=field, start=start, end=start+len(phrase), text=phrase)


def candidates(case):
    """Coordinates and lexical phrase pools only; no gold labels or semantic roles."""
    text = case['target_text']
    units = []
    start = 0
    for match in [*re.finditer(r'(?<=[.!?])\s+|\n+', text), None]:
        end = match.start() if match else len(text)
        left, right = start, end
        while left < right and text[left].isspace(): left += 1
        while right > left and text[right-1].isspace(): right -= 1
        if left < right:
            units.append(dict(candidate_id=f"{case['case_id']}:unit-{len(units)}", claim_span=dict(source_field='target_text', start=left, end=right, text=text[left:right])))
        if match: start = match.end()
    if len(units) > 8: raise ValueError('Bounded candidate ceiling exceeded')
    pools = {}
    patterns = {
        'objects': r'accepted by God|salvation|\bsaved\b|(?:requiring|require|requirement for) ramps in new public buildings|ramps in new public buildings|that requirement|that proposal',
        'conditions': r'\b(?:if|unless|as long as|except when)\b[^.!?\n]*',
        'uncertainty': r'\b(?:I am unsure|I do not yet know|I don.t know|I am uncertain)\b[^.!?\n]*',
        'scopes': r'\bnow\b|\bpresent(?:ly)?\b|\bpermanent(?:ly)?\b|\bin this emergency\b|\bin ordinary circumstances\b',
    }
    for name, pattern in patterns.items():
        found = []
        for field in ('target_text', 'leading_context', 'trailing_context'):
            if name != 'objects' and field != 'target_text': continue
            for m in re.finditer(pattern, case[field], re.I):
                found.append(dict(source_field=field, start=m.start(), end=m.end(), text=m.group()))
        if len(found) > 6: raise ValueError('Bounded phrase pool exceeded')
        pools[name] = {f'{name}-{i}': s for i,s in enumerate(found)}
    pools['frames'] = {f'frame-{i}': deepcopy(u['claim_span']) for i,u in enumerate(units)}
    return units, pools


def question(task, criteria):
    return dict(instructions=dict(task=task, boundary=BOUNDARY), criteria=criteria)


def questions(pools):
    q = {
        'subject': question('Which exact proof object is expressed by candidate.claim_span? Resolve references only if source wording fixes them.', {
            'salvation_acceptance': 'Saving acceptance/standing, loss or retention of salvation.',
            'city_ramp_requirement': 'The city requirement for ramps in new public buildings.',
            'no_match': 'No in-scope object/proposition, including merely treating the topic.',
            'unclear': 'Object/referent is unresolved; do not invent it.'}),
        'relation': question('Which relation is actually expressed by the exact candidate, including a reported proposition or explicit question/open issue? Topic discussion alone has no relation.', RELATIONS),
        'polarity': question('Relative to the voiced relation, is this candidate affirmative, negative, or an explicit unresolved issue? Rejection of a quote keeps its quoted polarity.', {
            'affirmed': 'The voiced relation is affirmative.', 'denied': 'The voiced relation is explicitly negated.',
            'unsettled': 'An unanswered question or explicit open issue, not a model withholding.',
            'no_expression': 'No in-scope proposition is voiced.', 'unclear': 'Voiced polarity is unresolved.'}),
        'expression': question('What expression is evidenced in this candidate?', {
            'assertion': 'An asserted proposition, including reports and qualified assertions.',
            'question': 'A question with no asserted answer; do not infer rhetorical polarity.',
            'open_issue': 'An explicitly unresolved/open issue.', 'no_expression': 'No in-scope expression.', 'unclear': 'Expression is unresolved.'}),
        'voice': question('Who voices the proposition in this candidate? Adoption is a separate judgment.', {
            'preacher': 'The speaker personally voices the proposition.', 'reported_teachers': 'Explicitly reported teachers.',
            'mayor': 'The explicitly reported mayor.', 'reported_other': 'Another explicitly reported speaker.',
            'mixed': 'More than one inseparable voice.', 'unclear': 'Voice is unresolved.'}),
        'adoption': question('What is the preacher’s adoption of the exact voiced proposition? Read explicit report/rejection/adoption framing in target_text. Never adopt an inferred opposite.', {
            'own_assertion': 'Personally asserted by the preacher, with conditions intact.',
            'explicitly_adopted': 'A report/quote is explicitly adopted.', 'reported_not_adopted': 'Reported without adoption.',
            'explicitly_rejected': 'This voiced proposition is explicitly rejected; retain its voiced polarity.',
            'undetermined': 'No adoption evidenced, including unanswered question/open issue.', 'unclear': 'Adoption unresolved.'}),
        'epistemic_status': question('Does candidate.claim_span explicitly express the voiced speaker’s uncertainty about its proposition? Model uncertainty is never speaker uncertainty.', {
            'expressed_uncertainty': 'Explicit uncertainty language tied to this proposition.',
            'not_stated': 'No explicit uncertainty language; a bare unanswered question does not suffice.', 'unclear': 'Binding of uncertainty unresolved.'}),
        'boundary': question('Can this local candidate’s object/proposition/framing be assessed without importing omitted treatment?', {
            'local_sufficient': 'Locally sufficient; not complete sermon/episode coverage.',
            'continuation_required': 'Needed local evidence is omitted.', 'unclear': 'Local sufficiency unresolved.'}),
    }
    for name, key, task in [('objects','object_anchor','Select the source phrase that actually identifies this candidate’s object; context may resolve a referent only.'),
                            ('uncertainty','epistemic_evidence','Select explicit uncertainty language actually attached to the proposition/voiced speaker in this candidate.'),
                            ('scopes','scope_evidence','Select explicit scope wording actually attached to this candidate; otherwise do not invent unrestricted scope.'),
                            ('frames','voice_evidence','Select the target sentence actually grounding the proposition speaker/voice for this candidate.'),
                            ('frames','adoption_evidence','Select the target sentence actually grounding adoption/report/rejection of this candidate; not a nearby unrelated stance.')]:
        options = {sid: {'meaning': task, 'source_span': s} for sid,s in pools[name].items()}
        q[key] = question(task, {**options, 'none': 'No corresponding explicit attached source phrase.', 'unclear': 'Attachment/reference unresolved.'})
    for sid, s in pools['conditions'].items():
        q['bind_'+sid] = question('Does this exact condition/exception phrase attach to candidate.claim_span, rather than another claim? Preserve its connective without inferring necessity/sufficiency.', {
            'bound': {'meaning': 'Target explicitly attaches this phrase to this claim.', 'source_span':s},
            'not_bound': 'Not attached to this candidate, or only to another claim.', 'unclear': 'Attachment unresolved.'})
    return q


def _case(cid, text, expected, reason, leading='', trailing='', source=None, origin='authored'):
    case = dict(case_id=cid, origin=origin, target_text=text, leading_context=leading, trailing_context=trailing,
                expected_claims=expected, reason=reason, source=source or {'kind':'authored_design'})
    case['candidates'], case['phrase_pools'] = candidates(case)
    case['source_text_fingerprint'] = fp({k:case[k] for k in ('target_text','leading_context','trailing_context')})
    return case


def prepare():
    design_path = 'docs/review-proposals/g1-binding-v1/cases-v1.json'
    design = json.loads((ROOT/design_path).read_text())
    runpy.run_path(str(ROOT/'docs/review-proposals/g1-binding-v1/build_cases.py'))['validate'](design)
    cases = [_case(c['case_id'],c['target_text'],c['expected_claims'],c['reason'],c['leading_context'],c['trailing_context'],{'path':design_path,'case_id':c['case_id']}) for c in design['cases']]
    # Fixed authored additions; expectations are not inputs to the candidate builder/provider.
    for cid,text,expected,reason in [
        ('B01','Some teachers say salvation can be lost, but I will not specify an alternative here.', [], 'Reported claim remains; no own/adopted alternative may be invented.'),
        ('B02','Salvation is our topic today.', [], 'Topic treatment alone supplies no bounded proposition.'),
        ('B03','The city discusses ramps in new public buildings.', [], 'A public topic supplies no support/opposition/prescription.'),
        ('B04','Salvation can be lost in this emergency. Salvation cannot be lost in ordinary circumstances.', [], 'Retain two differently scoped local claims without any contradiction/G4 verdict.'),
        ('B05','Salvation can be lost. I support requiring ramps in new public buildings if an equivalent accessible entrance is permitted.', [], 'The ramp condition cannot attach to the salvation claim.')]:
        cases.append(_case(cid,text,expected,reason))
    # Three frozen natural negatives. No new corpus search, annotation or production collection.
    for filename,video,block,phrase in [
        ('source-material-review-v1.json',4430,57,"I don't think God can forgive me."),
        ('source-material-review-v1.json',4430,25,'Jesus said something very clear.'),
        ('salvation-relationships-review-v3.json',1200,44,'The treasure of the gospel is extremely valuable.')]:
        path='evaluation/sermon-topics/'+filename
        row=next(c for c in json.loads((ROOT/path).read_text())['cases'] if c['video_id']==video and c['block_id']==block)
        start=row['target_text'].index(phrase)
        cases.append(_case(f'N-{video}-{block}',phrase,[], 'Natural source control: outside the bounded assurance/ramp relations, not a claim of no theology.',
                           row['target_text'][:start][-350:], row['target_text'][start+len(phrase):][:350],
                           dict(path=path,video_id=video,block_id=block,original_start=start,original_end=start+len(phrase),start_seconds=row['start_seconds'],end_seconds=row['end_seconds']), 'natural_archived_control'))
    # Expectations for supplemental controls are narrow, explicit checks rather than fabricated gold records.
    supplemental = {
        'B01':[dict(phrase='Some teachers say',fields={'subject':'salvation_acceptance','relation':'loss_possible','voice':'reported_teachers','adoption':'reported_not_adopted','polarity':'affirmed'})],
        'B02':[dict(phrase='Salvation',fields={'relation':'no_match'})],
        'B03':[dict(phrase='The city',fields={'relation':'no_match'})],
        'B04':[dict(phrase='in this emergency',fields={'relation':'loss_possible','polarity':'affirmed','scope_text':'in this emergency'}),dict(phrase='in ordinary circumstances',fields={'relation':'loss_possible','polarity':'denied','scope_text':'in ordinary circumstances'})],
        'B05':[dict(phrase='Salvation can',fields={'relation':'loss_possible','conditions':[]}),dict(phrase='I support',fields={'relation':'public_support','conditions':['if an equivalent accessible entrance is permitted']})],
    }
    supplemental['P07'] = [dict(phrase='I support', fields={'subject':{'allowed':['unclear','no_match']}})]
    for c in cases:
        c['review_checks'] = supplemental.get(c['case_id'],[])
        c['no_in_scope_claim_expected'] = c['case_id'] in {'A06','B02','B03'} or c['origin']=='natural_archived_control'
    source_paths = [design_path,'evaluation/sermon-topics/source-material-review-v1.json','evaluation/sermon-topics/salvation-relationships-review-v3.json']
    total = sum(len(c['candidates']) for c in cases)
    packet = dict(version=VERSION,status='prepared_not_evaluated',production_effect='none',model=MODEL,threshold=THRESHOLD,
                  cases=cases,sources={p:file_fp(ROOT/p) for p in source_paths},
                  holds=['G1 expansion/full collection','G2/G3 retuning','broader collection','candidate-discovery recall','production calibration','opportunity denominators','request economics study','pastor projection/comparison','clustering','G4','recurrence/rates','quality scoring'],
                  budget=dict(provider_request_ceiling=total,questions=sum(len(questions(c['phrase_pools']))*len(c['candidates']) for c in cases),sdk_retries=0,candidates_per_request=1,timeout_seconds=45),
                  limitations=['Prepared source windows and lexical phrase pools only; no automatic recall claim.', 'Natural controls are negatives in this bounded vocabulary; natural positive feasibility remains unestablished.', 'No production eligibility/membership or measured pastor positions.', 'Natural leading/trailing context uses fixed at-most-350-character windows; no complete boundary/episode claim.'])
    packet['content_fingerprint']=fp(packet)
    return packet


def validate(packet):
    if packet.get('content_fingerprint') != fp({k:v for k,v in packet.items() if k!='content_fingerprint'}): raise ValueError('Packet fingerprint mismatch')
    if packet != prepare(): raise ValueError('Fixed packet/source/question policy drift')
    for c in packet['cases']:
        for unit in c['candidates']:
            s=unit['claim_span']
            if s['source_field']!='target_text' or c['target_text'][s['start']:s['end']]!=s['text']: raise ValueError('Invalid target span')
    if len(packet['cases'])!=28 or packet['budget']['provider_request_ceiling']>60: raise ValueError('Bounded inventory/budget drift')


def state_for(case, unit):
    return {k:deepcopy(case[k]) for k in ('target_text','leading_context','trailing_context','phrase_pools')} | {'candidate':deepcopy(unit)}


def decisions(raw):
    return {k:v['choice'] if v['probabilities'][v['choice']]>=THRESHOLD else 'unclear' for k,v in raw.items()}


def compose(case, unit, d):
    """Compose partial local facts; never normalize rejection into an opposite."""
    pools=case['phrase_pools']
    known=lambda name,pool: deepcopy(pools[pool].get(d.get(name)))
    conditions=[dict(kind='exception' if s['text'].lower().startswith(('unless','except')) else 'condition',span=deepcopy(s)) for sid,s in pools['conditions'].items() if d.get('bind_'+sid)=='bound']
    notes=[]
    for k in ('subject','relation','polarity','expression','voice','adoption','boundary','object_anchor','epistemic_status','epistemic_evidence','scope_evidence','voice_evidence','adoption_evidence'):
        if d[k]=='unclear': notes.append(k+'_withheld')
    notes += [sid+'_binding_withheld' for sid in pools['conditions'] if d.get('bind_'+sid)=='unclear']
    subject_span=known('object_anchor','objects')
    if d['subject'] in {'salvation_acceptance','city_ramp_requirement'} and subject_span is None:notes.append('subject_evidence_missing')
    epistemic_span=known('epistemic_evidence','uncertainty')
    scope_span=known('scope_evidence','scopes')
    exists=d['subject'] in {'salvation_acceptance','city_ramp_requirement'} and d['relation'] in RELATIONS and d['relation'] not in {'no_match','unclear'} and subject_span is not None
    # Independent choices must form a compatible subject/relation; no silent repair.
    if exists and ((d['subject']=='salvation_acceptance') != (d['relation'] in {'acceptance_knowable_now','loss_possible','retention'})):
        exists=False;notes.append('incompatible_subject_relation')
    uncertainty='expressed_uncertainty' if d['epistemic_status']=='expressed_uncertainty' and epistemic_span else 'not_stated' if d['epistemic_status']=='not_stated' else 'unresolved'
    if d['epistemic_status']=='expressed_uncertainty' and not epistemic_span: notes.append('uncertainty_evidence_missing')
    voice_span=known('voice_evidence','frames');adoption_span=known('adoption_evidence','frames')
    if d['voice'] not in {'unclear','mixed'} and not voice_span:notes.append('voice_evidence_missing')
    if d['adoption'] in {'own_assertion','explicitly_adopted','reported_not_adopted','explicitly_rejected'} and not adoption_span:notes.append('adoption_evidence_missing')
    adopted=exists and d['adoption'] in {'own_assertion','explicitly_adopted'} and d['voice'] not in {'unclear','mixed'} and d['polarity'] in {'affirmed','denied'} and d['expression']=='assertion' and d['boundary']=='local_sufficient' and not notes
    return dict(candidate_id=unit['candidate_id'],claim_span=deepcopy(unit['claim_span']),subject_id=d['subject'],relation=d['relation'],polarity=d['polarity'],expression=d['expression'],voice=d['voice'],adoption=d['adoption'],subject_evidence=subject_span,binding_evidence=[deepcopy(unit['claim_span'])]+[s for s in (voice_span,adoption_span) if s is not None],voice_evidence=voice_span,adoption_evidence=adoption_span,conditions=conditions,epistemic_status=uncertainty,epistemic_evidence=epistemic_span,scope_text=scope_span['text'] if scope_span else None,scope_evidence=scope_span,
                observation_state='local_claim' if exists else 'no_in_scope_claim' if d['relation']=='no_match' else 'binding_withheld',provisional_adopted_local_assertion=bool(adopted),diagnostics=notes,claim_coverage='candidate_coverage_unknown',pastor_projection=None,contradiction_verdict=None,quality_score=None)


class Provider:
    def __init__(self):
        from typesafe_sdk import TypeSafeClient,Choice,RetryPolicy
        self.Choice=Choice
        self.client=TypeSafeClient(model=MODEL,timeout=45,retry=RetryPolicy(max_retries=0))
    def assess(self,state,inventory):
        result=self.client.system_one(state,{k:self.Choice(**q) for k,q in inventory.items()},model=MODEL,timeout=45)
        return dict(answers={k:dict(choice=str(a.choice),probabilities=dict(a.probabilities),confidence=getattr(a,'confidence',None)) for k,a in result.choices.items()},resolved_model=str(result.model),request_id=getattr(result,'request_id',None),usage=dict(input_tokens=getattr(result.usage,'input_tokens',None),output_tokens=getattr(result.usage,'output_tokens',None)))
    def close(self):
        self.client.close()


def _write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def _save_ledger(path,ledger):
    ledger['content_fingerprint']=fp({k:v for k,v in ledger.items() if k!='content_fingerprint'})
    _write(path,ledger)


def evaluate(packet,*,provider_factory=Provider,cache_dir=CACHE_PATH):
    validate(packet)
    cache_dir.mkdir(parents=True,exist_ok=True)
    ledger_path=cache_dir/'request-ledger.json'
    ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else dict(input_fingerprint=packet['content_fingerprint'],attempted_requests=0,attempts=[])
    if ledger_path.exists() and ledger.get('content_fingerprint')!=fp({k:v for k,v in ledger.items() if k!='content_fingerprint'}):raise ValueError('Corrupt request ledger')
    if ledger['input_fingerprint']!=packet['content_fingerprint'] or ledger['attempted_requests']!=len(ledger['attempts']): raise ValueError('Request ledger identity/count mismatch')
    rows=[];hits=0;new=0;provider=None
    try:
        for case in packet['cases']:
            for unit in case['candidates']:
                state=state_for(case,unit);inventory=questions(case['phrase_pools'])
                identity=dict(state=state,questions=inventory,model=MODEL,version=VERSION,input_fingerprint=packet['content_fingerprint'])
                key=fp(identity);path=cache_dir/(key+'.json')
                if path.exists():
                    cached=json.loads(path.read_text())
                    if cached['identity']!=identity or cached['fingerprint']!=fp({k:v for k,v in cached.items() if k!='fingerprint'}): raise ValueError('Corrupt cache; do not silently rerun')
                    response=cached['response'];hits+=1
                else:
                    if ledger['attempted_requests']>=packet['budget']['provider_request_ceiling']: raise ValueError('Cumulative provider request ceiling exhausted')
                    if provider is None:provider=provider_factory()
                    ledger['attempted_requests']+=1;new+=1
                    attempt=dict(request_key=key,case_id=case['case_id'],candidate_id=unit['candidate_id'],status='attempted')
                    ledger['attempts'].append(attempt);_save_ledger(ledger_path,ledger)
                    response=provider.assess(state,inventory)
                    attempt.update(status='response_received',request_id=response.get('request_id'),usage=response.get('usage',{}),resolved_model=response.get('resolved_model'));_save_ledger(ledger_path,ledger)
                    validate_answers(response['answers'],inventory)
                    if response['resolved_model']!=MODEL:raise ValueError('Resolved model mismatch')
                    attempt.update(status='completed',request_id=response.get('request_id'),usage=response.get('usage',{}));_save_ledger(ledger_path,ledger)
                    cached=dict(identity=identity,response=response);cached['fingerprint']=fp(cached);_write(path,cached)
                validate_answers(response['answers'],inventory)
                if response['resolved_model']!=MODEL:raise ValueError('Cached resolved model mismatch')
                d=decisions(response['answers'])
                rows.append(dict(case_id=case['case_id'],candidate=deepcopy(unit),raw_answers=response['answers'],decisions=d,observation=compose(case,unit,d),cache_key=key,resolved_model=response['resolved_model'],request_id=response.get('request_id'),usage=response.get('usage',{})))
    except Exception as error:
        ledger['last_failure']=dict(error_type=type(error).__name__,successful_caches_retained=True)
        _save_ledger(ledger_path,ledger)
        raise
    finally:
        if provider is not None and hasattr(provider,'close'):provider.close()
    checks=diagnose(packet,rows)
    report=dict(version=VERSION,status='evaluated_pending_interpretation_and_Brian_decision',input_fingerprint=packet['content_fingerprint'],model=MODEL,production_effect='none',execution=dict(provider_requests=new,cache_hits=hits,cumulative_attempted_requests=ledger['attempted_requests'],sdk_retries=0,known_cumulative_input_tokens=sum(a.get('usage',{}).get('input_tokens') or 0 for a in ledger['attempts']),known_cumulative_output_tokens=sum(a.get('usage',{}).get('output_tokens') or 0 for a in ledger['attempts']),requests_with_unknown_usage=sum(any(a.get('usage',{}).get(k) is None for k in ('input_tokens','output_tokens')) for a in ledger['attempts'])),request_ledger=deepcopy(ledger),rows=rows,diagnostics=checks)
    report['content_fingerprint']=fp(report)
    return report


def diagnose(packet,rows):
    checks=[]
    for case in packet['cases']:
        local=[r for r in rows if r['case_id']==case['case_id']]
        for gold in case['expected_claims']:
            matches=[r for r in local if gold['claim_span']['text'] in r['candidate']['claim_span']['text']]
            want={k:gold[k] for k in ('subject_id','relation','polarity','expression','voice','adoption','epistemic_status','scope_text')}
            want['conditions']=[c['span']['text'] for c in gold['conditions']]
            for key,expected in want.items():
                got=[r['observation'][key] if key!='conditions' else [c['span']['text'] for c in r['observation']['conditions']] for r in matches]
                checks.append(dict(case_id=case['case_id'],claim_id=gold['claim_id'],field=key,expected=expected,actual=got,status='matches_proposal' if expected in got else 'omitted_candidate' if not matches else 'withheld_or_mismatch'))
        for gold in case['review_checks']:
            matches=[r for r in local if gold['phrase'] in r['candidate']['claim_span']['text']]
            for key,expected in gold['fields'].items():
                mapped='subject_id' if key=='subject' else key
                got=[r['observation'][mapped] if key!='conditions' else [c['span']['text'] for c in r['observation']['conditions']] for r in matches]
                checks.append(dict(case_id=case['case_id'],field=key,expected=expected,actual=got,status='matches_proposal' if (any(v in expected['allowed'] for v in got) if isinstance(expected,dict) and 'allowed' in expected else expected in got) else 'omitted_candidate' if not matches else 'withheld_or_mismatch'))
        if case['case_id'] in {'A05','A08','P03','B01'}:
            checks.append(dict(case_id=case['case_id'],field='no_adopted_opposite_or_report_transfer',status='adoption_transfer_or_invented_opposite' if any(r['observation']['provisional_adopted_local_assertion'] for r in local) else 'matches_proposal'))
        if case['case_id']=='P10':
            checks.append(dict(case_id='P10',field='denied_opposition_is_not_support',status='invented_support' if any(r['observation']['relation']=='public_support' and r['observation']['observation_state']=='local_claim' for r in local) else 'matches_proposal'))
        if case['no_in_scope_claim_expected']:
            checks.append(dict(case_id=case['case_id'],field='topic/context_control',status='false_local_claim' if any(r['observation']['observation_state']=='local_claim' for r in local) else 'matches_proposal'))
    return dict(checks=checks,positive_or_partial_rows_require_semantic_review=[r['candidate']['candidate_id'] for r in rows if r['observation']['observation_state']!='no_in_scope_claim'],automatic_pass=False,automatic_candidate_recall='not_tested',contradiction_or_profile_verdict='not_performed')


def render(packet,report=None):
    if report is None:
        lines=['# G1 fixed feasibility packet V1','',f"Status: {packet['status']}. Cases: {len(packet['cases'])}; source candidates: {packet['budget']['provider_request_ceiling']}; uncached request ceiling: {packet['budget']['provider_request_ceiling']}; independent questions: {packet['budget']['questions']}. Provider execution is reserved for Brian.",'']
        for c in packet['cases']:
            lines += [f"## {c['case_id']} ({c['origin']})",'',c['target_text'],'',c['reason'],'',f"Source: `{json.dumps(c['source'])}`",'']
            for gold in c['expected_claims']:lines.append('- Authored expected local claim: `'+json.dumps(gold,ensure_ascii=False)+'`')
            for gold in c['review_checks']:lines.append('- Expected control: `'+json.dumps(gold,ensure_ascii=False)+'`')
            if c['no_in_scope_claim_expected']:lines.append('- Expected: no in-scope claim in this target; not a statement about the whole sermon.')
            lines.append('')
    else:
        lines=['# G1 bounded feasibility results V1','',report['status'],'',f"Execution: `{json.dumps(report['execution'])}`",'','No automatic PASS, production observation credit, pastor-level position or coherence judgment.','']
        for c in packet['cases']:
            lines += [f"## {c['case_id']}",'',c['target_text'],'']
            for row in report['rows']:
                if row['case_id']==c['case_id']:lines += ['- '+row['candidate']['claim_span']['text'],'  Observation: `'+json.dumps(row['observation'],ensure_ascii=False)+'`']
        lines += ['','## Prepared expectation checks','']
        lines += ['- '+json.dumps(c,ensure_ascii=False) for c in report['diagnostics']['checks']]
    return '\n'.join(lines)+'\n'


def run(mode='evaluate'):
    if mode=='prepare':
        packet=prepare();validate(packet);_write(PACKET_PATH,packet)
        (HERE/'input-v1.md').write_text(render(packet))
        _write(HERE/'questions-v1.json', {c['case_id']:questions(c['phrase_pools']) for c in packet['cases']})
        print(f"Prepared {len(packet['cases'])} cases; {packet['budget']['provider_request_ceiling']} request ceiling; provider_requests=0")
    elif mode=='check':
        packet=json.loads(PACKET_PATH.read_text());validate(packet)
        if json.loads((HERE/'questions-v1.json').read_text())!={c['case_id']:questions(c['phrase_pools']) for c in packet['cases']}:raise ValueError('Published question drift')
        print('PASS: fixed G1 packet/source/question integrity only; provider_requests=0; empirical feasibility untested')
    elif mode=='evaluate':
        packet=json.loads(PACKET_PATH.read_text());validate(packet)
        try:report=evaluate(packet)
        except Exception as error:
            failure=dict(status='execution_failed_not_semantic_verdict',input_fingerprint=packet['content_fingerprint'],error_type=type(error).__name__,successful_caches_retained=True,production_effect='none')
            _write(RESULT_DIR/'feasibility-v1.execution-failure.json',failure)
            (RESULT_DIR/'feasibility-v1.execution-failure.md').write_text('# G1 execution failure\n\nIncomplete execution; no semantic feasibility verdict. Successful caches and cumulative request ledger retained.\n')
            raise
        _write(RESULT_PATH,report);RESULT_PATH.with_suffix('.md').write_text(render(packet,report))
        print(f"Wrote {RESULT_PATH} and {RESULT_PATH.with_suffix('.md')}; {json.dumps(report['execution'])}; interpretation required, no automatic PASS")
    else:raise ValueError('Unsupported G1 mode')
