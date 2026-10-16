"""Provider-free, separately versioned development repair; Brian runs the dataset.

Natural inventories are sealed before frozen references are opened for matching.
No admission, semantic inference, authored rescue or confirmation execution.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import json

from pastor_transcript_extractor import evidence_supply_source_unit_repair as collector
from pastor_transcript_extractor import fresh_discovery_confirmation_results as baseline
from pastor_transcript_extractor import collector_recall_repair_v4_1 as comparison

prep=baseline.prep
HERE=prep.proposal.ROOT/'docs/review-proposals/source-unit-repair-v1'
INPUT=HERE/'input-v1.json'
ACCEPTANCE=baseline.confirmation.HERE/'acceptance-decision-v2.json'


def directory(base_dir=None):
    return baseline.confirmation.directory(base_dir).parent/'source-unit-repair-v1'


def verify(base_dir=None):
    review=baseline.verify_review(base_dir)
    accepted=prep.gate.sealed(ACCEPTANCE);packet=prep.gate.sealed(INPUT)
    if (accepted['status']!='ACCEPTED' or accepted['decision']!='scoped_FAIL'
            or accepted['G1_assurance']!='HOLD' or accepted['provider_calls_authorized'] is not False
            or accepted['review_fingerprint']!=review['content_fingerprint']
            or accepted['review_sha256']!=prep.proposal.a1.file_hash(baseline.REVIEW)
            or packet['acceptance_sha256']!=prep.proposal.a1.file_hash(ACCEPTANCE)
            or packet['baseline_review_fingerprint']!=review['content_fingerprint']
            or packet['reference_sha256']!=review['artifacts']['references']['sha256']
            or packet['semantic_admission_changes_authorized'] is not False
            or packet['policy']!=collector.POLICY
            or packet['development_video_ids']!=[2325,610,2298]
            or packet['provider_calls_authorized'] is not False
            or packet['confirmation_execution_authorized'] is not False):
        raise ValueError('Source-unit repair authority changed')
    for name,digest in packet['code_hashes'].items():
        path=(prep.proposal.ROOT/name).resolve()
        if not path.is_relative_to(prep.proposal.ROOT.resolve()) or prep.proposal.a1.file_hash(path)!=digest:
            raise ValueError('Source-unit repair implementation/test pin changed')
    return packet,review


def source_inputs(review):
    inventory=prep.gate.sealed(Path(review['artifacts']['inventory']['path']))
    sources={}
    for vid,info in inventory['source_files'].items():
        path=Path(info['path'])
        if prep.proposal.a1.file_hash(path)!=info['sha256']:raise ValueError('Canonical source changed')
        sources[int(vid)]=prep.gate.sealed(path)
    return inventory,sources


def size_preflight(review):
    """Unit formation only; no discovery, reference matching or model calls."""
    _,sources=source_inputs(review);rows=[]
    for vid,source in sources.items():
        nodes=collector.source_sentences(source);n=len(nodes)
        rows.append(dict(video_id=vid,source_chars=len(source['text']),unit_nodes=n,
            unit_chars=baseline.distribution([len(s['text']) for s in nodes]),
            G2_G3_upper_bound=10*n,
            G1_nominations=len({j for i,node in enumerate(nodes) if collector.ASSURANCE.search(node['text'])
                for j in range(max(0,i-1),min(n,i+2))})))
    if any(r['G1_nominations']>collector.POLICY['G1_source_ceiling'] for r in rows):
        raise ValueError('G1 nomination ceiling exceeded in structural preflight; no truncation')
    comparison.validate_size_proofs(rows)
    return rows


def cohort_report(review,rows):
    index={r['reference_id']:r for r in rows};groups={}
    for category in sorted({m['source_review_classification'] for m in review['misses']}):
        members=[m for m in review['misses'] if m['source_review_classification']==category]
        ledger=[]
        for m in members:
            r=index[m['reference_id']]
            ledger.append(dict(reference_id=m['reference_id'],video_id=m['video_id'],frozen_miss_classification=category,
                role_containment_hits=r['role_containment_hits'],required_evidence_coverage_hits=r['required_evidence_coverage_hits'],
                source_roles=m['source_roles'],manual_rescue_credit=0))
        groups[category]=dict(frozen_misses=len(members),
            natural_complete_role_hits=sum(bool(r['role_containment_hits']) for r in ledger),
            natural_required_evidence_hits=sum(bool(r['required_evidence_coverage_hits']) for r in ledger),ledger=ledger)
    return groups


def validate_natural(collection):
    for e in collection['entries']:
        c=e['candidate'];env=e['automatic_envelope']
        if c['pastor_credit'] or c['semantic_truth'] is not None:raise ValueError('Discovery cannot certify evidence')
        if c['capability']!='G1':
            if len(c['relation_frame']['text'])>6000:raise ValueError('Frame bound violated')
            if env['status']=='prepared_not_attested' and len(env['text'])>6000:raise ValueError('Envelope bound violated')


def run_development(base_dir=None,approve_input=None):
    packet,review=verify(base_dir)
    if approve_input!=packet['content_fingerprint']:raise ValueError('Use exact prepared source-unit repair fingerprint')
    out=directory(base_dir)/packet['content_fingerprint'];result_path=out/'results-v1.json'
    if result_path.exists():
        result=prep.gate.sealed(result_path)
        if (result['repair_input_fingerprint']!=packet['content_fingerprint'] or result['provider_requests']!=0
                or prep.proposal.a1.file_hash(out/'natural-inventory-v1.json')!=result['inventory_sha256']):
            raise ValueError('Existing development result/inventory changed')
        return result
    sizes=size_preflight(review);old,sources=source_inputs(review);inventories=[];total=0
    for vid in packet['development_video_ids']:
        source=sources[vid];col=collector.discover(source);total+=len(col['candidates'])
        if total>collector.POLICY['total_candidate_ceiling']:raise ValueError('Total candidate ceiling exceeded; no truncation')
        entries=[]
        for c in col['G1_candidates']+col['candidates']:
            env=(dict(status='prepared_not_attested',target=c['target'],leading_context=c['leading_context'],trailing_context=c['trailing_context'])
                if c['capability']=='G1' else collector.automatic_envelope(source,c))
            entries.append(dict(candidate=c,automatic_envelope=env))
        new=dict(video_id=vid,entries=entries,deferrals=col['deferred'],budget_proof=col['budget_proof'],
            search_diagnostics=col['search_diagnostics'],unit_diagnostics=col['unit_diagnostics'])
        validate_natural(new)
        # Unaffected sources must preserve all old role geometries. This is a
        # mechanical parity assertion, not a changed reference definition.
        if col['unit_diagnostics']['subdivided_parents']==0:
            previous=next(c for c in old['inventories'] if c['video_id']==vid)
            if {comparison.entry_key(e) for e in entries}!={comparison.entry_key(e) for e in previous['entries']}:
                raise ValueError('Ordinary punctuation path changed; preserve baseline')
        inventories.append(new)
    natural=prep.seal(dict(version='source-unit-repair-natural-v1',repair_input_fingerprint=packet['content_fingerprint'],
        source_files=old['source_files'],inventories=inventories,provider_requests=0,confirmation_evidence=False))
    prep.save_new(out/'natural-inventory-v1.json',natural)
    # References cannot influence discovery or source-only envelope materialization.
    refs=prep.gate.sealed(baseline.REFERENCES)
    before=prep.gate.sealed(Path(review['artifacts']['results']['path']))
    rows,matched=comparison.match_rows(refs,inventories)
    old_rows={r['reference_id']:r for r in before['records']}
    regressions=[r['reference_id'] for r in rows if old_rows[r['reference_id']]['role_containment_hits'] and not r['role_containment_hits']]
    evidence_regressions=[r['reference_id'] for r in rows if old_rows[r['reference_id']]['required_evidence_coverage_hits'] and not r['required_evidence_coverage_hits']]
    workload={str(c['video_id']):baseline.burden(c,sources[c['video_id']],matched,[x for x in refs['controls'] if x['video_id']==c['video_id']]) for c in inventories}
    counts={str(c['video_id']):dict(Counter(e['candidate']['capability'] for e in c['entries'])) for c in inventories}
    for vid,w in workload.items():
        w['baseline_counts']=before['workload'][vid]['counts']
        old_count=sum(w['baseline_counts'].values());new_count=sum(counts[vid].values())
        w['candidate_growth_ratio']=new_count/old_count if old_count else None
        w['candidate_count_delta']=new_count-old_count
    result=prep.seal(dict(version='source-unit-repair-development-v1',repair_input_fingerprint=packet['content_fingerprint'],
        baseline_result_fingerprint=before['content_fingerprint'],references_fingerprint=refs['content_fingerprint'],
        inventory_sha256=prep.proposal.a1.file_hash(out/'natural-inventory-v1.json'),
        verdict='DEVELOPMENT_DIAGNOSTIC_ONLY',G1_assurance='HOLD',cohorts=cohort_report(review,rows),
        regressions=regressions,required_evidence_regressions=evidence_regressions,records=rows,workload=workload,
        candidate_counts=counts,G2_G3_candidates=total,size_preflight=sizes,
        source_unit_diagnostics={str(c['video_id']):c['unit_diagnostics'] for c in inventories},
        provider_requests=0,manual_rescue_credit=0,semantic_measurements=None,admitted_items=None,
        safe_envelope_recall_certified=False,review_throughput=None,unit_economics=None,
        next_step='Codex reviews all 54 segmentation cases, separate four G2 misses, four frozen G3 questions, regressions and burden before selecting unseen confirmation sources. No automatic confirmation or inference.'))
    prep.save_new(result_path,result);(out/'results-v1.md').write_text(render(result)+'\n')
    return result


def render(result):
    lines=['# Source-unit repair V1 — development only','',
        'Fresh V2 remains accepted scoped FAIL / G1 HOLD. These are natural geometry and required-span upper bounds, not semantic or admission results.','',
        '| Frozen miss class | Cases | Natural role hits | Required-evidence hits |','|---|---:|---:|---:|']
    for name,c in result['cohorts'].items():lines.append(f"| {name} | {c['frozen_misses']} | {c['natural_complete_role_hits']} | {c['natural_required_evidence_hits']} |")
    lines+=['',f"G2/G3 candidates: {result['G2_G3_candidates']}. Regressions: {len(result['regressions'])} role / {len(result['required_evidence_regressions'])} evidence. Provider requests: 0.",
        '', 'JSON preserves each of the 62 original misses, all 94 reference match records, density/growth, frame/envelope distributions, deferrals, controls and source-unit diagnostics.',
        '', 'Units and overlapping target windows are retrieval hypotheses; complete utterance identity, source/recipient provenance and sufficiency remain unaudited. Mixed windows and unmatched candidates are not semantic positives or false positives. Review throughput, safe-envelope recall and economics remain unknown.',
        '',result['next_step']]
    return '\n'.join(lines)
