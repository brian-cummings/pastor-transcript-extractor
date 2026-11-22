"""Blind review and report for the downstream comparison (docs/THOUGHT_UNIT_EXPERIMENT.md section 16.3 and 16.4).

One shuffled queue holds up to 30 sampled records per arm plus every record that sits on a frozen component span; the queue never says which
arm a record came from (that lives in review_arms.json, read only by the report). A record found by more than one arm is labeled once.
Brian's labels are evaluation labels and never become runtime evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import random
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.bound_claims import contract as bound
from pastor_transcript_extractor.bound_claims.common import file_sha256, pilot_dir, read_json, write_json
from pastor_transcript_extractor.bound_claims.review import RECORD_FIELDS, parse_decision
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.object_position import components, sermon as sermons

from . import arms

VERSION = 'thought-unit-arms-review-v1'
SAMPLE = 30
WINDOW = 900
DECISIONS = 'decisions.jsonl'
PILOT_RECORDS = 319
EPSILON = 1e-9
# Acceptance, frozen in spec section 16.4.
A2_ALLOWANCE, A3_GAIN, A4_COST_RATIO, REFERENCE_SHARE = 0.10, 0.10, 1.5, 0.80


def _paths(base_dir: Path) -> dict[str, Path]:
    paths = arms.arms_paths(base_dir)
    return dict(paths, queue=paths['out'] / 'review.json', arms_map=paths['out'] / 'review_arms.json', decisions=paths['out'] / DECISIONS,
                report_md=paths['out'] / 'ARMS_REPORT.md', report_json=paths['out'] / 'ARMS_REPORT.json')


def load_extractions(base_dir: Path) -> dict[str, dict[str, Any]]:
    loaded = {}
    for arm in arms.ARMS:
        path = arms.arms_paths(base_dir)['out'] / f'extraction_{arm}.json'
        if not path.exists():
            raise ValueError(f'Extract every arm before review; missing {path.name}')
        result = read_json(path)
        if seal(result) != result:
            raise ValueError(f'{path.name} seal differs')
        loaded[arm] = result
    return loaded


def arm_records(extraction: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    records = {}
    for row in extraction['rows']:
        for item in row['claims']:
            records[item['key']] = dict(item, unit=row['unit'], leaf=row['leaf'])
    return records


def component_candidates(sermon: sermons.Sermon, start: int, end: int) -> list[int]:
    """Frozen components whose located source span the record's anchor overlaps (code; Brian then judges each)."""
    found = []
    for number, spans in components.located(sermon.text).items():
        if any(a < end and b > start for per_span in spans for a, b in per_span):
            found.append(number)
    return found


def build_queue(base_dir: Path) -> dict[str, Any]:
    paths, sermon = _paths(base_dir), sermons.load(arms.arms_paths(base_dir)['leaf'], arms.VIDEO)
    extractions = load_extractions(base_dir)
    records = {arm: arm_records(extractions[arm]) for arm in arms.ARMS}
    seed = sermon.source_sha256
    sampled = {}
    for arm, found in records.items():
        keys = sorted(found)
        random.Random(f'{seed}:arms-review:{arm}').shuffle(keys)
        sampled[arm] = keys[:SAMPLE]
    by_key: dict[str, dict[str, Any]] = {}
    for arm in arms.ARMS:
        for key, item in records[arm].items():
            by_key.setdefault(key, dict(item=item, arms=[], sampled_in=[]))['arms'].append(arm)
    for arm, keys in sampled.items():
        for key in keys:
            by_key[key]['sampled_in'].append(arm)
    items = []
    for key, entry in sorted(by_key.items()):
        item = entry['item']
        needed = component_candidates(sermon, item['sermon_start'], item['sermon_end'])
        entry['components'] = needed
        if not (entry['sampled_in'] or needed):
            continue
        claim = item['claim']
        items.append(dict(id=key, watch_url=sermon.link_at(item['sermon_start']),
                          before=sermon.text[max(0, item['sermon_start'] - WINDOW):item['sermon_start']], anchor=sermon.text[item['sermon_start']:item['sermon_end']],
                          after=sermon.text[item['sermon_end']:item['sermon_end'] + WINDOW], record={k: claim[k] for k in RECORD_FIELDS}, components=needed))
    random.Random(f'{seed}:arms-review:queue').shuffle(items)
    queue = seal(dict(version=VERSION, source_sha256=seed, item_count=len(items),
                      decisions=['accept', 'reject', *('reject:' + field for field in bound.REJECTION_FIELDS)], items=items))
    keep = {item['id'] for item in items}
    mapping = seal(dict(version=VERSION, queue_fingerprint=queue['content_fingerprint'],
                        records={key: dict(arms=entry['arms'], sampled_in=entry['sampled_in'], components=entry['components'])
                                 for key, entry in by_key.items() if key in keep},
                        arm_records={arm: sorted(found) for arm, found in records.items()}, sampled=sampled,
                        units={key: dict(unit=entry['item']['unit'], arms=entry['arms']) for key, entry in by_key.items() if key in keep}))
    write_json(paths['queue'], queue)
    write_json(paths['arms_map'], mapping)
    return dict(queue=str(paths['queue']), items=len(items), sampled={arm: len(keys) for arm, keys in sampled.items()},
                records={arm: len(found) for arm, found in records.items()}, component_records=sum(bool(i['components']) for i in items),
                shared_across_arms=sum(len(entry['arms']) > 1 for entry in by_key.values() if entry['sampled_in'] or entry['components']))


def _queue(base_dir: Path) -> dict[str, Any]:
    path = _paths(base_dir)['queue']
    if not path.exists():
        build_queue(base_dir)
    queue = read_json(path)
    if seal(queue) != queue:
        raise ValueError('review.json seal differs')
    return queue


def load_decisions(base_dir: Path) -> dict[str, dict[str, Any]]:
    path, latest = _paths(base_dir)['decisions'], {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                if record['decision'] == 'void':
                    latest.pop(record['item'], None)
                else:
                    latest[record['item']] = record
    return latest


def record_decision(base_dir: Path, item: str, decision: str, judged: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if decision != 'void' and parse_decision(decision) != decision:
        raise ValueError(f'Unknown decision: {decision}')
    record = dict(item=item, decision=decision, decided_at=datetime.now(timezone.utc).isoformat(), **(judged or {}))
    with _paths(base_dir)['decisions'].open('a') as stream:
        stream.write(json.dumps(record, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    return record


def render(item: Mapping[str, Any], number: int, total: int) -> str:
    record = item['record']
    lines = [f"\n[{number}/{total}] {item['watch_url']}", '', item['before'] + '«' + item['anchor'] + '»' + item['after'], '',
             f"AREA: {record['area']}    OBJECT: {record['object']}", f"PROPOSITION: {record['proposition']}",
             f"POLARITY: {record['polarity']}    VOICED BY: {record['voiced_by']}    PREACHER: {record['preacher_adoption']}    ROLE: {record['speech_role']}"]
    for name in ('conditions', 'qualifications', 'reasons'):
        lines.append(name.upper() + ': ' + ('; '.join(record[name]) if record[name] else '(none)'))
    lines.append('ANCHOR: «' + record['anchor_text'] + '»')
    return '\n'.join(lines)


PROMPT = ('accept (a) / reject (r) / reject:<field> where field is ' + ', '.join(bound.REJECTION_FIELDS) + ' / undo last (u) / quit (q): ')


def interactive(base_dir: Path, input_fn: Callable[[str], str] = input, output_fn: Callable[[str], Any] = print) -> dict[str, Any]:
    """Resumable. After the accept or reject, each frozen component the record sits on gets a faithful (y/n), and component 1 a qualification (y/n)."""
    queue, last = _queue(base_dir), None
    labels = {number: component['label'] for number, component in ((c['id'], c) for c in components.COMPONENTS)}
    while True:
        decided = load_decisions(base_dir)
        todo = [(number, item) for number, item in enumerate(queue['items'], 1) if item['id'] not in decided]
        if not todo:
            output_fn('All records are labeled.')
            break
        number, item = todo[0]
        output_fn(render(item, number, queue['item_count']))
        answer = input_fn(PROMPT).strip().lower()
        if answer in ('q', 'quit'):
            break
        if answer in ('u', 'undo'):
            if last is None:
                output_fn('Nothing to undo in this session.')
            else:
                record_decision(base_dir, last, 'void')
                last = None
            continue
        decision = parse_decision(answer)
        if decision is None:
            output_fn('Not understood.')
            continue
        judged: dict[str, Any] = dict(components={}, qualified=None)
        for component in item['components']:
            while str(component) not in judged['components']:
                said = input_fn(f'Component {component} ({labels[component]}): does this record state it faithfully (y/n)? ').strip().lower()
                if said in ('y', 'n'):
                    judged['components'][str(component)] = said == 'y'
            while component == 1 and judged['components']['1'] and judged['qualified'] is None:
                said = input_fn('Does it carry the religious-view qualification (y/n)? ').strip().lower()
                if said in ('y', 'n'):
                    judged['qualified'] = said == 'y'
        record_decision(base_dir, item['id'], decision, judged)
        last = item['id']
    return progress(base_dir)


def progress(base_dir: Path) -> dict[str, Any]:
    queue, decided = _queue(base_dir), load_decisions(base_dir)
    return dict(items=queue['item_count'], decided=sum(item['id'] in decided for item in queue['items']),
                remaining=sum(item['id'] not in decided for item in queue['items']), decisions_file=str(_paths(base_dir)['decisions']))


# ---- report ----------------------------------------------------------------------------------------------------------------

def _spend(ledger: Mapping[str, Any], prefix: str) -> tuple[Decimal, int]:
    """Known actual spend, else the reservation, of every entry under the prefix; the second value counts entries without known usage."""
    total, unknown = Decimal(0), 0
    for key, entry in ledger['entries'].items():
        if key.startswith(prefix):
            known = entry['status'] == 'resolved'
            total += Decimal(entry['actual_usd'] if known else entry['reserved_usd'])
            unknown += not known
    return total, unknown


def _percentile_rank(value: float, values: Sequence[float]) -> float:
    return round(sum(v <= value for v in values) / len(values), 4)


def evaluate(measures: Mapping[str, Any]) -> dict[str, Any]:
    """The frozen acceptance A1 to A4 and the decision, from per-arm measures. Pure so it can be tested without any artifacts."""
    arm = measures['arms']
    share = {name: arm[name]['accepted_share'] or 0.0 for name in arms.ARMS}
    kept = {name: (len(arm[name]['components_present']), int(arm[name]['qualification_attached'])) for name in arms.ARMS}
    cost = {name: arm[name]['cost_per_accepted_usd'] for name in arms.ARMS}
    a1 = bool(measures['a1']['passed'])
    a2_parts = dict(share=share['s'] >= share['b'] - A2_ALLOWANCE - EPSILON, components=kept['s'][0] >= kept['b'][0],
                    qualification=kept['s'][1] >= kept['b'][1])
    a3_parts = dict(share=share['x'] >= share['s'] + A3_GAIN - EPSILON, components=kept['x'][0] >= kept['s'][0],
                    qualification=kept['x'][1] >= kept['s'][1])
    a4 = cost['x'] is not None and cost['s'] is not None and cost['x'] <= A4_COST_RATIO * cost['s'] + EPSILON
    a2, a3 = all(a2_parts.values()), all(a3_parts.values())
    decision = ('stopped: A1 failed' if not a1 else 'time blocks stay' if not a2 else 'X (snapped edges with splitting)' if a3 and a4
                else 'S (snapped edges, no splitting)')
    return dict(A1=dict(passed=a1), A2=dict(passed=a1 and a2, parts=a2_parts), A3=dict(passed=a1 and a3, parts=a3_parts),
                A4=dict(passed=a1 and a4, cost_per_accepted_usd=cost, ratio=None if not (cost['x'] and cost['s']) else round(cost['x'] / cost['s'], 4)),
                decision=decision)


def report(base_dir: Path) -> dict[str, Any]:
    paths = _paths(base_dir)
    queue, mapping, decided = _queue(base_dir), read_json(paths['arms_map']), load_decisions(base_dir)
    if seal(mapping) != mapping or mapping['queue_fingerprint'] != queue['content_fingerprint']:
        raise ValueError('review_arms.json does not belong to this queue; rebuild the queue')
    missing = [item['id'] for item in queue['items'] if item['id'] not in decided]
    if missing:
        raise ValueError(f'{len(missing)} records are unlabeled; finish the review first')
    units, extractions = read_json(paths['units']), load_extractions(base_dir)
    sermon = sermons.load(paths['leaf'], arms.VIDEO)
    ledger, pilot = read_json(paths['ledger']), read_json(pilot_dir(base_dir) / 'ledger.json')
    spans = components.located(sermon.text)
    per_arm: dict[str, Any] = {}
    for name in arms.ARMS:
        found = mapping['arm_records'][name]
        sample = mapping['sampled'][name]
        accepts = sum(decided[key]['decision'] == 'accept' for key in sample)
        present, qualified = set(), False
        for key in found:
            judged = decided.get(key)
            if judged:
                present |= {int(k) for k, ok in judged['components'].items() if ok}
                qualified |= bool(judged['components'].get('1')) and bool(judged.get('qualified'))
        spend = {'snap': _spend(ledger, 'leaf/snap/')[0] if name != 'b' else Decimal(0),
                 'assess': _spend(ledger, f'leaf/{name}/')[0] if name != 'b' else _spend(pilot, f'leaf/{arms.VIDEO}/')[0],
                 'extract': _spend(ledger, f'extract_flash/{name}/')[0]}
        unknown = (_spend(ledger, f'extract_flash/{name}/')[1] + _spend(ledger, f'leaf/{name}/')[1] + (_spend(ledger, 'leaf/snap/')[1] if name != 'b' else 0))
        total = sum(spend.values(), Decimal(0))
        records = len(found)
        share = accepts / len(sample) if sample else None
        accepted_estimate = (share or 0.0) * records
        signals = arms.signals_by_unit(base_dir, name)
        topic = [row[arms.FLAG_TOPIC] for row in signals.values()]
        holding = {}
        for number, per_span in spans.items():
            at = per_span[0][0][0]
            unit = next(u for u in units['units'][name] if u['start'] <= at < u['end'])
            holding[str(number)] = dict(unit=unit['id'], topic_percentile=_percentile_rank(signals[unit['id']][arms.FLAG_TOPIC], topic),
                                        unit_holds_components_1_and_4=all(unit['start'] <= spans[k][0][0][0] < unit['end'] for k in (1, 4)))
        rejects = [decided[key]['decision'] for key in sample]
        per_arm[name] = dict(units=len(units['units'][name]), pairs=extractions[name]['summary']['pairs'], records=records, sampled=len(sample),
                             accepted=accepts, accepted_share=None if share is None else round(share, 4),
                             components_present=sorted(present), qualification_attached=qualified,
                             cost_usd={k: str(v) for k, v in spend.items()} | dict(total=str(total)), cost_with_unknown_usage_entries=unknown,
                             cost_per_accepted_usd=float(total / Decimal(str(accepted_estimate))) if accepted_estimate else None,
                             rejects=dict(total=sum(r != 'accept' for r in rejects), qualifications_or_conditions=sum(r in ('reject:qualifications', 'reject:conditions') for r in rejects)),
                             routing=holding, stopped=extractions[name]['stopped'])
    measures = dict(a1=units['summary']['a1'], arms=per_arm)
    outcome = evaluate(measures)
    best = max(per_arm, key=lambda n: per_arm[n]['accepted_share'] or 0.0)
    sources: dict[str, int] = {}
    for item in queue['items']:
        label = decided[item['id']].get('source', 'human')
        sources[label] = sources.get(label, 0) + 1
    final = dict(version=VERSION, decision=outcome['decision'], acceptance=outcome, arms=per_arm, labels_by=sources, units_summary=units['summary'],
                 reference=dict(best_arm=best, best_accepted_share=per_arm[best]['accepted_share'], reaches_reference=(per_arm[best]['accepted_share'] or 0) >= REFERENCE_SHARE,
                                reference_share=REFERENCE_SHARE, note='reported, not a bar; no production admission'),
                 pilot_records_all_sermons=PILOT_RECORDS, queue_items=queue['item_count'], ledger_attempts=len(ledger['entries']))
    write_json(paths['report_json'], final)
    lines = ['# Downstream comparison report (spec section 16)', '', f"**Decision: {outcome['decision']}**", '',
             'Exposed development material; one sermon. A pass is engineering evidence about unit shape, not validation or production admission.',
             f"Labels by: {sources} (`human` = Brian's own; any other source is a delegated first pass, not Brian's judgment).", '',
             '| Criterion | Rule | Observed | Result |', '| --- | --- | --- | --- |',
             f"| A1 | snapped arms keep all text once, no mid-sentence cuts, every unit mapped | `{units['summary']['a1']}` | {'PASS' if outcome['A1']['passed'] else 'FAIL'} |",
             f"| A2 | S accepted share not more than {A2_ALLOWANCE} below B; components and qualification no worse | `{outcome['A2']['parts']}` | {'PASS' if outcome['A2']['passed'] else 'FAIL'} |",
             f"| A3 | X accepted share at least {A3_GAIN} above S; components and qualification no worse | `{outcome['A3']['parts']}` | {'PASS' if outcome['A3']['passed'] else 'FAIL'} |",
             f"| A4 | X cost per accepted record at most {A4_COST_RATIO} times S | `{outcome['A4']['cost_per_accepted_usd']}` ratio {outcome['A4']['ratio']} | {'PASS' if outcome['A4']['passed'] else 'FAIL'} |",
             '', '| Arm | Units | Pairs | Records | Labeled | Accepted | Share | Components | Qualified | Cost USD | Cost per accepted |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for name, row in per_arm.items():
        lines.append(f"| {name.upper()} | {row['units']} | {row['pairs']} | {row['records']} | {row['sampled']} | {row['accepted']} | {row['accepted_share']} | "
                     f"{len(row['components_present'])} of 7 {row['components_present']} | {row['qualification_attached']} | {row['cost_usd']['total']} | {row['cost_per_accepted_usd']} |")
    lines += ['', f"Reference (not a bar): best arm {best} accepted share {per_arm[best]['accepted_share']} against {REFERENCE_SHARE}. Pilot volume across all sermons was {PILOT_RECORDS} records.", '']
    paths['report_md'].write_text('\n'.join(lines) + '\n')
    return dict(final, report_md=str(paths['report_md']), report_json=str(paths['report_json']))
