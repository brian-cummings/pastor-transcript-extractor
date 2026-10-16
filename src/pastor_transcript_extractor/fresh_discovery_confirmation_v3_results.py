"""Match sealed V3 sources after independent census; never run a collector/provider."""
from collections import Counter
from datetime import datetime
from pathlib import Path
from pastor_transcript_extractor import fresh_discovery_confirmation_v3 as config
from pastor_transcript_extractor import fresh_discovery_confirmation_results as common

prep=config.prep
HERE=config.HERE
REVIEW=HERE/'source-review-v3.json'
EXPECTED_INVENTORY='e01ebd9652c9bee476c505390ff8c2345203af19becb6e16bda6ca25b411754f'


def inputs(base_dir=None):
    manifest,auth=config.verify(base_dir);root=config.directory(base_dir)
    freeze=prep.gate.sealed(root/'freeze-v3.json');refs=prep.gate.sealed(config.REFERENCES)
    # Check independent seals/timing BEFORE opening the natural inventory.
    if (freeze['inventory_fingerprint']!=EXPECTED_INVENTORY or refs['inventory_fingerprint']!=EXPECTED_INVENTORY
            or refs['candidate_inventory_opened_during_census'] is not False
            or refs['matching_seen_at_census_freeze'] is not False
            or datetime.fromisoformat(refs['frozen_at_utc'])<=datetime.fromisoformat(freeze['frozen_at_utc'])):
        raise ValueError('V3 census blinding/freeze identity invalid')
    inv_path=root/'natural-inventory-v3.json'
    if prep.proposal.a1.file_hash(inv_path)!=freeze['inventory_sha256']:raise ValueError('Frozen inventory bytes changed')
    inventory=prep.gate.sealed(inv_path)
    if (inventory['content_fingerprint']!=EXPECTED_INVENTORY or inventory['manifest_fingerprint']!=manifest['content_fingerprint']
            or inventory['authorization_fingerprint']!=auth['content_fingerprint'] or inventory['source_files']!=freeze['source_files']
            or inventory['provider_requests']!=0 or inventory['provider_execution_authorized'] is not False):
        raise ValueError('V3 inventory scope changed')
    for name,digest in inventory['code_hashes'].items():
        path=(prep.proposal.ROOT/name).resolve()
        if not path.is_relative_to(prep.proposal.ROOT.resolve()) or prep.proposal.a1.file_hash(path)!=digest:
            raise ValueError('Frozen collector/preparation implementation changed')
    common.frozen.census_validate(refs,inventory)
    sources={int(v):prep.gate.sealed(Path(info['path'])) for v,info in inventory['source_files'].items()}
    for vid,source in sources.items():
        info=inventory['source_files'][str(vid)]
        if prep.proposal.a1.file_hash(Path(info['path']))!=info['sha256']:raise ValueError('Frozen source bytes changed')
        census=prep.gate.sealed(Path(refs['census_files'][str(vid)]['path']))
        if census['source_fingerprint']!=source['content_fingerprint'] or census['natural_candidate_results_seen'] is not False:
            raise ValueError('Independent source-census identity changed')
    return manifest,auth,inventory,refs,sources


def prepare(base_dir=None):
    if REVIEW.exists():
        return finalize(base_dir)
    _,auth,inventory,refs,sources=inputs(base_dir);root=config.directory(base_dir)
    rows,matched=config.repair.comparison.match_rows(refs,inventory['inventories'])
    result=prep.seal(dict(version='fresh-v3-source-only-matches',inventory_fingerprint=inventory['content_fingerprint'],
        inventory_sha256=prep.proposal.a1.file_hash(root/'natural-inventory-v3.json'),reference_fingerprint=refs['content_fingerprint'],
        reference_sha256=prep.proposal.a1.file_hash(config.REFERENCES),records=rows,
        statistics=common.route_statistics(rows,list(sources),auth['criteria']),
        workload={str(c['video_id']):common.burden(c,sources[c['video_id']],matched,[x for x in refs['controls'] if x['video_id']==c['video_id']]) for c in inventory['inventories']},
        candidate_counts={str(c['video_id']):dict(Counter(e['candidate']['capability'] for e in c['entries'])) for c in inventory['inventories']},
        queue_units=len(inventory['queue']),queue_request_shapes=sum(len(q['shapes']) for q in inventory['queue']),
        provider_requests=0,provider_execution_authorized=False,target_envelope_review='PENDING_AUTHORED_SOURCE_REVIEW',
        admitted_items=None,semantic_measurements=None,usable_evidence=None,unit_cost=None,
        verdict='FAIL' if any(s['decision']=='FAIL' for s in common.route_statistics(rows,list(sources),auth['criteria']).values()) else 'HOLD_PENDING_SOURCE_REVIEW'))
    prep.save_new(root/'references-v3.json',refs);prep.save_new(root/'matches-v3.json',result)
    return result


def verify_review(base_dir=None):
    _,auth,inventory,refs,sources=inputs(base_dir);review=prep.gate.sealed(REVIEW)
    for name,info in review['artifacts'].items():
        path=Path(info['path'])
        if prep.proposal.a1.file_hash(path)!=info['sha256']:raise ValueError('V3 reviewed artifact changed: '+name)
    for name,digest in review['review_code_hashes'].items():
        if prep.proposal.a1.file_hash(prep.proposal.ROOT/name)!=digest:raise ValueError('V3 review code changed')
    if (review['inventory_fingerprint']!=inventory['content_fingerprint'] or review['reference_fingerprint']!=refs['content_fingerprint']
            or review['provider_requests']!=0 or review['provider_execution_authorized'] is not False):raise ValueError('Review scope changed')
    matches=prep.gate.sealed(config.directory(base_dir)/'matches-v3.json')
    if review['raw_statistics']!=matches['statistics']:
        raise ValueError('Review changed frozen match statistics')
    validate_source_reviews(review,matches,inventory,refs)

    return review


def validate_source_reviews(review,matches,inventory,refs):
    """Binding checks only; never infer or replace an authored source judgment."""
    by_ref={x['reference_id']:x for x in matches['records']}
    entries={e['candidate']['candidate_id']:e for c in inventory['inventories'] for e in c['entries']}
    if {x['reference_id'] for x in review['case_reviews']}!={x['reference_id'] for x in refs['rows']} or len(review['case_reviews'])!=len(refs['rows']):
        raise ValueError('Missing/duplicate reviewed reference')
    if {x['candidate_id'] for x in review['queue_reviews']}!={x['candidate_id'] for x in inventory['queue']} or len(review['queue_reviews'])!=len(inventory['queue']):
        raise ValueError('Missing/duplicate frozen queue review')
    for row in review['case_reviews']:
        key=row['candidate_id']
        if key is None:
            if by_ref[row['reference_id']]['role_containment_hits'] or row['compatible_supply_evidenced']:
                raise ValueError('Missing reviewed supplied target')
            continue
        if (key not in by_ref[row['reference_id']]['role_containment_hits'] or row['exact_target_roles']!=entries[key]['candidate']['endpoints']
                or row['automatic_envelope_span']!={k:entries[key]['automatic_envelope'][k] for k in ('start','end')}):
            raise ValueError('Source review replaced a frozen natural target')
        if row['compatible_supply_evidenced'] and (row['target_status']!='source_supported_compatible_target'
                or row['envelope_status']!='sufficient_source_provenance_context'
                or key not in by_ref[row['reference_id']]['required_evidence_coverage_hits']):
            raise ValueError('Geometry/unknown review cannot become compatible supply')
    for row in review['queue_reviews']:
        c=entries[row['candidate_id']]['candidate'];env=entries[row['candidate_id']]['automatic_envelope']
        expected=dict(claim=c['claim'],target=c['target']) if c['capability']=='G1' else c['endpoints']
        envelope=(dict(start=c['target']['start'],end=c['target']['end']) if c['capability']=='G1' else {k:env[k] for k in ('start','end')})
        if row['exact_target_roles']!=expected or row['automatic_envelope_span']!=envelope or row['provider_execution_authorized'] is not False:
            raise ValueError('Queue source review changed a target/envelope or spending authority')
    for route,counts in review['reviewed_compatible_supply'].items():
        rows=[x for x in review['case_reviews'] if x['route']==route]
        if counts['frozen_opportunities']!=len(rows) or counts['reviewed_compatible_hits']!=sum(x['compatible_supply_evidenced'] for x in rows):
            raise ValueError('Compatible source review counts changed')


def finalize(base_dir=None):
    review=verify_review(base_dir);root=config.directory(base_dir)
    result=prep.seal(dict(version='fresh-v3-source-only-results',inventory_fingerprint=review['inventory_fingerprint'],
        reference_fingerprint=review['reference_fingerprint'],source_review_fingerprint=review['content_fingerprint'],
        source_review_sha256=prep.proposal.a1.file_hash(REVIEW),verdict=review['recommendation'],G1_assurance='HOLD',
        raw_statistics=review['raw_statistics'],reviewed_compatible_supply=review['reviewed_compatible_supply'],
        diagnosis=review['diagnosis'],workload_summary=review['workload_summary'],
        census_questions=review['post_match_census_questions'],provider_requests=0,provider_execution_authorized=False,
        semantic_measurements=None,admitted_items=None,usable_unique_evidence=None,unit_cost=None,
        next_recommendation=review['next_recommendation']))
    prep.save_new(root/'results-v3.json',result)
    (root/'results-v3.md').write_text(render(result)+'\n')
    return result


def render(result):
    lines=['# Fresh V3 — source-only readiness result','',f"**{result['verdict']}; G1 assurance HOLD. Provider requests=0.**",'',
        '| Route | Opportunities | Role upper hits | Required-evidence upper hits | Decision |', '|---|---:|---:|---:|---|']
    for route,row in result['raw_statistics'].items():
        lines.append(f"| {route} | {row['opportunities']} | {row['complete_role_upper_bound_hits']} | {row['required_evidence_upper_bound_hits']} | {row['decision']} |")
    lines+=['','These are fixed-census source-supply counts, not semantic/provider accuracy or admitted evidence. Compatible-target/envelope review is separate; see the source-controlled source review for every case and frozen queue unit.',
        '',result['next_recommendation'],'','No collector, source-unit, reference, measurement/admission, threshold or model changes. No provider inference, collection or projection.']
    return '\n'.join(lines)
