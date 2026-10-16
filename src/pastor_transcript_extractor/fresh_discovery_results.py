"""Match sealed source-only inventories to frozen source-reviewed references.

No discovery rerun, reference injection, provider client, model or ranker tuning.
Containment gives an explicit upper bound until original-target/envelope audit.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from pastor_transcript_extractor import fresh_discovery_preparation as prep
from pastor_transcript_extractor import fresh_evidence_adapter as adapter

HERE=prep.HERE
REFERENCES=HERE/'references-v1.1.json'
REVIEW=HERE/'preparation-review-v1.json'


def verify_bound_files(bindings):
    """Verify review-bound bytes as well as each document's internal seal."""
    values={}
    for name,info in bindings.items():
        path=Path(info['path'])
        if prep.proposal.a1.file_hash(path)!=info['sha256']:
            raise ValueError('Reviewed preparation artifact changed: '+name)
        values[name]=prep.gate.sealed(path)
    return values


def verify_preparation(base_dir=None):
    """Read-only handoff: no discovery, reference revision, model or replay."""
    prep.authorization(base_dir)
    review=prep.gate.sealed(REVIEW)
    if review['status']!='RECOMMENDATION_PENDING_BRIAN' or review['provider_execution_authorized'] is not False:
        raise ValueError('Unknown fresh preparation review authority')
    values=verify_bound_files(review['artifacts'])
    root=prep.directory(base_dir).resolve()
    for name in ('inventory','freeze','runtime_references','semantic_input','matches'):
        if not Path(review['artifacts'][name]['path']).resolve().is_relative_to(root):
            raise ValueError('Foreign preparation runtime directory')
    inventory=values['inventory'];refs=values['references'];sem=values['semantic_input'];matches=values['matches']
    census_validate(refs,inventory)
    if (values['runtime_references']!=refs
            or values['freeze']['inventory_fingerprint']!=inventory['content_fingerprint']
            or matches['reference_fingerprint']!=refs['content_fingerprint']
            or matches['inventory_fingerprint']!=inventory['content_fingerprint']
            or matches['semantic_input_fingerprint']!=sem['content_fingerprint']
            or sem['budget']['authorized_attempts']!=0
            or sem['budget']['authorized_cost_usd']!='0'
            or matches['provider_requests']!=0):
        raise ValueError('Preparation identity or zero-provider authority changed')
    adapter.validate_packet(sem)
    if (matches['statistics']!=review['statistics'] or matches['budget']!=review['budget']
            or matches['verdict']!=review['recommendation']):
        raise ValueError('Review differs from frozen preparation results')
    return review


def contains(a,b):
    return a['start']<=b['start']<b['end']<=a['end']


def route(row):
    return 'G1_assurance' if row['capability']=='G1' else 'G2_explanation' if row['capability']=='G2' else 'G3_reported' if row['source_namespace']=='reported_local' else 'G3_current'


def geometric_match(reference,entry):
    c=entry['candidate'];cap=c['capability']
    if cap!=reference['capability']:return False
    alternatives=reference['equivalent_role_occurrences']
    if cap=='G1':
        return (any(contains(c['claim'],s) for s in alternatives['claim'])
                and all(contains(c['target'],s) for s in reference.get('required_target_framing',[])))
    return all(any(contains(c['endpoints'][k],s) for s in alternatives[k]) for k in reference['roles'])


def coverage(reference,entry):
    c=entry['candidate'];env=entry['automatic_envelope']
    if c['capability']=='G1':
        lo=c['target']['start']-len(c['leading_context']);hi=c['target']['end']+len(c['trailing_context'])
        env=dict(start=lo,end=hi)
    if env.get('status')=='deferred':return False
    return all(contains(env,s) for s in reference['required_source_evidence_spans'])


def source_gate(hits,total,minimum=5,threshold=.80):
    if total<minimum:return 'DIAGNOSTIC_ONLY'
    return 'PASS' if hits/total>=threshold else 'FAIL'


def census_validate(refs,inventory):
    if (refs['inventory_fingerprint']!=inventory['content_fingerprint']
            or refs['matching_seen_at_census_freeze'] is not False
            or refs['refinements_before_any_matching'] is not True):
        raise ValueError('References are not bound to pre-census discovery freeze')
    ids=[r['reference_id'] for r in refs['rows']]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate opportunity references')
    for vid,info in inventory['source_files'].items():
        s=prep.gate.sealed(Path(info['path']));t=s['text'];lo,hi=(s['main_span'][k] for k in ('start','end'))
        census=prep.gate.sealed(Path(refs['census_files'][vid]['path']))
        if prep.proposal.a1.file_hash(Path(refs['census_files'][vid]['path']))!=refs['census_files'][vid]['sha256']:
            raise ValueError('Independent source census changed')
        cursor=lo
        for page in census['coverage_pages']:
            if (page['start']!=cursor or not cursor<page['end']<=hi or page['read_in_full'] is not True
                    or hashlib.sha256(t[cursor:page['end']].encode()).hexdigest()!=page['text_sha256']):
                raise ValueError('Incomplete source-review coverage')
            cursor=page['end']
        if cursor!=hi:raise ValueError('Unreviewed main source suffix')
        for row in [r for r in refs['rows'] if r['video_id']==int(vid)]:
            spans=list(row['roles'].values())+row['required_source_evidence_spans']+row.get('required_target_framing',[])
            spans += [s for values in row['equivalent_role_occurrences'].values() for s in values]
            for span in spans:
                if not 0<=span['start']<span['end']<=len(t) or t[span['start']:span['end']]!=span['text']:
                    raise ValueError('Reference role/condition/provenance is not exact source evidence')


def packet(inventory,root):
    cases=[];requests=[]
    source_map={int(vid):prep.gate.sealed(Path(info['path'])) for vid,info in inventory['source_files'].items()}
    entries={e['candidate']['candidate_id']:e for col in inventory['inventories'] for e in col['entries']}
    for queued in inventory['queue']:
        if queued['status']!='prepared':continue
        c,rs=adapter.materialize_case(source_map[queued['video_id']],entries[queued['candidate_id']])
        cases.append(c);requests.extend(rs)
    sizes=[];question_sizes=[]
    for r in requests:
        wire=dict(model=r['model'],state=r['state'],questions={k:dict(type='choice',**q) for k,q in r['questions'].items()})
        sizes.append(len(prep.gate.canonical(wire).encode()))
        question_sizes.extend(len(prep.gate.canonical(dict(state=r['state'],question=q)).encode()) for q in wire['questions'].values())
    if max(sizes,default=0)>60000 or max(question_sizes,default=0)>30000:
        raise ValueError('Prepared UTF-8 byte guard exceeded; no truncation or silent repacking')
    plan=prep.gate.sealed(prep.proposal.PLAN)
    modules=[prep,adapter,__import__('pastor_transcript_extractor.caption_normalization',fromlist=['_']),
             __import__('pastor_transcript_extractor.sermon_g1_feasibility_revision',fromlist=['_']),
             __import__('pastor_transcript_extractor.sermon_g2_feasibility_revision',fromlist=['_'])]
    pins={**plan['pins'],**inventory['code_hashes'],**{str(Path(m.__file__).relative_to(prep.proposal.ROOT)):prep.proposal.a1.file_hash(Path(m.__file__)) for m in modules}}
    tokens=len(requests)*64000;cost=Decimal(tokens)*Decimal('0.000000042')
    value=prep.seal(dict(version=adapter.VERSION,model=prep.MODEL,runtime_root=str(root),
        inventory_fingerprint=inventory['content_fingerprint'],inventory_sha256=prep.proposal.a1.file_hash(root/'natural-inventory-v1.json'),
        source_files=inventory['source_files'],code_hashes=pins,cases=cases,requests=requests,provider_calls_authorized=False,
        budget=dict(maximum_attempts=len(requests),reserved_input_tokens_per_attempt=64000,maximum_input_tokens=tokens,
            maximum_model_list_price_usd=str(cost),input_usd_per_million='0.042',output_usd_per_million='0',automatic_retries=0,
            model='jev-1.13.0',long_context=False,per_request_context_limit=64000,per_question_context_limit=32000,
            pricing_checked_on='2026-10-15',price_source='https://docs.typesafe.ai/models',
            wire_bytes_min=min(sizes,default=0),wire_bytes_max=max(sizes,default=0),wire_bytes_total=sum(sizes),
            per_question_state_bytes_max=max(question_sizes,default=0),
            note='64k reservation is the documented request-context ceiling, not an estimate of actual usage. Byte checks are engineering guards, not a provider tokenizer. Outputs are free at the checked list price. Exact future charged usage remains unknown.',
            authorized_attempts=0,authorized_cost_usd='0',actual_usage=None)))
    adapter.validate_packet(value)
    return value


def prepare(base_dir=None):
    plan,manifest,auth=prep.authorization(base_dir);root=prep.directory(base_dir)
    inventory=prep.gate.sealed(root/'natural-inventory-v1.json');freeze=prep.gate.sealed(root/'freeze-v1.json')
    if (freeze['inventory_fingerprint']!=inventory['content_fingerprint']
            or freeze['inventory_sha256']!=prep.proposal.a1.file_hash(root/'natural-inventory-v1.json')
            or freeze['references_existed_at_freeze'] is not False):raise ValueError('Natural inventory seal changed')
    for name,digest in inventory['code_hashes'].items():
        if prep.proposal.a1.file_hash(prep.proposal.ROOT/name)!=digest:raise ValueError('Frozen discovery code changed')
    refs=prep.gate.sealed(REFERENCES);census_validate(refs,inventory)
    if datetime.fromisoformat(freeze['frozen_at_utc'])>=datetime.fromisoformat(refs['frozen_at_utc']):
        raise ValueError('Census predates natural inventory freeze')
    # A runtime copy closes regeneration as well as pinning the authored census.
    prep.save_new(root/'references-v1.json',refs)
    rows=[]
    for r in refs['rows']:
        collection=next(c for c in inventory['inventories'] if c['video_id']==r['video_id'])
        entries=[e for e in collection['entries'] if e['candidate']['capability']==r['capability']]
        hits=[e for e in entries if geometric_match(r,e)]
        strict=[]
        for e in hits:
            c=e['candidate'];actual=c['target'] if c['capability']=='G1' else c['endpoints']
            if c['capability']=='G1':ok=contains(c['claim'],r['roles']['claim']) and all(contains(c['target'],s) for s in r.get('required_target_framing',[]))
            else:ok=all(contains(actual[k],s) for k,s in r['roles'].items())
            if ok:strict.append(c['candidate_id'])
        enough=[e for e in hits if coverage(r,e)]
        if hits:failure=None if enough else 'required_provenance_or_qualification_outside_automatic_envelope'
        elif r['capability']=='G1':failure='G1_claim_nomination_or_required_target_framing_miss'
        elif r['capability']=='G2':
            left=any(any(contains(e['candidate']['endpoints']['left'],s) for s in r['equivalent_role_occurrences']['left']) for e in entries)
            failure='G2_pair_not_retained' if left else 'G2_Bible_anchor_nomination_or_endpoint_miss'
        else:
            actual=[e['candidate']['endpoints']['utterance'] for e in entries]
            overlap=any(s['start']<r['roles']['utterance']['end'] and r['roles']['utterance']['start']<s['end'] for s in actual)
            failure='G3_complete_act_target_not_materialized' if overlap else 'G3_address_surface_nomination_miss'
        # These are source-aligned geometry/evidence-coverage upper bounds, never
        # raw semantics or authority to admit. Manual target audit is separate.
        rows.append(dict(reference_id=r['reference_id'],video_id=r['video_id'],route=route(r),classification=r['classification'],
            role_containment_hits=[e['candidate']['candidate_id'] for e in hits],canonical_role_hits=strict,
            required_evidence_coverage_hits=[e['candidate']['candidate_id'] for e in enough],failure=failure))
    stats={}
    minima=plan['proposed_criteria']['min_reference_opportunities']
    for rt in ('G1_assurance','G2_explanation','G3_current','G3_reported'):
        rr=[r for r in rows if r['route']==rt and r['classification']=='definite_compatible_opportunity']
        n=len(rr);h=sum(bool(r['role_containment_hits']) for r in rr);en=sum(bool(r['required_evidence_coverage_hits']) for r in rr)
        small=n<minima[rt]
        stats[rt]=dict(opportunities=n,role_containment_upper_bound_hits=h,role_containment_recall_upper_bound=h/n if n else None,
            automatic_required_evidence_upper_bound_hits=en,automatic_evidence_recall_upper_bound=en/n if n else None,
            opportunity_minimum=minima[rt],decision='HOLD' if small else 'FAIL' if h/n<.8 or en/n<.8 else 'PENDING_TARGET_ENVELOPE_AUDIT',
            per_source={str(vid):dict(opportunities=len(v:=[r for r in rr if r['video_id']==vid]),hits=sum(bool(r['role_containment_hits']) for r in v),
                recall_upper_bound=sum(bool(r['role_containment_hits']) for r in v)/len(v) if v else None,
                gate=source_gate(sum(bool(r['role_containment_hits']) for r in v),len(v))) for vid in (1565,1450,1618)})
    sem=packet(inventory,root);prep.save_new(root/'semantic-input-v1.json',sem)
    report=prep.seal(dict(version='fresh-provider-free-match-results-v1',reference_fingerprint=refs['content_fingerprint'],
        reference_file_sha256=prep.proposal.a1.file_hash(REFERENCES),inventory_fingerprint=inventory['content_fingerprint'],
        semantic_input_fingerprint=sem['content_fingerprint'],provider_requests=0,statistics=stats,records=rows,
        candidate_counts=freeze['candidate_counts'],queue_units=len(sem['cases']),requests=len(sem['requests']),budget=sem['budget'],
        verdict='FAIL' if any(v['decision']=='FAIL' for v in stats.values()) else 'HOLD',
        interpretation='Containment/evidence upper bounds only until source-target audit. A failed upper bound proves the proposed readiness target cannot be met by this frozen inventory; no paid semantic run can recover unsupplied evidence.',
        manual_rescue_discovery_credit=0,semantic_measurements=None,admitted_items=None,
        review_burden=dict(human_active_review_minutes=None,candidate_review_median_minutes=None,unresolved_deferral_rate=None,
            note='No provider outputs exist. Source-census elapsed intervals are recorded separately; active human annotation/claim-witness throughput not measured.')))
    prep.save_new(root/'match-results-v1.json',report)
    return report
