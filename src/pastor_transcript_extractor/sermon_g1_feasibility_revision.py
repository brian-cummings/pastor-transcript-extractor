"""One G1 V2 refinement over the exact V1 cases, states and expectations."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import math

from pastor_transcript_extractor import sermon_g1_feasibility_review as v1

ROOT = v1.ROOT
HERE = ROOT / 'docs/review-proposals/g1-feasibility-v2'
INPUT = HERE / 'input-v2.json'
RESULT = v1.RESULT_DIR / 'feasibility-v2.results.json'
CACHE = v1.RESULT_DIR / 'cache-v2'
VERSION = 'g1-negation-proposition-voice-and-attitude-v2'
CHANGED = ('relation', 'polarity', 'voice', 'adoption')
BASE_INPUT_FP = '36b41939722ed7f70dafe188353b0256258e23b68319be6b56246677f4de89ef'
BASE_RESULT_FP = '2aa8297d74f54040b9a368b6f6ddb9c092c5769d91a16ccb0dcc88f58de9d35e'
BASE_INPUT_SHA = '5d7e2366bdd99d1ffe06487819daf05aa30becc79e058f615b4f5d72126b7a63'
BASE_RESULT_SHA = '8926ae5d83a871700714c6e3e640ec5ba736a30b62eac0d71938be73aa8d211c'
FAMILIES = {
    'simple_negation': {'cases': ['A03','A07','A08','P10','B04'], 'fields': ['relation','polarity','adoption']},
    'direct_preacher_voice': {'cases': ['A01','A02','A10'], 'fields': ['voice','adoption']},
    'public_attitude_vs_prescription': {'cases': ['P01','P02','P03','P05','P06','P10','B05'], 'fields': ['relation','polarity','voice','adoption']},
}


def questions(pools):
    """Same output vocabulary and state; refine only four independent questions."""
    q = deepcopy(v1.questions(pools))
    q['relation'] = v1.question(
        'Identify the UNDERLYING PREDICATE of the exact candidate proposition independently of its affirmation, negation, question/open-issue form, source voice and adoption. '
        'Choose the same predicate for X and not-X; polarity records whether it is affirmed or denied. Negation must not move a loss predicate into retention. '
        'For public statements identify the MAIN predication: supports/rejects the specified requirement is an attitude ABOUT a proposal; requiring inside that object does not turn support into a prescription. '
        'A city-should-require statement itself is prescription. A request that listeners campaign, vote or take action is listener advocacy, not an asserted support/opposition attitude or institutional prescription by itself; use no_match unless an independent in-scope predicate is actually expressed. '
        'A bare report/rejection frame with no separately expressed proof proposition supplies no new opposite claim. Preserve the original quoted proposition on its own candidate. '
        'An unresolved object remains unresolved; topic treatment alone supplies no predicate.', {
            'acceptance_knowable_now': 'Predicate: present saving acceptance is knowable. Select also for denial of knowability or an explicit question/open issue about that predicate. Not permanence.',
            'loss_possible': 'Predicate: salvation/saving standing CAN BE LOST. Both can be lost and cannot be lost use loss_possible; their polarity differs. This is not retention merely because loss is denied.',
            'retention': 'Predicate: a person REMAINS SAVED or RETAINS SALVATION. Requires expressed remaining/retaining, with its qualifications. Do not infer this predicate as the opposite of loss.',
            'public_support': 'Predicate: a person SUPPORTS the specific city ramp requirement. Reported or direct support, including support for requiring ramps, uses this relation. Denying support stays this predicate with denied polarity. Requiring inside the object is not the main prescription.',
            'public_opposition': 'Predicate: a person OPPOSES the specific city ramp requirement. Opposes is affirmative opposition; does not oppose is denied opposition. Neither becomes public_support automatically. Reported opposition keeps this predicate independently of adoption.',
            'public_requirement': 'Main proposition PRESCRIBES that the city should require ramps/adopt the requirement. Not merely supporting or opposing a proposal whose content includes requiring ramps; not listener advocacy.',
            'no_match': 'No independently expressed in-scope proposition/question/open issue, including topic-only language, unrelated policy, or bare metadiscourse without a new proposition. No opposite is synthesized from rejection.',
            'unclear': 'Predicate or its in-scope object is genuinely unresolved. Do not replace ambiguity with a guessed relation.'})
    q['polarity'] = v1.question(
        'Judge the polarity of the UNDERLYING PREDICATE voiced in candidate.claim_span, not the emotional valence of its vocabulary and not the preacher’s endorsement. '
        'For loss_possible, can be lost affirms and cannot be lost denies the SAME predicate. For public_opposition, oppose affirms opposition and do not oppose denies opposition; opposition is not inherently denied polarity. '
        'For public_support, support affirms and do not support denies support. Institutional prescription has its own predicate. '
        'Keep quoted/reported polarity even when target_text rejects that quote. A rejected quoted denial remains a voiced denial, not an adopted affirmation. '
        'Each question is independent: infer no relation from another answer.', {
            'affirmed': 'The candidate affirmatively voices the predicate, including a reported affirmative proposition, qualified assertion, support or opposition. Lexically negative attitude is not propositional negation.',
            'denied': 'The predicate itself is explicitly negated, including cannot lose/cannot be lost or do not oppose. Report rejection outside the quote never flips its voiced polarity.',
            'unsettled': 'An unanswered question or explicit open issue expresses no asserted answer. Not a model withholding.',
            'no_expression': 'No in-scope proposition is voiced by this candidate.',
            'unclear': 'Actual voiced polarity is unresolved; withhold without inventing an answer.'})
    q['voice'] = v1.question(
        'Who originates the in-scope PROPOSITION CONTENT of this sermon candidate? Distinguish the proposition speaker from a narrator introducing or commenting on it. '
        'An ordinary unquoted, unattributed declarative assertion in the preacher’s current sermon discourse is the preacher’s own speech; it does not require I teach, I believe, a name, or an introductory attribution. '
        'This convention does not override quotation, Scripture attribution, reported/historical speakers, dialogue, ambiguous first-person reference or genuinely unresolved framing. '
        'For a reported proposition followed by the preacher’s reporting/disclaimer frame, preserve the reported proposition’s origin rather than labeling its reporting wrapper mixed by itself. '
        'If substantive proposition content genuinely has inseparable origins, retain mixed; do not default every candidate to preacher. Voice does not determine adoption.', {
            'preacher': 'The proposition is directly voiced in the preacher’s current unquoted/unattributed assertion or question, including second-person or impersonal sermon assertions. Clear source framing must support this; reported content is excluded.',
            'reported_teachers': 'The proposition belongs to explicitly reported teachers, even when the preacher narrates, rejects or comments on it.',
            'mayor': 'The proposition belongs to the explicitly reported mayor, whether endorsed, unadopted or rejected.',
            'reported_other': 'The proposition belongs to another explicitly reported/quoted speaker; retain its actual source framing.',
            'mixed': 'The proposition content itself contains multiple inseparable voices; not merely a report plus the preacher’s disclaimer about that report.',
            'unclear': 'Origin is genuinely unresolved from the provided discourse; quotation/identity ambiguities must continue to withhold.'})
    q['adoption'] = v1.question(
        'How does the preacher treat the exact VOICED PROPOSITION, separately from its positive/negative predicate and its origin? '
        'Direct personal assertions in ordinary unquoted sermon discourse, including impersonal/second-person assertions and negative assertions, are own assertions when not framed as reports or open issues. '
        'Do not require an I believe marker, and do not mistake a denial, an opposition claim, or two differently scoped assertions for uncertain adoption. '
        'Explicit rejection of reported content takes precedence over plain unadopted reporting, but does not invert the report into an adopted opposite. '
        'Bare unanswered questions and explicitly unresolved issues do not assert an answer. Quotes/reports need explicit adoption to receive adopted credit.', {
            'own_assertion': 'The preacher directly asserts this affirmative, negative or qualified proposition in current discourse. No assertion of the opposite or unconditional scope is inferred.',
            'explicitly_adopted': 'A quoted/reported proposition is explicitly adopted by the preacher in target evidence.',
            'reported_not_adopted': 'The proposition is reported without explicit adoption or rejection. It remains attributable to the reported speaker.',
            'explicitly_rejected': 'The target explicitly rejects this reported proposition. Preserve the original voice and voiced polarity; do not replace rejection with ordinary reporting or create an adopted opposite.',
            'undetermined': 'No asserted adoption is established, including an unanswered question or explicit open issue; do not supply an answer.',
            'unclear': 'Actual adoption is genuinely unresolved or inseparably mixed; retain withholding.'})
    return q


def load_baseline():
    if v1.file_fp(v1.PACKET_PATH) != BASE_INPUT_SHA or v1.file_fp(v1.RESULT_PATH) != BASE_RESULT_SHA:
        raise ValueError('Frozen V1 input/result bytes changed')
    packet = json.loads(v1.PACKET_PATH.read_text()); v1.validate(packet)
    result = json.loads(v1.RESULT_PATH.read_text())
    if packet['content_fingerprint'] != BASE_INPUT_FP or result['content_fingerprint'] != BASE_RESULT_FP or v1.fp({k:v for k,v in result.items() if k!='content_fingerprint'}) != BASE_RESULT_FP:
        raise ValueError('V1 fingerprint mismatch')
    if result['input_fingerprint'] != BASE_INPUT_FP or result['version'] != v1.VERSION or result['model'] != v1.MODEL or result['production_effect'] != 'none' or result['status'] != 'evaluated_pending_interpretation_and_Brian_decision':
        raise ValueError('V1 run identity mismatch')
    rows = {r['candidate']['candidate_id']:r for r in result['rows']}
    ids = {u['candidate_id'] for c in packet['cases'] for u in c['candidates']}
    if set(rows) != ids or len(rows) != len(result['rows']): raise ValueError('V1 missing/duplicate candidate rows')
    ledger = result['request_ledger']
    if ledger['input_fingerprint'] != BASE_INPUT_FP or ledger['content_fingerprint'] != v1.fp({k:v for k,v in ledger.items() if k!='content_fingerprint'}) or ledger['attempted_requests'] != len(ledger['attempts']):
        raise ValueError('V1 ledger mismatch')
    attempts = {a['request_key']:a for a in ledger['attempts']}
    for case in packet['cases']:
        original = v1.questions(case['phrase_pools']); revised = questions(case['phrase_pools'])
        if {k for k in original if original[k] != revised[k]} != set(CHANGED): raise ValueError('Revision exceeds four-question scope')
        for unit in case['candidates']:
            row = rows[unit['candidate_id']]
            identity = dict(state=v1.state_for(case,unit),questions=original,model=v1.MODEL,version=v1.VERSION,input_fingerprint=BASE_INPUT_FP)
            if row['candidate'] != unit or row['case_id'] != case['case_id'] or row['cache_key'] != v1.fp(identity) or row['resolved_model'] != v1.MODEL:
                raise ValueError('V1 state/model provenance mismatch')
            v1.validate_answers(row['raw_answers'],original)
            if row['decisions'] != v1.decisions(row['raw_answers']) or row['observation'] != v1.compose(case,unit,row['decisions']): raise ValueError('V1 decision/composition drift')
            attempt = attempts.get(row['cache_key'],{})
            if attempt.get('status') != 'completed' or attempt.get('request_id') != row['request_id'] or attempt.get('usage') != row['usage']: raise ValueError('V1 request provenance mismatch')
    return packet,result,rows


def audit():
    packet,result,rows = load_baseline()
    findings=[]
    for i,check in enumerate(result['diagnostics']['checks']):
        if check['status'] == 'matches_proposal': continue
        field = check['field']
        category = 'focused_semantic_or_question_contract_failure' if field in CHANGED else 'unchanged_conservative_binding_limitation'
        why = {
            'relation': 'Predicate identity is confounded with negation/open issue or embedded requirement content; retain source object and separate polarity.',
            'polarity': 'Voiced predicate negation is confounded with assertion positivity or negative attitude; quote rejection must not flip content.',
            'voice': 'Proposition origin can be confused with missing explicit self-attribution or the reporting wrapper; direct discourse needs a clear but guarded convention.',
            'adoption': 'Assertion adoption is being withheld on direct/negative statements, or explicit rejection is confused with plain reporting/open issue.',
        }.get(field,'This subject/object or other binding judgment is outside V2 question changes. Preserve the V1 answer and disclose any remaining withholding.')
        evidence=[dict(candidate_id=r['candidate']['candidate_id'],claim_span=deepcopy(r['candidate']['claim_span']),raw_answer=deepcopy(r['raw_answers'].get('subject' if field=='subject_id' else field)),decision=r['decisions'].get('subject' if field=='subject_id' else field)) for r in result['rows'] if r['case_id']==check['case_id']]
        findings.append(dict(check_index=i,case_id=check['case_id'],field=field,classification=category,rationale=why,original_check=deepcopy(check),evidence=evidence))
    report=dict(version='g1-v1-interpretation-before-v2',status='feasible_not_accepted_one_refinement_authorized',baseline_result_fingerprint=BASE_RESULT_FP,
                check_count=len(result['diagnostics']['checks']),matches=sum(c['status']=='matches_proposal' for c in result['diagnostics']['checks']),findings=findings,
                field_failure_counts=dict(Counter(c['field'] for c in findings)),
                legitimate_withholding_controls=['P07 unresolved object remains withheld','A09 unanswered question does not assert an answer','A04/P09 explicitly open issues do not assert settled polarity','Reported/rejected claims are never adopted by default'],
                expectation_revisions_proposed=[],expectation_review_note='No expectation revision proposed from source review; original 209 checks remain unchanged. Extra positive/metadiscourse interpretations must still be reviewed after V2.',
                provider_requests=0)
    report['content_fingerprint']=v1.fp(report)
    return report


def prepare():
    base,result,rows = load_baseline()
    sources = {str(p.relative_to(ROOT)):v1.file_fp(p) for p in (v1.PACKET_PATH,v1.RESULT_PATH,ROOT/'src/pastor_transcript_extractor/sermon_g1_feasibility_review.py')}
    changes = {c['case_id']:{k:questions(c['phrase_pools'])[k] for k in CHANGED} for c in base['cases']}
    reused = sum(len(r['raw_answers'])-len(CHANGED) for r in rows.values())
    packet=dict(version=VERSION,status='prepared_not_evaluated',production_effect='none',model=v1.MODEL,threshold=v1.THRESHOLD,
                baseline_input_fingerprint=BASE_INPUT_FP,baseline_result_fingerprint=BASE_RESULT_FP,sources=sources,
                cases=deepcopy(base['cases']),questions=changes,changed_fields=list(CHANGED),unchanged_composition_version=v1.VERSION,
                budget=dict(provider_request_ceiling=len(rows),new_question_count=len(rows)*len(CHANGED),reused_v1_answers=reused,sdk_retries=0,timeout_seconds=45),
                holds=deepcopy(base['holds']),baseline_audit_fingerprint=audit()['content_fingerprint'])
    packet['content_fingerprint']=v1.fp(packet)
    return packet


def validate(packet):
    if packet.get('content_fingerprint') != v1.fp({k:v for k,v in packet.items() if k!='content_fingerprint'}) or packet != prepare():
        raise ValueError('V2 packet/state/question/reuse drift')


def compare(base,result):
    before=base['diagnostics']['checks'];after=result['diagnostics']['checks']
    if len(before)!=len(after):raise ValueError('Expectation inventory changed')
    changes=[]
    for i,(old,new) in enumerate(zip(before,after)):
        if {k:v for k,v in old.items() if k not in {'actual','status'}} != {k:v for k,v in new.items() if k not in {'actual','status'}}: raise ValueError('Expectation semantics changed')
        focused=new['field'] in CHANGED
        if new['status']=='matches_proposal':
            kind='corrected_semantic_check_pending_source_review' if old['status']!='matches_proposal' and focused else 'other_composition_improvement_pending_source_review' if old['status']!='matches_proposal' else 'retained_match'
        elif old['status']=='matches_proposal': kind='regression_requires_review'
        elif new['field']=='subject_id':kind='unchanged_binding_withholding_outside_revision'
        else:kind='remaining_focused_failure' if focused else 'remaining_control_or_binding_failure'
        changes.append(dict(check_index=i,case_id=new['case_id'],field=new['field'],classification=kind,before=deepcopy(old),after=deepcopy(new)))
    rowpairs={r['candidate']['candidate_id']:r for r in base['rows']}
    field_transitions=[]
    for row in result['rows']:
        old=rowpairs[row['candidate']['candidate_id']]
        for field in CHANGED:
            field_transitions.append(dict(candidate_id=row['candidate']['candidate_id'],field=field,v1=old['decisions'][field],v2=row['decisions'][field],v1_raw=old['raw_answers'][field],v2_raw=row['raw_answers'][field]))
    families={}
    for name,spec in FAMILIES.items():
        relevant=[c for c in changes if c['case_id'] in spec['cases'] and c['field'] in spec['fields']]
        families[name]=dict(check_count=len(relevant),remaining_failures=[c for c in relevant if c['after']['status']!='matches_proposal'],systematicity='Source review required; repeated remaining case failures are disclosed, not explained away by average match rate.')
    return dict(check_transitions=changes,field_transitions=field_transitions,classification_counts=dict(Counter(c['classification'] for c in changes)),focused_families=families,
                legitimate_withholding_checks=[c for c in changes if c['after']['status']=='matches_proposal' and c['after'].get('expected') in ('undetermined','unsettled','question','open_issue')],
                source_justified_unresolved_object_controls=[c for c in changes if c['case_id']=='P07'],
                expectations_requiring_revision=[],expectation_review_note='None proposed before V2 execution. Source review may identify a disputed expectation, but must record it separately without rewriting the original checks.',automatic_acceptance=False)



# This override replaces only the response lost by the pre-receipt implementation.
LOST_ATTEMPTS_FP = '1a0c8cee0e3d6fb70e8cff7ea440d51e15a887d511c7d989d240a84559111eca'
LOST_REQUEST_KEY = '3abefcd9336cff66f18e0c936fc878ec60df25cb23f6b499b626fa2247a81cd5'


def validate_answers(raw, inventory):
    """Preserve the existing .01 mass tolerance, including floating point edges.

    Never normalize probabilities, fill omitted options or change the .80 decision
    threshold. Errors name the exact field and contract failure.
    """
    if not isinstance(raw, dict) or set(raw) != set(inventory):
        raise ValueError('Incomplete answer inventory: expected ' + ', '.join(inventory))
    for key, value in raw.items():
        if not isinstance(value, dict) or not isinstance(value.get('probabilities'), dict):
            raise ValueError(f'{key}: missing Choice probability mapping')
        probs = value['probabilities']; options = inventory[key]['criteria']
        if set(probs) != set(options):
            raise ValueError(f'{key}: probability options mismatch; missing={sorted(set(options)-set(probs))}; extra={sorted(set(probs)-set(options))}')
        if value.get('choice') not in options:
            raise ValueError(f'{key}: selected choice is outside criteria')
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 1 for x in probs.values()):
            raise ValueError(f'{key}: probabilities must be finite numbers in [0, 1]')
        mass = math.fsum(probs.values())
        if abs(mass - 1) > .010000001:
            raise ValueError(f'{key}: probability mass {mass!r} outside existing 0.01 tolerance')


def request_specs(packet):
    for case in packet['cases']:
        full = questions(case['phrase_pools']); changed = {k: full[k] for k in CHANGED}
        for unit in case['candidates']:
            state = v1.state_for(case, unit)
            identity = dict(state=state, questions=changed, model=v1.MODEL, version=VERSION, input_fingerprint=packet['content_fingerprint'])
            yield case, unit, full, changed, state, identity, v1.fp(identity)


def saved_response(path, identity, inventory, ledger):
    cache = json.loads(path.read_text())
    if cache.get('identity') != identity or cache.get('fingerprint') != v1.fp({k: v for k, v in cache.items() if k != 'fingerprint'}):
        raise ValueError(f'Corrupt V2 cache/receipt: {path.name}; do not silently rerun')
    response = cache['response']
    validate_answers(response['answers'], inventory)
    if response['resolved_model'] != v1.MODEL:
        raise ValueError('V2 cached/receipt model mismatch')
    attempts = [a for a in ledger['attempts'] if a.get('request_key') == v1.fp(identity)]
    if not attempts or not any(a.get('request_id', response.get('request_id')) == response.get('request_id') for a in attempts):
        raise ValueError('V2 saved response lacks matching charged request provenance')
    return response


def evaluate(packet, *, provider_factory=v1.Provider, cache_dir=CACHE, replace_lost_response=False):
    validate(packet)
    base, baseline, original_rows = load_baseline()
    cache_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = cache_dir / 'request-ledger.json'
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else dict(input_fingerprint=packet['content_fingerprint'], attempted_requests=0, attempts=[])
    if ledger_path.exists() and ledger.get('content_fingerprint') != v1.fp({k:v for k,v in ledger.items() if k!='content_fingerprint'}):
        raise ValueError('Corrupt V2 request ledger')
    if ledger['input_fingerprint'] != packet['content_fingerprint'] or ledger['attempted_requests'] != len(ledger['attempts']):
        raise ValueError('V2 ledger identity/count mismatch')
    ceiling = packet['budget']['provider_request_ceiling']
    if replace_lost_response:
        if v1.fp(ledger['attempts'][:30]) != LOST_ATTEMPTS_FP:
            raise ValueError('Replacement allowance applies only to the recorded 30-attempt interrupted run')
        ceiling += 1
    # Validate every saved response and count all outstanding work before spending.
    specs = list(request_specs(packet)); saved = {}
    for spec in specs:
        identity, key = spec[-2:]; inventory = spec[3]
        path = cache_dir / (key + '.json')
        receipt = cache_dir / 'response-receipts' / (key + '.json')
        if path.exists() or receipt.exists():
            saved[key] = saved_response(path if path.exists() else receipt, identity, inventory, ledger)
    needed = len(specs) - len(saved); remaining = ceiling - ledger['attempted_requests']
    if needed > remaining:
        raise ValueError(f'Cumulative V2 request ceiling exhausted or insufficient: {len(saved)} saved responses, {needed} still needed, {remaining} attempts remaining under ceiling {ceiling}. No provider called; do not reset the ledger. The recorded lost-response run requires explicit --replace-lost-response approval (ceiling 38).')
    new = hits = reused = 0; provider = None; rows = []
    try:
        for case, unit, full, changed, state, identity, key in specs:
            old = original_rows[unit['candidate_id']]; path = cache_dir / (key + '.json')
            was_cached = key in saved
            if was_cached:
                response = saved[key]; hits += 1
                if not path.exists():
                    # A valid receipt can recover locally without repeating inference.
                    attempt = next(a for a in reversed(ledger['attempts']) if a['request_key'] == key)
                    attempt.update(status='completed', request_id=response.get('request_id'), usage=response.get('usage', {}), resolved_model=response['resolved_model'])
                    v1._save_ledger(ledger_path, ledger)
                    cache = dict(identity=identity, response=response); cache['fingerprint'] = v1.fp(cache); v1._write(path, cache)
            else:
                if ledger['attempted_requests'] >= ceiling:
                    raise ValueError('Cumulative V2 request ceiling exhausted')
                if provider is None: provider = provider_factory()
                attempt = dict(request_key=key, case_id=case['case_id'], candidate_id=unit['candidate_id'], status='attempted')
                ledger['attempts'].append(attempt); ledger['attempted_requests'] += 1; new += 1; v1._save_ledger(ledger_path, ledger)
                response = provider.assess(state, changed)
                # Persist the untouched response BEFORE contract/model validation.
                receipt = dict(identity=identity, response=response); receipt['fingerprint'] = v1.fp(receipt)
                v1._write(cache_dir / 'response-receipts' / (key + '.json'), receipt)
                attempt.update(status='response_received', request_id=response.get('request_id'), usage=response.get('usage', {}), resolved_model=response.get('resolved_model')); v1._save_ledger(ledger_path, ledger)
                validate_answers(response['answers'], changed)
                if response['resolved_model'] != v1.MODEL: raise ValueError('V2 resolved model mismatch')
                cache = dict(identity=identity, response=response); cache['fingerprint'] = v1.fp(cache); v1._write(path, cache)
                attempt['status'] = 'completed'; v1._save_ledger(ledger_path, ledger)
            answers = deepcopy(old['raw_answers']); answers.update(deepcopy(response['answers']))
            validate_answers(answers, full)
            origin = {}
            for field, answer in answers.items():
                is_new = field in CHANGED
                if not is_new and full[field] != v1.questions(case['phrase_pools'])[field]: raise ValueError('Cannot reuse changed question')
                origin[field] = dict(source='v2_cache' if is_new and was_cached else 'v2_request' if is_new else 'frozen_v1_result',
                                   question_digest=v1.fp(full[field]), question_version=VERSION if is_new else v1.VERSION,
                                   state_fingerprint=v1.fp(state), resolved_model=response['resolved_model'] if is_new else old['resolved_model'],
                                   cache_key=key if is_new else old['cache_key'], request_id=response.get('request_id') if is_new else old.get('request_id'),
                                   baseline_result_fingerprint=BASE_RESULT_FP if not is_new else None)
                if not is_new: reused += 1
            d = v1.decisions(answers)
            rows.append(dict(case_id=case['case_id'], candidate=deepcopy(unit), raw_answers=answers, decisions=d, observation=v1.compose(case, unit, d), cache_key=key, resolved_model=v1.MODEL, request_id=response.get('request_id'), usage=response.get('usage', {}), answer_provenance=origin, baseline_decisions=deepcopy(old['decisions'])))
    except Exception as error:
        ledger['last_failure'] = dict(error_type=type(error).__name__, detail=str(error), successful_caches_retained=True); v1._save_ledger(ledger_path, ledger); raise
    finally:
        if provider is not None and hasattr(provider, 'close'): provider.close()
    validate(packet)
    result = dict(version=VERSION, status='evaluated_pending_interpretation_and_Brian_decision', input_fingerprint=packet['content_fingerprint'], baseline_input_fingerprint=BASE_INPUT_FP, baseline_result_fingerprint=BASE_RESULT_FP, model=v1.MODEL, production_effect='none',
                  execution=dict(provider_requests=new, v2_cache_hits=hits, reused_v1_answers=reused, new_question_count=packet['budget']['new_question_count'], cumulative_attempted_requests=ledger['attempted_requests'], original_request_ceiling=packet['budget']['provider_request_ceiling'], effective_request_ceiling=ceiling, lost_response_replacement_authorized=replace_lost_response, lost_request_key=LOST_REQUEST_KEY if replace_lost_response else None, sdk_retries=0, known_cumulative_input_tokens=sum(a.get('usage', {}).get('input_tokens') or 0 for a in ledger['attempts']), known_cumulative_output_tokens=sum(a.get('usage', {}).get('output_tokens') or 0 for a in ledger['attempts']), requests_with_unknown_usage=sum(any(a.get('usage', {}).get(k) is None for k in ('input_tokens', 'output_tokens')) for a in ledger['attempts'])),
                  request_ledger=deepcopy(ledger), rows=rows, diagnostics=v1.diagnose(base, rows))
    result['comparison'] = compare(baseline, result)
    result['content_fingerprint'] = v1.fp(result)
    return result


def render_audit(report):
    lines=['# G1 V1 interpretation for one V2 refinement','',f"V1: {report['matches']}/{report['check_count']} prepared checks match; {len(report['findings'])} unmet checks. No acceptance. No provider requests for this audit.", '',
           'Four questions change: relation, polarity, proposition voice and adoption. All other fields, candidates, cases, threshold and composition remain frozen. No expectation revision is proposed.', '']
    for f in report['findings']:
        c=f['original_check']
        lines += [f"- Check {f['check_index']}, {f['case_id']} / {f['field']}: **{f['classification']}**. Expected `{json.dumps(c.get('expected'))}`, got `{json.dumps(c.get('actual'))}`. {f['rationale']}"]
    lines += ['', 'Legitimate source withholding remains distinct from a missed positive. P07 is unresolved; direct preacher assertions and explicitly named subjects in A09/P09 are not relabeled legitimate ambiguities merely because the model withheld.', '',
              'Raw argmax under .80 remains withholding; a selected wrong argmax or a competing relation is separately visible in the frozen result. No raw result or expected label is rewritten.']
    return '\n'.join(lines)+'\n'


def run(mode='evaluate', *, replace_lost_response=False):
    if replace_lost_response and mode != 'evaluate':
        raise ValueError('Lost-response replacement is only available for V2 evaluation')
    if mode=='prepare':
        packet=prepare();v1._write(INPUT,packet)
        v1._write(HERE/'questions-v2.json',packet['questions'])
        review=audit();v1._write(HERE/'audit-v1.json',review);(HERE/'audit-v1.md').write_text(render_audit(review))
        (HERE/'input-v2.md').write_text('# G1 V2 fixed input reuse\n\nAll cases, candidates, source text, contexts, phrase pools and expectations are copied unchanged from [V1](../g1-feasibility-v1/input-v1.md).\n\n'+f"28 cases; 37 candidates; {packet['budget']['new_question_count']} new judgments; {packet['budget']['reused_v1_answers']} V1 answers reused; at most 37 cumulative V2 requests; zero SDK retries.\n\nOnly relation, polarity, voice and adoption change. No provider validation has run.\n")
        print('Prepared one G1 V2 refinement: 28 unchanged cases; 148 new judgments; 338 reused V1 answers; 37-request ceiling; provider_requests=0')
    elif mode=='check':
        packet=json.loads(INPUT.read_text());validate(packet)
        if json.loads((HERE/'questions-v2.json').read_text())!=packet['questions'] or json.loads((HERE/'audit-v1.json').read_text())!=audit():raise ValueError('Published V2 questions/audit drift')
        print('PASS: V2 source/state/expectation identity and unchanged-answer reuse integrity; provider_requests=0; semantic refinement untested')
    elif mode=='evaluate':
        packet=json.loads(INPUT.read_text());validate(packet)
        try:result=evaluate(packet, replace_lost_response=replace_lost_response)
        except Exception as error:
            failure=dict(status='execution_failed_not_semantic_verdict',input_fingerprint=packet['content_fingerprint'],error_type=type(error).__name__,detail=str(error),successful_caches_retained=True,production_effect='none')
            v1._write(RESULT.with_name('feasibility-v2.execution-failure.json'),failure)
            RESULT.with_name('feasibility-v2.execution-failure.md').write_text('# G1 V2 incomplete execution\n\nNo semantic verdict; successful caches and cumulative request ledger retained. Do not bypass the budget.\n\n'+str(error)+'\n')
            raise
        v1._write(RESULT,result)
        lines=[v1.render(packet,result).replace('# G1 bounded feasibility results V1','# G1 bounded feasibility results V2'), '\n## V1 versus V2\n',json.dumps(result['comparison']['classification_counts'],indent=2), '\nNo automatic acceptance: corrected checks need source review; legitimate withholdings, remaining repeated failures and disputed expectations must be interpreted before closing feasibility.\n']
        lines += ['\n## Corrected semantic checks — pending source review\n']
        for c in result['comparison']['check_transitions']:
            if c['classification']=='corrected_semantic_check_pending_source_review':lines.append('- '+json.dumps(c,ensure_ascii=False))
        lines += ['\n## Legitimate source withholding and unchanged binding limits\n',
                  'Only source-justified open issues/questions and unresolved antecedents count as legitimate withholding. A missed positive is not relabeled legitimate.\n']
        for c in result['comparison']['legitimate_withholding_checks']+result['comparison']['source_justified_unresolved_object_controls']:
            lines.append('- '+json.dumps(c,ensure_ascii=False))
        for c in result['comparison']['check_transitions']:
            if c['classification']=='unchanged_binding_withholding_outside_revision':lines.append('- Unchanged limitation: '+json.dumps(c,ensure_ascii=False))
        lines += ['\n## Remaining failures and regressions\n']
        for c in result['comparison']['check_transitions']:
            if c['after']['status']!='matches_proposal':lines.append('- '+json.dumps(c,ensure_ascii=False))
        for name,family in result['comparison']['focused_families'].items():lines += ['\n### '+name+'\n',json.dumps(family,indent=2,ensure_ascii=False)]
        lines += ['\n## Expectations requiring review\n', result['comparison']['expectation_review_note'],
                  '\nOriginal expectations are frozen. No revision has been applied; any source-supported proposed change belongs in a separate interpretation record.\n',
                  '\n## Complete unchanged expectation comparison\n']
        lines += ['- '+json.dumps(c,ensure_ascii=False) for c in result['comparison']['check_transitions']]
        RESULT.with_suffix('.md').write_text('\n'.join(lines))
        print(f"Wrote {RESULT} and {RESULT.with_suffix('.md')}; {json.dumps(result['execution'])}; source interpretation and bounded close decision required")
    else:raise ValueError('Unsupported G1 V2 mode')
