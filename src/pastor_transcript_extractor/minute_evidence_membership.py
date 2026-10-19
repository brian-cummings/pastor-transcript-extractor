"""Explicit reviewed-window precedence for retired fixtures; no production update."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import hashlib
import json
import subprocess

from pastor_transcript_extractor import minute_evidence_preparation as baseline
from pastor_transcript_extractor import minute_evidence_context as contexts
from pastor_transcript_extractor import minute_evidence_nomination as nominations
from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_classification import build_transcript_blocks

HERE=trace.ROOT/'docs/review-proposals/minute-membership-reconciliation-v1'
AUTH=HERE/'authorization-v1.json'
MANIFEST=HERE/'preparation-manifest-v1.json'
REVIEW=trace.ROOT/'docs/review-proposals/fresh-discovery-readiness-v3/source-validation-v3.json'
BASELINE_COMMIT='42f1fb6'
CLI_PATH='src/pastor_transcript_extractor/commands/analysis/structure.py'


def verify_baseline(base_dir=None):
    """Verify unchanged baseline data/code; only its CLI is read from Git."""
    baseline.verify_proposal()
    pointer=trace.read(baseline.MANIFEST,True)
    path=build_paths(base_dir).evaluation/pointer['relative_path']
    if trace.digest(path)!=pointer['sha256']:raise ValueError('Baseline preparation file differs')
    packet=trace.read(path,True)
    if packet['content_fingerprint']!=pointer['input_fingerprint']:raise ValueError('Baseline input binding differs')
    for name,expected in {**packet['input_files'],**packet['implementation_files']}.items():
        if trace.digest(name)==expected:continue
        relative=Path(name).relative_to(trace.ROOT).as_posix()
        if relative!=CLI_PATH:raise ValueError('Baseline dependency differs: '+name)
        result=subprocess.run(['git','show',BASELINE_COMMIT+':'+relative],cwd=trace.ROOT,check=True,capture_output=True)
        if hashlib.sha256(result.stdout).hexdigest()!=expected:raise ValueError('Archived baseline CLI differs')
    if packet['provider_requests']!=0 or packet['execution_authorized']:raise ValueError('Baseline scope differs')
    return packet,path


def effective_membership(source,extracted,*,review=None,authority=None):
    """Replacement, never union. No authority means persisted membership only."""
    if seal(source)!=source:raise ValueError('Source seal differs')
    saved=sorted(set(extracted['classification']['retained_segment_indexes']))
    saved_fp=seal(dict(indexes=saved))['content_fingerprint']
    if authority is None:
        return seal(dict(mode='persisted_extraction',scope='historical_saved_membership',effective_indexes=saved,
                         saved_indexes=saved,saved_identity=saved_fp,authority_fingerprint=None,production_authorization=False))
    if (seal(authority)!=authority or authority['status']!='PROVIDER_FREE_FIXTURE_RECONCILIATION_AUTHORIZED'
            or authority['membership_scope']!='retired_fixture_preparation_only'
            or any(authority[k] for k in ('production_authorization','provider_execution','measurement_admission','classifications_mutated','source_files_mutated','additional_sources'))):
        raise ValueError('Reconciliation authority/scope differs')
    if review is None or seal(review)!=review or source['source_validation_fingerprint']!=review['content_fingerprint'] or authority['review_validation_fingerprint']!=review['content_fingerprint']:
        raise ValueError('Reviewed source-window binding differs')
    binding=authority['source_bindings'].get(str(source['video_id']))
    if (not binding or binding['source_fingerprint']!=source['content_fingerprint']
            or binding['extraction_content_fingerprint']!=seal(extracted)['content_fingerprint']):
        raise ValueError('Source/extraction authority binding differs')
    rows=[r for r in review['rows'] if r['video_id']==source['video_id']]
    if len(rows)!=1 or rows[0]['technically_usable_sermon'] is not True:raise ValueError('Review has no unique usable source')
    window=rows[0]['main_span']
    if window!=source['main_span'] or binding['reviewed_main_span']!=window:raise ValueError('Reviewed window differs')
    lo,hi=window['start'],window['end']
    if type(lo) is not int or type(hi) is not int or not 0<=lo<hi<=len(source['text']):raise ValueError('Invalid reviewed bounds')
    included=[u for u in source['units'] if lo<=u['start']<u['end']<=hi]
    boundary=[u for u in source['units'] if u['start']<hi and u['end']>lo and u not in included]
    effective=sorted({i for u in included for i in u['source_segment_indexes']})
    return seal(dict(mode='explicit_reviewed_main_replacement',scope='retired_fixture_preparation_only',
        source_fingerprint=source['content_fingerprint'],review_fingerprint=review['content_fingerprint'],
        authority_fingerprint=authority['content_fingerprint'],reviewed_main_span=window,
        saved_indexes=saved,saved_identity=saved_fp,effective_indexes=effective,
        added_indexes=sorted(set(effective)-set(saved)),removed_indexes=sorted(set(saved)-set(effective)),
        included_unit_ids=[u['unit_id'] for u in included],boundary_units_deferred=[u['unit_id'] for u in boundary],
        precision='complete canonical normalization units; no raw word-level timestamps',
        production_authorization=False,classification_rewritten=False,pastor_identity_established=False))


def prepare(base_dir=None):
    old,_=verify_baseline(base_dir);authority=trace.read(AUTH,True);review=trace.read(REVIEW,True)
    if (authority['baseline_preparation_fingerprint']!=old['content_fingerprint']
            or authority['review_validation_sha256']!=trace.digest(REVIEW)
            or set(authority['source_bindings'])!={'520','1094','951'}):raise ValueError('Fixed reconciliation input differs')
    source_files=trace.read(trace.OLD_INPUT,True)['source_files'];spec=trace.read(trace.SPEC,True)
    if len(spec['cases'])!=24 or len(old['cases'])!=24:raise ValueError('Fixed diagnostic slate differs')
    oracle={c['case_id']:c for c in spec['cases']};sources={};rows=[];envelopes={}
    files={str(AUTH):trace.digest(AUTH),str(REVIEW):trace.digest(REVIEW),str(trace.SPEC):trace.digest(trace.SPEC),str(trace.OLD_INPUT):trace.digest(trace.OLD_INPUT)}
    for vid in (520,1094,951):
        info=source_files[str(vid)];source=trace.read(info['path'],True);binding=authority['source_bindings'][str(vid)]
        extraction_path=Path(source['source_manifest_row']['proposed_json_path'])
        if trace.digest(info['path'])!=binding['source_file_sha256'] or trace.digest(extraction_path)!=binding['extraction_file_sha256']:
            raise ValueError('Canonical source/extraction bytes changed')
        extracted=trace.read(extraction_path);segments=extracted['segments']
        if len(segments)>5000:raise ValueError('Bounded fixture size exceeded')
        proof=contexts.validate_source(source,segments)
        membership=effective_membership(source,extracted,review=review,authority=authority)
        drafts=[SegmentDraft(s['start_seconds'],s['end_seconds'],s['text'],s.get('speaker_hint'),s['label'],s.get('confidence')) for s in segments]
        blocks=build_transcript_blocks(drafts,target_seconds=60,max_chars=3200,normalize_rolling_captions=True)
        if len(blocks)>200:raise ValueError('Bounded block size exceeded')
        block_map={b.block_id:b for b in blocks}
        for previous in [r for r in old['cases'] if r['video_id']==vid]:
            if 'anchor_block_id' not in previous:raise ValueError('No fixed anchor; no alternative rescue allowed')
            block=block_map[previous['anchor_block_id']];a=previous['anchor']
            if (block.segment_indexes!=a['segment_indexes'] or block.start_seconds!=a['start_seconds'] or block.end_seconds!=a['end_seconds']):raise ValueError('Fixed anchor differs')
            anchor=contexts.map_anchor(source,block,set(membership['effective_indexes']),proof)
            anchor=seal({**anchor,'effective_membership_fingerprint':membership['content_fingerprint'],
                'membership_scope':membership['scope'],'historical_saved_membership_identity':membership['saved_identity']})
            context=contexts.plan_context(source,anchor)
            row=dict(case_id=previous['case_id'],kind=previous['kind'],route=previous['route'],video_id=vid,
                anchor_block_id=block.block_id,anchor=anchor,status=context['status'],reason=context.get('reason'),
                historical_status=previous['status'],historical_reason=previous['reason'],
                classification_changed=False,discovery_credit=False,current_routing_established=False)
            if context['status']=='prepared_context_only':
                family='G2' if row['route']=='G2' else 'G3'
                request=nominations.identity(proof,anchor,context,family,routing_identity=membership['content_fingerprint'])
                envelopes[context['content_fingerprint']]=context
                case=oracle[row['case_id']]
                row.update(context_fingerprint=context['content_fingerprint'],preparation_binding=request,
                    diagnostic_footprint_inside=all(context['start']<=s['start']<s['end']<=context['end'] for s in [*case['oracle']['focal_roles'].values(),*case['oracle']['required_source_supports']]))
            rows.append(row)
        sources[vid]=dict(membership=membership,source_kind=extracted['transcript_source'],manifest_source_kind=source['source_manifest_row']['source_kind'],
            proof=proof,source_study_only=True,nominal_pastor_credit=False)
        files[info['path']]=trace.digest(info['path']);files[str(extraction_path)]=trace.digest(extraction_path)
    rows.sort(key=lambda r:r['case_id'])
    pins=[Path(__file__),Path(contexts.__file__),Path(nominations.__file__),
          trace.ROOT/CLI_PATH,trace.ROOT/'tests/test_minute_evidence_membership.py']
    packet=seal(dict(version='minute-membership-reconciled-preparation-v1',status='RECONCILED_FIXTURES_NO_INFERENCE_AUTHORIZED',
        authority_fingerprint=authority['content_fingerprint'],baseline_preparation_fingerprint=old['content_fingerprint'],
        review_validation_fingerprint=review['content_fingerprint'],policy=contexts.POLICY,
        membership_scope='retired_fixture_preparation_only',sources=sources,cases=rows,contexts=envelopes,
        input_files=files,implementation_files={str(p):trace.digest(p) for p in pins},
        counts=dict(cases=len(rows),prepared=sum(r['status']=='prepared_context_only' for r in rows),
            unique_contexts=len(envelopes),unique_bindings=len({r['preparation_binding']['content_fingerprint'] for r in rows if 'preparation_binding' in r}),
            deferrals=dict(Counter(r['reason'] for r in rows if r.get('reason'))),
            newly_prepared=sum(r['status']=='prepared_context_only' and r['historical_status']!='prepared_context_only' for r in rows)),
        backend=old['backend'],provider_requests=0,model_loading=False,execution_authorized=False,
        production_authorization=False,measurement_execution=False,admission_execution=False,usable_evidence=None,
        semantic_recovery=None,execution_command=None,
        limitations=old['limitations']+['Explicit source-review precedence applies to these retired fixtures only, not production membership or nominal pastor attribution.',
            'Whole boundary-crossing normalization units remain excluded; no word-level membership is invented.',
            'Baseline 19/24 and its artifacts remain unchanged. Reconciled supply is not a discovery or semantic improvement result.']))
    out=build_paths(base_dir).evaluation/'minute-membership-reconciliation-v1'/packet['content_fingerprint'];out.mkdir(parents=True,exist_ok=True)
    path=out/'preparation-v1.json';raw=json.dumps(packet,ensure_ascii=False,indent=2)+'\n'
    if path.exists() and path.read_text()!=raw:raise ValueError('Immutable reconciliation differs')
    path.write_text(raw)
    return packet,path


def verify(base_dir=None):
    verify_baseline(base_dir);pointer=trace.read(MANIFEST,True)
    path=build_paths(base_dir).evaluation/pointer['relative_path']
    if trace.digest(path)!=pointer['sha256']:raise ValueError('Reconciled preparation file differs')
    packet=trace.read(path,True)
    if packet['content_fingerprint']!=pointer['input_fingerprint']:raise ValueError('Reconciled preparation binding differs')
    for name,expected in {**packet['input_files'],**packet['implementation_files']}.items():
        if trace.digest(name)!=expected:raise ValueError('Reconciliation dependency changed: '+name)
    authority=trace.read(AUTH,True)
    if packet['authority_fingerprint']!=authority['content_fingerprint'] or packet['membership_scope']!='retired_fixture_preparation_only':raise ValueError('Reconciliation authority changed')
    if packet['provider_requests'] or any(packet[k] for k in ('execution_authorized','production_authorization','measurement_execution','admission_execution')):raise ValueError('Reconciled scope differs')
    return packet,path
