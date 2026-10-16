"""Authorized fresh-source preparation; no provider constructor or paid execution.

Freeze immutable source-only inventory/queue before any reference census exists.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from pastor_transcript_extractor import fresh_discovery_readiness as proposal
from pastor_transcript_extractor import evidence_supply_collector_design as collector
from pastor_transcript_extractor import evidence_supply_revision as baseline
from pastor_transcript_extractor import evidence_boundary_admission as gate
from pastor_transcript_extractor.caption_normalization import normalize_caption_fragments
from pastor_transcript_extractor.config import build_paths

HERE = proposal.HERE
AUTH = HERE / 'preparation-authorization-v1.json'
MODEL = 'jev-1.13.0'
ENVELOPE_POLICY = dict(version='fresh-contiguous-envelope-v1', maximum_chars=6000,
    preceding_complete_sentences_chars=1200, following_complete_sentences_chars=400,
    role_target_unchanged=True, provenance_attestation=False)


def seal(value):
    value = {k:v for k,v in value.items() if k != 'content_fingerprint'}
    return value | {'content_fingerprint': baseline.fp(value)}


def save_new(path, value):
    """No replacement of a sealed inventory/reference/result, even on restart."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError('Existing frozen artifact differs; preserve it: ' + str(path))
        return
    with path.open('x') as stream:
        stream.write(raw)


def directory(base_dir=None):
    return build_paths(base_dir).evaluation / 'fresh-discovery-readiness-v1'


def authorization(base_dir=None):
    plan, manifest = proposal.verify(base_dir)
    auth = gate.sealed(AUTH)
    if (auth['status'] != 'AUTHORIZED' or auth['decision_owner'] != 'Brian'
            or auth['proposal_fingerprint'] != plan['content_fingerprint']
            or auth['manifest_fingerprint'] != manifest['content_fingerprint']
            or auth['proposal_sha256'] != proposal.a1.file_hash(proposal.PLAN)
            or auth['manifest_sha256'] != proposal.a1.file_hash(proposal.MANIFEST)
            or auth['primary_video_ids'] != [1565,1450,1618]
            or auth['preparation_authorized'] is not True or auth['provider_calls_authorized'] is not False
            or auth['criterion_clarification'] != dict(per_source_route_recall_min=.80,
                per_source_route_min_definite_opportunities_for_gate=5,denominators_1_to_4='diagnostic_only',
                aggregate_route_recall_min=.80,aggregate_sufficient_automatic_envelope_recall_min=.80)):
        raise ValueError('Missing exact provider-free preparation authority')
    return plan, manifest, auth


def source_snapshot(row):
    extracted = json.loads(Path(row['proposed_json_path']).read_text())
    segments = extracted['segments']
    normalized = normalize_caption_fragments((i,s['text']) for i,s in enumerate(segments))
    text = '\n'.join(u.text for u in normalized.units)
    units=[]; cursor=0
    for i,u in enumerate(normalized.units):
        start=cursor;end=start+len(u.text)
        units.append(dict(unit_id=f'{row["video_id"]}:F{i:04}',start=start,end=end,text=u.text,
            source_segment_indexes=list(u.source_segment_indexes),
            start_seconds=min(segments[j]['start_seconds'] for j in u.source_segment_indexes),
            end_seconds=max(segments[j]['end_seconds'] for j in u.source_segment_indexes)))
        cursor=end+1
    lo,hi=(row['existing_window_seconds'][k] for k in ('start_seconds','end_seconds'))
    main=[u for u in units if u['end_seconds'] > lo and u['start_seconds'] < hi]
    if not main: raise ValueError('No normalized main-source units')
    return seal(dict(version='fresh-source-snapshot-v1',video_id=row['video_id'],source_id=row['source_id'],
        source_manifest_row=row,text=text,units=units,
        main_span=dict(start=main[0]['start'],end=main[-1]['end'],
                       rationale='Existing extracted interval mapped to complete normalized source units; boundary audit required.'),
        normalized_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        normalization_diagnostics=normalized.diagnostics,pastor_credit=False))


def preview(base_dir=None):
    plan,manifest,auth=authorization(base_dir)
    sources=[source_snapshot(r) for r in manifest['sources'] if r['role']=='primary']
    if any(len(s['text'])>150000 for s in sources) or sum(len(s['text']) for s in sources)>300000:
        raise ValueError('Canonical character ceiling exceeded; no source truncation')
    for s in sources:
        save_new(directory(base_dir)/'sources'/f'{s["video_id"]}.json',s)
    return sources


@lru_cache(maxsize=4)
def _sentences(text, lo, hi):
    return baseline.sentences(dict(text=text,main_span=dict(start=lo,end=hi)))


def automatic_envelope(source,candidate):
    frame=candidate['relation_frame']
    sentences=_sentences(source['text'],source['main_span']['start'],source['main_span']['end'])
    before=[n for n in sentences if n['end']<=frame['start'] and frame['start']-n['start']<=ENVELOPE_POLICY['preceding_complete_sentences_chars']]
    after=[n for n in sentences if n['start']>=frame['end'] and n['end']-frame['end']<=ENVELOPE_POLICY['following_complete_sentences_chars']]
    lo=before[0]['start'] if before else frame['start'];hi=after[-1]['end'] if after else frame['end']
    # Drop optional complete context first; never clip a required target/attribution.
    if hi-lo>6000: hi=frame['end']
    if hi-lo>6000: lo=frame['start']
    if hi-lo>6000: return dict(status='deferred',reason='required_frame_exceeds_6000',required_span=frame)
    return dict(status='prepared_not_attested',start=lo,end=hi,text=source['text'][lo:hi],
                policy_version=ENVELOPE_POLICY['version'],source_voice=None,atomic_sufficiency=None)


def shapes(source, candidate, envelope):
    cap=candidate['capability']
    if cap=='G1':
        return [{k:r[k] for k in ('state','questions','question_version')} | {'phase':'G1_claim_and_source'}
                for r in baseline.request_inputs([candidate])]
    clean={k:envelope[k] for k in ('start','end','text')}
    return gate.materialize(source,cap,candidate['endpoints'],clean)['shapes']


def freeze(base_dir=None):
    plan,manifest,auth=authorization(base_dir)
    root=directory(base_dir)
    if (root/'references-v1.json').exists():
        raise ValueError('References already exist: never regenerate discovery after census')
    sources=preview(base_dir)
    validation=gate.sealed(HERE/'source-validation-v1.json')
    if (validation['manifest_fingerprint']!=manifest['content_fingerprint']
            or validation['primary_video_ids']!=auth['primary_video_ids']
            or validation['all_three_usable'] is not True):
        raise ValueError('Full-source identity/boundary and duplicate audit required before freeze')
    inventories=[]; queue=[]; source_info={}; total=0
    for s in sources:
        vid=s['video_id']
        reviewed=next(r for r in validation['rows'] if r['video_id']==vid)
        if proposal.a1.file_hash(root/'sources'/f'{vid}.json')!=reviewed['preview_sha256']:
            raise ValueError('Source preview changed after boundary review')
        s=seal({**s,'main_span':reviewed['main_span'],
                'source_validation_fingerprint':validation['content_fingerprint']})
        path=root/'sources'/f'{vid}.reviewed.json'
        save_new(path,s)
        source_info[str(vid)]=dict(path=str(path),sha256=proposal.a1.file_hash(path))
        collection=collector.discover(s)
        total+=len(collection['candidates'])
        if total>20000:raise ValueError('Aggregate G2/G3 candidate ceiling exceeded; no truncation')
        g1all,g1diag=baseline.discover(s)
        g1=[c for c in g1all if c['capability']=='G1']
        if len(g1)>200:raise ValueError('G1 source candidate ceiling exceeded; no truncation')
        entries=[]
        for c in g1+collection['candidates']:
            if c['capability']=='G1':
                env=dict(status='prepared_not_attested',target=c['target'],leading_context=c['leading_context'],trailing_context=c['trailing_context'])
            else: env=automatic_envelope(s,c)
            entries.append(dict(candidate=c,automatic_envelope=env))
        inventories.append(dict(video_id=vid,entries=entries,deferrals=collection['deferred'],
            budget_proof=collection['budget_proof'],search_diagnostics=collection['search_diagnostics'],
            G1_unrepresentable=[e for e in g1diag['unrepresentable'] if e['capability']=='G1']))
        for cap,quota in plan['semantic_queue']['per_source'].items():
            eligible=[e for e in entries if e['candidate']['capability']==cap]
            # Preserve the original source-only collector order; no reference input.
            for e in eligible[:quota]:
                c=e['candidate'];env=e['automatic_envelope']
                queue.append(dict(video_id=vid,capability=cap,candidate_id=c['candidate_id'],
                    status='prepared' if env['status']=='prepared_not_attested' else 'deferred',
                    shapes=shapes(s,c,env) if env['status']=='prepared_not_attested' else [],
                    deferral=None if env['status']=='prepared_not_attested' else env))
    inventory=seal(dict(version='fresh-natural-inventory-v1',authorization_fingerprint=auth['content_fingerprint'],
        source_files=source_info,source_validation_fingerprint=validation['content_fingerprint'],collector_policy=collector.POLICY,
        envelope_policy=ENVELOPE_POLICY,inventories=inventories,queue=queue,
        code_hashes={str(Path(m.__file__).relative_to(proposal.ROOT)):proposal.a1.file_hash(Path(m.__file__))
                     for m in (collector,baseline,__import__(__name__,fromlist=['_']))},
        references_received=False,provider_requests=0))
    save_new(root/'natural-inventory-v1.json',inventory)
    log=seal(dict(version='fresh-discovery-inventory-freeze-v1',frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        inventory_fingerprint=inventory['content_fingerprint'],inventory_sha256=proposal.a1.file_hash(root/'natural-inventory-v1.json'),
        source_files=source_info,references_existed_at_freeze=False,
        candidate_counts={str(v['video_id']):dict(Counter(e['candidate']['capability'] for e in v['entries'])) for v in inventories},
        queue_units=len(queue),prepared_requests=sum(len(q['shapes']) for q in queue),provider_requests=0))
    if not (root/'freeze-v1.json').exists():save_new(root/'freeze-v1.json',log)
    return inventory
