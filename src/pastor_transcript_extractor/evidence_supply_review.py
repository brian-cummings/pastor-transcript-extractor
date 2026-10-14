"""Provider-free evidence-supply preparation. Never constructs a provider.

References are independently authored inputs, never inputs to candidate discovery.
Spatial hits are diagnostics, not semantic matches or population recall.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PACKET_DIR = ROOT / 'docs/review-proposals/evidence-supply-readiness-v1'
VERSION = 'evidence-supply-readiness-v1'
BUILDER = 'lexical-source-supply-v1'
SOURCE_IDS = (1200, 421, 4050, 4430, 350, 1046)
MAX_CANDIDATES_PER_ROUTE_SERMON = 8
MODEL = 'jev-1.13.0'
PRICE = {'source': 'https://docs.typesafe.ai/models', 'checked_on': '2026-10-14',
         'input_usd_per_million_tokens': 0.042, 'output_usd_per_million_tokens': 0,
         'per_request_context_tokens': 64000, 'status': 'public_list_price_not_account_invoice'}
INTEGRITY = ('wrong_source_or_speaker', 'fabricated_proposition_relation_or_opposite',
             'context_promoted_to_target', 'incompatible_measurement_credited', 'provenance_loss')
AUTHORITY_PATHS = (
    'evaluation/g1-binding/feasibility-v2.results.json',
    'evaluation/g2-binding/feasibility-v2.results.json',
    'evaluation/g3-address/feasibility-v2.results.json',
    'docs/review-proposals/g1-feasibility-v2/input-v2.json',
    'docs/review-proposals/g2-feasibility-v2/input-v2.json',
    'docs/review-proposals/g3-feasibility-v2/input-v2.json',
    'evaluation/g1-binding/feasibility-stage-gate-v2.json',
    'evaluation/g2-binding/feasibility-stage-gate-v2.json',
    'evaluation/g3-address/feasibility-stage-gate-v2.json',
    'evaluation/observed-profile-consumer-v1/acceptance-decision-v1.json',
    'docs/review-proposals/profile-evidence-v1/packet-v1.json',
    'docs/review-proposals/pastor-contracts-v1/registry-v1.json',
    'src/pastor_transcript_extractor/sermon_g1_feasibility_review.py',
    'src/pastor_transcript_extractor/sermon_g1_feasibility_revision.py',
    'src/pastor_transcript_extractor/sermon_g2_feasibility_review.py',
    'src/pastor_transcript_extractor/sermon_g2_feasibility_revision.py',
    'src/pastor_transcript_extractor/sermon_g3_feasibility_review.py',
    'src/pastor_transcript_extractor/sermon_g3_feasibility_revision.py',
    'src/pastor_transcript_extractor/caption_normalization.py',
)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _span(text: str, start: int, end: int) -> dict[str, Any]:
    if not 0 <= start < end <= len(text):
        raise ValueError('Invalid source span')
    return {'start': start, 'end': end, 'text': text[start:end], 'role': 'target'}


def discover(source: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Lexical retrieval only. Never receives references or assigns semantic labels."""
    # Reuse the closed G2 coordinate slicer without calling its pilot runner.
    from pastor_transcript_extractor.sermon_g2_feasibility_review import candidates as g2_pairs

    pools: dict[str, list[dict[str, Any]]] = {'G1': [], 'G2': [], 'G3': []}
    scripture = re.compile(r'\b(?:Matthew|Mark|Luke|John|Romans|Corinthians|Genesis|Psalms?|Isaiah|Jeremiah|Ephesians|Philippians|Galatians|Titus|Zephaniah|Leviticus|Deuteronomy|Exodus|Jude|Revelation)\b', re.I)
    circumstance = re.compile(r'\b(?:griev\w*|guilt\w*|forgiv\w*|sinful|sorrow\w*|afraid|troubl\w*|doubt\w*|depress\w*|busy|children|parents|father|difficulty|difficult|temptation|backslid\w*|distract\w*|not ready|trembling)\b', re.I)
    claim = re.compile(r'\b(?:saved|salvation|pardoned|accepted by God|ramps?|retention)\b', re.I)
    vid, text, units = source['video_id'], source['text'], source['units']
    for index, unit in enumerate(units):
        # Each candidate uses exactly one normalized target unit, with one unit
        # of context each side. Long targets are withheld, never silently cut.
        if len(unit['text']) > 6000:
            continue
        context = {'leading_context': units[index-1]['text'] if index else '',
                   'trailing_context': units[index+1]['text'] if index+1 < len(units) else ''}
        common = dict(video_id=vid, unit_id=unit['unit_id'], target=_span(text, unit['start'], unit['end']),
                      source_segment_indexes=unit['source_segment_indexes'],
                      start_seconds=unit['start_seconds'], end_seconds=unit['end_seconds'], **context)
        if claim.search(unit['text']):
            pools['G1'].append(common | {'capability': 'G1'})
        if scripture.search(unit['text']):
            pairs, diagnostics = g2_pairs(unit['text'])
            for pair in pairs:
                pools['G2'].append(common | {'capability': 'G2', 'pair': pair,
                                             'local_builder_diagnostics': diagnostics})
        matches = list(circumstance.finditer(unit['text']))
        if matches:
            # At most one lexical circumstance per unit in V1. This explicit
            # recall limitation is audited, not corrected with reference hints.
            m = matches[0]
            pools['G3'].append(common | {'capability': 'G3',
                                         'circumstance': _span(unit['text'], m.start(), m.end())})
    selected = []
    for cap, values in pools.items():
        for i, value in enumerate(values[:MAX_CANDIDATES_PER_ROUTE_SERMON]):
            selected.append(value | {'candidate_id': f'{vid}:{cap}:{i:03}', 'builder_version': BUILDER,
                                      'semantic_decision': None})
    diagnostics = {cap: {'lexical_candidates': len(values),
                         'retained_candidates': min(len(values), MAX_CANDIDATES_PER_ROUTE_SERMON),
                         'truncated_candidates': max(0, len(values)-MAX_CANDIDATES_PER_ROUTE_SERMON)}
                   for cap, values in pools.items()}
    diagnostics['oversize_target_units'] = [u['unit_id'] for u in units if len(u['text']) > 6000]
    return selected, diagnostics


def request_for(candidate: dict[str, Any]) -> dict[str, Any]:
    """Materialize unchanged accepted question contracts; no expected labels sent."""
    from pastor_transcript_extractor import sermon_g1_feasibility_review as g1
    from pastor_transcript_extractor import sermon_g1_feasibility_revision as g1v2
    from pastor_transcript_extractor import sermon_g2_feasibility_revision as g2v2
    from pastor_transcript_extractor import sermon_g3_feasibility_review as g3
    from pastor_transcript_extractor import sermon_g3_feasibility_revision as g3v2

    text = candidate['target']['text']
    case = {'case_id': candidate['candidate_id'], 'target_text': text,
            'leading_context': candidate['leading_context'], 'trailing_context': candidate['trailing_context']}
    cap = candidate['capability']
    if cap == 'G1':
        try:
            units, phrases = g1.candidates(case)
        except ValueError as error:
            return {'candidate_id': candidate['candidate_id'], 'status': 'blocked', 'reason': str(error)}
        # One unit is one request; discovery retains all accepted G1 units here.
        return {'candidate_id': candidate['candidate_id'], 'status': 'prepared', 'capability': cap,
                'requests': [{'state': g1.state_for(case | {'phrase_pools': phrases}, unit),
                              'questions': g1v2.questions(phrases), 'question_version': g1v2.VERSION}
                             for unit in units]}
    if cap == 'G2':
        state = {k: case[k] for k in ('target_text', 'leading_context', 'trailing_context')}
        state['pairs'] = [deepcopy(candidate['pair'])]
        # Retain all independent accepted G2 questions, while reference coverage
        # tests only explains_text. Other facet outputs get no readiness credit.
        questions = g2v2.questions()
        version = g2v2.VERSION
    else:
        state = {k: case[k] for k in ('target_text', 'leading_context', 'trailing_context')}
        circ = {k: candidate['circumstance'][k] for k in ('start', 'end', 'text')}
        circ['source_field'] = 'target_text'
        state['candidate'] = {'circumstance': circ,
                              'utterance': {'source_field': 'target_text', 'start': 0, 'end': len(text), 'text': text}}
        questions = {k: v for k, v in g3.questions().items() if k != 'binding'} | g3v2.questions()
        version = g3v2.VERSION
    return {'candidate_id': candidate['candidate_id'], 'status': 'prepared', 'capability': cap,
            'requests': [{'state': state, 'questions': questions, 'question_version': version}]}


def validate_transport(observation: dict[str, Any], original: dict[str, Any]) -> dict[str, Any]:
    """A lossless archive envelope is separate from eligibility for field credit."""
    if observation['original_record'] != original:
        raise ValueError('Critical integrity failure: provenance_loss or record mutation')
    if observation['original_record_sha256'] != fingerprint(original):
        raise ValueError('Critical integrity failure: original record digest changed')
    if observation['subject_scope'] != 'supplied_passage' or observation['pastor_credit'] is not False:
        raise ValueError('Critical integrity failure: wrong_source_or_speaker')
    if observation['compatibility'] != 'archive_only_not_natural_reuse':
        raise ValueError('Critical integrity failure: incompatible_measurement_credited')
    for name in ('population_rate', 'recurrence', 'comparison', 'quality'):
        if observation[name] is not None:
            raise ValueError('Held output activated')
    return observation


def adapt_frozen(capability: str, row: dict[str, Any], path: str, pointer: str) -> dict[str, Any]:
    provenance = 'reuse_provenance' if capability == 'G3' else 'answer_provenance'
    if not row.get(provenance):
        raise ValueError('Critical integrity failure: provenance_loss')
    record = dict(capability=capability, original_record=deepcopy(row),
                  original_record_sha256=fingerprint(row), result_path=path, result_pointer=pointer,
                  subject_scope='supplied_passage', pastor_credit=False, compatibility='archive_only_not_natural_reuse',
                  population_rate=None, recurrence=None, comparison=None, quality=None)
    return validate_transport(record, row)


def supply_funnel(references: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for ref in references:
        matches = [c['candidate_id'] for c in candidates
                   if c['video_id'] == ref['video_id'] and c['capability'] == ref['capability']
                   and c['target']['start'] < ref['end'] and c['target']['end'] > ref['start']]
        rows.append({'reference_id': ref['reference_id'], 'video_id': ref['video_id'],
                     'capability': ref['capability'], 'reference_state': ref['reference_state'],
                     'spatial_candidate_ids': matches,
                     'supply_state': 'spatial_hit_semantic_match_unestablished' if matches else 'not_supplied',
                     'discovered_semantic_match': None, 'measured_observation': None,
                     'usable_evidence': None, 'withholding': None, 'measurement_error': None})
    return rows


def classify_failure(*, integrity: str | None = None, supplied: bool,
                     reference_state: str, observation: str | None = None,
                     expected: list[str] | None = None) -> str:
    """Predeclared categories; conservative withholding never erases a miss."""
    if integrity:
        if integrity not in INTEGRITY:
            raise ValueError('Unknown integrity failure')
        return 'critical_integrity_failure'
    if not supplied:
        return 'supply_discovery_miss' if reference_state == 'positive' else 'unsupplied_control_or_ambiguous'
    if observation is None:
        return 'not_measured'
    if observation in {'unclear', 'incomplete', 'withheld'}:
        return 'correctly_withheld' if reference_state == 'ambiguous' else 'conservative_measurement_omission'
    if expected is None:
        return 'reference_decision_unestablished'
    return 'correct_measurement' if observation in expected else 'measurement_error'


def sample_cost(usage: dict[str, Any], usable_items: int | None) -> dict[str, Any]:
    requests, input_tokens, output_tokens = (usage.get(k) for k in ('attempts', 'input_tokens', 'output_tokens'))
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in (requests, input_tokens, output_tokens)):
        raise ValueError('Missing or invalid actual usage; no zero-cost inference')
    if usable_items is not None and (not isinstance(usable_items, int) or isinstance(usable_items, bool) or usable_items < 0):
        raise ValueError('Invalid usable evidence count')
    dollars = input_tokens * PRICE['input_usd_per_million_tokens'] / 1_000_000
    return dict(attempts=requests, input_tokens=input_tokens, output_tokens=output_tokens,
                list_price_usd=dollars, usable_evidence_items=usable_items,
                usd_per_usable_item=dollars/usable_items if usable_items is not None and usable_items > 0 else None,
                unit_cost_state='defined' if usable_items is not None and usable_items > 0 else 'unmeasured_or_zero_usable_items',
                corpus_extrapolation=None)


def build_packet(packet_dir: Path = PACKET_DIR) -> dict[str, Any]:
    references = json.loads((packet_dir / 'references-v1.json').read_text())
    sources = [json.loads((packet_dir / 'sources' / f'{vid}.json').read_text()) for vid in SOURCE_IDS]
    candidates, diagnostics = [], {}
    for source in sources:
        found, diag = discover(source)
        candidates.extend(found); diagnostics[str(source['video_id'])] = diag
    requests = [request_for(c) for c in candidates]
    originals = [adapt_frozen(cap, row, path, pointer) for cap, path, pointer, row in _frozen_examples()]
    field_contracts = json.loads((ROOT / 'docs/review-proposals/profile-evidence-v1/packet-v1.json').read_text())['field_contracts']
    fields = []
    for field in field_contracts:
        cid = field['characteristic_id']
        route = 'G1' if cid in {'C03', 'C08', 'C18', 'C20'} else 'G2:explains_text' if cid in {'C10', 'C11'} else 'G3' if cid == 'C12' else None
        fields.append({'characteristic_id': cid, 'question': field['question'], 'required_inputs': field['compatible_inputs'],
                       'candidate_route': route, 'readiness': 'blocked_unestablished',
                       'claim_ceiling': 'E0_local_example_only', 'missing_information': field['missing_information'],
                       'reason': 'No activated projection or new semantic evidence; references and adapter inventory only.'})
    count = sum(len(r.get('requests', [])) for r in requests)
    question_count = sum(len(q['questions']) for r in requests for q in r.get('requests', []))
    # A conservative planning reservation, not a provider tokenizer or token guarantee.
    token_reservation = question_count * PRICE['per_request_context_tokens']
    blockers = ['complete_sermon_reference_not_certified', 'exact_endpoint_and_circumstance_reference_decisions_not_frozen',
                'natural_g1_city_ramp_positive_absent', 'human_packet_acceptance_pending',
                'paid_execution_not_authorized', 'paid_runtime_not_implemented',
                'token_reservation_not_verified_as_hard_billing_bound']
    blocked_targets = [r['candidate_id'] for r in requests if r['status'] == 'blocked']
    if blocked_targets:
        blockers.append('g1_target_windows_exceed_frozen_candidate_or_phrase_pool_limits')
    funnel = supply_funnel(references['rows'], candidates)
    if any(r['reference_state'] == 'positive' and r['supply_state'] == 'not_supplied' for r in funnel):
        blockers.append('bounded_candidate_prototype_omits_positive_reference_episodes')
    files = {str(p.relative_to(ROOT)): file_hash(p) for p in [*(ROOT / p for p in AUTHORITY_PATHS),
             packet_dir / 'references-v1.json', *(packet_dir / 'sources' / f'{vid}.json' for vid in SOURCE_IDS)]}
    files[str(Path(__file__).relative_to(ROOT))] = file_hash(Path(__file__))
    packet = dict(version=VERSION, status='prepared_provider_free_paid_proposal_blocked', provider_requests=0,
                  production_effect='none', model=MODEL, source_files=files, sources=sources,
                  references=references, candidates=candidates, discovery_diagnostics=diagnostics,
                  request_manifest=requests, source_adapters=originals, field_readiness=fields,
                  funnel=funnel, price_basis=PRICE,
                  budget={'maximum_attempts_proposed': count, 'question_count': question_count, 'automatic_retries': 0,
                          'token_reservation_proposed': token_reservation,
                          'list_price_reservation_usd': token_reservation * PRICE['input_usd_per_million_tokens'] / 1_000_000,
                          'blocked_target_ids': blocked_targets,
                          'authorized_attempts': 0, 'authorized_usd': 0,
                          'actual_usage': None, 'cost_per_usable_item': None, 'corpus_extrapolation': None},
                  criteria={'critical_integrity': {'maximum_failures': 0, 'types': list(INTEGRITY)},
                            'measurement': 'Unchanged accepted contracts; exact expected labels must be frozen before execution. No tuned production thresholds.',
                            'discovery': 'Exact opportunity-to-candidate matching must be frozen; spatial overlap alone cannot pass. A clear positive reference unsupplied is a miss.',
                            'pass': 'Per route: zero integrity failures, no definite measurement errors, all frozen mandatory positive/control opportunities supplied with semantically valid candidates, at least one usable positive per tested source containing an eligible positive; ambiguous correct withholding allowed. Clear-positive withholding makes route PARTIAL, never exact-match PASS.',
                            'partial': 'At least one supported local item with intact provenance, but supply misses or conservative positive omissions prevent PASS; preserve blocked routes.',
                            'blocked': 'Any preflight blocker prevents paid run; never certify readiness from packet integrity alone.'},
                  execution_preflight={'ready': False, 'blockers': blockers,
                                       'command': 'pte analysis evidence-supply-review --paid-run-preflight',
                                       'paid_command': None},
                  holds=['G1/G2/G3 tuning', 'broader collection', 'production calibration', 'population recall',
                         'operational opportunity denominators', 'production economics', 'projection/comparison',
                         'G4/coherence', 'clustering', 'recurrence/rates', 'quality/scoring'])
    packet['content_fingerprint'] = fingerprint(packet)
    validate_packet(packet)
    return packet


def _frozen_examples():
    for cap, path in [('G1', 'evaluation/g1-binding/feasibility-v2.results.json'),
                      ('G2', 'evaluation/g2-binding/feasibility-v2.results.json'),
                      ('G3', 'evaluation/g3-address/feasibility-v2.results.json')]:
        data = json.loads((ROOT / path).read_text())
        if cap == 'G2':
            row, pointer = data['cases'][0]['rows'][0], '/cases/0/rows/0'
        else:
            row, pointer = data['rows'][0], '/rows/0'
        yield cap, path, pointer, row


def validate_packet(packet: dict[str, Any], *, verify_files: bool = True) -> None:
    if packet.get('content_fingerprint') != fingerprint({k: v for k, v in packet.items() if k != 'content_fingerprint'}):
        raise ValueError('Packet fingerprint mismatch')
    if verify_files:
        for path, digest in packet['source_files'].items():
            target = (ROOT / path).resolve()
            if not target.is_relative_to(ROOT) or file_hash(target) != digest:
                raise ValueError('Frozen source changed: ' + path)
    if packet['provider_requests'] != 0 or packet['production_effect'] != 'none':
        raise ValueError('Provider-free preparation boundary violated')
    sources = {s['video_id']: s for s in packet['sources']}
    if set(sources) != set(SOURCE_IDS) or len(packet['sources']) != len(SOURCE_IDS):
        raise ValueError('Fixed six-source scope changed')
    if verify_files:
        for source in sources.values():
            original = json.loads((PACKET_DIR / 'sources' / f"{source['video_id']}.json").read_text())
            if source != original:
                raise ValueError('Critical integrity failure: wrong_source_or_speaker')
        if packet['references'] != json.loads((PACKET_DIR / 'references-v1.json').read_text()):
            raise ValueError('Independent reference decisions changed')
    for source in sources.values():
        text = source['text']
        if hashlib.sha256(text.encode()).hexdigest() != source['normalized_window_sha256']:
            raise ValueError('Source text hash mismatch')
        for unit in source['units']:
            if text[unit['start']:unit['end']] != unit['text']:
                raise ValueError('Source unit span changed')
    for ref in packet['references']['rows']:
        if sources[ref['video_id']]['text'][ref['start']:ref['end']] != ref['text']:
            raise ValueError('Reference source span changed')
    ids = [c['candidate_id'] for c in packet['candidates']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate candidate aliases')
    for c in packet['candidates']:
        source = sources[c['video_id']]; target = c['target']
        if source['text'][target['start']:target['end']] != target['text'] or target['role'] != 'target':
            raise ValueError('Critical integrity failure: context_promoted_to_target')
    for adapted in packet['source_adapters']:
        data = json.loads((ROOT / adapted['result_path']).read_text())
        for part in adapted['result_pointer'].strip('/').split('/'):
            data = data[int(part)] if isinstance(data, list) else data[part]
        validate_transport(adapted, data)
    if {f['characteristic_id'] for f in packet['field_readiness']} != {f'C{i:02}' for i in range(1,21)}:
        raise ValueError('Desired fields lost')
    if packet['execution_preflight']['ready'] or packet['budget']['authorized_attempts'] or packet['budget']['authorized_usd']:
        raise ValueError('Paid execution remains unauthorized')


def verify_live_sources(packet: dict[str, Any], base_dir: Path) -> None:
    """Focused read-only freshness check of exactly six sources and reviewed membership."""
    from pastor_transcript_extractor.storage import Database
    database = Database(base_dir / 'app.db', readonly=True)
    for source in packet['sources']:
        extraction = database.get_latest_extraction_result_for_video(source['video_id'])
        if extraction is None or extraction.id != source['extraction_id'] or file_hash(Path(extraction.proposed_json_path)) != source['source_file_sha256']:
            raise ValueError(f"Live extraction changed: {source['video_id']}")
        obs = source['observation']
        if obs is None or database.resolve_speaker_profile_id(source['profile_id']) != source['profile_id'] or obs['id'] not in database.list_effective_observation_ids_for_profile(source['profile_id']):
            raise ValueError(f"Live effective membership changed: {source['video_id']}")
        with database.connect() as connection:
            membership = dict(connection.execute('SELECT * FROM profile_observation_events WHERE profile_id=? AND observation_id=? ORDER BY id DESC LIMIT 1', (source['profile_id'], obs['id'])).fetchone())
            review = connection.execute('SELECT * FROM speaker_observation_review_events WHERE observation_id=? ORDER BY id DESC LIMIT 1', (obs['id'],)).fetchone()
        if membership != source['membership_event'] or (dict(review) if review else None) != source['single_speaker_review']:
            raise ValueError(f"Live review provenance changed: {source['video_id']}")


def render_review(packet: dict[str, Any]) -> str:
    positives = Counter(r['capability'] for r in packet['references']['rows'] if r['reference_state'] == 'positive')
    misses = Counter(r['capability'] for r in packet['funnel'] if r['reference_state'] == 'positive' and r['supply_state'] == 'not_supplied')
    counts = Counter(c['capability'] for c in packet['candidates'])
    lines = ['# Evidence-supply readiness V1 review', '',
             '**Provider-free preparation complete; paid proposal BLOCKED.** No readiness PASS or provider execution.', '',
             f"Packet fingerprint: `{packet['content_fingerprint']}`. Six recordings, two profiles, {len(packet['references']['rows'])} independently authored reference/control episodes, {len(packet['candidates'])} supplied lexical candidate targets.", '',
             'Codex reviewed every normalized unit of each supplied window independently before candidate generation. These episode references are not exhaustive gold endpoint pairs; whole-sermon completeness and exact semantic matching remain unestablished.', '',
             '## Fixed natural sources', '', '| Video | Title | Profile | Units | Membership event |', '| --- | --- | --- | --- | --- |']
    for s in packet['sources']:
        lines.append(f"| {s['video_id']} | {s['title'].replace('|','/')} | {s['profile_id']} | {len(s['units'])} | {s['membership_event']['id'] if s['membership_event'] else 'unknown'} |")
    lines += ['', 'Selection prioritizes explanation/address contrasts: text meaning, adopted and reported address, guilt/forgiveness, busy parents, adult children, backsliding, loss of father, and church/readiness controls. Three per profile is incidental to that coverage; the ramp-policy proof positive is absent. Current source boundaries remain disclosed, including 1200 starting partway through its opening story.', '',
              '## Supply funnel before measurement', '', '| Route | Positive reference episodes | Lexical target candidates | Clear positive episodes with no spatial candidate | Semantic matches | Usable observations |', '| --- | --- | --- | --- | --- | --- |']
    for cap in ('G1','G2','G3'):
        lines.append(f'| {cap} | {positives[cap]} | {counts[cap]} | {misses[cap]} | unknown | not measured |')
    lines += ['', 'Spatial overlap does not establish correct directed endpoints, circumstance binding, or semantic discovery. No overlap is an observable supply omission relative to this reference slate. Overlap alone is never reported as recall. Chronological caps, long-target skips, narrow lexical retrieval and the first-circumstance rule remain explicit. No misses are repaired with reference-informed extra candidates.', '',
              'This is a new bounded candidate prototype, not a test of an existing production collector. Its eight-target-per-route-per-sermon budget is deliberately explicit; the omissions include budget truncation, not just lexical non-detection. The result rejects spending on this particular prototype, not the feasibility of supplying these observations through another separately prepared workflow.', '',
              '| Route | All lexical candidates | Retained targets | Budget-truncated candidates |', '| --- | --- | --- | --- |']
    for cap in ('G1','G2','G3'):
        total = sum(d[cap]['lexical_candidates'] for d in packet['discovery_diagnostics'].values())
        truncated = sum(d[cap]['truncated_candidates'] for d in packet['discovery_diagnostics'].values())
        lines.append(f'| {cap} | {total} | {counts[cap]} | {truncated} |')
    lines += ['',
              '## Predeclared interpretation', '',
              '- Critical integrity: zero tolerance for wrong source/speaker, fabricated proposition/relation/opposite, context-to-target transfer, incompatible credit or lost provenance.',
              '- Measurement errors: wrong observations on supplied candidates under unchanged accepted contracts. Conservative positive withholding stays an omission; ambiguous correct withholding is separate.',
              '- Supply misses: positive reference opportunities absent from supplied candidates. They cannot be hidden in measured-candidate accuracy.',
              '- Scoped PASS requires exact frozen semantic matching, no integrity or definite measurement errors, all mandatory references supplied and usable positive evidence in each tested source with an eligible positive. Clear-positive withholding or misses prevent PASS. Broader calibration and collection remain held.', '',
              '## Request and bounded cost proposal', '',
              f"{packet['budget']['maximum_attempts_proposed']} attempted requests proposed, {packet['budget']['question_count']} question answers, zero automatic retries. Pinned `{MODEL}`; natural answers are not reused from differently shaped pilot states. Copied pilot rows test archive transport only.", '',
              f"{len(packet['budget']['blocked_target_ids'])} G1 target windows cannot be serialized under the frozen candidate/phrase-pool ceilings. Their IDs and reasons remain in the manifest; the request total covers serializable targets only and is not a complete-run budget.", '',
              f"Public list price checked 2026-10-14: $0.042 per million input tokens, output free ([TypeSafe model documentation](https://docs.typesafe.ai/models)). Conservative planning reservation: {packet['budget']['token_reservation_proposed']:,} tokens, ${packet['budget']['list_price_reservation_usd']:.4f}. This per-question context reservation is deliberately not represented as a verified tokenizer/billing bound or an authorized spending cap.", '',
              'Authorized spending is $0 and authorized provider attempts are 0. Actual requests/tokens/cost, usable items, errors and withholding remain null until execution. Cost per usable item remains null when unmeasured or when no usable items exist. No corpus extrapolation or production economics model.', '',
              '## Paid-run preflight blockers', '']
    lines += ['- ' + b.replace('_',' ') for b in packet['execution_preflight']['blockers']]
    lines += ['', 'The exact runnable proposal command is the provider-free preflight below. It intentionally exits nonzero with these blockers. There is no paid execution command in this revision; claiming one was ready would conceal the incomplete reference/coverage/billing prerequisites.', '',
              '```sh', 'pte analysis evidence-supply-review --check-only',
              'pte analysis evidence-supply-review --check-only --base-dir /Users/briancummings/Documents/PastorSearchData',
              'pte analysis evidence-supply-review --paid-run-preflight', '```', '',
              'Codex owns any proposed completion of full-sermon boundary/reference review, exact endpoint/circumstance expectations and billing preflight; Brian is not assigned annotation or JSON work. Recommend holding paid execution. The concrete next development proposal is to replace the chronological eight-target cap with a source-wide bounded candidate budget and source-preserving G1 local slices on these same six sources, then freeze exact endpoint/circumstance checks before pricing a runnable paid packet. Preserve this V1 diagnostic and its references; no construct tuning or extra sermons follow automatically.', '',
              'All C01–C20 remain visible in `field-matrix.md`. Sources, references, raw archive rows and request inputs are in `input-v1.json`; `cases.md` exposes literal reference text and candidate links. Frozen pilots/consumer are unchanged. Collection activation, production calibration/recall, operational denominators, production economics, pastor projection/comparison, G4/coherence, clustering, recurrence/rates and scoring stay held.', '']
    return '\n'.join(lines)


def write_packet(packet: dict[str, Any], output_dir: Path) -> None:
    validate_packet(packet)
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = output_dir / 'input-v1.json'
    if existing.exists() and json.loads(existing.read_text()) != packet:
        raise ValueError('Frozen V1 packet differs; preserve it and use a separately versioned proposal')
    (output_dir / 'input-v1.json').write_text(json.dumps(packet, indent=2, ensure_ascii=False)+'\n')
    (output_dir / 'REVIEW.md').write_text(render_review(packet))
    (output_dir / 'funnel-v1.json').write_text(json.dumps(packet['funnel'], indent=2)+'\n')
    fields = ['# C01–C20 evidence supply matrix', '', '| Field | Question | Proposed route | Readiness | Missing information |', '| --- | --- | --- | --- | --- |']
    for f in packet['field_readiness']:
        fields.append(f"| {f['characteristic_id']} | {f['question']} | {f['candidate_route'] or 'inventory only'} | {f['readiness']} | {'; '.join(f['missing_information']) or 'source, coverage, observation policy and stronger-use gates remain'} |")
    (output_dir / 'field-matrix.md').write_text('\n'.join(fields)+'\n')
    cases = ['# Independent reference opportunities and supplied candidates', '',
             'References were frozen before candidate comparison. Every link below is source-window evidence, not a pastor trait. Spatial candidates remain pending exact semantic match. No provider output exists.', '']
    funnel = {r['reference_id']: r for r in packet['funnel']}
    for ref in packet['references']['rows']:
        cases += [f"## {ref['reference_id']} — {ref['video_id']} {ref['capability']} {ref['reference_state']}", '',
                  ref['rationale'], '', 'Units: '+', '.join(ref['unit_ids'])+'.', '',
                  'Spatial candidates: '+(', '.join('['+i+'](#candidate-'+i.replace(':','-').lower()+')' for i in funnel[ref['reference_id']]['spatial_candidate_ids']) or 'not supplied')+'.', '',
                  '```text', ref['text'].replace('```','` ` `'), '```', '']
    for c in packet['candidates']:
        cases += [f"<a id=\"candidate-{c['candidate_id'].replace(':','-').lower()}\"></a>", '', f"## Candidate {c['candidate_id']}", '',
                  f"Source {c['unit_id']}; segments {c['source_segment_indexes']}; {c['start_seconds']}–{c['end_seconds']} seconds. Semantic decision: not measured.", '',
                  '```text', c['target']['text'].replace('```','` ` `'), '```', '']
    (output_dir / 'cases.md').write_text('\n'.join(cases))
