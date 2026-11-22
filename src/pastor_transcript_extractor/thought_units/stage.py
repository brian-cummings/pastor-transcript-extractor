"""Stages 0 and 1 and the boundary review (docs/THOUGHT_UNIT_EXPERIMENT.md sections 4, 4a and 5). Brian runs the paid commands."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from pastor_transcript_extractor.bound_claims.common import digest, ensure_outside_repository, file_sha256, pilot_dir, read_json, write_json
from pastor_transcript_extractor.bound_claims.extract import git_state
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths, evaluation_root_for
from pastor_transcript_extractor.object_position import sermon as sermons
from pastor_transcript_extractor.sermon_classifier_typesafe import _BOUNDARY_TRANSITION_CUE

from . import candidates as cand, decide, jev, questions

NAME = 'thought-unit-experiment-v1'
CEILING_USD, CEILING_ATTEMPTS = Decimal('3.00'), 600
PROBE_PAIRS, PROBE_CUE_SHARE = 40, 20
G1_BOUNDARIES, G1_NON_BOUNDARIES, G1_ASIDES, G1_THRESHOLD = 20, 10, 10, 0.8
DISPLAY = 600


def paths(base_dir: Path) -> tuple[Path, Path, Path]:
    pilot = pilot_dir(base_dir)
    return (pilot / 'leaf' / 'leaf_observations.json', pilot / 'slice.json',
            ensure_outside_repository(evaluation_root_for(build_paths(base_dir), base_dir) / NAME))


def _ledger(out: Path) -> PilotLedger:
    return PilotLedger(out / 'ledger.json', ceiling_usd=CEILING_USD, ceiling_attempts=CEILING_ATTEMPTS)


def _pieces(sermon: sermons.Sermon):
    pieces = cand.split_pieces(sermon.text)
    return pieces, cand.candidates(sermon.text, pieces)


def _seeded(seed: str, key: int) -> str:
    return digest(f'{seed}:{key}')


# ---- Stage 0: wording probe on a different sermon --------------------------------------------------------------------

def probe_pairs(base_dir: Path) -> dict[str, Any]:
    """40 candidate boundaries from the lowest-id sermon other than 281: 20 followed by a transition cue, 20 not (fixed seed)."""
    leaf, _, out = paths(base_dir)
    table = read_json(leaf)['sermons']
    video = min(item['video_id'] for item in table if item['video_id'] != 281)
    sermon = sermons.load(leaf, video)
    pieces, found = _pieces(sermon)
    cue = lambda c: bool(_BOUNDARY_TRANSITION_CUE.search(sermon.text[pieces[c.index + 1].start:pieces[c.index + 1].start + 40]))
    chosen = []
    for group in ([c for c in found if cue(c)], [c for c in found if not cue(c)]):
        chosen += sorted(group, key=lambda c: _seeded(sermon.source_sha256, c.index))[:PROBE_CUE_SHARE]
    pairs = []
    for c in sorted(chosen, key=lambda c: c.index):
        before, _, after = cand.passages(sermon.text, pieces, c.index)
        pairs.append(dict(id=f'p{c.index}', before=before, after=after, follows_transition_cue=cue(c)))
    result = dict(video_id=video, source_sha256=sermon.source_sha256, pairs=pairs)
    write_json(out / 'probe_pairs.json', result)
    return dict(output=str(out / 'probe_pairs.json'), video_id=video, pairs=len(pairs), cue_pairs=sum(p['follows_transition_cue'] for p in pairs))


def _probe_questions(pairs: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for pair in pairs:
        for variant in questions.Q1_VARIANTS:
            result[f"{variant}/{pair['id']}"] = questions.q1(variant, pair['before'], pair['after'])
        for variant in questions.Q2_VARIANTS:
            result[f"{variant}/{pair['id']}"] = questions.q2(variant, pair['before'], pair['after'])
    return result


def score_probe(answers: Mapping[str, float], labels: Mapping[str, Mapping[str, bool]]) -> dict[str, Any]:
    """Agreement at the fixed 0.7 / 0.3 thresholds against development labels; ties go to the shortest (plainest) wording."""
    rows = {}
    for variants, field, table in ((questions.Q1_VARIANTS, 'mid_sentence', 'q1'), (questions.Q2_VARIANTS, 'new_point', 'q2')):
        for variant, wording in variants.items():
            ids = [pair for pair in labels if labels[pair].get(field) is not None]  # ambiguous pairs are left unlabeled
            correct = unsettled = 0
            for pair in ids:
                probability = answers[f'{variant}/{pair}']
                correct += (probability >= decide.HIGH) if labels[pair][field] else (probability <= decide.LOW)
                unsettled += decide.LOW < probability < decide.HIGH
            rows[variant] = dict(question=table, agreement=round(correct / len(ids), 4), unsettled_share=round(unsettled / len(ids), 4),
                                 length=len(wording['statement']), pairs=len(ids), positives=sum(bool(labels[pair][field]) for pair in ids))
    selected = {}
    for table in ('q1', 'q2'):
        candidates = {k: v for k, v in rows.items() if v['question'] == table}
        selected[table] = min(candidates, key=lambda k: (-candidates[k]['agreement'], candidates[k]['length'], k))
    return dict(variants=rows, selected=selected)


def probe(base_dir: Path, *, check_only: bool = False, factory: Callable = jev.default_factory,
          state: Callable[[], dict[str, Any]] = git_state) -> dict[str, Any]:
    _, _, out = paths(base_dir)
    source = read_json(out / 'probe_pairs.json')
    all_questions = _probe_questions(source['pairs'])
    ledger = _ledger(out)
    asker = jev.Asker(out / 'probe_answers.json', ledger, questions.STATE, factory=factory, label='probe')
    plan = dict(step='stage 0 wording probe', video_id=source['video_id'], pairs=len(source['pairs']), **asker.plan(all_questions))
    if check_only:
        return plan
    if state()['dirty']:
        raise ValueError('Uncommitted source changes: commit before the probe so the wordings are reproducible')
    answers = asker.ask(all_questions)
    result = dict(plan, implementation=state(), answers=answers)
    labels_path = out / 'probe_labels.json'
    if labels_path.exists():
        labels = read_json(labels_path)
        result.update(labeled_by=labels['labeled_by'], **score_probe(answers, labels['labels']))
        write_json(out / 'probe_result.json', seal(result))
        return dict(plan, selected=result['selected'], variants=result['variants'], output=str(out / 'probe_result.json'))
    write_json(out / 'probe_answers_unscored.json', result)
    return dict(plan, note='No probe_labels.json yet; answers are saved and scoring waits for the development labels')


# ---- Stage 1: boundaries and units ------------------------------------------------------------------------------------

def _identity(sermon: sermons.Sermon, leaf_sha: str, selected: Mapping[str, str]) -> dict[str, Any]:
    constants = dict(high=decide.HIGH, low=decide.LOW, max_unit_characters=decide.MAX_UNIT_CHARACTERS, min_unit_pieces=decide.MIN_UNIT_PIECES,
                     window=cand.WINDOW, look_ahead=cand.LOOK_AHEAD, min_side_words=cand.MIN_SIDE_WORDS, long_piece_words=cand.LONG_PIECE_WORDS)
    wordings = dict(q1=questions.Q1_VARIANTS[selected['q1']], q2=questions.Q2_VARIANTS[selected['q2']], q3=questions.Q3_STATEMENT,
                    criteria=[questions.Q1_CRITERIA, questions.Q2_CRITERIA, questions.Q3_CRITERIA], caption=questions.CAPTION_HANDLING)
    return dict(video_id=sermon.video_id, source_sha256=sermon.source_sha256, leaf_sha256=leaf_sha, selected=dict(selected),
                wording_sha256=digest(wordings), constants_sha256=digest(constants), model=jev.MODEL)


def freeze(out: Path, identity: Mapping[str, Any], state: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    current = state()
    if current['dirty']:
        raise ValueError('Uncommitted source changes: the implementation must be committed and frozen before the paid step')
    path = out / 'plan.json'
    if path.exists():
        plan = read_json(path)
        if seal(plan) != plan:
            raise ValueError('plan.json seal differs')
        if ({k: plan[k] for k in identity}, plan['implementation']['src_tree']) != (dict(identity), current['src_tree']):
            raise ValueError('Frozen plan differs from the sermon, wordings, constants or implementation; no variant is allowed')
        return plan
    plan = seal(dict(version=NAME, **identity, implementation=current, ceiling=dict(usd=str(CEILING_USD), attempts=CEILING_ATTEMPTS),
                     retries='none; no second wording round, no threshold change, no re-run of a stage to overcome a result'))
    write_json(path, plan)
    return plan


def _segment_mapper(slice_path: Path, sermon: sermons.Sermon):
    entry = [s for s in read_json(slice_path)['sermons'] if s['video_id'] == sermon.video_id][0]
    source = read_json(entry['source_path'])
    blocks = {b['block_id']: b for b in source['classification']['blocks']}
    starts = {c: s for c, s, _, _ in sermon.blocks}

    def locate(position: int) -> dict[str, Any]:
        coordinate, seconds = sermon.block_at(position)
        block = blocks[int(coordinate.rsplit('b', 1)[1])]
        units = (block.get('normalization') or {}).get('normalized_units', [])
        line = sermon.text.count('\n', starts[coordinate], position)
        aligned = len(block['text'].split('\n')) == len(units)
        index = units[line]['source_segment_indexes'][0] if aligned else block['segment_indexes'][0]
        return dict(coordinate=coordinate, segment_index=index, start_seconds=source['segments'][index]['start_seconds'], line_aligned=aligned)
    return locate


def segment(base_dir: Path, video_id: int, *, check_only: bool = False, factory: Callable = jev.default_factory,
            state: Callable[[], dict[str, Any]] = git_state) -> dict[str, Any]:
    leaf, slice_path, out = paths(base_dir)
    selected = read_json(out / 'probe_result.json')['selected']
    sermon = sermons.load(leaf, video_id)
    text = sermon.text
    pieces, found = _pieces(sermon)
    first = {}
    for c in found:
        before, _, after = cand.passages(text, pieces, c.index)
        first[f'q1/{c.index}'] = questions.q1(selected['q1'], before, after)
        first[f'q2/{c.index}'] = questions.q2(selected['q2'], before, after)
    asker = jev.Asker(out / 'answers.json', _ledger(out), questions.STATE, factory=factory, label='segment')
    plan = dict(step='stage 1 boundaries', video_id=video_id, characters=len(text), pieces=len(pieces), candidates=len(found),
                selected=selected, first_pass=asker.plan(first),
                second_pass_note='Up to 8 resumption questions per cut or unsettled boundary; size known only after the first pass')
    if check_only:
        return plan
    frozen = freeze(out, _identity(sermon, file_sha256(leaf), selected), state)
    answers = asker.ask(first)
    outcomes = {c.index: decide.outcome(answers[f'q1/{c.index}'], answers[f'q2/{c.index}']) for c in found}
    flagged = [c for c in found if outcomes[c.index] in ('cut', 'unsettled')]
    second = {}
    for c in flagged:
        for skip in range(1, cand.LOOK_AHEAD + 1):
            before, between, after = cand.passages(text, pieces, c.index, skip)
            if after:
                second[f'q3/{c.index}/{skip}'] = questions.q3(before, between, after)
    answers3 = asker.ask(second)
    asides, resumption = {}, {}
    for c in flagged:
        by_skip = {int(k.rsplit('/', 1)[1]): v for k, v in answers3.items() if k.startswith(f'q3/{c.index}/')}
        kind, skip = decide.resumption(by_skip)
        resumption[c.index] = kind
        if kind == 'aside':
            asides[c.index] = skip
    q2 = {c.index: answers[f'q2/{c.index}'] for c in found}
    built = decide.build_units(len(pieces), pieces, found, q2, outcomes, asides)
    locate = _segment_mapper(slice_path, sermon)
    units = []
    for number, unit in enumerate(built, 1):
        start, end = pieces[unit.first].start, pieces[unit.last].end
        units.append(dict(id=f'u{number}', start=start, end=end, text=text[start:end], pieces=[unit.first, unit.last],
                          location=locate(start),
                          asides=[dict(pieces=list(rng), start=pieces[rng[0]].start, end=pieces[rng[1]].end) for rng in unit.asides]))
    counts = {kind: sum(v == kind for v in outcomes.values()) for kind in ('cut', 'no_cut', 'unsettled')}
    result = seal(dict(version=NAME, plan_fingerprint=frozen['content_fingerprint'], video_id=video_id, counts=counts,
                       resumption={kind: sum(v == kind for v in resumption.values()) for kind in ('aside', 'unsettled', 'break')},
                       candidates=[dict(index=c.index, position=c.position, outcome=outcomes[c.index], q1=answers[f'q1/{c.index}'],
                                        q2=q2[c.index], resumption=resumption.get(c.index)) for c in found],
                       units=units, ledger=_ledger(out).summary()))
    write_json(out / 'units.json', result)
    return dict(plan, output=str(out / 'units.json'), units=len(units), counts=counts, asides=len(asides),
                unit_characters=dict(median=sorted(len(u['text']) for u in units)[len(units) // 2], maximum=max(len(u['text']) for u in units)),
                ledger=_ledger(out).summary())


# ---- G1: Brian's boundary judgments ------------------------------------------------------------------------------------

def g1_sample(base_dir: Path) -> dict[str, Any]:
    leaf, _, out = paths(base_dir)
    result = read_json(out / 'units.json')
    sermon = sermons.load(leaf, result['video_id'])
    text, seed = sermon.text, sermon.source_sha256
    cuts = [c for c in result['candidates'] if any(abs(u['start'] - c['position']) < 40 for u in result['units'][1:])
            and c['outcome'] == 'cut']
    non = [c for c in result['candidates'] if c['outcome'] != 'cut' and c['resumption'] != 'aside']
    asides = [(unit, aside) for unit in result['units'] for aside in unit['asides']]
    pick = lambda items, n, key: sorted(items, key=lambda x: _seeded(seed, key(x)))[:n]
    items = []
    for c in pick(cuts, G1_BOUNDARIES, lambda c: c['index']):
        items.append(dict(kind='boundary', index=c['index'], before=text[max(0, c['position'] - DISPLAY):c['position']], after=text[c['position']:c['position'] + DISPLAY]))
    for c in pick(non, G1_NON_BOUNDARIES, lambda c: c['index']):
        items.append(dict(kind='non_boundary', index=c['index'], before=text[max(0, c['position'] - DISPLAY):c['position']], after=text[c['position']:c['position'] + DISPLAY]))
    for unit, aside in pick(asides, G1_ASIDES, lambda pair: pair[1]['start']):
        items.append(dict(kind='aside', index=aside['pieces'][0], before=text[max(0, aside['start'] - DISPLAY):aside['start']],
                          between=text[aside['start']:aside['end']], after=text[aside['end']:aside['end'] + DISPLAY]))
    for number, item in enumerate(items, 1):
        item['number'] = number
    sample = seal(dict(version=NAME, units_fingerprint=result['content_fingerprint'], items=items))
    write_json(out / 'g1_sample.json', sample)
    return dict(output=str(out / 'g1_sample.json'), items=len(items), kinds={k: sum(i['kind'] == k for i in items) for k in ('boundary', 'non_boundary', 'aside')})


QUESTIONS = dict(
    boundary='Does the text BEFORE the marked point end a complete thought? (y/n): ',
    non_boundary='Should a break have been at the marked point? (y/n): ',
    aside='Is the text BETWEEN the two spans an interruption, and does the speaker resume the same thought afterward? (y/n): ')


def judge(out: Path, input_fn: Callable[[str], str] = input, output_fn: Callable[[Any], Any] = print) -> dict[str, Any]:
    sample, path = read_json(out / 'g1_sample.json'), out / 'g1_judgments.json'
    saved = read_json(path) if path.exists() else {}
    for item in sample['items']:
        key = str(item['number'])
        while key not in saved:
            middle = f"\n[ASIDE] {item['between']}\n[/ASIDE]\n" if item['kind'] == 'aside' else '\n[BREAK HERE]\n'
            output_fn(f"\n({item['number']}/{len(sample['items'])}) {item['kind']}\n{item['before']}{middle}{item['after']}")
            answer = input_fn(QUESTIONS[item['kind']]).strip().lower()
            if answer in ('y', 'n'):
                saved[key] = answer == 'y'
                write_json(path, saved)
            else:
                output_fn('Not understood.')
    return saved


def g1_report(out: Path) -> dict[str, Any]:
    sample, saved = read_json(out / 'g1_sample.json'), read_json(out / 'g1_judgments.json')
    if len(saved) != len(sample['items']):
        raise ValueError('Judgments are incomplete; finish the review first')
    correct = {'boundary': 0, 'non_boundary': 0, 'aside': 0}
    total = {'boundary': 0, 'non_boundary': 0, 'aside': 0}
    for item in sample['items']:
        answer = saved[str(item['number'])]
        total[item['kind']] += 1
        correct[item['kind']] += (not answer) if item['kind'] == 'non_boundary' else answer
    positions = total['boundary'] + total['non_boundary']
    right = correct['boundary'] + correct['non_boundary']
    asides_ok = total['aside'] == 0 or correct['aside'] / total['aside'] >= G1_THRESHOLD
    passed = positions > 0 and right / positions >= G1_THRESHOLD and asides_ok
    report = dict(status='PASS' if passed else 'FAIL', correct=correct, judged=total,
                  boundary_positions=dict(correct=right, judged=positions), threshold=G1_THRESHOLD,
                  rule='At least 80% of boundary and non-boundary positions correct and, if asides were detected, at least 80% of asides correct')
    write_json(out / 'G1_REPORT.json', report)
    (out / 'G1_REPORT.md').write_text(f"# G1 boundary gate\n\n**{report['status']}**\n\n{report['rule']}.\n\n`{report}`\n")
    return report
