"""Brian's judgments against the frozen acceptance (spec section 5) and the report. The record list carries no model identity."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pastor_transcript_extractor.bound_claims.common import read_json, write_json

from . import components, sermon as sermons

JUDGMENTS = 'judgments.json'
RELEVANT_SHARE = 2 / 3


def packet(result: dict[str, Any], sermon: sermons.Sermon) -> str:
    lines = [f"# Object-position check: {result['object']}", '',
             f"{sermon.title}. {len(result['records'])} records, {len(result['anchor_failures'])} anchor failures."
             + (f" **{result['stopped']}**" if result['stopped'] else ''), '', '## Components (frozen) and where they are in the source', '']
    for component, found in zip(components.COMPONENTS, components.located(sermon.text).values()):
        place = '; '.join(f"{sermon.block_at(spans[0][0])[0]} {sermon.link_at(spans[0][0])}" for spans in found if spans)
        lines.append(f"{component['id']}. {component['label']}. Source: {place}")
    lines += ['', '## Records, in source order', '']
    for record in result['records']:
        claim = record['claim']
        lines += [f"### {record['number']}. {record['coordinate']} [{record['watch_url']}]",
                  f"AREA {claim['area']} | POLARITY {claim['polarity']} | VOICE {claim['voiced_by']} | PREACHER {claim['preacher_adoption']} | ROLE {claim['speech_role']}",
                  f"PROPOSITION: {claim['proposition']}"]
        lines += [f"{name.upper()}: " + ('; '.join(claim[name]) or '(none)') for name in ('conditions', 'qualifications', 'reasons')]
        lines += [f"ANCHOR: «{claim['anchor_text']}»", '']
    return '\n'.join(lines)


def _numbers(answer: str, count: int) -> list[int] | None:
    if answer.strip().lower() in ('n', 'none', ''):
        return []
    try:
        values = sorted({int(part) for part in answer.replace(' ', '').split(',')})
    except ValueError:
        return None
    return values if all(1 <= value <= count for value in values) else None


def judge(output: Path, input_fn: Callable[[str], str] = input, output_fn: Callable[[str], Any] = print) -> dict[str, Any]:
    """Resumable: components first (which records state each), then component 1's qualification, then each record."""
    output = Path(output)
    result, path = read_json(output / 'result.json'), output / JUDGMENTS
    count = len(result['records'])
    saved = read_json(path) if path.exists() else dict(components={}, qualified=None, records={})
    output_fn(f"{count} records; answer with record numbers (comma separated) or n.")
    for component in components.COMPONENTS:
        key = str(component['id'])
        while key not in saved['components']:
            answer = input_fn(f"Component {key}: {component['label']}\n  records that state it faithfully: ")
            values = _numbers(answer, count)
            if values is None:
                output_fn('Not understood.')
                continue
            saved['components'][key] = values
            write_json(path, saved)
    while saved['qualified'] is None and saved['components']['1']:
        answer = input_fn('Does a record for component 1 carry the religious-view qualification (y/n)? ').strip().lower()
        if answer in ('y', 'n'):
            saved['qualified'] = answer == 'y'
            write_json(path, saved)
    if saved['qualified'] is None:
        saved['qualified'] = False
        write_json(path, saved)
    for record in result['records']:
        key = str(record['number'])
        while key not in saved['records']:
            claim = record['claim']
            output_fn(f"\n[{key}/{count}] {record['coordinate']}\nPROPOSITION: {claim['proposition']}\nANCHOR: «{claim['anchor_text']}»")
            answer = input_fn('bears on the object (y/n), then problem (flipped, unresolved, wrong speaker or scope) (y/n), e.g. "y n": ').split()
            if len(answer) == 2 and all(part in ('y', 'n') for part in answer):
                saved['records'][key] = dict(relevant=answer[0] == 'y', problem=answer[1] == 'y')
                write_json(path, saved)
            else:
                output_fn('Not understood.')
    return saved


def acceptance(result: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
    records = saved['records']
    relevant = sum(item['relevant'] for item in records.values())
    count = len(result['records'])
    missing = [key for key, values in saved['components'].items() if not values]
    rows = {
        '1': dict(rule='All 7 components present', observed=dict(missing=missing), passed=not missing),
        '2': dict(rule='Component 1 carries the religious-view qualification', observed=saved['qualified'], passed=bool(saved['qualified'])),
        '3': dict(rule='At least two thirds of records bear on the object', observed=dict(relevant=relevant, records=count),
                  passed=count > 0 and relevant / count >= RELEVANT_SHARE),
        '4': dict(rule='No flipped, unresolved or misattributed record', observed=dict(problems=sum(item['problem'] for item in records.values())),
                  passed=sum(item['problem'] for item in records.values()) == 0),
        '5': dict(rule='Every anchor passes the literal check by code', observed=dict(anchor_failures=len(result['anchor_failures'])),
                  passed=not result['anchor_failures'])}
    stopped = result['stopped']
    status = 'FAIL' if stopped or not all(row['passed'] for row in rows.values()) else 'PASS'
    return dict(status=status, stopped=stopped, criteria=rows, judged_records=len(records), records=count)


def report(output: Path) -> dict[str, Any]:
    output = Path(output)
    result, saved = read_json(output / 'result.json'), read_json(output / JUDGMENTS)
    if len(saved['records']) != len(result['records']) or len(saved['components']) != len(components.COMPONENTS):
        raise ValueError('Judgments are incomplete; finish the review first')
    outcome = acceptance(result, saved)
    lines = ['# Object-position check report', '', outcome['status'] + (f" ({outcome['stopped']})" if outcome['stopped'] else ''), '',
             'Exposed development material; one sermon, one object. A pass is not validation or production admission (spec section 6).', '',
             '| # | Rule | Observed | Status |', '| --- | --- | --- | --- |']
    lines += [f"| {key} | {row['rule']} | `{row['observed']}` | **{'PASS' if row['passed'] else 'FAIL'}** |" for key, row in outcome['criteria'].items()]
    write_json(output / 'REPORT.json', outcome)
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    return dict(outcome, report_md=str(output / 'REPORT.md'), report_json=str(output / 'REPORT.json'))
