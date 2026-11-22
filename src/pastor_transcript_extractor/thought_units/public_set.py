"""A new set of public-life sermons for the leaf-evidence work (docs/THOUGHT_UNIT_EXPERIMENT.md section 19). Brian runs the paid commands.

Step 1 (`find`, offline): rank the corpus's analyzed sermons by a fixed public-life vocabulary density over the sermon window and keep the top few.
Step 2 (`score-topics`, Jev): the topic pack on every sermon-labeled time block of those sermons, in a new cache.
Step 3 (`score-leaves`, Jev): the public-life treatment pack on the blocks at or above the frozen topic gate, then the frozen flag rule gives the pairs.
Units are the saved time blocks, which section 16 kept. Section 16's constants are reused unchanged; nothing from sermon 281's artifacts is touched.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.bound_claims.common import digest, file_sha256, read_json, write_json
from pastor_transcript_extractor.bound_claims.extract import git_state
from pastor_transcript_extractor.bound_claims.leaf_pass import (
    CheckOnlyClient, JEV_REQUEST_RESERVATION, LedgeredClient, PACKS, SIGNAL_COUNTS, signals_for, worst_case_requests,
)
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.sermon_classifier_typesafe import TypeSafeBlockCache

from pastor_transcript_extractor.object_position import sermon as sermons

from . import arms, stage

VERSION = 'public-life-set-v1'
LEXICON = re.compile(
    r'\b(government|politic\w*|election\w*|vote[sd]?|voting|congress\w*|senat\w*|president\w*|legislat\w*|constitution\w*|democra\w*|republic\w*|taxes|'
    r'abortion|supreme court|immigra\w*|border|socialis\w*|communis\w*|secular\w*|america\w*|united states|founding fathers|founders)\b', re.IGNORECASE)
MIN_WORDS, TOP_SERMONS, MODEL = 8000, 6, 'jev-1.13.0'
EXCLUDED_VIDEOS = (281,)            # the section 16/17/18 development sermon
CEILING_USD, CEILING_ATTEMPTS = Decimal('1.00'), 600
TOPIC_LETTER, LEAF_LETTER = 'T', 'P'
SERMON_LABEL = 'sermon'

CANDIDATE_SQL = """
SELECT r.video_id, v.title, v.url, v.youtube_video_id, r.source_path
FROM sermon_analysis_runs r JOIN videos v ON v.id = r.video_id
WHERE r.analyzer_key = 'sermon-basics'
  AND r.id = (SELECT MAX(id) FROM sermon_analysis_runs x WHERE x.video_id = r.video_id AND x.analyzer_key = 'sermon-basics')
ORDER BY r.video_id
"""


def set_dir(base_dir: Path) -> Path:
    return stage.paths(base_dir)[2] / VERSION


def ledger_for(base_dir: Path) -> PilotLedger:
    return PilotLedger(set_dir(base_dir) / 'ledger.json', ceiling_usd=CEILING_USD, ceiling_attempts=CEILING_ATTEMPTS)


# ---- step 1: find (offline) -----------------------------------------------------------------------------------------------

def window_text(proposed: Mapping[str, Any]) -> str:
    segments, classification = proposed['segments'], proposed['classification']
    indexes = classification.get('retained_segment_indexes') or [i for i, s in enumerate(segments) if s.get('label') == SERMON_LABEL]
    return ' '.join(segments[i]['text'] for i in indexes)


def density(text: str) -> dict[str, Any]:
    words = len(text.split())
    hits = len(LEXICON.findall(text))
    return dict(words=words, hits=hits, per_thousand=round(1000 * hits / words, 3) if words else 0.0)


def rank(rows: Sequence[Mapping[str, Any]], read: Callable[[str], Mapping[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        try:
            measured = density(window_text(read(row['source_path'])))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if measured['words'] >= MIN_WORDS and row['video_id'] not in EXCLUDED_VIDEOS:
            scored.append(dict(video_id=row['video_id'], youtube_video_id=row['youtube_video_id'], title=row['title'], url=row['url'],
                               source_path=row['source_path'], **measured))
    return sorted(scored, key=lambda item: (-item['per_thousand'], item['video_id']))


def find(base_dir: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f'file:{build_paths(base_dir).database}?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in connection.execute(CANDIDATE_SQL)]
    finally:
        connection.close()
    ranked = rank(rows, read_json)
    chosen = ranked[:TOP_SERMONS]
    for item in chosen:
        item['source_sha256'] = file_sha256(Path(item['source_path']))
    result = seal(dict(version=VERSION, rule=f'sermon-basics sermons with at least {MIN_WORDS} words in the sermon window, excluding {list(EXCLUDED_VIDEOS)}, ranked by '
                       f'frozen public-life vocabulary hits per 1,000 words; the top {TOP_SERMONS} are chosen. A proxy only: Jev topic scores decide what is used.',
                       lexicon=LEXICON.pattern, calibration='sermon 281 scores 12.73; the seven other pilot sermons score 0.14 to 1.70',
                       analyzed_sermons=len(rows), eligible=len(ranked), chosen=chosen, next_ranked=ranked[TOP_SERMONS:TOP_SERMONS + 10]))
    write_json(set_dir(base_dir) / 'candidates.json', result)
    return dict(output=str(set_dir(base_dir) / 'candidates.json'), analyzed_sermons=len(rows), eligible=len(ranked),
                chosen=[{k: item[k] for k in ('video_id', 'title', 'words', 'hits', 'per_thousand')} for item in chosen])


# ---- blocks, sermon text and contexts ------------------------------------------------------------------------------------

def load_candidates(base_dir: Path) -> dict[str, Any]:
    path = set_dir(base_dir) / 'candidates.json'
    if not path.exists():
        raise ValueError('Run `pte analysis thought-units set-find` first')
    found = read_json(path)
    if seal(found) != found:
        raise ValueError('candidates.json seal differs')
    for item in found['chosen']:
        if file_sha256(Path(item['source_path'])) != item['source_sha256']:
            raise ValueError(f"Source changed after the set was chosen: video {item['video_id']}")
    return found


def final_pass_start(blocks: Sequence[Mapping[str, Any]]) -> int:
    """Where the last block set begins. A saved classification holds a coarse pass (about 5-minute blocks) and then the final finer pass (about 90-second blocks); a new
    set starts where the numbering restarts or time runs backward. The established topic analysis is exactly the last set, on all 16 other saved sermons that have one
    except video 419."""
    return max((k for k in range(1, len(blocks)) if blocks[k]['block_id'] <= blocks[k - 1]['block_id'] or blocks[k]['start_seconds'] < blocks[k - 1]['start_seconds']), default=0)


def sermon_blocks(proposed: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The saved time blocks of the final pass that the classifier labeled `sermon`, in order, with the segments and seconds they were saved with."""
    classification = proposed['classification']
    blocks, labels = classification['blocks'], classification['classifications']
    if len(blocks) != len(labels) or any(b['block_id'] != c['block_id'] for b, c in zip(blocks, labels)):
        raise ValueError('Saved blocks and classifications do not line up by position')
    start = final_pass_start(blocks)
    kept = [b for b, c in zip(blocks[start:], labels[start:]) if c['label'] == SERMON_LABEL and b['text'].strip()]
    ids = [b['block_id'] for b in kept]
    if len(set(ids)) != len(ids) or any(later['start_seconds'] < earlier['start_seconds'] for earlier, later in zip(kept, kept[1:])):
        raise ValueError('Final-pass blocks are not unique and in time order')
    return sorted(kept, key=lambda b: (b['start_seconds'], b['block_id']))


def sermon_layout(blocks: Sequence[Mapping[str, Any]], separator: str = '\n\n') -> dict[str, Any]:
    """The sermon text as saved blocks joined by a blank line, and each block's character range (as the section 16 sermon was built)."""
    cursor, ranges = 0, []
    for block in blocks:
        ranges.append((cursor, cursor + len(block['text'])))
        cursor += len(block['text']) + len(separator)
    return dict(text=separator.join(block['text'] for block in blocks), ranges=ranges)


def unit_records(blocks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The shape `arms.transcript_blocks` takes: one unit per saved block, numbered in order."""
    layout = sermon_layout(blocks)
    return [dict(id=f"b{block['block_id']:04d}", ordinal=ordinal, start=layout['ranges'][ordinal][0], end=layout['ranges'][ordinal][1], text=block['text'],
                 segment_indexes=list(block['segment_indexes']), start_seconds=block['start_seconds'], end_seconds=block['end_seconds'],
                 block_id=block['block_id']) for ordinal, block in enumerate(blocks)]


def _sermon(base_dir: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    proposed = read_json(Path(item['source_path']))
    units = unit_records(sermon_blocks(proposed))
    return dict(item=item, proposed=proposed, units=units, blocks=arms.transcript_blocks(units, proposed['segments']))


def load_sermon(base_dir: Path, video_id: int) -> sermons.Sermon:
    """A new-set sermon in the shape the review needs: its text (blocks joined by a blank line, the coordinates pairs use) and the watch link at a position."""
    item = next((i for i in load_candidates(base_dir)['chosen'] if i['video_id'] == video_id), None)
    if item is None:
        raise ValueError(f'Video {video_id} is not in the new set')
    units = _sermon(base_dir, item)['units']
    text = sermons.SEPARATOR.join(u['text'] for u in units)
    return sermons.Sermon(video_id=video_id, title=item['title'], url=item['url'], source_sha256=digest(text), text=text,
                          blocks=tuple((u['id'], u['start'], u['end'], u['start_seconds']) for u in units))


# ---- steps 2 and 3: Jev ------------------------------------------------------------------------------------------------------

def _missing(cache: TypeSafeBlockCache, blocks, contexts, letter: str) -> int:
    pack = PACKS[letter][0]
    return sum(not cache._pack_path(pack, cache._pack_identity({}, b, pack=pack, role_context=None, topic_context=contexts[b.block_id])).exists() for b in blocks)


def _cache(base_dir: Path, video_id: int) -> TypeSafeBlockCache:
    return TypeSafeBlockCache(set_dir(base_dir) / 'cache' / f'v{video_id}', model=MODEL)


def _score(base_dir: Path, letter: str, select: Callable[[dict[str, Any]], Sequence[int]], *, check_only: bool, client_factory,
           state: Callable[[], dict[str, Any]], name: str) -> dict[str, Any]:
    found, ledger = load_candidates(base_dir), ledger_for(base_dir)
    work = []
    for item in found['chosen']:
        sermon = _sermon(base_dir, item)
        wanted = select(sermon)
        blocks = [sermon['blocks'][0][i] for i in wanted]
        work.append((sermon, blocks, sermon['blocks'][1]))
    misses = {item[0]['item']['video_id']: _missing(_cache(base_dir, item[0]['item']['video_id']), item[1], item[2], letter) for item in work}
    requests = worst_case_requests({letter: sum(misses.values())}, {letter: SIGNAL_COUNTS[letter]})
    plan = dict(step=name, sermons=len(work), blocks=sum(len(item[1]) for item in work), cache_misses=misses, worst_case_requests=requests,
                worst_case_reserved_usd=str(JEV_REQUEST_RESERVATION * requests), ceiling_usd=str(CEILING_USD), check_only=check_only,
                remaining_ledger_usd=str(ledger.remaining()[0]))
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
    out = set_dir(base_dir)
    physical = 0
    for sermon, blocks, contexts in work:
        video = sermon['item']['video_id']
        cache = _cache(base_dir, video)
        client = LedgeredClient(ledger, factory, MODEL, f'{name}-v{video}') if factory else CheckOnlyClient()
        answers = cache.assess_packs(client, {}, blocks, requested_packs=frozenset({PACKS[letter][0]}), topic_contexts=contexts) if blocks else {}
        physical += getattr(client, 'requests', 0)
        write_json(out / f'{name}_v{video}.json', seal(dict(
            version=VERSION, step=name, video_id=video, source_sha256=sermon['item']['source_sha256'], model=MODEL,
            blocks=[dict(id=unit['id'], block_id=unit['block_id'], signals=signals_for(letter, answers[unit['ordinal']]))
                    for unit in sermon['units'] if any(b.block_id == unit['ordinal'] for b in blocks)])))
    return dict(plan, physical_requests=physical, ledger=ledger.summary())


def score_topics(base_dir: Path, *, check_only: bool = False, client_factory=None, state: Callable[[], dict[str, Any]] = git_state) -> dict[str, Any]:
    return _score(base_dir, TOPIC_LETTER, lambda sermon: [u['ordinal'] for u in sermon['units']], check_only=check_only, client_factory=client_factory,
                  state=state, name='topics')


def topic_signals(base_dir: Path, video_id: int) -> dict[str, dict[str, float]]:
    path = set_dir(base_dir) / f'topics_v{video_id}.json'
    if not path.exists():
        raise ValueError('Run `pte analysis thought-units set-score-topics` first')
    scored = read_json(path)
    if seal(scored) != scored:
        raise ValueError(f'{path.name} seal differs')
    return {item['id']: item['signals'] for item in scored['blocks']}


def gated_ordinals(sermon: Mapping[str, Any], topics: Mapping[str, Mapping[str, float]]) -> list[int]:
    return [u['ordinal'] for u in sermon['units'] if topics.get(u['id'], {}).get(arms.FLAG_TOPIC, 0.0) >= arms.FLAG_TOPIC_MIN]


def score_leaves(base_dir: Path, *, check_only: bool = False, client_factory=None, state: Callable[[], dict[str, Any]] = git_state) -> dict[str, Any]:
    def select(sermon):
        return gated_ordinals(sermon, topic_signals(base_dir, sermon['item']['video_id']))
    return _score(base_dir, LEAF_LETTER, select, check_only=check_only, client_factory=client_factory, state=state, name='leaves')


MIN_HALF_PAIRS = 15


def split_sermons(videos: Sequence[int], counts: Mapping[int, int]) -> dict[str, Any]:
    """Section 19.3: alternate down the sha256 order of the video id (even places development, odd places held-out); no judgment is involved."""
    order = sorted(videos, key=lambda v: hashlib.sha256(str(v).encode()).hexdigest())
    halves = dict(development=order[0::2], held_out=order[1::2])
    pairs = {name: sum(counts.get(v, 0) for v in members) for name, members in halves.items()}
    return dict(rule='alternate down sha256(str(video_id)) order, first is development', order=order, **halves, pairs=pairs,
                needs_decision=any(n < MIN_HALF_PAIRS for n in pairs.values()))


def half_pairs(base_dir: Path, half: str) -> list[dict[str, Any]]:
    """The sealed pairs of the development or held-out half."""
    if half not in ('development', 'held_out'):
        raise ValueError(f'unknown half {half!r}')
    result = read_json(set_dir(base_dir) / 'pairs.json')
    if seal(result) != result:
        raise ValueError('pairs.json seal differs')
    members = set(result['split'][half])
    return [p for p in result['pairs'] if p['video_id'] in members]


def build_pairs(base_dir: Path) -> dict[str, Any]:
    """Apply the frozen flag rule to every scored sermon; the pairs carry the unit text and its neighbors, as section 16's did."""
    found, out = load_candidates(base_dir), set_dir(base_dir)
    pairs, sermons = [], []
    for item in found['chosen']:
        video = item['video_id']
        sermon = _sermon(base_dir, item)
        topics = topic_signals(base_dir, video)
        leaf_path = out / f'leaves_v{video}.json'
        if not leaf_path.exists():
            raise ValueError('Run `pte analysis thought-units set-score-leaves` first')
        leaves = read_json(leaf_path)
        if seal(leaves) != leaves:
            raise ValueError(f'{leaf_path.name} seal differs')
        signals = {block['id']: {**topics[block['id']], **block['signals']} for block in leaves['blocks']}
        gated = [u for u in sermon['units'] if u['id'] in signals]
        units = sermon['units']
        for pair in arms.flagged_pairs(gated, signals):
            unit = next(u for u in units if u['id'] == pair['unit'])
            pairs.append(dict(pair, video_id=video, key=f"v{video}-{pair['unit']}-{pair['leaf'].removeprefix('P:')}", unit_start=unit['start'], text=unit['text'],
                              preceding_text=units[unit['ordinal'] - 1]['text'] if unit['ordinal'] else '',
                              following_text=units[unit['ordinal'] + 1]['text'] if unit['ordinal'] + 1 < len(units) else ''))
        sermons.append(dict(video_id=video, title=item['title'], url=item['url'], blocks=len(units), gated_blocks=len(gated),
                            pairs=sum(p['video_id'] == video for p in pairs)))
    split = split_sermons([item['video_id'] for item in found['chosen']], {s['video_id']: s['pairs'] for s in sermons})
    result = seal(dict(version=VERSION, candidates_fingerprint=found['content_fingerprint'], split=split, flag_rule=dict(topic=arms.FLAG_TOPIC, topic_min=arms.FLAG_TOPIC_MIN,
                       leaves=list(arms.FLAG_LEAVES), minimum=arms.FLAG_MIN, top=arms.FLAG_TOP), sermons=sermons, pairs=pairs, pairs_sha256=arms.pairs_digest(pairs)))
    write_json(out / 'pairs.json', result)
    return dict(output=str(out / 'pairs.json'), sermons=sermons, split=split, pairs=len(pairs), units_with_a_pair=len({(p['video_id'], p['unit']) for p in pairs}))
