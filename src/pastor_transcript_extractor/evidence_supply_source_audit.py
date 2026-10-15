"""Verify and render the authored V2 focal source audit; never calls a provider."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

from pastor_transcript_extractor import evidence_supply_revision as frozen

RESULTS = frozen.ROOT / "evaluation/evidence-supply-readiness-v2"
AUDIT = RESULTS / "source-audit-v2.json"


def accepted_decision(report):
    path = RESULTS / 'acceptance-decision-v2.json'
    if not path.exists():
        return None
    decision = json.loads(path.read_text())
    if (decision['content_fingerprint'] != frozen.fp({k:v for k,v in decision.items() if k != 'content_fingerprint'})
            or decision['audit_fingerprint'] != report['content_fingerprint']
            or decision['audit_file_sha256'] != frozen.v1.file_hash(AUDIT)
            or decision['status'] != 'FAIL' or decision['closed'] is not True):
        raise ValueError('Invalid V2 human acceptance decision')
    return decision


def validate_review(report, packet, result, references, sources, ledger):
    """Check the evidence/score/accounting bindings, not automate source judgment."""
    if report['content_fingerprint'] != frozen.fp({k: v for k, v in report.items() if k != 'content_fingerprint'}):
        raise ValueError('Source audit fingerprint mismatch')
    if report['input_fingerprint'] != packet['content_fingerprint'] or result['input_fingerprint'] != packet['content_fingerprint']:
        raise ValueError('Source audit belongs to another packet')
    expected = {c['check_id']: (r, c) for r in references['rows'] for c in r['checks']}
    actual = {r['check_id']: r for r in report['records']}
    scored = {r['check_id']: r for r in result['reference_checks']}
    if len(actual) != len(report['records']) or set(actual) != set(expected) or set(scored) != set(expected):
        raise ValueError('Missing, extra or duplicate focal audit check')
    observation_map = {o['candidate_id']: o for o in result['observations']}
    for key, row in actual.items():
        ref, check = expected[key]
        if row['frozen_check'] != check or row['frozen_status'] != scored[key]['status'] or row['video_id'] != ref['video_id'] or row['frozen_opportunity'] != check['opportunity']:
            raise ValueError('Frozen check or score changed in audit')
        source = sources[ref['video_id']]
        for name in ('claim', 'left', 'right', 'utterance', 'circumstance'):
            value = check.get(name)
            if value and (source['text'][value['start']:value['end']] != value['text'] or not source['main_span']['start'] <= value['start'] < value['end'] <= source['main_span']['end']):
                raise ValueError('Reference is not exact available main-source evidence')
        if [a['evaluation'] for a in row['aliases']] != scored[key]['evaluations']:
            raise ValueError('A scored alias was lost or changed')
        for alias in row['aliases']:
            obs = observation_map[alias['evaluation']['candidate_id']]
            if alias['raw_answers'] != obs['raw_answers'] or alias['payload'] != obs['payload'] or alias['request_key'] != obs['request_key']:
                raise ValueError('Audited alias differs from raw observation')
            for name in ('target', 'claim', 'left', 'right', 'circumstance', 'utterance'):
                value = alias['candidate'].get(name)
                if value and source['text'][value['start']:value['end']] != value['text']:
                    raise ValueError('Candidate evidence no longer matches source')
    counts = dict(Counter(r['frozen_status'] for r in actual.values()))
    if counts != result['check_counts'] or counts != report['frozen_counts']:
        raise ValueError('Frozen score totals changed')
    if report['audited_focal_checks'] != len(actual) or report['requested_nonmatching_checks'] != sum(r['frozen_status'] != 'matches_frozen_fields' for r in actual.values()):
        raise ValueError('Audit coverage totals changed')
    manifest = {r['request_key'] for r in packet['request_manifest']}
    raw = {r['request_key']: r for r in result['raw_rows']}
    attempts = {a['request_key']: a for a in ledger['attempts']}
    if len(raw) != len(result['raw_rows']) or len(attempts) != len(ledger['attempts']) or set(raw) != manifest or set(attempts) != manifest:
        raise ValueError('Incomplete or duplicate request accounting')
    if ledger['input_fingerprint'] != packet['content_fingerprint'] or any(a['status'] != 'validated' or a['usage'] != raw[key]['usage'] or a['resolved_model'] != packet['model'] for key, a in attempts.items()):
        raise ValueError('Ledger differs from completed raw usage/model')
    usage = {'attempts': len(raw), **{k: sum(r['usage'][k] for r in raw.values()) for k in ('input_tokens', 'output_tokens')}}
    cost = Decimal(usage['input_tokens']) * frozen.PRICE
    if usage != result['usage'] or cost != Decimal(result['actual_list_price_usd']):
        raise ValueError('Usage/cost mismatch')
    economics = report['usable_evidence']; items = economics['items']
    if len({i['item_id'] for i in items}) != len(items) or economics['audited_focal_subset_unique_items'] != len(items):
        raise ValueError('Usable subset duplicated or count mismatch')
    for item in items:
        obs = observation_map[item['candidate_id']]
        if not item['accepted_positive_facts'] or not item['check_ids'] or any(key not in actual or item['item_id'] not in actual[key]['usable_item_ids'] for key in item['check_ids']):
            raise ValueError('Usable item is not tied to an audited check')
        aliases = [a for key in item['check_ids'] for a in actual[key]['aliases'] if a['evaluation']['candidate_id'] == item['candidate_id']]
        if not aliases or item['retained_decisions'] != aliases[0]['evaluation']['decisions'] or any(item['retained_decisions'].get(k) != value for k, value in item['accepted_positive_facts'].items()):
            raise ValueError('Auditor filled a withheld or absent positive fact')
        if item['pastor_credit'] or obs['pastor_credit']:
            raise ValueError('Pastor credit activated')
        identity = {k: aliases[0]['candidate'][k] for k in ('claim', 'left', 'right', 'circumstance', 'utterance') if aliases[0]['candidate'].get(k)}
        if item['spans'] != identity or item['item_id'] != frozen.fp(dict(capability=item['capability'], video_id=item['video_id'], spans=identity)):
            raise ValueError('Usable opportunity identity drift')
    if economics['by_capability'] != dict(Counter(i['capability'] for i in items)) or economics['by_category'] != dict(Counter(i['category'] for i in items)):
        raise ValueError('Usable item breakdown drift')
    if Decimal(economics['full_run_list_price_usd']) != cost or Decimal(economics['full_run_cost_per_audited_subset_item_usd']) != cost / Decimal(len(items)):
        raise ValueError('Audited subset unit-cost denominator drift')
    if economics['whole_run_unique_items'] is not None or economics['whole_run_unit_cost_usd'] is not None or report['provider_requests_during_audit'] != 0:
        raise ValueError('Audit exceeds its declared scope')


def load_review():
    report = json.loads(AUDIT.read_text())
    for name, digest in report['input_file_sha256'].items():
        path = (frozen.ROOT / name).resolve()
        if not path.is_relative_to(frozen.ROOT.resolve()) or frozen.v1.file_hash(path) != digest:
            raise ValueError(f'Source audit input changed: {name}')
    packet = json.loads((frozen.HERE / 'input-v2.json').read_text())
    frozen.validate_packet(packet, reproduce=False)
    result = json.loads((RESULTS / 'results-v2.json').read_text())
    references = json.loads((frozen.HERE / 'references-v2.json').read_text())
    sources = {v: json.loads((frozen.HERE / 'sources' / f'{v}.json').read_text()) for v in packet['source_ids']}
    ledger = json.loads((RESULTS / 'request-ledger.json').read_text())
    frozen._verify_seal(ledger)
    validate_review(report, packet, result, references, sources, ledger)
    return report


def render_review(report):
    econ = report['usable_evidence']
    lines = ['# Evidence Supply V2 source audit', '',
             '**Recommendation: FAIL collection readiness; PARTIAL useful supplied local evidence. Brian’s decision is pending.**', '',
             'All 114 focal checks were source-reviewed, including the requested 44 not-supplied, 23 conservative-omission and 3 measurement-error checks. The frozen scores and expectations are unchanged. This is a focal-slate audit, not semantic certification of every non-reference output.', '',
             '## Findings', '',
             '- Of 44 unsupplied checks, 37 are candidate-discovery failures, two have a disputed positive explanation expectation, and five are incompatible with a positive narrow G1 opportunity (but remain useful missed diagnostic controls). All 44 exact texts exist in the available main-sermon sources; none is explained by missing transcript, source truncation, payment limits or a failed provider request.',
             '- The 37 discovery failures include 27 frozen positives. R020/R021 are the other two frozen positives: repetition/reading is not automatically explanation. Their mechanical horizon/same-sentence misses remain visible despite the reference disputes. No adjusted recall percentage is claimed.',
             '- The 23 omissions include genuine missed positives, six exact-anchor/contract-scope disputes, safe control withholding, and one integrity failure in an unscored field. All three original measurement errors are source-supported false negatives. No threshold is lowered or argmax promoted.',
             '- R078 emits reassurance for narration that contains no actual reassuring address. R080 misattributes a Desire of Ages quote and credits a non-biblical explanation anchor. Frozen field-only matches/omissions did not test those particular failures. These are at least two integrity findings, not an exhaustive whole-run count.', '',
             '## Supported local evidence and economics', '',
             f'The focal subset yields **{econ["audited_focal_subset_unique_items"]} unique positive records: 23 G2, 11 G3, zero G1**. Ten have resolved adopted local fields, 21 are partial, and three are report-only. This classification grants no pastor credit. The JSON lists every exact item identity and accepted positive-fact whitelist; all remaining decisions retain their original uncertainty. A control contributes only when it independently contains an audited observed positive act, never merely because a no-binding/no-match control matched.', '',
             f'Actual full-run list-price cost: **${econ["full_run_list_price_usd"]}**, from 55,847,356 input tokens at the frozen rate. Full-run cost divided by the 34 certified focal items is **${Decimal(econ["full_run_cost_per_audited_subset_item_usd"]):.6f} per audited-subset item** (about 6.9 cents). This charges the entire experiment to that subset; it is not a marginal cost, whole-run unit cost or production forecast.', '',
             f'Whole-run usable total and whole-run unit cost remain **null**. Another {econ["unreviewed_nonreference_positive_candidate_output_count"]} positive candidate outputs (231 G2 and 559 G3, before source deduplication) are outside the focal audit. They are explicitly unreviewed, not silently accepted or declared false. Manual source positives that the analyzer omitted do not enter the denominator.', '',
             '## Stage-gate recommendation', '',
             report['recommendation']['rationale'], '',
             'Accept this audit as a diagnostic record and keep collection/projection held. A next, separately authorized provider-free proposal should distinguish collector sentence/quote boundaries, lexical/horizon gaps, exact-check design disputes, and leakage in the collected request setting. The evidence does not isolate batching or model behavior as the cause. The closed contracts already prohibit the two integrity failures; this audit does not authorize reopening or tuning G1/G2/G3.', '',
             '## Limitations and continuing holds', '',
             *['- ' + s for s in report['limitations']], '',
             *['- ' + s for s in report['holds']], '',
             '## Verify this report through the CLI', '',
             '```sh', 'pte analysis evidence-supply-source-audit', '```', '',
             'This reads and verifies the frozen packet, source/reference/result hashes, ledger accounting, audit identities and subset arithmetic. It makes no provider calls, performs no reclassification, and grants no downstream authorization. Use `--write-reports` to deterministically render the Markdown and stage-gate summary from the authored JSON.', '',
             '## Check-by-check source audit', '']
    for row in report['records']:
        lines += [f'### {row["check_id"]} — {row["frozen_status"]}', '',
                  f'Source {row["video_id"]}; {row["capability"]}; frozen opportunity `{row["frozen_opportunity"]}`. Audit classification: **{row["primary_classification"]}**.', '',
                  row['assessment'], '', row['mechanical_evidence'], '']
        for name in ('claim', 'left', 'right', 'circumstance', 'utterance'):
            value = row['frozen_check'].get(name)
            if value:
                quote = value['text'].replace('\n', ' ')
                lines.append(f'- {name} [{value["start"]}:{value["end"]}]: “{quote}”')
        lines += ['', 'Frozen expectation: `' + json.dumps(row['frozen_check']['expected'], ensure_ascii=False) + '`.', '']
        for alias in row['aliases']:
            evaluation = alias['evaluation']
            lines += [f'Candidate `{evaluation["candidate_id"]}`; request `{alias["request_key"]}`.', '',
                      'Gated decisions: `' + json.dumps(evaluation['decisions'], ensure_ascii=False) + '`.', '']
            for name in sorted(set(evaluation['withheld_fields']) | {d['field'] for d in evaluation['differences']}):
                answer = alias['raw_answers'][name]
                lines += [f'- {name}: selected `{answer["choice"]}`; selected probability {answer["probabilities"][answer["choice"]]}; gated `{evaluation["decisions"][name]}`.']
            lines.append('')
        lines += [f'Usable positive items credited: {len(row["usable_item_ids"])}. Full target, surrounding source, raw distributions and any extra-field failures are preserved in `source-audit-v2.json`.', '']
    return '\n'.join(lines)


def write_reports(report):
    AUDIT.with_suffix('.md').write_text(render_review(report))
    gate = dict(version='evidence-supply-stage-gate-v2',status='recommendation_pending_Brian_decision',
                audit_fingerprint=report['content_fingerprint'], audit_file_sha256=frozen.v1.file_hash(AUDIT),
                input_fingerprint=report['input_fingerprint'], recommendation=report['recommendation'],
                critical_integrity_findings=report['critical_integrity_findings'],
                audited_focal_checks=report['audited_focal_checks'], frozen_counts=report['frozen_counts'],
                nonmatching_audit_summary=report['nonmatching_audit_summary'],
                source_availability_summary=report['source_availability_summary'],
                usable_evidence_summary={k:v for k,v in report['usable_evidence'].items() if k != 'items'},
                holds=report['holds'],limitations=report['limitations'],provider_requests_during_audit=0)
    gate['content_fingerprint'] = frozen.fp(gate)
    (RESULTS / 'stage-gate-v2.json').write_text(json.dumps(gate, ensure_ascii=False, indent=2) + '\n')
    (RESULTS / 'stage-gate-v2.md').write_text('\n'.join(render_review(report).split('## Check-by-check source audit')[0].splitlines()) + '\n')
