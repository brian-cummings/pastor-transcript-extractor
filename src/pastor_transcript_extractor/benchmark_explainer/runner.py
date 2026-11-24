"""Steps of the benchmark explainer; outputs under `<base>/evaluation/benchmark-explainer-v1/` (spec section 8).

Free steps: census, sermon-check, sermon-review, explain, review, rank, report. Paid step: score (Jev).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

from ..bound_claims.common import ensure_outside_repository, read_json, write_json
from ..config import build_paths, evaluation_root_for
from ..pastor_fit import corpus
from ..pastor_fit.cleaning import tokens
from ..pastor_fit.experiment import Fingerprints, distances, rank_credit
from ..pastor_fit.fingerprints import counts_from_counters
from . import EXPERIMENT, BENCHMARK_PASTORS, data, free, render, score, values

FLAG_RANK = 5


def _paths(base_dir: Path) -> tuple[Path, Path, Path]:
    paths = build_paths(base_dir)
    evaluation = evaluation_root_for(paths, base_dir)
    return ensure_outside_repository(evaluation / EXPERIMENT), evaluation, paths.database


def _need(path: Path, step: str) -> dict:
    if not path.exists():
        raise ValueError(f'{path.name} is missing; run `pte analysis benchmark-explainer {step}` first')
    return read_json(path)


def census(base_dir: Path) -> dict:
    _, _, database = _paths(base_dir)
    sermons = data.load(database)
    by = Counter(s.pastor for s in sermons)
    return dict(pool_profiles=sum(1 for p in by if p.startswith('p')), pool_sermons=sum(n for p, n in by.items() if p.startswith('p')),
                benchmarks={BENCHMARK_PASTORS[int(p[1:])]: n for p, n in by.items() if p.startswith('b')})


# ---- step 1 and 2: sermon check and free dimensions -------------------------------------------------------------------

def sermon_check(base_dir: Path, echo=print) -> dict:
    out, _, database = _paths(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'sermon_check.json').exists():
        raise ValueError('sermon_check.json already exists; this step runs once')
    sermons = data.as_dicts(data.load(database))
    counters, measured = {}, {}
    for number, sermon in enumerate(sermons, 1):
        text, _ = corpus.window_text(Path(sermon['extraction_path']))
        counters[sermon['video_id']] = Counter(tokens(text))
        measured[str(sermon['video_id'])] = free.measure(Path(sermon['extraction_path']))
        if number % 25 == 0:
            echo(f'{number}/{len(sermons)} sermons read and measured')
    fp = Fingerprints(counts_from_counters(counters), {}, {})
    by_pastor: dict[str, list[int]] = defaultdict(list)
    for sermon in sermons:
        by_pastor[sermon['pastor']].append(sermon['video_id'])
    pool = sorted(p for p in by_pastor if p.startswith('p'))
    details = data.video_details(database, [s['video_id'] for s in sermons if s['pastor'].startswith('b')])
    checks = []
    for sermon in (s for s in sermons if s['pastor'].startswith('b')):
        own = sermon['pastor']
        candidates = pool + [own]
        groups = [fp.style([v for v in by_pastor[c] if v != sermon['video_id']]) for c in candidates]
        dist = distances('style', fp.style([sermon['video_id']]), groups, groups)
        credit = rank_credit(dist[-1], dist[:-1], (FLAG_RANK,))
        nearest = [candidates[i] for i in sorted(range(len(candidates)), key=lambda i: dist[i])[:3]]
        checks.append(dict(video_id=sermon['video_id'], pastor=own, title=details[sermon['video_id']]['title'],
                           url=details[sermon['video_id']]['url'], own_rank=credit['expected_rank'],
                           flagged=credit['expected_rank'] > FLAG_RANK, nearest=nearest))
    write_json(out / 'sermons.json', sermons)
    write_json(out / 'measured.json', measured)
    write_json(out / 'sermon_check.json', dict(flag_rule=f'own benchmark ranked below {FLAG_RANK} of {len(pool) + 1}', checks=checks))
    return dict(sermons=len(sermons), benchmark_sermons=len(checks), flagged=sum(c['flagged'] for c in checks))


def sermon_review(base_dir: Path, ask: Callable[[str], str] = input, echo=print) -> dict:
    out, _, database = _paths(base_dir)
    checks = _need(out / 'sermon_check.json', 'sermon-check')['checks']
    decisions_path = out / 'sermon_decisions.json'
    decisions = read_json(decisions_path) if decisions_path.exists() else {}
    names = data.pastor_names(database, sorted({p for c in checks for p in c['nearest']} | {c['pastor'] for c in checks}))
    for check in checks:
        key = str(check['video_id'])
        if not check['flagged'] or key in decisions:
            continue
        echo(f"\n{names[check['pastor']]}: \"{check['title']}\"\n  {check['url']}\n"
             f"  His own sermons rank {check['own_rank']:.1f} for this sermon's wording; nearest: "
             + ', '.join(names[p] for p in check['nearest']))
        answer = ''
        while answer not in ('k', 'd'):
            answer = ask('  Is this him preaching? k = keep, d = drop: ').strip().lower()
        decisions[key] = 'keep' if answer == 'k' else 'drop'
        write_json(decisions_path, decisions)
    for check in checks:
        decisions.setdefault(str(check['video_id']), 'keep')
    write_json(decisions_path, decisions)
    return dict(kept=sum(v == 'keep' for v in decisions.values()), dropped=sum(v == 'drop' for v in decisions.values()))


def _active_sermons(out: Path) -> list[dict]:
    sermons = _need(out / 'sermons.json', 'sermon-check')
    checks = _need(out / 'sermon_check.json', 'sermon-check')['checks']
    decisions = read_json(out / 'sermon_decisions.json') if (out / 'sermon_decisions.json').exists() else {}
    if any(c['flagged'] and str(c['video_id']) not in decisions for c in checks):
        raise ValueError('Flagged benchmark sermons await your decision: run `pte analysis benchmark-explainer sermon-review`')
    return [s for s in sermons if decisions.get(str(s['video_id']), 'keep') == 'keep']


# ---- step 3: Jev --------------------------------------------------------------------------------------------------------

def run_score(base_dir: Path, *, check_only: bool, echo=print) -> dict:
    out, evaluation, _ = _paths(base_dir)
    sermons = _active_sermons(out)
    if check_only:
        return score.census(out, evaluation, sermons, seed=False)
    from ..bound_claims.extract import git_state
    return score.run(out, evaluation, sermons, state=git_state, echo=echo)


# ---- steps 4 to 9 -------------------------------------------------------------------------------------------------------

def _loaded(base_dir: Path):
    out, _, database = _paths(base_dir)
    _need(out / 'score.json', 'score')
    sermons = _active_sermons(out)
    scored = {s['video_id']: read_json(out / 'signals' / f"v{s['video_id']}.json") for s in sermons}
    measured = {int(k): v for k, v in read_json(out / 'measured.json').items()}
    dimensions = values.jev_dimensions(scored.values())
    table = values.pastor_values(scored, measured, sermons, dimensions)
    return out, database, sermons, scored, measured, dimensions, table


def explain(base_dir: Path) -> Path:
    out, database, sermons, scored, measured, dimensions, table = _loaded(base_dir)
    explanations = {b: values.explain(b, sermons, table, scored, measured, dimensions)
                    for b in sorted(p for p in table if p.startswith('b'))}
    details = data.video_details(database, [s['video_id'] for s in sermons])
    names = data.pastor_names(database, sorted(table))
    write_json(out / 'explain.json', dict(explanations=explanations))
    (out / 'EXPLAINER.md').write_text(render.explainer(explanations, names, details))
    return out / 'EXPLAINER.md'


def review(base_dir: Path, ask: Callable[[str], str] = input, echo=print) -> dict:
    out, _, database = _paths(base_dir)
    explanations = _need(out / 'explain.json', 'explain')['explanations']
    path = out / 'explain_review.json'
    decisions = read_json(path) if path.exists() else {}
    names = data.pastor_names(database, sorted(explanations))
    for benchmark, result in explanations.items():
        for row in result['explained']:
            key = f"{benchmark}/{row['dimension']}"
            if key in decisions:
                continue
            echo('\n' + render.dimension_card(names[benchmark], row))
            answer = ''
            while answer not in ('t', 'n', 'c'):
                answer = ask('  True of him? t = true, n = not true, c = can\'t tell: ').strip().lower()
            decisions[key] = {'t': 'true', 'n': 'not_true', 'c': 'cannot_tell'}[answer]
            write_json(path, decisions)
    return dict(Counter(decisions.values()))


def rank(base_dir: Path, ask: Callable[[str], str] = input, echo=print) -> dict:
    out, database, sermons, scored, measured, dimensions, table = _loaded(base_dir)
    explanations = _need(out / 'explain.json', 'explain')['explanations']
    marks = _need(out / 'explain_review.json', 'review')
    path = out / 'rank_review.json'
    saved = read_json(path) if path.exists() else {}
    by_pastor: dict[str, list[int]] = defaultdict(list)
    for sermon in sermons:
        by_pastor[sermon['pastor']].append(sermon['video_id'])
    names = data.pastor_names(database, sorted(table))
    details = data.video_details(database, [s['video_id'] for s in sermons])
    for benchmark, result in explanations.items():
        if benchmark in saved and saved[benchmark].get('complete'):
            continue
        true_dims = [r['dimension'] for r in result['explained'] if marks.get(f"{benchmark}/{r['dimension']}") == 'true']
        if not true_dims:
            saved[benchmark] = dict(complete=True, chosen=[], shortlist=[], note='no dimension marked true')
            write_json(path, saved)
            continue
        chosen = saved.get(benchmark, {}).get('chosen')
        if not chosen:
            echo(f"\n{names[benchmark]}: dimensions you marked true")
            for i, name in enumerate(true_dims, 1):
                echo(f'  {i}. {render.label(name)}')
            while True:
                picked = ask('  Pick 2 to 5 you would want in a pastor (numbers separated by commas): ')
                try:
                    numbers = sorted({int(x) for x in picked.replace(' ', '').split(',') if x})
                except ValueError:
                    continue
                if 2 <= len(numbers) <= 5 and all(1 <= n <= len(true_dims) for n in numbers) or (len(true_dims) == 1 and numbers == [1]):
                    break
            chosen = [true_dims[n - 1] for n in numbers]
            saved[benchmark] = dict(chosen=chosen, judgments={})
            write_json(path, saved)
        shortlist = values.rank(benchmark, chosen, table, by_pastor, scored, measured)[:values.SHORTLIST]
        saved[benchmark]['shortlist'] = [dict(pastor=r['pastor'], distance=r['distance'], values=r['values']) for r in shortlist]
        for row in shortlist:
            if row['pastor'] in saved[benchmark]['judgments']:
                continue
            echo('\n' + render.shortlist_card(names, benchmark, row, table, details))
            answer = ''
            while answer not in ('s', 'n'):
                answer = ask('  Does the evidence support "similar on these dimensions"? s = supported, n = not: ').strip().lower()
            saved[benchmark]['judgments'][row['pastor']] = 'supported' if answer == 's' else 'not_supported'
            write_json(path, saved)
        saved[benchmark]['complete'] = True
        write_json(path, saved)
    return {b: Counter(v.get('judgments', {}).values()) for b, v in saved.items()}


def report(base_dir: Path) -> Path:
    out, database, sermons, scored, measured, dimensions, table = _loaded(base_dir)
    explanations = _need(out / 'explain.json', 'explain')['explanations']
    marks = _need(out / 'explain_review.json', 'review')
    ranks = _need(out / 'rank_review.json', 'rank')
    stable = sorted({r['dimension'] for e in explanations.values() for r in e['explained']})
    pair = values.pair_distance_percentile('b65', 'b66', stable, table) if stable and {'b65', 'b66'} <= set(table) else None
    result = render.verdicts(explanations, marks, ranks, pair, read_json(out / 'score.json'))
    names = data.pastor_names(database, sorted(table))
    write_json(out / 'REPORT.json', result)
    (out / 'REPORT.md').write_text(render.report(result, names))
    return out / 'REPORT.md'
