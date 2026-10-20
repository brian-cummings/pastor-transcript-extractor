"""Provider-free check of existing source-unit ranges; no new segmentation."""
from __future__ import annotations
import json
from pathlib import Path
from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor import typesafe_window_review as windows
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths

VERSION='existing-source-unit-span-readiness-v1'


def inventory(source,context):
    if seal(source)!=source or seal(context)!=context or context['source_fingerprint']!=source['content_fingerprint']:
        raise ValueError('Foreign source/context')
    if source['text'][context['start']:context['end']]!=context['text']:raise ValueError('Context text differs')
    result=[];partial=[];previous=-1;ids=set()
    for unit in source['units']:
        if unit['unit_id'] in ids or unit['start']<previous or source['text'][unit['start']:unit['end']]!=unit['text']:
            raise ValueError('Invalid canonical unit inventory')
        previous=unit['end'];ids.add(unit['unit_id'])
        if unit['end']<=context['start'] or unit['start']>=context['end']:continue
        if context['start']<=unit['start']<unit['end']<=context['end']:result.append(unit)
        else:partial.append(unit['unit_id'])
    return dict(units=result,excluded_partial_unit_ids=partial,coordinates='unchanged canonical Unicode codepoints',
        context_fingerprint=context['content_fingerprint'],usable_evidence=False)


def cover(source,context,span):
    if type(span['start']) is not int or type(span['end']) is not int or not 0<=span['start']<span['end']<=len(source['text']) or source['text'][span['start']:span['end']]!=span['text']:
        raise ValueError('Foreign reference span')
    if not context['start']<=span['start']<span['end']<=context['end']:
        return dict(status='reference_outside_selected_context',reference=span)
    units=[u for u in source['units'] if u['start']<span['end'] and span['start']<u['end']]
    if not units:raise ValueError('Reference has no source unit')
    a,b=units[0]['start'],units[-1]['end']
    if a<context['start'] or b>context['end']:
        return dict(status='whole_cover_requires_outside_context',reference=span,unit_ids=[u['unit_id'] for u in units])
    return dict(status='exact' if (a,b)==(span['start'],span['end']) else 'whole_unit_expansion',
        reference=span,unit_ids=[u['unit_id'] for u in units],start=a,end=b,text=source['text'][a:b],
        extra_characters=(b-a)-(span['end']-span['start']),semantic_compatibility='requires_source_review')


def check_roles(source,context,family,roles):
    required=('left','right') if family=='G2' else ('utterance',)
    if family not in ('G2','G3') or set(roles)!=set(required):raise ValueError('Unsupported role inventory')
    covered={name:cover(source,context,roles[name]) for name in required}
    available=all('start' in c for c in covered.values())
    overlap=available and family=='G2' and covered['left']['start']<covered['right']['end'] and covered['right']['start']<covered['left']['end']
    return dict(family=family,covers=covered,whole_units_available=available,
        directed_roles_overlap=bool(overlap),all_roles_exact=all(c['status']=='exact' for c in covered.values()),
        inference_authorized=False,usable_evidence=False)


def prepare(base_dir=None):
    selected,path=windows.selected_windows(base_dir)
    spec=trace.read(trace.SPEC,True);old=trace.read(trace.OLD_INPUT,True)
    sources={};inputs={str(path):trace.digest(path),str(trace.SPEC):trace.digest(trace.SPEC)}
    for vid,info in old['source_files'].items():
        if trace.digest(info['path'])!=info['sha256']:raise ValueError('Canonical source changed')
        sources[int(vid)]=trace.read(info['path'],True);inputs[info['path']]=info['sha256']
    contexts={}
    for row in selected['cases']:
        context=selected['contexts'][row['context_fingerprint']]
        contexts[context['content_fingerprint']]=inventory(sources[row['video_id']],context)
    cases=[]
    for reference in spec['cases']:
        if reference['kind']!='adequate':continue
        row=next(r for r in selected['cases'] if r['case_id']==reference['case_id'])
        context=selected['contexts'][row['context_fingerprint']]
        geometry=check_roles(sources[row['video_id']],context,'G2' if reference['route']=='G2' else 'G3',reference['oracle']['focal_roles'])
        cases.append(dict(case_id=reference['case_id'],route=reference['route'],context_fingerprint=context['content_fingerprint'],**geometry))
    report=seal(dict(version=VERSION,status='STOP_BEFORE_INFERENCE_EXISTING_UNITS_TOO_COARSE',
        selected_preparation_fingerprint=selected['content_fingerprint'],input_files=inputs,contexts=contexts,cases=cases,
        counts=dict(selected_contexts=len(contexts),adequate_diagnostic_cases=len(cases),
            exact_case_geometries=sum(c['all_roles_exact'] for c in cases),
            G2_same_unit_role_collisions=sum(c['directed_roles_overlap'] for c in cases)),
        decision_basis='Two definite G2 opportunities cannot have distinct nonoverlapping targets using whole existing units; source review also finds multiple speech/act frames within whole G3 units. Do not infer readiness from span containment.',
        limitations=['Reference-assisted representation diagnostic only; no discovery/retrieval credit.','Nonexact text alone does not prove incompatibility. The overlapping G2 roles and source-reviewed mixed G3 targets are the substantive blockers.','No source units split, clipped, merged or regenerated; no new questions, requests or runtime prepared.','The 12 prior adequate locators are reused development diagnostics, not fresh confirmation or a transferred numeric pass gate.'],
        implementation_files={str(Path(__file__)):trace.digest(__file__)},provider_requests=0,
        inference_packet_prepared=False,measurement_admission_executed=False,contracts_changed=False,usable_evidence=False))
    out=build_paths(base_dir).evaluation/VERSION/report['content_fingerprint']/'readiness-v1.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists():
        if trace.read(out,True)!=report:raise ValueError('Immutable source-unit review differs')
    else:out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report,out
