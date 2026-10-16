"""Focused V4 packet and authorization checks; no semantic/provider evaluation."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor import evidence_supply_boundary_v4 as panel
from pastor_transcript_extractor.cli import app


class V4PacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = json.loads(panel.INPUT.read_text())

    def reseal(self, value):
        value['content_fingerprint'] = panel.old.frozen.fp({k:v for k,v in value.items() if k!='content_fingerprint'})
        return value

    def test_reproduces_exact_small_packet_without_provider(self):
        with patch.object(panel.old.frozen, 'HTTPProvider', side_effect=AssertionError('provider')):
            panel.validate_packet(self.packet, reproduce=True)
        self.assertEqual(24,len(self.packet['cases']))
        self.assertEqual(37,len(self.packet['requests']))
        self.assertEqual(2368000,self.packet['budget']['maximum_input_tokens'])
        self.assertFalse(self.packet['authorization']['semantic_execution'])

    def test_all_original_and_six_forward_comparisons_are_separate(self):
        comparisons = [d for c in self.packet['cases'] for d in c['comparisons']]
        self.assertEqual(21,sum(d['scope']=='historical_V3_geometry_diagnostic' for d in comparisons))
        self.assertEqual(6,sum(d['scope']=='proposed_forward_check' for d in comparisons))
        self.assertEqual(3,sum(c['case_id'].endswith(('explicit-gloss','complete-gloss','complete-promise')) for c in self.packet['cases']))

    def test_target_stays_fragment_while_context_preserves_promise(self):
        fragment=next(r for r in self.packet['requests'] if r['case_id']=='B4-R077' and r['phase']=='G3_acts_and_source_only')
        full=next(r for r in self.packet['requests'] if r['case_id']=='B4-R077-complete-promise' and r['phase']=='G3_acts_and_source_only')
        self.assertEqual('if you confess your sins',fragment['state']['target_text'])
        self.assertIn('he is faithful and just',fragment['state']['trailing_context'])
        self.assertIn('he is faithful and just',full['state']['target_text'])

    def test_reporting_context_and_natural_order_preserved(self):
        for rid, intro in [('R053','Joseph'),('R111','Bruce'),('R114','Fanny Crosby'),('R076','Miller Hall')]:
            case=next(c for c in self.packet['cases'] if c['case_id']=='B4-'+rid)
            for request in (r for r in self.packet['requests'] if r['case_id']==case['case_id']):
                state=request['state']
                self.assertEqual(case['source_envelope']['text'],state['leading_context']+state['target_text']+state['trailing_context'])
            act=next(r for r in self.packet['requests'] if r['case_id']==case['case_id'] and r['phase']=='G3_acts_and_source_only')
            self.assertIn(intro,act['state']['leading_context'])
            self.assertEqual(case['candidate']['endpoints']['utterance']['text'],act['state']['target_text'])
            self.assertNotIn('preliminary_facts',act['state'])

    def test_resealed_target_or_phase_change_is_rejected(self):
        for change in ('target','question'):
            packet=deepcopy(self.packet);request=packet['requests'][0]
            if change=='target':request['state']['target_text']+=' changed'
            else:request['questions']['illegal_act']={}
            request['request_key']=panel.old.frozen.fp({k:v for k,v in request.items() if k!='request_key'})
            packet['cases'][0]['request_keys']=[request['request_key']]
            with self.assertRaises(ValueError):panel.validate_packet(self.reseal(packet))

    def test_resealed_provider_authorization_and_budget_change_rejected(self):
        packet=deepcopy(self.packet);packet['authorization']['provider_calls']=True
        with self.assertRaisesRegex(ValueError,'authorization'):panel.validate_packet(self.reseal(packet))
        packet=deepcopy(self.packet);packet['budget']['maximum_attempts']=38
        with self.assertRaisesRegex(ValueError,'budget'):panel.validate_packet(self.reseal(packet))

    def test_runtime_symlink_cannot_resolve_into_repository(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=Path(root)/'evaluation';runtime.mkdir()
            (runtime/'evidence-supply-boundary-v4').symlink_to(panel.old.frozen.ROOT,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'outside'):panel.output_directory(Path(root))

    def test_changed_snapshot_or_code_rejected(self):
        original=panel.old.frozen.v1.file_hash
        for ending in ('sources/1200.json','evidence_boundary_admission.py'):
            def altered(path):
                return 'changed' if str(path).endswith(ending) else original(path)
            with patch.object(panel.old.frozen.v1,'file_hash',side_effect=altered):
                with self.assertRaisesRegex(ValueError,'changed'):panel.validate_packet(self.packet)

    def test_cli_requires_explicit_fingerprint_for_execution(self):
        for option in ('--execute','--approve-paid-packet'):
            result=CliRunner().invoke(app,['analysis','evidence-supply-boundary-revalidation',option])
            self.assertNotEqual(0,result.exit_code)
        with patch.object(panel.old.frozen,'HTTPProvider',side_effect=AssertionError('provider')):
            result=CliRunner().invoke(app,['analysis','evidence-supply-boundary-revalidation','--check-only'])
        self.assertEqual(0,result.exit_code,result.output)
        self.assertIn('provider_requests=0',' '.join(result.output.split()))
        self.assertIn(self.packet['content_fingerprint'],result.output)
