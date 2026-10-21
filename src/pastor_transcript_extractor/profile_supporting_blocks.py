"""Select complete illustrative blocks from established profile support sets.

This is presentation assembly, not classification or quotation extraction. Topic
examples illustrate attention; local relationship examples do not imply adoption.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib

VERSION = 'point-linked-supporting-blocks-v1'


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _review_matches(review, observation):
    expected = dict(evidence_id=observation['id'], video_id=observation['video_id'],
        block_id=observation['block_id'], dimension=observation['field'],
        source_sha256=observation.get('source_sha256'),
        start_seconds=observation.get('start_seconds'), end_seconds=observation.get('end_seconds'),
        target_sha256=_digest(observation.get('full_target_text', '')))
    return all(review.get(key) == value for key, value in expected.items())


def build(record):
    """Return one example record per established raw/reader claim, without I/O.

    Select at most one complete block for each recording/layer/field in the
    existing support set. Thus a multi-part point retains examples of each part,
    and one example never stands in for membership across several recordings.
    Existing local observation strength breaks salvation ties; other ties use
    time and block ID. No new semantic cutoff or probability pooling is used.
    """
    observations = {o['id']: o for o in record['observations']}
    if len(observations) != len(record['observations']):
        raise ValueError('Duplicate observation identity in supporting blocks')
    sources = {s['video_id']: s for s in record['source_identity']}
    raw = {c['id']: c for c in record['claims']}
    reader = record.get('reader', {})
    reviews = {r['evidence_id']: r for r in reader.get('source_reviews', [])}
    established = defaultdict(set)
    for claim in raw.values():
        if claim.get('rule') == 'topic' and claim.get('support_state') == 'supported_cached_description':
            established['topic'].update(claim['evidence_ids'])
        elif claim.get('rule') == 'salvation' and claim.get('support_state') == 'supported_local_observation':
            established['salvation'].update(claim['evidence_ids'])

    def eligibility(o):
        source = sources.get(o['video_id'])
        if not source or source.get('gate', {}).get('eligible') is not True:
            return 'Source is not eligible in the current profile membership.'
        if source.get('source_sha256') != o.get('source_sha256') or source.get('source_path') != o.get('source_path'):
            return 'Observation does not match the current source identity.'
        if not o.get('full_target_text', '').strip() or o.get('start_seconds', 0) >= o.get('end_seconds', 0):
            return 'Complete source text or valid source bounds are unavailable.'
        if o.get('eligibility', {}).get('eligible') is False or o.get('projection_eligibility', {}).get('eligible') is False:
            return 'Observation is explicitly ineligible.'
        layer = o.get('layer')
        if layer == 'topic' and o['id'] in established['topic'] and o.get('state') == 'measured':
            return None
        if layer == 'salvation' and o['id'] in established['salvation'] and o.get('state') == 'observed':
            return None
        if layer == 'treatment' and o['id'] in reviews and _review_matches(reviews[o['id']], o):
            return None
        return 'No compatible established point support: topic proximity, candidates and unadmitted observations are insufficient.'

    windows = defaultdict(list)
    for o in observations.values():
        windows[(o['video_id'], o['block_id'])].append(o)
    result = []
    all_claims = list(raw.values()) + reader.get('claims', [])
    if len({c['id'] for c in all_claims}) != len(all_claims):
        raise ValueError('Duplicate claim identity in supporting blocks')
    for claim in all_claims:
        is_raw = claim['id'] in raw
        refs = list(dict.fromkeys(claim.get('evidence_ids', [])))
        upstream = [raw[key] for key in claim.get('upstream_claim_ids', []) if key in raw]
        counter = list(dict.fromkeys(claim.get('counterevidence_ids', []) + [key for c in upstream for key in c.get('counterevidence_ids', [])]))
        qualifications = list(dict.fromkeys(text for text in [claim.get('uncertainty'), claim.get('reason'), *[c.get('uncertainty') for c in upstream],
            'Examples illustrate this point within the selected recordings; selection does not establish frequency, coverage or ministry-wide stability.'] if text))
        groups = defaultdict(list)
        withheld = []
        for key in refs:
            o = observations.get(key)
            reason = 'Supporting observation is unavailable.' if o is None else eligibility(o)
            if is_raw and (claim.get('rule'), claim.get('support_state')) not in (
                    ('topic', 'supported_cached_description'), ('salvation', 'supported_local_observation')):
                reason = 'This raw claim has no established example-selection rule.'
            if reason:
                withheld.append(dict(evidence_id=key, reason=reason))
            else:
                groups[(o['video_id'], o['layer'], o['field'])].append(o)
        selected = []
        for group in sorted(groups):
            chosen = min(groups[group], key=lambda o: (-o['value'] if o['layer'] == 'salvation' else 0,
                o['start_seconds'], o['block_id'], o['id']))
            # The canonical passage renderer groups observations by source block.
            # Refuse inconsistent copies rather than select/render different text.
            geometry = ('source_sha256', 'source_path', 'start_seconds', 'end_seconds', 'segment_indexes', 'full_target_text')
            if any(any(o.get(k) != chosen.get(k) for k in geometry) for o in windows[(chosen['video_id'], chosen['block_id'])]):
                raise ValueError('Conflicting source block copies in supporting observations')
            layer = chosen['layer']
            reason = {'topic': 'Existing representative support for topic attention; this does not establish agreement with the views discussed.',
                'salvation': 'An existing observed local relationship supports this descriptive point; this does not establish preacher adoption or polarity.',
                'treatment': 'An exact source-reviewed passage illustrates this treatment; a candidate probability alone supplies no authority.'}[layer]
            selected.append(dict(evidence_id=chosen['id'], evidence_ids=sorted(o['id'] for o in groups[group] if o['block_id'] == chosen['block_id']),
                video_id=chosen['video_id'], block_id=chosen['block_id'],
                passage_id=f'passage-{chosen["video_id"]}-{chosen["block_id"]}',
                **{k: deepcopy(chosen.get(k)) for k in geometry},
                target_sha256=_digest(chosen['full_target_text']), watch_url=chosen.get('watch_url'),
                eligibility=dict(eligible=True, basis='Current eligible source and established claim support set'),
                support_reason=reason, qualifications=qualifications,
                source_review=deepcopy(reviews.get(chosen['id'])) if layer == 'treatment' else None))
        result.append(dict(claim_id=claim['id'], rule_id=claim.get('rule', claim.get('rule_version')),
            selection_rule_version=VERSION, point=claim['wording'],
            status='partial' if selected and withheld else 'selected' if selected else 'unknown',
            reason='Selection uses only this established point’s eligible support set; no new text search or semantic inference.' if selected else 'No eligible authoritative supporting block is available.',
            eligible_observation_ids=sorted(o['id'] for values in groups.values() for o in values),
            recording_ids=sorted({o['video_id'] for values in groups.values() for o in values}),
            qualifications=qualifications, counterevidence_ids=counter,
            withheld_observations=withheld, selected_blocks=selected))
    return result
