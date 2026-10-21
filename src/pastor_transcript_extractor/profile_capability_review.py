"""Concrete, provider-free recommendation from the working profile's gaps.

This is a decision packet, not a bound-claim collector or profile-position engine.
It never invokes the closed G1/G2/G3 pilots or changes measurement admission.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.segment_profile_view import short_title, timestamp

VERSION = 'profile-next-capability-v2'
CASES_PATH = Path(__file__).with_name('data') / 'profile-capability-cases-v1.json'
REFERENCES = (
    'docs/review-proposals/g1-binding-v1/CONTRACT.md',
    'evaluation/g1-binding/feasibility-stage-gate-v2.json',
    'docs/review-proposals/g1-feasibility-v2/input-v2.json',
    'docs/review-proposals/fresh-discovery-readiness-v3/source-review-v3.json',
    'docs/review-proposals/g3-atomic-admission-v1/acceptance-decision-a1.json',
)


def load_inputs():
    inputs = json.loads(CASES_PATH.read_text())
    references = []
    for relative in REFERENCES:
        path = trace.ROOT / relative
        row = dict(path=relative, sha256=trace.digest(path))
        if path.suffix == '.json':
            value = trace.read(path, True)
            row.update(version=value['version'], status=value['status'])
        references.append(row)
    gate = trace.read(trace.ROOT / REFERENCES[1], True)
    if gate['status'] != 'PASS' or not gate['closed']:
        raise ValueError('The bounded G1 historical decision changed; review the recommendation')
    accepted = trace.read(trace.ROOT / REFERENCES[2], True)
    if accepted['content_fingerprint'] != gate['input_fingerprint']:
        raise ValueError('G1 contract input does not match its closed decision')
    inputs['references'] = references
    inputs['historical_target_hashes'] = [hashlib.sha256(c['target_text'].encode()).hexdigest() for c in accepted['cases']]
    return inputs


def build(record, inputs=None):
    inputs = inputs or {}
    observations = {o['id']: o for o in record['observations']}
    titles = {s['video_id']: short_title(s['title']) for s in record['source_identity']}
    cases = []
    excluded = []
    for prepared in inputs.get('cases', []):
        o = observations.get(prepared['evidence_id'])
        if o is None or o['layer'] != 'salvation' or o['field'] != 'assurance_security':
            excluded.append(dict(evidence_id=prepared['evidence_id'], reason='missing_current_assurance_observation'))
            continue
        digest = hashlib.sha256(o['full_target_text'].encode()).hexdigest()
        if o['source_sha256'] != prepared['source_sha256'] or digest != prepared['target_sha256']:
            excluded.append(dict(evidence_id=prepared['evidence_id'], reason='source_or_target_changed'))
            continue
        if prepared.get('proposed_position') is not None:
            raise ValueError('A capability review case must not populate a theological position')
        cases.append(dict(**prepared, video_id=o['video_id'], block_id=o['block_id'], sermon_title=titles[o['video_id']],
            start_seconds=o['start_seconds'], end_seconds=o['end_seconds'], watch_url=o['watch_url'],
            full_target_text=o['full_target_text'], current_state=o['state'], probability=o['value'],
            threshold=o['threshold'], opportunity_status='not_established', historical_exact_target_match=digest in inputs.get('historical_target_hashes', [])))
    gaps = [dict(gap) for gap in record['gaps']]
    return seal(dict(version=VERSION, status='SUPPORTED_PROFILE_WITH_CONSEQUENTIAL_GAPS',
        inventory_fingerprint=record['inventory_fingerprint'], membership_fingerprint=record['profile'].get('membership_fingerprint'),
        recommendation='Review the supported sample profile and its evidence; resolve only demonstrated gaps at their responsible upstream producer.',
        reader_value='The assessment combines existing observations, shows what differs across these recordings, and supplies full supporting passages. Unsupported conclusions remain visible.',
        why_first='Existing evidence integration, conservative aggregation and point-linked examples are the active product path. A missing semantic distinction is a conditional upstream repair, not another end-stage extraction project.',
        first_scope='Profile 318’s selected recordings and existing compatible observations. No additional recordings, inference calls or new measurement meanings.',
        reuse='Reuse existing G1/G2/G3 contracts and source-reviewed proposals only within their actual scopes, alongside compatible category-leaf results. A missing full-pack cache is not proof that constituent answers are absent. Keep the nine current salvation observations unchanged.',
        limits='The previous source-review pilot and extraction experiments are historical results, not new execution instructions. G1 discovery remains HOLD. No G1 V3, replay, automatic provenance rule, new measurement or upstream exact-span nomination follows. No provider/model calls, broader collection, production admission, benchmark/ranking or Ollama quotation execution.',
        proposed_delivery='Review the current runnable profile, recording comparison, supporting blocks and consequential-gap map. Codex owns interpretation and prepares precise upstream remedies; Brian runs the bounded command and reviews concrete results.',
        decision='Review the concrete profile. No fresh pilot authorization is requested. A held repair requires a named blocked statement, inspected reuse outcomes, exact missing field, responsible producer, smallest proposed change and acceptance/failure controls before a separate decision.',
        cases_role='Historical prepared assurance contrasts; not newly executed or automatically adopted findings.',
        prepared_cases_status='source_current' if cases and not excluded else 'incomplete_or_not_supplied',
        fields_to_preserve=['proposition', 'subject_or_referent', 'relation', 'polarity', 'expression', 'voice', 'adoption', 'binding_evidence', 'conditions_and_exceptions', 'stated_scope', 'expressed_uncertainty', 'source_identity', 'unresolved_fields'],
        acceptance_checks=['Each substantive profile statement traces to a descriptive rule and compatible eligible observations.',
            'Missing support/refutation, speaker/adoption and attached qualifications belong at the responsible upstream leaf or shared binding producer.',
            'Below-threshold and missing evidence never become denial; out-of-contract and incomplete-context readings stay withheld.',
            'Recording membership and example selection do not establish independent recurrence, complete coverage or ministry stability.',
            'No provider execution, collector change, frozen-threshold change or use of a quotation as admission authority.'],
        alternatives=[dict(capability='Specific upstream semantic repair', priority='Conditional', reason='Only after a consequential statement remains unsupported following compatible evidence reuse.'),
            dict(capability='Optional illustrative quotations', priority='Held', reason='Select a relevant contiguous statement from an established point’s supporting block; never supply missing analytical authority.'),
            dict(capability='More sermons or comparisons', priority='Held', reason='Coverage and comparability need their own authorized work; neither is an integration prerequisite.')],
        references=inputs.get('references', []), cases=cases, excluded_cases=excluded,
        source_identity=record['source_identity'], current_reuse_checks=record['reuse_checks'],
        evidence_supply=record.get('evidence_supply', {}), consequential_gaps=gaps,
        existing_profile_fields=['topic_attention', 'local_treatment', 'nine_local_salvation_relationships'],
        published_position_claims=[], provider_requests=0, database_writes=0, new_measurements=False,
        automatic_adoption=False, collection=False, pilot_execution=False, quote_execution=False))



def markdown(packet):
    lines = ['# Profile review and consequential next steps', '', packet['recommendation'], '', packet['reader_value'], '',
        '## Current delivery', '', packet['why_first'], '', packet['first_scope'], '', packet['proposed_delivery'], '',
        '## Next action', '', packet['decision'], '',
        '## Consequential gaps and insertion points', '']
    for gap in packet['consequential_gaps']:
        lines += ['### '+gap['withheld'], '', gap['reader_impact'], '',
            'Missing: '+gap['cause'], '', 'Existing reuse: '+gap['reuse'], '',
            'Smallest remedy: '+gap.get('smallest_change', gap['remedy']), '',
            'Responsible producer: '+str(gap.get('upstream_owner', gap['work_kind'])), '',
            'Boundary: '+str(gap.get('boundary', gap['work_kind'])), '',
            '<details><summary>Inspected reuse and exact missing information</summary>', '', '```json',
            json.dumps(gap, indent=2, ensure_ascii=False), '```', '', '</details>', '']
    if packet['cases']:
        lines += ['## Historical prepared assurance contrasts', '', packet['cases_role'], '']
    for case in packet['cases']:
        lines += ['### '+case['title'], '', case['sermon_title']+' · '+timestamp(case['start_seconds'])+'–'+timestamp(case['end_seconds']), '',
            case['review_question'], '', '**Do not infer:** '+case['caution'], '',
            f'[Read the full passage](index.html#passage-{case["video_id"]}-{case["block_id"]}) · [Watch the passage]({case["watch_url"]})', '',
            '<details><summary>Full source passage</summary>', '', '> '+case['full_target_text'].replace('\n', '\n> '), '', '</details>', '']
    if packet['excluded_cases']:
        lines += ['Historical prepared cases are incomplete because source evidence changed or is unavailable. No replacement was silently selected.', '']
    lines += ['## Reuse and boundaries', '', packet['reuse'], '', packet['limits'], '',
        '## Acceptance checks', '']
    lines += ['- '+check for check in packet['acceptance_checks']]
    lines += ['', '<details><summary>Technical details</summary>', '', '```json', json.dumps(dict(status=packet['status'], references=packet['references'],
        field_requirements=packet['fields_to_preserve'], excluded_cases=packet['excluded_cases'], current_reuse_checks=packet['current_reuse_checks']), indent=2, ensure_ascii=False), '```', '', '</details>', '',
        'Reproduce the profile and this packet with:', '', '```bash', 'pte analysis structure-readiness --segment-view --description --json', '```', '']
    return '\n'.join(lines)
