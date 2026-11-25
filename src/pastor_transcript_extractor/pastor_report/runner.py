"""`pte analysis pastor-report`: write REPORT.md and report.json under `<base>/evaluation/pastor-report/profile-<id>/`."""
from __future__ import annotations

import json
from pathlib import Path

from ..benchmark_explainer import data, render as explainer_render, runner as explainer
from ..bound_claims.common import ensure_outside_repository, read_json, watch_url, write_json
from ..church_fit import reading
from . import FEW_SERMONS, assemble

SCRIPTURE_KEYS = ('sermons_analyzed', 'total_sermon_words', 'reference_mentions', 'explicit_reference_mentions',
                  'contextual_reference_mentions', 'references_per_1000_words', 'old_testament_mentions',
                  'old_testament_percent', 'new_testament_mentions', 'new_testament_percent', 'top_scripture_books',
                  'repeated_scripture_chapters')


def run(base_dir: Path, profile_id: int, concerns_path: Path | None = None) -> Path:
    out, database, sermons, scored, measured, dimensions, table = explainer._loaded(base_dir)
    pastor = data.canonical_pool(database, [dict(pastor=data.pool_key(profile_id))])[0]['pastor']
    fit = concerns = None
    if concerns_path is not None:
        concerns = read_json(concerns_path)
        fit = reading(concerns, sermons, scored, measured, table)
    report = assemble(pastor, sermons, scored, measured, table, dimensions, fit)
    report['requested_profile_id'] = profile_id
    report['name'] = data.pastor_names(database, [pastor])[pastor]
    report['scripture'] = scripture_summary(database, int(pastor[1:]))
    details = data.video_details(database, report['video_ids'])
    target = ensure_outside_repository(out.parent / 'pastor-report' / f'profile-{pastor[1:]}')
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / 'report.json', report | dict(concerns=concerns, videos=details))
    (target / 'REPORT.md').write_text(markdown(report, concerns, details))
    return target / 'REPORT.md'


def scripture_summary(database_path: Path, profile_id: int) -> dict | None:
    """The latest materialized Scripture summary, or None. Read only; never materializes one."""
    from ..profile_analysis import PROFILE_ANALYZER_KEY
    from ..storage import Database
    database = Database(database_path)
    run = database.get_latest_speaker_profile_analysis_run(profile_id, PROFILE_ANALYZER_KEY)
    if run is None:
        return None
    values = {m.metric_key: json.loads(m.value_json) for m in database.list_speaker_profile_analysis_measurements(run.id)}
    return {k: values.get(k) for k in SCRIPTURE_KEYS} | dict(run_id=run.id)


def _source(details, item) -> str:
    detail = details.get(item['video_id'], {})
    link = watch_url(detail['url'], item['start_seconds']) if detail.get('url') and 'start_seconds' in item else ''
    return f"*{detail.get('title', 'video ' + str(item['video_id']))}* {link}".strip()


def _measure_line(row) -> str:
    name = row['dimension']
    return (f"{explainer_render.show(name, row['value'])} vs typical {explainer_render.show(name, row['pool_median'])}; "
            f"z {row['z']:+.1f} (halves {row['z_halves'][0]:+.1f} / {row['z_halves'][1]:+.1f})"
            if None not in row['z_halves'] else
            f"{explainer_render.show(name, row['value'])} vs typical {explainer_render.show(name, row['pool_median'])}; z {row['z']:+.1f}")


def _pattern_note(breadth, sermons: int) -> str:
    if breadth['pattern']:
        return ''
    if breadth['breadth_ok'] and sermons <= 3:
        return ' (the concentration check cannot pass with 3 or fewer sermons)'
    return ' (not yet a pattern across his sermons)'


def markdown(report, concerns, details) -> str:
    name, n = report['name'], report['sermons']
    lines = [f'# Pastor report: {name}', '',
             f"{n} sermons in the analyzed pool (halves {report['halves'][0]} and {report['halves'][1]}). Built from saved "
             'Jev answers and free measures; no new measurement. A z score compares him with every other pastor '
             '(0 = typical). Nothing here is a verdict or label. Rules: `pastor_report/__init__.py`.', '']
    if report['few_sermons']:
        lines += [f'**Small sample:** fewer than {FEW_SERMONS} sermons. One sermon can drive a trait, and the stability '
                  'check compares very small halves; read the passages before relying on any line.', '']
    lines += ['## Sermons', '']
    for video in report['video_ids']:
        detail = details.get(video, {})
        lines.append(f"- {detail.get('title', 'video ' + str(video))} {detail.get('url', '')}".rstrip())
    lines += ['', '## Distinctive and stable', '']
    if not report['explained']:
        lines += ['No dimension is both distinctive and stable.', '']
    for row in report['explained']:
        b = row['breadth']
        spread = f"on his side of typical in {b['on_his_side']}/{b['sermons']} sermons"
        if b.get('top3_share') is not None:
            spread += f"; top 3 sermons hold {100 * b['top3_share']:.0f}% of the matching blocks"
        lines += [f"### {'More' if row['z'] > 0 else 'Less'}: {explainer_render.label(row['dimension'])}", '',
                  f"{_measure_line(row)}. {spread}{_pattern_note(b, report['sermons'])}.", '']
        meaning = explainer_render.meaning(row['dimension'])
        if meaning:
            lines += [f'Means: {meaning}', '']
        for item in row.get('evidence', []):
            if 'text' in item:
                lines += [f"> \"{item['text'][:500]}\"  \n> — {_source(details, item)}", '']
            else:
                lines.append(f"- {_source(details, item)}: {explainer_render.show(row['dimension'], item['sermon_value'])}")
        lines.append('')
    lines += ['## Other notable measures', '', '| Measure | Direction | Reading | Why not above |', '| --- | --- | --- | --- |']
    for row in report['notable']:
        lines.append(f"| {explainer_render.label(row['dimension'])} | {'more' if row['z'] > 0 else 'less'} | "
                     f"{_measure_line(row)} | {row['why']} |")
    if not report['notable']:
        lines.append('| — | | | |')
    if report['not_enough_evidence']:
        lines += ['', 'Not enough evidence to compare: '
                  + ', '.join(explainer_render.label(d) for d in report['not_enough_evidence'])]
    lines += ['', '## Church fit', '']
    church = report['church_fit']
    if church is None:
        lines += ['Not included; pass `--concerns <church concerns JSON>` to add one church\'s reading.', '']
    elif not church['included']:
        lines += [f"Left out of the {church['version']} ranking (the church-fit rules need at least 3 sermons).", '']
    else:
        row = church['row']
        lines += [f"{concerns['church']} ({church['version']}): rank {row['rank']} of {church['ranked_of']}, "
                  f"want fit {row['want_fit']:+.2f}.", '', '| Concern | Score | Sermons on the want side |', '| --- | --- | --- |']
        names = {c['id']: c['name'] for c in concerns['concerns']}
        for cid, w in row['wants'].items():
            score = '—' if w['score'] is None else f"{w['score']:+.1f}"
            lines.append(f"| {cid} {names[cid]} | {score} | {w['breadth']['on_want_side']}/{w['breadth']['sermons']} |")
        for cid, m in row['avoids'].items():
            lines += ['', f"Avoid {cid} {names[cid]}: {m['blocks']} matching blocks in {m['sermons']} sermons"
                      + (' — listed for passage review.' if m['review'] else '.')]
            for item in m['passages'][:3] if m['review'] else []:
                lines.append(f"- \"{item['text'][:250]}\" — {_source(details, item)}")
        lines.append('')
    lines += ['## Scripture usage', '']
    s = report['scripture']
    if s is None:
        lines += ['No materialized Scripture summary; `pte analysis summarize-profile --profile-id '
                  f"{report['pastor'][1:]}` creates one.", '']
    else:
        lines += [f"{s['reference_mentions']} references in {s['total_sermon_words']:,} words "
                  f"({s['references_per_1000_words']} per 1,000); {s['explicit_reference_mentions']} explicit, "
                  f"{s['contextual_reference_mentions']} contextual. Old Testament {s['old_testament_mentions']} "
                  f"({s['old_testament_percent']}%), New Testament {s['new_testament_mentions']} ({s['new_testament_percent']}%).", '']
        books = [f"{b['book']} {b['mentions']}" for b in (s['top_scripture_books'] or [])[:8] if isinstance(b, dict)]
        if books:
            lines += ['Top books: ' + ', '.join(books) + '.', '']
        chapters = [f"{c['passage']} ({c['sermon_count']} sermons)" for c in (s['repeated_scripture_chapters'] or [])
                    if isinstance(c, dict)]
        if chapters:
            lines += ['Repeated chapters: ' + ', '.join(chapters) + '.', '']
    return '\n'.join(lines)
