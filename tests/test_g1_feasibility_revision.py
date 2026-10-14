from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor import sermon_g1_feasibility_review as v1
from pastor_transcript_extractor import sermon_g1_feasibility_revision as v2


def answer(inventory,selected=None):
    selected=selected or {}
    default={'relation':'no_match','polarity':'no_expression','voice':'unclear','adoption':'undetermined'}
    return {key:dict(choice=selected.get(key,default[key]),confidence=1.0,probabilities={option:float(option==selected.get(key,default[key])) for option in q['criteria']}) for key,q in inventory.items()}


class FakeProvider:
    def __init__(self): self.states=[];self.questions=[]
    def assess(self,state,inventory):
        self.states.append(deepcopy(state));self.questions.append(deepcopy(inventory))
        return dict(answers=answer(inventory),resolved_model=v1.MODEL,usage=dict(input_tokens=10,output_tokens=5),request_id=f'mock-v2-{len(self.states)}')


class G1RevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet=v2.prepare()
        cls.base,cls.result,cls.rows=v2.load_baseline()

    def test_identical_cases_expectations_states_and_four_changed_contracts(self):
        self.assertEqual(self.base['cases'],self.packet['cases'])
        self.assertEqual(28,len(self.packet['cases']))
        self.assertEqual({'provider_request_ceiling':37,'new_question_count':148,'reused_v1_answers':338,'sdk_retries':0,'timeout_seconds':45},self.packet['budget'])
        for case in self.base['cases']:
            old=v1.questions(case['phrase_pools']);new=v2.questions(case['phrase_pools'])
            self.assertEqual(set(v2.CHANGED),{k for k in old if old[k]!=new[k]})
            for unit in case['candidates']:
                self.assertNotIn('expected_claims',v1.state_for(case,unit))
        self.assertEqual(39,len(v2.audit()['findings']))
        self.assertEqual([],v2.audit()['expectation_revisions_proposed'])

    def test_mock_run_reuses_exact_original_answers_and_questions(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=FakeProvider();report=v2.evaluate(self.packet,provider_factory=lambda:provider,cache_dir=Path(directory))
            self.assertEqual(37,len(provider.states));self.assertTrue(all(set(q)==set(v2.CHANGED) for q in provider.questions))
            self.assertEqual(338,report['execution']['reused_v1_answers'])
            self.assertEqual(37,report['execution']['provider_requests'])
            for row in report['rows']:
                old=self.rows[row['candidate']['candidate_id']]
                for field in set(row['raw_answers'])-set(v2.CHANGED):
                    self.assertEqual(old['raw_answers'][field],row['raw_answers'][field])
                    self.assertEqual('frozen_v1_result',row['answer_provenance'][field]['source'])
                    self.assertEqual(v1.VERSION,row['answer_provenance'][field]['question_version'])
                case=next(c for c in self.base['cases'] if c['case_id']==row['case_id'])
                self.assertEqual(v1.compose(case,row['candidate'],row['decisions']),row['observation'])
            replay=v2.evaluate(self.packet,provider_factory=lambda:(_ for _ in ()).throw(AssertionError('provider')),cache_dir=Path(directory))
            self.assertEqual(0,replay['execution']['provider_requests']);self.assertEqual(37,replay['execution']['v2_cache_hits'])
            self.assertEqual('v2_cache',replay['rows'][0]['answer_provenance']['relation']['source'])
            self.assertEqual(338,replay['execution']['reused_v1_answers'])

    def test_semantic_changes_do_not_create_opposite_or_change_scope(self):
        case=next(c for c in self.base['cases'] if c['case_id']=='A08');unit=case['candidates'][0]
        raw=deepcopy(self.rows[unit['candidate_id']]['raw_answers'])
        raw.update(answer({k:v2.questions(case['phrase_pools'])[k] for k in v2.CHANGED},dict(relation='loss_possible',polarity='denied',voice='reported_teachers',adoption='explicitly_rejected')))
        observation=v1.compose(case,unit,v1.decisions(raw))
        self.assertEqual('loss_possible',observation['relation']);self.assertEqual('denied',observation['polarity'])
        self.assertFalse(observation['provisional_adopted_local_assertion']);self.assertIsNone(observation['contradiction_verdict'])
        self.assertEqual(self.rows[unit['candidate_id']]['observation']['scope_text'],observation['scope_text'])

    def test_uncertainty_and_context_decisions_are_not_refilled(self):
        for cid in ('A04','A09','P07','P09'):
            old=next(r for r in self.result['rows'] if r['case_id']==cid)
            case=next(c for c in self.base['cases'] if c['case_id']==cid)
            raw=deepcopy(old['raw_answers']);raw.update(answer({k:v2.questions(case['phrase_pools'])[k] for k in v2.CHANGED}))
            d=v1.decisions(raw)
            for key in ('subject','object_anchor','epistemic_status','epistemic_evidence','scope_evidence','boundary'):
                self.assertEqual(old['decisions'][key],d[key])
            self.assertFalse(v1.compose(case,old['candidate'],d)['provisional_adopted_local_assertion'])

    def test_expectations_are_unchanged_in_before_after_comparison(self):
        result=deepcopy(self.result)
        report=v2.compare(self.result,result)
        self.assertEqual({'retained_match':170,'remaining_focused_failure':37,'unchanged_binding_withholding_outside_revision':2},report['classification_counts'])
        result['diagnostics']['checks'][0]['expected']='rewritten'
        with self.assertRaisesRegex(ValueError,'Expectation semantics'):v2.compare(self.result,result)

    def test_changed_source_bytes_or_packet_prevent_reuse(self):
        with patch.object(v1,'file_fp',return_value='wrong'):
            with self.assertRaisesRegex(ValueError,'bytes changed'):v2.load_baseline()
        packet=deepcopy(self.packet);packet['cases'][0]['target_text']='new target'
        packet['content_fingerprint']=v1.fp({k:v for k,v in packet.items() if k!='content_fingerprint'})
        with self.assertRaisesRegex(ValueError,'reuse drift'):v2.validate(packet)

    def test_bad_model_and_incomplete_answers_are_charged_without_cache_credit(self):
        for failure in ('model','answers'):
            provider=FakeProvider();method=provider.assess
            def broken(state,inventory):
                result=method(state,inventory)
                if failure=='model':result['resolved_model']='wrong-model'
                else:result['answers'].pop('polarity')
                return result
            provider.assess=broken
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):v2.evaluate(self.packet,provider_factory=lambda:provider,cache_dir=Path(directory))
                ledger=json.loads((Path(directory)/'request-ledger.json').read_text())
                self.assertEqual(1,ledger['attempted_requests']);self.assertEqual(1,len(list(Path(directory).glob('*.json'))))

    def test_cumulative_budget_is_enforced_before_provider_instantiation(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            ledger=dict(input_fingerprint=self.packet['content_fingerprint'],attempted_requests=37,attempts=[{'status':'attempted'}]*37)
            v1._save_ledger(path/'request-ledger.json',ledger)
            with self.assertRaisesRegex(ValueError,'ceiling exhausted'):
                v2.evaluate(self.packet,provider_factory=lambda:(_ for _ in ()).throw(AssertionError('provider')),cache_dir=path)

    def test_native_cli_revision_default_and_mode_validation(self):
        runner=CliRunner()
        for options,mode in (([], 'evaluate'),(['--check-only'],'check'),(['--prepare-only'],'prepare')):
            with patch.object(v2,'run') as run:
                result=runner.invoke(app,['analysis','g1-feasibility-review','--revision','v2',*options])
                self.assertEqual(0,result.exit_code,result.output);run.assert_called_once_with(mode)
        with patch.object(v1,'run') as run:
            result=runner.invoke(app,['analysis','g1-feasibility-review','--check-only'])
            self.assertEqual(0,result.exit_code);run.assert_called_once_with('check')
        for options in (['--revision','v3'],['--revision','v2','--check-only','--prepare-only']):
            with patch.object(v2,'run') as run:
                result=runner.invoke(app,['analysis','g1-feasibility-review',*options]);self.assertNotEqual(0,result.exit_code);run.assert_not_called()


if __name__=='__main__':unittest.main()
