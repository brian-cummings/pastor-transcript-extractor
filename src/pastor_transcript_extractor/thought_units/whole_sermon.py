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

from pastor_transcript_extractor.bound_claims.common import read_json, write_json
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
