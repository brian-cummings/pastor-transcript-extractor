"""Exact structural hypotheses over frozen units; never semantic/provenance truth."""
from __future__ import annotations

from collections import Counter
import time
import re
from pastor_transcript_extractor import evidence_supply_source_unit_repair as substrate
from pastor_transcript_extractor import evidence_supply_collector_design as geometry

VERSION = 'coordinate-role-lattice-p1-v1'
# Grammar/turn signals only. No reference IDs, sermon phrases or act labels.
SUBJECT = r'(?:I|you|we|he|she|they|it|God|Jesus|Lord|please|let|do\s+not|don.t|remember|repent|believe|open|sing|bring)\b'
CUT = re.compile(r';\s*|(?<!\d):(?!\d)\s*|,\s+(?='+SUBJECT+r')|\b(?:and|but|yet|so)\s+(?='+SUBJECT+r')|\b(?:which\s+)?(?:means?|signifies|represents|in other words)\b', re.I)
REPORT = re.compile(r'\b(?:(?:[A-Z][a-z]+|he|she|they|I|Jesus|God)\s+(?:said|says|asked|replied|answered|told)\b|(?:according\s+to|quote|unquote)\b)', re.I)
SWITCH = re.compile(r'\b(?:Lord|Father|dear God)\b\s*[,!:]|'+REPORT.pattern, re.I)
DEPENDENT = re.compile(r'^(?:and\s+)?(?:if|unless|when|whenever|whatever|although|because|until|provided|as long as)\b', re.I)
TAIL_DEPENDENT = re.compile(r'^(?:but\s+)?(?:if|unless|provided|only\s+if|but\s+you\s+(?:must|have\s+to)|tell\s+him\s+that)\b', re.I)
FRAGMENT = re.compile(r'^(?:our\s+\w+\s+from|from\b|where\b|what\b)', re.I)


def exact(source, start, end):
    return geometry.trim_span(source['text'], start, end)


def clause_parts(source, node):
    cuts = sorted({node['start'], node['end'], *(node['start']+m.end() if m.group().strip() in (';', ':') else node['start']+m.start() for m in CUT.finditer(node['text']))})
    parts = [exact(source, a, b) for a, b in zip(cuts, cuts[1:])]
    return [p for p in parts if p]


def _requires_pair(left, right):
    if REPORT.search(left["text"]) and left["text"].rstrip().endswith(":"):
        return False
    # These are candidate dependencies, not a claim of semantic sufficiency.
    return (bool(DEPENDENT.search(left['text'].lstrip('“”"\''))) or bool(TAIL_DEPENDENT.search(right['text'].lstrip('“”"\'')))
            or left['text'].rstrip().endswith(('?', ':')) or bool(FRAGMENT.search(right['text'])))


def build(source, *, deadline=None):
    nodes = substrate.source_sentences(source)
    raw = [(i, p) for i, node in enumerate(nodes) for p in clause_parts(source, node)]
    completed = []; blocked = []
    for pos, (parent, part) in enumerate(raw):
        if deadline is not None and time.monotonic()>deadline:
            raise ValueError("Lattice wall-time ceiling reached")
        if REPORT.search(part['text']) and part['text'].rstrip().endswith(':'):
            blocked.append(dict(parent=parent, source_span=part, reason='reporting_introduction_context_only'))
            continue
        first = pos; last = pos
        # A dependent tail belongs to its immediately preceding core. A condition
        # followed by its consequence is similarly indivisible for this hypothesis.
        if pos and _requires_pair(raw[pos-1][1], part):
            first = pos-1
        while first and _requires_pair(raw[first-1][1], raw[first][1]):
            first -= 1
            if part["end"]-raw[first][1]["start"]>6000: break
        while last+1 < len(raw) and _requires_pair(raw[last][1], raw[last+1][1]):
            last += 1
            if raw[last][1]["end"]-raw[first][1]["start"]>6000: break
        values = [p for _, p in raw[first:last+1]]
        crossings = [p for p in values[1:] if SWITCH.search(p['text'])]
        # Keep the whole ambiguous core out of the selector. Never strip its
        # qualification merely because a switch/size prevented completion.
        start, end = values[0]['start'], values[-1]['end']
        if end-start > 6000 or crossings:
            blocked.append(dict(parent=parent, source_span=part,
                reason='dependency_crosses_scope_signal' if crossings else 'dependency_exceeds_frame_bound'))
            continue
        role = exact(source, start, end)
        completed.append(dict(parent=parent, span=role, trace=dict(kind='dependency_completion' if first!=last else 'core',
            source_parts=[dict(start=p['start'], end=p['end']) for p in values], semantic_sufficiency=None)))
    # Own a cross-unit completion at its first source unit; later fragments do not
    # acquire standalone claims or multiply budgets.
    by_parent = {i: [] for i in range(len(nodes))}; seen = set()
    for value in completed:
        key = (value['span']['start'], value['span']['end'])
        if key in seen: continue
        seen.add(key)
        owner = next(i for i, n in enumerate(nodes) if n['start'] <= key[0] < n['end'])
        value['parent'] = owner
        by_parent[owner].append(value)
    complete_pool=[c for values in by_parent.values() for c in values]
    descriptors = []; hypotheses = []; displacement = []; partition_pairs = []
    for i, node in enumerate(nodes):
        cores = sorted(by_parent[i], key=lambda x:(x['span']['start'], x['span']['end']))
        # At most two core/completion alternatives plus the intact indexing unit.
        keep = cores[:2]
        for c in cores[2:]:
            displacement.append(dict(parent=i, source_span=c['span'], reason='G3_two_per_unit_saturation',
                semantic_act_status='unmeasured_structural_hypothesis', trace=c['trace']))
        hypotheses.extend(keep)
        unique = {(node['start'], node['end']): dict(parent=i, span=node, kind='intact_index_unit')}
        for c in keep:
            key = (c['span']['start'], c['span']['end'])
            unique[key] = dict(parent=i, span=c['span'], kind=c['trace']['kind'])
        for d in unique.values():
            covers=[c['span'] for c in complete_pool if c['span']['start']<=d['span']['start'] and d['span']['end']<=c['span']['end']]
            d['materialization_span']=min(covers,key=lambda p:(p['end']-p['start'],p['start'])) if covers else d['span']
            d['materialization_available']=not any(b['reason'].startswith('dependency_') and b['source_span']['start']<d['span']['end'] and d['span']['start']<b['source_span']['end'] for b in blocked)
            # A unit used as a ranking feature never lends an incomplete piece of
            # a detected condition/completion as the emitted evidence role.
            descriptors.append(d)
        parts = clause_parts(source, node)
        if len(parts) >= 2:
            # First complete disjoint cores only. Do not split a required dependency.
            pair = next(((a['span'], b['span']) for a in cores for b in cores
                if a['span']['end'] <= b['span']['start'] and a['span']['start'] >= node['start']
                and b['span']['end'] <= node['end']), None)
            if pair: partition_pairs.append(dict(parent=i, left=pair[0], right=pair[1]))
    if len(descriptors)>3*len(nodes) or len(hypotheses)>2*len(nodes):
        raise ValueError('Lattice/target budget violated')
    return dict(version=VERSION, nodes=nodes, descriptors=descriptors, G3_hypotheses=hypotheses,
        partition_pairs=partition_pairs, deferred=blocked, G3_displacements=displacement,
        diagnostics=dict(G3_structural_hypotheses=len(hypotheses)+len(displacement),
            G3_retained_hypotheses=len(hypotheses), G3_budget_displaced=len(displacement),
            G3_dependency_blocked=len(blocked), descriptor_count=len(descriptors),
            per_unit_saturation=dict(Counter(x['parent'] for x in displacement)),
            identities_are_semantic=False, source_voice=None, recipient_scope=None, adoption=None))
