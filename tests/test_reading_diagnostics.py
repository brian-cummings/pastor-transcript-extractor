from copy import deepcopy
from dataclasses import asdict
import unittest
from pastor_transcript_extractor import reading_diagnostics as d
from pastor_transcript_extractor.learning_demo_thinking_check import schema
from pastor_transcript_extractor.evidence_requests import RequestSpec
from pastor_transcript_extractor.pastor_evidence import SourceWindow
from test_learning_demo import synthetic_packet,FakeProvider


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        packet=synthetic_packet();self.window=SourceWindow(**packet['windows'][0])
        self.output=FakeProvider()(RequestSpec(**packet['source_requests'][0]['request']))['output']

    def inspect(self,value):
        return d.inspect(value,schema(),self.window,model='synthetic',prompt_digest='synthetic',raw_response_ref='synthetic')

    def test_valid_output_uses_compiler_and_does_not_mutate(self):
        original=deepcopy(self.output);result=self.inspect(self.output)
        self.assertEqual(result['errors'],[]);self.assertEqual(len(result['observations']),2)
        self.assertEqual(self.output,original)

    def test_independent_field_errors_are_reported_together(self):
        row=self.output['claims'][0];row['adoption']['basis']='discourse_use'
        row['epistemic_status']['evidence']=[]
        row['scope']['evidence'][0]['text']='absent quotation'
        result=self.inspect(self.output);paths={e['path'] for e in result['errors']}
        self.assertIn('$.claims[0].adoption',paths)
        self.assertIn('$.claims[0].epistemic_status.evidence',paths)
        self.assertIn('$.claims[0].scope.evidence[0]',paths)
        self.assertEqual(len(result['observations']),1)

    def test_schema_diagnostics_collect_multiple_paths_and_never_repair(self):
        self.output['claims'][0]['voice']['kind']='bogus';del self.output['status']
        result=self.inspect(self.output)
        self.assertEqual({e['path'] for e in result['errors']},{'$.status','$.claims[0].voice.kind'})
        self.assertEqual(result['observations'],[])
        self.assertEqual(self.inspect('not json')['errors'][0]['code'],'json')

    def test_compiler_still_rejects_constraints_not_expanded_in_diagnostics(self):
        row=self.output['claims'][0]
        row['adoption'].update(status='adopted',basis='discourse_use',evidence=[deepcopy(row['proposition']['span'])])
        result=self.inspect(self.output)
        self.assertTrue(any(e['code']=='compiler' for e in result['errors']))

    def test_repeated_quote_never_selects_first_match(self):
        self.window=SourceWindow(**{**asdict(self.window),'blocks':(
            {**self.window.blocks[0],'target_text':'God creates the world. God creates the world. People respond with trust.'},)})
        result=self.inspect(self.output)
        self.assertTrue(any('matches=2' in e['message'] for e in result['errors']))
