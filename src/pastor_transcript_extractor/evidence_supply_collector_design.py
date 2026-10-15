"""Source-only collector geometry prototype and review packet; no paid runner.

The discovery function receives source text and policy only. Frozen references
are used afterward for diagnostics and explicitly authored representation cases.
This version changes collection geometry, never G1/G2/G3 question contracts.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from bisect import bisect_right
from functools import lru_cache
import hashlib
import json
import re
from pathlib import Path

from pastor_transcript_extractor import evidence_supply_revision as v2

HERE = v2.ROOT / 'docs/review-proposals/evidence-supply-collector-v3'
POLICY = dict(version='episode-anchor-geometry-prototype-v3', episode_chars=4000,
              max_frame_chars=6000, max_clause_children=8, max_mates_per_anchor=6,
              G2_max_mates=12, G2_local_slots=8, G2_same_sentence_slots=2, G2_long_range_slots=2,
              max_search_episodes=3, source_candidate_ceiling=12000,
              total_candidate_ceiling=20000, citation_scope_chars=700)
BOOKS = r'Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth|Samuel|Kings|Chronicles|Ezra|Nehemiah|Esther|Job|Psalms?|Proverbs|Ecclesiastes|Song of Solomon|Isaiah|Jeremiah|Lamentations|Ezekiel|Daniel|Hosea|Joel|Amos|Obadiah|Jonah|Micah|Nahum|Habakkuk|Zephaniah|Haggai|Zechariah|Malachi|Matthew|Mark|Luke|John|Acts|Romans|Corinthians|Galatians|Ephesians|Philippians|Colossians|Thessalonians|Timothy|Titus|Philemon|Hebrews|James|Peter|Jude|Revelation'
NONBIBLICAL = re.compile(r"Desire of Ages|Patriarchs and Prophets|(?:Christ'?s|Cross) Object Lessons?|Manuscript Release\w*|Ellen White", re.I)
# A common name or the word "job" alone is not a biblical citation.
ATTRIBUTION = re.compile(r"\b(?:" + NONBIBLICAL.pattern + r")\b|\b(?:(?:[123]|first|second|third)\s+)?(?:" + BOOKS + r')\s+(?:chapter\s+)?\d+(?::\d+)?|\bbook of (?:' + BOOKS + r')\b', re.I)
# This finite vocabulary is development-sample retrieval policy, not semantic gold.
CIRCUMSTANCE = re.compile(r'\b(?:griev\w*|guilt\w*|forgiv\w*|sin\w*|sorrow\w*|afraid|fright\w*|terrifi\w*|troubl\w*|doubt\w*|depress\w*|busy|children|kids?|parents?|fathers?|dads?|mothers?|sons?|young men|adults?|little ones|difficult\w*|hard time|temptation|backslid\w*|distract\w*|trembling|poor|selfish\w*|pride|fear|loss|divorce|convict\w*|peace|time|inventory|not ready|pain|cry\w*|cried|passed away|not believe)\b', re.I)
ADDRESS = re.compile(r'\b(?:you|your|we|us|let|pray|promise|call|help|come|should|please|I will|can I)\b', re.I)
GLOSS = re.compile(r'\b(?:means?|in other words|because|represents?|this is|that is|so|understand|in order|the reality)\b', re.I)
NARRATION = re.compile(r'\b(?:I|he|she|we|they)\s+(?:encouraged|prayed|visited|helped|comforted|counseled)\b', re.I)


def trim_span(text, start, end):
    while start < end and text[start].isspace(): start += 1
    while end > start and text[end-1].isspace(): end -= 1
    return v2.span(text, start, end) if start < end else None


def source_nodes(source, policy=POLICY):
    """Keep full sentences; add bounded exact clause children, never paraphrases."""
    nodes = []; deferred = []
    for i, sentence in enumerate(v2.sentences(source)):
        nodes.append(dict(**sentence, node_id=f'{source["video_id"]}:sentence:{i}', parent=i, kind='sentence'))
        # Digit colons in chapter:verse references do not become clause boundaries.
        cuts = [0] + [m.start() for m in re.finditer(r';\s*|(?<!\d):(?!\d)\s*|,\s+|\b(?:means|but|because|so that)\b', sentence['text'], re.I)] + [len(sentence['text'])]
        cuts = sorted(set(cuts)); children = [trim_span(source['text'], sentence['start']+a, sentence['start']+b) for a,b in zip(cuts,cuts[1:])]
        children = [c for c in children if c and len(c['text']) >= 8]
        if len(children) > policy['max_clause_children']:
            deferred.append(dict(reason='clause_fanout_requires_review', sentence_span=sentence, child_count=len(children)))
            continue
        if len(children) > 1:
            for j, child in enumerate(children):
                nodes.append(dict(**child, node_id=f'{source["video_id"]}:clause:{i}:{j}', parent=i, kind='clause'))
    return nodes, deferred


def episodes_for(source, policy=POLICY):
    sentences = v2.sentences(source); episodes = []; start = source['main_span']['start']
    for i, node in enumerate(sentences):
        if node['end'] - start >= policy['episode_chars'] or i == len(sentences)-1:
            episodes.append(dict(**v2.span(source['text'], start, node['end']), episode_id=f'{source["video_id"]}:episode:{len(episodes)}'))
            start = node['end']
    return episodes


@lru_cache(maxsize=8192)
def words(text):
    return frozenset(w for w in re.findall(r'[a-z]{4,}', text.lower()) if w not in {'that','this','with','have','they','them','what','when','there','from','your','were','will','into','said','says','then','about'})


@lru_cache(maxsize=12)
def attribution_marks(text, lo, hi):
    marks=tuple(ATTRIBUTION.finditer(text,lo,hi))
    return marks,tuple(m.end() for m in marks)


def attribution_before(source, start, end=None, policy=POLICY):
    marks,ends=attribution_marks(source['text'],source['main_span']['start'],source['main_span']['end'])
    pos=bisect_right(ends,end if end is not None else start)-1
    if pos<0:return None
    mark=marks[pos]
    if start-mark.end()>policy['citation_scope_chars']:
        return None
    # A named source is a retrieval signal, not an inferred semantic voice label.
    line = source['text'].rfind('\n', source['main_span']['start'], mark.start()) + 1
    return dict(span=v2.span(source['text'], max(source['main_span']['start'], line), mark.end()),
                named_source=mark.group(), family='nonbiblical_named_source' if NONBIBLICAL.fullmatch(mark.group()) else 'biblical_book_signal',
                source_voice=None, certainty='lexical_signal_requires_source_audit')


def represent(source, capability, endpoints, policy=POLICY):
    """Accept exact role spans at any sentence distance; bound the evidence frame.

    Used both by source-only discovery and a separate authored diagnostic panel.
    An ability to represent a reference is never reported as a discovery hit.
    """
    text = source['text']; lo = source['main_span']['start']; hi = source['main_span']['end']
    spans = [s for s in endpoints.values() if s]
    for s in spans:
        if not lo <= s['start'] < s['end'] <= hi or text[s['start']:s['end']] != s['text']:
            raise ValueError('Endpoint is not an exact main-source span')
    if capability == 'G2' and endpoints['left']['start'] < endpoints['right']['end'] and endpoints['right']['start'] < endpoints['left']['end']:
        return dict(status='deferred', reason='overlapping_G2_endpoint_roles', endpoints=endpoints)
    first = min(s['start'] for s in spans); last = max(s['end'] for s in spans)
    anchor = endpoints['left'] if capability=='G2' else endpoints['utterance']
    attribution = attribution_before(source, anchor['start'], anchor['end'],policy)
    frame_start = min(first, attribution['span']['start']) if attribution else first
    if last-frame_start > policy['max_frame_chars']:
        return dict(status='deferred', reason='attribution_or_relation_exceeds_frame_bound', endpoints=endpoints,
                    required_frame_chars=last-frame_start, attribution=attribution)
    frame = v2.span(text, frame_start, last)
    result = dict(status='represented', video_id=source['video_id'], capability=capability,
                  endpoints=endpoints, relation_frame=frame, attribution=attribution,
                  source_scope='supplied_passage', pastor_credit=False, semantic_truth=None)
    if capability == 'G2':
        result['admission'] = 'quarantine_nonbiblical_source_signal' if attribution and attribution['family']=='nonbiblical_named_source' else 'source_anchor_review_required'
        result['same_sentence_allowed'] = True
    else:
        utterance = endpoints['utterance']
        # Act phase sees its own target, never the larger relation frame as target.
        result['act_target'] = deepcopy(utterance)
        result['act_context'] = v2.span(text, frame_start, utterance['start']) if frame_start < utterance['start'] else None
        result['binding_target'] = frame
        narration = bool(NARRATION.search(utterance['text'])) and not re.search(r'["\u201c\u201d]|\b(?:you|your|please|let us|let me)\b', utterance['text'], re.I)
        result['admission'] = 'narration_control_only_no_positive_export' if narration else 'address_surface_review_required'
        result['boundary_guarantee'] = 'Binding-phase output cannot introduce, replace or strengthen act-phase facts; conflicts quarantine the record.'
    return result


def discover(source, policy=POLICY):
    """Bounded source-only searches; no reference IDs, expected labels or answers."""
    nodes, deferred = source_nodes(source, policy); episodes = episodes_for(source, policy)
    node_episodes = {n['node_id']: next(ep['episode_id'] for ep in episodes if ep['start'] <= n['start'] < ep['end']) for n in nodes}
    candidates = []; counts = Counter(); overflow = []
    # Full sentence anchors include their explicit scriptural-book signals.
    anchors=[]
    for n in nodes:
        if n['kind']!='sentence':continue
        attr=attribution_before(source,n['start'],n['end'],policy)
        if attr and attr['family']=='biblical_book_signal':anchors.append(n)
    utterances = [n for n in nodes if n['kind']=='sentence' and ADDRESS.search(n['text'])]
    circumstances = [n for n in nodes if n['kind']=='sentence' and CIRCUMSTANCE.search(n['text'])]
    for cap, origins in (('G2', anchors), ('G3', utterances)):
        for origin in origins:
            origin_words = words(origin['text']); home = node_episodes[origin['node_id']]
            ranked_episodes = sorted(episodes, key=lambda ep: (-int(ep['episode_id']==home), -len(origin_words & words(ep['text'])), abs(ep['start']-origin['start']), ep['start']))
            selected = {ep['episode_id'] for ep in ranked_episodes[:policy['max_search_episodes']]}
            pool = [n for n in (nodes if cap=='G2' else circumstances) if node_episodes[n['node_id']] in selected and (cap!='G2' or n['node_id']!=origin['node_id'] and GLOSS.search(n['text']))]
            if cap=='G2':
                # Same-sentence roles use distinct non-overlapping clause spans.
                parents = [n for n in nodes if n['parent']==origin['parent'] and n['kind']=='clause']
                for left in parents:
                    for right in parents:
                        if left['end'] <= right['start'] and GLOSS.search(right['text']):
                            pool.append(dict(right, proposed_left=left))
            ranked = sorted(pool, key=lambda n: (-int(n.get('proposed_left') is not None), -len(origin_words & words(n['text'])), abs(n['start']-origin['start']), n['start'], n['end']))
            eligible_before_quotas=len(ranked)
            if cap=='G2':
                # Local coverage, same-sentence roles and hierarchical search have
                # separate slots; clause fanout cannot consume the long-range route.
                same=[n for n in ranked if n.get('proposed_left')]
                local=sorted((n for n in nodes if n['kind']=='sentence' and 0<abs(n['parent']-origin['parent'])<=4),key=lambda n:(abs(n['parent']-origin['parent']),n['start']))
                remote=[n for n in ranked if not n.get('proposed_left') and abs(n['parent']-origin['parent'])>4]
                ranked=same[:policy['G2_same_sentence_slots']]+local[:policy['G2_local_slots']]+remote[:policy['G2_long_range_slots']]
                eligible_before_quotas+=len(local)
            kept = 0; seen = set()
            if cap=='G3':
                endpoints=dict(utterance={k:origin[k] for k in ('start','end','text')},circumstance=None)
                key=v2.fp(dict(video_id=source['video_id'],capability=cap,endpoints=endpoints))
                generic=represent(source,cap,endpoints,policy)
                if generic['status']=='represented':
                    generic.update(candidate_id=f'{source["video_id"]}:{cap}:{key[:16]}',selection='source_only_generic_address',searched_episode_ids=[home])
                    candidates.append(generic);counts[cap]+=1;kept=1;seen.add(key)
                else:deferred.append(generic)
            for mate in ranked:
                endpoints = dict(left=mate.get('proposed_left', origin), right=mate) if cap=='G2' else dict(utterance=origin, circumstance=mate)
                # Strip structural selection bookkeeping from exact role spans.
                endpoints = {k:{f:s[f] for f in ('start','end','text')} for k,s in endpoints.items()}
                key = v2.fp(dict(video_id=source['video_id'], capability=cap, endpoints=endpoints))
                if key in seen: continue
                seen.add(key)
                if kept >= (policy['G2_max_mates'] if cap=='G2' else policy['max_mates_per_anchor']):
                    continue
                candidate = represent(source,cap,endpoints,policy)
                if candidate['status']=='deferred':
                    deferred.append(candidate); continue
                candidate.update(candidate_id=f'{source["video_id"]}:{cap}:{key[:16]}', selection='source_only_episode_ranked', searched_episode_ids=sorted(selected))
                candidates.append(candidate); counts[cap]+=1; kept+=1
            overflow.append(dict(capability=cap,origin_span={k:origin[k] for k in ('start','end','text')},searched_episode_ids=sorted(selected),eligible_role_pairs=eligible_before_quotas,retained=kept,
                                 ranked_pairs_not_materialized=max(0,eligible_before_quotas-kept),reason='Declared source-only fanout quotas; counts are retrieval work, not semantic negatives. Other episode references remain addressable.'))
    unique = {c['candidate_id']:c for c in candidates}; candidates=list(unique.values())
    ceiling = policy['G2_max_mates']*len(anchors)+policy['max_mates_per_anchor']*len(utterances)
    if len(candidates)>ceiling or len(candidates)>policy['source_candidate_ceiling']:
        raise ValueError('Source candidate bound exceeded; no truncation is permitted')
    return dict(source_id=source['video_id'],episodes=episodes,nodes=nodes,candidates=candidates,deferred=deferred,search_diagnostics=overflow,
                budget_proof=dict(G2_anchor_count=len(anchors),G3_utterance_count=len(utterances),G2_max_mates=policy['G2_max_mates'],G3_max_mates=policy['max_mates_per_anchor'],linear_candidate_bound=ceiling,actual_candidates=len(candidates),hard_source_ceiling=policy['source_candidate_ceiling']))


def combine_address_phases(candidate, act_result, binding_result):
    """Structural review guard for a future runner, not a semantic classifier."""
    from pastor_transcript_extractor.sermon_g3_feasibility_review import ACTS
    if act_result['utterance'] != candidate['endpoints']['utterance'] or binding_result['utterance'] != act_result['utterance']:
        raise ValueError('Cannot reuse acts for a different utterance')
    if act_result['target'] != candidate['act_target'] or binding_result['target'] != candidate['binding_target']:
        raise ValueError('Phase target identity mismatch')
    if any(k in ACTS for k in binding_result['decisions']):
        raise ValueError('Binding phase cannot introduce or strengthen an act')
    positives={k:v for k,v in act_result['decisions'].items() if k in ACTS and v=='observed'}
    return dict(raw_act_decisions=act_result['decisions'],raw_binding_decisions=binding_result['decisions'],
                positive_facts={} if candidate['admission']=='narration_control_only_no_positive_export' else positives,
                admission='quarantined_narration' if candidate['admission']=='narration_control_only_no_positive_export' else 'pending_source_audit',
                integrity_finding=bool(positives) if candidate['admission']=='narration_control_only_no_positive_export' else None,
                pastor_credit=False)


def compact_collection(collection):
    collection=deepcopy(collection)
    for candidate in collection['candidates']:
        for field in ('relation_frame','act_target','act_context','binding_target'):
            value=candidate.get(field)
            if value:
                candidate[field]={k:value[k] for k in ('start','end')}|{'text_sha256':hashlib.sha256(value['text'].encode()).hexdigest()}
        if candidate.get('attribution'):
            value=candidate['attribution']['span']
            candidate['attribution']['span']={k:value[k] for k in ('start','end')}|{'text_sha256':hashlib.sha256(value['text'].encode()).hexdigest()}
    return collection


def request_shapes(candidate):
    """Prepare diagnostic shapes using untouched canonical questions; no client."""
    from pastor_transcript_extractor import sermon_g2_feasibility_revision as g2
    from pastor_transcript_extractor import sermon_g3_feasibility_review as g3
    from pastor_transcript_extractor import sermon_g3_feasibility_revision as g3v2
    if candidate['status']!='represented':return []
    def local(value,target):
        return None if value is None else dict(source_field='target_text',start=value['start']-target['start'],end=value['end']-target['start'],text=value['text'])
    frame=candidate['relation_frame'];endpoints=candidate['endpoints']
    if candidate['capability']=='G2':
        state=dict(target_text=frame['text'],leading_context='',trailing_context='',pairs=[dict(pair_id='diagnostic',left=local(endpoints['left'],frame),right=local(endpoints['right'],frame))])
        questions={k:v for k,v in g2.questions(0).items() if k.removeprefix('p0_') in {'explains_text','adoption','boundary','left_voice','right_voice'}}
        return [dict(phase='G2_single_pair',state=state,questions=questions,question_version=g2.VERSION)]
    act=candidate['act_target'];context=candidate['act_context']
    act_state=dict(target_text=act['text'],leading_context=context['text'] if context else '',trailing_context='',candidate=dict(utterance=local(endpoints['utterance'],act),circumstance=None))
    binding_state=dict(target_text=frame['text'],leading_context='',trailing_context='',candidate={k:local(value,frame) for k,value in endpoints.items()})
    return [dict(phase='G3_acts_and_source_only',state=act_state,questions={k:v for k,v in g3.questions().items() if k!='binding'},question_version=g3.VERSION),
            dict(phase='G3_relevance_and_recipient_binding_only',state=binding_state,questions=g3v2.questions(),question_version=g3v2.VERSION)]


def build_packet():
    from pastor_transcript_extractor import evidence_supply_source_audit as audit
    reviewed = json.loads(audit.AUDIT.read_text()); decision=audit.accepted_decision(reviewed)
    if decision is None: raise ValueError('Requires accepted V2 source audit/readiness decision')
    original = json.loads((v2.HERE/'input-v2.json').read_text()); v2.validate_packet(original,reproduce=False)
    sources = [json.loads((v2.HERE/'sources'/f'{v}.json').read_text()) for v in original['source_ids']]
    # Discovery is completed before any focal reference is read below.
    collections = [discover(source) for source in sources]
    source_map = {s['video_id']:s for s in sources}
    references = json.loads((v2.HERE/'references-v2.json').read_text())
    diagnostics=[]
    for ref in references['rows']:
        for check in ref['checks']:
            if ref['capability']=='G1':
                diagnostics.append(dict(check_id=check['check_id'],capability='G1',status='unchanged_V2_route',reason='No G1 collection expansion or construct revision; V2 exact focal supply/withholding remains historical.'))
                continue
            endpoints = {k:check[k] for k in ('left','right') if k in check} if ref['capability']=='G2' else {k:check[k] for k in ('circumstance','utterance')}
            representation = represent(source_map[ref['video_id']],ref['capability'],endpoints)
            matches = [c['candidate_id'] for col in collections if col['source_id']==ref['video_id'] for c in col['candidates'] if c['capability']==ref['capability'] and all((c['endpoints'].get(k) is None if s is None else c['endpoints'].get(k) is not None and c['endpoints'][k]['start']<=s['start'] and c['endpoints'][k]['end']>=s['end']) for k,s in endpoints.items())]
            diagnostics.append(dict(check_id=check['check_id'],reference_id=ref['reference_id'],capability=ref['capability'],video_id=ref['video_id'],frozen_expected=check['expected'],representation=representation,
                                    authored_representation_not_discovery=True,source_only_matching_candidates=matches,diagnostic_request_shapes=request_shapes(representation),semantic_measurement=None))
    count=sum(len(c['candidates']) for c in collections)
    if count>POLICY['total_candidate_ceiling']:raise ValueError('Total design candidate ceiling exceeded; review scope rather than truncate')
    old={r['check_id']:bool(r['matching_candidate_ids']) for r in original['funnel']}
    comparison=Counter(('retained_exact_geometry' if old[r['check_id']] else 'new_exact_geometry') if r.get('source_only_matching_candidates') else ('lost_V2_exact_geometry' if old[r['check_id']] else 'still_unsupplied') for r in diagnostics if r['capability']!='G1')
    packet=dict(version='evidence-supply-collector-design-v3',status='provider_free_prototype_for_review_not_paid_ready',provider_requests=0,production_effect='none',policy=POLICY,
                original_packet_fingerprint=original['content_fingerprint'],acceptance_fingerprint=decision['content_fingerprint'],source_ids=original['source_ids'],collections=[compact_collection(c) for c in collections],diagnostic_representation_panel=diagnostics,
                G1_policy='Reuse unchanged V2 inputs only; no new G1 semantic/collection run',candidate_count=sum(len(c['candidates']) for c in collections),
                bound=sum(c['budget_proof']['linear_candidate_bound'] for c in collections),semantic_contract_changes=0,
                source_only_supply_comparison=dict(comparison),
                holds=['No provider rerun or paid authorization','G1/G2/G3 and consumer contracts closed','No collection activation','No projection/scoring','790 non-reference V2 positives remain unaudited; no whole-run economics'],
                input_hashes={**original['source_files'],str(audit.AUDIT.relative_to(v2.ROOT)):v2.v1.file_hash(audit.AUDIT),str((audit.RESULTS/'acceptance-decision-v2.json').relative_to(v2.ROOT)):v2.v1.file_hash(audit.RESULTS/'acceptance-decision-v2.json'),str(Path(__file__).relative_to(v2.ROOT)):v2.v1.file_hash(Path(__file__)),**{str((HERE/name).relative_to(v2.ROOT)):v2.v1.file_hash(HERE/name) for name in ('PROPOSAL.md','CHECK_DESIGN.md','check-design-v3.json','authorization-v3.json')}})
    packet['content_fingerprint']=v2.fp(packet)
    return packet


def validate_packet(packet):
    if packet != build_packet():
        raise ValueError('Collector design no longer reproduces; preserve the frozen proposal and version changes')


def render_packet(packet):
    panel=packet['diagnostic_representation_panel']; represent_counts=Counter(r.get('representation',{}).get('status',r.get('status')) for r in panel)
    lines=['# Evidence-supply collector V3 provider-free prototype', '', '**Collection design revision only; no G1 V3, paid run or readiness PASS.**', '',
           f'Source-only prototype: {packet["candidate_count"]:,} G2/G3 candidates across the same six sources; declared linear upper bound {packet["bound"]:,}. V2 had 28,764 G2/G3 candidates plus 23 G1 candidates. Source/contract/decision hashes are pinned in `design-v3.json`.', '',
           'Each source retains all sentence nodes, bounded clause children and contiguous source episode references. G2 starts from explicit/recent citation signals, with separate slots for eight local neighbors, two distinct same-sentence clause roles and two long-range episode mates. G3 keeps one generic utterance and at most five circumstance mates. Hierarchical searches rank at most three episodes. Rank overflow, insufficient attribution/frame bounds and unexpanded clause fanout are explicit work items, never semantic negatives or silent truncation.', '',
           'This is a source-only sparse retrieval experiment, not a proved discovery algorithm. A fully authored exact representation panel demonstrates whether the frame builder can represent a known opportunity without a sentence-hop ceiling. It does not establish discovery hits, semantic truth or exhaustive episode boundaries. Focal exact source-only hits are reported separately. References/answers never enter discovery.', '',
           '## Growth and source coverage', '', '| Source | G2 anchors | G3 utterances | Candidates | Linear bound |', '| --- | ---: | ---: | ---: | ---: |']
    for col in packet['collections']:
        b=col['budget_proof'];lines.append(f'| {col["source_id"]} | {b["G2_anchor_count"]} | {b["G3_utterance_count"]} | {b["actual_candidates"]} | {b["linear_candidate_bound"]} |')
    lines += ['', '## Representation diagnostics', '', f'Panel counts: `{dict(represent_counts)}`. G1 remains unchanged. The following table separates factory representability from automatic discovery; neither column is a semantic result.', '', '| Check | Factory representation | Source-only exact candidate aliases | Admission/deferral |', '| --- | --- | ---: | --- |']
    for row in panel:
        r=row.get('representation',{});lines.append(f'| {row["check_id"]} | {r.get("status",row.get("status"))} | {len(row.get("source_only_matching_candidates",[]))} | {r.get("admission",r.get("reason",row.get("reason","")))} |')
    lines += ['', 'No model answers or costs are estimated here. The V2 34-item subset and $0.069 accounting ratio remain historical. New sparse selection can lose V2 hits; those regressions are disclosed rather than tuned away. Candidate counts are bounded engineering measurements, not corpus economics.', '', 'Use `pte analysis evidence-supply-collector-design --check-only` to reproduce the frozen source-only packet. Read `PROPOSAL.md` and `CHECK_DESIGN.md` for boundary, provenance and follow-on criteria. No paid execution flag exists.', '']
    lines += ['Source-only comparison to V2: `' + json.dumps(packet['source_only_supply_comparison'],sort_keys=True) + '`. These are physical exact-role matches, including diagnostic/quarantined records, not eligible positive observations.', '']
    return '\n'.join(lines)


def write_packet(packet):
    HERE.mkdir(parents=True,exist_ok=True)
    v2.dump(HERE/'design-v3.json',packet)
    (HERE/'GEOMETRY_REVIEW.md').write_text(render_packet(packet))
