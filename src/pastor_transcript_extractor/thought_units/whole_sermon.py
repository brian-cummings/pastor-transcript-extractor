"""The whole sermon through the whole pipeline, per arm (docs/THOUGHT_UNIT_EXPERIMENT.md section 31).

Arms: `b` (the saved 1-minute blocks of the confirmatory set) and `u` (the snapped units), on the three sermons of the end-to-end test. Every unit gets the topic pack; the
other packs run where the product routes them (31.1): salvation relationships and public-life treatment on units whose topic mass reaches the product route, listener
directives, source material and style on every unit. Leaf pairs are flagged per branch, plus one request per (unit, topic) for topics that have no leaf pack. The v5
instruction reads what Jev found from each pair: the routed category and the flagged leaf, each with the pack's own definition. Nothing here changes a pack, a question,
a floor or the instruction. Brian runs the paid steps.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.bound_claims.common import file_sha256, read_json, write_json
from pastor_transcript_extractor.bound_claims.extract import git_state
from pastor_transcript_extractor.bound_claims.leaf_pass import CheckOnlyClient, JEV_REQUEST_RESERVATION, LedgeredClient, PACKS, SIGNAL_COUNTS, signals_for, worst_case_requests
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.sermon_classifier_typesafe import TypeSafeBlockCache
from pastor_transcript_extractor.sermon_leaf_packs import LISTENER_DIRECTIVES, PUBLIC_LIFE_TREATMENT
from pastor_transcript_extractor.sermon_salvation_relationships import SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS, SALVATION_RELATIONSHIP_SPECS
from pastor_transcript_extractor.sermon_topics import TOPIC_SPECS

from . import arms, public_set, pipeline_arms

VERSION = 'whole-sermon-v1'
SET_ID = 'v2'
ARMS = ('b', 'u')
VIDEOS = pipeline_arms.VIDEOS
CEILING_USD, CEILING_ATTEMPTS = '1.00', 300          # per arm for all Jev passes together (31.1)

# ---- the routing table (31.1) ---------------------------------------------------------------------------------------------------------
SALVATION_TOPIC, PUBLIC_TOPIC = 'T:salvation_gospel', 'T:society_public_life'
TOPIC_ROUTE = 0.55                                   # the product's route for the salvation and public-life packs (`salvation_route_decision`, `public_life_support_route_v1`)
LEAF_FLOOR = 0.8                                     # the frozen experiment floor, used where the product has none
TOP_LEAVES, TOP_TOPICS = 3, 2
PUBLIC_LEAVES = ('critical', 'supportive', 'prescriptive', 'advocative', 'theological', 'moral')
SALVATION_LEAVES = tuple(name for name, floor in SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS.items() if floor is not None)
DIRECTIVE_LEAVES = tuple(LISTENER_DIRECTIVES.definitions)
OTHER_TOPICS = tuple(name for name in TOPIC_SPECS if f'T:{name}' not in (SALVATION_TOPIC, PUBLIC_TOPIC))
BRANCH_ORDER = ('S', 'P', 'L', 'T')
# which units each scored pack runs on: every unit, or the units at the topic route
PACK_RUNS = dict(T=None, S=SALVATION_TOPIC, P=PUBLIC_TOPIC, L=None, M=None, H=None)


def arm_dir(base_dir: Path, arm: str) -> Path:
    return public_set.set_dir(base_dir, SET_ID) / 'whole' / f'arm-{arm}'


def arm_sermon(base_dir: Path, video: int, arm: str) -> dict[str, Any]:
    if arm == 'b':
        item = next(i for i in public_set.load_candidates(base_dir, SET_ID)['chosen'] if i['video_id'] == video)
        return public_set._sermon(base_dir, item)
    if arm == 'u':
        return pipeline_arms.arm_sermon(base_dir, video, 'u')
    raise ValueError('--arm must be b or u')


def arm_cache(base_dir: Path, video: int, arm: str) -> TypeSafeBlockCache:
    """Each arm keeps the cache its earlier steps already filled, so every saved answer is reused and a hit never opens a client."""
    return public_set._cache(base_dir, video, SET_ID) if arm == 'b' else pipeline_arms._cache(base_dir, video, 'u')


def signals_path(base_dir: Path, arm: str, letter: str, video: int) -> Path:
    return arm_dir(base_dir, arm) / f'signals_{letter}_v{video}.json'


def read_signals(base_dir: Path, arm: str, letter: str, video: int, *, required: bool = True) -> dict[str, dict[str, float]]:
    path = signals_path(base_dir, arm, letter, video)
    if not path.exists():
        if required:
            raise ValueError(f'Run `pte analysis thought-units whole-score --arm {arm} --pack {letter}` first')
        return {}
    scored = read_json(path)
    if seal(scored) != scored:
        raise ValueError(f'{path.name} seal differs')
    return {item['id']: item['signals'] for item in scored['units']}


def routed_ordinals(base_dir: Path, arm: str, letter: str, sermon: Mapping[str, Any], video: int) -> list[int]:
    gate = PACK_RUNS[letter]
    if gate is None:
        return [u['ordinal'] for u in sermon['units']]
    topics = read_signals(base_dir, arm, 'T', video)
    return [u['ordinal'] for u in sermon['units'] if topics.get(u['id'], {}).get(gate, 0.0) >= TOPIC_ROUTE]


def score(base_dir: Path, arm: str, letter: str, *, check_only: bool = False, client_factory=None, state: Callable[[], dict[str, Any]] = git_state) -> dict[str, Any]:
    """One pack on the units it runs on (31.1): every unit for T, L, M, H; the units at the topic route for S and P."""
    from decimal import Decimal
    if letter not in PACK_RUNS:
        raise ValueError('--pack must be one of T S P L M H')
    out = arm_dir(base_dir, arm)
    ledger = PilotLedger(out / 'ledger.json', ceiling_usd=Decimal(CEILING_USD), ceiling_attempts=CEILING_ATTEMPTS)
    work = []
    for video in VIDEOS:
        sermon = arm_sermon(base_dir, video, arm)
        wanted = routed_ordinals(base_dir, arm, letter, sermon, video)
        work.append((video, sermon, [sermon['blocks'][0][i] for i in wanted], sermon['blocks'][1]))
    misses = {video: public_set._missing(arm_cache(base_dir, video, arm), blocks, contexts, letter) for video, _, blocks, contexts in work}
    requests = worst_case_requests({letter: sum(misses.values())}, {letter: SIGNAL_COUNTS[letter]})
    plan = dict(step=f'whole {PACKS[letter][1]}', arm=arm, pack=letter, units={v: len(s['units']) for v, s, _, _ in work}, scored_units=sum(len(b) for _, _, b, _ in work),
                cache_misses=misses, worst_case_requests=requests, worst_case_reserved_usd=str(JEV_REQUEST_RESERVATION * requests), ceiling_usd=CEILING_USD,
                ceiling_attempts=CEILING_ATTEMPTS, check_only=check_only, remaining_ledger_usd=str(ledger.remaining()[0]))
    if check_only:
        return plan
    if state()['dirty']:
        raise ValueError('Uncommitted source changes: commit before the paid step so the run is reproducible')
    if requests:
        ledger.require_step('leaf', JEV_REQUEST_RESERVATION * requests, requests)
    factory = client_factory
    if factory is None and requests:
        from pastor_transcript_extractor.recording_verifier_typesafe import TypeSafeSdkAdapter
        factory = lambda model: TypeSafeSdkAdapter(model=model)
    physical = 0
    for video, sermon, blocks, contexts in work:
        client = LedgeredClient(ledger, factory, public_set.MODEL, f'whole-{arm}-{letter}-v{video}') if factory else CheckOnlyClient()
        answers = arm_cache(base_dir, video, arm).assess_packs(client, {}, blocks, requested_packs=frozenset({PACKS[letter][0]}), topic_contexts=contexts) if blocks else {}
        physical += getattr(client, 'requests', 0)
        write_json(signals_path(base_dir, arm, letter, video), seal(dict(
            version=VERSION, arm=arm, pack=letter, video_id=video, model=public_set.MODEL,
            units=[dict(id=unit['id'], signals=signals_for(letter, answers[unit['ordinal']])) for unit in sermon['units'] if unit['ordinal'] in answers])))
    return dict(plan, physical_requests=physical, ledger=ledger.summary())


# ---- pairs --------------------------------------------------------------------------------------------------------------------------------

def category_meaning(topic: str) -> str:
    return TOPIC_SPECS[topic.removeprefix('T:')].definition


def leaf_info(leaf: str) -> dict[str, Any]:
    """What the pack itself says about a flagged leaf: its category, its meaning, and the pack's own criteria and note where it has them."""
    letter, name = leaf.split(':', 1)
    if letter == 'S':
        spec = SALVATION_RELATIONSHIP_SPECS[name]
        return dict(category='salvation_gospel', category_meaning=category_meaning(SALVATION_TOPIC), leaf_meaning=spec.description,
                    counts_when=spec.true_criteria, does_not_count_when=spec.false_criteria)
    if letter == 'P':
        return dict(category='society_public_life', category_meaning=category_meaning(PUBLIC_TOPIC), leaf_meaning=PUBLIC_LIFE_TREATMENT.definitions[name],
                    pack_note=PUBLIC_LIFE_TREATMENT.boundary)
    if letter == 'L':
        return dict(category='listener_directives', category_meaning=LISTENER_DIRECTIVES.positive_template.split(' to {definition}')[0],
                    leaf_meaning=LISTENER_DIRECTIVES.definitions[name], pack_note=LISTENER_DIRECTIVES.boundary)
    if letter == 'T':
        definition = TOPIC_SPECS[name].definition
        return dict(category=name, category_meaning=definition, leaf_meaning=f'The preacher states a point about this topic in their own voice: {definition}')
    raise ValueError(f'No extraction branch for leaf {leaf}')


def flagged(signals: Mapping[str, float]) -> list[tuple[str, str, float]]:
    """The routing table for one unit: (branch, leaf, probability) triples; the top three leaves per leaf pack and the top two topics without a leaf pack."""
    found: list[tuple[str, str, float]] = []
    if signals.get(SALVATION_TOPIC, 0.0) >= TOPIC_ROUTE:
        found += _top('S', [(f'S:{n}', signals.get(f'S:{n}', 0.0)) for n in SALVATION_LEAVES
                            if signals.get(f'S:{n}', 0.0) >= SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[n]], TOP_LEAVES)
    if signals.get(PUBLIC_TOPIC, 0.0) >= TOPIC_ROUTE:
        found += _top('P', [(f'P:{n}', signals.get(f'P:{n}', 0.0)) for n in PUBLIC_LEAVES if signals.get(f'P:{n}', 0.0) >= LEAF_FLOOR], TOP_LEAVES)
    found += _top('L', [(f'L:{n}', signals.get(f'L:{n}', 0.0)) for n in DIRECTIVE_LEAVES if signals.get(f'L:{n}', 0.0) >= LEAF_FLOOR], TOP_LEAVES)
    found += _top('T', [(f'T:{n}', signals.get(f'T:{n}', 0.0)) for n in OTHER_TOPICS if signals.get(f'T:{n}', 0.0) >= TOPIC_ROUTE], TOP_TOPICS)
    return found


def _top(branch: str, scored: Sequence[tuple[str, float]], top: int) -> list[tuple[str, str, float]]:
    return [(branch, leaf, probability) for leaf, probability in sorted(scored, key=lambda item: (-item[1], item[0]))[:top]]


def build_pairs(base_dir: Path, arm: str) -> dict[str, Any]:
    """Apply the routing table to the arm's scored units and write the sealed pairs; offline. A pair whose request cannot fit the 32768-byte input cap is excluded and reported."""
    from . import leaf_evidence
    pairs, excluded, per_sermon = [], [], {}
    for video in VIDEOS:
        sermon = arm_sermon(base_dir, video, arm)
        units = sermon['units']
        letters = {letter: read_signals(base_dir, arm, letter, video, required=letter in 'TSPL') for letter in 'TSPL'}
        found_units: dict[str, set[str]] = {}
        counts = {branch: 0 for branch in BRANCH_ORDER}
        for unit in units:
            signals = {}
            for letter in 'TSPL':
                signals.update(letters[letter].get(unit['id'], {}))
            for branch, leaf, probability in flagged(signals):
                pair = dict(unit=unit['id'], leaf=leaf, branch=branch, probability=probability, video_id=video, unit_start=unit['start'], text=unit['text'],
                            preceding_text=units[unit['ordinal'] - 1]['text'] if unit['ordinal'] else '',
                            following_text=units[unit['ordinal'] + 1]['text'] if unit['ordinal'] + 1 < len(units) else '',
                            key=f"v{video}-{unit['id']}-{leaf.replace(':', '-')}", **leaf_info(leaf))
                try:
                    leaf_evidence.build_request(pair, leaf_evidence.V5, leaf_evidence.PRODUCER_32K)
                except ValueError as error:
                    if 'input exceeds reservation' not in str(error):
                        raise
                    excluded.append(pair['key'])
                    continue
                pairs.append(pair)
                counts[branch] += 1
                found_units.setdefault(branch, set()).add(unit['id'])
        covered = set().union(*found_units.values()) if found_units else set()
        total = max(1, sum(len(u['text']) for u in units))
        per_sermon[video] = dict(units=len(units), pairs=sum(counts.values()), pairs_by_branch=counts, units_with_a_pair=len(covered),
                                 text_share_with_a_pair=round(sum(len(u['text']) for u in units if u['id'] in covered) / total, 3),
                                 topic_routed={'S': sum(1 for u in units if letters['T'].get(u['id'], {}).get(SALVATION_TOPIC, 0.0) >= TOPIC_ROUTE),
                                               'P': sum(1 for u in units if letters['T'].get(u['id'], {}).get(PUBLIC_TOPIC, 0.0) >= TOPIC_ROUTE)})
    document = seal(dict(version=VERSION, arm=arm, pairs=pairs, pairs_sha256=arms.pairs_digest(pairs), excluded_over_input_cap=excluded))
    path = public_set.set_dir(base_dir, SET_ID) / 'whole' / f'pairs-{arm}.json'
    write_json(path, document)
    return dict(output=str(path), pairs=len(pairs), excluded_over_input_cap=len(excluded), per_sermon=per_sermon)


# ---- the authorised retry of transport failures (31.4) --------------------------------------------------------------------------------
def extraction_path(base_dir: Path, scope: Any) -> Path:
    from . import leaf_evidence
    return leaf_evidence.leaf_dir(base_dir, leaf_evidence.V5, scope) / 'extraction.json'


def _keyed_rows(base_dir: Path, scope: Any, pairs_name: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(pair, row) in order. Unit ids repeat across sermons, so a row belongs to the pair at its position, checked by unit and leaf; the run writes one row per pair in order."""
    source = read_json(public_set.set_dir(base_dir, SET_ID) / 'whole' / pairs_name)['pairs']
    rows = read_json(extraction_path(base_dir, scope))['rows']
    if len(rows) != len(source) or any((p['unit'], p['leaf']) != (r['unit'], r['leaf']) for p, r in zip(source, rows)):
        raise ValueError(f'{scope.key}: extraction rows do not match {pairs_name} position by position')
    return list(zip(source, rows))


def build_retry_pairs(base_dir: Path, arm: str) -> dict[str, Any]:
    """Offline: the arm's pairs whose first attempt ended in a transport failure, sealed with the extraction they come from. Schema and anchor failures are not included."""
    from . import leaf_evidence
    if arm not in leaf_evidence.WHOLE_RETRY:
        raise ValueError(f'no retry is authorised for arm {arm}')
    scope = leaf_evidence.WHOLE[arm]
    pairs = [pair for pair, row in _keyed_rows(base_dir, scope, f'pairs-{arm}.json') if row['status'] == 'transport_failure']
    if not pairs:
        raise ValueError('no transport failures to retry')
    source = read_json(public_set.set_dir(base_dir, SET_ID) / 'whole' / f'pairs-{arm}.json')
    document = seal(dict(version=VERSION, arm=arm, retry_of=dict(extraction_sha256=file_sha256(extraction_path(base_dir, scope)), pairs_sha256=source['pairs_sha256']),
                         pairs=pairs, pairs_sha256=arms.pairs_digest(pairs)))
    path = public_set.set_dir(base_dir, SET_ID) / 'whole' / f'pairs-{arm}-retry.json'
    write_json(path, document)
    return dict(output=str(path), pairs=len(pairs), keys=[pair['key'] for pair in pairs])


def merged(base_dir: Path, arm: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(pair, row) for every pair of the arm, a retried pair's row replacing its transport-failure row (marked `retry_of_transport_failure`); every other row is the original."""
    from . import leaf_evidence
    keyed = _keyed_rows(base_dir, leaf_evidence.WHOLE[arm], f'pairs-{arm}.json')
    retry_scope = leaf_evidence.WHOLE_RETRY.get(arm)
    if retry_scope is None or not extraction_path(base_dir, retry_scope).exists():
        return keyed
    retried = {pair['key']: dict(row, retry_of_transport_failure=True) for pair, row in _keyed_rows(base_dir, retry_scope, f'pairs-{arm}-retry.json') if row['status'] != 'pending'}
    return [(pair, retried.get(pair['key'], row) if row['status'] == 'transport_failure' else row) for pair, row in keyed]


def merged_rows(base_dir: Path, arm: str) -> list[dict[str, Any]]:
    return [row for _, row in merged(base_dir, arm)]


# ---- the aggregate (31) -------------------------------------------------------------------------------------------------------------
RECORD_FIELDS = ('summary', 'target')
CLAIM_FIELDS = ('proposition', 'polarity', 'voiced_by', 'preacher_adoption', 'speech_role', 'qualifications', 'conditions', 'reasons')
M_FLOOR = LEAF_FLOOR


def _weighted(units: Sequence[Mapping[str, Any]], signals: Mapping[str, Mapping[str, float]], prefix: str) -> dict[str, float]:
    total = sum(len(u['text']) for u in units) or 1
    names = sorted({name for u in units for name in signals.get(u['id'], {}) if name.startswith(prefix)})
    return {name: round(sum(len(u['text']) * signals.get(u['id'], {}).get(name, 0.0) for u in units) / total, 3) for name in names}


def build_aggregate(base_dir: Path, arm: str, video: int) -> dict[str, Any]:
    """One sermon's aggregate for one arm (31): the topic profile (text-weighted mean topic probability and the units at the product route), the style profile, the source-material counts
    and every extracted record labeled by branch and ordered by position. No sermon text, no anchors, no unit ids and nothing a grader touched; the two arms use one format."""
    sermon = arm_sermon(base_dir, video, arm)
    units = sermon['units']
    total = sum(len(u['text']) for u in units) or 1
    span = units[-1]['end'] or 1       # a record's position is its unit's start as a share of the sermon
    signals = {letter: read_signals(base_dir, arm, letter, video, required=letter in 'TSPL') for letter in 'TMH'}
    topics = _weighted(units, signals['T'], 'T:')
    at_route = {name: sum(1 for u in units if signals['T'].get(u['id'], {}).get(name, 0.0) >= TOPIC_ROUTE) for name in topics}
    records, statuses, covered = [], {}, set()
    for pair, row in merged(base_dir, arm):
        if pair['video_id'] != video:
            continue
        statuses[row['status']] = statuses.get(row['status'], 0) + 1
        for found in row['claims']:
            covered.add(pair['unit'])
            claim = found['claim']
            records.append(dict(position=round(pair['unit_start'] / span, 3),
                                branch=pair['branch'], leaf=pair['leaf'], summary=found['summary'], target=found['target'], **{name: claim[name] for name in CLAIM_FIELDS}))
    records.sort(key=lambda r: (r['position'], r['branch'], r['leaf']))
    return dict(version=VERSION, video_id=video, text_characters=total, topic_profile=dict(sorted(topics.items(), key=lambda item: -item[1])),
                topic_units_at_route=dict(sorted(at_route.items(), key=lambda item: -item[1])),
                style_profile=_weighted(units, signals['H'], 'H:'),
                source_material_units_at_floor={name: sum(1 for u in units if signals['M'].get(u['id'], {}).get(name, 0.0) >= M_FLOOR) for name in sorted(next(iter(signals['M'].values())))},
                extraction=dict(statuses=statuses, records=len(records), share_of_text_in_units_with_a_record=round(sum(len(u['text']) for u in units if u['id'] in covered) / total, 3)),
                records=records)


def write_aggregates(base_dir: Path, arm: str) -> dict[str, Any]:
    out = arm_dir(base_dir, arm)
    summary = {}
    for video in VIDEOS:
        document = seal(build_aggregate(base_dir, arm, video))
        write_json(out / f'aggregate_v{video}.json', document)
        summary[video] = dict(records=document['extraction']['records'], statuses=document['extraction']['statuses'], text_share=document['extraction']['share_of_text_in_units_with_a_record'])
    return dict(arm=arm, output=str(out), sermons=summary)


# ---- the report (31.6) ---------------------------------------------------------------------------------------------------------------
CLOSER_BY, JUDGE_VERDICTS = 0.5, ('full', 'partly', 'not')


def report_dir(base_dir: Path) -> Path:
    return public_set.set_dir(base_dir, SET_ID) / 'whole' / 'report'


def score_report(base_dir: Path) -> dict[str, Any]:
    """Unblind the saved judgments (`report/judge_<video>.json`, `_arm_codes_DO_NOT_SHARE.json`) and score each arm by the reading fixed in 31: an arm is closer if its mean closeness is
    higher by at least 0.5 and it conveys at least as many control points fully; otherwise the arms are level. Offline."""
    here = report_dir(base_dir)
    codes = read_json(here / '_arm_codes_DO_NOT_SHARE.json')
    arms_ = {arm: dict(full=0, partly=0, **{'not': 0}, closeness=[], errors=0, words=[], records=0, text_share=[], failures={}) for arm in ARMS}
    sermons, categories, better = {}, {}, {arm: 0 for arm in (*ARMS, 'tie')}
    for video in VIDEOS:
        judged = read_json(here / f'judge_{video}.json')
        by_code = {codes[str(video)][arm]: arm for arm in ARMS}
        row = dict(points=len(judged['control_points']), arms={})
        for code, arm in by_code.items():
            counts = {name: sum(point[code] == name for point in judged['control_points']) for name in JUDGE_VERDICTS}
            words = len((here / f'sum_{code}_{video}.txt').read_text().split())
            aggregate = read_json(arm_dir(base_dir, arm) / f'aggregate_v{video}.json')
            row['arms'][arm] = dict(code=code, **counts, closeness=judged[code]['closeness'], errors=judged[code]['errors'], words=words,
                                    records=aggregate['extraction']['records'], share_of_text_in_units_with_a_record=aggregate['extraction']['share_of_text_in_units_with_a_record'],
                                    statuses=aggregate['extraction']['statuses'])
            total = arms_[arm]
            for name in JUDGE_VERDICTS:
                total[name] += counts[name]
            total['closeness'].append(judged[code]['closeness'])
            total['errors'] += len(judged[code]['errors'])
            total['words'].append(words)
            total['records'] += aggregate['extraction']['records']
            total['text_share'].append(aggregate['extraction']['share_of_text_in_units_with_a_record'])
            for status, count in aggregate['extraction']['statuses'].items():
                total['failures'][status] = total['failures'].get(status, 0) + count
        row['better'] = by_code.get(judged['better'], 'tie')
        better[row['better']] += 1
        sermons[video] = row
        for point in judged['control_points']:
            bucket = categories.setdefault(point['category'], {arm: dict(full=0, partly=0, **{'not': 0}) for arm in ARMS})
            for code, arm in by_code.items():
                bucket[arm][point[code]] += 1
    summary = {}
    for arm, total in arms_.items():
        mean = lambda values: round(sum(values) / len(values), 2)
        summary[arm] = dict(full=total['full'], partly=total['partly'], not_conveyed=total['not'], mean_closeness=mean(total['closeness']), errors=total['errors'], mean_words=mean(total['words']),
                            records=total['records'], mean_share_of_text_in_units_with_a_record=mean(total['text_share']), statuses=total['failures'])
    gap = round(summary['u']['mean_closeness'] - summary['b']['mean_closeness'], 2)
    leader = 'u' if gap > 0 else 'b'
    closer = abs(gap) >= CLOSER_BY and summary[leader]['full'] >= summary['b' if leader == 'u' else 'u']['full']
    outside = {arm: sum(categories.get('none', {}).get(arm, {}).get(name, 0) for name in ('partly', 'not')) for arm in ARMS}
    lost = {arm: summary[arm]['partly'] + summary[arm]['not_conveyed'] for arm in ARMS}
    return dict(version=VERSION, reading=dict(rule=f'closer if mean closeness is higher by at least {CLOSER_BY} and at least as many control points are conveyed fully; otherwise level',
                                              closeness_gap_u_minus_b=gap, result=f'{arm_name(leader)} closer' if closer else 'level'),
                arms=summary, per_sermon=sermons, better_per_sermon=better, categories=categories,
                points_not_fully_conveyed=dict(total=lost, outside_pipeline_categories=outside, inside=({arm: lost[arm] - outside[arm] for arm in ARMS})))


def arm_name(arm: str) -> str:
    return {'b': 'B (blocks)', 'u': 'U (snapped units)'}[arm]


def render_report(result: Mapping[str, Any]) -> str:
    arms_, reading = result['arms'], result['reading']
    lines = ['# Whole-sermon aggregate test: blocks (B) against snapped units (U)', '',
             f"**Reading (rule fixed before any output):** {reading['rule']}.", '',
             f"**Result: {reading['result']}** (mean closeness U minus B = {reading['closeness_gap_u_minus_b']:+.2f}).", '',
             '| Arm | mean closeness | control points full / partly / not (of 36) | errors | records | share of text in units with a record | mean candidate words |', '| --- | --- | --- | --- | --- | --- | --- |']
    for arm in ARMS:
        a = arms_[arm]
        lines.append(f"| {arm_name(arm)} | {a['mean_closeness']:.2f} | {a['full']} / {a['partly']} / {a['not_conveyed']} | {a['errors']} | {a['records']} | {a['mean_share_of_text_in_units_with_a_record']:.2f} | {a['mean_words']:.0f} |")
    lines += ['', '## Per sermon', '', '| Sermon | arm | closeness | full / partly / not | errors | records | words | better |', '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for video, row in result['per_sermon'].items():
        for arm in ARMS:
            a = row['arms'][arm]
            lines.append(f"| {video} | {arm.upper()} | {a['closeness']} | {a['full']} / {a['partly']} / {a['not']} | {len(a['errors'])} | {a['records']} | {a['words']} | {'yes' if row['better'] == arm else ('tie' if row['better'] == 'tie' else '')} |")
    lost = result['points_not_fully_conveyed']
    lines += ['', '## Where the losses fall', '',
              f"Control points not fully conveyed: B {lost['total']['b']}, U {lost['total']['u']}. Of these, outside every category the pipeline extracts (judge label `none`): B {lost['outside_pipeline_categories']['b']}, U {lost['outside_pipeline_categories']['u']}.", '',
              '| Control-point category | B full / partly / not | U full / partly / not |', '| --- | --- | --- |']
    for name, bucket in sorted(result['categories'].items()):
        lines.append(f"| {name} | {bucket['b']['full']} / {bucket['b']['partly']} / {bucket['b']['not']} | {bucket['u']['full']} / {bucket['u']['partly']} / {bucket['u']['not']} |")
    lines += ['', '## Errors the judge listed', '']
    for video, row in result['per_sermon'].items():
        for arm in ARMS:
            for error in row['arms'][arm]['errors']:
                lines.append(f"- {video} {arm.upper()}: {error}")
    lines += ['', '## Limits', '', '- Three sermons, one writer and one judge per arm and sermon, one control writer per sermon: a direction, not a finding.',
              f"- The writers were asked for 250 to 400 words; {sum(row['arms'][arm]['words'] > 400 for row in result['per_sermon'].values() for arm in ARMS)} of 6 candidates were longer (see the words columns), and the judge was told not to reward length.",
              '- "Inside" a pipeline category is broad: the topic pack has 20 topics, so only a point that fits none counts as outside.']
    return '\n'.join(lines) + '\n'


def write_report(base_dir: Path) -> dict[str, Any]:
    result = score_report(base_dir)
    here = report_dir(base_dir)
    write_json(here / 'WHOLE_SERMON_REPORT.json', seal(result))
    (here / 'WHOLE_SERMON_REPORT.md').write_text(render_report(result))
    return dict(output=str(here / 'WHOLE_SERMON_REPORT.md'), reading=result['reading'], arms=result['arms'])


# ---- calibration of the whole-sermon test (31.7) ---------------------------------------------------------------------------------------
def score_calibration(base_dir: Path) -> dict[str, Any]:
    """Offline, from the saved calibration files (`report/calibration/`): (1) the ceiling, a summary of each whole transcript by an independent writer (C), judged with the two arms' summaries on one
    scale (`judge3_<video>.json`); (2) recall, whether each control point is stated by the records themselves (`recall_<video>.json`), crossed with what the arm's summary conveyed (`report/judge_<video>.json`)."""
    here = report_dir(base_dir)
    codes = read_json(here / '_arm_codes_DO_NOT_SHARE.json')
    ceiling = {name: dict(full=0, partly=0, **{'not': 0}, closeness=[], errors=0) for name in (*ARMS, 'ceiling')}
    recall = {arm: {} for arm in ARMS}
    for video in VIDEOS:
        code = codes[str(video)]
        judged = read_json(here / 'calibration' / f'judge3_{video}.json')
        for name, letter in (('b', code['b']), ('u', code['u']), ('ceiling', 'C')):
            for verdict in JUDGE_VERDICTS:
                ceiling[name][verdict] += sum(point[letter] == verdict for point in judged['control_points'])
            ceiling[name]['closeness'].append(judged[letter]['closeness'])
            ceiling[name]['errors'] += len(judged[letter]['errors'])
        present = {point['n']: point for point in read_json(here / 'calibration' / f'recall_{video}.json')['points']}
        conveyed = {point['n']: point for point in read_json(here / f'judge_{video}.json')['control_points']}
        for arm in ARMS:
            for number, point in present.items():
                key = f"records {point[code[arm]]} -> summary {conveyed[number][code[arm]]}"
                recall[arm][key] = recall[arm].get(key, 0) + 1
    for name, total in ceiling.items():
        total['mean_closeness'] = round(sum(total['closeness']) / len(total['closeness']), 2)
        del total['closeness']
    return dict(version=VERSION, scale_note='The ceiling writer saw the whole transcript; arms B and U were re-judged in the same pass, so their counts differ slightly from the scored report (judge noise)',
                ceiling=ceiling, records_to_summary=recall)


def write_calibration(base_dir: Path) -> dict[str, Any]:
    result = score_calibration(base_dir)
    here = report_dir(base_dir)
    write_json(here / 'CALIBRATION_REPORT.json', seal(result))
    lines = ['# Whole-sermon test: calibration', '', result['scale_note'] + '.', '',
             '| Candidate | control points full / partly / not (of 36) | mean closeness | errors |', '| --- | --- | --- | --- |']
    for name, label in (('ceiling', 'Ceiling (summary from the whole transcript)'), ('b', 'B (blocks)'), ('u', 'U (snapped units)')):
        c = result['ceiling'][name]
        lines.append(f"| {label} | {c['full']} / {c['partly']} / {c['not']} | {c['mean_closeness']:.2f} | {c['errors']} |")
    lines += ['', '## From the records to the summary (each control point, per arm)', '', '| Arm | records state the point | summary conveys it | points |', '| --- | --- | --- | --- |']
    for arm in ARMS:
        for key, count in sorted(result['records_to_summary'][arm].items()):
            present, conveyed = key.removeprefix('records ').split(' -> summary ')
            lines.append(f'| {arm.upper()} | {present} | {conveyed} | {count} |')
    (here / 'CALIBRATION_REPORT.md').write_text('\n'.join(lines) + '\n')
    return dict(output=str(here / 'CALIBRATION_REPORT.md'), ceiling=result['ceiling'], records_to_summary=result['records_to_summary'])
