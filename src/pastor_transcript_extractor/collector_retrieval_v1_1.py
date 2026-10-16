"""Bounded G2/G3 source-only nomination. No model/admission/benchmark authority."""
from __future__ import annotations
from collections import Counter
import math
import time

from pastor_transcript_extractor import collector_role_lattice_v1_1 as lattice
from pastor_transcript_extractor import evidence_supply_collector_design as geometry
from pastor_transcript_extractor import evidence_supply_source_unit_repair as substrate
from pastor_transcript_extractor import evidence_supply_revision as spans

VERSION = 'independent-role-qualification-retrieval-v1.1'
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
    primary=graph['G2_primary']
    composition=[]; ranking=[]
    def emit(cap, endpoints, lane, parent):
        check_time()
        key=spans.fp(dict(version=VERSION, source=source['video_id'], capability=cap, endpoints=endpoints))
        if key in seen:
            diagnostics.append(dict(parent=parent, lane=lane, reason='duplicate_geometry_no_refill'))
            return dict(status='duplicate_geometry_no_refill')
        seen.add(key)
        c=geometry.represent(source,cap,endpoints)
        if c['status']=='deferred':
            deferred.append(dict(c, capability=cap, lane=lane, parent=parent)); return dict(status='representation_rejected',reason=c.get('reason'))
        env=automatic_envelope(source,c,nodes)
        if env['status']=='deferred':
            deferred.append(dict(reason=env['reason'], capability=cap, endpoints=endpoints, lane=lane, parent=parent)); return dict(status='envelope_rejected',reason=env['reason'])
        c.update(candidate_id=f"{source['video_id']}:{cap}:{key[:16]}", builder_version=VERSION,
            selection=lane, parent_unit=parent, source_hypothesis_only=True,
            automatic_provenance_attestation=False, reference_policy='P1', automatic_envelope=env)
        candidates.append(c); lanes[lane]+=1
        return dict(status='emitted',candidate_id=c['candidate_id'])
    def pair(a,b,lane,parent,seed_ids=None,mate_id=None):
        if seed_ids is None: seed_ids=[j for j,d in enumerate(graph['descriptors']) if d['materialization_span']==a]
        if mate_id is None: mate_id=next((j for j,d in enumerate(graph['descriptors']) if d['materialization_span']==b),None)
        outcomes=[emit('G2',dict(left=a,right=b),lane,parent),emit('G2',dict(left=b,right=a),lane,parent)]
        composition.append(dict(parent=parent,lane=lane,seed_descriptor_ids=seed_ids,
            mate_descriptor_id=mate_id,origin=dict(start=a['start'],end=a['end']),
            mate=dict(start=b['start'],end=b['end']),forward=outcomes[0],reverse=outcomes[1]))

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
        # Compact source-only trace includes every descriptor comparison or
        # exclusion. Rank is global among eligible descriptors, before per-mate
        # deduplication and top-K. No reference information enters this path.
        rows=[]; ranked=[]; origin=primary[i]
        for j,d in enumerate(graph['descriptors']):
            check_time()
            target=d['materialization_span']
            if abs(d['parent']-i)<=1:
                reason='local_or_same_unit'; score=None
            elif vectors[j] is None:
                reason='encoder_token_limit'; score=None
            elif not d['materialization_available']:
                reason='role_not_materializable'; score=None
            else:
                comparisons+=1
                if comparisons>POLICY['comparisons_per_source']: raise ValueError('Comparison ceiling exceeded')
                score=cosine(query,vectors[j])
                if origin['start']<target['end'] and target['start']<origin['end']:
                    reason='overlapping_roles'
                elif max(origin['end'],target['end'])-min(origin['start'],target['start'])>6000:
                    reason='frame_bound'
                else:
                    reason='eligible'; ranked.append((-score,target['start'],target['end'],d['parent'],j))
            rows.append([j,score,None,reason])
        ordered=sorted(ranked); best={}
        for rank,(_,_,_,parent,j) in enumerate(ordered,1):
            rows[j][2]=rank
            if parent in best:
                rows[j][3]='same_mate_unit_displaced'
            else:
                best[parent]=j
        chosen=list(best.values())[:2]
        for j in list(best.values())[2:]: rows[j][3]='top_K_displaced'
        for j in chosen:
            rows[j][3]='selected_for_composition'
            pair(primary[i],graph['descriptors'][j]['materialization_span'],
                'G2_source_wide_concept',i,by_parent[i],j)
        codes=['local_or_same_unit','encoder_token_limit','role_not_materializable','overlapping_roles','frame_bound','same_mate_unit_displaced','top_K_displaced','selected_for_composition']
        for row in rows: row[3]=codes.index(row[3])
        ranking.append(dict(parent=i,seed_descriptor_ids=[j for j in by_parent[i] if vectors[j] is not None],
            query='mean_of_encodable_G2_descriptors',
            origin=dict(start=origin['start'],end=origin['end']),
            columns=['mate_descriptor_id','cosine_rounded_6','eligible_rank','decision_code'],decision_codes=codes,rows=rows))
        diagnostics.append(dict(parent=i,reason='concept_lane_accounting',
            eligible_descriptors=len(ordered),eligible_distinct_mate_units=len(best),retained_mates=len(chosen),
            budget_displaced_mate_units=max(0,len(best)-len(chosen)),
            frame_excluded=sum(r[3]==codes.index('frame_bound') for r in rows),
            overlap_excluded=sum(r[3]==codes.index('overlapping_roles') for r in rows)))
    g1,g1_deferred=substrate.g1_candidates(source,nodes);deferred.extend(g1_deferred)
    count=Counter(c['capability'] for c in candidates)
    if (count['G2']>8*len(nodes) or count['G3']>2*len(nodes)
            or len(candidates)>12000 or len(graph['descriptors'])>3*len(nodes)
            or lanes['G2_local_complete_roles']>2*len(nodes)
            or lanes['G2_within_unit_partition']>2*len(nodes)
            or lanes['G2_source_wide_concept']>4*len(nodes)):
        raise ValueError('Candidate/index budget proof violated')
    return dict(source_id=source['video_id'], nodes=nodes, candidates=candidates, G1_candidates=g1,
        descriptors=graph['descriptors'], G2_primary=primary, G2_role_construction=graph['G2_role_construction'], deferred=deferred, search_diagnostics=diagnostics,
        retrieval_trace=ranking, composition_trace=composition,
        G3_construction=graph['G3_hypotheses'], G3_displacements=graph['G3_displacements'], lattice_diagnostics=graph['diagnostics'],
        resource_counts=dict(comparisons=comparisons, descriptors=len(vectors),
            encoder_tokens=getattr(encoder,'tokens',0)-token_start, encoder_calls=len(vectors)),
        budget_proof=dict(**size, sentence_count=len(nodes), actual_candidates=len(candidates), lane_counts=dict(lanes),
            G3_budget_displaced=graph['diagnostics']['G3_budget_displaced']))
