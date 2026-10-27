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
