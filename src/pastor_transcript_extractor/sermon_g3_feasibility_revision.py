"""One bounded G3 revision: relevance differs from recipient-circumstance binding."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path

from pastor_transcript_extractor import sermon_g3_feasibility_review as v1
from pastor_transcript_extractor.analysis_artifact_cache import write_json_markdown
from pastor_transcript_extractor.sermon_g2_feasibility_revision import validate_answers

ROOT = v1.ROOT
HERE = ROOT / 'docs/review-proposals/g3-feasibility-v2'
INPUT = HERE / 'input-v2.json'
RESULT = ROOT / 'evaluation/g3-address/feasibility-v2.results.json'
CACHE = ROOT / 'evaluation/g3-address/cache-v2'
VERSION = 'g3-relevance-recipient-binding-choice-v2'
REUSED_FIELDS = tuple(k for k in v1.questions() if k != 'binding')
# Exact original spans/context: no new cases, boundaries, acts or stance tuning.
SELECTED = [('G3-01', 0), ('G3-06', 1), ('G3-08', 0), ('G3-09', 0),
            ('G3-11', 0), ('G3-12', 0), ('G3-14', 1),
            ('G3-proximity', 0), ('G3-wrong-object', 0),
            ('natural-1200-32', 0), ('natural-4430-57', 0), ('natural-590-64', 1)]


def questions():
    boundary = (
        'Judge the exact candidate.utterance and candidate.circumstance. The utterance must be in '
        'target_text. Context can resolve who you/them is or what this loss refers to only when target '
        'evidence itself connects the utterance to that referent; it cannot supply absent address or '
        'connection. A circumstance can concern a person who is not the addressee. Judge relation '
        'existence independently of act type, source voice, preacher adoption and whether the person '
        'is a current listener. Rejected/reported address can still address its reported recipient. '
        'No inner empathy, listener effect or pastor quality is inferred.'
    )
    return {
        'circumstance_relevance': {
            'instructions': {'task': 'Does candidate.utterance itself semantically concern the specific candidate.circumstance, regardless of whom it addresses? Explicit topic discussion, prayer about people, or speech to a reported person can be relevant. Mere presence elsewhere in the target, proximity, or a different object does not establish relevance. A null circumstance has no demonstrated relevance.', 'boundary': boundary},
            'criteria': {
                'relevant_in_target': 'The utterance demonstrably concerns this circumstance; its identity is in target evidence. It need not address the person experiencing it.',
                'relevant_context_resolved': 'Target demonstrates the semantic connection; context only resolves the identity of the circumstance/reference.',
                'not_relevant': 'Utterance does not demonstrably concern this specified circumstance, including missing candidate or unrelated nearby subject.',
                'incomplete': 'Required semantic connection is outside the target.',
                'unclear': 'Relevance to this specific circumstance is unresolved.'}},
        'recipient_circumstance_binding': {
            'instructions': {'task': 'Does candidate.utterance address a HUMAN RECIPIENT as someone experiencing candidate.circumstance? The target must connect the addressed person to that circumstance, not merely discuss or request something about a third party. God, comfort those grieving concerns mourners but addresses God, so is not_bound. A counselor told the mourner, You need not face this alone binds the reported mourner, irrespective of preacher adoption. If you need company through this loss, invite a friend binds you to the loss; context may identify which loss. Topic description, wrong recipient and generic continuation do not bind. Do not require a particular act type or current-listener status: those are separate observations.', 'boundary': boundary},
            'criteria': {
                'bound_in_target': 'Target demonstrates that the human recipient is addressed in their identified circumstance, including reported/historical recipients.',
                'bound_context_resolved': 'Target establishes recipient-to-circumstance address; context resolves only person/circumstance identity.',
                'not_bound': 'No such human-recipient circumstance address; includes address to God, topic-only discussion, wrong person/object, context-only treatment or no circumstance.',
                'incomplete': 'Establishing recipient-to-circumstance address would require omitted target treatment.',
                'unclear': 'Recipient-to-circumstance connection unresolved.'}},
    }


def load_baseline():
    packet = json.loads(v1.INPUT.read_text()); v1.validate_packet(packet)
    result = json.loads(v1.RESULT.read_text())
    if result['content_fingerprint'] != v1.fp({k: v for k, v in result.items() if k != 'content_fingerprint'}):
        raise ValueError('V1 result fingerprint mismatch')
    if result['input_fingerprint'] != packet['content_fingerprint'] or result['question_digest'] != packet['question_digest'] or result['status'] != 'evaluated_pending_PTE_interpretation_and_Brian_decision':
        raise ValueError('V1 results do not match frozen input/questions or completed execution')
    expected_ids = {p['candidate_id'] for c in packet['cases'] for p in c['candidates']}
    rows = {r['candidate_id']: r for r in result['rows']}
    if set(rows) != expected_ids or len(result['rows']) != len(expected_ids):
        raise ValueError('V1 candidate omissions/duplicates')
    for c in packet['cases']:
        for p in c['candidates']:
            row = rows[p['candidate_id']]
            if row['case_id'] != c['case_id'] or row['candidate'] != {k: p[k] for k in ('circumstance', 'utterance')}:
                raise ValueError('V1 candidate mismatch')
            validate_answers(row['raw_answers'], v1.questions())
            if row['decisions'] != {k: v1.decision(a) for k, a in row['raw_answers'].items()}:
                raise ValueError('V1 decision mismatch')
            cache = json.loads((v1.CACHE / f"{row['cache_key']}.json").read_text())
            identity = {'state': v1.state_for(c, p), 'questions': v1.questions(), 'model': packet['model'], 'version': v1.VERSION, 'source_fingerprints': packet['sources']}
            if row['cache_key'] != v1.fp(identity) or cache['identity'] != identity or cache['content_fingerprint'] != v1.fp({k: value for k, value in cache.items() if k != 'content_fingerprint'}) or cache['response']['resolved_model'] != packet['model'] or cache['response']['answers'] != row['raw_answers']:
                raise ValueError('V1 state/model/raw answer provenance mismatch')
    return packet, result, rows


def expected_relations(cid):
    if cid == 'G3-11':
        return {'circumstance_relevance': 'relevant_context_resolved', 'recipient_circumstance_binding': 'bound_context_resolved'}
    if cid == 'G3-09':
        return {'circumstance_relevance': 'relevant_in_target', 'recipient_circumstance_binding': 'not_bound'}
    if cid in {'G3-12', 'G3-proximity', 'G3-wrong-object', 'natural-590-64'}:
        return {'circumstance_relevance': 'not_relevant', 'recipient_circumstance_binding': 'not_bound'}
    return {'circumstance_relevance': 'relevant_in_target', 'recipient_circumstance_binding': 'bound_in_target'}


def prepare():
    baseline, result, rows = load_baseline()
    cases = []
    for cid, index in SELECTED:
        c = deepcopy(next(c for c in baseline['cases'] if c['case_id'] == cid))
        p = c['candidates'][index]; c['candidates'] = [p]
        p['expected'].pop('binding', None); p['expected'].update(expected_relations(cid))
        p['baseline_binding'] = rows[p['candidate_id']]['decisions']['binding']
        p['reused_answers'] = {field: deepcopy(rows[p['candidate_id']]['raw_answers'][field]) for field in REUSED_FIELDS}
        p['reuse_provenance'] = {'baseline_result_fingerprint': result['content_fingerprint'], 'baseline_cache_key': rows[p['candidate_id']]['cache_key'], 'state_fingerprint': v1.fp(v1.state_for(c, p)), 'questions': {field: v1.fp(v1.questions()[field]) for field in REUSED_FIELDS}, 'question_version': v1.VERSION, 'model': baseline['model']}
        cases.append(c)
    packet = {'version': VERSION, 'status': 'prepared_not_evaluated', 'production_effect': 'none', 'model': baseline['model'], 'threshold': baseline['threshold'], 'baseline_input_fingerprint': baseline['content_fingerprint'], 'baseline_result_fingerprint': result['content_fingerprint'], 'sources': {**baseline['sources'], str(v1.INPUT.relative_to(ROOT)): v1.file_fp(v1.INPUT), str(v1.RESULT.relative_to(ROOT)): v1.file_fp(v1.RESULT), str(__file__).replace(str(ROOT) + '/', ''): v1.file_fp(Path(__file__))}, 'questions': questions(), 'question_digest': v1.fp(questions()), 'reused_question_inventory': {k: v1.questions()[k] for k in REUSED_FIELDS}, 'cases': cases, 'candidate_scope': baseline['candidate_scope'], 'holds': baseline['holds'], 'budget': {'provider_request_ceiling': 12, 'new_question_count': 24, 'question_count': 24, 'v1_answers_reused': 132, 'sdk_retries': 0, 'candidates_per_request': 1}}
    packet['content_fingerprint'] = v1.fp(packet)
    return packet


def validate_packet(packet):
    if packet != prepare():
        raise ValueError('Frozen G3 V2 input, baseline provenance or questions changed')


def provisional(decisions):
    eligible = decisions['circumstance_relevance'] in {'relevant_in_target', 'relevant_context_resolved'} and decisions['recipient_circumstance_binding'] in {'bound_in_target', 'bound_context_resolved'} and decisions['addressee'] == 'direct_current_listener' and decisions['adoption'] == 'own_or_adopted' and decisions['boundary'] == 'local_sufficient'
    return [act for act in v1.ACTS if eligible and decisions[act] == 'observed']


def evaluate(packet, *, provider_factory=v1.Provider, cache_dir=CACHE):
    validate_packet(packet)
    rows = []; requests = hits = 0; provider = None
    for c in packet['cases']:
        p = c['candidates'][0]
        identity = {'state': v1.state_for(c, p), 'questions': questions(), 'model': packet['model'], 'version': VERSION, 'source_fingerprints': packet['sources']}
        key = v1.fp(identity); path = cache_dir / f'{key}.json'; response = None
        if path.exists():
            try:
                cached = json.loads(path.read_text())
                if cached['identity'] != identity or cached['content_fingerprint'] != v1.fp({k: v for k, v in cached.items() if k != 'content_fingerprint'}):
                    raise ValueError('V2 cache mismatch')
                validate_answers(cached['response']['answers'], questions())
                if cached['response']['resolved_model'] != packet['model']:
                    raise ValueError('V2 cached model mismatch')
                response = cached['response']; hits += 1
            except (ValueError, KeyError, TypeError):
                response = None
        if response is None:
            if requests >= packet['budget']['provider_request_ceiling']:
                raise ValueError('Request ceiling exceeded')
            if provider is None:
                provider = provider_factory()
            requests += 1; response = provider.assess(identity['state'], questions())
            validate_answers(response['answers'], questions())
            if response['resolved_model'] != packet['model']:
                raise ValueError('Resolved model mismatch')
            cached = {'identity': identity, 'response': response}; cached['content_fingerprint'] = v1.fp(cached)
            cache_dir.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(cached, indent=2) + '\n')
        raw = {**p['reused_answers'], **response['answers']}
        decisions = {k: v1.decision(a) for k, a in raw.items()}
        checks = []
        for field, expected in p['expected'].items():
            allowed = expected if isinstance(expected, list) else [expected]
            observed = decisions[field]
            status = 'direct_match' if observed in allowed else 'withheld_or_missed' if observed in {'unclear', 'unresolved', 'incomplete', 'continuation_required'} or (field in v1.ACTS and observed == 'not_observed' and 'observed' in allowed) else 'conflicting_judgment_requires_A_B_C_review'
            checks.append({'field': field, 'expected': allowed, 'observed': observed, 'status': status, 'answer_origin': 'new_v2' if field in questions() else 'reused_v1'})
        rows.append({'case_id': c['case_id'], 'candidate_id': p['candidate_id'], 'candidate': {k: p[k] for k in ('circumstance', 'utterance')}, 'raw_answers': raw, 'decisions': decisions, 'provisional_current_listener_acts': provisional(decisions), 'checks': checks, 'review_reason': p['review_reason'], 'baseline_binding': p['baseline_binding'], 'reuse_provenance': p['reuse_provenance'], 'new_answer_cache_key': key, 'usage': response.get('usage', {})})
    validate_packet(packet)
    report = {'version': VERSION, 'status': 'evaluated_pending_PTE_interpretation_and_Brian_decision', 'production_effect': 'none', 'input_fingerprint': packet['content_fingerprint'], 'question_digest': packet['question_digest'], 'baseline_result_fingerprint': packet['baseline_result_fingerprint'], 'execution': {'provider_requests': requests, 'cache_hits': hits, 'v1_answers_reused': 132}, 'candidate_omissions_against_frozen_catalog': [], 'automatic_sermon_candidate_recall': 'not_tested', 'rows': rows}
    report['content_fingerprint'] = v1.fp(report)
    return report


def render_results(report, packet):
    text = v1.render_results(report, packet).replace('results V1', 'results V2')
    text += '\n## Revision provenance\n\nOnly two relationship questions are new. All acts and framing below are frozen V1 answers, not fresh confirmations.\n'
    for row in report['rows']:
        text += f"\n- {row['candidate_id']}: old binding `{row['baseline_binding']}`; reused `{row['reuse_provenance']['baseline_cache_key']}`; new `{row['new_answer_cache_key']}`.\n"
    return text


def run(mode='evaluate'):
    if mode not in {'prepare', 'check', 'evaluate'}:
        raise ValueError('Unsupported G3 revision mode')
    if mode == 'prepare':
        packet = prepare()
        write_json_markdown(INPUT, packet, v1.render_input(packet).replace('inputs V1', 'inputs V2'))
        (HERE / 'questions-v2.json').write_text(json.dumps({'version': VERSION, 'digest': v1.fp(questions()), 'questions': questions()}, indent=2) + '\n')
        print('Prepared G3 V2: 12 candidates, 24 new questions, 132 V1 answers reused; provider_requests=0')
        return
    packet = json.loads(INPUT.read_text()); validate_packet(packet)
    if json.loads((HERE / 'questions-v2.json').read_text()) != {'version': VERSION, 'digest': v1.fp(questions()), 'questions': questions()}:
        raise ValueError('V2 question artifact changed')
    if mode == 'check':
        print('G3 V2 integrity/provenance checked; provider_requests=0'); return
    try:
        report = evaluate(packet)
    except Exception as error:
        failure = {'status': 'execution_failed_no_semantic_decision', 'input_fingerprint': packet['content_fingerprint'], 'error_type': type(error).__name__, 'successful_caches_retained': True}
        write_json_markdown(RESULT.with_name('feasibility-v2.execution-failure.json'), failure, '# G3 V2 execution failure\n\nNo semantic verdict; successful caches retained.\n')
        raise
    write_json_markdown(RESULT, report, render_results(report, packet))
    print(f'G3 V2 results: {RESULT}; {report["execution"]}; pending interpretation')
