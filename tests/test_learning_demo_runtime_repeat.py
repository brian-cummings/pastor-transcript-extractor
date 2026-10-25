from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import learning_demo_runtime_repeat as repeat
from pastor_transcript_extractor import learning_demo_model_fit as fit
from pastor_transcript_extractor import ollama_conformance as conformance
from pastor_transcript_extractor.evidence_requests import ReceiptStore, RequestSpec, WireResponse
from pastor_transcript_extractor.pastor_evidence import EvidenceArtifactStore, digest
from test_learning_demo_model_fit import packet
from test_learning_demo import FakeProvider


class RuntimeRepeatTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.prior=packet()
        self.runtime=self.prior['generation_runtime']
        self.prior.update(schema_version=fit.VERSION,code_identity=fit.code_identity(),history=dict(
            prior_input=str(self.base/'gemma/input.json'),preserved_files={}),
            budget=dict(prior_attempts=15,maximum_attempts=6,maximum_paid_attempts=0,max_usd='0',output_cap=8192,retries=0,fallbacks=0),
            selection=dict(windows=6),proposal={},source_refs=[],samples=[])
        self.prior.pop('input_fingerprint',None)
        self.prior=json.loads(json.dumps(self.prior))
        self.fingerprint=digest(self.prior);self.prior['input_fingerprint']=self.fingerprint
        self.out=fit.directory(self.base,self.fingerprint)
        EvidenceArtifactStore(self.out).write_immutable('input.json',self.prior)
        fit.run_recipe(self.prior,ReceiptStore(self.out/'execution'),lambda spec:WireResponse(200,json.dumps(dict(
            model=spec.body['model'],done=True,done_reason='stop',prompt_eval_count=10,eval_count=10,
            message=dict(content='not JSON')))))
        probes=[]
        for version,failed in [('0.31.1',True),('0.40.11',False)]:
            value=conformance.packet(self.runtime,version);root=conformance.root(self.base,value['input_fingerprint'])
            EvidenceArtifactStore(root).write_immutable('input.json',value)
            with patch.object(conformance.requests,'ollama_runtime_identity',return_value=self.runtime),\
                 patch.object(conformance,'server_version',return_value=version):
                def send(spec):
                    content='RUNTIME_UNCONSTRAINED' if failed and spec.source_identity['synthetic_case']=='conflicting' else json.dumps(
                        dict(result='SCHEMA_ENFORCED',detail=dict(marker='SYNTHETIC_ONLY')))
                    return WireResponse(200,json.dumps(dict(model=spec.body['model'],done=True,done_reason='stop',
                        prompt_eval_count=10,eval_count=10,message=dict(content=content))))
                conformance.run(root/'input.json',self.base,transport=send)
            probes.append(value['input_fingerprint'])
        for name,value in [('PRIOR',self.fingerprint),('BEFORE',probes[0]),('AFTER',probes[1])]:
            p=patch.object(repeat,name,value);p.start();self.addCleanup(p.stop)
        p=patch.object(fit,'prepare',side_effect=lambda *a,**kw:(deepcopy(self.prior),self.out));p.start();self.addCleanup(p.stop)
        p=patch.object(conformance,'server_version',return_value='0.40.11');p.start();self.addCleanup(p.stop)

    def prepare(self):
        return repeat.prepare(self.out/'input.json',self.base)

    def test_identical_bodies_new_cache_identity_six_slots_and_immutable_history(self):
        old_files={p:p.read_bytes() for p in self.out.rglob('*.json')}
        value,out=self.prepare()
        self.assertEqual(value['budget']['maximum_attempts'],6)
        self.assertEqual(value['budget']['cumulative_maximum_attempts'],31)
        self.assertEqual(value['generation_runtime']['server_version'],'0.40.11')
        for before,after in zip(self.prior['source_requests'],value['source_requests']):
            self.assertEqual(before['request']['body'],after['request']['body'])
            self.assertNotEqual(before['fingerprint'],after['fingerprint'])
            self.assertNotIn('SCHEMA_ENFORCED',json.dumps(after['request']['body']))
        self.assertTrue(all(p.read_bytes()==data for p,data in old_files.items()))
        self.assertEqual(fit.verify(out/'input.json',self.base),value)
        provider=FakeProvider()
        result=fit.run_recipe(value,ReceiptStore(out/'execution'),provider)
        self.assertEqual(len(provider.calls),6)
        self.assertEqual(result['accounting']['cumulative_attempts'],31)
        self.assertEqual(result['accounting']['prior_source_attempts'],21)
        self.assertEqual(result['accounting']['prior_synthetic_attempts'],4)
        self.assertEqual(result['accounting']['paid_attempts'],0)
        self.assertEqual(result['runtime_comparison']['server_version'],'0.40.11')
        self.assertEqual(result['runtime_comparison']['prior_diagnostics']['schema_valid_responses'],0)
        self.assertEqual(fit.run_recipe(value,ReceiptStore(out/'execution'),provider),result)
        self.assertEqual(len(provider.calls),6)

    def test_failed_proof_changed_server_or_body_block_preparation(self):
        with patch.object(conformance,'server_version',return_value='other'):
            with self.assertRaisesRegex(ValueError,'differs from passing'):self.prepare()
        self.prior['source_requests'][0]['request']['body']['think']=True
        with self.assertRaisesRegex(ValueError,'changed model, source prompt'):self.prepare()

    def test_one_repeat_marker_and_history_changes_are_detected(self):
        value,out=self.prepare()
        marker=fit.authorization_marker(value)
        self.assertEqual(marker,self.out/'execution/runtime-repeat-authorization.json')
        EvidenceArtifactStore(marker.parent).write_immutable(marker.name,dict(input_fingerprint='other'))
        with self.assertRaisesRegex(ValueError,'already assigned'):fit.verify(out/'input.json',self.base)
        # Frozen evidence is hashed even when the altered data remains parseable.
        result_path=self.out/'execution/results.json'
        old=json.loads(result_path.read_text());old['extra']='changed';result_path.write_text(json.dumps(old))
        with self.assertRaisesRegex(ValueError,'frozen sources, requests'):fit.verify(out/'input.json',self.base)

    def test_server_drift_before_send_does_not_reach_generation(self):
        value,out=self.prepare()
        with patch.object(fit,'verify',return_value=value),patch.object(fit,'ollama_transport') as send,\
             patch.object(conformance,'server_version',return_value='drifted'):
            result=fit.run(out/'input.json',self.base,experimental=True,approve_input=value['input_fingerprint'])
            send.assert_not_called()
            self.assertEqual(result['status'],'FAIL(component)')
            self.assertIn('server changed',result['halt'])

    def test_cli_routes_explicit_runtime_repeat(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        with patch.object(repeat,'prepare',return_value=(dict(input_fingerprint='fixture',selection={},budget={}),self.out)) as prepare:
            result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','prepare','--runtime-repeat',
                '--from-input',str(self.out/'input.json'),'--json'])
            self.assertEqual(result.exit_code,0,result.output)
            prepare.assert_called_once()
