"""Read-only verification of the authored source-unit development audit.

No collector replay, semantic execution, matching revision or source selection.
"""
from pathlib import Path
from pastor_transcript_extractor import source_unit_repair as repair

HERE=repair.HERE
REVIEW=HERE/'source-audit-v1.json'


def validate_summary(review):
    recovered=review['recovered_cases'];misses=review['remaining_segmentation_cases']
    ids=[r['reference_id'] for r in recovered+misses]
    if (len(recovered)!=47 or len(misses)!=7 or len(set(ids))!=54
            or any(r['usable_atomic_evidence_certified'] is not False for r in recovered)
            or len(review['persistent_G2_cases'])!=4 or len(review['preserved_G3_questions'])!=4
            or review['provider_requests']!=0 or review['implementation_changed'] is not False
            or review['confirmation_selected'] is not False):
        raise ValueError('Audit counts/scope changed')


def verify_review(base_dir=None):
    packet,_=repair.verify(base_dir);review=repair.prep.gate.sealed(REVIEW)
    expected=repair.directory(base_dir).resolve()/packet['content_fingerprint']
    if review['input_fingerprint']!=packet['content_fingerprint']:
        raise ValueError('Foreign repair input')
    for name,info in review['artifacts'].items():
        path=Path(info['path']).resolve()
        if name in {'results','inventory'} and path.parent!=expected:
            raise ValueError('Foreign runtime audit artifact')
        if repair.prep.proposal.a1.file_hash(path)!=info['sha256']:
            raise ValueError(f'Audited artifact changed: {name}')
    for name,digest in review['review_code_hashes'].items():
        path=(repair.prep.proposal.ROOT/name).resolve()
        if not path.is_relative_to(repair.prep.proposal.ROOT.resolve()) or repair.prep.proposal.a1.file_hash(path)!=digest:
            raise ValueError('Audit verification code/test changed')
    result=repair.prep.gate.sealed(expected/'results-v1.json')
    inventory=repair.prep.gate.sealed(expected/'natural-inventory-v1.json')
    if (result['content_fingerprint']!=review['result_fingerprint']
            or inventory['content_fingerprint']!=review['inventory_fingerprint']
            or result['inventory_sha256']!=review['artifacts']['inventory']['sha256']
            or result['provider_requests']!=0 or inventory['provider_requests']!=0):
        raise ValueError('Audit result/inventory identity changed')
    validate_summary(review)
    return review
