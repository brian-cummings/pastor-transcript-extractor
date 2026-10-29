"""Freeze four existing regression cases, never expected semantic answers."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from . import evidence_requests as requests
from .pastor_evidence import digest
from .deepinfra_streaming import JSONWhitespaceDetector,WhitespaceLoop

POLICY='first-lexical-per-demonstrated-contract-category-v1'
CATEGORIES=('whitespace_recovery','citation_binding','qualification_preservation','unresolved_path')


def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_packet(run_dir):
    path=Path(run_dir).resolve()/'input.json';packet=json.loads(path.read_text())
    if packet['input_fingerprint']!=digest({k:v for k,v in packet.items() if k!='input_fingerprint'}):raise ValueError('Prior input fingerprint differs')
    return packet


def select(run_dir,plan,profile_path):
    root=Path(run_dir).resolve();original=source_packet(root);path=root/'results.json';report=json.loads(path.read_text())
    if report['input_fingerprint']!=original['input_fingerprint']:raise ValueError('Prior result belongs to another input')
    if original['profile_input']['sha256']!=file_hash(profile_path):raise ValueError('Validation requires the identical assembled profile')
    prior={i['claim_id']:i for i in original['plan']['items']};tasks={t['claim_id']:t for t in original['tasks']};rows={r['claim_id']:r for r in report['results']}
    current={i['claim_id']:i for i in plan['items']};files={str(root/'input.json'):file_hash(root/'input.json'),str(path):file_hash(path)}
    candidates={name:[] for name in CATEGORIES};artifacts={}
    for cid,row in sorted(rows.items()):
        if cid not in tasks or not row.get('receipt'):continue
        receipt_path=Path(row['receipt']);spec=requests.RequestSpec(**tasks[cid]['request'])
        if receipt_path.name!=spec.fingerprint+'.json':raise ValueError('Prior receipt identity differs')
        receipt=json.loads(receipt_path.read_text());wire_path=receipt_path.parent.parent/'wire-responses'/receipt_path.name
        raw_wire=json.loads(wire_path.read_text())
        if receipt['request']!=asdict(spec) or receipt['response_digest']!=digest(receipt['response']) or receipt['wire_response_digest']!=digest(raw_wire):raise ValueError('Prior receipt or wire digest differs')
        raw=json.loads(raw_wire['text']);response=receipt.get('response');answer=(row.get('judgment') or {}).get('answer')
        if response is not None:
            requests.validate_response(spec,response)
            if not receipt['halt'] and requests.decode_response(spec,requests.WireResponse(**raw_wire))!=response:raise ValueError('Prior decoded response differs')
            if answer is None:
                try:answer=requests.strict_json(response['output'])
                except ValueError:pass
        artifacts[cid]=(receipt_path,wire_path)
        if (row.get('failure') or '').startswith('Incomplete DeepInfra response'):
            try:JSONWhitespaceDetector(256).feed(raw['choices'][0]['message']['content'])
            except WhitespaceLoop:candidates['whitespace_recovery'].append(cid)
        if answer and row['status']=='component_failure' and isinstance(answer.get('evidence'),list):
            sources=prior[cid]['case']['sources']
            if any(isinstance(c,dict) and c.get('passage_id') in sources and c.get('field') in sources[c['passage_id']]['fields'] and (c.get('start_unit') not in {u['id'] for u in sources[c['passage_id']]['fields'][c['field']]} or c.get('end_unit') not in {u['id'] for u in sources[c['passage_id']]['fields'][c['field']]}) for c in answer['evidence']):candidates['citation_binding'].append(cid)
        if (row['status']=='complete' and answer and answer.get('judgment')=='supported' and answer.get('qualifications')
            and prior[cid]['case']['state']['candidate']['analytical_basis']=='source_reviewed_style_example'):candidates['qualification_preservation'].append(cid)
        if answer and answer.get('judgment')=='unresolved':candidates['unresolved_path'].append(cid)
    chosen=[]
    for category in CATEGORIES:
        eligible=sorted(set(candidates[category])-{c['claim_id'] for c in chosen})
        if not eligible:raise ValueError('No saved case for validation category '+category)
        cid=eligible[0]
        if cid not in current or any(current[cid][k]!=prior[cid][k] for k in ('statement','scope','case')):raise ValueError('Selected existing evidence changed: '+cid)
        chosen.append(dict(category=category,claim_id=cid,prior_status=rows[cid]['status'],prior_failure=rows[cid].get('failure')))
        for artifact in artifacts[cid]:files[str(artifact)]=file_hash(artifact)
    selected=deepcopy(plan);ids={c['claim_id'] for c in chosen};selected['items']=[i for i in selected['items'] if i['claim_id'] in ids]
    selected['selection']=dict(mode='bounded_contract_validation',assembled_total=len(plan['items']),policy=POLICY,selected=chosen)
    lineage=dict(source_run=str(root),preserved_files=files,selection=chosen,policy=POLICY,
        limitation='Four previously exposed real-profile cases selected by mechanical failure category, not an independent accuracy benchmark. No expected semantic judgments, corrected wording or authored warrants enter requests. Unselected dependencies remain unevaluated; no full-profile advancement.')
    return selected,lineage
