"""Stage 0 free checks for the snapped-unit test (docs/THOUGHT_UNIT_EXPERIMENT.md section 28.8): block size check and the frozen target-point table.

Saved data only, no provider call. The target point of a pair is the span of its saved block-run (B1) anchors, in sermon coordinates; it is fixed before any
unit output exists and its sha256 goes into the spec.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pastor_transcript_extractor.bound_claims.common import digest, read_json, write_json
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal

from . import candidates as cand, public_set, snap

VERSION = 'stage0-check-v1'
EXTRACTION = 'leaf-evidence-b4-confirm-top3/extraction.json'     # B1: the existing v4 block results of section 24


def target_points(base_dir: Path, set_id: str = 'v2', extraction: str = EXTRACTION, top: int = 3) -> list[dict[str, Any]]:
    """One row per extracted pair: the span of its anchored records in sermon coordinates, or None when no record carries an anchor."""
    folder = public_set.set_dir(base_dir, set_id)
    rows = read_json(folder / extraction)['rows']
    pairs = [p for p in read_json(folder / public_set.pairs_name(top))['pairs']]
    # extraction rows carry the unit id and leaf; pairs excluded for input size are absent from them, so rows are matched to pairs in order
    queue = iter(rows)
    table, row = [], next(queue, None)
    for pair in pairs:
        if row is None or row['unit'] != pair['unit'] or row['leaf'] != pair['leaf']:
            continue
        spans = [(c['sermon_start'], c['sermon_end']) for c in row['claims'] if c['anchor'].get('status') == 'ok']
        table.append(dict(key=pair['key'], video_id=int(pair['video_id']), unit=pair['unit'], leaf=pair['leaf'], unit_start=int(pair['unit_start']),
                          records=len(row['claims']), anchored=len(spans),
                          point=dict(start=min(s for s, _ in spans), end=max(e for _, e in spans)) if spans else None))
        row = next(queue, None)
    if row is not None:
        raise ValueError('Extraction rows do not line up with the pairs')
    return table


def size_check(base_dir: Path, set_id: str = 'v2', top: int = 3) -> dict[str, Any]:
    """Every block of every sermon that holds pairs against the snap's guards: at most MAX_CHARACTERS and at least MIN_PIECES sentences."""
    report = {}
    for video in snap.pair_sermons(base_dir, set_id, top):
        sermon = public_set.load_sermon(base_dir, video, set_id)
        pieces = cand.split_pieces(sermon.text)
        sizes = [(coordinate, end - start, snap.piece_count(pieces, start, end)) for coordinate, start, end, _ in sermon.blocks]
        report[str(video)] = dict(blocks=len(sizes), max_characters=max(s for _, s, _ in sizes), over_cap=[c for c, s, _ in sizes if s > snap.MAX_CHARACTERS],
                                  under_min_sentences=[c for c, _, n in sizes if n < snap.MIN_PIECES])
    return dict(sermons=len(report), blocks=sum(v['blocks'] for v in report.values()),
                over_cap=sum(len(v['over_cap']) for v in report.values()), under_min_sentences=sum(len(v['under_min_sentences']) for v in report.values()),
                per_sermon=report)


def run(base_dir: Path, set_id: str = 'v2', top: int = 3) -> dict[str, Any]:
    folder = public_set.set_dir(base_dir, set_id)
    table = target_points(base_dir, set_id, top=top)
    checked = size_check(base_dir, set_id, top)
    result = seal(dict(version=VERSION, set_id=set_id, pairs=len(table), with_point=sum(row['point'] is not None for row in table), points=table, size_check=checked))
    write_json(folder / 'stage0-check.json', result)
    return dict(output=str(folder / 'stage0-check.json'), points_sha256=digest(table), pairs=len(table), with_point=result['with_point'],
                without_point=[row['key'] for row in table if row['point'] is None], size_check={k: v for k, v in checked.items() if k != 'per_sermon'},
                blocks_failing=({v: {k: x[k] for k in ('over_cap', 'under_min_sentences')} for v, x in checked['per_sermon'].items() if x['over_cap'] or x['under_min_sentences']}))
