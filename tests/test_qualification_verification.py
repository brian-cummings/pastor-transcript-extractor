from dataclasses import asdict
from itertools import product
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import qualification_verification as q
from pastor_transcript_extractor import reference_field_validation as v
from pastor_transcript_extractor import source_context
from pastor_transcript_extractor.cli import app


class QualificationContractTests(unittest.TestCase):
    def test_tristate_composition_never_repairs_unknown(self):
        for a,b in product((True,False,None),repeat=2):
            expected=False if a is False or b is False else True if a is True and b is True else None
            self.assertIs(q.combine(a,b),expected)
        for bad in (0,1,.99,'true',[]):
            with self.assertRaises(ValueError):q.combine(bad,True)

    def test_empty_list_support_identity_never_implies_completeness(self):
        cases=v.boundary_controls();spec,index,fixed=q.request(cases,source_identity={'fixture':'neutral'})
        self.assertEqual(len(index),7)
        self.assertEqual(set(fixed),{'0','2','3'})
        for i in fixed:
            self.assertIn('q'+i+'_complete',index)
            self.assertNotIn('q'+i+'_supported',index)
            self.assertTrue(fixed[i]['supported'])
        self.assertNotIn('expected',v.requests.wire(spec.body))
        self.assertTrue(all('voice/adoption' in x['instructions'] for x in spec.body['questions'].values()))
        self.assertTrue(all('even if already in the proposition' in x['instructions'] for x in spec.body['questions'].values()))

    def test_unrelated_proposals_do_not_change_request_or_mutate_input(self):
        from copy import deepcopy
        cases=v.boundary_controls();original=deepcopy(cases)
        before=q.request(cases,source_identity={})[0]
        for row in cases:row['adoption']='rejected';row['voice']='preacher'
        after=q.request(cases,source_identity={})[0]
        self.assertEqual(before,after)
        self.assertNotIn('adoption',before.body['state']['items'][0])
        self.assertEqual(original,v.boundary_controls())
        # Same target/source, changed list must change cache identity.
        cases[2]['qualifications']=deepcopy(cases[1]['qualifications'])
        self.assertNotEqual(q.request(cases,source_identity={})[0].fingerprint,before.fingerprint)

    def test_source_producer_uses_same_contract_without_admitting_or_rewriting(self):
        from copy import deepcopy
        window=v.evidence.SourceWindow('synthetic',1,2,'synthetic',1,(dict(block_id=1,target_text='The elevator is working.',start_seconds=0,end_seconds=60,segment_indexes=[0]),),'synthetic')
        observations=[dict(binding=dict(proposition=dict(reading='The elevator is working.'),qualifications=[]))];old=deepcopy(observations)
        spec,index,fixed=source_context.qualification_verification(window,observations)
        self.assertEqual(spec.namespace,q.VERSION);self.assertEqual(spec.body['state']['sources']['w0'],'The elevator is working.')
        self.assertEqual(observations,old);self.assertTrue(fixed['0']['supported'])
        self.assertEqual(len(index),1)

    def test_qwen_contract_composes_components_and_preserves_failure(self):
        from test_reference_field_validation import QwenInstantTests
        trial=v.boundary_trial();spec=v.qwen_request(trial)
        packet=dict(request=asdict(spec),native_trial=trial,qualification_contract_version=q.VERSION)
        wire=QwenInstantTests().wire(spec,trial)
        result=v.qwen_assess(packet,v.requests.decode_response(spec,wire))
        self.assertEqual(result['summary']['correct'],7)
        self.assertEqual(result['case_summary'],dict(total=5,correct=5,wrong=0,withheld=0))
        self.assertEqual([r['verdict'] for r in result['cases']],[True,True,False,False,False])
        # Passing completeness cannot conceal an unsupported extra entry.
        self.assertEqual(result['cases'][4]['components'],dict(complete=True,supported=False))
        self.assertFalse(result['cases'][4]['verdict'])
        response=v.requests.decode_response(spec,wire)
        import json
        values=json.loads(response['output']);values['q1_supported']['verdict']=None;response['output']=json.dumps(values)
        result=v.qwen_assess(packet,response)
        self.assertIsNone(result['cases'][1]['verdict'])

    def test_cli_requires_explicit_version_and_preserves_historical_default(self):
        with patch.object(v,'qwen_run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','question-pair-run','--input','/tmp/frozen.json','--qwen-instant','--field-boundaries','--max-usd','.02','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['field_boundaries'])
        result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','question-pair-prepare','--field-boundaries','--check-only'])
        self.assertNotEqual(result.exit_code,0);self.assertIn('requires --qwen-instant',result.output)


class SourceFirstQualifierTests(unittest.TestCase):
    def fixture(self):
        spec,trial=v.source_first_trial()
        packet=dict(request=asdict(spec),native_trial=trial,qualifier_selection_version=q.SELECTION_VERSION)
        answers={}
        for key,item in trial['state'].items():
            unit=item['source']['units'][0]['id']
            answers[key]=dict(status='inspected',qualifiers=[dict(start_unit=unit,end_unit=unit,kind=kind) for kind in trial['audit_index'][key]['expected_kinds']],rationale='Synthetic source selection')
        return packet,spec,answers

    def test_list_independent_input_and_source_inventory_reuse(self):
        import json
        packet,spec,_=self.fixture();state=json.loads(spec.body['messages'][1]['content'])
        self.assertEqual(state,packet['native_trial']['state'])
        for token in ('expected_kinds','qualifier_ids','proposed'):
            self.assertNotIn(token,v.requests.wire(state))
        self.assertEqual(len(state),6)  # List variants share one source/point input.
        self.assertEqual(packet['native_trial'],json.loads(json.dumps(packet['native_trial'])))
        for key,item in state.items():
            window=v.evidence.SourceWindow(**packet['native_trial']['windows'][key])
            self.assertEqual(item,source_context.qualifier_source_item(window,item['proposition']))
        self.assertEqual(spec.body['reasoning_effort'],'none')

    def test_exact_quotes_bound_in_code_and_stable_scoped_ids(self):
        from copy import deepcopy
        packet,_,answers=self.fixture();key='q1';item=packet['native_trial']['state'][key];window=v.evidence.SourceWindow(**packet['native_trial']['windows'][key]);old=deepcopy(answers[key])
        first=q.compile_selection(window,item['proposition'],answers[key]);second=q.compile_selection(window,item['proposition'],answers[key])
        self.assertEqual(first,second);self.assertEqual(answers[key],old)
        self.assertIn('"',first['nodes'][0]['span']['text'])
        self.assertNotIn('“',first['nodes'][0]['span']['text'])
        changed=q.compile_selection(window,dict(reading='A different point'),answers[key])
        self.assertNotEqual(first['nodes'][0]['node_id'],changed['nodes'][0]['node_id'])
        self.assertFalse(first['production_admission'])
        with self.assertRaises(ValueError):q.compile_selection(window,item['proposition'],dict(answers[key],qualifiers=answers[key]['qualifiers']*2))
        with self.assertRaises(ValueError):q.compile_selection(window,item['proposition'],dict(answers[key],qualifiers=[dict(start_unit='unknown',end_unit='unknown',kind='concession')]))
        self.assertIn(first['nodes'][0]['span']['text'],window.target()[0]['target_text'])

    def test_retention_omissions_foreign_ids_unresolved_and_no_legacy_repairs(self):
        packet,_,answers=self.fixture();item=packet['native_trial']['state']['q1'];window=v.evidence.SourceWindow(**packet['native_trial']['windows']['q1'])
        catalog=q.compile_selection(window,item['proposition'],answers['q1']);ids=[n['node_id'] for n in catalog['nodes']];proposal=dict(catalog_id=catalog['catalog_id'],qualifier_ids=ids)
        self.assertTrue(q.retention(catalog,proposal)['complete'])
        self.assertFalse(q.retention(catalog,dict(proposal,qualifier_ids=[]))['complete'])
        self.assertFalse(q.retention(catalog,dict(proposal,qualifier_ids=ids+['foreign']))['complete'])
        self.assertIsNone(q.retention(catalog,[])['complete'])
        self.assertIsNone(q.retention(dict(catalog,inspection='unresolved'),proposal)['complete'])
        with self.assertRaises(ValueError):q.retention(catalog,dict(proposal,qualifier_ids=ids*2))
        with self.assertRaises(ValueError):q.retention(catalog,dict(proposal,catalog_id='other-point'))
        self.assertEqual(ids,[n['node_id'] for n in catalog['nodes']])

    def test_selection_quality_and_retention_quality_reported_separately(self):
        import json
        packet,spec,answers=self.fixture()
        response=dict(model=spec.body['model'],complete=True,usage=dict(input_tokens=100,output_tokens=100),output=json.dumps(answers))
        result=v.qwen_assess(packet,response)
        self.assertEqual(result['summary'],dict(total=6,correct=6,wrong=0,withheld=0))
        for row in result['rows']:
            probes=row['synthetic_retention_probes']
            self.assertTrue(probes['all_ids_retained']['complete'])
            self.assertFalse(probes['foreign_id']['complete'])
            self.assertTrue(all(x['complete'] is False for x in probes['each_omission']))
        answers['q1']['qualifiers']=[];response['output']=json.dumps(answers)
        result=v.qwen_assess(packet,response)
        self.assertEqual(result['summary']['wrong'],1)
        # ID coverage passes an empty catalog, but cannot conceal a semantic miss.
        self.assertTrue(result['rows'][1]['synthetic_retention_probes']['all_ids_retained']['complete'])
        answers['q1']['status']='unresolved';response['output']=json.dumps(answers)
        result=v.qwen_assess(packet,response)
        self.assertEqual(result['summary']['withheld'],1)
        self.assertIsNone(result['rows'][1]['synthetic_retention_probes']['all_ids_retained']['complete'])

    def test_source_first_cli_is_explicit_and_mutually_scoped(self):
        with patch.object(v,'qwen_run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','question-pair-run','--input','/tmp/frozen.json','--qwen-instant','--source-first','--max-usd','.02','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['source_first'])
        result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','question-pair-prepare','--source-first','--check-only'])
        self.assertNotEqual(result.exit_code,0);self.assertIn('requires --qwen-instant',result.output)


class IndependentQualifierTests(unittest.TestCase):
    def fixture(self):
        spec,trial=v.source_first_trial(atomic=True);answers={}
        for key,item in trial['state'].items():
            units=item['source']['units']
            answers[key]={role:([dict(start_unit=units[0]['id'],end_unit=units[-1]['id'])] if role in trial['audit_index'][key]['expected_kinds'] else []) for role in ('concession','expressed_uncertainty')}
        return dict(request=asdict(spec),native_trial=trial,qualifier_selection_version=q.SELECTION_VERSION,qualifier_decision_version=q.ATOMIC_VERSION),spec,answers

    def test_fixed_regression_points_terse_input_and_no_evaluator_hints(self):
        import json
        packet,spec,_=self.fixture();_,old=v.source_first_trial()
        for key,value in old['state'].items():self.assertEqual(value,packet['native_trial']['state'][key])
        state=json.loads(spec.body['messages'][1]['content'])
        for token in ('expected_markers','expected_kinds','qualifier_ids','proposed'):
            self.assertNotIn(token,v.requests.wire(state))
        self.assertEqual(spec.body['reasoning_effort'],'none');self.assertEqual(len(state),8)
        schema=spec.body['response_format']['json_schema']['schema']
        self.assertNotIn('rationale',v.requests.wire(schema))
        self.assertNotIn('confidence',v.requests.wire(schema))
        self.assertEqual(packet['native_trial'],json.loads(json.dumps(packet['native_trial'])))

    def test_independent_roles_can_cooccur_without_model_label_selection(self):
        import json
        packet,spec,answers=self.fixture()
        response=dict(model=spec.body['model'],complete=True,usage=dict(input_tokens=100,output_tokens=100),output=json.dumps(answers))
        result=v.qwen_assess(packet,response)
        self.assertEqual(result['summary'],dict(total=8,correct=8,wrong=0,withheld=0))
        self.assertEqual(len(result['rows'][-1]['catalog']['nodes']),2)
        self.assertEqual({n['kind'] for n in result['rows'][-1]['catalog']['nodes']},{'concession','expressed_uncertainty'})
        self.assertEqual(sum(len(r['per_role']) for r in result['rows']),16)
        for row in result['rows']:
            self.assertTrue(all(p['evaluation_marker_covered'] is not False for p in row['per_role']))

    def test_unknown_and_wrong_evidence_do_not_gain_semantic_support(self):
        import json
        packet,spec,answers=self.fixture();answers['q1']['concession']=None
        response=dict(model=spec.body['model'],complete=True,usage=dict(input_tokens=100,output_tokens=100),output=json.dumps(answers))
        result=v.qwen_assess(packet,response)
        self.assertEqual(result['summary']['withheld'],1)
        self.assertIsNone(result['rows'][1]['synthetic_retention_probes']['all_ids_retained']['complete'])
        # Correct role, unrelated unit: coverage must fail the evaluation.
        answers['q1']['concession']=[dict(start_unit='u0000',end_unit='u0000')]
        answers['q6']['concession']=[dict(start_unit='u0001',end_unit='u0001')]
        response['output']=json.dumps(answers);result=v.qwen_assess(packet,response)
        self.assertEqual(result['summary']['wrong'],1)
        self.assertFalse(result['rows'][6]['per_role'][0]['evaluation_marker_covered'])
        window=v.evidence.SourceWindow(**packet['native_trial']['windows']['q1']);point=packet['native_trial']['state']['q1']['proposition']
        with self.assertRaises(ValueError):q.compile_atomic_selection(window,point,dict(concession=True,expressed_uncertainty=[]))
        with self.assertRaises(ValueError):q.compile_atomic_selection(window,point,dict(concession=[],expressed_uncertainty=[],rationale='Do not infer from me'))

    def test_one_paid_recipe_boundary_replay_and_explicit_cli(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        packet,spec,answers=self.fixture();packet.update(input_fingerprint='synthetic-independent',baseline={},policy=dict(reasoning_effort='none'),limitation='synthetic',budget=dict(max_usd='.02',spend_root='unused'))
        with TemporaryDirectory() as folder:
            packet['budget']['spend_root']=folder;calls=[]
            def transport(s):
                calls.append(s)
                return v.requests.WireResponse(200,json.dumps(dict(model=s.body['model'],choices=[dict(finish_reason='stop',message=dict(content=json.dumps(answers)))],usage=dict(prompt_tokens=100,completion_tokens=100))))
            result=v.qwen_recipe(packet,Path(folder)/'run/execution',transport)
            self.assertEqual(result['assessment']['summary']['correct'],8)
            self.assertFalse(result['production_admission']);self.assertEqual(len(calls),1)
            self.assertEqual(result,v.qwen_recipe(packet,Path(folder)/'run/execution',lambda s:self.fail('no replay')))
        with patch.object(v,'qwen_run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','question-pair-run','--input','/tmp/frozen.json','--qwen-instant','--source-first','--atomic-qualifiers','--max-usd','.02','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['atomic_qualifiers'])
