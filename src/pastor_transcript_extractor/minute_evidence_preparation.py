"""Authorized provider-free fixture materialization, never a provider executor."""
from __future__ import annotations
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

from pastor_transcript_extractor import minute_evidence_handoff as design
from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor import minute_evidence_context as contexts
from pastor_transcript_extractor import minute_evidence_nomination as nominations
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths, build_llm_config
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_classification import build_transcript_blocks

HERE=design.ROOT/'docs/review-proposals/minute-evidence-handoff-implementation-v1'
AUTH=HERE/'authorization-v1.json'
MANIFEST=HERE/'preparation-manifest-v1.json'
OVERLAYS={'src/pastor_transcript_extractor/commands/analysis/structure.py','docs/review-proposals/README.md'}


def verify_proposal():
    proposal=trace.read(design.HERE/'proposal-v1.json',True);design.validate(proposal)
    packet=trace.read(design.HERE/'packet-v1.json',True)
    if packet['proposal_fingerprint']!=proposal['content_fingerprint']:raise ValueError('Proposal packet changed')
    auth=trace.read(AUTH,True)
    if (auth['proposal_fingerprint']!=proposal['content_fingerprint'] or auth['status']!='IMPLEMENTATION_PROVIDER_FREE_PREPARATION_AUTHORIZED'
            or set(auth['authorized_overlays'])!=OVERLAYS or auth['baseline_commit']!='ac4ed19'
            or not auth['implementation'] or not auth['provider_free_preparation']
            or any(auth[k] for k in ('provider_execution','model_loading','Jev','admission','collection_projection','fresh_sources'))):
        raise ValueError('Implementation authority changed')
    for name,expected in packet['files'].items():
        path=(design.ROOT/name).resolve()
        if not path.is_relative_to(design.ROOT):raise ValueError('Foreign proposal path')
        if trace.digest(path)==expected:continue
        if name not in OVERLAYS:raise ValueError('Frozen proposal dependency differs: '+name)
        result=subprocess.run(['git','show','ac4ed19:'+name],cwd=design.ROOT,check=True,capture_output=True)
        if hashlib.sha256(result.stdout).hexdigest()!=expected:raise ValueError('Frozen baseline differs')
    if proposal['probe_supersession_fingerprint']!=design.closure()['content_fingerprint']:raise ValueError('Supersession changed')
    return proposal


def prepare(base_dir=None):
    proposal=verify_proposal();old_trace,_=trace.verify(base_dir)
    spec=trace.read(trace.SPEC,True);old=trace.read(trace.OLD_INPUT,True)
    if len(spec['cases'])!=24:raise ValueError('Only the prepared 24 trace slots are authorized')
    sources={};proofs={};envelopes={};rows=[]
    files={str(trace.SPEC):trace.digest(trace.SPEC),str(trace.OLD_INPUT):trace.digest(trace.OLD_INPUT)}
    for vid in (520,1094,951):
        info=old['source_files'][str(vid)]
        if trace.digest(info['path'])!=info['sha256']:raise ValueError('Frozen source changed')
        source=trace.read(info['path'],True);manifest=source['source_manifest_row']
        path=Path(manifest['proposed_json_path'])
        if trace.digest(path)!=manifest['file_hashes']['proposed_json_path']:raise ValueError('Extraction changed')
        extracted=trace.read(path);segments=extracted['segments']
        if len(segments)>5000:raise ValueError('Bounded fixture limit exceeded')
        proof=contexts.validate_source(source,segments)
        retained=set(extracted['classification']['retained_segment_indexes'])
        drafts=[SegmentDraft(s['start_seconds'],s['end_seconds'],s['text'],s.get('speaker_hint'),s['label'],s.get('confidence')) for s in segments]
        blocks=build_transcript_blocks(drafts,target_seconds=60,max_chars=3200,normalize_rolling_captions=True)
        if len(blocks)>200:raise ValueError('Bounded block limit exceeded')
        block_map={b.block_id:b for b in blocks}
        source_rows=[]
        for case in [c for c in spec['cases'] if c['video_id']==vid]:
            traced=next(c for c in old_trace['cases'] if c['case_id']==case['case_id'])
            # Diagnostic anchors were already selected by the sealed trace; this
            # is not natural retrieval, new reference matching or a rescue.
            candidate=traced['reconstructed_minute_candidates'][0] if traced['reconstructed_minute_candidates'] else None
            if candidate is None:
                rows.append(dict(case_id=case['case_id'],video_id=vid,status='deferred',reason='no_trace_anchor'));continue
            block=block_map[candidate['block_id']]
            if (block.segment_indexes!=candidate['segment_indexes'] or block.start_seconds!=candidate['start_seconds'] or block.end_seconds!=candidate['end_seconds']):
                raise ValueError('Trace anchor no longer matches deterministic block')
            anchor=contexts.map_anchor(source,block,retained,proof);context=contexts.plan_context(source,anchor)
            row=dict(case_id=case['case_id'],kind=case['kind'],route=case['route'],video_id=vid,
                anchor_block_id=block.block_id,anchor=anchor,status=context['status'],reason=context.get('reason'),
                discovery_credit=False,current_routing_established=False)
            if context['status']=='prepared_context_only':
                family='G2' if case['route']=='G2' else 'G3'
                binding=nominations.identity(proof,anchor,context,family)
                envelopes[context['content_fingerprint']]=context
                row.update(context_fingerprint=context['content_fingerprint'],preparation_binding=binding,
                    diagnostic_footprint_inside=all(context['start']<=s['start']<s['end']<=context['end'] for s in
                        [*case['oracle']['focal_roles'].values(),*case['oracle']['required_source_supports']]))
            source_rows.append(row);rows.append(row)
        sources[vid]=dict(proof=proof,retained_membership_basis='historical extraction membership, not newly classified eligibility',
            source_kind=extracted['transcript_source'],manifest_source_kind=manifest['source_kind'],
            source_kind_discrepancy=extracted['transcript_source']!=manifest['source_kind'],
            classifications_reused_as_exact_evidence=False,anchors_attempted=len(source_rows))
        files[info['path']]=info['sha256'];files[str(path)]=trace.digest(path);proofs[vid]=proof
    rows.sort(key=lambda r:r['case_id']);config=build_llm_config()
    pins=[Path(__file__),Path(contexts.__file__),Path(nominations.__file__),AUTH,
          design.ROOT/'src/pastor_transcript_extractor/commands/analysis/structure.py',
          design.ROOT/'tests/test_minute_evidence_implementation.py']
    packet=seal(dict(version='minute-evidence-provider-free-preparation-v1',status='PREPARED_NO_INFERENCE_AUTHORIZED',
        proposal_fingerprint=proposal['content_fingerprint'],authorization_fingerprint=trace.read(AUTH,True)['content_fingerprint'],
        trace_fingerprint=old_trace['content_fingerprint'],policy=contexts.POLICY,sources=sources,cases=rows,
        contexts=envelopes,input_files=files,implementation_files={str(p):trace.digest(p) for p in pins},
        counts=dict(cases=len(rows),mapped=sum(r['anchor']['status']=='mapped' for r in rows if 'anchor' in r),
                    prepared=sum(r['status']=='prepared_context_only' for r in rows),unique_contexts=len(envelopes),
                    unique_bindings=len({r['preparation_binding']['content_fingerprint'] for r in rows if 'preparation_binding' in r}),
                    deferrals=dict(Counter(r['reason'] for r in rows if r.get('reason')))),
        backend=dict(configured_model=config.model,configured_context_size=config.context_size,
            model_digest=None,model_metadata_fetched=False,token_budget_established=False,prompt_or_provider_wire_request_prepared=False),
        provider_requests=0,model_loading=False,semantic_recovery=None,measurement_execution=False,admission_execution=False,
        usable_evidence=None,execution_authorized=False,execution_command=None,
        limitations=['Trace-selected anchors are retired development fixtures, not discovery or fresh confirmation.',
            'Membership is from historical persisted extraction; present-model routing is unestablished.',
            'Context/target geometry is not semantic sufficiency, provenance attestation or pastor credit.',
            'Ollama model/tokenizer/prompt/runtime/output budgets remain unlocked; prepared bindings cannot execute or reuse provider caches.',
            'The existing 24 oracle slots are diagnostics only; old 10/12 or paid execution authorizations do not transfer.']))
    out=build_paths(base_dir).evaluation/'minute-evidence-handoff-v1'/packet['content_fingerprint']
    out.mkdir(parents=True,exist_ok=True);path=out/'preparation-v1.json'
    raw=json.dumps(packet,ensure_ascii=False,indent=2)+'\n'
    if path.exists() and path.read_text()!=raw:raise ValueError('Immutable preparation differs')
    path.write_text(raw)
    return packet,path


def verify(base_dir=None):
    verify_proposal();pointer=trace.read(MANIFEST,True)
    path=build_paths(base_dir).evaluation/pointer['relative_path']
    if trace.digest(path)!=pointer['sha256']:raise ValueError('Preparation file differs')
    packet=trace.read(path,True)
    if packet['content_fingerprint']!=pointer['input_fingerprint']:raise ValueError('Preparation binding differs')
    for name,expected in {**packet['input_files'],**packet['implementation_files']}.items():
        if trace.digest(name)!=expected:raise ValueError('Preparation dependency changed: '+name)
    if packet['provider_requests']!=0 or packet['execution_authorized'] or packet['measurement_execution'] or packet['admission_execution']:
        raise ValueError('Provider-free scope differs')
    return packet,path
