"""Recording-first membership summaries over existing descriptive claims.

This is an auditable presentation rule, not a measurement or semantic classifier.
A retained counterevidence reference has its upstream meaning; it is not a claim
that the preacher refutes a proposition. Missingness never becomes disagreement.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib

VERSION = 'recording-first-membership-v1'


def build(record, reader_claims):
    observations = {o['id']: o for o in record['observations']}
    source_ids = sorted(s['video_id'] for s in record['source_identity'])
    positive = set(ref for c in reader_claims for ref in c['evidence_ids'])
    # Raw cached answers have no new admission authority at this consumer.
    positive = {ref for ref in positive if observations[ref]['layer'] != 'cached_leaf'
        and observations[ref].get('state') not in ('measured_below_threshold', 'measured_not_admitted')}
    counters = set(ref for c in record['claims'] for ref in c.get('counterevidence_ids', []))
    windows = defaultdict(list)
    for o in observations.values():
        # Exact source geometry establishes one window even if several observations
        # reference it. Equal complete text records known repeated content, without
        # claiming that recordings are independent teaching occasions.
        text = o.get('full_target_text')
        identity = ('text', hashlib.sha256(text.encode()).hexdigest()) if text else (
            'window', o['video_id'], o.get('source_sha256'), o['block_id'],
            o.get('start_seconds'), o.get('end_seconds'))
        windows[identity].append(o['id'])
    duplicate_groups = [dict(observation_ids=sorted(refs),
        video_ids=sorted({observations[ref]['video_id'] for ref in refs}),
        reason='Same complete source text or source window; not independent evidence.')
        for refs in windows.values() if len({(observations[ref]['video_id'], observations[ref]['block_id']) for ref in refs}) > 1]
    recordings = []
    for vid in source_ids:
        local = [o for o in observations.values() if o['video_id'] == vid]
        states = defaultdict(list)
        for o in local:
            states[o.get('state', 'unspecified')].append(o['id'])
        recordings.append(dict(video_id=vid,
            supported_observation_ids=sorted(o['id'] for o in local if o['id'] in positive),
            counterevidence_ids=sorted(o['id'] for o in local if o['id'] in counters),
            observation_states={state: sorted(refs) for state, refs in sorted(states.items())},
            salvation_block_states=[dict(item) for item in record.get('salvation_block_states', []) if item['video_id'] == vid],
            unresolved_leaves=list(record.get('unresolved_leaves', [])),
            reader_claim_ids=[c['id'] for c in reader_claims if any(observations[ref]['video_id'] == vid for ref in c['evidence_ids'])]))
    groups = defaultdict(dict)
    for recording in recordings:
        for ref in recording['supported_observation_ids']:
            o = observations[ref]
            groups[(o['layer'], o['field'])].setdefault(recording['video_id'], []).append(ref)
    patterns = []
    for (layer, field), members in sorted(groups.items()):
        all_refs = [ref for refs in members.values() for ref in refs]
        patterns.append(dict(id=f'pattern-{layer}-{field}', layer=layer, field=field,
            video_ids=sorted(members), by_recording=members,
            status='supported_in_each_selected_recording' if len(members) == len(source_ids) else 'supported_in_named_recordings',
            recordings_without_support=sorted(set(source_ids)-set(members)),
            counterevidence_ids=sorted(ref for ref in counters if observations.get(ref, {}).get('layer') == layer and observations[ref]['field'] == field),
            evidence_ids=sorted(all_refs), rule_id=VERSION,
            withholding='No support in a recording means this rule supplies no claim there; not absence, denial or an opposing position.'))
    return dict(version=VERSION, interpretation_status='proposed deterministic descriptive rule; reviewable, not semantic admission',
        recordings=recordings, patterns=patterns, duplicate_content_groups=duplicate_groups,
        scope='Membership in these selected recordings only; independence, opportunity coverage and chronological change are unknown.',
        deduplication='Each recording contributes membership once per field. Repeated observation references and exact repeated full blocks are not additional teaching occasions.',
        counterevidence_meaning='Upstream counterevidence is retained with its original meaning; no support/refutation or adoption is inferred.',
        withholding='Unrouted, missing compatible results, below threshold, not admitted and unresolved remain distinct; no frequency, intensity, dominance, ministry stability or stance rule.')
