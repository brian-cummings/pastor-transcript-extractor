"""Steps of the benchmark explainer; outputs under `<base>/evaluation/benchmark-explainer-v1/` (spec section 8).

Free steps: census, sermon-check, add-sermons, add-pool, sermon-review, explain, review, rank, report.
Paid steps: score and score-added (Jev).
"""
from __future__ import annotations

import re
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
    excluded: list = []
    sermons = data.load(database, excluded)
    by = Counter(s.pastor for s in sermons)
    return dict(excluded_without_sermon_window=excluded, pool_profiles=sum(1 for p in by if p.startswith('p')), pool_sermons=sum(n for p, n in by.items() if p.startswith('p')),
                benchmarks={BENCHMARK_PASTORS[int(p[1:])]: n for p, n in by.items() if p.startswith('b')})


# ---- step 1 and 2: sermon check and free dimensions -------------------------------------------------------------------

def _measure(sermon: dict) -> dict:
    try:
        return free.measure(Path(sermon['extraction_path']))
    except (ValueError, KeyError, TypeError) as error:   # free dimensions only: the sermon stays in, its values are missing
        return {name: None for name in free.DIMENSIONS} | {'error': f'{type(error).__name__}: {error}'}


def _checks(sermons: list[dict], targets: list[dict], database: Path, echo=print) -> list[dict]:
    """Stylometric sermon check (spec step 1) for `targets`, each against its benchmark's other sermons and the pool."""
    counters = {}
    for number, sermon in enumerate(sermons, 1):
        text, _ = corpus.window_text(Path(sermon['extraction_path']))
        counters[sermon['video_id']] = Counter(tokens(text))
        if number % 50 == 0:
            echo(f'{number}/{len(sermons)} sermons read')
    fp = Fingerprints(counts_from_counters(counters), {}, {})
    by_pastor: dict[str, list[int]] = defaultdict(list)
    for sermon in sermons:
        by_pastor[sermon['pastor']].append(sermon['video_id'])
    pool = sorted(p for p in by_pastor if p.startswith('p'))
    details = data.video_details(database, [s['video_id'] for s in targets])
    checks = []
    for sermon in targets:
        own = sermon['pastor']
        candidates = pool + [own]
        groups = [fp.style([v for v in by_pastor[c] if v != sermon['video_id']]) for c in candidates]
        dist = distances('style', fp.style([sermon['video_id']]), groups, groups)
        credit = rank_credit(dist[-1], dist[:-1], (FLAG_RANK,))
        nearest = [candidates[i] for i in sorted(range(len(candidates)), key=lambda i: dist[i])[:3]]
        checks.append(dict(video_id=sermon['video_id'], pastor=own, title=details[sermon['video_id']]['title'],
                           url=details[sermon['video_id']]['url'], own_rank=credit['expected_rank'],
                           flagged=credit['expected_rank'] > FLAG_RANK, nearest=nearest))
    return checks


def sermon_check(base_dir: Path, echo=print) -> dict:
    out, _, database = _paths(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'sermon_check.json').exists():
        raise ValueError('sermon_check.json already exists; this step runs once (use add-sermons for new recordings)')
    excluded: list = []
    sermons = data.as_dicts(data.load(database, excluded))
    measured = {str(s['video_id']): _measure(s) for s in sermons}
    checks = _checks(sermons, [s for s in sermons if s['pastor'].startswith('b')], database, echo)
    write_json(out / 'sermons.json', sermons)
    write_json(out / 'measured.json', measured)
    write_json(out / 'sermon_check.json', dict(flag_rule=f'own benchmark ranked below {FLAG_RANK} of {len(set(s["pastor"] for s in sermons if s["pastor"].startswith("p"))) + 1}',
                                               checks=checks, excluded_without_sermon_window=excluded))
    return dict(sermons=len(sermons), benchmark_sermons=len(checks), flagged=sum(c['flagged'] for c in checks),
                excluded_without_sermon_window=[e['video_id'] for e in excluded])


def add_sermons(base_dir: Path, echo=print) -> dict:
    """Add benchmark recordings that gained an extraction since sermon-check (free): measure them, run the sermon
    check on them, and append them. The pool is unchanged. New recordings are then reviewed with
    `sermon-review --all` and scored with `score-added`."""
    out, _, database = _paths(base_dir)
    sermons = _need(out / 'sermons.json', 'sermon-check')
    check_file = _need(out / 'sermon_check.json', 'sermon-check')
    known = {s['video_id'] for s in sermons} | {e['video_id'] for e in check_file.get('excluded_without_sermon_window', [])}
    excluded: list = []
    current = data.as_dicts(data.load(database, excluded))
    pool_now = {s['video_id'] for s in current if s['pastor'].startswith('p')}
    pool_before = {s['video_id'] for s in sermons if s['pastor'].startswith('p')}
    if pool_now - pool_before:
        raise ValueError(f'{len(pool_now - pool_before)} analyzed pool sermons are not in the explainer yet; '
                         'run `pte analysis benchmark-explainer add-pool` first')
    added = [s for s in current if s['pastor'].startswith('b') and s['video_id'] not in known]
    new_excluded = [e for e in excluded if e['video_id'] not in known]
    if not added:
        if new_excluded:
            check_file.setdefault('excluded_without_sermon_window', []).extend(new_excluded)
            write_json(out / 'sermon_check.json', check_file)
        return dict(added=[], excluded_without_sermon_window=[e['video_id'] for e in new_excluded])
    measured = read_json(out / 'measured.json')
    for sermon in added:
        measured[str(sermon['video_id'])] = _measure(sermon)
    # Reference groups use the reviewed sets (drops and re-filings applied), so a new recording is compared with him.
    checks = _checks(_active_sermons(out) + added, added, database, echo)
    check_file['checks'].extend(checks)
    check_file.setdefault('excluded_without_sermon_window', []).extend(new_excluded)
    write_json(out / 'measured.json', measured)
    write_json(out / 'sermon_check.json', check_file)
    write_json(out / 'sermons.json', sermons + added)
    return dict(added=[dict(video_id=c['video_id'], benchmark=c['pastor'], title=c['title'], flagged=c['flagged']) for c in checks],
                excluded_without_sermon_window=[e['video_id'] for e in new_excluded],
                next='pte analysis benchmark-explainer sermon-review --all, then score-added')


USD_PER_BLOCK = 8.52 / 12_090   # section 11: the approved score run


def _usd_per_minute(out: Path, sermons: list[dict], measured: dict) -> float:
    """Jev dollars per sermon minute, from the blocks already scored (spec section 11's block price)."""
    blocks = minutes = 0.0
    for sermon in sermons:
        path = out / 'signals' / f"v{sermon['video_id']}.json"
        length = (measured.get(str(sermon['video_id'])) or {}).get('F:sermon_minutes')
        if path.exists() and length:
            blocks += len(read_json(path).get('blocks', []))
            minutes += length
    return USD_PER_BLOCK * blocks / minutes if minutes else USD_PER_BLOCK


def add_pool(base_dir: Path, *, include_unnamed: bool = False, echo=print) -> dict:
    """Free: add pool sermons that profile analysis has and the explainer lacks (after `pte analysis backfill`):
    new sermons of pool pastors, and the sermons of newly analyzed named profiles (unnamed ones only with
    `include_unnamed`). Measures them and appends them; `score-added` then scores them. A sermon already in the
    explainer is never re-filed: if one now resolves to a different pastor, the step refuses."""
    out, _, database = _paths(base_dir)
    sermons = _need(out / 'sermons.json', 'sermon-check')
    known = {s['video_id'] for s in sermons}
    before = {s['video_id']: s['pastor'] for s in data.canonical_pool(database, [s for s in sermons if s['pastor'].startswith('p')])}
    current = data.canonical_pool(database, [s for s in data.as_dicts(data.load(database)) if s['pastor'].startswith('p')])
    moved = sorted(s['video_id'] for s in current if s['video_id'] in before and before[s['video_id']] != s['pastor'])
    if moved:
        raise ValueError(f'{len(moved)} explainer sermons now belong to a different profile ({moved[:5]}); '
                         'resolve the profile change before adding to the pool')
    in_pool = set(before.values())
    new = [s for s in current if s['video_id'] not in known]
    names = data.pastor_names(database, sorted({s['pastor'] for s in new}))
    skipped = Counter(s['pastor'] for s in new
                      if s['pastor'] not in in_pool and not include_unnamed and names[s['pastor']].startswith('profile '))
    added = [s for s in new if s['pastor'] not in skipped]
    retired = sorted(set(before) - {s['video_id'] for s in current})
    if added:
        measured = read_json(out / 'measured.json')
        for number, sermon in enumerate(added, 1):
            measured[str(sermon['video_id'])] = _measure(sermon)
            if number % 25 == 0:
                echo(f'{number}/{len(added)} sermons measured')
        write_json(out / 'measured.json', measured)
        write_json(out / 'sermons.json', sermons + added)
    else:
        measured = read_json(out / 'measured.json')
    minutes = sum((measured.get(str(s['video_id'])) or {}).get('F:sermon_minutes') or 0 for s in added)
    by_pastor = Counter(s['pastor'] for s in added)
    return dict(
        added_sermons=len(added),
        new_pastors={names[p]: n for p, n in sorted(by_pastor.items()) if p not in in_pool},
        pool_pastors_with_new_sermons={names[p]: n for p, n in sorted(by_pastor.items()) if p in in_pool},
        skipped_unnamed_profiles={p: n for p, n in sorted(skipped.items())},
        no_longer_in_profile_analysis=len(retired),
        sermon_minutes=round(minutes),
        estimated_jev_usd=round(minutes * _usd_per_minute(out, sermons, measured), 2),
        next='pte analysis benchmark-explainer score-added --ceiling-usd <about 1.5 x the estimate>')


_BRACKET = re.compile(r'\[([^\]]+)\]')


def propose(title: str, benchmark_name: str) -> tuple[str, str]:
    """Proposed keep or drop for a benchmark recording, from the speakers its title names in brackets."""
    surname = benchmark_name.split()[-1].lower()
    match = _BRACKET.search(title or '')
    if not match:
        return 'keep', "the title doesn't name a speaker"
    names = [name.strip() for name in match.group(1).split(',') if name.strip()]
    if len(names) == 1 and surname in names[0].lower():
        return 'keep', 'the title names him alone'
    if any(surname in name.lower() for name in names):
        return 'drop', f'the title names him with others ({match.group(1)})'
    return 'drop', f'the title names someone else ({match.group(1)})'


def sermon_review(base_dir: Path, ask: Callable[[str], str] = input, echo=print, all_recordings: bool = False,
                  open_url: Callable[[str], object] | None = None) -> dict:
    """Keep or drop benchmark recordings: the flagged ones, or with `all_recordings` every one, each with a proposal
    from its title (Enter accepts the proposal). Undecided recordings are kept."""
    out, _, database = _paths(base_dir)
    checks = _need(out / 'sermon_check.json', 'sermon-check')['checks']
    decisions_path = out / 'sermon_decisions.json'
    decisions = read_json(decisions_path) if decisions_path.exists() else {}
    names = data.pastor_names(database, sorted({p for c in checks for p in c['nearest']} | {c['pastor'] for c in checks}))
    for check in checks:
        key = str(check['video_id'])
        if not (check['flagged'] or all_recordings) or key in decisions:
            continue
        proposal, reason = propose(check['title'], names[check['pastor']])
        echo(f"\nVideo {key}: \"{check['title']}\"\n  {check['url']}\n"
             f"  Filed under: {names[check['pastor']]}\n"
             f"  PROPOSED: {proposal.upper()} ({reason})")
        if open_url is not None:
            open_url(check['url'])
        answer = None
        while answer not in ('k', 'd'):
            answer = ask(f"  Is this {names[check['pastor']]} preaching alone? Enter = {proposal}, k = keep, d = drop: ").strip().lower() or proposal[0]
        decisions[key] = 'keep' if answer == 'k' else 'drop'
        write_json(decisions_path, decisions)
    write_json(decisions_path, decisions)
    final = [decisions.get(str(c['video_id']), 'keep') for c in checks]
    return dict(kept=final.count('keep'), dropped=final.count('drop'),
                dropped_videos=sorted(int(k) for k, v in decisions.items() if v == 'drop'))


def _parse_decision(decision: str) -> str:
    if decision in ('keep', 'drop'):
        return decision
    if decision.startswith('file:') and decision[5:].isdigit() and int(decision[5:]) in BENCHMARK_PASTORS:
        return decision
    raise ValueError(f'decision must be keep, drop or file:<benchmark pastor id> ({", ".join(map(str, BENCHMARK_PASTORS))}); got {decision!r}')


def sermon_decide(base_dir: Path, video_ids: list[int], decision: str) -> dict:
    """Record one decision for several benchmark recordings without the interactive review: keep, drop, or
    `file:<pastor id>` to count a recording as the other benchmark's (a sermon filed under the wrong channel)."""
    out, _, _ = _paths(base_dir)
    decision = _parse_decision(decision)
    checks = {str(c['video_id']): c for c in _need(out / 'sermon_check.json', 'sermon-check')['checks']}
    unknown = [v for v in video_ids if str(v) not in checks]
    if unknown:
        raise ValueError(f'not benchmark recordings: {unknown}')
    path = out / 'sermon_decisions.json'
    decisions = read_json(path) if path.exists() else {}
    for video in video_ids:
        decisions[str(video)] = decision
    write_json(path, decisions)
    return dict(Counter(decisions.get(key, 'keep') for key in checks))


def _active_sermons(out: Path) -> list[dict]:
    """Kept benchmark recordings, with any `file:<pastor id>` decision applied to the recording's benchmark."""
    sermons = _need(out / 'sermons.json', 'sermon-check')
    checks = _need(out / 'sermon_check.json', 'sermon-check')['checks']
    decisions = read_json(out / 'sermon_decisions.json') if (out / 'sermon_decisions.json').exists() else {}
    if any(c['flagged'] and str(c['video_id']) not in decisions for c in checks):
        raise ValueError('Flagged benchmark sermons await your decision: run `pte analysis benchmark-explainer sermon-review`')
    active = []
    for sermon in sermons:
        decision = _parse_decision(decisions.get(str(sermon['video_id']), 'keep'))
        if decision == 'drop':
            continue
        if decision.startswith('file:'):
            sermon = dict(sermon, pastor=data.benchmark_key(int(decision[5:])))
        active.append(sermon)
    return active


# ---- step 3: Jev --------------------------------------------------------------------------------------------------------

def run_score(base_dir: Path, *, check_only: bool, echo=print) -> dict:
    out, evaluation, _ = _paths(base_dir)
    sermons = _active_sermons(out)
    if check_only:
        return score.census(out, evaluation, sermons, seed=False)
    from ..bound_claims.extract import git_state
    return score.run(out, evaluation, sermons, state=git_state, echo=echo)


# ---- steps 4 to 9 -------------------------------------------------------------------------------------------------------

def run_score_added(base_dir: Path, *, ceiling_usd: str, check_only: bool = False, echo=print) -> dict:
    """A separately capped Jev round for kept sermons that have no signals yet (recordings from add-sermons)."""
    out, evaluation, _ = _paths(base_dir)
    _need(out / 'score.json', 'score')
    missing = [s for s in _active_sermons(out) if not (out / 'signals' / f"v{s['video_id']}.json").exists()]
    if not missing:
        raise ValueError('Every kept sermon is already scored; nothing to add')
    if check_only:
        return score.census(out, evaluation, missing, seed=False) | dict(ceiling_usd=ceiling_usd)
    from decimal import Decimal
    from ..bound_claims.extract import git_state
    return score.run_round(out, evaluation, missing, ceiling_usd=Decimal(ceiling_usd), state=git_state, echo=echo)


def _loaded(base_dir: Path):
    out, _, database = _paths(base_dir)
    _need(out / 'score.json', 'score')
    sermons = data.canonical_pool(database, _active_sermons(out))
    unscored = [s['video_id'] for s in sermons if not (out / 'signals' / f"v{s['video_id']}.json").exists()]
    if unscored:
        raise ValueError(f'{len(unscored)} kept sermons are not scored yet ({unscored[:5]}...): run '
                         '`pte analysis benchmark-explainer score-added`, or drop them with sermon-decide')
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


def check_traits(base_dir: Path) -> Path:
    """Free: breadth of each explained dimension across his sermons, plus up to 6 top passages per MORE dimension
    (one per sermon) for the content check. Writes trait_checks.json and TRAIT_CHECKS.md."""
    out, database, sermons, scored, measured, dimensions, table = _loaded(base_dir)
    explanations = _need(out / 'explain.json', 'explain')['explanations']
    names = data.pastor_names(database, sorted(table))
    by_pastor: dict[str, list[int]] = defaultdict(list)
    for sermon in sermons:
        by_pastor[sermon['pastor']].append(sermon['video_id'])
    result = {}
    for benchmark, explained in explanations.items():
        rows = []
        for row in explained['explained']:
            item = dict(dimension=row['dimension'], z=row['z'], value=row['value'], pool_median=row['pool_median'],
                        **values.breadth(row, by_pastor[benchmark], scored, measured))
            if row['z'] > 0 and row['dimension'] not in free.DIMENSIONS:
                item['passages'] = values.evidence(row['dimension'], by_pastor[benchmark], scored, measured, limit=6)
            rows.append(item)
        result[benchmark] = rows
    details = data.video_details(database, [s['video_id'] for s in sermons if s['pastor'].startswith('b')])
    write_json(out / 'trait_checks.json', dict(breadth_min_share=values.BREADTH_MIN_SHARE,
                                               concentration_max=values.CONCENTRATION_MAX, benchmarks=result))
    (out / 'TRAIT_CHECKS.md').write_text(render.trait_checks(result, names, details))
    return out / 'TRAIT_CHECKS.md'


def review(base_dir: Path, ask: Callable[[str], str] = input, echo=print,
           open_url: Callable[[str], object] | None = None) -> dict:
    """Mark each explained dimension; with `open_url`, each evidence passage opens on YouTube at its start."""
    from ..bound_claims.common import watch_url
    out, _, database = _paths(base_dir)
    explanations = _need(out / 'explain.json', 'explain')['explanations']
    path = out / 'explain_review.json'
    decisions = read_json(path) if path.exists() else {}
    names = data.pastor_names(database, sorted(explanations))
    details = data.video_details(database, sorted({item['video_id'] for result in explanations.values()
                                                   for row in result['explained'] for item in row.get('evidence', [])}))
    for benchmark, result in explanations.items():
        for row in result['explained']:
            key = f"{benchmark}/{row['dimension']}"
            if key in decisions:
                continue
            echo('\n' + render.dimension_card(names[benchmark], row, details))
            if open_url is not None:
                for item in row.get('evidence', []):
                    if 'text' in item and details.get(item['video_id'], {}).get('url'):
                        open_url(watch_url(details[item['video_id']]['url'], item['start_seconds']))
            answer = ''
            while answer not in ('t', 'n', 'c'):
                answer = ask('  True of him? t = true, n = not true, c = can\'t tell: ').strip().lower()
            decisions[key] = {'t': 'true', 'n': 'not_true', 'c': 'cannot_tell'}[answer]
            write_json(path, decisions)
    return dict(Counter(decisions.values()))


def rank(base_dir: Path, ask: Callable[[str], str] = input, echo=print,
         open_url: Callable[[str], object] | None = None) -> dict:
    """Pick dimensions per benchmark, then judge the shortlist; with `open_url`, each shortlist example opens on YouTube."""
    from ..bound_claims.common import watch_url
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
            rows = {r['dimension']: r for r in result['explained']}
            for i, name in enumerate(true_dims, 1):
                echo(f'  {i}. {render.pick_line(rows[name])}')
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
            if open_url is not None:
                for items in row['evidence'].values():
                    for item in items:
                        if 'text' in item and details.get(item['video_id'], {}).get('url'):
                            open_url(watch_url(details[item['video_id']]['url'], item['start_seconds']))
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
