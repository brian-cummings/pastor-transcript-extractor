"""Snap test (docs/THOUGHT_UNIT_EXPERIMENT.md section 15): place block edges by Jev's ranking and split at ranked peaks.

Every arm is a list of cut positions; units are the text between consecutive cuts, so no sentence can be dropped or duplicated.
Constants are fixed in the spec and never tuned.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import statistics
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.bound_claims.common import digest, file_sha256, read_json, write_json
from pastor_transcript_extractor.bound_claims.extract import git_state
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.object_position import sermon as sermons

from . import candidates as cand, improve, jev, questions, stage

GAIN_MARGIN = 0.15
MIN_PIECES = 2
MAX_CHARACTERS = 2304
SPLIT_PERCENTILE = 0.75
SPLIT_SEPARATION = 3
PEAK_RADIUS = 2
SAMPLE_EDGES, SPLIT_SAMPLE, UNIT_SAMPLE, CALIBRATION = 40, 15, 15, 15
BAR_ORIGINAL, BAR_CODE_NON_TIES, BAR_SPLIT_PRECISION, BAR_MULTI_DROP = 0.7, 15, 0.6, 0.4
EXCLUDED_VIDEOS = (281, 350, 590)
TERMINAL = '.?!"\')]'


# ---- geometry ---------------------------------------------------------------------------------------------------------

def ranges_from_cuts(text: str, cuts: Sequence[int]) -> list[tuple[int, int]]:
    """Units are the text between consecutive cuts, trimmed of surrounding whitespace; nothing else is removed."""
    edges = [0, *sorted(set(cuts)), len(text)]
    result = []
    for start, end in zip(edges, edges[1:]):
        chunk = text[start:end]
        lead, trail = len(chunk) - len(chunk.lstrip()), len(chunk) - len(chunk.rstrip())
        if chunk.strip():
            result.append((start + lead, end - trail))
    return result


def coverage(text: str, ranges: Sequence[tuple[int, int]]) -> dict[str, Any]:
    strip = lambda value: ''.join(value.split())
    contiguous = all(not text[ranges[i][1]:ranges[i + 1][0]].strip() and ranges[i][1] <= ranges[i + 1][0] for i in range(len(ranges) - 1))
    exact = strip(''.join(text[a:b] for a, b in ranges)) == strip(text)
    return dict(units=len(ranges), contiguous=contiguous, exact_text_once=exact, ok=contiguous and exact)


def piece_count(pieces: Sequence[cand.Piece], start: int, end: int) -> int:
    return sum(start <= p.start < end for p in pieces)


def is_mid_sentence(text: str, position: int) -> bool:
    before = text[:position].rstrip()
    return bool(before) and before[-1] not in TERMINAL


def percentile(values: Sequence[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * (len(ordered) - 1) + 0.5))]


# ---- arms -------------------------------------------------------------------------------------------------------------

def nearest_candidate(found: Sequence[cand.Candidate], position: int, lo: int = -1, hi: int | None = None) -> cand.Candidate | None:
    pool = [c for c in found if c.position > lo and (hi is None or c.position < hi)]
    return min(pool, key=lambda c: (abs(c.position - position), c.position)) if pool else None


def code_cuts(found: Sequence[cand.Candidate], edges: Sequence[int]) -> list[int]:
    return sorted({nearest_candidate(found, e).position for e in edges if nearest_candidate(found, e)})


DROP_PENALTY = -10.0
OFF_MARGIN_PENALTY = -0.5   # allowed only when nothing better keeps the chain feasible
DISTANCE_TIE_BREAK = 1e-6


def place_edges(text: str, pieces: Sequence[cand.Piece], found: Sequence[cand.Candidate], scores: Mapping[int, float],
                edges: Sequence[int]) -> dict[str, Any]:
    """The `jev` arm, placed jointly by dynamic programming so neighbouring edges cannot fight.

    Each edge may land strictly between its neighbours' original positions (the two adjacent blocks). Its utility is 0 at its nearest
    sentence end, the score gain over that sentence end when the gain reaches GAIN_MARGIN, and a penalty otherwise. Positions must
    increase, every unit must keep at least MIN_PIECES sentences and at most MAX_CHARACTERS, and an edge is dropped only when no
    feasible placement exists. Ties go to the placement nearer the original edges.
    """
    bounds = [(edges[j - 1] if j else 0, edges[j + 1] if j + 1 < len(edges) else len(text)) for j in range(len(edges))]
    near = [nearest_candidate(found, edge, *bounds[j]) for j, edge in enumerate(edges)]
    eligible = [[c for c in found if bounds[j][0] < c.position < bounds[j][1]] for j in range(len(edges))]

    def utility(j: int, c: cand.Candidate) -> float:
        if near[j] is None or c.position == near[j].position:
            return 0.0
        gain = scores[c.index] - scores[near[j].index]
        return (gain if gain >= GAIN_MARGIN else OFF_MARGIN_PENALTY) - DISTANCE_TIE_BREAK * abs(c.position - edges[j])

    def room(left: int, right: int) -> bool:
        return right > left and piece_count(pieces, left, right) >= MIN_PIECES and right - left <= MAX_CHARACTERS

    # state: position of the last placed cut (None = text start) -> (total utility, placements so far as {edge: position})
    states: dict[int | None, tuple[float, dict[int, int]]] = {None: (0.0, {})}
    for j in range(len(edges)):
        step: dict[int | None, tuple[float, dict[int, int]]] = {}
        for last, (total, path) in states.items():
            if last not in step or total + DROP_PENALTY > step[last][0]:
                step[last] = (total + DROP_PENALTY, path)
            for c in eligible[j]:
                if not room(last if last is not None else 0, c.position):
                    continue
                value = total + utility(j, c)
                if c.position not in step or value > step[c.position][0]:
                    step[c.position] = (value, {**path, j: c.position})
        states = step
    finals = [(total, path, last) for last, (total, path) in states.items()
              if last is None or room(last, len(text)) or piece_count(pieces, last, len(text)) >= MIN_PIECES and len(text) - last <= MAX_CHARACTERS]
    total, path, _ = max(finals, key=lambda item: (item[0], -len(item[1])))
    moves = []
    for j, position in sorted(path.items()):
        moves.append(dict(edge=j, original=edges[j], placed=position, distance=abs(position - edges[j]),
                          moved_off_nearest=near[j] is not None and position != near[j].position, candidates=len(eligible[j])))
    cuts = sorted(path.values())
    ranges = ranges_from_cuts(text, cuts)
    violations = [r for r in ranges if r[1] - r[0] > MAX_CHARACTERS or piece_count(pieces, r[0], r[1]) < MIN_PIECES]
    return dict(cuts=cuts, dropped_edges=[j for j in range(len(edges)) if j not in path], moves=moves, guard_violations=len(violations))


def split_cuts(text: str, pieces: Sequence[cand.Piece], found: Sequence[cand.Candidate], scores: Mapping[int, float],
               cuts: Sequence[int]) -> dict[str, Any]:
    """The `jev_split` arm: local score peaks at or above the sermon's 75th percentile, 3 sentences from every other cut."""
    ordered = sorted(found, key=lambda c: c.index)
    threshold = percentile([scores[c.index] for c in ordered], SPLIT_PERCENTILE)
    peaks = []
    for position, c in enumerate(ordered):
        near = ordered[max(0, position - PEAK_RADIUS):position + PEAK_RADIUS + 1]
        if scores[c.index] >= threshold and scores[c.index] >= max(scores[n.index] for n in near):
            peaks.append(c)
    piece_at = lambda pos: sum(p.end <= pos for p in pieces)  # sentences before the position
    accepted = list(cuts)
    added = []
    for c in sorted(peaks, key=lambda c: (-scores[c.index], c.position)):
        inside = MIN_PIECES <= piece_at(c.position) <= len(pieces) - MIN_PIECES   # no stray fragment at either end of the sermon
        if inside and all(abs(piece_at(c.position) - piece_at(other)) >= SPLIT_SEPARATION for other in accepted):
            accepted.append(c.position)
            added.append(c.position)
    return dict(cuts=sorted(accepted), added=sorted(added), threshold=round(threshold, 4), peaks=len(peaks))


# ---- running ----------------------------------------------------------------------------------------------------------

ARMS_CEILING_USD, ARMS_CEILING_ATTEMPTS = Decimal('1.00'), 600


def arms_dir(base_dir: Path, video: int) -> Path:
    """The downstream comparison's own folder and ledger (spec section 16); sermon 1200's artifacts are never touched."""
    return stage.paths(base_dir)[2] / f'arms-{video}'


def set_snap_dir(base_dir: Path, set_id: str, video: int) -> Path:
    """A public-set sermon's snap folder and ledger (section 28): beside the set, one per sermon, as `arms_dir` does for sermon 281."""
    from . import public_set
    return public_set.set_dir(base_dir, set_id) / 'snap' / f'snap-{video}'


def _prepare(base_dir: Path, video: int | None = None, set_id: str | None = None):
    if set_id is not None:
        # Public-set sermons are not in the pilot leaf table; the sermon is rebuilt from its saved final-pass blocks in the coordinates pairs use.
        from . import public_set
        if video is None:
            raise ValueError('A public-set snap needs a sermon (--video)')
        leaf, out, sermon = None, set_snap_dir(base_dir, set_id, video), public_set.load_sermon(base_dir, video, set_id)
    else:
        leaf, _, out = stage.paths(base_dir)
        if video is None:
            video = min(item['video_id'] for item in read_json(leaf)['sermons'] if item['video_id'] not in EXCLUDED_VIDEOS)
        else:
            out = arms_dir(base_dir, video)
        sermon = sermons.load(leaf, video)
    pieces = cand.split_pieces(sermon.text)
    # Sentence ends only: a cut after a piece without terminal punctuation (an unpunctuated caption line) would be mid-sentence.
    found = [c for c in cand.candidates(sermon.text, pieces) if not is_mid_sentence(sermon.text, c.position)]
    edges = [start for _, start, _, _ in sermon.blocks[1:]]
    return leaf, out, sermon, pieces, found, edges


def candidate_questions(sermon: sermons.Sermon, pieces, found) -> dict[str, dict[str, Any]]:
    built = {}
    for c in found:
        before, _, after = cand.passages(sermon.text, pieces, c.index)
        for name in improve.ATOMIC_NAMES:
            built[f'atomic/{name}/{c.index}'] = questions.atomic(name, before, after)
    return built


def candidate_scores(answers: Mapping[str, float], found: Sequence[cand.Candidate]) -> dict[int, float]:
    return {c.index: improve.atomic_outcome({n: answers[f'atomic/{n}/{c.index}'] for n in improve.ATOMIC_NAMES})[1] for c in found}


def arm_summary(text: str, pieces, cuts: Sequence[int]) -> dict[str, Any]:
    ranges = ranges_from_cuts(text, cuts)
    sizes = [b - a for a, b in ranges]
    return dict(cuts=len(cuts), units=len(ranges), mid_sentence_cuts=sum(is_mid_sentence(text, c) for c in cuts),
                size=dict(min=min(sizes), median=statistics.median(sizes), p90=sorted(sizes)[int(0.9 * (len(sizes) - 1))], max=max(sizes)),
                min_pieces=min(piece_count(pieces, a, b) for a, b in ranges), coverage=coverage(text, ranges))


def run(base_dir: Path, *, check_only: bool = False, factory: Callable = jev.default_factory,
        state: Callable[[], dict[str, Any]] = git_state, video: int | None = None, set_id: str | None = None) -> dict[str, Any]:
    """Default: the held-out sermon of section 15. With `video`: the same method on that sermon, under its own folder and ledger. With `set_id` and `video`: a public-set sermon (section 28)."""
    leaf, out, sermon, pieces, found, edges = _prepare(base_dir, video, set_id)
    built = candidate_questions(sermon, pieces, found)
    ledger = (stage._ledger(out) if video is None
              else stage._ledger(out, ceiling_usd=ARMS_CEILING_USD, ceiling_attempts=ARMS_CEILING_ATTEMPTS))
    asker = jev.Asker(out / 'snap_answers.json', ledger, questions.STATE, factory=factory, label='snap')
    in_range = [sum(lo < c.position < hi for c in found) for lo, hi in
                ((edges[j - 1] if j else 0, edges[j + 1] if j + 1 < len(edges) else len(sermon.text)) for j in range(len(edges)))]
    plan = dict(step='snap test', video_id=sermon.video_id, title=sermon.title, characters=len(sermon.text), pieces=len(pieces),
                candidates=len(found), edges=len(edges), candidates_per_edge=dict(median=statistics.median(in_range), min=min(in_range)),
                **asker.plan(built))
    if check_only:
        return plan
    if state()['dirty']:
        raise ValueError('Uncommitted source changes: commit before the paid step so the run is reproducible')
    answers = asker.ask(built)
    scores = candidate_scores(answers, found)
    original = list(edges)
    code = code_cuts(found, edges)
    placed = place_edges(sermon.text, pieces, found, scores, edges)
    split = split_cuts(sermon.text, pieces, found, scores, placed['cuts'])
    arms = dict(original=original, code=code, jev=placed['cuts'], jev_split=split['cuts'])
    summaries = {name: arm_summary(sermon.text, pieces, cuts) for name, cuts in arms.items()}
    if not all(s['coverage']['ok'] for s in summaries.values()):
        raise ValueError('Coverage check failed: units do not rejoin to the sermon text exactly once')
    distances = [m['distance'] for m in placed['moves']]
    result = seal(dict(plan, implementation=state(), source_sha256=sermon.source_sha256, leaf_sha256=file_sha256(leaf) if leaf else None, set_id=set_id,
                       constants=dict(gain_margin=GAIN_MARGIN, min_pieces=MIN_PIECES, max_characters=MAX_CHARACTERS, split_percentile=SPLIT_PERCENTILE,
                                      split_separation=SPLIT_SEPARATION, peak_radius=PEAK_RADIUS),
                       arms=arms, summaries=summaries, placement=dict(
                           dropped_edges=placed['dropped_edges'], guard_violations=placed['guard_violations'],
                           moved_off_nearest=sum(m['moved_off_nearest'] for m in placed['moves']),
                           edges_with_3_or_more_candidates=sum(m['candidates'] >= 3 for m in placed['moves']),
                           move_distance=dict(median=statistics.median(distances) if distances else 0, max=max(distances) if distances else 0),
                           moves=placed['moves']),
                       split=dict(added=split['added'], threshold=split['threshold'], peaks=split['peaks']),
                       scores={str(k): round(v, 4) for k, v in scores.items()}))
    write_json(out / 'snap_result.json', result)
    if video is not None:  # the downstream comparison needs the arms only; the blind packet is the section 15 grading apparatus
        return dict(plan, output=str(out / 'snap_result.json'), summaries=summaries,
                    placement={k: v for k, v in result['placement'].items() if k != 'moves'}, split=result['split'])
    sample = build_sample(sermon, pieces, result)
    write_json(out / 'snap_sample.json', sample)
    return dict(plan, output=str(out / 'snap_result.json'), summaries=summaries, placement={k: v for k, v in result['placement'].items() if k != 'moves'},
                split=result['split'], sample=dict(items=len(sample['items']), kinds={k: sum(i['kind'] == k for i in sample['items']) for k in ('edge_pair', 'split', 'unit')}))


def pair_sermons(base_dir: Path, set_id: str, top: int = 3) -> list[int]:
    """The sermons that hold flagged pairs, in video order: the only ones section 28 snaps."""
    from . import public_set
    pairs = read_json(public_set.set_dir(base_dir, set_id) / public_set.pairs_name(top))['pairs']
    return sorted({int(pair['video_id']) for pair in pairs})


def run_pair_sermons(base_dir: Path, set_id: str, *, check_only: bool = False, factory: Callable = jev.default_factory,
                     state: Callable[[], dict[str, Any]] = git_state, top: int = 3) -> dict[str, Any]:
    """Snap every sermon that holds a flagged pair, one folder and ledger per sermon. Check-only sends nothing and totals the estimate; a failure stops the loop."""
    results = {}
    for video in pair_sermons(base_dir, set_id, top):
        results[video] = run(base_dir, check_only=check_only, factory=factory, state=state, video=video, set_id=set_id)
    summary = dict(sermons=len(results))
    if check_only:
        summary.update(requests=sum(r['requests'] for r in results.values()), questions=sum(r['questions'] for r in results.values()),
                       cached=sum(r['cached'] for r in results.values()),
                       estimated_usd=str(sum(Decimal(r['estimated_usd']) for r in results.values())),
                       worst_case_reserved_usd=str(sum(Decimal(r['worst_case_reserved_usd']) for r in results.values())),
                       per_sermon_ceiling=dict(usd=str(ARMS_CEILING_USD), attempts=ARMS_CEILING_ATTEMPTS))
    else:
        summary.update(dropped_edges={v: r['placement']['dropped_edges'] for v, r in results.items() if r['placement']['dropped_edges']},
                       guard_violations={v: r['placement']['guard_violations'] for v, r in results.items() if r['placement']['guard_violations']})
    return dict(summary, per_sermon={str(v): {k: r[k] for k in ('characters', 'candidates', 'edges', 'requests', 'estimated_usd', 'worst_case_reserved_usd') if k in r}
                                     for v, r in results.items()})


# ---- blind grading packet ----------------------------------------------------------------------------------------------

CONTEXT = 260


def _excerpt(text: str, marks: Mapping[str, int]) -> str:
    start, end = max(0, min(marks.values()) - CONTEXT), min(len(text), max(marks.values()) + CONTEXT)
    pieces_, cursor = [], start
    for label, position in sorted(marks.items(), key=lambda kv: kv[1]):
        pieces_.append(text[cursor:position])
        pieces_.append(f' ⟦{label}⟧ ')
        cursor = position
    pieces_.append(text[cursor:end])
    return ''.join(pieces_).strip()


def build_sample(sermon: sermons.Sermon, pieces, result: Mapping[str, Any]) -> dict[str, Any]:
    text, seed, arms = sermon.text, sermon.source_sha256, result['arms']
    seeded = lambda key: digest(f'{seed}:snap:{key}')
    items = []
    for j in sorted(range(len(arms['original'])), key=lambda j: seeded(f'edge{j}'))[:SAMPLE_EDGES]:
        placed = next((m['placed'] for m in result['placement']['moves'] if m['edge'] == j), None)
        if placed is None:
            continue
        near = nearest_candidate([cand.Candidate(0, p) for p in arms['code']], arms['original'][j])
        for other_name, other in (('original', arms['original'][j]), ('code', near.position if near else None)):
            if other is None or abs(other - placed) < 1:
                continue
            flip = int(seeded(f'flip{j}{other_name}'), 16) % 2
            first, second = (('jev', placed), (other_name, other)) if flip == 0 else ((other_name, other), ('jev', placed))
            items.append(dict(kind='edge_pair', edge=j, versus=other_name, arms=dict(A=first[0], B=second[0]),
                              excerpt=_excerpt(text, dict(A=first[1], B=second[1]))))
    order = sorted(range(len(items)), key=lambda i: seeded(f'order{i}'))
    items = [items[i] for i in order]
    for number, item in enumerate(items, 1):
        item['id'] = f'e{number}'
    added = result['split']['added']
    for position in sorted(added, key=lambda p: seeded(f'split{p}'))[:SPLIT_SAMPLE]:
        items.append(dict(kind='split', position=position, arm='jev_split', excerpt=_excerpt(text, dict(CUT=position))))
    for arm in ('jev', 'jev_split'):
        units = ranges_from_cuts(text, arms[arm])
        for start, end in sorted(units, key=lambda r: seeded(f'{arm}unit{r[0]}'))[:UNIT_SAMPLE]:
            items.append(dict(kind='unit', arm=arm, start=start, end=end, excerpt=text[start:end]))
    hidden = [i for i in items if i['kind'] != 'edge_pair']
    for number, item in enumerate(sorted(hidden, key=lambda i: seeded(f"mix{i['kind']}{i.get('position', i.get('start'))}{i['arm']}")), 1):
        item['id'] = f"{'s' if item['kind'] == 'split' else 'u'}{number}"
    return dict(version='snap-sample-v1', items=items)


PROMPTS = dict(edge_pair='Which is the better place to end the block, A or B (or tie)? (a/b/t): ',
               split='Is the marked point a real break between two thoughts? (y/n): ',
               unit='Does this passage contain more than one complete thought? (y/n): ')
ANSWERS = dict(edge_pair={'a', 'b', 't'}, split={'y', 'n'}, unit={'y', 'n'})


def judge(out: Path, grader: str, kinds: Sequence[str], limit: int | None = None, input_fn: Callable[[str], str] = input,
          output_fn: Callable[[Any], Any] = print) -> dict[str, str]:
    """Resumable. The sample lists edge comparisons first in seeded order, so a `limit` takes the same leading items for every grader."""
    sample, path = read_json(out / 'snap_sample.json'), out / 'snap_judgments.json'
    saved = read_json(path) if path.exists() else {}
    mine = saved.setdefault(grader, {})
    items = [i for i in sample['items'] if i['kind'] in kinds]
    for item in items[:limit]:
        while item['id'] not in mine:
            output_fn(f"\n[{item['id']}] {item['kind']}\n{item['excerpt']}")
            answer = input_fn(PROMPTS[item['kind']]).strip().lower()
            if answer in ANSWERS[item['kind']]:
                mine[item['id']] = answer
                write_json(path, saved)
            else:
                output_fn('Not understood.')
    return mine


def record(out: Path, grader: str, answers: Mapping[str, str]) -> None:
    sample = {i['id']: i for i in read_json(out / 'snap_sample.json')['items']}
    for key, answer in answers.items():
        if answer not in ANSWERS[sample[key]['kind']]:
            raise ValueError(f'Invalid answer {answer!r} for {key}')
    path = out / 'snap_judgments.json'
    saved = read_json(path) if path.exists() else {}
    saved.setdefault(grader, {}).update(answers)
    write_json(path, saved)


def report(out: Path, grader: str = 'claude') -> dict[str, Any]:
    sample, judgments = read_json(out / 'snap_sample.json'), read_json(out / 'snap_judgments.json')
    result = read_json(out / 'snap_result.json')
    mine = judgments[grader]
    outcome: dict[str, Any] = {}
    for versus, key in (('original', 'vs_original'), ('code', 'vs_code')):
        wins = losses = ties = 0
        many = 0
        for item in sample['items']:
            if item['kind'] != 'edge_pair' or item['versus'] != versus or item['id'] not in mine:
                continue
            answer = mine[item['id']]
            if answer == 't':
                ties += 1
                continue
            jev_won = item['arms'][answer.upper()] == 'jev'
            wins += jev_won
            losses += not jev_won
            many += next((m['candidates'] >= 3 for m in result['placement']['moves'] if m['edge'] == item['edge']), False)
        outcome[key] = dict(wins=wins, losses=losses, ties=ties, non_ties=wins + losses, win_share=round(wins / (wins + losses), 4) if wins + losses else None,
                            non_ties_on_edges_with_3_or_more_candidates=many)
    splits = [mine[i['id']] for i in sample['items'] if i['kind'] == 'split' and i['id'] in mine]
    units = {arm: [mine[i['id']] for i in sample['items'] if i['kind'] == 'unit' and i['arm'] == arm and i['id'] in mine] for arm in ('jev', 'jev_split')}
    share = lambda values: round(sum(v == 'y' for v in values) / len(values), 4) if values else None
    multi = {arm: share(values) for arm, values in units.items()}
    drop = (1 - multi['jev_split'] / multi['jev']) if multi['jev'] and multi['jev_split'] is not None else None
    h1, h2 = outcome['vs_original'], outcome['vs_code']
    summaries = result['summaries']
    bars = dict(
        H1=dict(rule=f'jev beats original in at least {BAR_ORIGINAL:.0%} of non-tie comparisons', observed=h1, passed=h1['win_share'] is not None and h1['win_share'] >= BAR_ORIGINAL),
        H2=dict(rule=f'jev beats code in more than half of non-tie comparisons with at least {BAR_CODE_NON_TIES} on edges with 3+ candidates', observed=h2,
                passed=(h2['win_share'] or 0) > 0.5 and h2['non_ties_on_edges_with_3_or_more_candidates'] >= BAR_CODE_NON_TIES,
                inconclusive=h2['non_ties_on_edges_with_3_or_more_candidates'] < BAR_CODE_NON_TIES),
        H3=dict(rule='no jev cut is mid-sentence and no unit breaks the size guards', observed=dict(mid_sentence=summaries['jev']['mid_sentence_cuts'],
                guard_violations=result['placement']['guard_violations']),
                passed=summaries['jev']['mid_sentence_cuts'] == 0 and result['placement']['guard_violations'] == 0),
        H4=dict(rule=f'split precision at least {BAR_SPLIT_PRECISION:.0%} and multi-thought share down at least {BAR_MULTI_DROP:.0%}',
                observed=dict(real_breaks=share(splits), splits_judged=len(splits), multi_thought_share=multi, relative_drop=None if drop is None else round(drop, 4)),
                passed=bool(splits) and share(splits) >= BAR_SPLIT_PRECISION and drop is not None and drop >= BAR_MULTI_DROP))
    agreement = None
    if 'brian' in judgments:
        shared = [k for k in judgments['brian'] if k in mine]
        agreement = dict(items=len(shared), same=sum(judgments['brian'][k] == mine[k] for k in shared))
    verdict = 'PASS' if all(bars[k]['passed'] for k in ('H1', 'H2', 'H3')) else 'FAIL' if not bars['H2'].get('inconclusive') else 'INCONCLUSIVE'
    final = dict(grader=grader, verdict=verdict, bars=bars, brian_agreement=agreement, summaries=summaries,
                 placement={k: v for k, v in result['placement'].items() if k != 'moves'})
    write_json(out / 'SNAP_REPORT.json', final)
    lines = [f'# Snap test report (graded by {grader}, not Brian)', '', f'**{verdict}** (H4, splitting, is reported separately).', '', '| Bar | Rule | Observed | Result |', '| --- | --- | --- | --- |']
    lines += [f"| {k} | {v['rule']} | `{v['observed']}` | {'PASS' if v['passed'] else 'FAIL'} |" for k, v in bars.items()]
    lines += ['', f'Brian agreement on calibration items: {agreement}.', '', f"Arm summaries: `{summaries}`", '']
    (out / 'SNAP_REPORT.md').write_text('\n'.join(lines))
    return final
