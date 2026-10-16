"""Bounded G2/G3 source-only nomination. No model/admission/benchmark authority."""
from __future__ import annotations
from collections import Counter
import math
import time

from pastor_transcript_extractor import collector_role_lattice as lattice
from pastor_transcript_extractor import evidence_supply_collector_design as geometry
from pastor_transcript_extractor import evidence_supply_source_unit_repair as substrate
from pastor_transcript_extractor import evidence_supply_revision as spans

VERSION = 'directed-role-atomic-core-retrieval-v1'
POLICY = dict(version=VERSION, G2_per_unit=8, G3_per_unit=2, descriptors_per_unit=3,
    local_lane_per_unit=2, partition_lane_per_unit=2, concept_lane_per_unit=4,
    source_candidate_ceiling=12000, total_candidate_ceiling=20000, G1_source_ceiling=200,
    max_frame_chars=6000, max_envelope_chars=6000, comparisons_per_source=8000000)


def structural_preflight(source):
    n = len(substrate.source_sentences(source))
    if 10*n>12000: raise ValueError('Source-derived candidate ceiling exceeded; no truncation')
    if 3*n*n>POLICY['comparisons_per_source']: raise ValueError('Index comparison preflight exceeded')
    return dict(video_id=source['video_id'], unit_count=n, descriptors_max=3*n,
        G2_max=8*n, G3_max=2*n, G2_G3_max=10*n,
        comparisons_max=3*n*n, encoded_tokens_max=3*n*256)


def cosine(a, b):
    if len(a)!=len(b) or not a: raise ValueError('Inconsistent rank vector width')
    norm = math.sqrt(math.fsum(x*x for x in a)*math.fsum(y*y for y in b))
    if norm==0 or not math.isfinite(norm): raise ValueError('Invalid rank vector')
    value = math.fsum(x*y for x,y in zip(a,b))/norm
    if not math.isfinite(value): raise ValueError('Nonfinite similarity')
    return round(value, 6)


def automatic_envelope(source, candidate, nodes):
    frame = candidate['relation_frame']; text=source['text']
    # Preserve the nearest structural reporting introduction (within the existing
    # bound) and known named attribution. Neither is a resolved source identity.
    marks = list(lattice.REPORT.finditer(text, max(source['main_span']['start'], frame['start']-6000), frame['start']))
    required_start=frame['start']
    if marks:
        mark=marks[-1]
        previous=next((n for n in nodes if n['start']<=mark.start()<n['end']), None)
        required_start=min(required_start, previous['start'] if previous else mark.start())
    if frame['end']-required_start>6000:
        return dict(status='deferred', reason='reporting_context_exceeds_envelope_bound')
    before=[n for n in nodes if n['end']<=required_start][-2:]
    after=[n for n in nodes if n['start']>=frame['end']][:1]
    lo=before[0]['start'] if before else required_start
    hi=after[-1]['end'] if after else frame['end']
    if hi-lo>6000: hi=frame['end']
    if hi-lo>6000: lo=required_start
    return dict(status='prepared_not_attested', start=lo, end=hi, text=text[lo:hi],
        required_structural_context_start=required_start, source_voice=None,
        recipient_scope=None, atomic_sufficiency=None, reporting_context_complete=None,
        requires_source_review=True)


def discover(source, encoder, *, deadline=None):
    token_start=getattr(encoder,'tokens',0)
    size=structural_preflight(source); graph=lattice.build(source,deadline=deadline); nodes=graph['nodes']
    deferred=list(graph['deferred']); diagnostics=[]; candidates=[]; seen=set(); lanes=Counter()
    def check_time():
        if deadline is not None and time.monotonic()>deadline:
            raise ValueError('Development wall-time ceiling reached; no partial result credit')
    vectors=[]
    for item in graph['descriptors']:
        check_time(); value=encoder.encode(item['span']['text'])
        if value is None:
            deferred.append(dict(reason='encoder_token_limit_ranking_descriptor_deferred', source_span=item['span'], parent=item['parent']))
        vectors.append(value)
    by_parent={i:[j for j,d in enumerate(graph['descriptors']) if d['parent']==i] for i in range(len(nodes))}
    cores={i:[h for h in graph['G3_hypotheses'] if h['parent']==i] for i in range(len(nodes))}
    primary={i:(cores[i][0]['span'] if cores[i] else None) for i in cores}
    def emit(cap, endpoints, lane, parent):
        check_time()
        key=spans.fp(dict(version=VERSION, source=source['video_id'], capability=cap, endpoints=endpoints))
        if key in seen:
            diagnostics.append(dict(parent=parent, lane=lane, reason='duplicate_geometry_no_refill'))
            return
        seen.add(key)
        c=geometry.represent(source,cap,endpoints)
        if c['status']=='deferred':
            deferred.append(dict(c, capability=cap, lane=lane, parent=parent)); return
        env=automatic_envelope(source,c,nodes)
        if env['status']=='deferred':
            deferred.append(dict(reason=env['reason'], capability=cap, endpoints=endpoints, lane=lane, parent=parent)); return
        c.update(candidate_id=f"{source['video_id']}:{cap}:{key[:16]}", builder_version=VERSION,
            selection=lane, parent_unit=parent, source_hypothesis_only=True,
            automatic_provenance_attestation=False, reference_policy='P1', automatic_envelope=env)
        candidates.append(c); lanes[lane]+=1
    def pair(a,b,lane,parent):
        emit('G2',dict(left=a,right=b),lane,parent)
        emit('G2',dict(left=b,right=a),lane,parent)
    for item in graph['G3_hypotheses']:
        emit('G3',dict(utterance=item['span'],circumstance=None),'G3_core_or_required_completion',item['parent'])
    for i in range(len(nodes)-1):
        if primary[i] and primary[i+1]: pair(primary[i],primary[i+1],'G2_local_complete_roles',i)
    for item in graph['partition_pairs']:
        pair(item['left'],item['right'],'G2_within_unit_partition',item['parent'])
    comparisons=0
    for i in range(len(nodes)):
        available=[vectors[j] for j in by_parent[i] if vectors[j] is not None]
        if not available or not primary[i]:
            diagnostics.append(dict(parent=i, reason='concept_query_unavailable_no_lexical_fallback'))
            continue
        width=len(available[0])
        query=[math.fsum(v[k] for v in available)/len(available) for k in range(width)]
        # Mean of competing role features forms one query per substrate unit.
        # Ranked target descriptors still retain their complete exact roles.
        best={}; eligible=0; frame_excluded=0; overlap_excluded=0
        for j,d in enumerate(graph['descriptors']):
            check_time()
            if vectors[j] is None or not d['materialization_available'] or abs(d['parent']-i)<=1: continue
            comparisons+=1
            if comparisons>POLICY['comparisons_per_source']: raise ValueError('Comparison ceiling exceeded')
            score=cosine(query,vectors[j]); target=d['materialization_span']; origin=primary[i]
            if origin['start']<target['end'] and target['start']<origin['end']:
                overlap_excluded+=1;continue
            if max(origin['end'],target['end'])-min(origin['start'],target['start'])>6000:
                frame_excluded+=1;continue
            eligible+=1
            key=(-score,target['start'],target['end'],d['parent'])
            prior=best.get(d['parent'])
            if prior is None or key<prior[0]: best[d['parent']]=(key,target)
        chosen=sorted(best.values(),key=lambda x:x[0])[:2]
        for _,target in chosen: pair(primary[i],target,'G2_source_wide_concept',i)
        diagnostics.append(dict(parent=i, reason='concept_lane_accounting', eligible_descriptors=eligible,
            eligible_distinct_mate_units=len(best), retained_mates=len(chosen),
            budget_displaced_mate_units=max(0,len(best)-len(chosen)),
            frame_excluded=frame_excluded, overlap_excluded=overlap_excluded))
    g1,g1_deferred=substrate.g1_candidates(source,nodes);deferred.extend(g1_deferred)
    count=Counter(c['capability'] for c in candidates)
    if (count['G2']>8*len(nodes) or count['G3']>2*len(nodes)
            or len(candidates)>12000 or len(graph['descriptors'])>3*len(nodes)
            or lanes['G2_local_complete_roles']>2*len(nodes)
            or lanes['G2_within_unit_partition']>2*len(nodes)
            or lanes['G2_source_wide_concept']>4*len(nodes)):
        raise ValueError('Candidate/index budget proof violated')
    return dict(source_id=source['video_id'], nodes=nodes, candidates=candidates, G1_candidates=g1,
        descriptors=graph['descriptors'], deferred=deferred, search_diagnostics=diagnostics,
        G3_displacements=graph['G3_displacements'], lattice_diagnostics=graph['diagnostics'],
        resource_counts=dict(comparisons=comparisons, descriptors=len(vectors),
            encoder_tokens=getattr(encoder,'tokens',0)-token_start, encoder_calls=len(vectors)),
        budget_proof=dict(**size, sentence_count=len(nodes), actual_candidates=len(candidates), lane_counts=dict(lanes),
            G3_budget_displaced=graph['diagnostics']['G3_budget_displaced']))
