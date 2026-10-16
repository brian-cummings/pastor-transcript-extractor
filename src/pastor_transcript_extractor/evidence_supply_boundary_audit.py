"""Verify the authored boundary audit against frozen source and sealed local receipts.

This checks provenance and coverage, not the correctness of human source judgments.
It has no provider-execution or artifact-writing path.
"""
from __future__ import annotations

from collections import Counter
import json

from pastor_transcript_extractor import evidence_supply_boundary_validation as panel

AUDIT = panel.HERE / 'source-audit-v3.json'


def verify(base_dir=None):
    packet = json.loads(panel.INPUT.read_text())
    panel.validate_packet(packet)
    directory = panel.output_directory(base_dir)
    report = json.loads(AUDIT.read_text())
    result = json.loads((directory / 'results-v3.json').read_text())
    frozen = panel.frozen
    for value in (report, result):
        if value['content_fingerprint'] != frozen.fp({k: v for k, v in value.items() if k != 'content_fingerprint'}):
            raise ValueError('Audit/result fingerprint mismatch')
    if report['input_fingerprint'] != packet['content_fingerprint'] or report['result_fingerprint'] != result['content_fingerprint']:
        raise ValueError('Audit belongs to another input/result')
    for name, digest in report['repository_file_hashes'].items():
        path = (frozen.ROOT / name).resolve()
        if not path.is_relative_to(frozen.ROOT.resolve()) or frozen.v1.file_hash(path) != digest:
            raise ValueError('Pinned audit source changed')
    expected_files = {'results-v3.json', 'request-ledger.json'} | {
        'receipts/' + q['request_key'] + '.json' for q in packet['requests']}
    if set(report['runtime_file_hashes']) != expected_files:
        raise ValueError('Incomplete audited receipt inventory')
    for name, digest in report['runtime_file_hashes'].items():
        if frozen.v1.file_hash(directory / name) != digest:
            raise ValueError('Audited runtime artifact changed')
    ledger, cache = panel.read_cache(packet, directory)
    if len(ledger['attempts']) != 33 or len(cache) != 33:
        raise ValueError('Incomplete charged request accounting')
    rows = [dict(request_key=q['request_key'], case_id=q['case_id'], phase=q['phase'],
                 raw_answers=cache[q['request_key']]['answers'], usage=cache[q['request_key']]['usage'],
                 resolved_model=cache[q['request_key']]['model']) for q in packet['requests']]
    if panel.interpret(packet, rows) != result:
        raise ValueError('Completed result differs from exact receipt reconstruction')
    validate_coverage(report, packet, result)
    return report


def validate_coverage(report, packet, result):
    """Ensure every frozen case, field, difference, flag and supplied state is retained."""
    records = report['records']
    if [r['case_id'] for r in records] != [c['case_id'] for c in packet['cases']]:
        raise ValueError('Missing, reordered or duplicated audit case')
    for record, case, observation in zip(records, packet['cases'], result['observations'], strict=True):
        if record['frozen_case'] != case or record['guarded_local_payload'] != observation['guarded_local_payload']:
            raise ValueError('Frozen case or actual guard changed')
        requests = [dict(request_key=q['request_key'], phase=q['phase'], state=q['state'])
                    for q in packet['requests'] if q['case_id'] == case['case_id']]
        if record['request_states'] != requests:
            raise ValueError('Supplied request state changed')
        source = json.loads((panel.frozen.HERE / 'sources' / f"{case['video_id']}.json").read_text())['text']
        excerpt = record['source_excerpt']
        if source[excerpt['start']:excerpt['end']] != excerpt['text']:
            raise ValueError('Source excerpt changed')
        for span in case['candidate']['endpoints'].values():
            if span and source[span['start']:span['end']] != span['text']:
                raise ValueError('Endpoint no longer matches source')
        fields = {row['field']: row for row in record['fields']}
        if len(fields) != len(record['fields']) or set(fields) != set(observation['decisions']):
            raise ValueError('Incomplete field audit')
        for phase in observation['phases']:
            for name, decision in phase['decisions'].items():
                field = fields[name]
                raw = phase['raw_answers'].get('p0_' + name, phase['raw_answers'].get(name))
                if (field['decision'] != decision or field['phase'] != phase['phase']
                        or field['raw_choice'] != raw['choice'] or field['confidence'] != raw['confidence']
                        or field['selected_probability'] != raw['probabilities'][raw['choice']]
                        or field['probabilities'] != raw['probabilities']):
                    raise ValueError('Raw choice/probability/gated decision conflated')
                if not field['classification'] or not field['rationale']:
                    raise ValueError('Missing source judgment')
        differences = [{k: d[k] for k in ('field', 'expected', 'actual')} for d in record['prepared_differences']]
        if differences != observation['prepared_field_differences']:
            raise ValueError('Frozen prepared differences changed')
        for difference in record['prepared_differences']:
            if difference['classification'] != fields[difference['field']]['classification']:
                raise ValueError('Difference classification disagrees with field audit')
        if [a['flag'] for a in record['automatic_flags']] != observation['automatic_critical_flags']:
            raise ValueError('Automatic flag omitted')
        if record['pastor_credit'] is not False:
            raise ValueError('Audit activates pastor credit')
    counts = dict(Counter(d['classification'] for r in records for d in r['prepared_differences']))
    if (report['audited_cases'] != len(records) or report['audited_fields'] != sum(len(r['fields']) for r in records)
            or report['prepared_differences'] != sum(counts.values()) or report['difference_class_counts'] != counts
            or report['confirmed_critical_raw_cases'] != [r['case_id'] for r in records if r['confirmed_critical_raw_error']]
            or report['usage'] != result['usage'] or report['actual_list_price_usd'] != result['actual_list_price_usd']):
        raise ValueError('Audit coverage/accounting mismatch')
