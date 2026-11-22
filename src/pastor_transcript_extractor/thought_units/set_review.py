"""Blind review and report for the new public-life set (docs/THOUGHT_UNIT_EXPERIMENT.md sections 19.3 and 20).

One queue per half. It mixes every version run on that half so the grader cannot tell which version wrote a record (identical records are labeled once),
shows record items and no-record items first and summary items only after those are done, and keeps the version map in a separate file. The labeling loop
and the decision log are `leaf_review`'s; only the queue, the sample and the report differ. Labels are evaluation labels, never runtime evidence.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import random
from typing import Any, Mapping

from pastor_transcript_extractor.bound_claims.common import digest, read_json, write_json
from pastor_transcript_extractor.bound_claims.review import RECORD_FIELDS
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal

from . import leaf_evidence, leaf_review, main_point, public_set

VERSION = 'set-review-v1'
WINDOW = leaf_review.WINDOW
HELD_OUT_SAMPLE = 30                    # section 19.5: the first 30 held-out pairs in sha256(pair key) order; development is graded whole
VARIANTS_BY_HALF = dict(development=('v2',), held_out=('v2', 'v3'), development_top3=('v3', 'v4'), held_out_top3=('v3', 'v4'), confirm_top3=('v3', 'v4'))
PRIMARY = dict(development='v2', held_out='v3', development_top3='v4', held_out_top3='v4', confirm_top3='v4')      # the version whose bars are tested; the other is its reference
# Section 23 halves read the three-leaf pairs; they were seen while the design was chosen, so their reports are exploratory and carry no pass or fail.
VERDICT_HALVES = ('held_out',)
CONFIRM_HALVES = ('confirm_top3',)      # section 24: unused sermons, readings fixed in advance, a verdict
CONFIRM_SAMPLE = 60                      # section 24.5: every pair is graded up to 60; the first 60 by hash of the pair key when the set has more


def review_dir(base_dir: Path, half: str) -> Path:
    return public_set.set_dir(base_dir, leaf_evidence.SCOPES[half].set_id) / f"leaf-review-{half.replace('_', '-')}"


def paths_for(base_dir: Path, half: str) -> dict[str, Path]:
    out = review_dir(base_dir, half)
    return dict(out=out, queue=out / 'review.json', versions=out / 'review_versions.json', decisions=out / leaf_review.DECISIONS,
                report_md=out / 'SET_REPORT.md', report_json=out / 'SET_REPORT.json')


def reviewed_pairs(base_dir: Path, half: str) -> list[dict[str, Any]]:
    """Development: every pair. Held-out: the fixed sample, chosen by the hash of the pair key alone."""
    scope = leaf_evidence.SCOPES[half]
    pairs = leaf_evidence.pair_inputs(base_dir, scope)
    if (scope.half or scope.key) == 'development':
        return pairs
    if half in CONFIRM_HALVES:
        return pairs if len(pairs) <= CONFIRM_SAMPLE else sorted(pairs, key=lambda p: digest(p['key']))[:CONFIRM_SAMPLE]
    return sorted(pairs, key=lambda p: digest(p['key']))[:HELD_OUT_SAMPLE]


def by_key(base_dir: Path, half: str, variant: leaf_evidence.Variant) -> dict[str, Any]:
    """A version's records (none, one, or several) for each pair of the half; every pair must be answered."""
    scope = leaf_evidence.SCOPES[half]
    path = leaf_evidence.leaf_dir(base_dir, variant, scope) / 'extraction.json'
    result = leaf_review._sealed(path)
    pairs = leaf_evidence.pair_inputs(base_dir, scope)
    if len(result['rows']) != len(pairs):
        raise ValueError(f'{variant.key} answered {len(result["rows"])} of {len(pairs)} pairs; the run stopped or is incomplete')
    found = {}
    for pair, row in zip(pairs, result['rows']):
        if (row['unit'], row['leaf']) != (pair['unit'], pair['leaf']):
            raise ValueError(f"{path.name} rows do not line up with the pairs at {pair['key']}")
        if row['status'] == 'schema_failure':        # the version broke its own output contract on this pair: no record, counted as a miss and reported, never graded as 'none'
            found[pair['key']] = None
            continue
        if row['status'] != 'ok':
            raise ValueError(f"Pair {pair['key']} is {row['status']} for {variant.key}; the test needs every pair answered")
        found[pair['key']] = list(row['claims'])
    return found


def build_queue(base_dir: Path, half: str, variants: tuple[str, ...] | None = None, wide: bool = False) -> dict[str, Any]:
    keys = variants or VARIANTS_BY_HALF[half]
    pairs = {p['key']: p for p in reviewed_pairs(base_dir, half)}
    found = {key: by_key(base_dir, half, leaf_evidence.VARIANTS[key]) for key in keys}
    texts: dict[int, Any] = {}
    sermon_of = lambda video: texts[video] if video in texts else texts.setdefault(video, public_set.load_sermon(base_dir, video, leaf_evidence.SCOPES[half].set_id))      # once per sermon: setdefault alone would load it on every call
    seed = digest(dict(half=half, pairs=sorted(pairs), variants=list(keys)))
    phase1, phase2, records, summaries, distinct = [], [], {}, {}, {}
    for variant in keys:
        for key, claims in sorted(found[variant].items()):
            if key not in pairs or claims is None:
                continue
            pair, sermon = pairs[key], sermon_of(pairs[key]['video_id'])
            for index, record in enumerate(claims):
                use = dict(version=variant, pair=key, index=index)
                shared = {k: record['claim'][k] for k in RECORD_FIELDS}
                fingerprint = digest(dict(at=record['sermon_start'], leaf=pair['leaf'], shared=shared, video=pair['video_id']))
                if fingerprint in records:
                    records[fingerprint]['uses'].append(use)
                else:
                    records[fingerprint] = item = dict(
                        id=fingerprint[:16], kind='record', leaf=pair['leaf'], leaf_meaning=main_point.leaf_meaning(pair['leaf']), watch_url=sermon.link_at(record['sermon_start']),
                        before=sermon.text[max(0, record['sermon_start'] - WINDOW):record['sermon_start']], anchor=sermon.text[record['sermon_start']:record['sermon_end']],
                        after=sermon.text[record['sermon_end']:record['sermon_end'] + WINDOW], record=shared, uses=[use])
                    phase1.append(item)
                summary_print = digest(dict(pair=key, summary=record['summary'], target=record['target'], proposition=record['claim']['proposition']))
                if summary_print in summaries:
                    summaries[summary_print]['uses'].append(use)
                else:
                    summaries[summary_print] = item = dict(
                        id=summary_print[:16], kind='summary', pair=key, leaf=pair['leaf'], leaf_meaning=main_point.leaf_meaning(pair['leaf']),
                        watch_url=sermon.link_at(record['sermon_start']), unit_text=pair['text'], summary=record['summary'], target=record['target'],
                        proposition=record['claim']['proposition'], asks_framing=True, uses=[use])
                    phase2.append(item)
            if len(claims) >= 2:        # a version that returned several records for one pair: do they state different points?
                digest_of = digest(dict(pair=key, summaries=[c['summary'] for c in claims]))
                if digest_of in distinct:
                    distinct[digest_of]['uses'].append(dict(version=variant, pair=key))
                else:
                    distinct[digest_of] = item = dict(id=digest_of[:16], kind='distinct_points', pair=key, leaf=pair['leaf'], leaf_meaning=main_point.leaf_meaning(pair['leaf']),
                                                      watch_url=sermon.link_at(pair['unit_start']), unit_text=pair['text'],
                                                      records=[dict(summary=c['summary'], proposition=c['claim']['proposition']) for c in claims], uses=[dict(version=variant, pair=key)])
                    phase2.append(item)
    for key, pair in sorted(pairs.items()):
        silent = [v for v in keys if found[v][key] == []]
        if silent:
            phase1.append(dict(id=digest(dict(none=key))[:16], kind='none', pair=key, leaf=pair['leaf'], leaf_meaning=main_point.leaf_meaning(pair['leaf']),
                               watch_url=sermon_of(pair['video_id']).link_at(pair['unit_start']), unit_text=pair['text'],
                               uses=[dict(version=v, pair=key) for v in silent]))
    random.Random(f'{seed}:1').shuffle(phase1)
    random.Random(f'{seed}:2').shuffle(phase2)
    items = [*phase1, *phase2]
    if wide:        # section 25.3: every new queue shows the wide context
        items = widen_items(base_dir, half, items, dict(items={i['id']: {k: i[k] for k in ('kind', 'uses', 'pair') if k in i} for i in items}))
    visible = [{k: v for k, v in item.items() if k not in ('uses', 'pair')} for item in items]
    queue = seal(dict(version=VERSION, half=half, source_sha256=seed, item_count=len(items), phase1=len(phase1), items=visible))
    versions = seal(dict(version=VERSION, half=half, queue_fingerprint=queue['content_fingerprint'], variants=list(keys), reviewed_pairs=sorted(pairs),
                         answered={v: {k: len(r or []) for k, r in found[v].items() if k in pairs} for v in keys},
                         failed={v: sorted(k for k, r in found[v].items() if k in pairs and r is None) for v in keys},
                         items={item['id']: {k: item[k] for k in ('kind', 'uses', 'pair') if k in item} for item in items}))
    paths = paths_for(base_dir, half)
    paths['out'].mkdir(parents=True, exist_ok=True)
    write_json(paths['queue'], queue)
    write_json(paths['versions'], versions)
    return dict(queue=str(paths['queue']), half=half, variants=list(keys), pairs=len(pairs), items=len(items), phase1=len(phase1), phase2=len(phase2),
                records={v: sum(len(r or []) for k, r in found[v].items() if k in pairs) for v in keys},
                pairs_with_several={v: sum(len(r or []) >= 2 for k, r in found[v].items() if k in pairs) for v in keys},
                failed_pairs={v: sum(r is None for k, r in found[v].items() if k in pairs) for v in keys})


def judge(base_dir: Path, half: str, source: str = 'human', input_fn=input, output_fn=print, wide: bool = False) -> dict[str, Any]:
    paths = paths_for(base_dir, half)
    return leaf_review.judge(base_dir, source, input_fn, output_fn, leaf_evidence.V2, paths, lambda b, _v: build_queue(b, half, wide=wide))


def progress(base_dir: Path, half: str) -> dict[str, Any]:
    return leaf_review.progress(base_dir, leaf_evidence.V2, paths_for(base_dir, half), lambda b, _v: build_queue(b, half))


def tally(queue: Mapping[str, Any], versions: Mapping[str, Any], decided: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    rows = {v: dict(records=0, accepted=0, qualification_rejects=0, adoption_polarity_rejects=0, pairs_correct=0, summaries_ok=0, framed_ok=0, rejects={},
                    pairs_with_records=0, pairs_with_several=0, distinct_ok=0, distinct_total=0) for v in keys}
    fits: dict[tuple[str, str], list[bool]] = {}
    for item_id, meta in versions['items'].items():
        label = decided[item_id]
        for use in meta['uses']:
            row = rows[use['version']]
            if meta['kind'] == 'record':
                row['records'] += 1
                row['accepted'] += label['decision'] == 'accept'
                row['qualification_rejects'] += label['decision'] == 'reject:qualifications'
                row['adoption_polarity_rejects'] += label['decision'] in ('reject:adoption', 'reject:polarity')
                fits.setdefault((use['version'], use['pair']), []).append(bool(label['fit']))
                if label['decision'] != 'accept':
                    row['rejects'][label['decision']] = row['rejects'].get(label['decision'], 0) + 1
            elif meta['kind'] == 'none':
                row['pairs_correct'] += not label['answer']
            elif meta['kind'] == 'distinct_points':
                row['distinct_total'] += 1
                row['distinct_ok'] += bool(label['answer'])
            else:
                row['summaries_ok'] += bool(label['answer'])
                row['framed_ok'] += bool(label['framed'])
    for (version, _pair), found in fits.items():          # a pair is correct on leaf fit when every record it produced fits the leaf
        rows[version]['pairs_with_records'] += 1
        rows[version]['pairs_with_several'] += len(found) >= 2
        rows[version]['pairs_correct'] += all(found)
    return rows


def defects(queue: Mapping[str, Any], versions: Mapping[str, Any], decided: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every record or summary that failed a check, with the pair and the content that failed, for the defect table."""
    shown = {item['id']: item for item in queue['items']}
    out = []
    for item_id, meta in sorted(versions['items'].items(), key=lambda kv: kv[1].get('pair', kv[0])):
        label, item = decided[item_id], shown[item_id]
        for use in meta['uses']:
            if meta['kind'] == 'record' and (label['decision'] != 'accept' or not label['fit']):
                out.append(dict(version=use['version'], pair=use['pair'], kind='record', decision=label['decision'], leaf_fit=bool(label['fit']),
                                proposition=item['record']['proposition'], polarity=item['record']['polarity'], speech_role=item['record']['speech_role']))
            elif meta['kind'] == 'none' and label['answer']:
                out.append(dict(version=use['version'], pair=use['pair'], kind='missing_record', decision='should have a record'))
            elif meta['kind'] == 'distinct_points' and not label['answer']:
                out.append(dict(version=use['version'], pair=use['pair'], kind='padding', decision='records do not state different points',
                                summaries=[r['summary'] for r in item['records']]))
            elif meta['kind'] == 'summary' and (not label['answer'] or not label['framed']):
                out.append(dict(version=use['version'], pair=use['pair'], kind='summary', faithful=bool(label['answer']), leaf_framed=bool(label['framed']),
                                summary=item['summary'], proposition=item['proposition']))
    return out


def _spend(base_dir: Path, half: str, keys: tuple[str, ...]) -> dict[str, str]:
    cost = {}
    for key in keys:
        ledger = read_json(leaf_evidence.leaf_dir(base_dir, leaf_evidence.VARIANTS[key], leaf_evidence.SCOPES[half]) / 'ledger.json')
        cost[key] = str(sum((Decimal(e['actual_usd'] if e['status'] == 'resolved' else e['reserved_usd']) for e in ledger['entries'].values()), Decimal(0)))
    return cost


def report(base_dir: Path, half: str) -> dict[str, Any]:
    paths = paths_for(base_dir, half)
    queue, versions = leaf_review._sealed(paths['queue']), leaf_review._sealed(paths['versions'])
    if versions['queue_fingerprint'] != queue['content_fingerprint']:
        raise ValueError('review_versions.json does not belong to this queue; rebuild the queue')
    decided = leaf_review.load_decisions(base_dir, leaf_evidence.V2, paths)
    missing = [item['id'] for item in queue['items'] if item['id'] not in decided]
    if missing:
        raise ValueError(f'{len(missing)} items are unlabeled; finish the review first')
    keys, primary = tuple(versions['variants']), PRIMARY[half]
    if primary not in keys:
        primary = keys[-1]
    rows = tally(queue, versions, decided, keys)
    for version in keys:
        rows[version]['failed_pairs'] = len(versions.get('failed', {}).get(version, []))
    pairs = len(versions['reviewed_pairs'])
    reference = next((k for k in keys if k != primary), None)
    outcomes = {}
    for key in keys:
        base = rows[reference]['pairs_correct'] if reference and key == primary else 0
        outcomes[key] = leaf_review.evaluate(dict(pairs=pairs, new=rows[key], baseline=rows[reference or key], reference_pairs_correct=base), leaf_evidence.V2,
                                         f'{reference} version on the same pairs' if reference and key == primary else 'zero reference (none in this half)')
    paired = None
    if reference:
        accepted = lambda version, pair: any(decided[i]['decision'] == 'accept' for i, m in versions['items'].items() if m['kind'] == 'record'
                                             and any(u['version'] == version and u['pair'] == pair for u in m['uses']))
        status = {p: (accepted(primary, p), accepted(reference, p)) for p in versions['reviewed_pairs']}
        paired = dict(both=sum(a and b for a, b in status.values()), primary_only=sum(a and not b for a, b in status.values()),
                      reference_only=sum(b and not a for a, b in status.values()), neither=sum(not a and not b for a, b in status.values()))
    bars_met = outcomes[primary]['passed']
    not_below = None if paired is None else paired['primary_only'] >= paired['reference_only']
    passed = bars_met and (not_below is not False)
    readings = None
    if half in CONFIRM_HALVES and reference:           # section 24.3: the four readings of 23.3, fixed before any output, decide the verdict
        extras = [(m, u) for m in versions['items'].values() if m['kind'] == 'record' for u in m['uses'] if u['version'] == primary and u.get('index', 0) >= 1]
        extras_accepted = sum(decided[next(i for i, mm in versions['items'].items() if mm is m)]['decision'] == 'accept' for m, _u in extras)
        distinct = rows[primary]['distinct_total']
        pairs_accepted = lambda version: sum(any(decided[i]['decision'] == 'accept' for i, m in versions['items'].items() if m['kind'] == 'record'
                                                 and any(u['version'] == version and u['pair'] == p for u in m['uses'])) for p in versions['reviewed_pairs'])
        readings = dict(
            padding=bool(extras) and extras_accepted / len(extras) + 1e-9 >= 0.85 and (not distinct or rows[primary]['distinct_ok'] / distinct + 1e-9 >= 0.85),
            no_loss=bool(not_below),
            recall=pairs_accepted(primary) >= pairs_accepted(reference) and rows[primary]['accepted'] > rows[reference]['accepted'],
            single_point=rows[primary]['summaries_ok'] >= rows[reference]['summaries_ok'])
        readings['detail'] = dict(extra_records=len(extras), extra_accepted=extras_accepted, distinct=f"{rows[primary]['distinct_ok']} of {distinct}",
                                  pairs_with_accepted={primary: pairs_accepted(primary), reference: pairs_accepted(reference)})
        passed = all(v for k, v in readings.items() if k != 'detail')
    sources: dict[str, int] = {}
    for item in queue['items']:
        sources[decided[item['id']]['source']] = sources.get(decided[item['id']]['source'], 0) + 1
    final = dict(version=VERSION, half=half, pairs_reviewed=pairs, primary=primary, reference=reference, bars_met=bars_met, not_below_reference=not_below,
                 passed=passed if (half in VERDICT_HALVES or half in CONFIRM_HALVES) else None, readings=readings, criteria={k: o['criteria'] for k, o in outcomes.items()}, tally=rows, paired_accepted=paired,
                 labels_by=sources, cost_usd=_spend(base_dir, half, keys), defects=defects(queue, versions, decided))
    write_json(paths['report_json'], final)
    verdict = ('PASS' if passed else 'FAIL') if (half in VERDICT_HALVES or half in CONFIRM_HALVES) else 'EXPLORATORY (bars reported, no pass or fail)'
    lines = [f'# New-set leaf-evidence report: {half.replace("_", " ")} half', '', f'**{verdict}**', '',
             f"{pairs} pairs reviewed; labels by: {sources} (`human` = Brian's own; any other source is a delegated first pass, not Brian's judgment).", '',
             '| Version | Criterion | Rule | Observed | Result |', '| --- | --- | --- | --- | --- |']
    for key, outcome in outcomes.items():
        lines += [f"| {key} | {name} | {row['rule']} | `{row['observed']}` | {'PASS' if row['passed'] else 'FAIL'} |" for name, row in outcome['criteria'].items()]
    if readings is not None:
        lines += ['', f'Confirmatory readings (section 24.3): `{readings}`']
    if paired is not None:
        lines += ['', f'Paired accepted counts ({primary} against {reference}): `{paired}`; {primary} not below {reference}: {not_below}.']
    lines += ['', f"Defects: {len(final['defects'])}. Cost (not a bar): {final['cost_usd']}. Exposed development material when run on the development half; theme overlaps with sermon 281.", '']
    paths['report_md'].write_text('\n'.join(lines) + '\n')
    return dict(final, report_md=str(paths['report_md']), report_json=str(paths['report_json']))


# ---- spot check of the delegated labels (docs/THOUGHT_UNIT_EXPERIMENT.md section 24.8) ---------------------------------------------------------------

SPOT_SIZE = 10
SPOT_WINDOW = 3000        # characters of sermon text shown each side of a record, and of the neighboring units shown with the other items


def spot_paths(base_dir: Path, half: str) -> dict[str, Path]:
    paths = paths_for(base_dir, half)
    return dict(out=paths['out'], queue=paths['out'] / 'spot-check-queue.json', decisions=paths['out'] / 'decisions-spot-check.jsonl',
                report_md=paths['out'] / 'SPOT_CHECK.md', report_json=paths['out'] / 'SPOT_CHECK.json')


def spot_ids(queue: Mapping[str, Any]) -> list[str]:
    """Every distinct-points item (they decide the padding reading) plus the first others in sha256(item id) order, up to ten. Chosen by rule, not by my uncertainty."""
    distinct = [i['id'] for i in queue['items'] if i['kind'] == 'distinct_points']
    others = sorted((i['id'] for i in queue['items'] if i['kind'] != 'distinct_points'), key=digest)
    return (distinct + others)[:max(SPOT_SIZE, len(distinct))]


def widen_items(base_dir: Path, half: str, items: list[dict[str, Any]], versions: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Section 24.8 and 25.3: show each record with SPOT_WINDOW characters of sermon text either side, and each unit-based item with its neighboring units, so a grader never
    sees less text than the extractor had. Item ids do not depend on the display, so labels carry over."""
    pairs, texts = {p['key']: p for p in reviewed_pairs(base_dir, half)}, {}
    for item in items:
        if item['kind'] == 'record':
            pair = pairs[versions['items'][item['id']]['uses'][0]['pair']]
            if pair['video_id'] not in texts:
                texts[pair['video_id']] = public_set.load_sermon(base_dir, pair['video_id'], leaf_evidence.SCOPES[half].set_id)
            sermon = texts[pair['video_id']]
            at = sermon.text.find(item['before'] + item['anchor'])
            if at < 0 or sermon.text.find(item['before'] + item['anchor'], at + 1) >= 0:
                raise ValueError('Cannot place the record in the sermon text uniquely')
            start = at + len(item['before'])
            item['before'] = sermon.text[max(0, start - SPOT_WINDOW):start]
            item['after'] = sermon.text[start + len(item['anchor']):start + len(item['anchor']) + SPOT_WINDOW]
        else:
            pair = pairs[versions['items'][item['id']].get('pair') or versions['items'][item['id']]['uses'][0]['pair']]
            item['preceding_text'], item['following_text'] = pair['preceding_text'][-SPOT_WINDOW:], pair['following_text'][:SPOT_WINDOW]
    return items


def build_spot_queue(base_dir: Path, half: str) -> dict[str, Any]:
    """The same items as the full queue, without any label, in the full queue's wording; record and no-record items first, as in the blind pass."""
    full, versions = leaf_review._sealed(paths_for(base_dir, half)['queue']), leaf_review._sealed(paths_for(base_dir, half)['versions'])
    chosen = set(spot_ids(full))
    items = [dict(i) for i in full['items'] if i['id'] in chosen]
    items = widen_items(base_dir, half, items, versions)
    items = [i for i in items if i['kind'] in ('record', 'none')] + [i for i in items if i['kind'] not in ('record', 'none')]
    queue = seal(dict(version=VERSION, half=half, source_sha256=full['content_fingerprint'], item_count=len(items),
                      phase1=sum(i['kind'] in ('record', 'none') for i in items), items=items))
    paths = spot_paths(base_dir, half)
    write_json(paths['queue'], queue)
    kinds: dict[str, int] = {}
    for item in items:
        kinds[item['kind']] = kinds.get(item['kind'], 0) + 1
    return dict(queue=str(paths['queue']), items=len(items), kinds=kinds, decisions=str(paths['decisions']))


def judge_spot(base_dir: Path, half: str, input_fn=input, output_fn=print) -> dict[str, Any]:
    paths = spot_paths(base_dir, half)
    paths['out'].mkdir(parents=True, exist_ok=True)
    build = lambda b, _v: build_spot_queue(b, half)
    return leaf_review.judge(base_dir, 'human', input_fn, output_fn, leaf_evidence.V2, paths, build)


def spot_report(base_dir: Path, half: str) -> dict[str, Any]:
    """Brian's labels against mine on the same items, and what the padding reading would be if his labels replaced mine on them."""
    paths, full = spot_paths(base_dir, half), paths_for(base_dir, half)
    queue, versions = leaf_review._sealed(paths['queue']), leaf_review._sealed(full['versions'])
    mine, his = leaf_review.load_decisions(base_dir, leaf_evidence.V2, full), leaf_review.load_decisions(base_dir, leaf_evidence.V2, paths)
    missing = [i['id'] for i in queue['items'] if i['id'] not in his]
    if missing:
        raise ValueError(f'{len(missing)} spot-check items are unlabeled')
    fields = dict(record=('decision', 'fit'), none=('answer',), summary=('answer', 'framed'), distinct_points=('answer',))
    rows, same = [], 0
    for item in queue['items']:
        a, b = mine[item['id']], his[item['id']]
        agree = {f: a.get(f) == b.get(f) for f in fields[item['kind']]}
        same += all(agree.values())
        rows.append(dict(item=item['id'], kind=item['kind'], leaf=item['leaf'], mine={f: a.get(f) for f in agree}, his={f: b.get(f) for f in agree}, agree=all(agree.values())))
    primary = PRIMARY[half]
    def reading(label_of) -> dict[str, Any]:
        distinct = [i for i, m in versions['items'].items() if m['kind'] == 'distinct_points' and any(u['version'] == primary for u in m['uses'])]
        extras = [i for i, m in versions['items'].items() if m['kind'] == 'record' and any(u['version'] == primary and u.get('index', 0) >= 1 for u in m['uses'])]
        ok = sum(bool(label_of(i)['answer']) for i in distinct)
        accepted = sum(label_of(i)['decision'] == 'accept' for i in extras)
        return dict(distinct=f'{ok} of {len(distinct)}', extras_accepted=f'{accepted} of {len(extras)}',
                    padding_reading=bool(extras) and accepted / len(extras) + 1e-9 >= 0.85 and (not distinct or ok / len(distinct) + 1e-9 >= 0.85))
    replaced = lambda i: his.get(i) or mine[i]
    result = dict(items=len(rows), agree=same, rows=rows, padding_reading_with_my_labels=reading(lambda i: mine[i]), padding_reading_with_his_labels_where_given=reading(replaced))
    write_json(paths['report_json'], result)
    lines = ['# Spot check of the delegated labels (section 24.8)', '', f'{same} of {len(rows)} items agree on every field.', '',
             '| Item | Kind | Leaf | Mine | Brian | Agree |', '| --- | --- | --- | --- | --- | --- |']
    lines += [f"| {r['item']} | {r['kind']} | {r['leaf']} | `{r['mine']}` | `{r['his']}` | {'yes' if r['agree'] else '**no**'} |" for r in rows]
    lines += ['', f"Padding reading with my labels: `{result['padding_reading_with_my_labels']}`", f"Padding reading with Brian's labels where given: `{result['padding_reading_with_his_labels_where_given']}`", '']
    paths['report_md'].write_text('\n'.join(lines))
    return dict(result, report_md=str(paths['report_md']), report_json=str(paths['report_json']))
