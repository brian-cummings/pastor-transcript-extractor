"""Read-only binding verification for the authorized retired-source audit."""
from __future__ import annotations
from pathlib import Path
import copy
import json
from pastor_transcript_extractor import collector_retrieval_workflow as workflow

HERE=workflow.HERE
REVIEW=HERE/'development-source-audit-v1.json'



def original_output_seal(path):
    """Read-only recovery of the exact writer's typed integer-key preimage.

    Never rewrite/reseal output or accept a hash mismatch. Only the known
    per_unit_saturation fields regain their writer's integer keys for checking.
    Returned data stays JSON-shaped. Canonical JSON seal defect remains disclosed.
    """
    value=json.loads(Path(path).read_text()); original=copy.deepcopy(value)
    if 'collection' in original:
        maps=[original['collection']['lattice_diagnostics']]
    elif 'inventories' in original:
        maps=[c['lattice_diagnostics'] for c in original['inventories']]
    elif 'G3_budget_displacement' in original:
        maps=list(original['G3_budget_displacement'].values())
    else:
        raise ValueError('Unknown legacy output schema')
    for item in maps:
        keys=item['per_unit_saturation']
        if any(not k.isdecimal() or str(int(k))!=k for k in keys):
            raise ValueError('Unexpected saturation-map key')
        item['per_unit_saturation']={int(k):v for k,v in keys.items()}
    if workflow.prep.seal(original)['content_fingerprint']!=value['content_fingerprint']:
        raise ValueError('Original output fingerprint does not reproduce')
    return value


def load(base_dir=None):
    packet=workflow.verify();root=workflow.directory(base_dir)/packet['content_fingerprint']
    result=original_output_seal(root/'results-v1.json')
    natural=original_output_seal(root/'natural-inventory-v1.json')
    authority=workflow.design.sealed(workflow.EXECUTION)
    if (result['input_fingerprint']!=packet['content_fingerprint']
            or natural['input_fingerprint']!=packet['content_fingerprint']
            or result['inventory_sha256']!=workflow.design.file_hash(root/'natural-inventory-v1.json')
            or result['execution_authorization_fingerprint']!=authority['content_fingerprint']
            or natural['execution_authorization_fingerprint']!=authority['content_fingerprint']
            or result['provider_requests']!=0 or natural['provider_requests']!=0
            or natural['source_files']!=packet['source_files']):
        raise ValueError('Development result/inventory authority changed')
    refs=workflow.design.sealed(Path(packet['reference_path']))
    if workflow.design.file_hash(Path(packet['reference_path']))!=packet['reference_sha256']:
        raise ValueError('Frozen historical references changed')
    return packet,result,natural,refs,workflow.sources(packet)


def validate_cases(review,result,natural,refs):
    entries={e['candidate']['candidate_id']:e for source in natural['inventories'] for e in source['entries']}
    expected={r['reference_id'] for r in refs['rows']}
    rows=review['historical_case_reviews']
    if len(rows)!=len(expected) or {r['reference_id'] for r in rows}!=expected:
        raise ValueError('Missing or duplicate historical case review')
    match={r['reference_id']:r for r in result['historical_exact_target_diagnostics']}
    for r in rows:
        key=r['candidate_id']
        if key is None:
            if r['source_compatible_supply'] or match[r['reference_id']]['role_containment_hits']:
                raise ValueError('Missing supplied-target review')
            continue
        if (key not in match[r['reference_id']]['role_containment_hits']
                or r['target_roles']!=entries[key]['candidate']['endpoints']
                or r['envelope_span']!={k:entries[key]['automatic_envelope'][k] for k in ('start','end')}):
            raise ValueError('Audit replaced a natural historical target')
        if r['source_compatible_supply'] and (r['target_status']!='source_supported_compatible'
                or key not in match[r['reference_id']]['required_evidence_coverage_hits']):
            raise ValueError('Unestablished target/context cannot become compatible supply')
    for row in review.get('P1_annotations',[]):
        if row.get('historical_score_change') is not False:
            raise ValueError('P1 annotation must not revise a historical score')
        for key in row.get('candidate_ids',[]):
            if key not in entries: raise ValueError('P1 annotation references unknown natural candidate')
            entry=entries[key]
            if row['exact_target_roles']!=entry['candidate']['endpoints'] or row['envelope_span']!={k:entry['automatic_envelope'][k] for k in ('start','end')}:
                raise ValueError('P1 annotation changed a natural target/envelope')
        if row.get('annotation_is_new_gold') is not False or row.get('no_manual_narrowing') is not True:
            raise ValueError('P1 quality annotation cannot manufacture new historical gold')
    displaced={(f'D{c["video_id"]}-{i:03}',c['video_id'],d['parent'],d['source_span']['start'],d['source_span']['end'])
        for c in natural['inventories'] for i,d in enumerate(c['G3_displacements'])}
    reviews=review['G3_quota_displacement_reviews']
    actual={(r['displacement_id'],r['video_id'],r['parent_unit'],r['source_span']['start'],r['source_span']['end']) for r in reviews}
    if len(reviews)!=len(displaced) or actual!=displaced:
        raise ValueError('Missing/changed G3 quota displacement review')
    if {r['control_id'] for r in review['controls']}!={r['control_id'] for r in refs['controls']}:
        raise ValueError('Missing source control review')


def verify(base_dir=None):
    packet,result,natural,refs,source_files=load(base_dir);review=workflow.design.sealed(REVIEW)
    root=workflow.directory(base_dir)/packet['content_fingerprint']
    for vid,source in source_files.items():
        checkpoint=original_output_seal(root/f'source-{vid}.json')
        if (checkpoint['input_fingerprint']!=packet['content_fingerprint']
                or checkpoint['source_fingerprint']!=source['content_fingerprint']
                or checkpoint['execution_authorization_fingerprint']!=result['execution_authorization_fingerprint']):
            raise ValueError('Checkpoint authority/source binding changed')
    if (review['input_fingerprint']!=packet['content_fingerprint']
            or review['result_fingerprint']!=result['content_fingerprint']
            or review['inventory_fingerprint']!=natural['content_fingerprint']
            or review['provider_requests']!=0 or review['semantic_measurements'] is not None):
        raise ValueError('Audit scope/result changed')
    for item in review['artifacts'].values():
        if workflow.design.file_hash(Path(item['path']))!=item['sha256']:
            raise ValueError('Reviewed artifact changed')
    validate_cases(review,result,natural,refs)
    return review
