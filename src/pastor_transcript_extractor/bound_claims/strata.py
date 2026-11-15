"""Step C: deterministic stratified selection of 100 blocks from the leaf table; no provider call."""
from __future__ import annotations

from pathlib import Path
import random
from typing import Any, Mapping

from .common import file_sha256, read_json, write_json, watch_url

VERSION = 'bound-claim-strata-v1'
SALVATION, PUBLIC = 'T:salvation_gospel', 'T:society_public_life'
STRONG, NEAR, ABSENT_TOPIC, ABSENT_LEAF = 0.70, 0.40, 0.15, 0.30
MAX_CONTEXT_GAP_SECONDS = 5.0
# Scarcer public-life strata are filled first; blocks are never reused across strata.
STRATA = (
    ('public_life_strong', 20), ('public_life_near', 15), ('salvation_strong', 25),
    ('salvation_near', 20), ('absent_control', 15), ('other_topic', 5),
)


def qualifies(stratum: str, signals: Mapping[str, float]) -> bool:
    salvation, public = signals[SALVATION], signals[PUBLIC]
    if stratum == 'salvation_strong':
        return salvation >= STRONG
    if stratum == 'salvation_near':
        return NEAR <= salvation < STRONG
    if stratum == 'public_life_strong':
        return public >= STRONG
    if stratum == 'public_life_near':
        return NEAR <= public < STRONG
    if stratum == 'absent_control':
        # Needs the S and P leaf signals; when they were not collected the rule cannot be evaluated.
        leaves = [value for key, value in signals.items() if key[:2] in ('S:', 'P:')]
        return salvation < ABSENT_TOPIC and public < ABSENT_TOPIC and bool(leaves) and all(v < ABSENT_LEAF for v in leaves)
    if stratum == 'other_topic':
        others = [value for key, value in signals.items() if key[:2] == 'T:' and key not in (SALVATION, PUBLIC)]
        return any(v >= STRONG for v in others) and salvation < NEAR and public < NEAR
    raise ValueError('Unknown stratum')


def _context(blocks: list[dict[str, Any]], ordinal: int, offset: int) -> str:
    index = ordinal + offset
    if not 0 <= index < len(blocks):
        return ''
    here, other = blocks[ordinal], blocks[index]
    gap = here['start_seconds'] - other['end_seconds'] if offset < 0 else other['start_seconds'] - here['end_seconds']
    return other['text'] if gap <= MAX_CONTEXT_GAP_SECONDS else ''


def select(leaf: Mapping[str, Any], seed: str) -> dict[str, Any]:
    candidates = []
    for sermon in leaf['sermons']:
        for block in sermon['blocks']:
            missing = [key for key in (SALVATION, PUBLIC) if key not in block['signals']]
            if missing:
                raise ValueError(f"Leaf table lacks required topic signals {missing}; run leaf-run with the topic pack")
            candidates.append((sermon, block))
    candidates.sort(key=lambda item: item[1]['coordinate'])
    chosen: dict[str, dict[str, Any]] = {}
    report = []
    for stratum, wanted in STRATA:
        pool = [item for item in candidates if item[1]['coordinate'] not in chosen and qualifies(stratum, item[1]['signals'])]
        picked = random.Random(f'{seed}:{stratum}').sample(pool, min(wanted, len(pool)))
        for sermon, block in sorted(picked, key=lambda item: item[1]['coordinate']):
            blocks = sermon['blocks']
            ordinal = block['ordinal']
            chosen[block['coordinate']] = dict(
                coordinate=block['coordinate'], stratum=stratum, video_id=sermon['video_id'], profile_id=sermon['profile_id'],
                block_id=block['block_id'], title=sermon['title'], start_seconds=block['start_seconds'], end_seconds=block['end_seconds'],
                watch_url=watch_url(sermon['url'], block['start_seconds']),
                text=block['text'], preceding_text=_context(blocks, ordinal, -1), following_text=_context(blocks, ordinal, 1),
                signals={SALVATION: block['signals'][SALVATION], PUBLIC: block['signals'][PUBLIC]})
        report.append(dict(stratum=stratum, requested=wanted, eligible=len(pool), selected=len(picked),
                           shortfall=wanted - len(picked)))
    return dict(report=report, blocks=list(chosen.values()))


def run(slice_path: Path, leaf_path: Path, output: Path) -> dict[str, Any]:
    slice_path, output = Path(slice_path).resolve(), Path(output).resolve()
    if output != slice_path.parent / 'strata.json':
        raise ValueError('strata.json must be written beside slice.json; every later step reads it from the pilot directory')
    slice_sha = file_sha256(slice_path)
    leaf = read_json(leaf_path)
    if leaf.get('slice_sha256') != slice_sha:
        raise ValueError('Leaf table was collected for a different slice')
    selection = select(leaf, slice_sha)
    result = dict(
        version=VERSION, slice_sha256=slice_sha, leaf_sha256=file_sha256(leaf_path), seed=slice_sha,
        rules=dict(strong=STRONG, near=NEAR, absent_topic=ABSENT_TOPIC, absent_leaf=ABSENT_LEAF, order=[name for name, _ in STRATA],
                   note='Strata are filled in order and a block belongs to one stratum; shortfalls are reported, never borrowed.'),
        shortfalls=[row for row in selection['report'] if row['shortfall']], strata=selection['report'],
        block_count=len(selection['blocks']), blocks=selection['blocks'])
    write_json(output, result)
    return dict(output=str(output), sha256=file_sha256(output), block_count=result['block_count'], strata=result['strata'])
