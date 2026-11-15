"""Step G: producer precision, Jev threshold curves against Brian's labels, controls and the acceptance table."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import statistics
from typing import Any, Mapping

from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal

from .common import canonical, file_sha256, read_json, write_json
from .ledger import PilotLedger
from .review import PRODUCERS, load_decisions
from .verify import QUESTION_IDS

VERSION = 'bound-claim-pilot-report-v1'
THRESHOLDS = (0.60, 0.70, 0.80, 0.90, 0.95)
STRONG_STRATA = ('salvation_strong', 'public_life_strong')
PRECISION_FLOOR, MARGIN_OVER_FLASH, JEV_PRECISION, JEV_RETAINED, MAX_CONTROL_ACCEPTED = 0.80, 0.15, 0.90, 0.50, 1


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def producer_metrics(extraction: Mapping[str, Any], decisions: Mapping[str, Mapping[str, Any]], strata: Mapping[str, Any]) -> dict[str, Any]:
    blocks = {b['coordinate']: b for b in strata['blocks']}
    rows = [row for row in extraction['rows'] if row['status'] == 'ok']
    anchored = [(row, claim) for row in rows for claim in row['claims']]
    failures = sum(len(row['anchor_failures']) for row in rows)
    labels = {claim['fingerprint']: decisions.get(claim['fingerprint'], {}).get('decision') for _, claim in anchored}
    accepted = sum(label == 'accept' for label in labels.values())
    labeled = sum(label is not None for label in labels.values())
    rejected_by = Counter()
    for label in labels.values():
        if label and label != 'accept':
            rejected_by[label.partition(':')[2] or 'unspecified'] += 1
    rejected_by['anchor_failure'] += failures
    strong = [row for row in rows if blocks[row['coordinate']]['stratum'] in STRONG_STRATA]
    controls = [row for row in rows if blocks[row['coordinate']]['stratum'] == 'absent_control']
    return dict(
        blocks=len(extraction['rows']), blocks_ok=len(rows), failed_blocks=len(extraction['rows']) - len(rows),
        claims_produced=len(anchored) + failures, anchor_failures=failures, anchored_claims=len(anchored),
        labeled=labeled, unlabeled=len(anchored) - labeled, accepted=accepted, rejected=labeled - accepted,
        precision=_ratio(accepted, failures + labeled), rejected_by_category=dict(sorted(rejected_by.items())),
        offsets_corrected_by_code=sum(c['anchor']['offsets_corrected'] for _, c in anchored),
        strong_signal_blocks=len(strong),
        claims_per_strong_block=round(sum(len(r['claims']) for r in strong) / len(strong), 3) if strong else None,
        zero_claim_rate_on_strong_blocks=_ratio(sum(not r['claims'] and not r['anchor_failures'] for r in strong), len(strong)),
        control_blocks=len(controls), control_claims=sum(len(r['claims']) for r in controls),
        control_accepted=sum(labels.get(c['fingerprint']) == 'accept' for r in controls for c in r['claims']),
        control_unlabeled=sum(labels.get(c['fingerprint']) is None for r in controls for c in r['claims']),
        stopped=extraction.get('stopped'))


def jev_curves(scopes: Mapping[str, set[str]], verification: Mapping[str, Mapping[str, float]],
               decisions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for scope, fingerprints in scopes.items():
        labeled = {fp: decisions[fp]['decision'] == 'accept' for fp in fingerprints if fp in decisions}
        for question in QUESTION_IDS:
            scored = {fp: verification[fp][question] for fp in labeled if question in verification.get(fp, {})}
            accepted_total = sum(labeled[fp] for fp in scored)
            table, first = [], None
            for threshold in THRESHOLDS:
                passed = [fp for fp, probability in scored.items() if probability >= threshold]
                true_positive = sum(labeled[fp] for fp in passed)
                precision = _ratio(true_positive, len(passed))
                table.append(dict(threshold=threshold, passed=len(passed), accepted_passed=true_positive, precision=precision,
                                  retained_accepted_fraction=_ratio(true_positive, accepted_total)))
                if first is None and precision is not None and precision >= JEV_PRECISION:
                    first = threshold
            result.setdefault(scope, {})[question] = dict(labeled_scored=len(scored), accepted=accepted_total,
                                                          thresholds=table, first_threshold_reaching_precision_90=first)
    return result


def agreement(extractions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    def keys(row: Mapping[str, Any]) -> set[tuple[str, str]]:
        return {(c['claim']['object'].strip().lower(), c['claim']['polarity']) for c in row['claims']}
    pro = {r['coordinate']: r for r in extractions['pro']['rows'] if r['status'] == 'ok'}
    flash = {r['coordinate']: r for r in extractions['flash']['rows'] if r['status'] == 'ok'}
    both = sorted(set(pro) & set(flash))
    matched = sum(len(keys(pro[c]) & keys(flash[c])) for c in both)
    pro_only = sum(len(keys(pro[c]) - keys(flash[c])) for c in both)
    flash_only = sum(len(keys(flash[c]) - keys(pro[c])) for c in both)
    return dict(definition='same block, same object (case-insensitive) and polarity', blocks_compared=len(both),
                matched=matched, pro_only=pro_only, flash_only=flash_only,
                agreement_rate=_ratio(matched, matched + pro_only + flash_only))


def billing_finding(pilot: Path, verification: Mapping[str, Any] | None) -> dict[str, Any]:
    """Which size model makes tokens-per-character most constant: state billed once per request or once per question."""
    samples = []
    for row in (verification or {}).get('rows', []):
        if row['status'] != 'ok':
            continue
        for path in (pilot / 'verify' / row['fingerprint'] / 'receipts').glob('*.json'):
            receipt = read_json(path)
            body = receipt['request']['body']
            state, question = len(canonical(body['state'])), len(canonical(body['questions']))
            samples.append((receipt['response']['usage']['input_tokens'], state, question, len(body['questions'])))
    if len(samples) < 5:
        return dict(model='undetermined', reason='fewer than five verification requests with saved usage', samples=len(samples))

    def spread(sizes: list[float]) -> float:
        ratios = [tokens / size for (tokens, *_), size in zip(samples, sizes)]
        return statistics.pstdev(ratios) / statistics.mean(ratios)
    per_request = spread([state + question for _, state, question, _ in samples])
    per_question = spread([state * n + question for _, state, question, n in samples])
    return dict(model='per_request' if per_request <= per_question else 'per_question', samples=len(samples),
                tokens_per_character_variation=dict(per_request=round(per_request, 4), per_question=round(per_question, 4)),
                basis='Lower coefficient of variation of input tokens per character of billed size identifies the billing unit.')


def acceptance(metrics: Mapping[str, Any], jev: Mapping[str, Any], decisions: Mapping[str, Any], extractions: Mapping[str, Any],
               sections: Mapping[str, Any]) -> list[dict[str, Any]]:
    pro, flash = metrics['pro'], metrics['flash']
    rows = []

    def row(number: int, name: str, rule: str, observed: Any, status: str, component: str) -> None:
        rows.append(dict(criterion=number, name=name, rule=rule, observed=observed, status=status,
                         failing_component=component if status == 'FAIL' else None))

    pending = bool(pro['unlabeled'] or flash['unlabeled'])
    if pending or pro['precision'] is None or flash['precision'] is None:
        status = 'PENDING_REVIEW'
    else:
        status = 'PASS' if pro['precision'] >= PRECISION_FLOOR and pro['precision'] >= flash['precision'] + MARGIN_OVER_FLASH else 'FAIL'
    row(1, 'Producer precision', 'V4 Pro accepted/produced >= .80 and >= Flash + .15',
        dict(pro=pro['precision'], flash=flash['precision']), status, 'producer or contract')

    supported = jev['pro']['supported']
    qualifying = [t for t in supported['thresholds'] if t['precision'] is not None and t['precision'] >= JEV_PRECISION
                  and t['retained_accepted_fraction'] is not None and t['retained_accepted_fraction'] >= JEV_RETAINED]
    row(2, 'Verifier discrimination', 'For `supported`, some threshold gives precision >= .90 while retaining >= 50% of accepted V4 Pro claims',
        dict(qualifying_thresholds=[t['threshold'] for t in qualifying], accepted_pro_claims=supported['accepted']),
        'PENDING_REVIEW' if pro['unlabeled'] or not supported['labeled_scored'] else 'PASS' if qualifying else 'FAIL', 'verifier design')

    delivered = {pid: s for pid, s in sections.items() if len({f['video_id'] for f in s['findings']}) >= 2
                 and all(f['watch_url'].startswith('https://') and '=' in f['watch_url'] for f in s['findings'])}
    row(3, 'Delivered findings', '>= 2 accepted claims for one profile from different sermons in the rendered section with source links',
        dict(sections_rendered=sorted(sections), qualifying_profiles=sorted(delivered), links_checked='structure only (YouTube URL with t= offset); not opened'),
        'PASS' if delivered else ('PENDING_RENDER' if not sections else 'FAIL'), 'assembly')

    public = [fp for fp, d in decisions.items() if d['decision'] == 'accept' and fp in _pro_public(extractions)]
    row(4, 'Public life', '>= 1 accepted public_life V4 Pro claim (accepting it accepts its voice and polarity)',
        dict(accepted_public_life_claims=len(public)), 'PASS' if public else ('PENDING_REVIEW' if pro['unlabeled'] else 'FAIL'), 'producer on C08')

    controls = pro['control_accepted']
    row(5, 'Controls', f'<= {MAX_CONTROL_ACCEPTED} accepted V4 Pro claim across the absent-control blocks',
        dict(control_blocks=pro['control_blocks'], claims=pro['control_claims'], accepted=controls, unlabeled=pro['control_unlabeled']),
        'FAIL' if controls > MAX_CONTROL_ACCEPTED else 'PENDING_REVIEW' if pro['control_unlabeled'] else 'PASS', 'producer over-generation')
    return rows


def _pro_public(extractions: Mapping[str, Any]) -> set[str]:
    return {c['fingerprint'] for r in extractions['pro']['rows'] for c in r['claims'] if c['claim']['area'] == 'public_life'}


def compute(pilot: Path) -> dict[str, Any]:
    strata = read_json(pilot / 'strata.json')
    extractions = {producer: read_json(pilot / 'extract' / producer / 'extraction.json') for producer in PRODUCERS}
    for extraction in extractions.values():
        if seal(extraction) != extraction or extraction['strata_sha256'] != file_sha256(pilot / 'strata.json'):
            raise ValueError('Extraction is not sealed for this strata file')
    decisions = load_decisions(pilot)
    verification_path = pilot / 'verify' / 'verification.json'
    verification_doc = read_json(verification_path) if verification_path.exists() else None
    verification = {row['fingerprint']: row['answers'] for row in (verification_doc or {}).get('rows', []) if row['status'] == 'ok'}
    scopes = {producer: {c['fingerprint'] for r in extractions[producer]['rows'] for c in r['claims']} for producer in PRODUCERS}
    scopes['pooled'] = scopes['pro'] | scopes['flash']
    metrics = {producer: producer_metrics(extractions[producer], decisions, strata) for producer in PRODUCERS}
    jev = jev_curves(scopes, verification, decisions)
    sections = {}
    for path in sorted(pilot.glob('SECTION_*.json')):
        section = read_json(path)
        sections[str(section['profile_id'])] = section
    table = acceptance(metrics, jev, decisions, extractions, sections)
    ledger = PilotLedger(pilot / 'ledger.json').summary()
    statuses = {row['status'] for row in table}
    overall = 'PASS' if statuses == {'PASS'} else 'FAIL' if 'FAIL' in statuses else 'INCOMPLETE'
    return dict(
        version=VERSION, status=overall, strata_sha256=file_sha256(pilot / 'strata.json'),
        strata=[{k: row[k] for k in ('stratum', 'requested', 'eligible', 'selected', 'shortfall')} for row in strata['strata']],
        labels=dict(decided=len(decisions), accepted=sum(d['decision'] == 'accept' for d in decisions.values())),
        producers=metrics, jev_thresholds=jev, agreement=agreement(extractions),
        costs=dict(ledger=ledger, jev_billing_finding=billing_finding(pilot, verification_doc),
                   note='Known list-price usage replaces reservations; unresolved usage keeps its reservation; invoice not checked.'),
        acceptance=table,
        failing_components=sorted({r['failing_component'] for r in table if r['failing_component']}),
        next_action=('All five criteria pass: the mechanism is proven for this slice; proceed to the gold-set and corpus phases.'
                     if overall == 'PASS' else
                     'A criterion failed: stop, name the failing component, and propose one next action; no prompt, schema, model or threshold variant is run inside this pilot.'
                     if overall == 'FAIL' else 'Complete the review (and run render) so every criterion can be decided.'))


def markdown(report: Mapping[str, Any]) -> str:
    lines = ['# Bound-claim pilot report', '', report['status'], '', report['next_action'], '', '## Acceptance', '',
             '| # | Criterion | Rule | Observed | Status | Failing component |', '| --- | --- | --- | --- | --- | --- |']
    for row in report['acceptance']:
        lines.append(f"| {row['criterion']} | {row['name']} | {row['rule']} | `{json.dumps(row['observed'], sort_keys=True)}` | **{row['status']}** | {row['failing_component'] or ''} |")
    lines += ['', '## Producers', '', '| Measure | V4 Pro | V4.1 Flash |', '| --- | --- | --- |']
    pro, flash = report['producers']['pro'], report['producers']['flash']
    for key in ('blocks_ok', 'failed_blocks', 'claims_produced', 'anchor_failures', 'offsets_corrected_by_code', 'labeled', 'unlabeled', 'accepted',
                'precision', 'claims_per_strong_block', 'zero_claim_rate_on_strong_blocks', 'control_claims', 'control_accepted'):
        lines.append(f'| {key} | {pro[key]} | {flash[key]} |')
    lines.append(f"| rejected by category | `{json.dumps(pro['rejected_by_category'])}` | `{json.dumps(flash['rejected_by_category'])}` |")
    lines += ['', '## Jev thresholds against labels', '',
              'Precision is accepted/passed at the threshold; retained is accepted-passed/all accepted.', '']
    for scope, questions in report['jev_thresholds'].items():
        for question, data in questions.items():
            if not data['labeled_scored']:
                continue
            first = data['first_threshold_reaching_precision_90']
            lines += [f"**{scope} / {question}** ({data['labeled_scored']} labeled, {data['accepted']} accepted; precision first reaches .90 at {first})", '',
                      '| Threshold | Passed | Precision | Retained |', '| --- | --- | --- | --- |']
            lines += [f"| {t['threshold']} | {t['passed']} | {t['precision']} | {t['retained_accepted_fraction']} |" for t in data['thresholds']]
            lines.append('')
    agree = report['agreement']
    lines += ['## Producer agreement', '', f"{agree['definition']}: {agree['matched']} matched, {agree['pro_only']} Pro only, "
              f"{agree['flash_only']} Flash only across {agree['blocks_compared']} blocks (rate {agree['agreement_rate']}).", '',
              '## Strata', '', '| Stratum | Requested | Eligible | Selected | Shortfall |', '| --- | --- | --- | --- | --- |']
    lines += [f"| {s['stratum']} | {s['requested']} | {s['eligible']} | {s['selected']} | {s['shortfall']} |" for s in report['strata']]
    ledger = report['costs']['ledger']
    lines += ['', '## Costs', '', f"Committed ${ledger['committed_usd']} of ${ledger['ceiling_usd']} over {ledger['attempts']} of {ledger['ceiling_attempts']} attempts.", '',
              '| Step | Attempts | Known usage USD | Unresolved | Reserved unresolved USD | Input tokens | Output tokens |', '| --- | --- | --- | --- | --- | --- | --- |']
    lines += [f"| {step} | {d['attempts']} | {d['known_usd']} | {d['unresolved']} | {d['reserved_unresolved_usd']} | {d['input_tokens']} | {d['output_tokens']} |"
              for step, d in sorted(ledger['steps'].items())]
    lines += ['', f"Jev billing finding: `{json.dumps(report['costs']['jev_billing_finding'])}`", '', report['costs']['note'], '']
    return '\n'.join(lines)


def run(pilot: Path) -> dict[str, Any]:
    report = seal(compute(pilot))
    write_json(pilot / 'REPORT.json', report)
    (pilot / 'REPORT.md').write_text(markdown(report))
    return dict(status=report['status'], acceptance={row['criterion']: row['status'] for row in report['acceptance']},
                failing_components=report['failing_components'], report_md=str(pilot / 'REPORT.md'), report_json=str(pilot / 'REPORT.json'))
