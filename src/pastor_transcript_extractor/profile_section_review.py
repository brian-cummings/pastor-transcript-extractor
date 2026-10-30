"""Offline review packet for unchanged source generations; never runtime evidence."""
from pathlib import Path
import json
from .profile_support_validation import file_hash
from .pastor_evidence import EvidenceArtifactStore as Store, digest


def prepare(path):
    path=Path(path);p=json.loads(path.read_text());root=path.parent
    if p['input_fingerprint']!=digest({k:v for k,v in p.items() if k!='input_fingerprint'}):
        raise ValueError('Section freeze changed')
    cases=[]
    for task in p['tasks']:
        result_path=root/'sources'/task['id']/'result.json'
        result=json.loads(result_path.read_text());generations=[]
        for n,round_ in enumerate(result['rounds'],1):
            receipt_path=Path(round_['receipt']);receipt=json.loads(receipt_path.read_text())
            if receipt['halt'] or receipt['response_digest']!=digest(receipt['response']):
                raise ValueError('Source generation receipt changed')
            output=receipt['response']['output'];output=json.loads(output) if isinstance(output,str) else output
            generations.append(dict(round=n,receipt=dict(path=str(receipt_path),sha256=file_hash(receipt_path)),
                output=output,mechanical_errors=round_['errors']))
        observations={o['binding']['binding_id']:o for o in result['observations']}
        candidates=[]
        for item in generations[-1]['output']['claims']:
            o=observations.get(item['binding_id']);checks=({**o['field_judgments'],**o['response_growth']['checks']} if o else {})
            candidates.append(dict(id=task['id']+':'+item['binding_id'],binding_id=item['binding_id'],
                statement=item['response_growth']['reader_statement'],original_binding=item,
                compiled_observation_id=o['id'] if o else None,checks=checks,
                eligibility=o['section_eligibility'] if o else dict(eligible=False,reason='mechanical_validation_failed')))
        source=next(s for s in p['source_identity'] if s['video_id']==task['window']['video_id'])
        cases.append(dict(id=task['id'],window=task['window'],source=source,result=dict(path=str(result_path),sha256=file_hash(result_path)),
            source_status=result['source_status'],execution_status=result['status'],generations=generations,candidates=candidates,
            verification_receipt=result['verification_receipt']))
    packet=dict(version='profile-section-source-review-v1',plan=dict(path=str(path),sha256=file_hash(path)),cases=cases,
        scope='All final candidates and all original/corrective generations in the six frozen windows. Exposed development material; not an untouched holdout.',
        authority='Evaluation-only assistant review packet; never an upstream observation, runtime warrant, semantic approval or production admission.',
        coverage=dict(windows=len(cases),blocks=sum(len(c['window']['blocks']) for c in cases),final_candidates=sum(len(c['candidates']) for c in cases),
            eligible=sum(i['eligibility']['eligible'] for c in cases for i in c['candidates']),
            saturated_windows=[c['id'] for c in cases if c['source_status']=='saturated']))
    packet['fingerprint']=digest(packet);out=root/'source-review';Store(out).write_immutable('packet.json',packet)
    lines=['# Original source output review','',packet['scope'],'',packet['authority'],'',
        'Scores retain their frozen diagnostic meaning; they are not calibrated probabilities of semantic truth. No wording below is repaired.','']
    for case in cases:
        lines.extend(['## '+case['id'],'',f"Execution: {case['execution_status']}; source coverage status: {case['source_status']}.",''])
        for candidate in case['candidates']:
            lines.extend(['### '+candidate['id'],'',candidate['statement'],'',
                'Eligibility: '+json.dumps(candidate['eligibility']),
                'Unresolved field checks: '+json.dumps({k:v for k,v in candidate['checks'].items() if not v['resolved']}),''])
        if len(case['generations'])>1:
            lines.extend(['### Initial wording before mechanical correction',''])
            for item in case['generations'][0]['output']['claims']:
                lines.extend([item['binding_id']+': '+item['response_growth']['reader_statement'],''])
        lines.extend(['### Complete frozen source',''])
        for block in case['window']['blocks']:
            lines.extend([f"Block {block['block_id']} · {block['start_seconds']}–{block['end_seconds']} seconds",'',block['target_text'],''])
    (out/'packet.md').write_text('\n'.join(lines)+'\n')
    return dict(packet=str(out/'packet.json'),review=str(out/'packet.md'),coverage=packet['coverage'],provider_calls=0)
