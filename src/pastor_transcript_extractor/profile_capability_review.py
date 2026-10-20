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

VERSION = 'profile-next-capability-v1'
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
            threshold=o['threshold'], historical_exact_target_match=digest in inputs.get('historical_target_hashes', [])))
    return seal(dict(version=VERSION, status='READY_FOR_BOUNDED_DECISION' if cases and not excluded else 'PREPARED_CASES_INCOMPLETE',
        inventory_fingerprint=record['inventory_fingerprint'], membership_fingerprint=record['profile'].get('membership_fingerprint'),
        recommendation='Distinguish theological views the preacher personally affirms from views merely discussed, quoted or rejected.',
        reader_value='This would move the profile from what subjects occur to what is actually taught, with the qualifications that change its meaning.',
        why_first='The current profile already describes subjects, examples and practical guidance. More prose, quotations or style labels would not resolve the central uncertainty about the preacher’s own theological claims.',
        first_scope='Assurance of salvation: knowing present acceptance, possible loss, and retention, with their stated conditions. Use only the prepared passages from this sample.',
        reuse='Reuse the existing G1 bound-claim representation and its separate relation, polarity, expression, voice, adoption, conditions and scope fields. Keep the nine current salvation observations unchanged.',
        limits='G1 passed only fixed-passage feasibility and is closed. Natural discovery and coverage remain unestablished; G1 assurance discovery remains HOLD. The V3 source-only discovery review recommends HOLD, not a semantic admission decision. A1 is a bounded G3 containment decision, not authority for theological adoption. No G1 V3, replay, automatic provenance rule or upstream exact-span nomination follows.',
        proposed_delivery='A small, source-reviewed assurance account: exact supported statements, their speaker and adoption evidence, conditions and scope, plus explicit withheld readings. Codex prepares the readings and proposed bindings; Brian reviews concrete results, with no annotation or JSON authoring assigned. No eternal-security label or overall pastor position.',
        decision='Approve a provider-free, source-reviewed assurance-position pilot on these prepared passages using the existing G1 representation. No providers, new measurements, automatic binding, new doctrine vocabulary, broader collection or profile-wide projection. If the existing contract cannot represent a reading faithfully, withhold it and bring back the precise gap.',
        fields_to_preserve=['proposition', 'subject_or_referent', 'relation', 'polarity', 'expression', 'voice', 'adoption', 'binding_evidence', 'conditions_and_exceptions', 'stated_scope', 'expressed_uncertainty', 'source_identity', 'unresolved_fields'],
        acceptance_checks=['An assertion and its voice/adoption evidence are distinguished from nearby quotation or rhetorical questions.',
            'Knowing present acceptance is not converted into permanent security; conditions are preserved without inferring an opposite doctrine.',
            'Below-threshold and missing evidence never become denial; out-of-contract and incomplete-context readings stay withheld.',
            'Any supported description stays local to the exact supplied passages; no claim of complete opportunity coverage or ministry stability.',
            'No provider execution, collector change, frozen-threshold change or use of a quotation as admission authority.'],
        alternatives=[dict(capability='Pastoral tone and listener appeals', priority='Next after the bounded theological-position question', reason='Important for evaluation, but an added tone description would still leave the preacher’s own theological claims unresolved.'),
            dict(capability='Style predominance and cross-book reasoning', priority='Later interpretation/coverage work', reason='Concrete examples already give useful style information; stronger prevalence or cross-book claims need additional justified evidence.'),
            dict(capability='More sermons, quotations or comparisons', priority='Held or lower immediate value', reason='Broader coverage cannot repair missing voice/adoption binding; quotations improve presentation; comparisons lack a validated method.')],
        references=inputs.get('references', []), cases=cases, excluded_cases=excluded,
        source_identity=record['source_identity'], current_reuse_checks=record['reuse_checks'],
        existing_profile_fields=['topic_attention', 'local_treatment', 'nine_local_salvation_relationships'],
        published_position_claims=[], provider_requests=0, database_writes=0, new_measurements=False,
        automatic_adoption=False, collection=False, pilot_execution=False, quote_execution=False))


def markdown(packet):
    lines = ['# The next capability that would most improve this profile', '', packet['recommendation'], '', packet['reader_value'], '',
        '## Why this comes first', '', packet['why_first'], '', '## Smallest useful first step', '', packet['first_scope'], '', packet['proposed_delivery'], '',
        '## Concrete proposal for Brian’s decision', '', packet['decision'], '', 'No pilot has been executed. The current profile’s adopted-position fields remain unknown.', '',
        '## Prepared passages', '']
    for case in packet['cases']:
        lines += ['### '+case['title'], '', case['sermon_title']+' · '+timestamp(case['start_seconds'])+'–'+timestamp(case['end_seconds']), '',
            case['review_question'], '', '**Do not infer:** '+case['caution'], '',
            f'[Read the full passage](index.html#passage-{case["video_id"]}-{case["block_id"]}) · [Watch the passage]({case["watch_url"]})', '',
            '<details><summary>Full source passage</summary>', '', '> '+case['full_target_text'].replace('\n', '\n> '), '', '</details>', '']
    if packet['excluded_cases']:
        lines += ['Prepared cases are incomplete because source evidence changed or is unavailable. No replacement was silently selected.', '']
    lines += ['## Why not another capability first?', '']
    for option in packet['alternatives']:
        lines += ['- **'+option['capability']+'** — '+option['reason']]
    lines += ['', '## Reuse and boundaries', '', packet['reuse'], '', packet['limits'], '',
        'The existing materialized profile supplies topic/treatment/local salvation findings, not bound adopted positions. The prepared windows were compared with the exact target texts of the closed G1 pilot; a nonmatch is not a global cache-absence claim, and a match would still require compatible question, model, context and source provenance before reuse.', '',
        '## Acceptance criteria for the proposed pilot', '']
    lines += ['- '+check for check in packet['acceptance_checks']]
    lines += ['', '<details><summary>Technical details</summary>', '', '```json', json.dumps(dict(status=packet['status'], references=packet['references'],
        field_requirements=packet['fields_to_preserve'], excluded_cases=packet['excluded_cases'], current_reuse_checks=packet['current_reuse_checks']), indent=2, ensure_ascii=False), '```', '', '</details>', '',
        'Reproduce the profile and this packet with:', '', '```bash', 'pte analysis structure-readiness --segment-view --description --json', '```', '']
    return '\n'.join(lines)
