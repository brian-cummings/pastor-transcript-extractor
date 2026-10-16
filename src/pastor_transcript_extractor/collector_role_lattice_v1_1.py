"""Prospective, source-only role construction; no semantic sufficiency authority.

G2 indexes intact units and independent partition/completion roles. G3 selects
from qualification-connected components, never from G2's descriptor quota.
"""
from __future__ import annotations

from collections import Counter
import re
import time
from pastor_transcript_extractor import collector_role_lattice as old
from pastor_transcript_extractor import evidence_supply_source_unit_repair as substrate

VERSION = 'independent-role-qualification-lattice-v1.1'
REPORT = old.REPORT
# A detected qualification is not allowed to cross an exported core boundary.
QUALIFIER = re.compile(r'\b(?:if|unless|until|provided|although|because|whenever|when|except|otherwise|even though|as long as|only|but)\b', re.I)
COMPLEMENT = re.compile(r'(?:\b(?:that|to|from|with|of|for|as|than|whether|not|never|cannot|can.t|don.t|won.t)[;,.!?]?|[:,])\s*[“"\']?\s*$', re.I)
REFERENTIAL = re.compile(r'^(?:(?:and|but|then|so)\s+)?(?:he|she|they|it|this|that|these|those)\b|\b(?:tell|ask|remember|memorize|believe|trust|follow|do)\s+(?:him|her|them|it|this|that)\b', re.I)
SPEECH_FRAME = re.compile(r'\b(?:say|said|says|tell|told|ask|asked|pray|prayed|resolve|decide|repeat|answer|answered)\b', re.I)
FIRST_PERSON = re.compile(r'^[,;:\s“”\"\']*(?:I|we)\b',re.I)
DEPENDENT = re.compile(r'^(?:(?:and|but|then|so)\s+)?(?:if|unless|when|whenever|because|until|provided|although|even|otherwise|except|only|which|who|whose|where|what|from)\b', re.I)


def _parts(source, nodes):
    return [(i, p) for i, n in enumerate(nodes) for p in old.clause_parts(source, n)]


def components(source, nodes, *, deadline=None, route="G3"):
    """Close detected dependencies before either selector applies any quota.

    Ambiguous referring content without a structural antecedent is deferred.
    Larger completions remain hypotheses requiring semantic/source review.
    """
    raw = _parts(source, nodes)
    # Frozen retrieval-unit seams are not evidence that qualification scope
    # ended. Preserve the enclosing punctuation parent's detected qualification;
    # a leading dependent parent also needs the next parent's completion.
    parents=substrate.frozen.source_sentences(source)
    scopes=[]
    for i,parent in enumerate(parents):
        if QUALIFIER.search(parent['text']):
            end=parent['end']
            if old.DEPENDENT.search(parent['text'].lstrip('“"\'')) and i+1<len(parents):
                end=parents[i+1]['end']
            scopes.append((parent['start'],end))
    links = []
    for (_, a), (_, b) in zip(raw, raw[1:]):
        # Embedded qualifications share a source unit; leading/trailing
        # dependent clauses and required complements can cross unit seams.
        reasons = []
        if any(lo<=a['start'] and b['end']<=hi for lo,hi in scopes):
            reasons.append('qualification_preservation')
        if old.DEPENDENT.search(a['text'].lstrip('“"\'')) or DEPENDENT.search(b['text'].lstrip('“"\'')):
            reasons.append('dependent_continuation')
        if SPEECH_FRAME.search(a['text']) and FIRST_PERSON.search(b['text']):
            reasons.append('outer_speech_or_modelled_content')
        if COMPLEMENT.search(a['text']) or a['text'].rstrip().endswith('?'):
            reasons.append('required_complement_or_response')
        if route == 'G3' and REFERENTIAL.search(b['text'].lstrip('“"\'')):
            reasons.append('referent_context_required')
        # Explicit outer exhortation/modelled speech and reporting introduction
        # cannot become an independently credited quotation by cutting a colon.
        links.append(reasons)
    groups = []; blocked = []; pos = 0
    while pos < len(raw):
        if deadline is not None and time.monotonic() > deadline:
            raise ValueError('Lattice wall-time ceiling reached')
        end = pos
        while end < len(links) and links[end]:
            end += 1
        values = raw[pos:end+1]
        span = old.exact(source, values[0][1]['start'], values[-1][1]['end'])
        reasons = sorted({r for link in links[pos:end] for r in link})
        reason = None
        if span['end']-span['start'] > 6000:
            reason = 'dependency_exceeds_frame_bound'
        elif route == 'G3' and REFERENTIAL.search(values[0][1]['text'].lstrip('“"\'')):
            reason = 'unresolved_initial_referent'
        elif COMPLEMENT.search(values[-1][1]['text']) or old.DEPENDENT.search(values[-1][1]['text'].lstrip('“"\'')):
            reason = 'unresolved_required_completion'
        elif span['text'].count('“') != span['text'].count('”') or span['text'].count('"') % 2:
            reason = 'unclosed_quotation_dependency'
        entry = dict(parent=values[0][0], span=span,
            trace=dict(kind='dependency_completion' if pos != end else 'core',
                dependency_reasons=reasons, source_parts=[dict(start=p['start'], end=p['end']) for _, p in values],
                semantic_sufficiency=None, provenance=None))
        if reason:
            blocked.append(dict(parent=entry['parent'], source_span=span, reason=reason, trace=entry['trace']))
        else:
            groups.append(entry)
        pos = end+1
    return groups, blocked


def g2_roles(source, nodes, *, deadline=None):
    """Independent role lattice: intact unit/completion plus disjoint partitions.

    This function has no G3 inputs, target quota, act/core selection or rank.
    A unit that crosses a detected dependency expands to the whole component.
    """
    groups, blocked = components(source, nodes, deadline=deadline, route="G2")
    descriptors = []; primary = {}; partitions = []
    for i, node in enumerate(nodes):
        overlapping = [g['span'] for g in groups if g['span']['start'] < node['end'] and node['start'] < g['span']['end']]
        if any(b['source_span']['start'] < node['end'] and node['start'] < b['source_span']['end'] for b in blocked):
            primary[i] = None
            continue
        lo = min([node['start']]+[s['start'] for s in overlapping])
        hi = max([node['end']]+[s['end'] for s in overlapping])
        primary[i] = old.exact(source, lo, hi)
        complete = [g['span'] for g in groups if g['parent'] == i and node['start'] <= g['span']['start'] and g['span']['end'] <= node['end']]
        pair = next(((a,b) for a in complete for b in complete if a['end'] <= b['start']), None)
        if pair:
            partitions.append(dict(parent=i, left=pair[0], right=pair[1]))
        roles = [primary[i]] + (list(pair) if pair else complete[:2])
        seen = set()
        for role in roles:
            key = (role['start'], role['end'])
            if key in seen: continue
            seen.add(key)
            descriptors.append(dict(parent=i, span=role, materialization_span=role,
                materialization_available=True, kind='G2_intact_or_complete_role', descriptor_id=len(descriptors)))
    construction=[dict(g,descriptor_ids=[d['descriptor_id'] for d in descriptors if d['span']==g['span']],
        selection_status='descriptor_present' if any(d['span']==g['span'] for d in descriptors) else 'not_selected_under_intact_plus_two_partition_descriptor_budget') for g in groups]
    return dict(primary=primary, descriptors=descriptors, partition_pairs=partitions,construction=construction,
        deferred=[dict(b, capability='G2') for b in blocked])


def g3_roles(source, nodes, *, deadline=None):
    groups, blocked = components(source, nodes, deadline=deadline)
    hypotheses = []; displacement = []
    for i in range(len(nodes)):
        eligible = [g for g in groups if g['parent'] == i]
        hypotheses.extend(eligible[:2])
        for g in eligible[2:]:
            displacement.append(dict(parent=i, source_span=g['span'], reason='G3_two_per_unit_saturation',
                trace=g['trace'], structural_dependency_status='completed_no_detected_open_dependency',
                semantic_act_status='unmeasured_requires_source_review'))
    return hypotheses, displacement, [dict(b, capability='G3') for b in blocked]


def build(source, *, deadline=None):
    nodes = substrate.source_sentences(source)
    g2 = g2_roles(source, nodes, deadline=deadline)
    g3, displaced, blocked = g3_roles(source, nodes, deadline=deadline)
    if len(g2['descriptors']) > 3*len(nodes) or len(g3) > 2*len(nodes):
        raise ValueError('Lattice/target budget violated')
    return dict(version=VERSION, nodes=nodes, descriptors=g2['descriptors'], G2_primary=g2['primary'],
        G3_hypotheses=g3, G2_role_construction=g2['construction'], partition_pairs=g2['partition_pairs'], deferred=g2['deferred']+blocked,
        G3_displacements=displaced, diagnostics=dict(G3_structural_hypotheses=len(g3)+len(displaced),
            G3_retained_hypotheses=len(g3), G3_budget_displaced=len(displaced), G3_dependency_blocked=len(blocked),
            descriptor_count=len(g2['descriptors']), G2_seed_unavailable=sum(p is None for p in g2['primary'].values()),
            per_unit_saturation={str(k):v for k,v in Counter(d['parent'] for d in displaced).items()},
            identities_are_semantic=False, source_voice=None, recipient_scope=None, adoption=None))
