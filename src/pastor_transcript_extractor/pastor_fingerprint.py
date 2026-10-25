"""Deterministic sample-scoped qualified fingerprints, shared by all consumers."""
from __future__ import annotations
from dataclasses import asdict
from collections import defaultdict
import math
from .pastor_evidence import digest

VERSION = 'pastor-fingerprint-v1'
DIMENSION_POLICY = 'hierarchy-unique-feature-v1'
ROOTS = ('theology', 'theological_emphasis', 'biblical_interpretation', 'christian_living',
         'pastoral_orientation', 'social_worldview', 'preaching_communication')
QUALIFIED_FIELDS = ('proposition', 'referents', 'modality', 'quantifiers', 'conditions',
                    'exceptions', 'temporal_scope', 'scope')


def ancestors(path):
    parts = path.split('/')
    if parts[0] not in ROOTS or any(not p or p in ('.', '..') for p in parts):
        raise ValueError('Unsupported hierarchy path')
    return ['/'.join(parts[:i]) for i in range(1, len(parts)+1)]


def aggregate_occurrences(rows):
    """Set union by literal source/coordinates, independent of repeated window IDs."""
    unique = {}
    for row in rows:
        key = digest({k:row[k] for k in ('video_id', 'block_id', 'target_sha256', 'local_start', 'local_end')})
        unique[key] = {k:row[k] for k in ('video_id', 'block_id', 'target_sha256', 'local_start', 'local_end')}
    return [unique[k] for k in sorted(unique)]


def qualified_key(meaning):
    if set(meaning) != set(QUALIFIED_FIELDS) or not meaning['proposition'] or not meaning['scope']:
        raise ValueError('Alignment must preserve every qualified semantic field')
    return digest(meaning)


def _aligned(row):
    alignment = row.get('alignment', {})
    meaning = alignment.get('meaning')
    if meaning is None:
        return None, [], False
    key = qualified_key(meaning)
    paths = sorted(set(alignment['paths']))
    for path in paths: ancestors(path)
    verified = (alignment.get('resolved') is True and
                type(alignment.get('probability')) in (int, float) and
                .9 <= alignment['probability'] <= 1 and bool(alignment.get('evidence')))
    return key, paths, verified


def build_fingerprint(sample, evidence_view, dimension_policy=DIMENSION_POLICY, *, measurements=()):
    if dimension_policy != DIMENSION_POLICY:
        raise ValueError('Unknown dimension policy')
    unique = {}
    for row in evidence_view.observations:
        if row['id'] in unique and unique[row['id']] != row:
            raise ValueError('Conflicting observation identity')
        unique[row['id']] = row
    from dataclasses import replace
    evidence_view = replace(evidence_view, observations=tuple(unique[k] for k in sorted(unique)))
    accepted, excluded = evidence_view.partition()
    admitted = {r['id'] for r in accepted}
    frames, assignments, unknown = {}, {}, []
    for row in sorted(evidence_view.observations, key=lambda r:r['id']):
        if any(ref['video_id'] not in sample.video_ids for ref in row['source_refs']):
            raise ValueError('Evidence outside sample')
        key, paths, verified = _aligned(row)
        if key is None:
            unknown.append(dict(id=row['id'], reason='unresolved_canonicalization'))
            continue
        meaning = row['alignment']['meaning']
        frame = frames.setdefault(key, dict(id=key, meaning=meaning, paths=[], A=[], D=[], U=[],
            evidence_ids=[], withheld=[], alignment_decisions=[]))
        frame['paths'] = sorted(set(frame['paths']) | set(paths))
        frame['evidence_ids'].append(row['id'])
        frame['alignment_decisions'].append(row['alignment'])
        binding = row['binding']
        usable = (row['id'] in admitted and verified and binding['voice']['occurrence'] == 'actual'
                  and binding['adoption']['status'] in ('own_assertion', 'adopted')
                  and binding['expression']['value'] == 'assertion')
        state = {'affirmed':'A', 'denied':'D'}.get(binding['polarity']['value']) if usable else None
        frame[state or 'U'].extend(row['source_refs'])
        if not usable or state is None:
            frame['withheld'].append(dict(id=row['id'], reason='unverified_unadopted_or_unresolved'))
    for frame in frames.values():
        for state in ('A', 'D', 'U'): frame[state] = aggregate_occurrences(frame[state])
        frame['state'] = [int(bool(frame['A'])), int(bool(frame['D']))]
        frame['evidence_ids'] = sorted(set(frame['evidence_ids']))
    # Measurements retain independent estimands, contract identity and per-recording exposure.
    features = {}
    for raw in sorted(measurements, key=digest):
        row = dict(raw)
        if row['video_id'] not in sample.video_ids:
            raise ValueError('Measurement outside declared sample')
        if row['operator'] not in ('emphasis', 'relation', 'form'):
            raise ValueError('Unsupported measured operator')
        if row['operator'] == 'emphasis' and row['estimand'] not in (
                'normalized_expected_prominence', 'developed_emphasis_probability'):
            raise ValueError('Raw leaf confidence is not attention')
        if row['operator'] in ('relation', 'form') and (row.get('assessed') is not True or
                row.get('denominator', 0) <= 0 or not row.get('unit') or not row.get('exposure')):
            raise ValueError('Relation/form needs assessed opportunities and exposure')
        value = row['value']
        if type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('Feature outside bounded measurement meaning')
        for path in row['paths']: ancestors(path)
        identity = (row['operator'], row['id'])
        feature = features.setdefault(identity, dict(id=row['id'], operator=row['operator'],
            contract=row['contract'], estimand=row['estimand'], paths=[], recordings={}))
        if (feature['contract'],feature['estimand']) != (row['contract'],row['estimand']):
            raise ValueError('Conflicting feature contracts')
        feature['paths'] = sorted(set(feature['paths']) | set(row['paths']))
        prior = feature['recordings'].get(str(row['video_id']))
        if prior and prior != row:
            raise ValueError('Conflicting same-sermon feature; aggregate at responsible producer')
        feature['recordings'][str(row['video_id'])] = row
    for feature in features.values():
        feature['value'] = sum(r['value'] for r in feature['recordings'].values())/len(feature['recordings'])
        feature['measured_sermons'] = len(feature['recordings'])
        feature['missing_sermons'] = sorted(set(sample.video_ids)-{int(v) for v in feature['recordings']})
    paths = set(ROOTS)
    for row in [*frames.values(), *features.values()]:
        for path in row['paths']: paths.update(ancestors(path))
    for path in sorted(paths):
        assignments[path] = dict(position=sorted(k for k,r in frames.items()
            if any(p==path or p.startswith(path+'/') for p in r['paths'])),
            **{op:sorted(r['id'] for r in features.values() if r['operator']==op
                and any(p==path or p.startswith(path+'/') for p in r['paths'])
                and (op!='emphasis' or r['estimand']=='normalized_expected_prominence'))
                for op in ('emphasis','relation','form')})
    result = dict(schema_version=VERSION, profile_id=sample.profile_id, sample_spec=asdict(sample),
        membership_fingerprint=sample.membership_fingerprint, input_run_ids=list(sample.input_run_ids),
        evidence_policy=asdict(evidence_view.policy), dimension_policy=dimension_policy,
        claim_frames=frames, evidence_observations=list(evidence_view.observations),
        evidence_relations=[dict(observation_id=r['id'],relations=r['binding']['development_relations'],
            address_acts=r['binding']['address_acts']) for r in evidence_view.observations], features={op:{r['id']:r for r in features.values() if r['operator']==op}
            for op in ('emphasis','relation','form')}, dimension_views=assignments,
        source_coverage=dict(video_ids=list(sample.video_ids), observed_occurrences=aggregate_occurrences(
            [ref for row in evidence_view.observations for ref in row['source_refs']])),
        uncertainty=dict(independence=sample.occasion_independence, model='uncalibrated_field_judgments',
                         scope='declared_sample_only'), missingness=dict(excluded=excluded, unaligned=unknown))
    result['derivation_fingerprint'] = digest(result)
    return result


def project_dimension(fingerprint, path):
    ancestors(path)
    return fingerprint['dimension_views'].get(path, dict(position=[], emphasis=[], relation=[], form=[]))


def topic_measurements(video_id, measurements, contract, source_refs):
    """Adapt existing source projection; preserve the two separate topic estimands."""
    for topic, values in sorted(measurements.items()):
        for estimand in ('normalized_expected_prominence', 'developed_emphasis_probability'):
            if estimand not in values: continue
            yield dict(id=f'T:{topic}:{estimand}', video_id=video_id, operator='emphasis',
                estimand=estimand, value=values[estimand], contract=contract,
                paths=[f'theological_emphasis/{topic}'], source_refs=source_refs,
                eligible_duration=values.get('eligible_duration_seconds'),
                measured_duration=values.get('measured_duration_seconds'))
