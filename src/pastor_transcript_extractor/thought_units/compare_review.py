"""Blind review and report for the same-passage comparison (docs/THOUGHT_UNIT_EXPERIMENT.md section 22).

One item per passage. It shows the passage text and, in shuffled order with neutral letters, each distinct record the arms produced for it (arms that produced the same
record share one option). For every option the grader answers whether the record is defensible (supported by the passage, polarity and voice right, nothing added)
and whether it states a single point (not a bundle of separable claims and not a fragment); when there are two or more options, which states the single most defensible
point, or tie, or none. The arm map is kept in a separate file. Labels are evaluation labels and never become runtime evidence; each carries its source.
"""
from __future__ import annotations

from math import comb
from pathlib import Path
import random
from typing import Any, Callable, Mapping

from pastor_transcript_extractor.bound_claims.common import digest, read_json, write_json
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.object_position import sermon as sermons

from . import arms, leaf_evidence, leaf_review, main_point, unit_compare

VERSION = 'unit-compare-review-v1'
CONTEXT = 250
ARM_NAMES = dict(b='time blocks', s='snapped units', x='snapped units with splits')
# Decision rule, frozen in spec section 22.4.
SIGN_TEST_P, MIN_DECISIVE = 0.10, 8


def paths_for(base_dir: Path, variant: leaf_evidence.Variant = leaf_evidence.V2) -> dict[str, Path]:
    out = unit_compare.compare_dir(base_dir) / f'review-{variant.key}'
    return dict(out=out, queue=out / 'review.json', versions=out / 'review_arms.json', decisions=out / leaf_review.DECISIONS,
                report_md=out / 'COMPARE_REPORT.md', report_json=out / 'COMPARE_REPORT.json')


def extraction(base_dir: Path, arm: str, variant: leaf_evidence.Variant) -> dict[str, Any]:
    scope = leaf_evidence.COMPARE[arm]
    result = leaf_review._sealed(leaf_evidence.leaf_dir(base_dir, variant, scope) / 'extraction.json')
    pairs = leaf_evidence.pair_inputs(base_dir, scope)
    if len(result['rows']) != len(pairs):
        raise ValueError(f'{arm} answered {len(result["rows"])} of {len(pairs)} pairs; the run stopped or is incomplete')
    found = {}
    for pair, row in zip(pairs, result['rows']):
        if row['status'] != 'ok':
            raise ValueError(f"Pair {pair['key']} is {row['status']} for arm {arm}; the comparison needs every pair answered")
        found[(pair['unit'], pair['leaf'])] = row['claims'][0] if row['claims'] else None
    return found


def build_queue(base_dir: Path, variant: leaf_evidence.Variant = leaf_evidence.V2) -> dict[str, Any]:
    clusters = unit_compare.load(base_dir)['clusters']
    sermon = sermons.load(arms.arms_paths(base_dir)['leaf'], arms.VIDEO)
    found = {arm: extraction(base_dir, arm, variant) for arm in unit_compare.ARMS}
    seed = digest(dict(sermon=sermon.source_sha256, clusters=[c['id'] for c in clusters], variant=variant.key))
    items, arm_map = [], {}
    for cluster in clusters:
        options: dict[str, dict[str, Any]] = {}
        for arm in unit_compare.ARMS:
            record = found[arm][(cluster['evidence'][arm]['unit'], cluster['leaf'])]
            if record is None:
                continue
            fingerprint = digest(dict(at=record['sermon_start'], end=record['sermon_end'], summary=record['summary'], proposition=record['claim']['proposition']))
            option = options.setdefault(fingerprint, dict(record=record, arms=[]))
            option['arms'].append(arm)
        ordered = sorted(options.items())
        random.Random(f"{seed}:{cluster['id']}").shuffle(ordered)
        shown = []
        for letter, (fingerprint, option) in zip('ABC', ordered):
            record, claim = option['record'], option['record']['claim']
            shown.append(dict(letter=letter, summary=record['summary'], target=record['target'], proposition=claim['proposition'], polarity=claim['polarity'],
                              voiced_by=claim['voiced_by'], preacher_adoption=claim['preacher_adoption'], speech_role=claim['speech_role'],
                              qualifications=claim['qualifications'], anchor=sermon.text[record['sermon_start']:record['sermon_end']]))
        item_id = digest(dict(passage=cluster['id'], seed=seed))[:16]
        items.append(dict(id=item_id, kind='passage', passage=cluster['id'], leaf=cluster['leaf'], leaf_meaning=main_point.leaf_meaning(cluster['leaf']),
                          watch_url=sermon.link_at(cluster['start']), before=sermon.text[max(0, cluster['start'] - CONTEXT):cluster['start']],
                          text=sermon.text[cluster['start']:cluster['end']], after=sermon.text[cluster['end']:cluster['end'] + CONTEXT], options=shown))
        arm_map[item_id] = dict(passage=cluster['id'], leaf=cluster['leaf'], flagged_by=cluster['flagged_by'], origin={a: cluster['evidence'][a]['origin'] for a in unit_compare.ARMS},
                                options={option['letter']: dict(arms=option_arms) for option, option_arms in
                                         zip(shown, [o['arms'] for _, o in ordered])},
                                arm_option={arm: next((s['letter'] for s, (_, o) in zip(shown, ordered) if arm in o['arms']), None) for arm in unit_compare.ARMS})
    items.sort(key=lambda item: item['id'])
    queue = seal(dict(version=VERSION, variant=variant.key, source_sha256=seed, item_count=len(items), items=items))
    arms_file = seal(dict(version=VERSION, queue_fingerprint=queue['content_fingerprint'], passages=arm_map))
    paths = paths_for(base_dir, variant)
    paths['out'].mkdir(parents=True, exist_ok=True)
    write_json(paths['queue'], queue)
    write_json(paths['versions'], arms_file)
    return dict(queue=str(paths['queue']), variant=variant.key, passages=len(items), with_two_or_more_options=sum(len(i['options']) >= 2 for i in items),
                no_record_anywhere=sum(not i['options'] for i in items))


def render(item: Mapping[str, Any], number: int, total: int) -> str:
    lines = [f"\n[{number}/{total}] {item['watch_url']}\nLEAF {item['leaf']}: {item['leaf_meaning']}\n", item['before'] + '«' + item['text'] + '»' + item['after'], '']
    for option in item['options']:
        lines += [f"OPTION {option['letter']}: {option['summary']}", f"  PROPOSITION: {option['proposition']}",
                  f"  {option['polarity']} | voiced by {option['voiced_by']} | {option['preacher_adoption']} | {option['speech_role']} | qualifications: {option['qualifications'] or '(none)'}",
                  f"  ANCHOR: «{option['anchor']}»", '']
    return '\n'.join(lines or ['(no record from any arm)'])


def _yes_no(prompt: str, input_fn: Callable[[str], str], output_fn: Callable[[str], Any]) -> bool:
    while True:
        said = input_fn(prompt).strip().lower()
        if said in ('y', 'n'):
            return said == 'y'
        output_fn('Answer y or n.')


def judge(base_dir: Path, source: str = 'human', input_fn: Callable[[str], str] = input, output_fn: Callable[[str], Any] = print,
          variant: leaf_evidence.Variant = leaf_evidence.V2) -> dict[str, Any]:
    """Resumable; one item at a time, then options in turn, then the best option when there are two or more."""
    paths = paths_for(base_dir, variant)
    queue = _queue(base_dir, variant)
    while True:
        decided = leaf_review.load_decisions(base_dir, variant, paths)
        todo = [(n, item) for n, item in enumerate(queue['items'], 1) if item['id'] not in decided and item['options']]
        if not todo:
            output_fn('All items are labeled.')
            break
        number, item = todo[0]
        output_fn(render(item, number, queue['item_count']))
        if input_fn('Enter to label, q to quit: ').strip().lower() in ('q', 'quit'):
            break
        labels = {o['letter']: dict(defensible=_yes_no(f"{o['letter']}: defensible (supported by the passage, polarity and voice right, nothing added) (y/n)? ", input_fn, output_fn),
                                    single=_yes_no(f"{o['letter']}: states a single point, not a bundle or a fragment (y/n)? ", input_fn, output_fn)) for o in item['options']}
        best = None
        if len(item['options']) >= 2:
            while best is None:
                said = input_fn(f"Which states the single most defensible point ({'/'.join(o['letter'] for o in item['options'])} / tie / none)? ").strip().upper()
                best = said if said in {o['letter'] for o in item['options']} else said.lower() if said.lower() in ('tie', 'none') else None
        leaf_review.record_decision(base_dir, item['id'], source, variant, paths, options=labels, best=best)
    return progress(base_dir, variant)


def _queue(base_dir: Path, variant: leaf_evidence.Variant) -> dict[str, Any]:
    path = paths_for(base_dir, variant)['queue']
    if not path.exists():
        build_queue(base_dir, variant)
    return leaf_review._sealed(path)


def progress(base_dir: Path, variant: leaf_evidence.Variant = leaf_evidence.V2) -> dict[str, Any]:
    queue, decided = _queue(base_dir, variant), leaf_review.load_decisions(base_dir, variant, paths_for(base_dir, variant))
    todo = [i for i in queue['items'] if i['options']]
    return dict(items=len(todo), decided=sum(i['id'] in decided for i in todo), remaining=sum(i['id'] not in decided for i in todo),
                no_record_anywhere=sum(not i['options'] for i in queue['items']), decisions_file=str(paths_for(base_dir, variant)['decisions']))


def sign_test(wins: int, losses: int) -> float:
    """One-sided exact binomial p-value that wins are at least this many out of the decisive comparisons under a fair coin."""
    n = wins + losses
    return sum(comb(n, k) for k in range(wins, n + 1)) / 2 ** n if n else 1.0


def evaluate(passages: Mapping[str, Any], decided: Mapping[str, Any], total: int) -> dict[str, Any]:
    """Per-arm defensible/single counts, coverage, and the pairwise comparisons of arms S and X with arm B. Pure, so it is testable without artifacts."""
    arm_rows = {arm: dict(records=0, defensible=0, single=0, good=0, good_flagged=0, good_forced=0) for arm in unit_compare.ARMS}
    pairwise = {arm: dict(wins=0, losses=0, ties=0, same_record=0) for arm in ('s', 'x')}
    shared = dict(clusters=0, good={arm: 0 for arm in unit_compare.ARMS})
    for item_id, meta in passages.items():
        label = decided.get(item_id)
        if label is None:
            continue
        options = label['options']
        for arm, letter in meta['arm_option'].items():
            if letter is None:
                continue
            row, answer = arm_rows[arm], options[letter]
            row['records'] += 1
            row['defensible'] += answer['defensible']
            row['single'] += answer['single']
            good = answer['defensible'] and answer['single']
            row['good'] += good
            row['good_' + meta['origin'][arm]] += good
        if all(meta['arm_option'][arm] for arm in unit_compare.ARMS):
            shared['clusters'] += 1
            for arm in unit_compare.ARMS:
                shared['good'][arm] += options[meta['arm_option'][arm]]['defensible'] and options[meta['arm_option'][arm]]['single']
        base = meta['arm_option']['b']
        for arm in ('s', 'x'):
            other = meta['arm_option'][arm]
            if base is None or other is None:
                continue
            if base == other:
                pairwise[arm]['same_record'] += 1
            elif label['best'] == other:
                pairwise[arm]['wins'] += 1
            elif label['best'] == base:
                pairwise[arm]['losses'] += 1
            else:
                pairwise[arm]['ties'] += 1
    verdicts = {}
    for arm in ('s', 'x'):
        row = pairwise[arm]
        decisive = row['wins'] + row['losses']
        p = sign_test(row['wins'], row['losses'])
        better = decisive >= MIN_DECISIVE and row['wins'] > row['losses'] and p <= SIGN_TEST_P and arm_rows[arm]['good'] >= arm_rows['b']['good']
        worse = decisive >= MIN_DECISIVE and row['losses'] > row['wins'] and sign_test(row['losses'], row['wins']) <= SIGN_TEST_P
        verdicts[arm] = dict(decisive=decisive, p_better=round(p, 4), verdict='better than time blocks' if better else 'worse than time blocks' if worse else 'no demonstrated difference',
                             rule=f'at least {MIN_DECISIVE} decisive comparisons, one-sided exact sign test p at most {SIGN_TEST_P}, and good records not fewer than arm B')
    coverage = {arm: round(row['good'] / total, 3) for arm, row in arm_rows.items()}
    return dict(arms=arm_rows, coverage_good_over_passages=coverage, pairwise_against_b=pairwise, shared_passages=shared, verdicts=verdicts)


def report(base_dir: Path, variant: leaf_evidence.Variant = leaf_evidence.V2) -> dict[str, Any]:
    paths = paths_for(base_dir, variant)
    queue, versions = leaf_review._sealed(paths['queue']), leaf_review._sealed(paths['versions'])
    if versions['queue_fingerprint'] != queue['content_fingerprint']:
        raise ValueError('review_arms.json does not belong to this queue; rebuild the queue')
    decided = leaf_review.load_decisions(base_dir, variant, paths)
    labeled = [i for i in queue['items'] if i['options']]
    missing = [i['id'] for i in labeled if i['id'] not in decided]
    if missing:
        raise ValueError(f'{len(missing)} passages are unlabeled; finish the review first')
    outcome = evaluate(versions['passages'], decided, len(queue['items']))
    sources: dict[str, int] = {}
    for item in labeled:
        sources[decided[item['id']]['source']] = sources.get(decided[item['id']]['source'], 0) + 1
    final = dict(version=VERSION, variant=variant.key, passages=len(queue['items']), no_record_anywhere=sum(not i['options'] for i in queue['items']),
                 labels_by=sources, **outcome)
    write_json(paths['report_json'], final)
    lines = [f'# Same-passage unit comparison report (spec section 22, instruction {variant.version})', '',
             f"{final['passages']} passages (every passage any arm flagged); {final['no_record_anywhere']} had no record from any arm. Labels by: {sources} (`human` = Brian's own; any other source is a delegated first pass).", '',
             '| Arm | Records | Defensible | Single point | Both | Both over all passages | Both on own flags / forced |', '| --- | --- | --- | --- | --- | --- | --- |']
    for arm, row in outcome['arms'].items():
        lines.append(f"| {ARM_NAMES[arm]} | {row['records']} | {row['defensible']} | {row['single']} | {row['good']} | {outcome['coverage_good_over_passages'][arm]} | {row['good_flagged']} / {row['good_forced']} |")
    lines += ['', 'Pairwise against time blocks, passages where both arms produced a record:', '', '| Arm | Wins | Losses | Ties | Same record | Decisive | p (better) | Verdict |', '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for arm in ('s', 'x'):
        row, verdict = outcome['pairwise_against_b'][arm], outcome['verdicts'][arm]
        lines.append(f"| {ARM_NAMES[arm]} | {row['wins']} | {row['losses']} | {row['ties']} | {row['same_record']} | {verdict['decisive']} | {verdict['p_better']} | {verdict['verdict']} |")
    lines += ['', f"Passages where all three arms produced a record: {outcome['shared_passages']['clusters']}; good records there: {outcome['shared_passages']['good']}.",
              'One sermon, one set of passages chosen by the arms themselves, one rater; a verdict is for sermon 281 only.', '']
    paths['report_md'].write_text('\n'.join(lines) + '\n')
    return dict(final, report_md=str(paths['report_md']), report_json=str(paths['report_json']))
