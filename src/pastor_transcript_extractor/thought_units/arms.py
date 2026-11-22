"""Downstream comparison (docs/THOUGHT_UNIT_EXPERIMENT.md section 16): units for time blocks (B), snapped edges (S) and snapped edges
with splits (X), their segment mapping, the Jev assessment on S and X, and the flagged (unit, leaf) pairs. Brian runs the paid commands.
"""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.bound_claims.common import digest, file_sha256, read_json, write_json
from pastor_transcript_extractor.bound_claims.extract import git_state
from pastor_transcript_extractor.bound_claims.leaf_pass import (
    CheckOnlyClient, JEV_REQUEST_RESERVATION, LedgeredClient, PACKS, SIGNAL_COUNTS, signals_for, worst_case_requests,
)
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.models import TranscriptSegmentLabel
from pastor_transcript_extractor.object_position import sermon as sermons
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_classification import TranscriptBlock
from pastor_transcript_extractor.sermon_classifier_typesafe import TOPIC_PACK, TypeSafeBlockCache, topic_question_inventory
from pastor_transcript_extractor.sermon_topics import build_topic_context

from . import candidates as cand, snap, stage

VERSION = 'thought-unit-arms-v1'
ARMS = ('b', 's', 'x')
SNAP_ARM = dict(s='jev', x='jev_split')
VIDEO = 281
ASSESS_LETTERS = 'TP'
# Section 3 flag rule, unchanged: public-life position leaves on units that are about society and public life.
FLAG_TOPIC, FLAG_TOPIC_MIN = 'T:society_public_life', 0.9
FLAG_LEAVES = tuple(f'P:{name}' for name in ('critical', 'supportive', 'prescriptive', 'advocative', 'theological', 'moral'))
FLAG_MIN, FLAG_TOP = 0.8, 2


def arms_paths(base_dir: Path, video: int = VIDEO) -> dict[str, Path]:
    leaf, slice_path, _ = stage.paths(base_dir)
    out = snap.arms_dir(base_dir, video)
    return dict(leaf=leaf, slice=slice_path, out=out, snap=out / 'snap_result.json', units=out / 'units.json', cache=out / 'cache',
                ledger=out / 'ledger.json')


def ledger_for(base_dir: Path, video: int = VIDEO):
    return stage._ledger(arms_paths(base_dir, video)['out'], ceiling_usd=snap.ARMS_CEILING_USD, ceiling_attempts=snap.ARMS_CEILING_ATTEMPTS)


# ---- source: normalized lines, segments and blocks ---------------------------------------------------------------------

def load_source(base_dir: Path, video: int = VIDEO) -> dict[str, Any]:
    paths = arms_paths(base_dir, video)
    table = [s for s in read_json(paths['leaf'])['sermons'] if s['video_id'] == video]
    if len(table) != 1:
        raise ValueError(f'Video {video} is not in the saved leaf table')
    entry = [s for s in read_json(paths['slice'])['sermons'] if s['video_id'] == video][0]
    proposed = read_json(Path(entry['source_path']))
    return dict(sermon=sermons.load(paths['leaf'], video), leaf_blocks=table[0]['blocks'], entry=entry, segments=proposed['segments'],
                class_blocks={b['block_id']: b for b in proposed['classification']['blocks']})


def line_table(source: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Each caption line of the sermon text with the source segments it came from.

    A block's text lines correspond one for one to its `normalized_units`. A block where they do not (the spec's 4 of 76) is one line
    holding all of the block's segments, deterministically, and is reported.
    """
    rows, misaligned = [], []
    for (coordinate, start, end, _), leaf_block in zip(source['sermon'].blocks, source['leaf_blocks']):
        saved = source['class_blocks'][leaf_block['block_id']]
        if saved['text'] != leaf_block['text']:
            raise ValueError(f'{coordinate}: the saved block text differs from its classification block; no segment mapping is possible')
        parts, units = leaf_block['text'].split('\n'), saved['normalization']['normalized_units']
        if len(parts) == len(units):
            cursor = start
            for part, unit in zip(parts, units):
                rows.append(dict(start=cursor, end=cursor + len(part), sources=list(unit['source_segment_indexes']), block=coordinate))
                cursor += len(part) + 1
        else:
            rows.append(dict(start=start, end=end, sources=list(leaf_block['segment_indexes']), block=coordinate))
            misaligned.append(coordinate)
    return rows, misaligned


def map_unit(rows: Sequence[Mapping[str, Any]], segments: Sequence[Mapping[str, Any]], start: int, end: int) -> dict[str, Any] | None:
    """Segments of every caption line the unit overlaps. A cut inside a line shares that line's segments with its neighbour."""
    hit = [row for row in rows if row['start'] < end and row['end'] > start]
    indexes = sorted({i for row in hit for i in row['sources']})
    starts = [segments[i]['start_seconds'] for i in indexes if segments[i].get('start_seconds') is not None]
    ends = [segments[i]['end_seconds'] for i in indexes if segments[i].get('end_seconds') is not None]
    if not indexes or not starts or not ends:
        return None
    return dict(segment_indexes=indexes, start_seconds=min(starts), end_seconds=max(ends), lines=len(hit))


def _units(arm: str, text: str, ranges: Sequence[tuple[int, int]], source: Mapping[str, Any], rows) -> list[dict[str, Any]]:
    whole = {(start, end): (coordinate, block) for (coordinate, start, end, _), block in zip(source['sermon'].blocks, source['leaf_blocks'])}
    units = []
    for ordinal, (start, end) in enumerate(ranges):
        saved = whole.get((start, end))
        if saved:   # a unit that is exactly one saved block keeps that block's own segments and times (its cached answers match)
            mapped = dict(segment_indexes=list(saved[1]['segment_indexes']), start_seconds=saved[1]['start_seconds'],
                          end_seconds=saved[1]['end_seconds'], lines=len(text[start:end].split('\n')))
        else:
            mapped = map_unit(rows, source['segments'], start, end)
        units.append(dict(id=f'{arm}{ordinal + 1:03d}', ordinal=ordinal, start=start, end=end, text=text[start:end],
                          whole_block=saved[0] if saved else None, mapped=mapped is not None, **(mapped or {})))
    return units


def build_units(base_dir: Path, *, check_only: bool = False, video: int = VIDEO) -> dict[str, Any]:
    paths = arms_paths(base_dir, video)
    if not paths['snap'].exists():
        raise ValueError('Run `pte analysis thought-units snap --video` first: the snapped arms come from its result')
    result = read_json(paths['snap'])
    source = load_source(base_dir, video)
    sermon = source['sermon']
    if result['source_sha256'] != sermon.source_sha256:
        raise ValueError('The snap result is for a different source text')
    rows, misaligned = line_table(source)
    block_ranges = [(start, end) for _, start, end, _ in sermon.blocks]
    arms = dict(b=block_ranges, **{arm: snap.ranges_from_cuts(sermon.text, result['arms'][name]) for arm, name in SNAP_ARM.items()})
    built = {arm: _units(arm, sermon.text, ranges, source, rows) for arm, ranges in arms.items()}
    coverage = {arm: snap.coverage(sermon.text, arms[arm]) for arm in ARMS}
    shared = {arm: sum(sum(r['start'] < u['end'] and r['end'] > u['start'] for u in built[arm]) > 1 for r in rows) for arm in ARMS}
    a1 = dict(coverage_ok=all(c['ok'] for c in coverage.values()),
              mid_sentence_cuts={name: result['summaries'][name]['mid_sentence_cuts'] for name in ('jev', 'jev_split')},
              guard_violations=result['placement']['guard_violations'], dropped_edges=len(result['placement']['dropped_edges']),
              unmapped_units={arm: sum(not u['mapped'] for u in built[arm]) for arm in ARMS})
    a1['passed'] = (a1['coverage_ok'] and not any(a1['mid_sentence_cuts'].values()) and a1['guard_violations'] == 0
                    and not any(a1['unmapped_units'].values()))
    summary = dict(video_id=video, units={arm: len(built[arm]) for arm in ARMS}, coverage=coverage, a1=a1,
                   lines=len(rows), misaligned_blocks=misaligned, lines_shared_between_units=shared,
                   whole_block_units={arm: sum(u['whole_block'] is not None for u in built[arm]) for arm in ARMS})
    if check_only:
        return dict(summary, check_only=True)
    write_json(paths['units'], seal(dict(version=VERSION, source_sha256=sermon.source_sha256, leaf_sha256=file_sha256(paths['leaf']),
                                         snap_result_sha256=file_sha256(paths['snap']), summary=summary, units=built)))
    return dict(summary, output=str(paths['units']))


def load_units(base_dir: Path, video: int = VIDEO) -> dict[str, Any]:
    path = arms_paths(base_dir, video)['units']
    if not path.exists():
        raise ValueError('Run `pte analysis thought-units arms` first')
    units = read_json(path)
    if seal(units) != units:
        raise ValueError('units.json seal differs')
    if not units['summary']['a1']['passed']:
        raise ValueError('A1 (integrity) failed for the snapped arms; the run stops and nothing further is paid for')
    return units


# ---- assessment (Jev, new cache) ----------------------------------------------------------------------------------------

def transcript_blocks(units: Sequence[Mapping[str, Any]], segments: Sequence[Mapping[str, Any]]):
    """Blocks and bounded contexts by the same rule as the saved blocks (adjacent timed segments, two sentences a side)."""
    drafts = [SegmentDraft(start_seconds=g.get('start_seconds'), end_seconds=g.get('end_seconds'), text=g['text'], speaker_hint=g.get('speaker_hint'),
                           label=TranscriptSegmentLabel(g['label']), confidence=g.get('confidence')) for g in segments]
    blocks, contexts = [], {}
    for unit in units:
        block = TranscriptBlock(block_id=unit['ordinal'], segment_indexes=list(unit['segment_indexes']), start_seconds=unit['start_seconds'],
                                end_seconds=unit['end_seconds'], text=unit['text'], normalization=dict(context='rolling-caption-normalized'))
        blocks.append(block)
        contexts[block.block_id] = build_topic_context(drafts, block)
    return blocks, contexts


def _pilot_cache_root(source: Mapping[str, Any]) -> Path:
    return TypeSafeBlockCache(Path(source['entry']['cache_dir']), model=source['entry']['model']).root


def _identities(cache: TypeSafeBlockCache, block, pack: str, context) -> list[dict[str, Any]]:
    """The current cache identity and, for the topic pack, the earlier transport identity the pilot's saved answers sit under."""
    current = cache._pack_identity({}, block, pack=pack, role_context=None, topic_context=context)
    return [current] + ([dict(current, questions=topic_question_inventory(0))] if pack == TOPIC_PACK else [])


def seed_from_pilot(cache: TypeSafeBlockCache, pilot_root: Path, blocks, contexts, letters: str, *, copy: bool) -> dict[str, Any]:
    """Reuse a saved pilot answer only when its whole identity (model, question set, text, segments, seconds, context) is identical.

    A pack file is named by the hash of its identity, so a file with the same name under the pilot cache is the same identity.
    """
    counts: dict[str, Any] = dict(already_here=0, reusable=0, missing=0, missing_by_letter={letter: 0 for letter in letters})
    for block in blocks:
        for letter in letters:
            pack = PACKS[letter][0]
            targets = [cache._pack_path(pack, identity) for identity in _identities(cache, block, pack, contexts[block.block_id])]
            if any(path.exists() for path in targets):
                counts['already_here'] += 1
                continue
            saved = next(((pilot_root / 'packs' / pack / path.name, path) for path in targets if (pilot_root / 'packs' / pack / path.name).exists()), None)
            if saved is None:
                counts['missing'] += 1
                counts['missing_by_letter'][letter] += 1
                continue
            counts['reusable'] += 1
            if copy:
                saved[1].parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(saved[0], saved[1])
    return counts


def assess(base_dir: Path, arm: str, *, check_only: bool = False, client_factory: Callable[[str], Any] | None = None,
           state: Callable[[], dict[str, Any]] = git_state, video: int = VIDEO) -> dict[str, Any]:
    if arm not in SNAP_ARM:
        raise ValueError('Assess runs on arm s or x; arm b uses the saved leaf table')
    paths = arms_paths(base_dir, video)
    units, source = load_units(base_dir, video), load_source(base_dir, video)
    items = units['units'][arm]
    blocks, contexts = transcript_blocks(items, source['segments'])
    model = source['entry']['model']
    cache = TypeSafeBlockCache(paths['cache'], model=model)
    seeded = seed_from_pilot(cache, _pilot_cache_root(source), blocks, contexts, ASSESS_LETTERS, copy=not check_only)
    misses = seeded['missing_by_letter']   # a unit with no identical saved or cached answer is the only miss
    questions = {letter: SIGNAL_COUNTS[letter] for letter in ASSESS_LETTERS}
    requests = worst_case_requests(misses, questions)
    ledger = ledger_for(base_dir, video)
    plan = dict(step=f'assess arm {arm}', units=len(items), packs=ASSESS_LETTERS, pilot_answers=seeded, cache_misses=misses,
                worst_case_requests=requests, worst_case_reserved_usd=str(JEV_REQUEST_RESERVATION * requests), check_only=check_only,
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
        factory = lambda name: TypeSafeSdkAdapter(model=name)
    fresh = TypeSafeBlockCache(paths['cache'], model=model)
    client = LedgeredClient(ledger, factory, model, arm) if factory else CheckOnlyClient()
    table = {block.block_id: {} for block in blocks}
    for letter in ASSESS_LETTERS:
        answers = fresh.assess_packs(client, {}, blocks, requested_packs=frozenset({PACKS[letter][0]}), topic_contexts=contexts)
        for block in blocks:
            table[block.block_id].update(signals_for(letter, answers[block.block_id]))
    output = paths['out'] / f'assess_{arm}.json'
    result = seal(dict(version=VERSION, arm=arm, units_sha256=file_sha256(paths['units']), packs=ASSESS_LETTERS, model=model,
                       pilot_answers=seeded, cache_hits=fresh.hits, cache_misses=fresh.misses, physical_requests=getattr(client, 'requests', 0),
                       units=[dict(id=item['id'], signals=table[item['ordinal']]) for item in items], ledger=ledger.summary()))
    write_json(output, result)
    return dict(plan, output=str(output), physical_requests=getattr(client, 'requests', 0), ledger=ledger.summary())


# ---- flagged pairs ------------------------------------------------------------------------------------------------------

def signals_by_unit(base_dir: Path, arm: str, video: int = VIDEO) -> dict[str, dict[str, float]]:
    paths = arms_paths(base_dir, video)
    if arm == 'b':
        units = load_units(base_dir, video)['units']['b']
        blocks = load_source(base_dir, video)['leaf_blocks']
        return {unit['id']: dict(block['signals']) for unit, block in zip(units, blocks)}
    path = paths['out'] / f'assess_{arm}.json'
    if not path.exists():
        raise ValueError(f'Run `pte analysis thought-units assess --arm {arm}` first')
    assessed = read_json(path)
    if seal(assessed) != assessed:
        raise ValueError(f'{path.name} seal differs')
    return {item['id']: item['signals'] for item in assessed['units']}


def flagged_pairs(units: Sequence[Mapping[str, Any]], signals: Mapping[str, Mapping[str, float]]) -> list[dict[str, Any]]:
    """The section 3 rule, identical for every arm: topic at least 0.9, leaves at least 0.8, at most the top two per unit."""
    pairs = []
    for unit in units:
        row = signals[unit['id']]
        if row.get(FLAG_TOPIC, 0.0) < FLAG_TOPIC_MIN:
            continue
        eligible = sorted(((row[leaf], leaf) for leaf in FLAG_LEAVES if row.get(leaf, 0.0) >= FLAG_MIN), key=lambda item: (-item[0], item[1]))
        pairs += [dict(unit=unit['id'], leaf=leaf, probability=probability, topic=row[FLAG_TOPIC]) for probability, leaf in eligible[:FLAG_TOP]]
    return pairs


def pairs_digest(pairs: Sequence[Mapping[str, Any]]) -> str:
    return digest([[p['unit'], p['leaf']] for p in pairs])
