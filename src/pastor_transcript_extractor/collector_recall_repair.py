"""Collector V4 development-only comparison and later fresh-source selection.

No provider imports or semantic execution. Dataset comparison is Brian's CLI
handoff. A new confirmation manifest never runs confirmation or constructs gold.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import hashlib
import json
import re
import sqlite3

from pastor_transcript_extractor import evidence_supply_collector_v4 as collector
from pastor_transcript_extractor import fresh_discovery_results as frozen

prep=frozen.prep
HERE=prep.proposal.ROOT/'docs/review-proposals/evidence-supply-collector-v4'
INPUT=HERE/'repair-input-v4.json'
AUTH=HERE/'authorization-v4.json'
ACCEPTANCE=prep.HERE/'acceptance-decision-v1.json'


def directory(base_dir=None):
    return prep.directory(base_dir).parent/'collector-recall-repair-v4'


def verify(base_dir=None):
    old=frozen.verify_preparation(base_dir)
    accepted=prep.gate.sealed(ACCEPTANCE);auth=prep.gate.sealed(AUTH);packet=prep.gate.sealed(INPUT)
    if (accepted['status']!='ACCEPTED' or accepted['discovery_readiness']!='FAIL'
            or accepted['G1_assurance']!='HOLD' or accepted['provider_execution_authorized'] is not False
            or accepted['review_sha256']!=prep.proposal.a1.file_hash(frozen.REVIEW)
            or auth['acceptance_sha256']!=prep.proposal.a1.file_hash(ACCEPTANCE)
            or auth['acceptance_fingerprint']!=accepted['content_fingerprint']
            or auth['implementation'] is not True or auth['provider_calls'] is not False
            or packet['authorization_sha256']!=prep.proposal.a1.file_hash(AUTH)
            or packet['policy']!=collector.POLICY
            or packet['development_video_ids']!=[1565,1450,1618]
            or packet['provider_calls_authorized'] is not False
            or packet['semantic_admission_changes_authorized'] is not False
            or packet['confirmation_execution_authorized'] is not False):
        raise ValueError('Collector repair authority/accepted decision changed')
    for name,digest in packet['code_hashes'].items():
        path=(prep.proposal.ROOT/name).resolve()
        if not path.is_relative_to(prep.proposal.ROOT.resolve()) or prep.proposal.a1.file_hash(path)!=digest:
            raise ValueError('Repair implementation/test pin changed')
    if packet['frozen_reference_sha256']!=old['artifacts']['references']['sha256']:
        raise ValueError('Development references changed')
    return packet,old


def entry_key(entry):
    c=entry['candidate']
    roles={k:c[k] for k in ('claim','target') if k in c} if c['capability']=='G1' else c['endpoints']
    return prep.baseline.fp(dict(capability=c['capability'],video_id=c['video_id'],roles=roles))


def match_rows(references,inventories):
    """Identical frozen geometry and required-span test; no revised gold."""
    rows=[];matched_ids=set()
    for ref in references['rows']:
        entries=next(i['entries'] for i in inventories if i['video_id']==ref['video_id'])
        hits=[e for e in entries if frozen.geometric_match(ref,e)]
        enough=[e for e in hits if frozen.coverage(ref,e)]
        if ref['classification']=='definite_compatible_opportunity':
            matched_ids.update(e['candidate']['candidate_id'] for e in hits)
        rows.append(dict(reference_id=ref['reference_id'],video_id=ref['video_id'],route=frozen.route(ref),
            classification=ref['classification'],role_containment_hits=[e['candidate']['candidate_id'] for e in hits],
            required_evidence_coverage_hits=[e['candidate']['candidate_id'] for e in enough]))
    return rows,matched_ids


def compare_rows(before,after):
    """Development recovery/regressions only; no .80 development PASS gate."""
    old={r['reference_id']:r for r in before};groups={}
    for route in ('G1_assurance','G2_explanation','G3_current','G3_reported'):
        rows=[r for r in after if r['route']==route and r['classification']=='definite_compatible_opportunity']
        recovered=[r['reference_id'] for r in rows if r['role_containment_hits'] and not old[r['reference_id']]['role_containment_hits']]
        lost=[r['reference_id'] for r in rows if not r['role_containment_hits'] and old[r['reference_id']]['role_containment_hits']]
        n=len(rows);hits=sum(bool(r['role_containment_hits']) for r in rows)
        groups[route]=dict(opportunities=n,baseline_upper_bound_hits=sum(bool(old[r['reference_id']]['role_containment_hits']) for r in rows),
            development_upper_bound_hits=hits,development_recall_upper_bound=hits/n if n else None,
            required_evidence_upper_bound_hits=sum(bool(r['required_evidence_coverage_hits']) for r in rows),
            recovered_reference_ids=recovered,regressed_reference_ids=lost,
            remaining_miss_ids=[r['reference_id'] for r in rows if not r['role_containment_hits']],
            per_source={str(v):dict(opportunities=len(ss:=[r for r in rows if r['video_id']==v]),hits=sum(bool(r['role_containment_hits']) for r in ss)) for v in (1565,1450,1618)})
    return groups


def burden(entries,old_entries,matched_ids,controls):
    old_keys={entry_key(e) for e in old_entries}
    new=[e for e in entries if entry_key(e) not in old_keys]
    control_contacts=[]
    for ctrl in controls:
        span=ctrl['span'];hits=[]
        for e in entries:
            c=e['candidate']
            targets=[c['claim']] if c['capability']=='G1' else [c['endpoints']['utterance']] if c['capability']=='G3' else list(c['endpoints'].values())
            if any(t is not None and frozen.contains(t,span) for t in targets):hits.append(c['candidate_id'])
        control_contacts.append(dict(control_id=ctrl['control_id'],classification=ctrl['classification'],candidate_ids=hits))
    return dict(candidates=len(entries),baseline_candidates=len(old_entries),new_role_geometries=len(new),
        reference_unmatched_candidate_count=sum(e['candidate']['candidate_id'] not in matched_ids for e in entries),
        new_reference_unmatched_candidate_count=sum(e['candidate']['candidate_id'] not in matched_ids for e in new),
        control_contacts=control_contacts,semantically_false_positive_candidates=None,
        note='Unmatched candidates can be valid evidence outside the census. Control contacts can include mixed or ambiguous targets; they are review-work proxies, not semantic false positives, precision or admitted evidence.')


def run_development(base_dir=None,approve_input=None):
    packet,review=verify(base_dir)
    if approve_input!=packet['content_fingerprint']:raise ValueError('Use the exact prepared repair input fingerprint')
    out=directory(base_dir)/packet['content_fingerprint']
    if (out/'results-v4.json').exists():
        return verify_result(base_dir,out/'results-v4.json')
    old_inventory=prep.gate.sealed(Path(review['artifacts']['inventory']['path']))
    # Discovery receives only source text/policy. References enter after all three
    # new inventories and their source-only envelopes have been materialized.
    inventories=[];total=0
    for vid in packet['development_video_ids']:
        source=prep.gate.sealed(Path(old_inventory['source_files'][str(vid)]['path']))
        if len(source['text'])>150000:raise ValueError('Source character ceiling exceeded')
        collection=collector.discover(source)
        total+=len(collection['candidates'])
        if total>collector.POLICY['total_candidate_ceiling']:raise ValueError('Aggregate candidate ceiling exceeded; no truncation')
        entries=[]
        for c in collection['G1_candidates']+collection['candidates']:
            env=(dict(status='prepared_not_attested',target=c['target'],leading_context=c['leading_context'],trailing_context=c['trailing_context'])
                 if c['capability']=='G1' else prep.automatic_envelope(source,c))
            entries.append(dict(candidate=c,automatic_envelope=env))
        inventories.append(dict(video_id=vid,entries=entries,deferrals=collection['deferred'],budget_proof=collection['budget_proof'],search_diagnostics=collection['search_diagnostics']))
    natural=prep.seal(dict(version='collector-v4-development-natural-inventory',repair_input_fingerprint=packet['content_fingerprint'],
        source_files=old_inventory['source_files'],inventories=inventories,provider_requests=0,confirmation_evidence=False))
    prep.save_new(out/'natural-inventory-v4.json',natural)
    references=prep.gate.sealed(frozen.REFERENCES)
    baseline=prep.gate.sealed(Path(review['artifacts']['matches']['path']))
    rows,matched_ids=match_rows(references,inventories);comparison=compare_rows(baseline['records'],rows)
    workloads={}
    for col in inventories:
        vid=col['video_id'];old=next(i['entries'] for i in old_inventory['inventories'] if i['video_id']==vid)
        workloads[str(vid)]=burden(col['entries'],old,matched_ids,[r for r in references['controls'] if r['video_id']==vid])
    result=prep.seal(dict(version='collector-v4-development-results',repair_input_fingerprint=packet['content_fingerprint'],
        generated_at_utc=datetime.now(timezone.utc).isoformat(),natural_inventory_path=str(out/'natural-inventory-v4.json'),
        natural_inventory_sha256=prep.proposal.a1.file_hash(out/'natural-inventory-v4.json'),reference_fingerprint=references['content_fingerprint'],
        comparison=comparison,records=rows,workload=workloads,
        candidate_counts={str(i['video_id']):dict(Counter(e['candidate']['capability'] for e in i['entries'])) for i in inventories},
        deferrals={str(i['video_id']):dict(Counter(d['reason'] for d in i['deferrals'])) for i in inventories},
        linear_candidate_bound=sum(i['budget_proof']['linear_candidate_bound'] for i in inventories),G2_G3_candidates=total,
        provider_requests=0,semantic_measurements=None,admitted_items=None,certified_envelope_recall=None,
        verdict='DEVELOPMENT_DIAGNOSTIC_NOT_CONFIRMATION',recommendation='Codex reviews recovery, regressions and candidate/control burden before fresh confirmation selection; no automatic recall PASS.',
        full_semantic_false_positive_audit=False,human_review_throughput=None))
    prep.save_new(out/'results-v4.json',result)
    (out/'results-v4.md').write_text(render(result)+'\n')
    return result


def verify_result(base_dir,result_path):
    packet,_=verify(base_dir);result_path=Path(result_path).resolve()
    expected=directory(base_dir)/packet['content_fingerprint']/'results-v4.json'
    if result_path!=expected.resolve():raise ValueError('Foreign development results path')
    result=prep.gate.sealed(result_path)
    if result['repair_input_fingerprint']!=packet['content_fingerprint'] or result['provider_requests']!=0:
        raise ValueError('Development result identity/provider count changed')
    natural=Path(result['natural_inventory_path'])
    if natural.resolve()!=expected.parent/'natural-inventory-v4.json' or prep.proposal.a1.file_hash(natural)!=result['natural_inventory_sha256']:
        raise ValueError('Development inventory changed')
    inventory=prep.gate.sealed(natural)
    if (inventory['repair_input_fingerprint']!=packet['content_fingerprint']
            or inventory['provider_requests']!=0 or inventory['confirmation_evidence'] is not False
            or result['semantic_measurements'] is not None or result['admitted_items'] is not None):
        raise ValueError('Development inventory scope changed')
    return result


def render(result):
    lines=['# Collector V4 development comparison','', '**Development diagnostics only; no confirmation PASS or semantic evidence.**','',
        '| Route | Baseline hits | V4 hits | Opportunities | Recovered | Regressed |','|---|---:|---:|---:|---:|---:|']
    for rt,r in result['comparison'].items():
        lines.append(f"| {rt} | {r['baseline_upper_bound_hits']} | {r['development_upper_bound_hits']} | {r['opportunities']} | {len(r['recovered_reference_ids'])} | {len(r['regressed_reference_ids'])} |")
    lines+=['',f"G2/G3 candidates: {result['G2_G3_candidates']}; source-derived bound {result['linear_candidate_bound']}. Provider requests=0.",
        '', 'Counts are complete-role/required-span upper bounds. Candidate/control contacts and unmatched new geometries quantify potential review work, not semantic false positives. Raw semantics, safe envelopes, admission and human review throughput are unmeasured.',
        '', 'Review the JSON for every recovery, regression, remaining miss, deferral, candidate count and control contact. Do not regenerate or edit the frozen Fresh V1 references. Fresh V1 is retired from confirmation.',
        '', 'No fixed .80 development gate. Decide whether the demonstrated failure classes have materially improved with acceptable burden; then prepare new mechanically selected sources. No paid calls, collection or projection.']
    return '\n'.join(lines)


def select_confirmation_rows(rows,extracted_metadata,excluded_sources,excluded_videos,salt='fresh-discovery-readiness-v2:'):
    """Metadata-only selection; never accepts candidates or reference labels."""
    selected=[];used=set(excluded_sources)
    for row in sorted(rows,key=lambda r:hashlib.sha256((salt+r['youtube_video_id']).encode()).hexdigest()):
        if row['source_id'] in used or row['video_id'] in excluded_videos:continue
        if re.search(r'bible study|bible answers live|q\s*&\s*a|questions?\s*(?:and|&)\s*answers?',row['title'],re.I):continue
        meta=extracted_metadata(row)
        if meta is None or meta['final_disposition']['status']!='accepted_sermon' or meta['guest_speaker_suspected'] is not False:continue
        selected.append({**row,'selection_sha256':hashlib.sha256((salt+row['youtube_video_id']).encode()).hexdigest(),
            'role':'primary' if len(selected)<3 else 'technical_reserve_only'})
        used.add(row['source_id'])
        if len(selected)==4:break
    if len(selected)!=4:raise ValueError('Insufficient technically eligible distinct fresh channels')
    return selected


def prepare_confirmation(base_dir,approve_result):
    """Optional later handoff after Codex reviews Brian's development results.

    Explicit result fingerprint is selection authority, not confirmation/run
    authority. No source text, discovery or reference census is inspected here.
    """
    packet,_=verify(base_dir)
    result=verify_result(base_dir,directory(base_dir)/packet['content_fingerprint']/'results-v4.json')
    if result['content_fingerprint']!=approve_result:raise ValueError('Use the reviewed development result fingerprint')
    if result['G2_G3_candidates']>20000:raise ValueError('Development exceeded candidate bounds')
    out=prep.directory(base_dir).parent/'fresh-discovery-readiness-v2'/'source-manifest-v2.json'
    if out.exists():
        prior=prep.gate.sealed(out)
        if prior['repair_input_fingerprint']!=packet['content_fingerprint'] or prior['development_result_fingerprint']!=result['content_fingerprint']:
            raise ValueError('Existing confirmation selection belongs to a different repair/result; preserve it')
        return prior
    old=prep.gate.sealed(prep.proposal.MANIFEST)
    excluded_sources=set(old['development_source_ids'])|{r['source_id'] for r in old['sources']}
    excluded_videos=set(old['development_video_ids'])|{r['video_id'] for r in old['sources']}
    paths=prep.proposal.build_paths(base_dir)
    query=old['selection_sql']
    with sqlite3.connect(paths.database.as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;rows=[dict(r) for r in db.execute(query)]
    for row in rows:row['video_id']=row.pop('id')
    def metadata(row):
        # Check file availability and only extract technical disposition metadata.
        if any(not Path(row[k]).is_file() for k in ('raw_text_path','proposed_json_path','proposed_text_path')):return None
        try:
            value=json.loads(Path(row['proposed_json_path']).read_text())
            return dict(final_disposition=value['final_disposition'],guest_speaker_suspected=value['guest_speaker_suspected'])
        except (OSError,ValueError,KeyError):return None
    selected=select_confirmation_rows(rows,metadata,excluded_sources,excluded_videos)
    for row in selected:row['file_hashes']={k:prep.proposal.a1.file_hash(Path(row[k])) for k in ('raw_text_path','proposed_json_path','proposed_text_path')}
    manifest=prep.seal(dict(version='fresh-discovery-source-manifest-v2',selection_salt='fresh-discovery-readiness-v2:',
        prepared_at_utc=datetime.now(timezone.utc).isoformat(),repair_input_fingerprint=packet['content_fingerprint'],development_result_fingerprint=result['content_fingerprint'],
        selection_sql=query,excluded_source_ids=sorted(excluded_sources),excluded_video_ids=sorted(excluded_videos),sources=selected,
        discovery_executed=False,references_constructed=False,provider_calls_authorized=False,confirmation_execution_authorized=False,
        selection_note='Metadata-only salted hash order, distinct channels, same duration/disposition/title/file rules; all old primary/reserve and development channels excluded. No opportunity-based selection or swapping. Technical duplicate/boundary validation pending before confirmation freeze.'))
    # A sealed selection is reused, never refreshed because outcomes disappoint.
    prep.save_new(out,manifest)
    return manifest
