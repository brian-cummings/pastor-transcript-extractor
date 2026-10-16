"""Fresh V2 preparation with frozen Collector V4.1, never provider execution."""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import json
import sqlite3

from pastor_transcript_extractor import collector_recall_repair_v4_1 as repair

prep=repair.prep
HERE=prep.proposal.ROOT/'docs/review-proposals/fresh-discovery-readiness-v2'
MANIFEST=HERE/'source-manifest-v2.json'
AUTH=HERE/'authorization-v2.json'
VALIDATION=HERE/'source-validation-v2.json'
REFERENCES=HERE/'references-v2.json'


def directory(base_dir=None):return prep.directory(base_dir).parent/'fresh-discovery-readiness-v2'


def verify(base_dir=None):
    packet,_=repair.verify(base_dir)
    manifest=prep.gate.sealed(MANIFEST);auth=prep.gate.sealed(AUTH)
    accepted=prep.gate.sealed(repair.HERE/'development-acceptance-v4.1.json')
    if (auth['status']!='AUTHORIZED' or auth['provider_calls_authorized'] is not False
            or auth['tuning_authorized'] is not False or auth['collector_frozen'] is not True
            or auth['repair_input_fingerprint']!=packet['content_fingerprint']
            or auth['source_manifest_sha256']!=prep.proposal.a1.file_hash(MANIFEST)
            or auth['development_acceptance_sha256']!=prep.proposal.a1.file_hash(repair.HERE/'development-acceptance-v4.1.json')
            or accepted['status']!='ACCEPTED_DEVELOPMENT_ONLY' or accepted['frozen_code_hashes']!=packet['code_hashes']
            or accepted['result_fingerprint']!=manifest['development_result_fingerprint']
            or manifest['repair_input_fingerprint']!=packet['content_fingerprint']
            or auth['criteria']!=dict(aggregate_recall=.80,aggregate_sufficient_envelope_recall=.80,
                per_source_recall=.80,per_source_minimum=5,small_cells='diagnostic',
                aggregate_floors=dict(G1_assurance=5,G2_explanation=10,G3_current=5,G3_reported=3),
                manual_envelope_repair_max=.20,unresolved_review_deferral_max=.20,
                median_active_candidate_review_minutes_max=5,active_review_budget_minutes=480)
            or auth['semantic_queue']!=dict(G1=10,G2=15,G3=15)
            or auth['bounds']!=dict(G2_G3_per_source=12000,G2_G3_total=20000,G1_per_source=200,
                characters_per_source=150000,characters_total=300000,semantic_units_per_source=40,
                semantic_units_total=120,semantic_requests_max=240,retries=0)):
        raise ValueError('Fresh V2 authorization/frozen collector changed')
    paths=prep.proposal.build_paths(base_dir)
    with sqlite3.connect(paths.database.as_uri()+'?mode=ro',uri=True) as db:
        for row in manifest['sources']:
            if row['source_id'] in manifest['excluded_source_ids'] or row['video_id'] in manifest['excluded_video_ids']:
                raise ValueError('Exposed source cannot enter fresh confirmation')
            identity=db.execute('select source_id,youtube_video_id,title from videos where id=?',(row['video_id'],)).fetchone()
            if identity!=(row['source_id'],row['youtube_video_id'],row['title']):raise ValueError('Fresh source identity changed')
            if db.execute('select count(*) from sermon_analysis_runs where video_id=?',(row['video_id'],)).fetchone()[0]:
                raise ValueError('Selected source has semantic analysis exposure')
            for key,digest in row['file_hashes'].items():
                if prep.proposal.a1.file_hash(Path(row[key]))!=digest:raise ValueError('Selected source bytes changed')
    return manifest,auth


def snapshot(row):
    metadata=json.loads(Path(row['proposed_json_path']).read_text())
    enriched={**row,'existing_window_seconds':{k:metadata['sermon_window'][k] for k in ('start_seconds','end_seconds')}}
    return prep.source_snapshot(enriched)


def preview(base_dir=None,include_reserve=False):
    manifest,_=verify(base_dir);root=directory(base_dir)
    selected=[r for r in manifest['sources'] if include_reserve or r['role']=='primary']
    for row in selected:
        source=snapshot(row)
        if len(source['text'])>150000:raise ValueError('Source character bound exceeded; no truncation')
        prep.save_new(root/'sources'/f"{row['video_id']}.json",source)
    return [r['video_id'] for r in selected]


def validated_sources(base_dir=None):
    manifest,_=verify(base_dir);v=prep.gate.sealed(VALIDATION);root=directory(base_dir)
    if v['manifest_fingerprint']!=manifest['content_fingerprint'] or v['all_three_usable'] is not True:
        raise ValueError('Technical source validation required')
    primary=[r['video_id'] for r in manifest['sources'] if r['role']=='primary'];reserve=manifest['sources'][-1]['video_id']
    ids=v['active_video_ids'];replaced=set(primary)-set(ids)
    if len(ids)!=3 or len(set(ids))!=3 or len(replaced)>1 or not set(ids)<=set(primary+[reserve]):
        raise ValueError('Invalid primary/technical reserve substitution')
    if replaced:
        if set(ids)-set(primary)!={reserve} or {r['video_id'] for r in v['technical_exclusions']}!=replaced:
            raise ValueError('Missing explicit technical exclusion')
        if any(r['reason'] not in {'non_sermon','unavailable','corrupt','duplicate','irrecoverable_extraction'} for r in v['technical_exclusions']):
            raise ValueError('Opportunity/results-based replacement prohibited')
    sources=[]
    for row in v['rows']:
        if row['video_id'] not in ids:continue
        path=root/'sources'/f"{row['video_id']}.json"
        if prep.proposal.a1.file_hash(path)!=row['preview_sha256']:raise ValueError('Boundary-reviewed preview changed')
        source=prep.gate.sealed(path)
        span=row['main_span']
        if not 0<=span['start']<span['end']<=len(source['text']):raise ValueError('Invalid reviewed main span')
        sources.append(prep.seal({**source,'main_span':span,'source_validation_fingerprint':v['content_fingerprint']}))
    if {s['video_id'] for s in sources}!=set(ids):raise ValueError('Missing active source validation')
    sources.sort(key=lambda s:ids.index(s['video_id']))
    if sum(len(s['text']) for s in sources)>300000:raise ValueError('Aggregate character ceiling exceeded')
    return sources,v


def freeze(base_dir=None):
    manifest,auth=verify(base_dir);root=directory(base_dir)
    if REFERENCES.exists() or (root/'references-v2.json').exists():raise ValueError('Never regenerate confirmation discovery after census')
    sources,validation=validated_sources(base_dir)
    sizes=[repair.size_proof(s) for s in sources];repair.validate_size_proofs(sizes)
    inventories=[];queue=[];source_files={};total=0
    for source in sources:
        vid=source['video_id'];path=root/'sources'/f'{vid}.reviewed.json';prep.save_new(path,source)
        source_files[str(vid)]=dict(path=str(path),sha256=prep.proposal.a1.file_hash(path))
        collection=repair.collector.discover(source);total+=len(collection['candidates'])
        if total>20000:raise ValueError('Aggregate G2/G3 ceiling exceeded; no truncation')
        entries=[]
        for candidate in collection['G1_candidates']+collection['candidates']:
            envelope=(dict(status='prepared_not_attested',target=candidate['target'],leading_context=candidate['leading_context'],trailing_context=candidate['trailing_context'])
                if candidate['capability']=='G1' else prep.automatic_envelope(source,candidate))
            entries.append(dict(candidate=candidate,automatic_envelope=envelope))
        inventories.append(dict(video_id=vid,entries=entries,deferrals=collection['deferred'],search_diagnostics=collection['search_diagnostics'],budget_proof=collection['budget_proof']))
        for cap,quota in auth['semantic_queue'].items():
            for entry in [e for e in entries if e['candidate']['capability']==cap][:quota]:
                c=entry['candidate'];env=entry['automatic_envelope']
                queue.append(dict(video_id=vid,capability=cap,candidate_id=c['candidate_id'],status='prepared' if env['status']=='prepared_not_attested' else 'deferred',
                    shapes=prep.shapes(source,c,env) if env['status']=='prepared_not_attested' else [],deferral=None if env['status']=='prepared_not_attested' else env))
    # Legacy basename is required by the existing typed fresh adapter, inside the
    # separate V2 directory; its document version and identity are explicitly V2.
    inventory=prep.seal(dict(version='fresh-natural-inventory-v2',authorization_fingerprint=auth['content_fingerprint'],
        manifest_fingerprint=manifest['content_fingerprint'],source_validation_fingerprint=validation['content_fingerprint'],
        source_files=source_files,inventories=inventories,queue=queue,collector_policy=repair.collector.POLICY,
        envelope_policy=prep.ENVELOPE_POLICY,code_hashes={**prep.gate.sealed(repair.INPUT)['code_hashes'],
            str(Path(__file__).relative_to(prep.proposal.ROOT)):prep.proposal.a1.file_hash(Path(__file__))},references_received=False,provider_requests=0))
    prep.save_new(root/'natural-inventory-v1.json',inventory)
    existing=root/'freeze-v2.json'
    if not existing.exists():
        prep.save_new(existing,prep.seal(dict(version='fresh-inventory-freeze-v2',frozen_at_utc=datetime.now(timezone.utc).isoformat(),
            inventory_fingerprint=inventory['content_fingerprint'],inventory_sha256=prep.proposal.a1.file_hash(root/'natural-inventory-v1.json'),
            source_files=source_files,references_existed_at_freeze=False,provider_requests=0,
            candidate_counts={str(i['video_id']):dict(Counter(e['candidate']['capability'] for e in i['entries'])) for i in inventories},
            size_preflight=sizes,queue_units=len(queue),prepared_requests=sum(len(q['shapes']) for q in queue))))
    return inventory['content_fingerprint']
