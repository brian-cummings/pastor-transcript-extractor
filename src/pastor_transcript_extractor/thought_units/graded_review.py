"""Three-level grading of summaries and distinct points (docs/THOUGHT_UNIT_EXPERIMENT.md section 25).

The yes/no questions of the earlier review put accuracy and completeness in one answer. Here a summary is complete, accurate but incomplete (flagged when the omitted
material is the preacher's own objection, ground or condition for the point), or wrong; two records of a pair are distinct, overlapping or the same point twice. Items come from
an existing set queue (`set_review`), widened so the grader sees what the extractor had. Labels are evaluation labels with their source; this module changes no earlier label.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from pastor_transcript_extractor.bound_claims.common import digest, write_json
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal

from . import leaf_evidence, leaf_review, set_review

VERSION = 'graded-review-v1'
SUMMARY_LEVELS = dict(c='complete', a='accurate_incomplete', w='wrong')
DISTINCT_LEVELS = dict(d='distinct', o='overlapping', s='same_point_twice')
ACCURACY_BAR, FLAG_SHARE_LIMIT, SAME_POINT_LIMIT, MIN_MULTI_RECORD_PAIRS = 0.90, 0.15, 0.15, 12      # section 25.1 and 25.2
PILOT_SUMMARIES = 12
QUESTIONS = dict(summary='Level: complete (c), accurate but incomplete (a), wrong (w)? ',
                 flag='Is the omitted material the preacher\'s own objection, ground or condition for the point (y/n)? ',
                 framed='Does the summary state the act of its own leaf as the definition shown describes it (y/n)? ',
                 distinct_points='Are the records distinct (d), overlapping (o) or the same point twice (s)? ')


def graded_paths(base_dir: Path, half: str, name: str = 'graded') -> dict[str, Path]:
    out = set_review.paths_for(base_dir, half)['out']
    return dict(out=out, queue=out / f'{name}-queue.json', decisions=out / f'decisions-{name}.jsonl', report_md=out / f'{name.upper()}_REPORT.md', report_json=out / f'{name.upper()}_REPORT.json')


def pilot_ids(queue: Mapping[str, Any], count: int = PILOT_SUMMARIES) -> list[str]:
    """The first `count` summary items in sha256(item id) order: chosen by rule, before any grade exists."""
    return sorted((i['id'] for i in queue['items'] if i['kind'] == 'summary'), key=digest)[:count]


def build(base_dir: Path, half: str, count: int = PILOT_SUMMARIES, name: str = 'graded') -> dict[str, Any]:
    full_paths = set_review.paths_for(base_dir, half)
    full, versions = leaf_review._sealed(full_paths['queue']), leaf_review._sealed(full_paths['versions'])
    chosen = set(pilot_ids(full, count))
    items = set_review.widen_items(base_dir, half, [dict(i) for i in full['items'] if i['id'] in chosen], versions)
    queue = seal(dict(version=VERSION, half=half, source_sha256=full['content_fingerprint'], item_count=len(items), phase1=0, items=items))
    paths = graded_paths(base_dir, half, name)
    write_json(paths['queue'], queue)
    return dict(queue=str(paths['queue']), items=len(items), decisions=str(paths['decisions']))


def _ask(prompt: str, allowed: Mapping[str, str], input_fn: Callable[[str], str], output_fn: Callable[[str], Any]) -> str:
    while True:
        said = input_fn(prompt).strip().lower()
        if said in allowed:
            return said
        output_fn('Answer one of: ' + ', '.join(allowed) + '.')


def judge(base_dir: Path, half: str, source: str = 'human', input_fn=input, output_fn=print, name: str = 'graded') -> dict[str, Any]:
    paths = graded_paths(base_dir, half, name)
    if not paths['queue'].exists():
        build(base_dir, half, name=name)
    queue = leaf_review._sealed(paths['queue'])
    for number, item in enumerate(queue['items'], 1):
        if item['id'] in leaf_review.load_decisions(base_dir, leaf_evidence.V2, paths):
            continue
        output_fn(leaf_review.render(item, number, queue['item_count']))
        if item['kind'] == 'summary':
            level = _ask(QUESTIONS['summary'], SUMMARY_LEVELS, input_fn, output_fn)
            flag = _ask(QUESTIONS['flag'], dict(y='', n=''), input_fn, output_fn) == 'y' if level == 'a' else False
            framed = _ask(QUESTIONS['framed'], dict(y='', n=''), input_fn, output_fn) == 'y'
            leaf_review.record_decision(base_dir, item['id'], source, leaf_evidence.V2, paths, level=SUMMARY_LEVELS[level], flag=flag, framed=framed)
        else:
            level = _ask(QUESTIONS['distinct_points'], DISTINCT_LEVELS, input_fn, output_fn)
            leaf_review.record_decision(base_dir, item['id'], source, leaf_evidence.V2, paths, level=DISTINCT_LEVELS[level])
    return progress(base_dir, half, name)


def progress(base_dir: Path, half: str, name: str = 'graded') -> dict[str, Any]:
    paths = graded_paths(base_dir, half, name)
    queue, decided = leaf_review._sealed(paths['queue']), leaf_review.load_decisions(base_dir, leaf_evidence.V2, paths)
    return dict(items=queue['item_count'], decided=sum(i['id'] in decided for i in queue['items']), remaining=sum(i['id'] not in decided for i in queue['items']),
                decisions_file=str(paths['decisions']))


def measures(queue: Mapping[str, Any], decided: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Pure: the section 25 counts and readings from graded items. Distinct-points readings are declared only with enough multi-record pairs."""
    summaries = [decided[i['id']] for i in queue['items'] if i['kind'] == 'summary']
    pairs = [decided[i['id']] for i in queue['items'] if i['kind'] == 'distinct_points']
    n = len(summaries)
    count = lambda level: sum(s['level'] == level for s in summaries)
    complete, partial, wrong = count('complete'), count('accurate_incomplete'), count('wrong')
    flagged = sum(s['level'] == 'accurate_incomplete' and s.get('flag') for s in summaries)
    same = sum(p['level'] == 'same_point_twice' for p in pairs)
    share = lambda k, total: (k / total) if total else None
    return dict(
        summaries=n, complete=complete, accurate_incomplete=partial, flagged=flagged, wrong=wrong, framed=sum(bool(s.get('framed')) for s in summaries),
        accuracy=share(complete + partial, n), completeness=share(complete, n), flagged_share=share(flagged, n),
        accuracy_bar_met=bool(n) and (complete + partial) / n + 1e-9 >= ACCURACY_BAR, flag_defect=bool(n) and flagged / n > FLAG_SHARE_LIMIT,
        multi_record_pairs=len(pairs), distinct=sum(p['level'] == 'distinct' for p in pairs), overlapping=sum(p['level'] == 'overlapping' for p in pairs), same_point_twice=same,
        padding_reading=(None if len(pairs) < MIN_MULTI_RECORD_PAIRS else same / len(pairs) <= SAME_POINT_LIMIT + 1e-9),
        padding_reading_note=None if len(pairs) >= MIN_MULTI_RECORD_PAIRS else f'reported only: fewer than {MIN_MULTI_RECORD_PAIRS} multi-record pairs')


def report(base_dir: Path, half: str, name: str = 'graded', compare_with: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """`compare_with` is the earlier yes/no labels by item id (section 24's); the cross-tab shows where the two standards differ."""
    paths = graded_paths(base_dir, half, name)
    queue, decided = leaf_review._sealed(paths['queue']), leaf_review.load_decisions(base_dir, leaf_evidence.V2, paths)
    missing = [i['id'] for i in queue['items'] if i['id'] not in decided]
    if missing:
        raise ValueError(f'{len(missing)} items are unlabeled')
    result = dict(version=VERSION, half=half, **measures(queue, decided), labels_by=sorted({decided[i['id']]['source'] for i in queue['items']}))
    if compare_with is not None:
        table: dict[str, int] = {}
        for item in queue['items']:
            if item['kind'] == 'summary' and item['id'] in compare_with:
                key = f"old {'faithful' if compare_with[item['id']]['answer'] else 'not faithful'} -> new {decided[item['id']]['level']}"
                table[key] = table.get(key, 0) + 1
        result['against_old_yes_no'] = table
    result['defects'] = [dict(item=i['id'], kind=i['kind'], leaf=i['leaf'], level=decided[i['id']]['level'], flag=decided[i['id']].get('flag'), summary=i.get('summary'))
                         for i in queue['items'] if decided[i['id']]['level'] in ('wrong', 'same_point_twice') or decided[i['id']].get('flag')]
    write_json(paths['report_json'], result)
    lines = [f'# Graded review, {half.replace("_", " ")} (section 25)', '', f"{result['summaries']} summaries: complete {result['complete']}, accurate but incomplete {result['accurate_incomplete']} "
             f"(flagged {result['flagged']}), wrong {result['wrong']}; accuracy {result['accuracy']}, completeness {result['completeness']}; leaf framed {result['framed']}.",
             f"Accuracy bar (at least {ACCURACY_BAR:.0%}): {'met' if result['accuracy_bar_met'] else 'not met'}; flagged share limit ({FLAG_SHARE_LIMIT:.0%}): {'exceeded' if result['flag_defect'] else 'ok'}.",
             f"Multi-record pairs {result['multi_record_pairs']}: distinct {result['distinct']}, overlapping {result['overlapping']}, same point twice {result['same_point_twice']}; reading: {result['padding_reading'] if result['padding_reading'] is not None else result['padding_reading_note']}."]
    if compare_with is not None:
        lines += ['', 'Against the old yes/no fidelity (same items): ' + '; '.join(f'{k}: {v}' for k, v in sorted(result['against_old_yes_no'].items()))]
    lines += ['', f'Labels by: {result["labels_by"]}. A pilot, not a test: no verdict, no earlier label changed (section 25).', '']
    paths['report_md'].write_text('\n'.join(lines))
    return dict(result, report_md=str(paths['report_md']), report_json=str(paths['report_json']))
