"""`pte analysis church-fit`: write FIT.md and fit.json under `<base>/evaluation/church-fit/<concerns version>/`."""
from __future__ import annotations

from pathlib import Path

from ..benchmark_explainer import data, free as explainer_free, render as explainer_render, runner as explainer
from ..bound_claims.common import ensure_outside_repository, read_json, watch_url, write_json
from . import reading

TOP = 10


def run(base_dir: Path, concerns_path: Path) -> Path:
    concerns = read_json(concerns_path)
    out, database, sermons, scored, measured, dimensions, table = explainer._loaded(base_dir)
    unknown = sorted({n for c in concerns['concerns'] for n in [*c['for'], *c.get('against', [])]}
                     - set(dimensions) - set(explainer_free.DIMENSIONS))
    if unknown:
        raise ValueError(f'No scored sermon has {unknown}; a concern would silently read as never found. Score them '
                         'first (Christian nationalism: nationalism-probe, nationalism-add, nationalism-decide --accept)')
    result = reading(concerns, sermons, scored, measured, table)
    target = ensure_outside_repository(out.parent / 'church-fit' / concerns['version'])
    target.mkdir(parents=True, exist_ok=True)
    names = data.pastor_names(database, sorted(result['pastors']))
    details = data.video_details(database, [s['video_id'] for s in sermons])
    write_json(target / 'fit.json', result | dict(concerns=concerns, names=names))
    (target / 'FIT.md').write_text(_markdown(result, concerns, names, details))
    return target / 'FIT.md'


def _link(details, item) -> str:
    detail = details.get(item['video_id'], {})
    return watch_url(detail['url'], item['start_seconds']) if detail.get('url') else ''


def _markdown(result, concerns, names, details) -> str:
    wants = [c for c in concerns['concerns'] if c['kind'] == 'want']
    avoids = [c for c in concerns['concerns'] if c['kind'] == 'avoid']
    pastors = result['pastors']
    lines = [f"# Fit reading: {concerns['church']} ({concerns['version']})", '',
             'Scores are robust z against the pool pastors (0 = typical, clipped to +-3). Breadth is the share of a '
             "pastor's sermons on the want side. Avoid concerns list passages for review; nothing is a verdict or label. "
             'Rules are in `church_fit/__init__.py`.', '',
             '## Ranking on the want concerns', '',
             '| Rank | Pastor | Sermons | Want fit | ' + ' | '.join(c['id'] for c in wants) + ' | Avoid review |',
             '| --- | --- | --- | --- | ' + ' | '.join('---' for _ in wants) + ' | --- |']
    shown = result['ranked'][:TOP] + [p for p in result['ranked'] if p.startswith('b') and p not in result['ranked'][:TOP]]
    for pastor in shown:
        row = pastors[pastor]
        cells = []
        for c in wants:
            w = row['wants'][c['id']]
            cells.append('—' if w['score'] is None else f"{w['score']:+.1f} ({w['breadth']['on_want_side']}/{w['breadth']['sermons']})")
        flagged = [a for a, m in row['avoids'].items() if m['review']]
        lines.append(f"| {row['rank']} | {names[pastor]} | {row['sermons']} | {row['want_fit']:+.2f} | " + ' | '.join(cells)
                     + f" | {', '.join(flagged) or '—'} |")
    lines += ['', 'Cells: concern score (sermons on the want side / sermons).', '',
              '| Concern | Importance | Measures |', '| --- | --- | --- |']
    for c in concerns['concerns']:
        measures = ', '.join(explainer_render.label(m) for m in c['for']) + (
            '; against: ' + ', '.join(explainer_render.label(m) for m in c['against']) if c.get('against') else '')
        lines.append(f"| {c['id']} {c['name']} | {c['importance']} | {measures or c.get('not_yet_measured', '')} |")
    lines += ['', '## Evidence for the top 5', '']
    for pastor in result['ranked'][:5]:
        lines += [f"### {pastors[pastor]['rank']}. {names[pastor]} (want fit {pastors[pastor]['want_fit']:+.2f})", '']
        for c in wants:
            for item in pastors[pastor]['wants'][c['id']]['evidence'][:1]:
                lines += [f"- **{c['id']} {c['name']}**: \"{item['text'][:300]}\" — "
                          f"*{details.get(item['video_id'], {}).get('title', '')}* {_link(details, item)}"]
        lines.append('')
    for c in avoids:
        lines += [f"## Avoid {c['id']}: {c['name']}", '']
        if not c['for']:
            lines += [f"Not yet measured: {c.get('not_yet_measured', '')}", '']
            continue
        flagged = [p for p in result['ranked'] if pastors[p]['avoids'][c['id']]['review']]
        lines += [f"Does not count: {c.get('does_not_count', '')}.",
                  f"Pastors with matches in at least 2 sermons ({len(flagged)} of {len(result['ranked'])}); read before any conclusion.", '']
        for pastor in flagged:
            m = pastors[pastor]['avoids'][c['id']]
            lines.append(f"- **{names[pastor]}**: {m['blocks']} blocks in {m['sermons']} sermons")
            for item in m['passages'][:2]:
                lines.append(f"  - \"{item['text'][:250]}\" {_link(details, item)}")
        lines.append('')
    return '\n'.join(lines)
