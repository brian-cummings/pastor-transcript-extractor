"""Offline synthetic checks of condition attachment boundaries, never semantic repair."""
from copy import deepcopy
from pathlib import Path

from . import learning_demo as demo
from . import source_context as context
from . import theological_binding as binding
from .pastor_evidence import SourceWindow, EvidenceArtifactStore, EvidencePolicy, digest

VERSION='condition-contract-check-v1'


def cases():
    """Authored neutral controls exercise the contract; no pastor readings or warrants."""
    def make(name,text,proposition=None):
        def span(quote): return dict(source_field='target_text',text=quote)
        prop=span(proposition or text)
        def finding(**values): return dict(**values,evidence=[deepcopy(prop)],rationale='Synthetic control.')
        row=dict(binding_id=name,title='Synthetic attachment control',
            proposition=dict(node_id='p',span=prop,reading=proposition or text),
            voice=finding(kind='preacher',speaker='synthetic speaker',occurrence='actual'),
            adoption=finding(status='own_assertion',basis='own_speech'),polarity=finding(value='affirmed'),
            expression=finding(value='assertion'),epistemic_status=finding(value='not_stated'),conditions=[],
            scope=dict(reading='Only the stated synthetic proposition.',evidence=[deepcopy(prop)]),
            evidence_nodes=[dict(node_id='p',span=deepcopy(prop),role='teaching_statement',voice='preacher',
                adoption='own_assertion',reference_status='Synthetic; no external attribution')],
            qualifications=[],development_relations=[],address_acts=[],unknowns=['No wider claim established.'])
        window=SourceWindow('synthetic-'+name,0,0,digest(text),0,
            (dict(block_id=0,start_seconds=0,end_seconds=60,segment_indexes=[0],target_text=text),),
            'synthetic_contract_control')
        return dict(id=name,window=window,reading=dict(status='proposed',claims=[row],abstentions=[]),
            expected_mechanical_pass=True,intent=''),row,span

    values=[]
    direct,row,span=make('direct_condition','The seed sprouts if the soil stays moist.')
    row['conditions']=[dict(kind='condition',span=span('if the soil stays moist'),rationale='Condition on sprouting.')]
    direct['intent']='Condition attached to the exact proposition is retained.';values.append(direct)
    exception,row,span=make('exception','The gate stays open unless the wind rises.')
    row['conditions']=[dict(kind='exception',span=span('unless the wind rises'),rationale='Exception to remaining open.')]
    exception['intent']='Exception remains distinct from a condition.';values.append(exception)
    concession,row,span=make('concession','The pump works, although it is noisy.')
    row['evidence_nodes'].append(dict(node_id='q',span=span('although it is noisy'),role='qualification',
        voice='preacher',adoption='own_assertion',reference_status='Synthetic'))
    row['qualifications']=[dict(node_id='q',applies_to='p',reading='The working pump is noisy.')]
    concession['intent']='A concession need not become a logical condition.';values.append(concession)
    unrelated,_,_=make('unrelated_conditional','The gate is blue. If it rains, the path gets wet.','The gate is blue.')
    unrelated['intent']='An unrelated if-clause does not condition the gate color.';values.append(unrelated)
    consequence,row,span=make('conditional_consequence',
        'The gardener gives each seed a pot so it can sprout if the soil stays moist.',
        'The gardener gives each seed a pot')
    row['evidence_nodes'].append(dict(node_id='result',span=span('it can sprout if the soil stays moist'),
        role='implication',voice='preacher',adoption='own_assertion',reference_status='Synthetic'))
    row['development_relations']=[dict(relation_id='r',kind='works_out_implication',from_node='p',to_node='result',
        status='supported_observation',rationale='The stated purpose is conditional sprouting.',
        evidence=[span(consequence['window'].blocks[0]['target_text'])],voice='preacher',adoption='own_assertion',
        scope='Moisture conditions sprouting, not giving the pot.',stated_qualifications=[span('if the soil stays moist')])]
    consequence['intent']='A conditional consequence does not automatically condition the initiating proposition.';values.append(consequence)
    dropped=deepcopy(direct);dropped['id']='omitted_condition';dropped['reading']['claims'][0]['conditions']=[]
    dropped['intent']='Negative semantic control: omission is mechanically representable; compilation cannot establish completeness.'
    values.append(dropped)
    misplaced=deepcopy(direct);misplaced['id']='condition_only_in_qualification';row=misplaced['reading']['claims'][0]
    phrase=row['conditions'].pop()['span']
    row['evidence_nodes'].append(dict(node_id='q',span=phrase,role='qualification',voice='preacher',
        adoption='own_assertion',reference_status='Synthetic'))
    row['qualifications']=[dict(node_id='q',applies_to='p',reading='Sprouting depends on moist soil.')]
    misplaced['intent']='Scope/type completeness needs semantic review even when the words survive as a qualification.';values.append(misplaced)
    invalid=deepcopy(concession);invalid['id']='foreign_attachment'
    invalid['reading']['claims'][0]['qualifications'][0]['applies_to']='other-proposition'
    invalid.update(expected_mechanical_pass=False,intent='A qualification attached to another proposition must be rejected.')
    values.append(invalid)
    return values


def check():
    rows=[]
    for case in cases():
        original=deepcopy(case['reading'])
        checked=context.inspect(case['reading'],case['window'],model='synthetic-control',
            prompt_digest=VERSION,raw_response_ref='synthetic-control; no provider response')
        passed=not checked['errors'];checks=dict(expected_mechanical_result=passed==case['expected_mechanical_pass'],
            input_unchanged=case['reading']==original)
        forwarded=None
        if passed:
            observation=checked['observations'][0];compiled=observation['binding']
            spec,_=context.verification(case['window'],checked['observations'])
            forwarded=spec.body['questions'][observation['id']+':qualifications']['instructions']['returned_value']
            checks.update(condition_kind_and_text_preserved=[(c['kind'],c['span']['text']) for c in compiled['conditions']]==
                [(c['kind'],c['span']['text']) for c in original['claims'][0]['conditions']],
                qualification_attachment_preserved=compiled['qualifications']==original['claims'][0]['qualifications'],
                relation_qualifications_preserved=[[q['text'] for q in r['stated_qualifications']] for r in compiled['development_relations']]==
                    [[q['text'] for q in r['stated_qualifications']] for r in original['claims'][0]['development_relations']],
                full_binding_forwarded=compiled==spec.body['state']['items'][0]['binding'],
                conditions_forwarded=forwarded['conditions']==compiled['conditions'],
                qualifications_forwarded=forwarded['qualifications']==compiled['qualifications'],
                not_admitted=not EvidencePolicy().permits(observation)[0])
        rows.append(dict(id=case['id'],intent=case['intent'],source=case['window'].blocks[0]['target_text'],
            proposed_reading=original,mechanical_pass=passed,errors=checked['errors'],checks=checks,
            verifier_field_value=forwarded,semantic_outcome='NOT_ASSESSED_OFFLINE'))
    result=dict(version=VERSION,status='PASS' if all(all(r['checks'].values()) for r in rows) else 'FAIL(component)',
        cases=rows,generation_calls=0,paid_calls=0,production_admission=False,
        semantic_outcome='INCONCLUSIVE: no semantic model accuracy measured',
        conclusion='No structural contract inconsistency demonstrated. Mechanical acceptance cannot establish semantic condition completeness or scope.',
        gap_review=dict(blocked_statement='A mechanically bound point cannot yet be presented as a verified qualified theological observation.',
            inspected_reuse_paths=['Source-reading schema/prompt: distinct conditions, qualifications and relation stated_qualifications.',
                'Shared compiler: literal integrity and exact proposition references, not semantic completeness.',
                'Existing qualification verifier: forwards conditions, qualifications and full binding/source.',
                'Evidence policy: missing required semantic checks withholds observations.'],
            missing_information='Reliable semantic judgment about attachment scope and complete preservation; no dropped field demonstrated in this check.',
            responsible_producer='Existing automatic source reader; existing semantic verifier assesses its proposals.',
            smallest_change='Offline diagnostic and regression controls only; no justified change to runtime parsing or automatic repairs.',
            acceptance='All synthetic boundary/preservation assertions pass; semantic omissions remain unadmitted, not repaired.',
            boundary='No provider execution, historical evidence changes, model variants or production admission.'),
        recommendation='Keep existing contracts and gates. Before another source trial, use a bounded source-independent semantic check to assess condition/qualification attachment; no blanket if-clause repair.',
        code_identity={m.__name__.rsplit('.',1)[-1]:demo.file_hash(Path(m.__file__)) for m in
            (context,context.diagnostics,context.fields,binding)},
        checker_sha256=demo.file_hash(Path(__file__)))
    result['fingerprint']=digest(result)
    return result


def export(base_dir=None):
    result=check();root=demo.build_paths(base_dir).evaluation/'condition-contract-check'/result['fingerprint']
    if root.resolve().is_relative_to(Path(__file__).parents[2].resolve()): raise ValueError('Artifacts must be outside repository')
    EvidenceArtifactStore(root).write_immutable('results.json',result)
    lines=['# Synthetic condition attachment contract check','',result['conclusion'],'',
        '| Control | Mechanical result | Intent |','| --- | --- | --- |']
    lines.extend('| '+r['id']+' | '+('PASS' if r['mechanical_pass'] else 'REJECTED')+' | '+r['intent']+' |' for r in result['cases'])
    lines.extend(['','The PASS is for contract assertions, not extraction accuracy. Deliberately omitted or mistyped semantic conditions can pass mechanical checks. Both condition and qualification values reach the existing verifier unchanged.',
        '',result['recommendation'],'','No provider calls, pastor inputs, threshold changes or production admission.'])
    (root/'review.md').write_text('\n'.join(lines)+'\n')
    return {k:v for k,v in result.items() if k!='cases'}|dict(case_count=len(result['cases']),results=str(root/'results.json'),review=str(root/'review.md'))
