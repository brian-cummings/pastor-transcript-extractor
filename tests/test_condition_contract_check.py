from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor import condition_contract_check as c
from pastor_transcript_extractor.cli import app


class ConditionContractTests(unittest.TestCase):
    def test_boundaries_preserve_all_fields_without_admission_or_inference(self):
        # No executor or provider metadata belongs in this offline diagnostic.
        with patch.object(c.context.requests,'execute',side_effect=AssertionError('no inference')):
            result=c.check()
        self.assertEqual(result['status'],'PASS');self.assertEqual(len(result['cases']),8)
        self.assertEqual(result['generation_calls'],0);self.assertEqual(result['paid_calls'],0)
        self.assertFalse(result['production_admission'])
        for row in result['cases']:
            self.assertTrue(all(row['checks'].values()),row)
            self.assertEqual(row['semantic_outcome'],'NOT_ASSESSED_OFFLINE')
        self.assertEqual(c.check(),result)

    def test_conditional_words_do_not_create_conditions_and_omissions_are_not_auto_repaired(self):
        cases={r['id']:r for r in c.check()['cases']}
        for key in ('unrelated_conditional','conditional_consequence','omitted_condition','condition_only_in_qualification'):
            self.assertTrue(cases[key]['mechanical_pass'])
            self.assertEqual(cases[key]['verifier_field_value']['conditions'],[])
        self.assertEqual(len(cases['condition_only_in_qualification']['verifier_field_value']['qualifications']),1)
        self.assertEqual(cases['concession']['verifier_field_value']['conditions'],[])
        self.assertEqual(cases['exception']['verifier_field_value']['conditions'][0]['kind'],'exception')
        self.assertFalse(cases['foreign_attachment']['mechanical_pass'])
        self.assertTrue(any(e['code']=='reference' for e in cases['foreign_attachment']['errors']))

    def test_detects_lost_conditions_in_verifier_presentation(self):
        real=c.context.verification
        def broken(window,observations):
            spec,candidates=real(window,observations);body=deepcopy(spec.body)
            for key,question in body['questions'].items():
                if key.endswith(':qualifications'):
                    question['instructions']['returned_value']['conditions']=[]
            return replace(spec,body=body),candidates
        with patch.object(c.context,'verification',side_effect=broken): result=c.check()
        self.assertEqual(result['status'],'FAIL(component)')
        row=next(r for r in result['cases'] if r['id']=='direct_condition')
        self.assertFalse(row['checks']['conditions_forwarded'])

    def test_condition_removal_changes_only_its_declared_field(self):
        controls={r['id']:r for r in c.cases()}
        original=controls['direct_condition']['reading']['claims'][0]
        omitted=controls['omitted_condition']['reading']['claims'][0]
        self.assertEqual({k for k in original if original[k]!=omitted[k]},{'conditions'})

    def test_cli_exports_reproducible_report_only_under_application_base(self):
        with TemporaryDirectory() as directory:
            args=['analysis','learning-demo','model-fit','condition-contract-check','--base-dir',directory,'--json']
            runner=CliRunner();result=runner.invoke(app,args)
            self.assertEqual(result.exit_code,0,result.output);value=json.loads(result.output)
            self.assertEqual(value['case_count'],8)
            path=Path(value['results']);self.assertTrue(path.resolve().is_relative_to(Path(directory).resolve()))
            saved=path.read_bytes();self.assertTrue(Path(value['review']).exists())
            self.assertEqual(runner.invoke(app,args).exit_code,0)
            self.assertEqual(path.read_bytes(),saved)
        repo=Path(c.__file__).parents[2]
        with self.assertRaisesRegex(ValueError,'outside repository'): c.export(repo)
