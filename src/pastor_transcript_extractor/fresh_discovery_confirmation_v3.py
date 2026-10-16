"""Unseen V3 preparation using the accepted, unchanged source-unit repair.

Metadata-only source selection precedes text inspection. Brian freezes the
source-only inventory before Codex constructs the independent opportunity census.
There is no provider client or semantic execution route in this module.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import hashlib

from pastor_transcript_extractor import source_unit_repair_audit as audit
from pastor_transcript_extractor import fresh_discovery_confirmation as previous

repair=audit.repair
prep=repair.prep
collector=repair.collector
HERE=prep.proposal.ROOT/'docs/review-proposals/fresh-discovery-readiness-v3'
AUTH=HERE/'authorization-v3.1.json'
ORIGINAL_AUTH=HERE/'authorization-v3.json'
MANIFEST=HERE/'source-manifest-v3.1.json'
ORIGINAL_MANIFEST=HERE/'source-manifest-v3.json'
TECHNICAL_REVIEW=HERE/'technical-selection-review-v3.json'
VALIDATION=HERE/'source-validation-v3.json'
REFERENCES=HERE/'references-v3.json'
ACCEPTANCE=audit.HERE/'acceptance-v1.json'
SALT='fresh-discovery-readiness-v3:'


def directory(base_dir=None):
    return previous.directory(base_dir).parent/'fresh-discovery-readiness-v3'


def authority(base_dir=None):
    source_audit=audit.verify_review(base_dir);accepted=prep.gate.sealed(ACCEPTANCE);auth=prep.gate.sealed(AUTH)
    packet,_=repair.verify(base_dir);prior_auth=prep.gate.sealed(previous.AUTH)
    if (accepted['status']!='ACCEPTED_FROZEN_DEVELOPMENT_ONLY'
            or accepted['audit_fingerprint']!=source_audit['content_fingerprint']
            or accepted['audit_sha256']!=prep.proposal.a1.file_hash(audit.REVIEW)
            or accepted['repair_input_fingerprint']!=packet['content_fingerprint']
            or accepted['frozen_code_hashes']!=packet['code_hashes']
            or auth['acceptance_sha256']!=prep.proposal.a1.file_hash(ACCEPTANCE)
            or auth['status']!='AUTHORIZED_PROVIDER_FREE_PREPARATION'
            or auth['collector_policy']!=collector.POLICY
            or auth['original_authorization_sha256']!=prep.proposal.a1.file_hash(ORIGINAL_AUTH)
            or auth['technical_review_sha256']!=prep.proposal.a1.file_hash(TECHNICAL_REVIEW)
            or auth['technical_reserves_max']!=2
            or auth['criteria']!=prior_auth['criteria'] or auth['bounds']!=prior_auth['bounds']
            or auth['semantic_queue']!=prior_auth['semantic_queue']
            or auth['target_envelope_review_required'] is not True
            or auth['target_review_protocol_sha256']!=prep.proposal.a1.file_hash(HERE/'target-review-protocol-v3.json')
            or auth['provider_calls_authorized'] is not False
            or auth['tuning_authorized'] is not False
            or auth['collection_projection_authorized'] is not False):
        raise ValueError('V3 preparation authority or frozen configuration changed')
    for name,digest in auth['code_hashes'].items():
        path=(prep.proposal.ROOT/name).resolve()
        if not path.is_relative_to(prep.proposal.ROOT.resolve()) or prep.proposal.a1.file_hash(path)!=digest:
            raise ValueError('V3 preparation implementation/test pin changed')
    return auth


def exposure_sets():
    """Include every old development/primary/reserve channel, even exclusions."""
    old=prep.gate.sealed(previous.MANIFEST)
    return (set(old['excluded_source_ids'])|{s['source_id'] for s in old['sources']},
        set(old['excluded_video_ids'])|{s['video_id'] for s in old['sources']})


def select_sources(base_dir=None):
    auth=authority(base_dir)
    if MANIFEST.exists():
        return verify(base_dir)[0]
    prior=prep.gate.sealed(previous.MANIFEST);excluded_sources,excluded_videos=exposure_sets()
    paths=prep.proposal.build_paths(base_dir)
    with sqlite3.connect(paths.database.as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;rows=[dict(r) for r in db.execute(prior['selection_sql'])]
    for row in rows:row['video_id']=row.pop('id')
    def metadata(row):
        if any(not Path(row[k]).is_file() for k in ('raw_text_path','proposed_json_path','proposed_text_path')):return None
        try:
            value=json.loads(Path(row['proposed_json_path']).read_text())
            return dict(final_disposition=value['final_disposition'],guest_speaker_suspected=value['guest_speaker_suspected'])
        except (OSError,ValueError,KeyError):return None
    initial=prep.gate.sealed(ORIGINAL_MANIFEST);technical=prep.gate.sealed(TECHNICAL_REVIEW)
    if (technical['initial_manifest_fingerprint']!=initial['content_fingerprint']
            or technical['initial_manifest_sha256']!=prep.proposal.a1.file_hash(ORIGINAL_MANIFEST)
            or technical['collector_executed'] is not False or technical['opportunity_census_started'] is not False
            or len(technical['exclusions'])!=2 or any(r['reason']!='non_sermon' for r in technical['exclusions'])):
        raise ValueError('Technical continuation must precede discovery/census and preserve original selection')
    selected=list(initial['sources'])
    extra=previous.repair.select_confirmation_rows(rows,metadata,
        excluded_sources|{s['source_id'] for s in selected},excluded_videos|{s['video_id'] for s in selected},salt=SALT)[0]
    extra['role']='technical_reserve_only';selected.append(extra)
    for row in selected:
        row['file_hashes']={k:prep.proposal.a1.file_hash(Path(row[k])) for k in ('raw_text_path','proposed_json_path','proposed_text_path')}
    value=prep.seal(dict(version='fresh-discovery-source-manifest-v3',authorization_fingerprint=auth['content_fingerprint'],
        selected_at_utc=datetime.now(timezone.utc).isoformat(),original_manifest_sha256=prep.proposal.a1.file_hash(ORIGINAL_MANIFEST),
        technical_review_sha256=prep.proposal.a1.file_hash(TECHNICAL_REVIEW),selection_salt=SALT,selection_sql=prior['selection_sql'],
        excluded_source_ids=sorted(excluded_sources),excluded_video_ids=sorted(excluded_videos),sources=selected,
        source_text_inspected_for_selection=False,collector_or_reference_inputs_to_selection=False,
        discovery_executed=False,references_constructed=False,provider_requests=0,
        freshness_scope='Prior named development/primary/reserve channels excluded and selected videos have no local sermon_analysis_runs; no model-training or universal prior-exposure claim.'))
    prep.save_new(MANIFEST,value)
    return value


def verify(base_dir=None):
    auth=authority(base_dir);manifest=prep.gate.sealed(MANIFEST);es,ev=exposure_sets()
    if (manifest['authorization_fingerprint']!=auth['content_fingerprint'] or manifest['selection_salt']!=SALT
            or set(manifest['excluded_source_ids'])!=es or set(manifest['excluded_video_ids'])!=ev
            or len(manifest['sources'])!=5 or len({r['source_id'] for r in manifest['sources']})!=5
            or manifest['original_manifest_sha256']!=prep.proposal.a1.file_hash(ORIGINAL_MANIFEST)
            or manifest['technical_review_sha256']!=prep.proposal.a1.file_hash(TECHNICAL_REVIEW)
            or manifest['sources'][:4]!=prep.gate.sealed(ORIGINAL_MANIFEST)['sources']):
        raise ValueError('V3 source selection identity/exclusions changed')
    paths=prep.proposal.build_paths(base_dir)
    with sqlite3.connect(paths.database.as_uri()+'?mode=ro',uri=True) as db:
        for index,row in enumerate(manifest['sources']):
            if row['source_id'] in es or row['video_id'] in ev:raise ValueError('Exposed source in V3')
            if row['selection_sha256']!=hashlib.sha256((SALT+row['youtube_video_id']).encode()).hexdigest():
                raise ValueError('Selection hash changed')
            if row['role']!=('primary' if index<3 else 'technical_reserve_only'):raise ValueError('Source roles changed')
            identity=db.execute('select source_id,youtube_video_id,title from videos where id=?',(row['video_id'],)).fetchone()
            if identity!=(row['source_id'],row['youtube_video_id'],row['title']):raise ValueError('Source identity changed')
            if db.execute('select count(*) from sermon_analysis_runs where video_id=?',(row['video_id'],)).fetchone()[0]:
                raise ValueError('Source has semantic execution exposure')
            for key,digest in row['file_hashes'].items():
                if prep.proposal.a1.file_hash(Path(row[key]))!=digest:raise ValueError('Selected source bytes changed')
    return manifest,auth


def preview(base_dir=None,include_reserve=False):
    manifest,_=verify(base_dir);selected=[r for r in manifest['sources'] if include_reserve or r['role']=='primary']
    for row in selected:
        source=previous.snapshot(row)
        if len(source['text'])>150000:raise ValueError('Source character ceiling exceeded; no truncation')
        prep.save_new(directory(base_dir)/'sources'/f"{row['video_id']}.json",source)
    return [r['video_id'] for r in selected]


def validate_selection(manifest,validation):
    if validation['manifest_fingerprint']!=manifest['content_fingerprint'] or validation['all_three_usable'] is not True:
        raise ValueError('V3 technical source validation required')
    primary=[r['video_id'] for r in manifest['sources'] if r['role']=='primary'];reserves={r['video_id'] for r in manifest['sources'] if r['role']=='technical_reserve_only'}
    ids=validation['active_video_ids'];replaced=set(primary)-set(ids)
    if len(ids)!=3 or len(set(ids))!=3 or len(replaced)>2 or not set(ids)<=set(primary)|reserves:
        raise ValueError('Invalid technical reserve substitution')
    exclusions=validation['technical_exclusions']
    if {r['video_id'] for r in exclusions}!=replaced:
        raise ValueError('Missing or extra technical exclusion')
    if replaced and (not (set(ids)-set(primary))<=reserves or any(r['reason'] not in {'non_sermon','unavailable','corrupt','duplicate','irrecoverable_extraction'} for r in exclusions)):
        raise ValueError('Opportunity/results/punctuation-based replacement prohibited')
    return ids


def validated_sources(base_dir=None):
    manifest,_=verify(base_dir);validation=prep.gate.sealed(VALIDATION);ids=validate_selection(manifest,validation)
    sources=[]
    for vid in ids:
        rows=[r for r in validation['rows'] if r['video_id']==vid]
        if len(rows)!=1:raise ValueError('Missing/duplicate source validation')
        row=rows[0];path=directory(base_dir)/'sources'/f'{vid}.json'
        if prep.proposal.a1.file_hash(path)!=row['preview_sha256']:raise ValueError('Source preview changed')
        source=prep.gate.sealed(path);span=row['main_span']
        if not 0<=span['start']<span['end']<=len(source['text']):raise ValueError('Invalid main span')
        sources.append(prep.seal({**source,'main_span':span,'source_validation_fingerprint':validation['content_fingerprint']}))
    if sum(len(s['text']) for s in sources)>300000:raise ValueError('Aggregate source character ceiling exceeded')
    return sources,validation


def size_preflight(sources):
    """Source-unit formation only; no candidate generation or reference lookup."""
    rows=[]
    for s in sources:
        nodes=collector.source_sentences(s);n=len(nodes)
        nominees={j for i,node in enumerate(nodes) if collector.ASSURANCE.search(node['text']) for j in range(max(0,i-1),min(n,i+2))}
        if len(nominees)>200:raise ValueError('G1 nomination bound exceeded; no truncation')
        rows.append(dict(video_id=s['video_id'],source_chars=len(s['text']),unit_nodes=n,
            G2_G3_upper_bound=10*n,G1_nominations=len(nominees),unit_max_chars=max(len(n['text']) for n in nodes)))
    previous.repair.validate_size_proofs(rows)
    return rows


def freeze_guard(root):
    if REFERENCES.exists() or (root/'references-v3.json').exists() or list(HERE.glob('census-*-v3.json')) or list(root.glob('census-*-v3.json')):
        raise ValueError('Never generate confirmation discovery after reference census exists')


def freeze(base_dir=None):
    manifest,auth=verify(base_dir);root=directory(base_dir);freeze_guard(root)
    if (root/'freeze-v3.json').exists():
        prior=prep.gate.sealed(root/'freeze-v3.json');inv=root/'natural-inventory-v3.json'
        if (prior['authorization_fingerprint']!=auth['content_fingerprint'] or prior['manifest_fingerprint']!=manifest['content_fingerprint']
                or prep.proposal.a1.file_hash(inv)!=prior['inventory_sha256']):raise ValueError('Existing freeze identity changed')
        return prior['inventory_fingerprint']
    sources,validation=validated_sources(base_dir);sizes=size_preflight(sources)
    inventories=[];source_files={};queue=[];total=0
    for source in sources:
        vid=source['video_id'];path=root/'sources'/f'{vid}.reviewed.json';prep.save_new(path,source)
        source_files[str(vid)]=dict(path=str(path),sha256=prep.proposal.a1.file_hash(path))
        col=collector.discover(source);total+=len(col['candidates'])
        if total>20000:raise ValueError('Aggregate candidate ceiling exceeded; no truncation')
        entries=[]
        for c in col['G1_candidates']+col['candidates']:
            env=(dict(status='prepared_not_attested',target=c['target'],leading_context=c['leading_context'],trailing_context=c['trailing_context'])
                if c['capability']=='G1' else collector.automatic_envelope(source,c))
            entries.append(dict(candidate=c,automatic_envelope=env))
        record=dict(video_id=vid,entries=entries,deferrals=col['deferred'],search_diagnostics=col['search_diagnostics'],
            budget_proof=col['budget_proof'],unit_diagnostics=col['unit_diagnostics'])
        repair.validate_natural(record);inventories.append(record)
        for cap,quota in auth['semantic_queue'].items():
            for entry in [e for e in entries if e['candidate']['capability']==cap][:quota]:
                c=entry['candidate'];env=entry['automatic_envelope'];ready=env['status']=='prepared_not_attested'
                queue.append(dict(video_id=vid,capability=cap,candidate_id=c['candidate_id'],status='prepared_unreviewed' if ready else 'deferred',
                    shapes=prep.shapes(source,c,env) if ready else [],target_envelope_source_review='pending',provider_execution_authorized=False))
    if len(queue)>120 or sum(len(q['shapes']) for q in queue)>240:raise ValueError('Future queue bound violated; no truncation')
    inv=prep.seal(dict(version='fresh-natural-inventory-v3',authorization_fingerprint=auth['content_fingerprint'],manifest_fingerprint=manifest['content_fingerprint'],
        source_validation_fingerprint=validation['content_fingerprint'],source_files=source_files,inventories=inventories,queue=queue,
        collector_policy=collector.POLICY,code_hashes={**prep.gate.sealed(repair.INPUT)['code_hashes'],**auth['code_hashes']},
        references_received=False,target_envelope_audit_pending=True,provider_requests=0,provider_execution_authorized=False))
    prep.save_new(root/'natural-inventory-v3.json',inv)
    receipt=prep.seal(dict(version='fresh-inventory-freeze-v3',frozen_at_utc=datetime.now(timezone.utc).isoformat(),authorization_fingerprint=auth['content_fingerprint'],
        manifest_fingerprint=manifest['content_fingerprint'],inventory_fingerprint=inv['content_fingerprint'],inventory_sha256=prep.proposal.a1.file_hash(root/'natural-inventory-v3.json'),
        source_files=source_files,references_existed_at_freeze=False,size_preflight=sizes,provider_requests=0))
    prep.save_new(root/'freeze-v3.json',receipt)
    return inv['content_fingerprint']
