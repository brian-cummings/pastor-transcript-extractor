from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor import sermon_g1_feasibility_review as g1


def raw_choices(inventory, selected=None):
    selected=selected or {}
    default={'subject':'no_match','relation':'no_match','polarity':'no_expression','expression':'no_expression',
             'voice':'unclear','adoption':'undetermined','epistemic_status':'not_stated','boundary':'local_sufficient'}
    answers={}
    for key,q in inventory.items():
        choice=selected.get(key,default.get(key,'not_bound' if key.startswith('bind_') else 'none'))
        answers[key]={'choice':choice,'probabilities':{option:float(option==choice) for option in q['criteria']},'confidence':1.0}
    return answers


class FakeProvider:
    def __init__(self):self.calls=0
    def assess(self,state,inventory):
        self.calls+=1
        return {'answers':raw_choices(inventory),'resolved_model':g1.MODEL,'request_id':f'mock-{self.calls}','usage':{'input_tokens':10,'output_tokens':20}}


class G1FeasibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.packet=g1.prepare()

    def case(self,cid):return deepcopy(next(c for c in self.packet['cases'] if c['case_id']==cid))

    def test_fixed_packet_and_expected_labels_never_supply_provider_state(self):
        self.assertEqual(28,len(self.packet['cases']))
        self.assertEqual(37,self.packet['budget']['provider_request_ceiling'])
        c=self.case('A02');before=g1.candidates(c);c['expected_claims']=[];c['review_checks']=[{'pretend':'opposite'}]
        self.assertEqual(before,g1.candidates(c))
        state=g1.state_for(c,c['candidates'][0])
        self.assertEqual({'target_text','leading_context','trailing_context','phrase_pools','candidate'},set(state))
        self.assertNotIn('expected',json.dumps(state))

    def test_packet_scope_source_and_unsigned_drift_rejected(self):
        p=deepcopy(self.packet);p['model']='jev';p['content_fingerprint']=g1.fp({k:v for k,v in p.items() if k!='content_fingerprint'})
        with self.assertRaisesRegex(ValueError,'policy drift'):g1.validate(p)
        p=deepcopy(self.packet);p['cases'][0]['candidates'][0]['claim_span']['start']=2
        with self.assertRaisesRegex(ValueError,'fingerprint'):g1.validate(p)

    def test_report_rejection_does_not_invent_adopted_opposite(self):
        c=self.case('A08');d={k:v['choice'] for k,v in raw_choices(g1.questions(c['phrase_pools']),{'subject':'salvation_acceptance','relation':'loss_possible','polarity':'denied','expression':'assertion','voice':'reported_teachers','adoption':'explicitly_rejected','object_anchor':'objects-0','voice_evidence':'frame-0','adoption_evidence':'frame-1'}).items()}
        out=g1.compose(c,c['candidates'][0],d)
        self.assertEqual('denied',out['polarity']);self.assertEqual('explicitly_rejected',out['adoption'])
        self.assertFalse(out['provisional_adopted_local_assertion']);self.assertIsNone(out['contradiction_verdict'])
        self.assertEqual(c['target_text'], ' '.join(s['text'] for s in out['binding_evidence'][1:]))

    def test_model_withholding_is_not_speaker_uncertainty(self):
        c=self.case('A04');inventory=g1.questions(c['phrase_pools'])
        raw=raw_choices(inventory,{'epistemic_status':'expressed_uncertainty'})
        raw['epistemic_status']['probabilities']={'expressed_uncertainty':.6,'not_stated':.3,'unclear':.1}
        d=g1.decisions(raw)
        self.assertEqual('unclear',d['epistemic_status'])
        self.assertEqual('unresolved',g1.compose(c,c['candidates'][0],d)['epistemic_status'])
        d['epistemic_status']='expressed_uncertainty'
        self.assertNotEqual('expressed_uncertainty',g1.compose(c,c['candidates'][0],d)['epistemic_status'])
        d['epistemic_evidence']='uncertainty-0'
        self.assertEqual('expressed_uncertainty',g1.compose(c,c['candidates'][0],d)['epistemic_status'])

    def test_wrong_claim_qualifier_and_scoped_claims_remain_local(self):
        c=self.case('B05');inventory=g1.questions(c['phrase_pools'])
        d=g1.decisions(raw_choices(inventory))
        self.assertEqual([],g1.compose(c,c['candidates'][0],d)['conditions'])
        d['bind_conditions-0']='bound'
        out=g1.compose(c,c['candidates'][1],d)
        self.assertEqual('if an equivalent accessible entrance is permitted',out['conditions'][0]['span']['text'])
        self.assertIsNone(out['pastor_projection']);self.assertIsNone(out['quality_score'])
        c=self.case('B04');d=g1.decisions(raw_choices(g1.questions(c['phrase_pools']),{'scope_evidence':'scopes-0'}))
        self.assertEqual('in this emergency',g1.compose(c,c['candidates'][0],d)['scope_text'])

    def test_full_mock_run_and_zero_request_cache_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=FakeProvider();cache=Path(directory)
            report=g1.evaluate(self.packet,provider_factory=lambda:provider,cache_dir=cache)
            self.assertEqual(37,provider.calls);self.assertEqual(37,report['execution']['provider_requests'])
            self.assertFalse(report['diagnostics']['automatic_pass'])
            with patch.object(g1,'Provider',side_effect=AssertionError('must not contact provider')):
                replay=g1.evaluate(self.packet,provider_factory=lambda:(_ for _ in ()).throw(AssertionError('provider constructed')),cache_dir=cache)
            self.assertEqual(0,replay['execution']['provider_requests']);self.assertEqual(37,replay['execution']['cache_hits'])
            self.assertEqual(37,replay['execution']['cumulative_attempted_requests'])
            self.assertEqual(37,len(report['request_ledger']['attempts']))
            self.assertEqual(370,report['execution']['known_cumulative_input_tokens'])
            self.assertEqual(740,report['execution']['known_cumulative_output_tokens'])

    def test_invalid_model_records_attempt_and_stops_without_cache_credit(self):
        provider=FakeProvider();original=provider.assess
        def wrong(state,inventory):
            value=original(state,inventory);value['resolved_model']='unapproved-model';return value
        provider.assess=wrong
        with tempfile.TemporaryDirectory() as directory:
            cache=Path(directory)
            with self.assertRaisesRegex(ValueError,'model mismatch'):g1.evaluate(self.packet,provider_factory=lambda:provider,cache_dir=cache)
            ledger=json.loads((cache/'request-ledger.json').read_text())
            self.assertEqual(1,ledger['attempted_requests']);self.assertEqual('response_received',ledger['attempts'][0]['status'])
            self.assertEqual(1,len(list(cache.glob('*.json'))))

    def test_cumulative_budget_exhaustion_prevents_provider_construction(self):
        with tempfile.TemporaryDirectory() as directory:
            cache=Path(directory);ceiling=self.packet['budget']['provider_request_ceiling']
            ledger=dict(input_fingerprint=self.packet['content_fingerprint'],attempted_requests=ceiling,attempts=[{'status':'attempted'}]*ceiling)
            g1._save_ledger(cache/'request-ledger.json',ledger)
            with self.assertRaisesRegex(ValueError,'ceiling exhausted'):
                g1.evaluate(self.packet,provider_factory=lambda:(_ for _ in ()).throw(AssertionError('provider constructed')),cache_dir=cache)

    def test_cli_modes_are_native_and_execution_is_never_run_in_tests(self):
        runner=CliRunner()
        for args,mode in [([], 'evaluate'),(['--check-only'],'check'),(['--prepare-only'],'prepare')]:
            with patch.object(g1,'run') as run:
                result=runner.invoke(app,['analysis','g1-feasibility-review',*args])
                self.assertEqual(0,result.exit_code,result.output);run.assert_called_once_with(mode)
        with patch.object(g1,'run') as run:
            result=runner.invoke(app,['analysis','g1-feasibility-review','--check-only','--prepare-only'])
            self.assertNotEqual(0,result.exit_code);run.assert_not_called()


if __name__=='__main__':unittest.main()
