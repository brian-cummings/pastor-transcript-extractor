"""Bounded source-unit repair of the frozen V4.1 source-only collector.

Normal punctuation geometry is preserved. Mechanical subdivisions and overlapping
G3 windows are hypotheses, never certified sentences, utterances or usable facts.
The factorization below is copied from V4.1 to avoid modifying pinned history.
"""
from __future__ import annotations

from collections import Counter
import re

from pastor_transcript_extractor import evidence_supply_collector_design as geometry
from pastor_transcript_extractor import evidence_supply_revision as spans
from pastor_transcript_extractor import evidence_supply_collector_v4_1 as frozen

VERSION='bounded-source-units-v1'
POLICY=dict(version=VERSION,source_candidate_ceiling=12000,total_candidate_ceiling=20000,
    G1_source_ceiling=200,max_frame_chars=6000,episode_chars=4000,
    G2_per_sentence_bound=8,G2_boundary_width_policy='narrow_and_maximal_available',
    G2_same_sentence_slots=2,G2_remote_slots=2,G3_per_sentence_bound=2,
    continuation_sentences=4,continuation_chars=1000,G1_preceding_sentences=1,
    G1_following_sentences=2,G1_max_target_chars=1800,
    intact_punctuation_unit_chars=1000,fallback_unit_chars=400,
    fallback_caption_min_chars=200,fallback_G3_target_chars=1000)
# Discourse markers propose exact cuts; none attests explanatory meaning.
GLOSS=re.compile(r'\b(?:(?:which|also|this|that|it)\s+)?(?:mean(?:s|t|ing)?|signif(?:y|ies|ying)|represent(?:s|ed|ing)?)\b|\bin other words\b|\bbecause\b',re.I)
ASSURANCE=re.compile(r'\b(?:salvation|sav(?:ed|ing)|accept(?:ed|ance)|pardon\w*|assur\w*|eternal|life|union|secur\w*)\b',re.I)
ABBREVIATION=re.compile(r'\b(?:etc|e\.g|i\.e|mr|mrs|ms|dr|st|vs|jr|sr)\.$',re.I)
CONTINUATION=re.compile(r'^(?:and\s+)?(?:this|that|these|those|it|they|such|which|as|because|if|unless|yet|but|so|therefore|the\b)',re.I)
REPORT_SWITCH=re.compile(r'\b(?:he|she|they|I)\s+(?:said|says|asked|replied|answered)|\b(?:quote|unquote)\b',re.I)


def source_sentences(source):
    """Keep ordinary punctuation units; subdivide oversized ones without rewriting.

    Caption fragment ends are preferred in the latter half of a bounded block.
    Otherwise use the last whitespace boundary, or an exact character boundary
    for a single oversized token. These are retrieval units, not sentences or
    certified utterances. Every non-whitespace source character remains covered.
    """
    text=source['text'];nodes=[]
    caption_ends=sorted({u['end'] for u in source.get('units',[])})
    for parent in frozen.source_sentences(source):
        if len(parent['text'])<=POLICY['intact_punctuation_unit_chars']:
            nodes.append(parent);continue
        cursor=parent['start']
        while cursor<parent['end']:
            limit=min(cursor+POLICY['fallback_unit_chars'],parent['end'])
            end=limit
            if limit<parent['end']:
                preferred=[e for e in caption_ends if cursor+POLICY['fallback_caption_min_chars']<=e<=limit]
                if preferred:end=preferred[-1]
                else:
                    spaces=list(re.finditer(r'\s+',text[cursor:limit+1]))
                    if spaces:end=cursor+spaces[-1].start()
                    if end<=cursor:end=limit
            value=geometry.trim_span(text,cursor,end)
            if value:nodes.append(value)
            cursor=end
            while cursor<parent['end'] and text[cursor].isspace():cursor+=1
    return nodes


def fallback_node(source,node):
    # Parent membership is structural, never a source/phrase/reference lookup.
    return any(p['start']<=node['start'] and node['end']<=p['end']
               and len(p['text'])>POLICY['intact_punctuation_unit_chars']
               for p in frozen.source_sentences(source))


def joined(source,nodes,first,last):
    return spans.span(source['text'],nodes[first]['start'],nodes[last]['end'])


def continuation(source,nodes,index,policy=POLICY):
    """One bounded discourse continuation hypothesis; exact singletons stay too.

    A fragment after a question or a referential/conditional continuation can
    complete a quoted gloss or warning. Reporting switches stop grouping. The
    result still requires target/voice review; it is not a resolved speech turn.
    """
    if fallback_node(source,nodes[index]):
        end=index
        for j in range(index+1,len(nodes)):
            if nodes[j]['end']-nodes[index]['start']>policy['fallback_G3_target_chars']:break
            end=j
        return joined(source,nodes,index,end) if end>index else None
    end=index
    for j in range(index+1,min(len(nodes),index+policy['continuation_sentences'])):
        previous=nodes[j-1]['text'];current=nodes[j]['text']
        if nodes[j]['end']-nodes[index]['start']>policy['continuation_chars']:break
        if REPORT_SWITCH.search(current):break
        fragment_after_question=previous.rstrip('"\u201d\u2019\x27').endswith('?') and len(current.split())<=10
        if not (fragment_after_question or CONTINUATION.search(current)):break
        end=j
    return joined(source,nodes,index,end) if end>index else None


def g1_candidates(source,nodes,policy=POLICY):
    """Nominate claims near proof-topic surfaces; keep factory/pool limits intact.

    A wider topic surface is not a new object option or semantic assertion.
    Framing is never shrunk to force a fit: incompatible eight-frame/six-phrase
    ceilings become explicit deferrals.
    """
    from pastor_transcript_extractor import sermon_g1_feasibility_review as g1
    seeds={i for i,n in enumerate(nodes) if ASSURANCE.search(n['text'])}
    nominated={j for i in seeds for j in range(max(0,i-1),min(len(nodes),i+2))}
    candidates=[];deferred=[]
    for i in sorted(nominated):
        target=joined(source,nodes,max(0,i-policy['G1_preceding_sentences']),min(len(nodes)-1,i+policy['G1_following_sentences']))
        case=dict(case_id='source-only-G1',target_text=target['text'],leading_context='',trailing_context='')
        try:
            if len(target['text'])>policy['G1_max_target_chars']:raise ValueError('G1 complete framing exceeds target bound')
            _,pools=g1.candidates(case)
        except ValueError as error:
            deferred.append(dict(capability='G1',reason='complete_G1_framing_not_representable',source_span=nodes[i],detail=str(error)))
            continue
        claim=nodes[i];local=dict(source_field='target_text',start=claim['start']-target['start'],end=claim['end']-target['start'],text=claim['text'])
        c=dict(capability='G1',video_id=source['video_id'],claim=claim,target=target,local_claim=local,
            phrase_pools=pools,leading_context='',trailing_context='',builder_version=VERSION,
            semantic_truth=None,pastor_credit=False,selection='source_only_proof_topic_neighborhood')
        c['candidate_id']=identity(source,'G1',dict(target=target,claim=claim));candidates.append(c)
    if len(candidates)>policy['G1_source_ceiling']:raise ValueError('G1 candidate ceiling exceeded; no truncation')
    return candidates,deferred


def identity(source,cap,endpoints):
    return f"{source['video_id']}:{cap}:"+spans.fp(dict(version=VERSION,video_id=source['video_id'],capability=cap,endpoints=endpoints))[:16]


def discover(source,policy=POLICY):
    """Same bounded collector interface; no benchmark or expectation input.

    G2: four oriented narrow/maximal pairs at each source gap, up to two
    prefix/suffix gloss cuts and two nearest nonlocal gloss hypotheses per
    sentence. G3: every exact sentence plus at most one continuation unit;
    no circumstance-mate multiplication for this atomic-local workflow.
    """
    nodes=source_sentences(source);candidates=[];deferred=[];seen=set();diagnostics=[]
    gloss_indexes=[i for i,n in enumerate(nodes) if GLOSS.search(n['text'])]
    shape_policy={**geometry.POLICY,'max_frame_chars':policy['max_frame_chars']}
    def emit(cap,endpoints,reason):
        key=identity(source,cap,endpoints)
        if key in seen:return
        seen.add(key)
        candidate=geometry.represent(source,cap,endpoints,shape_policy)
        if candidate['status']=='deferred':
            deferred.append(dict(candidate,capability=cap,selection=reason));return
        candidate.update(candidate_id=key,builder_version=VERSION,selection=reason,
            source_hypothesis_only=True,automatic_provenance_attestation=False)
        candidates.append(candidate)
    for i,node in enumerate(nodes):
        emit('G3',dict(utterance=node,circumstance=None),'source_only_exact_unit_hypothesis')
        group=continuation(source,nodes,i,policy)
        if group:emit('G3',dict(utterance=group,circumstance=None),'source_only_bounded_continuation_requires_target_review')
        # Factor both sides of a gap without assuming which is biblical.
        if i+1<len(nodes):
            maximum=(min(2,i+1),min(2,len(nodes)-i-1))
            widths=list(dict.fromkeys(((1,1),maximum)))
            omitted=[(a,b) for a in range(1,maximum[0]+1) for b in range(1,maximum[1]+1) if (a,b) not in widths]
            if omitted:
                diagnostics.append(dict(capability='G2',origin_span=node,
                    reason='asymmetric_boundary_variants_not_materialized',omitted_widths=[list(w) for w in omitted],
                    note='Maximal roles contain these spans geometrically; semantic context equivalence is not established. Narrow roles remain separate.'))
            for left_width,right_width in widths:
                a=joined(source,nodes,i-left_width+1,i);b=joined(source,nodes,i+1,i+right_width)
                emit('G2',dict(left=a,right=b),'source_only_local_boundary_factorization')
                emit('G2',dict(left=b,right=a),'source_only_local_boundary_factorization')
        cuts=[]
        for match in GLOSS.finditer(node['text']):
            left=geometry.trim_span(source['text'],node['start'],node['start']+match.start())
            right=geometry.trim_span(source['text'],node['start']+match.start(),node['end'])
            if left and right:cuts.append((left,right))
        for a,b in cuts[:policy['G2_same_sentence_slots']]:
            emit('G2',dict(left=a,right=b),'source_only_complete_prefix_suffix')
        if len(cuts)>policy['G2_same_sentence_slots']:
            deferred.append(dict(capability='G2',reason='same_sentence_cut_fanout',source_span=node,eligible=len(cuts),retained=policy['G2_same_sentence_slots']))
        remote=[j for j in gloss_indexes if abs(j-i)>2
                and max(nodes[j]['end'],node['end'])-min(nodes[j]['start'],node['start'])<=policy['max_frame_chars']]
        remote.sort(key=lambda j:(abs(j-i),nodes[j]['start']))
        for j in remote[:policy['G2_remote_slots']]:
            emit('G2',dict(left=node,right=nodes[j]),'source_only_nearest_nonlocal_gloss')
        if len(remote)>policy['G2_remote_slots']:
            diagnostics.append(dict(capability='G2',origin_span=node,reason='nonlocal_gloss_fanout',eligible=len(remote),retained=policy['G2_remote_slots']))
    g1,g1_deferred=g1_candidates(source,nodes,policy);deferred.extend(g1_deferred)
    counts=Counter(c['capability'] for c in candidates);bound=len(nodes)*(policy['G2_per_sentence_bound']+policy['G3_per_sentence_bound'])
    if counts['G2']>8*len(nodes) or counts['G3']>2*len(nodes) or len(candidates)>bound:
        raise ValueError('Source-derived candidate proof violated')
    if len(candidates)>policy['source_candidate_ceiling']:raise ValueError(f"Source {source['video_id']} candidate ceiling exceeded: {len(candidates)} > {policy['source_candidate_ceiling']}; no truncation")
    return dict(source_id=source['video_id'],nodes=nodes,episodes=[],candidates=candidates,G1_candidates=g1,
        deferred=deferred,search_diagnostics=diagnostics,
        unit_diagnostics=dict(punctuation_units=len(frozen.source_sentences(source)),
            subdivided_parents=sum(len(p['text'])>POLICY['intact_punctuation_unit_chars'] for p in frozen.source_sentences(source)),
            fallback_units=sum(fallback_node(source,n) for n in nodes),
            unit_chars=[len(n['text']) for n in nodes],
            hard_token_split_coordinates=[a['end'] for a,b in zip(nodes,nodes[1:])
                if a['end']==b['start'] and source['text'][a['end']-1:a['end']].isalnum()
                and source['text'][b['start']:b['start']+1].isalnum()],
            units_are_semantic_boundaries=False),
        budget_proof=dict(sentence_count=len(nodes),G2_per_sentence_bound=8,G3_per_sentence_bound=2,
            linear_candidate_bound=bound,actual_candidates=len(candidates),G1_candidates=len(g1),
            hard_source_ceiling=policy['source_candidate_ceiling'],hard_G1_ceiling=policy['G1_source_ceiling']))


def automatic_envelope(source,candidate):
    """Same optional context budgets using bounded units; never trim attribution.

    No source voice or sufficiency is attested by this mechanical envelope.
    """
    if not any(len(n['text'])>POLICY['intact_punctuation_unit_chars'] for n in frozen.source_sentences(source)):
        from pastor_transcript_extractor.fresh_discovery_preparation import automatic_envelope as original
        return original(source,candidate)
    frame=candidate['relation_frame'];nodes=source_sentences(source)
    before=[n for n in nodes if n['end']<=frame['start'] and frame['start']-n['start']<=1200]
    after=[n for n in nodes if n['start']>=frame['end'] and n['end']-frame['end']<=400]
    lo=before[0]['start'] if before else frame['start'];hi=after[-1]['end'] if after else frame['end']
    if hi-lo>6000:hi=frame['end']
    if hi-lo>6000:lo=frame['start']
    if hi-lo>6000:return dict(status='deferred',reason='required_frame_exceeds_6000',required_span=frame)
    return dict(status='prepared_not_attested',start=lo,end=hi,text=source['text'][lo:hi],
        policy_version=VERSION,source_voice=None,atomic_sufficiency=None)
