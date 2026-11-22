"""Boundary-improvement probe (docs/THOUGHT_UNIT_EXPERIMENT.md section 14): a baseline and three approaches on a fresh small set.

Labels are written from the text alone before any Jev answer exists and are hashed into the result. One run, no second round.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.bound_claims.common import digest, file_sha256, read_json, write_json
from pastor_transcript_extractor.bound_claims.extract import git_state
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.object_position import sermon as sermons
from pastor_transcript_extractor.sermon_classifier_typesafe import _BOUNDARY_TRANSITION_CUE

from . import candidates as cand, decide, jev, questions, stage

SET_SIZE, CUE_SHARE = 60, 30
WIDE_WINDOW = 6
EXCLUDED_VIDEOS = (281, 350)   # the sermons already used for G1 and the wording probe
ADOPT_F1_GAIN, ADOPT_PRECISION = 0.15, 0.8
APPROACHES = ('base', 'wide', 'atomic', 'graded')
ATOMIC_NAMES = tuple(questions.ATOMIC)


def paths(base_dir: Path) -> tuple[Path, Path]:
    leaf, _, out = stage.paths(base_dir)
    return leaf, out


def choose_pairs(base_dir: Path) -> dict[str, Any]:
    """60 candidates from the lowest-id sermon not already used: 30 followed by a transition cue, 30 not (fixed seed)."""
    leaf, out = paths(base_dir)
    video = min(item['video_id'] for item in read_json(leaf)['sermons'] if item['video_id'] not in EXCLUDED_VIDEOS)
    sermon = sermons.load(leaf, video)
    pieces = cand.split_pieces(sermon.text)
    found = cand.candidates(sermon.text, pieces)
    cue = lambda c: bool(_BOUNDARY_TRANSITION_CUE.search(sermon.text[pieces[c.index + 1].start:pieces[c.index + 1].start + 40]))
    chosen = []
    for group in ([c for c in found if cue(c)], [c for c in found if not cue(c)]):
        chosen += sorted(group, key=lambda c: stage._seeded(sermon.source_sha256, c.index))[:CUE_SHARE]
    items = []
    for c in sorted(chosen, key=lambda c: c.index):
        before, _, after = cand.passages(sermon.text, pieces, c.index)
        items.append(dict(id=f'i{c.index}', index=c.index, follows_transition_cue=cue(c), before=before, after=after))
    result = dict(video_id=video, source_sha256=sermon.source_sha256, items=items)
    write_json(out / 'improve_pairs.json', result)
    return dict(output=str(out / 'improve_pairs.json'), video_id=video, items=len(items), cue_items=sum(i['follows_transition_cue'] for i in items))


def build_questions(sermon: sermons.Sermon, items: Sequence[Mapping[str, Any]], selected_q2: str) -> dict[str, dict[str, Any]]:
    pieces = cand.split_pieces(sermon.text)
    built: dict[str, dict[str, Any]] = {}
    for item in items:
        index, key = item['index'], item['id']
        before, _, after = cand.passages(sermon.text, pieces, index)
        wide_before, _, wide_after = cand.passages(sermon.text, pieces, index, window=WIDE_WINDOW)
        built[f'base/{key}'] = questions.q2(selected_q2, before, after)
        built[f'wide/{key}'] = questions.q2(selected_q2, wide_before, wide_after)
        for name in ATOMIC_NAMES:
            built[f'atomic/{name}/{key}'] = questions.atomic(name, before, after)
        built[f'graded/{key}'] = questions.graded(before, after)
    return built


def atomic_outcome(answers: Mapping[str, float]) -> tuple[str, float]:
    """Decision from the five atomic judgments, fixed now: cut needs closure, a new-step signal and no development."""
    closure, development = answers['b4_closure'], answers['b5_development']
    signal = max(answers['b1_transition'], answers['b2_new_element'], answers['b3_kind_of_speech'])
    score = (closure + signal + (1.0 - development)) / 3.0
    if development >= decide.HIGH or closure <= decide.LOW:
        return 'no_cut', score
    if closure >= decide.HIGH and signal >= decide.HIGH and development <= decide.LOW:
        return 'cut', score
    return 'unsettled', score


def graded_outcome(probabilities: Mapping[str, float]) -> tuple[str, float]:
    """Levels 1 and 2 (unrelated, new point) mean a break; the same 0.7 / 0.3 convention as the Noul rule."""
    low = probabilities.get('1', 0.0) + probabilities.get('2', 0.0)
    return ('cut' if low >= decide.HIGH else 'no_cut' if low <= decide.LOW else 'unsettled'), low


def decisions(answers: Mapping[str, Any], ids: Sequence[str]) -> dict[str, dict[str, tuple[str, float]]]:
    result: dict[str, dict[str, tuple[str, float]]] = {name: {} for name in APPROACHES}
    for key in ids:
        for name in ('base', 'wide'):
            value = answers[f'{name}/{key}']
            result[name][key] = (decide.outcome(0.0, value), value)   # Q1 is not asked here; only the Q2 side of the table applies
        result['atomic'][key] = atomic_outcome({n: answers[f'atomic/{n}/{key}'] for n in ATOMIC_NAMES})
        result['graded'][key] = graded_outcome(answers[f'graded/{key}'])
    return result


def auc(scores_by_label: Sequence[tuple[float, bool]]) -> float | None:
    positives = [s for s, label in scores_by_label if label]
    negatives = [s for s, label in scores_by_label if not label]
    if not positives or not negatives:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return round(wins / (len(positives) * len(negatives)), 4)


def metrics(labels: Mapping[str, bool | None], decided: Mapping[str, tuple[str, float]]) -> dict[str, Any]:
    ids = [key for key, label in labels.items() if label is not None and key in decided]
    tp = sum(decided[k][0] == 'cut' and labels[k] for k in ids)
    fp = sum(decided[k][0] == 'cut' and not labels[k] for k in ids)
    fn = sum(decided[k][0] != 'cut' and labels[k] for k in ids)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return dict(labeled=len(ids), breaks=sum(bool(labels[k]) for k in ids), cuts=tp + fp, true_cuts=tp, false_cuts=fp, missed=fn,
                precision=round(precision, 4), recall=round(recall, 4), f1=round(f1, 4),
                unsettled_share=round(sum(decided[k][0] == 'unsettled' for k in ids) / len(ids), 4) if ids else 0.0,
                auc=auc([(decided[k][1], bool(labels[k])) for k in ids]))


def verdict(results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    base = results['base']['f1']
    improved = {name: r['f1'] >= base + ADOPT_F1_GAIN and r['precision'] >= ADOPT_PRECISION for name, r in results.items() if name != 'base'}
    best = max((n for n in improved if improved[n]), key=lambda n: (results[n]['f1'], results[n]['auc'] or 0.0), default=None)
    return dict(rule=f'An approach improves only if F1 is at least the baseline F1 + {ADOPT_F1_GAIN} and precision is at least {ADOPT_PRECISION}',
                improved=improved, best=best)


def run(base_dir: Path, *, check_only: bool = False, factory: Callable = jev.default_factory,
        state: Callable[[], dict[str, Any]] = git_state) -> dict[str, Any]:
    leaf, out = paths(base_dir)
    pairs = read_json(out / 'improve_pairs.json')
    labels_path = out / 'improve_labels.json'
    if not labels_path.exists():
        raise ValueError('improve_labels.json must exist before any Jev answer is requested')
    labels_file = read_json(labels_path)
    selected_q2 = read_json(out / 'probe_result.json')['selected']['q2']
    sermon = sermons.load(leaf, pairs['video_id'])
    built = build_questions(sermon, pairs['items'], selected_q2)
    asker = jev.Asker(out / 'improve_answers.json', stage._ledger(out), questions.STATE, factory=factory, label='improve')
    plan = dict(step='boundary improvement probe', video_id=pairs['video_id'], items=len(pairs['items']), approaches=list(APPROACHES),
                wide_window=WIDE_WINDOW, **asker.plan(built))
    if check_only:
        return plan
    if state()['dirty']:
        raise ValueError('Uncommitted source changes: commit before the probe so the questions are reproducible')
    answers = asker.ask(built)
    ids = [item['id'] for item in pairs['items']]
    decided = decisions(answers, ids)
    results = {name: metrics(labels_file['labels'], decided[name]) for name in APPROACHES}
    result = seal(dict(plan, labels_sha256=file_sha256(labels_path), labeled_by=labels_file['labeled_by'], implementation=state(),
                       results=results, verdict=verdict(results),
                       decisions={name: {k: list(v) for k, v in rows.items()} for name, rows in decided.items()}))
    write_json(out / 'improve_result.json', result)
    lines = ['# Boundary improvement probe', '', f"Labels by: {labels_file['labeled_by']} (not Brian). One run, no second round.", '',
             '| Approach | Labeled | Breaks | Cuts | True cuts | Missed | Precision | Recall | F1 | Unsettled | AUC |', '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    lines += [f"| {n} | {r['labeled']} | {r['breaks']} | {r['cuts']} | {r['true_cuts']} | {r['missed']} | {r['precision']} | {r['recall']} | {r['f1']} | {r['unsettled_share']} | {r['auc']} |"
              for n, r in results.items()]
    lines += ['', result['verdict']['rule'] + '.', '', f"Improved: {result['verdict']['improved']}. Best: {result['verdict']['best']}."]
    (out / 'IMPROVE_REPORT.md').write_text('\n'.join(lines) + '\n')
    return dict(plan, output=str(out / 'improve_result.json'), results=results, verdict=result['verdict'])
