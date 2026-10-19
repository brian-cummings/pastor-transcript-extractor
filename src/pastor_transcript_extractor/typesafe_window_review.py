"""Inspect selected windows and prepare a usage-limited TypeSafe bridge offline."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import subprocess

from pastor_transcript_extractor import minute_evidence_membership as membership
from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor import typesafe_window_bridge as bridge
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths

HERE=trace.ROOT/'docs/review-proposals/typesafe-selected-window-bridge-v1'
MANIFEST=HERE/'preparation-manifest-v1.json'
AUTH=HERE/'authorization-v1.json'
CLI_PATH='src/pastor_transcript_extractor/commands/analysis/structure.py'


def selected_windows(base_dir=None):
    membership.verify_baseline(base_dir)
    pointer=trace.read(membership.MANIFEST,True);path=build_paths(base_dir).evaluation/pointer['relative_path']
    if trace.digest(path)!=pointer['sha256']:raise ValueError('Selected window packet changed')
    packet=trace.read(path,True)
    if packet['content_fingerprint']!=pointer['input_fingerprint']:raise ValueError('Selected window identity differs')
    for name,expected in {**packet['input_files'],**packet['implementation_files']}.items():
        if trace.digest(name)==expected:continue
        relative=Path(name).relative_to(trace.ROOT).as_posix()
        if relative!=CLI_PATH:raise ValueError('Selected-window dependency changed: '+name)
        result=subprocess.run(['git','show','e41aeb2:'+relative],cwd=trace.ROOT,check=True,capture_output=True)
        if hashlib.sha256(result.stdout).hexdigest()!=expected:raise ValueError('Historical selected-window CLI differs')
    if (packet['authority_fingerprint']!=trace.read(membership.AUTH,True)['content_fingerprint']
            or packet['membership_scope']!='retired_fixture_preparation_only'
            or packet['provider_requests'] or any(packet[k] for k in ('execution_authorized','production_authorization','measurement_execution','admission_execution'))):
        raise ValueError('Selected window authority/scope differs')
    return packet,path


def prepare(base_dir=None):
    packet,source_path=selected_windows(base_dir);authority=trace.read(AUTH,True)
    if (authority['selected_preparation_fingerprint']!=packet['content_fingerprint'] or authority['status']!='PROVIDER_FREE_TYPESAFE_BRIDGE_AUTHORIZED'
            or any(authority[k] for k in ('provider_execution','Ollama','Jev_execution','collection_projection','new_measurement_semantics'))):raise ValueError('Bridge preparation authority differs')
    unique={}
    for row in packet['cases']:
        if row['status']!='prepared_context_only':continue
        context=packet['contexts'][row['context_fingerprint']];anchor=row['anchor'];family=row['preparation_binding']['family']
        key=(context['content_fingerprint'],anchor['content_fingerprint'])
        value=unique.setdefault(key,dict(context=context,anchor=anchor,families=set(),diagnostic_slots=[]))
        value['families'].add(family);value['diagnostic_slots'].append(row['case_id'])
    old=trace.read(trace.OLD_INPUT,True)
    canonical_sources=[trace.read(info['path'],True) for info in old['source_files'].values()]
    source_map={s['content_fingerprint']:s for s in canonical_sources}
    plans=[];blocked=[];checks=0;hits=0;cache_files={}
    for _,item in sorted(unique.items()):
        scope=bridge.measurement_scope(item['context'],source_map[item['context']['source_fingerprint']])
        if not scope['eligible']:
            blocked.append(dict(context_fingerprint=item['context']['content_fingerprint'],families=sorted(item['families']),diagnostic_slots=item['diagnostic_slots'],reason=scope['reason'],provider_requests=0,semantic_result=None))
            continue
        request=bridge.prepare_selection(item['context'],item['anchor'],item['families']);cache={}
        for key in request['questions']:
            name=bridge.leaf_key(request,key);path=build_paths(base_dir).evaluation/'typesafe-selected-window-bridge-v1/exact-leaves'/f'{name}.json'
            checks+=1
            if path.exists():cache[name]=trace.read(path,True);cache_files[str(path)]=trace.digest(path)
        dispatch=bridge.dispatch_plan(request,cache);hits+=len(dispatch['cached_answers'])
        plans.append(dict(request=request,dispatch=dispatch,diagnostic_slots=item['diagnostic_slots'],
            exact_target_status='NOT_YET_NOMINATED',measurement_requests_prepared=0,usable_evidence=False))
    source_rows=[];old=trace.read(trace.OLD_INPUT,True)
    for vid,info in old['source_files'].items():
        source=trace.read(info['path'],True);extracted=trace.read(source['source_manifest_row']['proposed_json_path']);classification=extracted['classification']
        source_rows.append(dict(video_id=int(vid),persisted_model=classification['model'],persisted_method=classification['method'],
            cache_stats=classification['cache_stats'],eligible_exact_atomic_results=0,
            reason='Persisted sermon-localization answers concern different questions/state/targets; no existing exact nominated target is in this selected-window packet. No global cache scan or provider refill was performed.'))
    questions=sum(len(p['request']['questions']) for p in plans)
    direct=sum(p['request']['phase']=='direct_points' for p in plans)
    g2=sum('G2' in p['request']['metadata']['families'] for p in plans)
    g3=sum('G3' in p['request']['metadata']['families'] for p in plans)
    caps=dict(selected_contexts=len(unique),selected_family_bindings=sum(len(item['families']) for item in unique.values()),
        structurally_blocked_contexts=len(blocked),unique_context_requests=len(plans),family_bindings=g2+g3,G2_bindings=g2,G3_bindings=g3,
        endpoint_questions_first_pass=questions,endpoint_questions_second_pass_max=sum(len(p['request']['questions']) for p in plans if p['request']['phase']!='direct_points'),
        first_pass_cache_hits=hits,first_pass_cache_checks=checks,first_pass_requests_after_exact_reuse=sum(p['dispatch']['requests_needed'] for p in plans),
        second_pass_requests_max=len(plans)-direct,selection_requests_max=sum(p['dispatch']['requests_needed'] for p in plans)+len(plans)-direct,
        measurement_requests_prepared=0,conditional_atomic_measurement_requests_upper_bound=g2+g3,
        unrequested_circumstance_binding_requests_avoided=g3,extra_presence_or_routing_questions=0,
        repeated_sermon_classifications=0,generative_extractor_calls=0,automatic_retries=0)
    pins=[Path(__file__),Path(bridge.__file__),AUTH,trace.ROOT/CLI_PATH,trace.ROOT/'tests/test_typesafe_window_bridge.py']
    report=seal(dict(version='typesafe-selected-window-bridge-v1',status='PROVIDER_FREE_PLAN_EXACT_TARGET_SELECTION_PENDING',
        selected_preparation_fingerprint=packet['content_fingerprint'],selected_preparation_path=str(source_path),
        selected_preparation_sha256=trace.digest(source_path),authorization_fingerprint=authority['content_fingerprint'],
        plans=plans,structural_deferrals=blocked,usage_bounds=caps,persisted_artifact_review=source_rows,cache_files=cache_files,
        implementation_files={str(p):trace.digest(p) for p in pins},
        source_scope='retired fixtures only; no production membership or pastor ownership',
        new_nomination_questions_version=bridge.VERSION,closed_measurement_questions_changed=False,
        upstream_exact_targets_available=0,provider_requests=0,execution_authorized=False,
        execution_command=None,model_token_price_runtime_locks_complete=False,
        limitations=['Position questions are prospective, unvalidated discovery/nomination judgments, not changed G2/G3 measurement contracts.',
            'Only the first complete eligible object per family/context is proposed; additional opportunities are unenumerated and no recall claim follows.',
            'No reference targets or oracle answers are used as nominations or provider choices.',
            'Exact cache leaves must bind full state, questions, phase, model and source/membership scope; old topic/sermon-edge answers cannot substitute.',
            'A null-circumstance atomic G3 plan leaves relation fields unmeasured; existing fixed-panel consumers are not automatically compatible.',
            'The selected contexts are unchanged. Context outside the frozen measurement main-source bound is explicitly blocked, not silently clipped.',
            'No provider executor, token/cost lock, new admission adapter or receipt authority is created.']))
    out=build_paths(base_dir).evaluation/'typesafe-selected-window-bridge-v1'/report['content_fingerprint'];out.mkdir(parents=True,exist_ok=True)
    path=out/'preparation-v1.json';raw=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if path.exists() and path.read_text()!=raw:raise ValueError('Immutable bridge preparation differs')
    path.write_text(raw)
    return report,path


def verify(base_dir=None):
    selected_windows(base_dir);pointer=trace.read(MANIFEST,True)
    path=build_paths(base_dir).evaluation/pointer['relative_path']
    if trace.digest(path)!=pointer['sha256']:raise ValueError('Bridge preparation file differs')
    report=trace.read(path,True)
    if report['content_fingerprint']!=pointer['input_fingerprint']:raise ValueError('Bridge identity differs')
    for name,expected in {**report['implementation_files'],**report['cache_files']}.items():
        if trace.digest(name)!=expected:raise ValueError('Bridge dependency changed: '+name)
    if trace.digest(report['selected_preparation_path'])!=report['selected_preparation_sha256']:raise ValueError('Selected input differs')
    if report['provider_requests'] or report['execution_authorized']:raise ValueError('Bridge scope differs')
    return report,path
