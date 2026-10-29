from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
from pastor_transcript_extractor import profile_support_acceptance as a
from pastor_transcript_extractor import profile_support_budget as guard
from test_profile_analysis_support_execution import packet,wire


def allowance(folder,spend_root):
    root=Path(folder);objective=root/'goal.md';objective.write_text('Authorized synthetic test')
    value=dict(version=guard.VERSION,starting_conservative_usd='.5',additional_usd='2',cumulative_ceiling_usd='2.5',spend_root=spend_root,objective=dict(path=str(objective),sha256=a.file_hash(objective)))
    file=root/'allowance.json';file.write_text(json.dumps(value))
    return dict(path=str(file),sha256=a.file_hash(file))


class AcceptanceTests(unittest.TestCase):
    def test_explicit_goal_allowance_and_historical_guard(self):
        with TemporaryDirectory() as folder:
            p,out=packet(folder);self.assertEqual(guard.ceiling(p),1)
            p['acceptance_authorization']=allowance(folder,p['budget']['spend_root']);p['budget']['cumulative_ceiling_usd']='2.5'
            self.assertEqual(guard.ceiling(p),Decimal('2.5'))
            p['budget']['cumulative_ceiling_usd']='3'
            with self.assertRaisesRegex(ValueError,'ceiling'):guard.ceiling(p)
            p['budget']['cumulative_ceiling_usd']='2.5';Path(p['acceptance_authorization']['path']).write_text('{}')
            with self.assertRaisesRegex(ValueError,'changed'):guard.ceiling(p)

    def test_batches_close_dependencies_once_and_reserve_both_generations(self):
        with TemporaryDirectory() as folder:
            p,out=packet(folder)
            for t in p['tasks']:t['correction']=a.x.correction.policy(a.x.requests.RequestSpec(**t['request']))
            groups=a.partition(p['plan'],{'summary'},{t['claim_id']:t for t in p['tasks']})
            self.assertEqual(groups[0]['id'],'prerequisites-01');self.assertEqual(groups[0]['claim_ids'],['local'])
            self.assertEqual(Decimal(groups[0]['reserved_usd']),2*a.x.requests.request_reservation(a.x.requests.RequestSpec(**p['tasks'][0]['request'])))
            p['plan']['items'][0]['case']['dependencies']=['summary']
            with self.assertRaisesRegex(ValueError,'Cyclic'):a.partition(p['plan'],set(),{t['claim_id']:t for t in p['tasks']})

    def test_seed_and_batch_assemble_dependency_chain_without_generation(self):
        with TemporaryDirectory() as folder:
            p,unused=packet(folder)
            for t in p['tasks']:t['correction']=a.x.correction.policy(a.x.requests.RequestSpec(**t['request']))
            seed=deepcopy(p);seed['plan']['items']=seed['plan']['items'][:1];seed['tasks']=seed['tasks'][:1]
            seedroot=Path(folder)/'seed';a.x.recipe(seed,seedroot,wire)
            ref=allowance(folder,p['budget']['spend_root'])
            plan=dict(plan=p['plan'],tasks=p['tasks'],input_fingerprint='frozen',seed_run=str(seedroot),acceptance_authorization=ref,batches=[dict(id='remaining-01',claim_ids=['summary'],reserved_usd=str(2*a.x.requests.request_reservation(a.x.requests.RequestSpec(**p['tasks'][1]['request']))))])
            with patch.object(a,'load',return_value=(plan,Path(folder)/'acceptance')):
                sent=[]
                def send(spec):sent.append(spec);return wire(spec)
                r=a.run('/synthetic','remaining-01',approve_plan='frozen',transport=send)
                self.assertEqual(len(sent),1);self.assertEqual(r['coverage']['by_status'],dict(dependency_unresolved=1))
                with patch.object(a.x.provider,'transport',side_effect=AssertionError('no generation')):
                    doc=a.assemble('/synthetic')
                self.assertEqual(doc['coverage']['by_status'],dict(supported=2));self.assertEqual(doc['generation_calls'],0)
                with self.assertRaisesRegex(ValueError,'approval'):a.run('/synthetic','remaining-01',approve_plan='wrong',transport=send)
                self.assertEqual(a.run('/synthetic','remaining-01',approve_plan='frozen',transport=lambda s:self.fail('no repeat')),r)

    def test_wrong_goal_file_or_overlarge_allowance_is_rejected(self):
        with TemporaryDirectory() as folder:
            p,out=packet(folder);p['budget']['cumulative_ceiling_usd']='2.5';p['acceptance_authorization']=allowance(folder,p['budget']['spend_root'])
            path=Path(p['acceptance_authorization']['path']);v=json.loads(path.read_text());v['additional_usd']='3';path.write_text(json.dumps(v));p['acceptance_authorization']['sha256']=a.file_hash(path)
            with self.assertRaisesRegex(ValueError,'Invalid'):guard.ceiling(p)

    def test_repreparation_cannot_reset_the_goal_credit(self):
        with TemporaryDirectory() as folder:
            p,unused=packet(folder);profile=Path(folder)/'profile.json';profile.write_text('{}')
            p['profile_input']=dict(path=str(profile),sha256=a.file_hash(profile))
            p['input_fingerprint']=a.x.digest({k:v for k,v in p.items() if k!='input_fingerprint'})
            seed=Path(folder)/'seed';a.x.Store(seed).write_immutable('input.json',p);a.x.recipe(p,seed,wire)
            objective=Path(folder)/'objective.md';objective.write_text('Additional $2 authorized')
            with patch.object(a.x.core,'build_plan',return_value=p['plan']):
                first=a.prepare(seed,objective,Path(folder))
                with patch.object(a.x.supervised,'cumulative_history',side_effect=AssertionError('Must reuse original allowance baseline')):
                    second=a.prepare(seed,objective,Path(folder))
            self.assertEqual(first,second)

    def test_explicit_allowance_extends_only_its_own_execution_guard(self):
        from contextlib import contextmanager
        @contextmanager
        def spent(packet,root):yield [({},Decimal('.8'))]
        with TemporaryDirectory() as folder:
            p,out=packet(folder)
            with patch.object(a.x.supervised,'cumulative_history',spent):
                with self.assertRaisesRegex(ValueError,'ceiling'):a.x.recipe(p,out,lambda s:self.fail('legacy guard'))
            p['acceptance_authorization']=allowance(folder,p['budget']['spend_root']);p['budget']['cumulative_ceiling_usd']='2.5'
            with patch.object(a.x.supervised,'cumulative_history',spent):
                report=a.x.recipe(p,out,wire)
            self.assertEqual(report['execution_status'],'COMPLETE')
