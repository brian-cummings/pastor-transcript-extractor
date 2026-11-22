"""Blind review and report for the leaf-evidence test (docs/THOUGHT_UNIT_EXPERIMENT.md sections 17.4 and 17.5).

Phase 1 is blind to prompt version: the 19 baseline records and the new records for the same pairs, shuffled, with only the fields both versions have, plus
a should-there-be-a-record question for any pair where a version returned none. Phase 2 (new records only) starts after phase 1 is complete. Labels are
evaluation labels and never become runtime evidence; each carries its source.
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
from pastor_transcript_extractor.bound_claims.common import digest, read_json, write_json
from pastor_transcript_extractor.bound_claims.review import RECORD_FIELDS, parse_decision
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.object_position import sermon as sermons

from . import arms, leaf_evidence, main_point

VERSION = 'leaf-evidence-review-v1'
WINDOW = 900
DECISIONS = 'decisions.jsonl'
# Acceptance, frozen in spec section 17.5.
SHARE_BAR, MAX_QUALIFICATION_REJECTS, MAX_SAME_SUPPORT = 0.85, 1, 1


V1, V2 = leaf_evidence.V1, leaf_evidence.V2


def _paths(base_dir: Path, variant: leaf_evidence.Variant = V1) -> dict[str, Path]:
    """Version 1 is compared with section 16's arm B records; version 2 is compared with version 1's records (the reference)."""
    out = leaf_evidence.leaf_dir(base_dir, variant)
    v1_out = leaf_evidence.leaf_dir(base_dir, V1)
    reference = (arms.arms_paths(base_dir)['out'] / 'extraction_b.json', arms.arms_paths(base_dir)['ledger'], 'extract_flash/b/') if variant == V1 \
        else (v1_out / 'extraction.json', v1_out / 'ledger.json', 'extract_flash/leaf/')
    return dict(out=out, queue=out / 'review.json', versions=out / 'review_versions.json', decisions=out / DECISIONS, new=out / 'extraction.json',
                baseline=reference[0], arms_ledger=reference[1], reference_prefix=Path(reference[2]), ledger=out / 'ledger.json',
                leaf=arms.arms_paths(base_dir)['leaf'], section17=v1_out / 'LEAF_REPORT.json', report_md=out / 'LEAF_REPORT.md', report_json=out / 'LEAF_REPORT.json')


def _sealed(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f'Missing {path.name}; run the earlier step first')
    value = read_json(path)
    if seal(value) != value:
        raise ValueError(f'{path.name} seal differs')
    return value


def by_pair(result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Each flagged pair of a version: its leaf, unit and its one record (or none)."""
    pairs = {}
    for row in result['rows']:
        if row['status'] != 'ok':
            raise ValueError(f"Pair {row['unit']} {row['leaf']} is {row['status']}; the test needs every pair answered")
        pairs[f"{row['unit']}-{row['leaf'].removeprefix('P:')}"] = dict(unit=row['unit'], leaf=row['leaf'], record=row['claims'][0] if row['claims'] else None)
    return pairs


def build_queue(base_dir: Path, variant: leaf_evidence.Variant = V1) -> dict[str, Any]:
    paths = _paths(base_dir, variant)
    baseline, new = by_pair(_sealed(paths['baseline'])), by_pair(_sealed(paths['new']))
    if set(baseline) != set(new):
        raise ValueError('The two versions do not cover the same pairs')
    sermon, units = sermons.load(paths['leaf'], arms.VIDEO), arms.load_units(base_dir)['units']['b']
    unit_by_id = {unit['id']: unit for unit in units}
    seed = sermon.source_sha256
    phase1, content = [], {}
    for version, found in (('baseline', baseline), ('new', new)):
        for pair, row in sorted(found.items()):
            record = row['record']
            if record is None:
                continue
            claim = record['claim']
            shared = {k: claim[k] for k in RECORD_FIELDS}
            fingerprint = digest(dict(at=record['sermon_start'], leaf=row['leaf'], shared=shared))
            if fingerprint in content:      # indistinguishable records are labeled once
                content[fingerprint]['uses'].append(dict(version=version, pair=pair))
                continue
            content[fingerprint] = item = dict(
                id=fingerprint[:16], kind='record', leaf=row['leaf'], leaf_meaning=main_point.leaf_meaning(row['leaf']), watch_url=sermon.link_at(record['sermon_start']),
                before=sermon.text[max(0, record['sermon_start'] - WINDOW):record['sermon_start']], anchor=sermon.text[record['sermon_start']:record['sermon_end']],
                after=sermon.text[record['sermon_end']:record['sermon_end'] + WINDOW], record=shared, uses=[dict(version=version, pair=pair)])
            phase1.append(item)
    for pair, row in sorted(new.items()):
        if row['record'] is None or baseline[pair]['record'] is None:
            unit = unit_by_id[row['unit']]
            phase1.append(dict(id=digest(dict(none=pair))[:16], kind='none', pair=pair, leaf=row['leaf'], leaf_meaning=main_point.leaf_meaning(row['leaf']),
                               watch_url=sermon.link_at(unit['start']), unit_text=unit['text'], uses=[dict(version=v, pair=pair) for v, f in
                                                                                                     (('baseline', baseline), ('new', new)) if f[pair]['record'] is None]))
    phase2 = []
    for pair, row in sorted(new.items()):
        if row['record'] is not None:
            record = row['record']
            phase2.append(dict(id=digest(dict(summary=pair))[:16], kind='summary', pair=pair, leaf=row['leaf'], leaf_meaning=main_point.leaf_meaning(row['leaf']),
                               watch_url=sermon.link_at(record['sermon_start']), unit_text=unit_by_id[row['unit']]['text'], summary=record['summary'],
                               target=record['target'], proposition=record['claim']['proposition'], **(dict(asks_framing=True) if variant == V2 else {})))
    per_unit: dict[str, list[str]] = {}
    for pair, row in sorted(new.items()):
        if row['record'] is not None:
            per_unit.setdefault(row['unit'], []).append(pair)
    for unit_id, members in sorted(per_unit.items()):
        if len(members) == 2 and variant == V1:   # version 2 drops the difference question (17.10: it penalised legitimate overlap)
            phase2.append(dict(id=digest(dict(distinct=members))[:16], kind='distinct', pairs=members, unit_text=unit_by_id[unit_id]['text'],
                               records=[dict(leaf=new[m]['leaf'], summary=new[m]['record']['summary']) for m in members]))
    random.Random(f'{seed}:leaf-review:1').shuffle(phase1)
    random.Random(f'{seed}:leaf-review:2').shuffle(phase2)
    items = [*phase1, *phase2]
    visible = [{k: v for k, v in item.items() if k not in ('uses', 'pair', 'pairs')} for item in items]
    queue = seal(dict(version=VERSION, source_sha256=seed, item_count=len(items), phase1=len(phase1), items=visible))
    versions = seal(dict(version=VERSION, queue_fingerprint=queue['content_fingerprint'], baseline_pairs={p: bool(r['record']) for p, r in baseline.items()},
                         new_pairs={p: bool(r['record']) for p, r in new.items()}, items={item['id']: {k: item[k] for k in ('kind', 'uses', 'pair', 'pairs') if k in item}
                                                                                             for item in items}))
    write_json(paths['queue'], queue)
    write_json(paths['versions'], versions)
    return dict(queue=str(paths['queue']), variant=variant.key, items=len(items), phase1=len(phase1), phase2=len(phase2), pairs=len(new),
                baseline_records=sum(bool(r['record']) for r in baseline.values()), new_records=sum(bool(r['record']) for r in new.values()))


def _queue(base_dir: Path, variant: leaf_evidence.Variant = V1) -> dict[str, Any]:
    path = _paths(base_dir, variant)['queue']
    if not path.exists():
        build_queue(base_dir, variant)
    return _sealed(path)


def load_decisions(base_dir: Path, variant: leaf_evidence.Variant = V1) -> dict[str, dict[str, Any]]:
    path, latest = _paths(base_dir, variant)['decisions'], {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                if record.get('void'):
                    latest.pop(record['item'], None)
                else:
                    latest[record['item']] = record
    return latest


def record_decision(base_dir: Path, item: str, source: str, variant: leaf_evidence.Variant = V1, **judged: Any) -> dict[str, Any]:
    if 'decision' in judged and parse_decision(judged['decision']) != judged['decision']:
        raise ValueError(f"Unknown decision: {judged['decision']}")
    record = dict(item=item, source=source, decided_at=datetime.now(timezone.utc).isoformat(), **judged)
    with _paths(base_dir, variant)['decisions'].open('a') as stream:
        stream.write(json.dumps(record, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    return record


def render(item: Mapping[str, Any], number: int, total: int) -> str:
    head = f"\n[{number}/{total}] {item.get('watch_url', '')}\nLEAF {item.get('leaf', '')}: {item.get('leaf_meaning', '')}\n"
    if item['kind'] == 'record':
        record = item['record']
        lines = [head, item['before'] + '«' + item['anchor'] + '»' + item['after'], '', f"PROPOSITION: {record['proposition']}",
                 f"POLARITY: {record['polarity']}    VOICED BY: {record['voiced_by']}    PREACHER: {record['preacher_adoption']}    ROLE: {record['speech_role']}"]
        lines += [name.upper() + ': ' + ('; '.join(record[name]) or '(none)') for name in ('conditions', 'qualifications', 'reasons')]
        return '\n'.join(lines + ['ANCHOR: «' + record['anchor_text'] + '»'])
    if item['kind'] == 'none':
        return head + 'UNIT: ' + item['unit_text']
    if item['kind'] == 'summary':
        return head + 'UNIT: ' + item['unit_text'] + f"\n\nSUMMARY: {item['summary']}\nTARGET: {item['target']}\nPROPOSITION: {item['proposition']}"
    return '\n[distinct]\nUNIT: ' + item['unit_text'] + '\n' + '\n'.join(f"{r['leaf']}: {r['summary']}" for r in item['records'])


def _yes_no(prompt: str, input_fn: Callable[[str], str], output_fn: Callable[[str], Any]) -> bool:
    while True:
        said = input_fn(prompt).strip().lower()
        if said in ('y', 'n'):
            return said == 'y'
        output_fn('Answer y or n.')


QUESTIONS = dict(none='Should this unit have a record for the leaf (y/n)? ',
                 summary='Is the summary faithful to the thought (nothing added, no material qualification or reason omitted), in the leaf\'s terms, with an accurate target (y/n)? ',
                 distinct='Do the two summaries state different supports for their leaves (y/n)? ',
                 framed='Does the summary state the act of its own leaf as the definition shown describes it (y/n)? ')
RECORD_PROMPT = ('accept (a) / reject (r) / reject:<field> where field is ' + ', '.join(bound.REJECTION_FIELDS) + ' / undo last (u) / quit (q): ')


def judge(base_dir: Path, source: str = 'human', input_fn: Callable[[str], str] = input, output_fn: Callable[[str], Any] = print,
          variant: leaf_evidence.Variant = V1) -> dict[str, Any]:
    """Resumable. Phase 2 items are not shown until every phase 1 item is labeled, so the blind pass stays blind."""
    queue, last = _queue(base_dir, variant), None
    while True:
        decided = load_decisions(base_dir, variant)
        todo = [(n, item) for n, item in enumerate(queue['items'], 1) if item['id'] not in decided]
        phase1_left = [(n, item) for n, item in todo if n <= queue['phase1']]
        todo = phase1_left or todo
        if not todo:
            output_fn('All items are labeled.')
            break
        number, item = todo[0]
        output_fn(render(item, number, queue['item_count']))
        if item['kind'] == 'record':
            answer = input_fn(RECORD_PROMPT).strip().lower()
            if answer in ('q', 'quit'):
                break
            if answer in ('u', 'undo'):
                if last is None:
                    output_fn('Nothing to undo in this session.')
                else:
                    record_decision(base_dir, last, source, variant, void=True)
                    last = None
                continue
            decision = parse_decision(answer)
            if decision is None:
                output_fn('Not understood.')
                continue
            fit = _yes_no('Does what the record states fit the leaf definition shown (y/n)? ', input_fn, output_fn)
            record_decision(base_dir, item['id'], source, variant, decision=decision, fit=fit)
        else:
            answer = _yes_no(QUESTIONS[item['kind']], input_fn, output_fn)
            extra = dict(framed=_yes_no(QUESTIONS['framed'], input_fn, output_fn)) if item.get('asks_framing') else {}
            record_decision(base_dir, item['id'], source, variant, answer=answer, **extra)
        last = item['id']
    return progress(base_dir, variant)


def progress(base_dir: Path, variant: leaf_evidence.Variant = V1) -> dict[str, Any]:
    queue, decided = _queue(base_dir, variant), load_decisions(base_dir, variant)
    return dict(items=queue['item_count'], decided=sum(item['id'] in decided for item in queue['items']),
                remaining=sum(item['id'] not in decided for item in queue['items']), decisions_file=str(_paths(base_dir, variant)['decisions']))


def _spend(ledger: Mapping[str, Any], prefix: str) -> Decimal:
    return sum((Decimal(e['actual_usd'] if e['status'] == 'resolved' else e['reserved_usd']) for k, e in ledger['entries'].items() if k.startswith(prefix)), Decimal(0))


def evaluate(measures: Mapping[str, Any], variant: leaf_evidence.Variant = V1) -> dict[str, Any]:
    """L1 to L4 from per-version measures. Pure, so it can be tested without any artifacts.

    Version 1 (spec 17.5) compares with section 16's records and asks that two-leaf units differ. Version 2 (spec 18.4) adds an adoption and polarity
    check to L1, compares leaf fit with the section 16 baseline carried in `reference_pairs_correct`, and replaces the difference bar with leaf framing.
    """
    new, base = measures['new'], measures['baseline']
    records, pairs = new['records'], measures['pairs']
    share = lambda count, total: (count / total) if total else 0.0
    l1_share = share(new['accepted'], records)
    new_rate = share(new['pairs_correct'], pairs)
    if variant == V1:
        base_rate = share(base['pairs_correct'], pairs)
        l1 = dict(rule=f'at least {SHARE_BAR:.0%} of new records accepted, at most {MAX_QUALIFICATION_REJECTS} qualification reject',
                  observed=dict(accepted=new['accepted'], records=records, qualification_rejects=new['qualification_rejects']),
                  passed=records > 0 and l1_share + 1e-9 >= SHARE_BAR and new['qualification_rejects'] <= MAX_QUALIFICATION_REJECTS)
        l4 = dict(rule=f'at most {MAX_SAME_SUPPORT} two-leaf unit with the same support under both leaves',
                  observed=dict(same_support=measures['same_support'], two_leaf_units=measures['two_leaf_units']), passed=measures['same_support'] <= MAX_SAME_SUPPORT)
    else:
        base_rate = share(measures['reference_pairs_correct'], pairs)
        l1 = dict(rule=f'at least {SHARE_BAR:.0%} of new records accepted, at most {MAX_QUALIFICATION_REJECTS} qualification reject and at most {MAX_QUALIFICATION_REJECTS} adoption or polarity reject',
                  observed=dict(accepted=new['accepted'], records=records, qualification_rejects=new['qualification_rejects'],
                                adoption_or_polarity_rejects=new['adoption_polarity_rejects']),
                  passed=(records > 0 and l1_share + 1e-9 >= SHARE_BAR and new['qualification_rejects'] <= MAX_QUALIFICATION_REJECTS
                          and new['adoption_polarity_rejects'] <= MAX_QUALIFICATION_REJECTS))
        l4 = dict(rule=f'at least {SHARE_BAR:.0%} of new summaries state the act of their own leaf',
                  observed=dict(framed=new['framed_ok'], records=records), passed=records > 0 and share(new['framed_ok'], records) + 1e-9 >= SHARE_BAR)
    rows = dict(
        L1=l1,
        L2=dict(rule=f'at least {SHARE_BAR:.0%} of pairs correct on leaf fit and no lower than the section 16 baseline' if variant == V2
                else f'at least {SHARE_BAR:.0%} of pairs correct on leaf fit and no lower than the baseline',
                observed=dict(new=new['pairs_correct'], baseline=measures['reference_pairs_correct'] if variant == V2 else base['pairs_correct'], pairs=pairs),
                passed=new_rate + 1e-9 >= SHARE_BAR and new_rate + 1e-9 >= base_rate),
        L3=dict(rule=f'at least {SHARE_BAR:.0%} of new records have a {"faithful, complete summary with an accurate target" if variant == V2 else "faithful, leaf-framed, complete summary with an accurate target"}',
                observed=dict(summaries_ok=new['summaries_ok'], records=records), passed=records > 0 and share(new['summaries_ok'], records) + 1e-9 >= SHARE_BAR),
        L4=l4)
    return dict(criteria=rows, passed=all(row['passed'] for row in rows.values()))


def report(base_dir: Path, variant: leaf_evidence.Variant = V1) -> dict[str, Any]:
    paths = _paths(base_dir, variant)
    queue, versions, decided = _queue(base_dir, variant), _sealed(paths['versions']), load_decisions(base_dir, variant)
    if versions['queue_fingerprint'] != queue['content_fingerprint']:
        raise ValueError('review_versions.json does not belong to this queue; rebuild the queue')
    missing = [item['id'] for item in queue['items'] if item['id'] not in decided]
    if missing:
        raise ValueError(f'{len(missing)} items are unlabeled; finish the review first')
    baseline, new = by_pair(_sealed(paths['baseline'])), by_pair(_sealed(paths['new']))
    tally = {v: dict(records=0, accepted=0, qualification_rejects=0, adoption_polarity_rejects=0, pairs_correct=0, rejects={}) for v in ('baseline', 'new')}
    for item_id, meta in versions['items'].items():
        label = decided[item_id]
        for use in meta.get('uses', []):
            row = tally[use['version']]
            if meta['kind'] == 'record':
                row['records'] += 1
                row['accepted'] += label['decision'] == 'accept'
                row['qualification_rejects'] += label['decision'] == 'reject:qualifications'
                row['adoption_polarity_rejects'] += label['decision'] in ('reject:adoption', 'reject:polarity')
                row['pairs_correct'] += bool(label['fit'])
                if label['decision'] != 'accept':
                    row['rejects'][label['decision']] = row['rejects'].get(label['decision'], 0) + 1
            else:        # a pair with no record is correct when the grader says it should not have one
                row['pairs_correct'] += not label['answer']
    summaries = [decided[i]['answer'] for i, m in versions['items'].items() if m['kind'] == 'summary']
    tally['new']['summaries_ok'] = sum(bool(a) for a in summaries)
    measures = dict(pairs=len(new), new=tally['new'], baseline=tally['baseline'])
    if variant == V2:
        tally['new']['framed_ok'] = sum(bool(decided[i]['framed']) for i, m in versions['items'].items() if m['kind'] == 'summary')
        if not paths['section17'].exists():
            raise ValueError('Version 2 compares leaf fit with the section 16 baseline recorded in the section 17 report; run that report first')
        measures['reference_pairs_correct'] = read_json(paths['section17'])['tally']['baseline']['pairs_correct']
        distinct = []
    else:
        distinct = [decided[i]['answer'] for i, m in versions['items'].items() if m['kind'] == 'distinct']
        measures.update(two_leaf_units=len(distinct), same_support=sum(not a for a in distinct))
    outcome = evaluate(measures, variant)
    sources: dict[str, int] = {}
    for item in queue['items']:
        sources[decided[item['id']]['source']] = sources.get(decided[item['id']]['source'], 0) + 1
    reference_ledger, leaf_ledger = read_json(paths['arms_ledger']), read_json(paths['ledger'])
    cost = dict(baseline=str(_spend(reference_ledger, str(paths['reference_prefix']))), new=str(_spend(leaf_ledger, 'extract_flash/leaf/')))
    paired = dict(both_accepted=0, new_only=0, baseline_only=0, neither=0)
    for pair in new:
        status = {}
        for version, found in (('baseline', baseline), ('new', new)):
            record = found[pair]['record']
            item = next((i for i, m in versions['items'].items() if m['kind'] == 'record' and dict(version=version, pair=pair) in m['uses']), None)
            status[version] = bool(record) and decided[item]['decision'] == 'accept'
        paired['both_accepted' if status['baseline'] and status['new'] else 'new_only' if status['new'] else 'baseline_only' if status['baseline'] else 'neither'] += 1
    final = dict(version=VERSION, variant=variant.key, instruction_version=variant.version, passed=outcome['passed'], criteria=outcome['criteria'], labels_by=sources,
                 tally=tally, paired_accepted=paired, cost_usd=cost, reference=('section 16 arm B records' if variant == V1 else 'leaf-evidence v1 records'),
                 two_leaf_units=len(distinct), no_record_pairs=dict(baseline=sum(not r['record'] for r in baseline.values()), new=sum(not r['record'] for r in new.values())))
    write_json(paths['report_json'], final)
    lines = [f'# Leaf-evidence test report ({"spec section 17" if variant == V1 else "spec section 18, version 2"})', '', f"**{'PASS' if outcome['passed'] else 'FAIL'}**", '',
             'Exposed development material; one sermon, arm B\'s 19 pairs. A pass is engineering evidence, not validation or production admission.',
             f"Labels by: {sources} (`human` = Brian's own; any other source is a delegated first pass, not Brian's judgment).", '',
             '| Criterion | Rule | Observed | Result |', '| --- | --- | --- | --- |']
    lines += [f"| {key} | {row['rule']} | `{row['observed']}` | {'PASS' if row['passed'] else 'FAIL'} |" for key, row in outcome['criteria'].items()]
    lines += ['', f"Paired accepted counts against the {final['reference']} on the same pairs: `{paired}`. Cost (not a bar): reference ${cost['baseline']}, new ${cost['new']}. "
              f"No-record pairs: reference {final['no_record_pairs']['baseline']}, new {final['no_record_pairs']['new']}.", '']
    paths['report_md'].write_text('\n'.join(lines) + '\n')
    return dict(final, report_md=str(paths['report_md']), report_json=str(paths['report_json']))
