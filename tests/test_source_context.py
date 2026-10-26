from copy import deepcopy
from dataclasses import asdict,replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor import source_context as c
from pastor_transcript_extractor import binding_retry as b
from pastor_transcript_extractor import evidence_requests as r
from pastor_transcript_extractor import learning_demo_feedback as feedback
from pastor_transcript_extractor.pastor_evidence import SourceWindow
from test_binding_retry import specimen
from test_learning_demo_correction import wire_response


def fixture():
    value,spec,valid,_=specimen()
    valid['abstentions']=[]
    window=SourceWindow(**value['window'])
    spec=replace(spec,body=deepcopy(spec.body))
    spec.body['messages'][0]['content']+='\n'+c.PROMPT
    spec.body['response_format']['json_schema']['schema']=c.schema()
    return window,spec,valid


def abstain(reading,index=0,missing='continuation'):
    result=deepcopy(reading);claim=result['claims'].pop(index)
    result['abstentions'].append(dict(binding_id=claim['binding_id'],span=claim['proposition']['span'],
        missing_components=[missing],rationale='The declared target lacks consequential context.'))
    result['status']='needs_more_context'
    return result


def inspect(reading,window):
    return c.inspect(reading,window,model='synthetic',prompt_digest='synthetic',raw_response_ref='synthetic-receipt')


class SourceContextTests(unittest.TestCase):
    def test_complete_bindings_remain_identical_and_abstentions_never_compile(self):
        window,spec,valid=fixture();old=deepcopy(valid);del old['abstentions']
        original=b.diagnostics.inspect(old,b.context.thinking.schema(),window,
            model='synthetic',prompt_digest='synthetic',raw_response_ref='synthetic-receipt')
        checked=inspect(valid,window)
        self.assertEqual(checked['observations'],original['observations'])
        for missing in ('continuation','referent','condition','attribution','scope'):
            mixed=abstain(valid,missing=missing);saved=deepcopy(mixed)
            result=inspect(mixed,window)
            self.assertEqual(result['errors'],[]);self.assertEqual(len(result['observations']),1)
            self.assertEqual(len(result['abstentions']),1);self.assertEqual(mixed,saved)
            self.assertEqual(result['abstentions'][0]['origin'],'machine_generated')
            self.assertEqual(result['abstentions'][0]['raw_response_ref'],'synthetic-receipt')
            self.assertIn('start',result['abstentions'][0]['record']['span'])
            self.assertTrue(result['abstentions'][0]['source_refs'])

    def test_fragment_is_retained_without_an_invented_proposition(self):
        window,_,valid=fixture();block=deepcopy(window.blocks[0])
        block['target_text']='If the gardener finds'
        window=replace(window,blocks=(block,))
        value=dict(status='needs_more_context',claims=[],abstentions=[dict(binding_id='fragment',
            span=dict(source_field='target_text',text=block['target_text']),missing_components=['continuation'],
            rationale='The condition and consequent are unavailable in the declared source.')])
        checked=inspect(value,window)
        self.assertEqual(checked['errors'],[]);self.assertEqual(checked['observations'],[])
        self.assertNotIn('proposition',checked['abstentions'][0]['record'])
        self.assertNotIn('polarity',checked['abstentions'][0]['record'])

    def test_complete_conditional_across_blocks_and_punctuation_do_not_trigger_code_abstention(self):
        # Completeness is a reader/verifier decision, never a punctuation heuristic.
        window,_,valid=fixture()
        for suffix in ('','?','...',' If the gardener finds a seed, she plants it.'):
            block=deepcopy(window.blocks[0]);block['target_text']+=suffix
            changed=replace(window,blocks=(block,))
            checked=inspect(valid,changed)
            self.assertEqual(checked['errors'],[]);self.assertEqual(checked['abstentions'],[])
        text=window.blocks[0]['target_text'];cut=text.index(' ')
        blocks=({**window.blocks[0],'target_text':text[:cut]},
                {**window.blocks[0],'block_id':9999,'target_text':text[cut+1:]})
        split=replace(window,blocks=blocks)
        value=abstain(abstain(valid))
        value['abstentions'][0]['span']['text']=split.target()[0]['target_text']
        checked=inspect(value,split)
        self.assertEqual(checked['errors'],[])
        self.assertEqual(len(checked['abstentions'][0]['source_refs']),2)

    def test_invalid_abstention_never_admits_partial_inventory(self):
        window,_,valid=fixture()
        for kind in ('literal','identity','missing','rationale','status','foreign','duplicate-component'):
            with self.subTest(kind=kind):
                value=abstain(valid);row=value['abstentions'][0]
                if kind=='literal': row['span']['text']='absent words'
                if kind=='identity': row['binding_id']=value['claims'][0]['binding_id']
                if kind=='missing': row['missing_components']=[]
                if kind=='rationale': row['rationale']=' '
                if kind=='status': value['status']='proposed'
                if kind=='foreign': row['proposition']='invented completion'
                if kind=='duplicate-component': row['missing_components']*=2
                result=inspect(value,window)
                self.assertTrue(result['errors']);self.assertEqual(result['observations'],[])
                self.assertEqual(result['abstentions'],[])

    def test_context_is_same_batch_separate_gate_and_missing_judgment_fails_closed(self):
        window,_,valid=fixture();checked=inspect(valid,window)
        old,_=c.fields.verification(window,checked['observations'])
        spec,candidates=c.verification(window,checked['observations'])
        self.assertEqual(spec.body['state'],old.body['state'])
        self.assertEqual({k:v for k,v in spec.body['questions'].items() if k in old.body['questions']},old.body['questions'])
        answers={k:dict(type='noul',noul=.99) for k in spec.body['questions']}
        for k in answers:
            if k.endswith(':context_sufficiency'): answers[k]['noul']=.5
        judgment=feedback.judgments(dict(output=answers),spec,candidates)
        outcome=c.eligibility(checked,judgment)
        self.assertEqual(outcome['eligible_observation_ids'],[])
        self.assertTrue(all(x['unresolved_fields']==['context_sufficiency'] for x in outcome['withheld']))
        self.assertEqual(len(c.review_scores(spec,judgment)),8)
        self.assertEqual(c.eligibility(checked,None)['eligible_observation_ids'],[])
        for findings in judgment['findings'].values(): findings['context_sufficiency'].update(probability=.99,resolved=True)
        self.assertEqual(len(c.eligibility(checked,judgment)['eligible_observation_ids']),2)
        self.assertFalse(outcome['production_admission'])

    def test_dedicated_conditions_question_reuses_meaning_state_and_criteria(self):
        window,_,valid=fixture();checked=inspect(valid,window)
        spec,candidates=c.verification(window,checked['observations'])
        full=c.contract.verification_request('source_verification',spec.body['state'],spec.body['state']['items'],
            spec.source_identity,source=True)
        for item in spec.body['state']['items']:
            key=item['id']+':conditions';question=spec.body['questions'][key]
            self.assertEqual(question['criteria'],full.body['questions'][key]['criteria'])
            self.assertEqual(question['instructions']['check'],c.contract.CHECK_MEANINGS['conditions'])
            self.assertEqual(question['instructions']['returned_value'],item['binding']['conditions'])
            self.assertEqual(question['instructions']['attachment_rule'],c.ATTACHMENT_RULE)
        self.assertEqual(spec.version,c.VERSION);self.assertEqual(spec.namespace,c.VERSION)
        self.assertEqual(c.fields.PASS,.90);self.assertEqual(c.fields.FAIL,.10)
        spec.preflight()

    def test_old_three_field_verdicts_and_uncertain_conditions_do_not_satisfy_new_gate(self):
        window,_,valid=fixture();checked=inspect(valid,window)
        spec,candidates=c.verification(window,checked['observations'])
        answers={k:dict(type='noul',noul=.99) for k in spec.body['questions']}
        judgment=feedback.judgments(dict(output=answers),spec,candidates)
        for mode in ('missing','uncertain','false'):
            prior=deepcopy(judgment)
            for finding in prior['findings'].values():
                if mode=='missing': finding.pop('conditions')
                else: finding['conditions'].update(probability=.5 if mode=='uncertain' else .05,resolved=False)
            outcome=c.eligibility(checked,prior)
            self.assertEqual(outcome['eligible_observation_ids'],[])
            self.assertTrue(all(row['unresolved_fields']==['conditions'] for row in outcome['withheld']))
        self.assertEqual(len(c.eligibility(checked,judgment)['eligible_observation_ids']),2)
        self.assertFalse(c.eligibility(checked,judgment)['production_admission'])

    def test_attachment_rule_is_required_without_a_schema_or_compiler_change(self):
        window,spec,valid=fixture();before=deepcopy(valid)
        c.validate_request(spec)
        packet=c.contract_packet()
        self.assertIn(c.ATTACHMENT_RULE,packet['reader_prompt'])
        self.assertEqual(packet['fields'],['qualifications','polarity','context_sufficiency','conditions'])
        self.assertEqual(packet['version'],'qualified-source-context-attachment-v2')
        self.assertEqual(inspect(valid,window)['errors'],[]);self.assertEqual(valid,before)
        spec.body['messages'][0]['content']=spec.body['messages'][0]['content'].replace(c.ATTACHMENT_RULE,'')
        with self.assertRaisesRegex(ValueError,'explicit reader'): c.validate_request(spec)

    def test_old_contract_version_cannot_silently_run_under_new_attachment_policy(self):
        window,spec,valid=fixture()
        with TemporaryDirectory() as directory:
            result=b.run_case(dict(input_fingerprint='historical-version-control',schema=c.schema(),
                policy=dict(source_context_version='qualified-source-context-v1')),
                dict(case_id='synthetic',window=asdict(window),request=asdict(spec)),Path(directory),
                lambda s:self.fail('old policy must stop before send'),lambda s:self.fail('no verifier'))
            self.assertIn('Unsupported source context contract version',result['halt'])
            self.assertEqual(result['status'],'FAIL(component)')

    def test_uncertain_conditions_enter_same_correction_loop_and_are_rechecked(self):
        window,spec,valid=fixture();calls=[];verifiers=[]
        def flash(request): calls.append(request);return wire_response(request,json.dumps(valid))
        def typesafe(request):
            verifiers.append(request)
            return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),
                output={k:dict(type='noul',noul=.05 if len(verifiers)==1 and k.endswith(':conditions') else .99)
                    for k in request.body['questions']})
        with TemporaryDirectory() as directory:
            result=b.run_case(dict(input_fingerprint='synthetic',schema=c.schema(),policy=dict(source_context_version=c.VERSION)),
                dict(case_id='synthetic',window=asdict(window),request=asdict(spec)),Path(directory),flash,typesafe)
            self.assertIsNone(result['halt']);self.assertEqual(len(calls),2);self.assertEqual(len(verifiers),2)
            self.assertIn('"field":"conditions"',calls[1].body['messages'][-1]['content'])
            self.assertTrue(all(k['unresolved_fields']==['conditions'] for k in result['context_eligibility']['initial']['withheld']))
            comparisons=[x for x in result['revision']['field_comparisons'] if x['field']=='conditions']
            self.assertEqual(len(comparisons),2)
            self.assertTrue(all(x['previous_probability_correct']==.05 and x['probability_correct']==.99 for x in comparisons))
            self.assertFalse(result['production_admission'])

    def test_abstention_transition_preserves_coverage_and_reports_changes(self):
        _,_,valid=fixture();mixed=abstain(valid)
        changes=c.changes(json.dumps(valid),mixed)
        self.assertEqual(changes[0]['from_collection'],'claims');self.assertEqual(changes[0]['to_collection'],'abstentions')
        mixed['abstentions']=[]
        with self.assertRaisesRegex(ValueError,'identity/coverage'): c.changes(valid,mixed)

    def test_binding_retry_can_explicitly_abstain_without_dropping_identity(self):
        window,spec,valid=fixture();bad=deepcopy(valid);bad['claims'][0]['proposition']['span']['text']='missing'
        calls=[]
        def send(s): calls.append(s);return wire_response(s,json.dumps(bad if len(calls)==1 else abstain(valid)))
        with TemporaryDirectory() as directory:
            result=b.read(spec,window,c.schema(),r.ReceiptStore(Path(directory)),send)
            self.assertEqual(len(calls),2);self.assertEqual(result['validation']['errors'],[])
            self.assertEqual(len(result['validation']['abstentions']),1)

    def test_context_review_to_all_abstentions_skips_empty_verifier_call(self):
        window,spec,valid=fixture();calls=[];verifications=[];messages=[]
        def flash(s): calls.append(s);return wire_response(s,json.dumps(valid if len(calls)==1 else abstain(abstain(valid))))
        def typesafe(s):
            verifications.append(s)
            return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),
                output={k:dict(type='noul',noul=.5 if k.endswith(':context_sufficiency') else .99) for k in s.body['questions']})
        packet=dict(input_fingerprint='synthetic',schema=c.schema(),policy=dict(source_context_version=c.VERSION))
        case=dict(case_id='synthetic',window=asdict(window),request=asdict(spec))
        with TemporaryDirectory() as directory:
            result=b.run_case(packet,case,Path(directory),flash,typesafe,progress=messages.append)
            self.assertIsNone(result['halt']);self.assertEqual(len(calls),2);self.assertEqual(len(verifications),1)
            self.assertEqual(result['revision']['mechanical']['observations'],[])
            self.assertEqual(len(result['context_eligibility']['final']['abstained_binding_ids']),2)
            self.assertEqual(result['context_eligibility']['final']['eligible_observation_ids'],[])
            self.assertIn('move its existing binding ID',calls[1].body['messages'][-1]['content'])

    def test_all_abstentions_do_not_retry_or_call_typesafe(self):
        window,spec,valid=fixture();calls=[]
        with TemporaryDirectory() as directory:
            def flash(s): calls.append(s);return wire_response(s,json.dumps(abstain(abstain(valid))))
            result=b.run_case(dict(input_fingerprint='synthetic',schema=c.schema(),policy=dict(source_context_version=c.VERSION)),
                dict(case_id='synthetic',window=asdict(window),request=asdict(spec)),Path(directory),
                flash,lambda s:self.fail('no claims to verify'))
            self.assertIsNone(result['halt']);self.assertEqual(len(calls),1);self.assertEqual(result['initial_binding_retries'],0)

    def test_contract_mismatch_stops_before_send(self):
        window,spec,valid=fixture();spec.body['messages'][0]['content']='old reader instructions'
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'explicit reader'):
                b.read(spec,window,c.schema(),r.ReceiptStore(Path(directory)),lambda s:self.fail('no send'))

    def test_historical_schema_answer_is_not_silently_upgraded(self):
        window,_,valid=fixture();del valid['abstentions']
        checked=inspect(valid,window)
        self.assertTrue(any(e['path']=='$.abstentions' for e in checked['errors']))
        self.assertEqual(checked['observations'],[])

    def test_context_is_rechecked_and_uncertainty_withholds_complete_claims(self):
        window,spec,valid=fixture();calls=[];verifications=[]
        def flash(s): calls.append(s);return wire_response(s,json.dumps(abstain(valid)))
        def typesafe(s):
            verifications.append(s)
            return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),
                output={k:dict(type='noul',noul=.5 if k.endswith(':context_sufficiency') else .99) for k in s.body['questions']})
        with TemporaryDirectory() as directory:
            result=b.run_case(dict(input_fingerprint='synthetic',schema=c.schema(),policy=dict(source_context_version=c.VERSION)),
                dict(case_id='synthetic',window=asdict(window),request=asdict(spec)),Path(directory),flash,typesafe)
            self.assertIsNone(result['halt']);self.assertEqual(len(calls),2);self.assertEqual(len(verifications),2)
            self.assertTrue(all(sum(k.endswith(':context_sufficiency') for k in s.body['questions'])==1 for s in verifications))
            final=result['context_eligibility']['final']
            self.assertEqual(final['eligible_observation_ids'],[])
            self.assertEqual(final['withheld'][0]['unresolved_fields'],['context_sufficiency'])
            self.assertEqual(len(final['abstained_binding_ids']),1)

    def test_offline_cli_exports_contract_outside_repository(self):
        with TemporaryDirectory() as directory:
            result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','source-context-contract','--base-dir',directory,'--json'])
            self.assertEqual(result.exit_code,0,result.output)
            result=json.loads(result.output);self.assertEqual(result['paid_calls'],0)
            saved=json.loads(Path(result['contract']).read_text())
            self.assertEqual(saved['schema'],c.schema());self.assertEqual(saved['version'],c.VERSION)
            self.assertNotIn('cases',saved)
