"""Reviewed interpretation across existing points, never new semantic measurement.

Authored warrants are visible and provisional. Source hashes verify compatibility;
they do not establish the truth of an interpretation or confer reader acceptance.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

PATH = Path(__file__).with_name('data') / 'profile-portrait-authored-v1.json'
VERSION = 'pastor-profile-portrait-v1'


def apply(reader, packet=None):
    packet = json.loads(PATH.read_text()) if packet is None else packet
    points = {p['point_id']:p for p in reader['explanatory_descriptions']['points']}
    by_id = {c['id']:c for c in reader['claims']}
    compatible = set()
    for key,point in points.items():
        original = {k:v for k,v in point.items() if k != 'claim_id'}
        digest = hashlib.sha256(json.dumps(original,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        if packet['sources'].get(key) == digest:
            compatible.add(key)
    result = dict(version=VERSION,status='withheld_no_compatible_interpretations',
        entries=[],withheld=[],reader_acceptance=False,semantic_admission=False)
    for entry in packet['entries']:
        support = entry['support_point_ids']
        if (not support or not set(support) <= compatible or not set(support) <= set(by_id)
                or not all(entry.get(k,'').strip() for k in ('text','rationale','limits','alternative'))):
            result['withheld'].append(dict(id=entry['id'],reason='Missing, changed or incomplete reviewed support/warrant.'))
            continue
        upstream = [by_id[key] for key in support]
        evidence = list(dict.fromkeys(ref for c in upstream for ref in c['evidence_ids']))
        counter = list(dict.fromkeys(ref for c in upstream for ref in c.get('counterevidence_ids',[])))
        coverage = sorted({vid for key in support for vid in points[key]['video_ids']})
        claim = dict(id=entry['id'],wording=entry['text'],
            reason=entry['rationale']+' Limits: '+entry['limits']+' Alternative explanation: '+entry['alternative'],
            analytical_basis='reviewed_cross_point_interpretation',interpretation_status=entry['review_status'],
            interpretation_kind=entry['kind'],facet=entry['facet'],
            rule_version=VERSION,rule_id='authored-cross-point-warrant',
            evidence_ids=evidence,observation_input_ids=list(dict.fromkeys(evidence+
                [ref for c in upstream for ref in c.get('observation_input_ids',[])])),
            counterevidence_ids=counter,upstream_claim_ids=list(support),
            reviewed_binding_ids=list(dict.fromkeys(ref for key in support for ref in points[key]['reviewed_binding_ids'])),
            scope=dict(video_ids=coverage,meaning='Interpretation of selected reviewed passages, not ministry-wide stability or production admission.'),
            recording_support={str(vid):list(dict.fromkeys(ref for c in upstream for ref in c.get('recording_support',{}).get(str(vid),[]))) for vid in coverage},
            qualifications=[entry['limits'],entry['alternative']],portrait_review=deepcopy(entry))
        reader['claims'].append(claim)
        result['entries'].append(deepcopy(entry))
    reader['portrait'] = result
    if not result['entries']:
        return reader
    accepted = {entry['id']:entry for entry in result['entries']}
    assessment = [[(accepted[key]['text'],key) for key in paragraph if key in accepted]
                  for paragraph in packet['paragraphs']]
    reader['assessment'] = [paragraph for paragraph in assessment if paragraph]
    reader['assessment_scope'] = packet['scope_note']
    if result['withheld']:
        reader['assessment_scope'] += ' Some proposed interpretations are withheld because their reviewed support is unavailable or changed.'
    result['status'] = 'preliminary_portrait_pending_reader_review'
    return reader
