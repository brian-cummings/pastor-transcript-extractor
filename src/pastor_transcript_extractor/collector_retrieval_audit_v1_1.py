"""Read-only, receipt-bound V1.1 source audit. Never loads or reruns an encoder."""
from __future__ import annotations
import json
from pathlib import Path
from pastor_transcript_extractor import collector_retrieval_workflow_v1_1 as workflow

HERE=workflow.HERE
REVIEW=HERE/'development-source-audit-v1.1.json'


def load(base_dir=None):
    packet=workflow.verify()
    decision=workflow.require_execution(packet,packet['content_fingerprint'],'development_execution_authorized')
    root=workflow.directory(base_dir)/packet['content_fingerprint']
    result=workflow.design.sealed(root/'results-v1.1.json')
    natural=workflow.design.sealed(root/'natural-inventory-v1.1.json')
    sources=workflow.sources(packet)
    refs=workflow.design.sealed(Path(packet['reference_path']))
    if (result['input_fingerprint']!=packet['content_fingerprint'] or natural['input_fingerprint']!=packet['content_fingerprint']
            or result['execution_authorization_fingerprint']!=decision['content_fingerprint']
            or natural['execution_authorization_fingerprint']!=decision['content_fingerprint']
            or result['inventory_sha256']!=workflow.design.file_hash(root/'natural-inventory-v1.1.json')
            or natural['source_files']!=packet['source_files']
            or result['reference_fingerprint']!=refs['content_fingerprint']
            or result['provider_requests']!=0 or natural['provider_requests']!=0
            or any(result[k] is not None for k in ('semantic_measurements','admitted_items','usable_unique_evidence','unit_cost'))):
        raise ValueError('V1.1 result/source/authority binding mismatch')
    for vid,source in sources.items():
        checkpoint=workflow.design.sealed(root/f'source-{vid}.json')
        if (checkpoint['input_fingerprint']!=packet['content_fingerprint']
                or checkpoint['execution_authorization_fingerprint']!=decision['content_fingerprint']
                or checkpoint['source_fingerprint']!=source['content_fingerprint']):
            raise ValueError('V1.1 source checkpoint binding mismatch')
        col=checkpoint['collection'];inv=next(c for c in natural['inventories'] if c['video_id']==vid)
        for key in ('descriptors','G2_primary','G2_role_construction','G3_construction','retrieval_trace','composition_trace',
                    'G3_displacements','lattice_diagnostics','resource_counts','budget_proof'):
            if col[key]!=inv[key]:raise ValueError('Inventory trace differs from sealed source checkpoint')
        original={c['candidate_id']:c for c in col['G1_candidates']+col['candidates']}
        if set(original)!={e['candidate']['candidate_id'] for e in inv['entries']}:
            raise ValueError('Inventory candidate set differs from source checkpoint')
        for e in inv['entries']:
            candidate=original[e['candidate']['candidate_id']].copy()
            if candidate['capability']!='G1':
                if candidate.pop('automatic_envelope')!=e['automatic_envelope']:
                    raise ValueError('Inventory envelope changed')
            if candidate!=e['candidate']:raise ValueError('Inventory candidate changed')
    return packet,result,natural,refs,sources


def validate(review,result,natural,refs):
    entries={e['candidate']['candidate_id']:e for col in natural['inventories'] for e in col['entries']}
    matches={r['reference_id']:r for r in result['historical_exact_target_diagnostics']}
    expected={r['reference_id'] for r in refs['rows']}
    cases=review['historical_case_reviews']
    if len(cases)!=len(expected) or {r['reference_id'] for r in cases}!=expected:
        raise ValueError('V1.1 audit must preserve every frozen check')
    for row in cases:
        match=matches[row['reference_id']];key=row['candidate_id']
        if key is None:
            if match['role_containment_hits']:raise ValueError('Supplied case lacks source review')
            continue
        if key not in match['role_containment_hits']:raise ValueError('Reviewed candidate is not a frozen-role hit')
        e=entries[key]
        if row['target_roles']!=e['candidate']['endpoints'] or row['envelope_span']!={k:e['automatic_envelope'][k] for k in ('start','end')}:
            raise ValueError('Audit narrowed or replaced natural target/envelope')
        if row['source_supported_P1_input'] and key not in match['required_evidence_coverage_hits']:
            raise ValueError('Missing source context cannot become P1 compatible supply')
    for row in review['P1_annotations']:
        e=entries[row['candidate_id']]
        if row['exact_target_roles']!=e['candidate']['endpoints'] or row['envelope_span']!={k:e['automatic_envelope'][k] for k in ('start','end')}:
            raise ValueError('P1 audit changed a supplied target')
        if row['annotation_is_new_gold'] or row['historical_score_change'] or row['pastor_credit']:
            raise ValueError('P1 audit cannot grant measurement or historical credit')
    quota={(c['video_id'],i,d['parent'],d['source_span']['start'],d['source_span']['end'])
        for c in natural['inventories'] for i,d in enumerate(c['G3_displacements'])}
    reviews=review['G3_quota_displacement_reviews']
    if len(reviews)!=len(quota) or {(r['video_id'],r['index'],r['parent_unit'],r['source_span']['start'],r['source_span']['end']) for r in reviews}!=quota:
        raise ValueError('Missing or changed quota review')
    if {r['control_id'] for r in review['controls']}!={r['control_id'] for r in refs['controls']}:
        raise ValueError('Missing frozen controls')
    missed={r['reference_id'] for r in result['historical_exact_target_diagnostics'] if r['route']=='G2_explanation' and not r['role_containment_hits']}
    if {r['reference_id'] for r in review['G2_miss_reviews']}!=missed:
        raise ValueError('Missing G2 miss diagnosis')


def verify(base_dir=None):
    packet,result,natural,refs,_=load(base_dir)
    review=workflow.design.sealed(REVIEW)
    if (review['input_fingerprint']!=packet['content_fingerprint']
            or review['result_fingerprint']!=result['content_fingerprint']
            or review['inventory_fingerprint']!=natural['content_fingerprint']
            or review['recommendation']!='DEVELOPMENT_FAIL_STOP_THIS_ARCHITECTURE'
            or review['provider_requests']!=0 or review['G1_assurance']!='HOLD'):
        raise ValueError('V1.1 review result/scope mismatch')
    for item in review['artifacts'].values():
        if workflow.design.file_hash(Path(item['path']))!=item['sha256']:
            raise ValueError('V1.1 reviewed artifact byte hash changed')
    for name,digest in review['audit_code_pins'].items():
        if workflow.design.file_hash(workflow.design.ROOT/name)!=digest:
            raise ValueError('V1.1 audit verifier changed')
    validate(review,result,natural,refs)
    return review
