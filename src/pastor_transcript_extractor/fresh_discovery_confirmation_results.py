"""Source-only Fresh V2 matching/reporting; never infer provider answers."""
from __future__ import annotations
from collections import Counter
from datetime import datetime
from pathlib import Path
import json,math,statistics

from pastor_transcript_extractor import fresh_discovery_confirmation as confirmation
from pastor_transcript_extractor import fresh_discovery_results as frozen

prep=confirmation.prep
REFERENCES=confirmation.HERE/'references-v2.1.json'
REVIEW=confirmation.HERE/'preparation-review-v2.json'
ROUTES=('G1_assurance','G2_explanation','G3_current','G3_reported')


def route_statistics(rows,ids,criteria):
    stats={}
    for rt in ROUTES:
        rr=[r for r in rows if r['route']==rt and r['classification']=='definite_compatible_opportunity']
        n=len(rr);h=sum(bool(r['role_containment_hits']) for r in rr);e=sum(bool(r['required_evidence_coverage_hits']) for r in rr)
        cells={}
        for vid in ids:
            ss=[r for r in rr if r['video_id']==vid];nn=len(ss);hh=sum(bool(r['role_containment_hits']) for r in ss)
            cells[str(vid)]=dict(opportunities=nn,hits=hh,recall_upper_bound=hh/nn if nn else None,
                gate=frozen.source_gate(hh,nn,minimum=criteria['per_source_minimum'],threshold=criteria['per_source_recall']))
        if n<criteria['aggregate_floors'][rt]:decision='HOLD'
        elif h/n<criteria['aggregate_recall'] or e/n<criteria['aggregate_sufficient_envelope_recall'] or any(c['gate']=='FAIL' for c in cells.values()):decision='FAIL'
        else:decision='PENDING_TARGET_ENVELOPE_AUDIT'
        stats[rt]=dict(opportunities=n,complete_role_upper_bound_hits=h,complete_role_recall_upper_bound=h/n if n else None,
            required_evidence_upper_bound_hits=e,required_evidence_recall_upper_bound=e/n if n else None,
            aggregate_floor=criteria['aggregate_floors'][rt],per_source=cells,decision=decision)
    return stats


def distribution(values):
    values=sorted(values)
    return dict(n=len(values),minimum=min(values) if values else None,median=statistics.median(values) if values else None,
        p90=values[math.ceil(.9*len(values))-1] if values else None,maximum=max(values) if values else None,total=sum(values))


def miss_diagnostic(ref,entries,source,nodes,hits,enough):
    if hits:return dict(cause=None if enough else 'required_evidence_outside_automatic_envelope')
    oversized=[]
    for role,span in ref['roles'].items():
        oversized.extend(dict(role=role,start=n['start'],end=n['end'],chars=n['end']-n['start']) for n in nodes if frozen.contains(n,span) and n['end']-n['start']>6000)
    cap=ref['capability']
    if cap in {'G2','G3'}:
        endpoints=dict(ref['roles'])
        if cap=='G3':endpoints['circumstance']=None
        authored=prep.collector.represent(source,cap,endpoints)
    else:authored=dict(status='not_tested')
    cause=('oversize_punctuation_unit_prevents_bounded_role_materialization' if oversized else
        'complete_directed_pair_not_materialized' if cap=='G2' else 'complete_atomic_target_not_materialized' if cap=='G3' else 'G1_nomination_or_complete_framing_miss')
    return dict(cause=cause,oversized_covering_units=oversized,authored_geometry_status=authored['status'],
        authored_geometry_reason=authored.get('reason'),manual_rescue_discovery_credit=0,
        note='Authored exact roles are representability diagnostics only; no repaired candidate/envelope enters discovery or the frozen queue.')


def burden(collection,source,matched,controls):
    entries=collection['entries'];n=collection['budget_proof']['sentence_count'];chars=source['main_span']['end']-source['main_span']['start']
    counts=Counter(e['candidate']['capability'] for e in entries);contacts=[]
    for ctrl in controls:
        ids=[]
        for entry in entries:
            c=entry['candidate'];targets=[c['claim']] if c['capability']=='G1' else [c['endpoints']['utterance']] if c['capability']=='G3' else list(c['endpoints'].values())
            if any(s is not None and frozen.contains(s,ctrl['span']) for s in targets):ids.append(c['candidate_id'])
        contacts.append(dict(control_id=ctrl['control_id'],classification=ctrl['classification'],candidate_ids=ids))
    frames=[];envelopes=[]
    for entry in entries:
        c=entry['candidate'];env=entry['automatic_envelope'];frame=c['target'] if c['capability']=='G1' else c['relation_frame']
        frames.append(frame['end']-frame['start'])
        if c['capability']=='G1':envelopes.append(len(c['target']['text'])+len(c['leading_context'])+len(c['trailing_context']))
        elif env['status']=='prepared_not_attested':envelopes.append(env['end']-env['start'])
    return dict(main_chars=chars,sentence_nodes=n,counts=dict(counts),
        candidate_density_per_1000_main_chars={cap:count*1000/chars for cap,count in counts.items()},
        candidate_density_per_100_sentence_nodes={cap:count*100/n if n else None for cap,count in counts.items()},
        full_inventory_measurement_request_slots=counts['G1']+counts['G2']+2*counts['G3'],
        full_inventory_slots_note='One G1/G2 request and two isolated G3 phases per candidate; hypothetical processing work, not execution authority, token usage or usable evidence.',
        reference_unmatched_candidates=sum(e['candidate']['candidate_id'] not in matched for e in entries),
        control_contacts=contacts,frame_chars=distribution(frames),envelope_chars=distribution(envelopes),
        deferral_counts=dict(Counter(d['reason'] for d in collection['deferrals'])),
        deferred_source_role_records=len(collection['deferrals']),
        structural_work_diagnostics=dict(Counter(d['reason'] for d in collection['search_diagnostics'])),
        certified_semantic_false_positive_candidates=None,active_candidate_review_minutes=None,
        candidate_namespace_note='G3 current/reported provenance is not automatically assigned. Raw G3 volume is combined; opportunity recall namespaces are source-audited separately.',
        interpretation='Unmatched candidates and mixed/ambiguous control contacts are review-work proxies, not false positives, precision or admitted evidence.')


def prepare(base_dir=None):
    manifest,auth=confirmation.verify(base_dir);root=confirmation.directory(base_dir)
    inventory=prep.gate.sealed(root/'natural-inventory-v1.json');freeze=prep.gate.sealed(root/'freeze-v2.json')
    if (freeze['inventory_fingerprint']!=inventory['content_fingerprint'] or freeze['inventory_sha256']!=prep.proposal.a1.file_hash(root/'natural-inventory-v1.json')
            or freeze['references_existed_at_freeze'] is not False):raise ValueError('Fresh V2 inventory changed')
    for name,digest in inventory['code_hashes'].items():
        if prep.proposal.a1.file_hash(prep.proposal.ROOT/name)!=digest:raise ValueError('Frozen collector/preparation code changed')
    refs=prep.gate.sealed(REFERENCES);frozen.census_validate(refs,inventory)
    if datetime.fromisoformat(freeze['frozen_at_utc'])>=datetime.fromisoformat(refs['frozen_at_utc']):raise ValueError('Census must follow inventory freeze')
    sources={int(vid):prep.gate.sealed(Path(info['path'])) for vid,info in inventory['source_files'].items()}
    rows=[];matched=set()
    for ref in refs['rows']:
        entries=next(c['entries'] for c in inventory['inventories'] if c['video_id']==ref['video_id'])
        hits=[e for e in entries if frozen.geometric_match(ref,e)];enough=[e for e in hits if frozen.coverage(ref,e)]
        if ref['classification']=='definite_compatible_opportunity':matched.update(e['candidate']['candidate_id'] for e in hits)
        source=sources[ref['video_id']];nodes=confirmation.repair.collector.source_sentences(source)
        rows.append(dict(reference_id=ref['reference_id'],video_id=ref['video_id'],route=frozen.route(ref),classification=ref['classification'],
            role_containment_hits=[e['candidate']['candidate_id'] for e in hits],required_evidence_coverage_hits=[e['candidate']['candidate_id'] for e in enough],
            diagnostic=miss_diagnostic(ref,entries,source,nodes,hits,enough)))
    stats=route_statistics(rows,list(sources),auth['criteria'])
    workloads={str(c['video_id']):burden(c,sources[c['video_id']],matched,[x for x in refs['controls'] if x['video_id']==c['video_id']]) for c in inventory['inventories']}
    shape_stats={}
    for vid,source in sources.items():
        nodes=confirmation.repair.collector.source_sentences(source)
        shape_stats[str(vid)]=dict(sentence_nodes=len(nodes),sentence_chars=distribution([n['end']-n['start'] for n in nodes]),
            units_over_6000=[dict(start=n['start'],end=n['end'],chars=n['end']-n['start']) for n in nodes if n['end']-n['start']>6000],
            source_kind=source['source_manifest_row']['source_kind'])
    result=prep.seal(dict(version='fresh-provider-free-results-v2',inventory_fingerprint=inventory['content_fingerprint'],
        inventory_sha256=prep.proposal.a1.file_hash(root/'natural-inventory-v1.json'),reference_fingerprint=refs['content_fingerprint'],reference_sha256=prep.proposal.a1.file_hash(REFERENCES),
        freeze_fingerprint=freeze['content_fingerprint'],statistics=stats,records=rows,workload=workloads,source_shapes=shape_stats,
        source_ids=list(sources),source_manifest_fingerprint=manifest['content_fingerprint'],reference_opportunities=len(refs['rows']),controls=len(refs['controls']),
        failure_counts=dict(Counter(r['diagnostic']['cause'] for r in rows if r['diagnostic']['cause'])),
        frozen_queue_units=len(inventory['queue']),frozen_queue_request_shapes=sum(len(q['shapes']) for q in inventory['queue']),
        semantic_input=None,semantic_measurements=None,admitted_items=None,provider_requests=0,provider_execution_authorized=False,
        verdict='FAIL' if any(x['decision']=='FAIL' for x in stats.values()) else 'HOLD',
        safe_envelope_recall_certified=False,manual_rescue_discovery_credit=0,
        review_burden=dict(active_human_minutes=None,median_active_candidate_review_minutes=None,p90_active_candidate_review_minutes=None,
            manual_envelope_repair_fraction=None,unresolved_candidate_review_deferral_fraction=None,
            reason='Source-only census complete, but semantic candidate/claim-witness review and human throughput not measured. No semantic outputs exist. No safe-envelope PASS is inferred from required-span coverage.'),
        semantic_packet_reason='Do not prepare/execute paid inference after decisive discovery failure; if upper bounds are not decisive, source-target/envelope audit precedes any separately authorized semantic decision.',
        holds=auth['holds']))
    prep.save_new(root/'references-v2.json',refs);prep.save_new(root/'results-v2.json',result)
    (root/'results-v2.md').write_text(render(result)+'\n')
    return result


def render(result):
    lines=['# Fresh Discovery/Readiness V2 — source-only result','',f"**Recommendation: {result['verdict']}. Zero provider requests.**",'',
        '| Route | Opportunities | Complete-role upper hits | Required-evidence upper hits | Decision |','|---|---:|---:|---:|---|']
    for rt,s in result['statistics'].items():lines.append(f"| {rt} | {s['opportunities']} | {s['complete_role_upper_bound_hits']} | {s['required_evidence_upper_bound_hits']} | {s['decision']} |")
    lines+=['','These are complete-role and enumerated-required-span upper bounds, not certified safe automatic envelopes, semantic positives or admitted evidence.','',
        'Raw G3 candidate volume is not assigned current/reported namespaces automatically. See JSON workload/source-shape/deferral/control-contact records. Unknown review throughput, precision and unit economics remain unknown.',
        '', 'Collector V4.1 and all measurement/admission contracts remain unchanged. No source replacement due to sparse opportunities or poor discovery. The reserve replaced an independently evidenced non-sermon before discovery.',
        '', 'A failed recall upper bound is decisive; paid inference cannot restore unsupplied evidence. No provider execution or fresh semantic input is authorized.']
    return '\n'.join(lines)


def verify_review(base_dir=None):
    confirmation.verify(base_dir);review=prep.gate.sealed(REVIEW)
    for name,digest in review['review_code_hashes'].items():
        if prep.proposal.a1.file_hash(prep.proposal.ROOT/name)!=digest:
            raise ValueError('Fresh V2 matching/review code changed')
    values=frozen.verify_bound_files(review['artifacts'])
    root=confirmation.directory(base_dir).resolve()
    for name in ('inventory','freeze','runtime_references','results'):
        if not Path(review['artifacts'][name]['path']).resolve().is_relative_to(root):
            raise ValueError('Foreign Fresh V2 runtime artifact')
    inventory=values['inventory'];result=values['results'];refs=values['references']
    frozen.census_validate(refs,inventory)
    for name,digest in inventory['code_hashes'].items():
        if prep.proposal.a1.file_hash(prep.proposal.ROOT/name)!=digest:raise ValueError('Frozen collector/preparation code changed')
    if (values['runtime_references']!=refs or result['inventory_fingerprint']!=inventory['content_fingerprint']
            or result['reference_fingerprint']!=refs['content_fingerprint'] or result['statistics']!=review['statistics']
            or result['verdict']!=review['recommendation'] or result['provider_requests']!=0
            or result['provider_execution_authorized'] is not False):raise ValueError('Fresh V2 result/review identity changed')
    return review
