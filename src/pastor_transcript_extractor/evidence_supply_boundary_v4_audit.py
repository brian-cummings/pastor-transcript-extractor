"""Verify the authored receipt-bound V4 audit and replay the frozen local gate.

No provider path, writes, semantic reclassification or automatic review authority.
Semantic judgments remain authored; this verifies evidence bindings and coverage.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import json

from pastor_transcript_extractor import evidence_supply_boundary_execution as execution
from pastor_transcript_extractor import evidence_boundary_admission as gate

panel = execution.panel
HERE = panel.HERE
AUDIT = HERE / 'source-audit-v4.json'
REVIEW = HERE / 'source-review-v4.json'
ACCEPTANCE = HERE / 'source-review-acceptance-v4.json'


def validate_coverage(report, packet, review, measurements):
    records = report['records']
    if [r['case_id'] for r in records] != [c['case_id'] for c in packet['cases']]:
        raise ValueError('Missing, duplicate or reordered case audit')
    if [r['case_id'] for r in review['rows']] != [r['case_id'] for r in records]:
        raise ValueError('Source-review coverage changed')
    for row, case, witness in zip(records, packet['cases'], review['rows'], strict=True):
        measurement = measurements[row['case_id']]
        doc = measurement.document
        if (row['video_id'] != case['video_id'] or row['capability'] != case['capability']
                or row['frozen_case'] != case or row['binding'] != doc['binding']
                or row['measurement_fingerprint'] != measurement.fingerprint
                or witness['binding'] != doc['binding'] or witness['measurement_fingerprint'] != measurement.fingerprint
                or row['witness_facts'] != witness['facts']):
            raise ValueError('Source witness/case/measurement binding changed')
        expected_states = [dict(request_key=r['request_key'], phase=r['phase'], state=r['state'])
                           for r in packet['requests'] if r['case_id'] == case['case_id']]
        if row['request_states'] != expected_states:
            raise ValueError('Supplied target/envelope state changed')
        info = packet['source_files'][str(case['video_id'])]
        source = json.loads((panel.old.frozen.ROOT / info['path']).read_text())['text']
        span = row['source_excerpt']
        if (not 0 <= span['start'] < span['end'] <= len(source)
                or source[span['start']:span['end']] != span['text'] or witness['source_support'] != [span]):
            raise ValueError('Full-source excerpt changed')
        fields = {f['field']: f for f in row['fields']}
        if len(fields) != len(row['fields']) or set(fields) != set(doc['decisions']):
            raise ValueError('Incomplete all-field audit')
        for phase in doc['phases']:
            for key, raw in phase['raw_answers'].items():
                name = key.removeprefix('p0_'); field = fields[name]
                if (field['question_key'] != key or field['phase'] != phase['phase']
                        or field['decision'] != phase['decisions'][name]
                        or field['raw_choice'] != raw['choice'] or field['probabilities'] != raw['probabilities']
                        or field['selected_probability'] != raw['probabilities'][raw['choice']]
                        or field['confidence'] != raw['confidence']):
                    raise ValueError('Raw distribution/choice/confidence/gating changed')
                if not field['classification'] or not field['rationale']:
                    raise ValueError('Missing authored semantic judgment')
        comparisons = []
        for comparison in case['comparisons']:
            differences = [dict(field=k, expected=v, actual=doc['decisions'].get(k)) for k, v in comparison['expected'].items()
                           if doc['decisions'].get(k) not in v]
            comparisons.append(dict(check_id=comparison['check_id'], scope=comparison['scope'], differences=differences))
        if [{k:r[k] for k in ('check_id', 'scope', 'differences')} for r in row['comparisons']] != comparisons:
            raise ValueError('Frozen historical/forward comparison changed')
        for comparison in row['comparisons']:
            if [{k:r[k] for k in ('field', 'expected', 'actual')} for r in comparison['difference_reviews']] != comparison['differences']:
                raise ValueError('Difference lacks source review')
            for difference in comparison['difference_reviews']:
                field = fields[difference['field']]
                if difference['classification'] != field['classification'] or difference['rationale'] != field['rationale']:
                    raise ValueError('Difference/field judgment conflicts')
        unscored = [dict(field=x['field'], classification=x['classification'], rationale=x['rationale']) for x in row['fields']
                    if x['classification'] != 'supported_observation'
                    and not any(x['field'] in co['expected'] for co in case['comparisons'])]
        if unscored != row['unscored_findings']:
            raise ValueError('Unscored finding lost')
    counts = dict(Counter(f['classification'] for r in records for f in r['fields']))
    critical = [dict(case_id=r['case_id'], field=f['field']) for r in records for f in r['fields'] if f['critical']]
    historical = sum(len(c['differences']) for r in records for c in r['comparisons'] if c['scope'] == 'historical_V3_geometry_diagnostic')
    forward = [c for r in records for c in r['comparisons'] if c['scope'] == 'proposed_forward_check']
    if (report['audited_cases'] != len(records) or report['audited_fields'] != sum(counts.values())
            or counts != report['field_class_counts'] or critical != report['critical_raw_fields']
            or report['critical_raw_cases'] != [r['case_id'] for r in records if any(f['critical'] for f in r['fields'])]
            or report['historical_difference_count'] != historical or report['forward_checks'] != len(forward)
            or report['forward_difference_count'] != sum(len(c['differences']) for c in forward)
            or report['forward_checks_matching'] != sum(not c['differences'] for c in forward)
            or report['cases_without_forward_checks'] != sum(not any(c['scope'] == 'proposed_forward_check' for c in r['comparisons']) for r in records)):
        raise ValueError('Audit coverage/critical/forward counts changed')


def verify(base_dir=None):
    report = gate.sealed(AUDIT)
    packet = json.loads(panel.INPUT.read_text())
    decision = execution.authorization(packet, base_dir)
    directory = panel.output_directory(base_dir)
    ledger, cache = execution.read_cache(packet, directory, decision)
    result = gate.sealed(directory / 'results-v4.json')
    if len(cache) != 37 or len(ledger['attempts']) != 37:
        raise ValueError('Incomplete authorized V4 receipt inventory')
    expected_files = {'results-v4.json', 'results-v4.md', 'request-ledger.json'} | {
        'receipts/' + r['request_key'] + '.json' for r in packet['requests']}
    if set(report['runtime_file_hashes']) != expected_files:
        raise ValueError('Missing audited runtime identity')
    for name, digest in report['runtime_file_hashes'].items():
        if panel.old.frozen.v1.file_hash(directory / name) != digest:
            raise ValueError('Original runtime evidence changed')
    if report['input_fingerprint'] != packet['content_fingerprint'] or report['raw_results_fingerprint'] != result['content_fingerprint']:
        raise ValueError('Source audit belongs to another run')
    usage = dict(attempts=37, input_tokens=sum(a['usage']['input_tokens'] for a in ledger['attempts']),
                 output_tokens=sum(a['usage']['output_tokens'] for a in ledger['attempts']))
    if (report['usage'] != usage or result['usage'] != usage
            or Decimal(report['actual_list_price_usd']) != Decimal(usage['input_tokens']) * execution.PRICE
            or result['actual_list_price_usd'] != report['actual_list_price_usd']
            or result['ledger_file_sha256'] != panel.old.frozen.v1.file_hash(directory / 'request-ledger.json')
            or result['authorization_fingerprint'] != decision['content_fingerprint']):
        raise ValueError('Charged accounting/result binding changed')
    original = panel.interpret_receipts(packet, list(cache.values()))
    if any(result[key] != value for key, value in original.items()):
        raise ValueError('Original pre-review raw result reconstruction differs')
    review = gate.sealed(REVIEW)
    if (review['content_fingerprint'] != report['review_fingerprint']
            or panel.old.frozen.v1.file_hash(REVIEW) != report['review_file_sha256']):
        raise ValueError('Authored receipt-bound source review changed')
    authority = gate.ReviewAuthority.load(REVIEW, ACCEPTANCE, report['review_acceptance_file_sha256'])
    boundary = gate.Boundary(packet, authority)
    measurements = {c['case_id']: boundary.measure(c['case_id'], [cache[k] for k in c['request_keys']]) for c in packet['cases']}
    if any(m.document != o['raw_measurement'] for m, o in zip(measurements.values(), result['observations'], strict=True)):
        raise ValueError('Raw observation changed')
    validate_coverage(report, packet, review, measurements)
    replay = panel.interpret_receipts(packet, list(cache.values()), authority)
    if report['consumer_replay'] != replay['local_evidence']:
        raise ValueError('Real export/deserialize/consumer replay changed')
    for row in report['records']:
        verdict = boundary.admit(measurements[row['case_id']])
        actual = dict(status='admitted_local_only' if verdict.item else 'quarantined', reasons=list(verdict.reasons),
                      item=json.loads(verdict.item.document_json) if verdict.item else None)
        if row['admission'] != actual:
            raise ValueError('Actual admission differs from authored audit')
        # Independent reviewed whitelist, not a success inferred from guard output.
        if verdict.item and (not row['auditor_accepted_item'] or actual['item']['positive_facts'] != {'explains_text': 'linked'}
                             or actual['item']['namespace'] != 'G2_adopted_bible_explanation'
                             or actual['item']['source_voice'] != dict(left_voice='quoted_or_reported', right_voice='preacher', adoption='own_or_adopted')):
            raise ValueError('Unsupported local item admitted')
    admitted = [r for r in report['records'] if r['admission']['item']]
    namespaces = dict(Counter(r['admission']['item']['namespace'] for r in admitted))
    missing = [n for n in ('G2_adopted_bible_explanation', 'G3_current_preacher_act', 'G3_reported_local_act') if n not in namespaces]
    g3 = [r for r in report['records'] if r['capability'] == 'G3']
    summary = report['admission_summary']
    if (summary['admitted'] != len(admitted) or summary['quarantined'] != 24-len(admitted)
            or summary['by_namespace'] != namespaces or summary['admitted_case_ids'] != [r['case_id'] for r in admitted]
            or summary['missing_positive_families'] != missing or len(g3) != 13
            or not summary['all_13_G3_boundary_decisions_withheld']
            or not all(next(f['decision'] for f in r['fields'] if f['field']=='boundary') == 'unclear' for r in g3)
            or summary['unsupported_admitted'] != 0 or summary['unresolved_admitted'] != 0
            or report['raw_semantic_recommendation'] != 'FAIL' or report['containment_recommendation'] != 'HOLD'
            or report['final_raw_semantic_decision'] is not None or report['final_containment_decision'] is not None):
        raise ValueError('Admission summary or pending gate decision changed')
    return report
