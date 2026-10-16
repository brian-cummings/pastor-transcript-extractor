"""Fingerprint-bound retired-source workflow. Execution remains separately held."""
from __future__ import annotations
from contextlib import contextmanager
import fcntl
import json
import os
import uuid
from pathlib import Path
import time

from pastor_transcript_extractor import collector_retrieval_design as design
from pastor_transcript_extractor import collector_retrieval_v1_1 as collector
from pastor_transcript_extractor import collector_retrieval_encoder as encoder
from pastor_transcript_extractor import collector_retrieval_json_v1_1 as prep
from pastor_transcript_extractor import collector_retrieval_workflow as historical
from pastor_transcript_extractor.config import build_paths

HERE=design.ROOT/'docs/review-proposals/collector-retrieval-repair-v1.1'
INPUT=HERE/'development-input-v1.1.json'
EXECUTION=HERE/'execution-authorization-v1.1.json'


def directory(base_dir=None):
    return build_paths(base_dir).evaluation/'collector-retrieval-development-v1.1'


def verify():
    original=historical.verify()
    packet=design.sealed(INPUT)
    decision=design.sealed(HERE/'implementation-authorization-v1.1.json')
    if (decision['implementation_authorized'] is not True or decision['execution_authorized'] is not False
            or decision['accepted']!={'retrieval_V1':'FAIL','G1':'HOLD'}
            or decision['decision_owner']!='Brian'
            or packet['implementation_authorization_sha256']!=design.file_hash(HERE/'implementation-authorization-v1.1.json')
            or packet['baseline_input_fingerprint']!=original['content_fingerprint']
            or packet['policy']!=collector.POLICY
            or packet['artifact_lock_fingerprint']!=original['artifact_lock_fingerprint']
            or packet['resources']!=original['resources']
            or any(packet[k]!=original[k] for k in ('source_files','development_video_ids','reference_path','reference_sha256'))
            or any(packet[k] is not False for k in ('execution_authorized','model_loading_authorized','provider_calls_authorized','fresh_source_selection_authorized'))):
        raise ValueError('V1.1 repair scope/budget changed')
    if {k:v for k,v in collector.POLICY.items() if k!='version'}!={k:v for k,v in historical.collector.POLICY.items() if k!='version'}:
        raise ValueError('Frozen ceilings changed')
    for name,digest in packet['pins'].items():
        path=(design.ROOT/name).resolve()
        if not path.is_relative_to(design.ROOT) or design.file_hash(path)!=digest:
            raise ValueError('V1.1 implementation/baseline pin changed: '+name)
    return packet


def sources(packet):
    result={}
    for vid,info in packet['source_files'].items():
        path=Path(info['path'])
        if design.file_hash(path)!=info['sha256']: raise ValueError('Retired source changed')
        value=design.sealed(path)
        if value['video_id']!=int(vid): raise ValueError('Source identity mismatch')
        result[int(vid)]=value
    return result


def preflight(packet=None):
    """Structural counts only; no lattice, candidates, matching, or model import."""
    packet=packet or verify(); values=sources(packet)
    rows=[collector.structural_preflight(s) for s in values.values()]
    if sum(r['G2_G3_max'] for r in rows)>20000: raise ValueError('Aggregate candidate proof exceeds ceiling')
    if (any(len(s['text'])>150000 for s in values.values()) or sum(len(s['text']) for s in values.values())>300000):
        raise ValueError('Source character ceiling exceeded')
    for s in values.values():
        nodes=collector.substrate.source_sentences(s)
        nominations={j for i,n in enumerate(nodes) if collector.substrate.ASSURANCE.search(n['text'])
            for j in range(max(0,i-1),min(len(nodes),i+2))}
        if len(nominations)>200: raise ValueError('G1 source nomination ceiling exceeded')
    return rows


def require_execution(packet, approve_input, operation):
    if approve_input!=packet['content_fingerprint']: raise ValueError('Exact development input fingerprint required')
    if not EXECUTION.exists(): raise ValueError('Separate model/development execution authorization is absent; held')
    decision=design.sealed(EXECUTION)
    if (decision['status']!='AUTHORIZED' or decision['decision_owner']!='Brian'
            or decision['input_fingerprint']!=packet['content_fingerprint']
            or decision['artifact_lock_fingerprint']!=packet['artifact_lock_fingerprint']
            or decision['provider_calls_authorized'] is not False
            or decision['source_selection_authorized'] is not False
            or decision['collection_projection_authorized'] is not False
            or decision.get('attempts')!=1
            or decision.get('development_video_ids')!=packet['development_video_ids']
            or decision.get('resources')!=packet['resources']
            or any(decision.get(k) is not False for k in ('semantic_admission_threshold_changes_authorized',
                'automatic_provenance_authorized','model_comparison_training_authorized','reference_specific_tuning_authorized'))
            or decision.get('local_encoder_execution_authorized') is not True
            or decision[operation] is not True):
        raise ValueError('Separate execution authority mismatches this packet')
    return decision


@contextmanager
def exclusive(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a') as stream:
        try: fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error: raise ValueError('Workflow is already locked') from error
        try: yield
        finally: fcntl.flock(stream,fcntl.LOCK_UN)



def save_checkpoint(path, value, resources):
    """Immutable atomic seals; interrupted temporary writes are never reused."""
    normalized=prep.seal(value)
    if value.get('content_fingerprint')!=normalized['content_fingerprint']:
        raise ValueError('Checkpoint seal does not match JSON-native preimage')
    value=normalized
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
    if len(raw)>resources['inventory_bytes_max']: raise ValueError('Checkpoint/output size ceiling exceeded')
    if path.exists():
        if design.sealed(path)!=value: raise ValueError('Existing sealed checkpoint differs')
        return
    used=sum(p.stat().st_size for p in path.parent.glob('*.json'))
    if used+len(raw)>resources['runtime_output_bytes_max']: raise ValueError('Runtime output budget exceeded')
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.partial')
    try:
        with temp.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.link(temp,path) # fail if any competing writer already created the seal
    finally:
        if temp.exists(): temp.unlink()


def run_development(base_dir=None, approve_input=None):
    packet=verify(); decision=require_execution(packet,approve_input,'development_execution_authorized')
    if decision.get('model_loading_authorized') is not True: raise ValueError('Model loading remains held')
    sizes=preflight(packet); values=sources(packet); root=directory(base_dir)/packet['content_fingerprint']
    lock=design.sealed(encoder.LOCK); model_dir=historical.directory(base_dir)/'model'/lock['revision']
    started=time.monotonic();deadline=started+packet['resources']['wall_time_seconds_max']
    with exclusive(root/'execution.lock'):
        result_path=root/'results-v1.1.json'
        if result_path.exists():
            result=design.sealed(result_path)
            if (result['execution_authorization_fingerprint']!=decision['content_fingerprint']
                    or result['input_fingerprint']!=packet['content_fingerprint']
                    or result['inventory_sha256']!=design.file_hash(root/'natural-inventory-v1.1.json')):
                raise ValueError('Existing result binding changed')
            return result
        inventories=[]; total=0; engine=None
        for vid in packet['development_video_ids']:
            path=root/f'source-{vid}.json'
            if path.exists():
                cached=design.sealed(path)
                if (cached['execution_authorization_fingerprint']!=decision['content_fingerprint']
                        or cached['input_fingerprint']!=packet['content_fingerprint']
                        or cached['source_fingerprint']!=values[vid]['content_fingerprint']):
                    raise ValueError('Source checkpoint binding changed')
                col=cached['collection']
            else:
                if engine is None: engine=encoder.LocalEncoder(model_dir,execution_authorized=True)
                col=collector.discover(values[vid],engine,deadline=deadline)
                save_checkpoint(path,prep.seal(dict(input_fingerprint=packet['content_fingerprint'],execution_authorization_fingerprint=decision['content_fingerprint'],
                    source_fingerprint=values[vid]['content_fingerprint'],collection=col)),packet['resources'])
            total+=len(col['candidates'])
            if total>20000: raise ValueError('Aggregate candidate ceiling exceeded; no truncation')
            entries=[]
            for original in col['G1_candidates']+col['candidates']:
                c=dict(original)
                env=(dict(status='prepared_not_attested',target=c['target'],leading_context=c['leading_context'],trailing_context=c['trailing_context'])
                    if c['capability']=='G1' else c.pop('automatic_envelope'))
                entries.append(dict(candidate=c,automatic_envelope=env))
            inventories.append(dict(video_id=vid,entries=entries,deferrals=col['deferred'],
                budget_proof=col['budget_proof'],search_diagnostics=col['search_diagnostics'],
                G3_displacements=col['G3_displacements'],lattice_diagnostics=col['lattice_diagnostics'],
                resource_counts=col['resource_counts'],descriptors=col['descriptors'],
                G2_primary=col['G2_primary'],G2_role_construction=col['G2_role_construction'],retrieval_trace=col['retrieval_trace'],composition_trace=col['composition_trace']))
        natural=prep.seal(dict(version='collector-retrieval-development-natural-v1.1',input_fingerprint=packet['content_fingerprint'],execution_authorization_fingerprint=decision['content_fingerprint'],
            source_files=packet['source_files'],inventories=inventories,provider_requests=0,confirmation_evidence=False,
            P1_policy='prospective_only_no_historical_reference_rewrite'))
        raw=json.dumps(natural,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        if len(raw.encode())>packet['resources']['inventory_bytes_max']: raise ValueError('Inventory output size ceiling exceeded')
        save_checkpoint(root/'natural-inventory-v1.1.json',natural,packet['resources'])
        # Frozen references are opened only after all natural inventory seals.
        from pastor_transcript_extractor import collector_recall_repair_v4_1 as matching
        from pastor_transcript_extractor import fresh_discovery_confirmation_results as reports
        ref_path=Path(packet['reference_path'])
        if design.file_hash(ref_path)!=packet['reference_sha256']: raise ValueError('Historical references changed')
        refs=design.sealed(ref_path);rows,matched=matching.match_rows(refs,inventories)
        workload={str(c['video_id']):reports.burden(c,values[c['video_id']],matched,[x for x in refs['controls'] if x['video_id']==c['video_id']]) for c in inventories}
        result=prep.seal(dict(version='collector-retrieval-development-results-v1.1',input_fingerprint=packet['content_fingerprint'],execution_authorization_fingerprint=decision['content_fingerprint'],
            verdict='DEVELOPMENT_DIAGNOSTIC_ONLY',G1_assurance='HOLD',
            inventory_sha256=design.file_hash(root/'natural-inventory-v1.1.json'),reference_fingerprint=refs['content_fingerprint'],
            historical_exact_target_diagnostics=rows,workload=workload,
            G3_budget_displacement={str(c['video_id']):c['lattice_diagnostics'] for c in inventories},
            source_preflight=sizes,elapsed_seconds=time.monotonic()-started,provider_requests=0,
            semantic_measurements=None,admitted_items=None,usable_unique_evidence=None,unit_cost=None,
            next_step='Codex audits natural target/envelope supply, G3 saturation, limitations and resources before any fresh confirmation decision. No historical rescoring, new P1 gold or semantic execution.'))
        save_checkpoint(result_path,result,packet['resources'])
        (root/'results-v1.1.md').write_text('# Retrieval development V1.1\n\nDEVELOPMENT_DIAGNOSTIC_ONLY; G1 HOLD; provider requests=0.\n\nJSON separates unchanged historical-target diagnostics from G3 budget displacement. Natural geometry is not usable evidence. Codex source audit is next; no automatic confirmation or inference.\n')
        return result
