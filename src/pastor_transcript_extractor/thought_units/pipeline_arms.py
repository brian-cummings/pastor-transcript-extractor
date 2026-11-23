"""The full pipeline per unit arm (docs/THOUGHT_UNIT_EXPERIMENT.md section 30): each arm's units are gated by Jev on their own text, not by the block flags.

For a sermon of the confirmatory set, an arm is a list of units cut from the sermon text: `u` (the snapped units) or `s` (the units of the interior split), both from the saved
snap results. Every unit gets the topic pack; units at or above the frozen topic gate get the public-life leaf pack; the frozen flag rule (top three leaves per unit) gives the
pairs, which the frozen v4 instruction reads under the 32768-byte policy. Nothing here changes a threshold, a pack or an instruction. Brian runs the paid steps.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.bound_claims.common import read_json, write_json
from pastor_transcript_extractor.bound_claims.extract import git_state
from pastor_transcript_extractor.bound_claims.leaf_pass import CheckOnlyClient, JEV_REQUEST_RESERVATION, LedgeredClient, PACKS, SIGNAL_COUNTS, signals_for, worst_case_requests
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.sermon_classifier_typesafe import TypeSafeBlockCache

from . import arms, public_set, snap

VERSION = 'pipeline-arms-v1'
SET_ID = 'v2'
VIDEOS = (1502, 1634, 321)                     # the three sermons of the end-to-end test (29)
ARM_PREFIX = dict(u='u', s='s')                # u: snapped units (`jev` cuts); s: the interior split (`jev_split` cuts)
ARM_CUTS = dict(u='jev', s='jev_split')
CEILING_USD, CEILING_ATTEMPTS = Decimal('3.00'), 1200


def arm_dir(base_dir: Path, arm: str) -> Path:
    return public_set.set_dir(base_dir, SET_ID) / 'pipeline' / f'arm-{arm}'


def unit_records(originals: Sequence[Mapping[str, Any]], ranges: Sequence[tuple[int, int]], text: str, prefix: str) -> list[dict[str, Any]]:
    """Units cut from the sermon text, in the shape the pipeline takes. A unit's segments and times come from the saved blocks it overlaps (the segments carry the neighbor context)."""
    records = []
    for ordinal, (start, end) in enumerate(ranges):
        covered = [o for o in originals if o['end'] > start and o['start'] < end]
        if not covered:
            raise ValueError(f'No saved block overlaps the unit at {start}')
        records.append(dict(id=f'{prefix}{ordinal:04d}', ordinal=ordinal, start=start, end=end, text=text[start:end],
                            segment_indexes=sorted({i for o in covered for i in o['segment_indexes']}),
                            start_seconds=covered[0]['start_seconds'], end_seconds=covered[-1]['end_seconds'], block_id=ordinal))
    return records


def arm_sermon(base_dir: Path, video: int, arm: str) -> dict[str, Any]:
    item = next(i for i in public_set.load_candidates(base_dir, SET_ID)['chosen'] if i['video_id'] == video)
    base = public_set._sermon(base_dir, item)
    text = public_set.load_sermon(base_dir, video, SET_ID).text
    result = read_json(snap.set_snap_dir(base_dir, SET_ID, video) / 'snap_result.json')
    if seal(result) != result:
        raise ValueError(f'snap_result.json of sermon {video} seal differs')
    units = unit_records(base['units'], snap.ranges_from_cuts(text, result['arms'][ARM_CUTS[arm]]), text, ARM_PREFIX[arm])
    return dict(item=item, proposed=base['proposed'], units=units, blocks=arms.transcript_blocks(units, base['proposed']['segments']))


def _cache(base_dir: Path, video: int, arm: str) -> TypeSafeBlockCache:
    return TypeSafeBlockCache(arm_dir(base_dir, arm) / 'cache' / f'v{video}', model=public_set.MODEL)


def _signals(base_dir: Path, arm: str, name: str, video: int) -> dict[str, dict[str, float]]:
    path = arm_dir(base_dir, arm) / f'{name}_v{video}.json'
    if not path.exists():
        raise ValueError(f'Run `pte analysis thought-units pipeline-score --arm {arm}` for the earlier pack first')
    scored = read_json(path)
    if seal(scored) != scored:
        raise ValueError(f'{path.name} seal differs')
    return {item['id']: item['signals'] for item in scored['blocks']}


def score(base_dir: Path, arm: str, letter: str, *, check_only: bool = False, client_factory=None, state: Callable[[], dict[str, Any]] = git_state) -> dict[str, Any]:
    """The topic pack (letter T) on every unit of the arm, or the leaf pack (letter P) on the units at or above the frozen topic gate."""
    name = 'topics' if letter == public_set.TOPIC_LETTER else 'leaves'
    out = arm_dir(base_dir, arm)
    ledger = PilotLedger(out / 'ledger.json', ceiling_usd=CEILING_USD, ceiling_attempts=CEILING_ATTEMPTS)
    work = []
    for video in VIDEOS:
        sermon = arm_sermon(base_dir, video, arm)
        if letter == public_set.TOPIC_LETTER:
            wanted = [u['ordinal'] for u in sermon['units']]
        else:
            topics = _signals(base_dir, arm, 'topics', video)
            wanted = [u['ordinal'] for u in sermon['units'] if topics.get(u['id'], {}).get(arms.FLAG_TOPIC, 0.0) >= arms.FLAG_TOPIC_MIN]
        work.append((sermon, [sermon['blocks'][0][i] for i in wanted], sermon['blocks'][1]))
    misses = {w[0]['item']['video_id']: public_set._missing(_cache(base_dir, w[0]['item']['video_id'], arm), w[1], w[2], letter) for w in work}
    requests = worst_case_requests({letter: sum(misses.values())}, {letter: SIGNAL_COUNTS[letter]})
    plan = dict(step=f'pipeline {name}', arm=arm, units={w[0]['item']['video_id']: len(w[0]['units']) for w in work}, scored_units=sum(len(w[1]) for w in work),
                cache_misses=misses, worst_case_requests=requests, worst_case_reserved_usd=str(JEV_REQUEST_RESERVATION * requests), ceiling_usd=str(CEILING_USD),
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
    for sermon, blocks, contexts in work:
        video = sermon['item']['video_id']
        client = LedgeredClient(ledger, factory, public_set.MODEL, f'pipeline-{arm}-{name}-v{video}') if factory else CheckOnlyClient()
        answers = _cache(base_dir, video, arm).assess_packs(client, {}, blocks, requested_packs=frozenset({PACKS[letter][0]}), topic_contexts=contexts) if blocks else {}
        physical += getattr(client, 'requests', 0)
        write_json(out / f'{name}_v{video}.json', seal(dict(
            version=VERSION, step=name, arm=arm, video_id=video, model=public_set.MODEL,
            blocks=[dict(id=unit['id'], block_id=unit['block_id'], signals=signals_for(letter, answers[unit['ordinal']]))
                    for unit in sermon['units'] if any(b.block_id == unit['ordinal'] for b in blocks)])))
    return dict(plan, physical_requests=physical, ledger=ledger.summary())


def build_pairs(base_dir: Path, arm: str, top: int = 3) -> dict[str, Any]:
    """Apply the frozen flag rule to the arm's scored units: the pairs carry the unit text and the adjacent units, as the block pairs do (23: top three leaves per unit)."""
    pairs, per_sermon = [], {}
    for video in VIDEOS:
        sermon = arm_sermon(base_dir, video, arm)
        topics, leaves = _signals(base_dir, arm, 'topics', video), _signals(base_dir, arm, 'leaves', video)
        signals = {unit['id']: {**topics[unit['id']], **leaves.get(unit['id'], {})} for unit in sermon['units']}
        units = sermon['units']
        found = arms.flagged_pairs(units, signals, top)
        for pair in found:
            unit = next(u for u in units if u['id'] == pair['unit'])
            pairs.append(dict(pair, video_id=video, key=f"v{video}-{pair['unit']}-{pair['leaf'].removeprefix('P:')}", unit_start=unit['start'], text=unit['text'],
                              preceding_text=units[unit['ordinal'] - 1]['text'] if unit['ordinal'] else '',
                              following_text=units[unit['ordinal'] + 1]['text'] if unit['ordinal'] + 1 < len(units) else ''))
        per_sermon[video] = dict(units=len(units), gated=sum(signals[u['id']].get(arms.FLAG_TOPIC, 0.0) >= arms.FLAG_TOPIC_MIN for u in units), pairs=len(found),
                                 flagged_units=len({p['unit'] for p in found}), flagged_text_share=round(sum(len(u['text']) for u in units if u['id'] in {p['unit'] for p in found}) /
                                                                                                         max(1, sum(len(u['text']) for u in units)), 3))
    document = seal(dict(version=VERSION, arm=arm, pairs=pairs, pairs_sha256=arms.pairs_digest(pairs)))
    path = public_set.set_dir(base_dir, SET_ID) / 'pipeline' / f'pairs-{arm}.json'
    write_json(path, document)
    return dict(output=str(path), pairs=len(pairs), per_sermon=per_sermon)
