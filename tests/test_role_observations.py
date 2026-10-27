from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import role_observations as integration
from pastor_transcript_extractor.cli import app
from test_role_decisions_check import fixture


def inputs():
    packet,context,checked,baseline,old_spec=fixture()
    spec=integration.check.requests.RequestSpec(**packet['request'])
    answers={}
    for key,index in packet['audit_index'].items():
        options=integration.check.choices.CRITERIA[index['field']];choice=next(iter(options))
        answers[key]=dict(type='choice',choice=choice,probabilities={k:.97 if k==choice else .03/(len(options)-1) for k in options},confidence=.5)
    response=dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output=answers)
    rows=integration.check.choices.decisions(response,spec,packet['audit_index'])
    old_answers={r['question_id']:{k:r[k] for k in ('type','choice','probabilities','confidence')} for r in baseline}
    old_response=dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output=old_answers)
    def raw(response): return dict(response=response,response_digest=integration.evidence.digest(response))
    source_spec=integration.check.requests.RequestSpec(**context['request'])
    return dict(packet=packet,context_packet=context,checked=checked,result=dict(decisions=rows,reused_decisions=packet['reused_decisions']),
        new_receipt=(spec,raw(response),Path('/synthetic/new-receipt.json')),
        baseline_receipt=(old_spec,raw(old_response),Path('/synthetic/baseline-receipt.json')),
        evidence_receipt=(source_spec,raw(dict(output='synthetic role proposal')),Path('/synthetic/evidence-receipt.json')),
        preserved_files={})


class RoleObservationIntegrationTests(unittest.TestCase):
    def test_integrates_compatible_reused_and_new_fields_without_semantic_repairs(self):
        value=inputs();before=deepcopy(value);rows=integration.integrate(value)
        self.assertEqual(value,before);self.assertEqual(len(rows),1)
        row=rows[0];partial=row['partial_binding']
        self.assertEqual(partial['values'],dict(voice=None,occurrence='actual',adoption=None))
        self.assertEqual(row['field_decisions']['occurrence']['raw_response_ref'],'/synthetic/baseline-receipt.json')
        self.assertEqual(row['field_decisions']['voice']['raw_response_ref'],'/synthetic/new-receipt.json')
        self.assertEqual(row['producer']['role_evidence']['raw_response_ref'],'/synthetic/evidence-receipt.json')
        self.assertEqual(partial['evidence'],value['checked']['evidence'][0]['package']['binding_evidence'])
        summary=integration.report(rows);self.assertEqual(summary['known_fields'],dict(voice=0,occurrence=1,adoption=0))
        self.assertEqual(summary['eligible_complete_observations'],0)
        self.assertFalse(summary['production_admission']);self.assertEqual(summary['paid_calls'],0)
        self.assertEqual(summary['status'],'PASS');self.assertIn('INCONCLUSIVE',summary['semantic_outcome'])

    def test_missing_duplicate_and_raw_or_source_changes_fail_closed(self):
        for mode in ('missing','duplicate_new','duplicate_reuse','raw_change','bad_span','package_mismatch','extra_package'):
            value=inputs()
            if mode=='missing': value['result']['decisions'].pop()
            if mode=='duplicate_new': value['result']['decisions'].append(deepcopy(value['result']['decisions'][0]))
            if mode=='duplicate_reuse': value['result']['reused_decisions'].append(deepcopy(value['result']['reused_decisions'][0]))
            if mode=='raw_change': value['result']['decisions'][0]['confidence']=.99
            if mode=='bad_span': value['checked']['evidence'][0]['package']['binding_evidence']['voice']['evidence'][0]['text']='invented'
            if mode=='package_mismatch': value['checked']['evidence'][0]['package']['proposition']['span']['text']='invented'
            if mode=='extra_package': value['checked']['evidence'].append(deepcopy(value['checked']['evidence'][0]))
            with self.subTest(mode=mode),self.assertRaises(ValueError): integration.integrate(value)

    def test_offline_build_replay_no_writes_check_and_cli(self):
        value=inputs()
        with TemporaryDirectory() as folder,patch.object(integration,'load_inputs',return_value=value),patch.object(integration.check.requests,'typesafe_transport',side_effect=AssertionError('No provider calls')):
            base=Path(folder);planned=integration.build(base,check_only=True)
            self.assertEqual(planned['status'],'CHECKED_NO_WRITES');self.assertFalse(Path(planned['manifest']).exists())
            built=integration.build(base);self.assertEqual(built,integration.build(base))
            manifest=json.loads(Path(built['manifest']).read_text());rows=json.loads(Path(built['output']).read_text())
            self.assertEqual(manifest['observation_ids'],[r['id'] for r in rows])
            self.assertEqual(built['paid_calls'],0);self.assertEqual(built['observations'],1)
        with patch.object(integration,'build',return_value=dict(status='CHECKED_NO_WRITES')) as build:
            result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','role-observations-build','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(build.call_args.kwargs['check_only'])
