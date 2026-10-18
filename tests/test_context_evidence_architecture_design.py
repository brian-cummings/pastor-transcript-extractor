"""Proposal/authority checks only; no replacement workflow implementation."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from pastor_transcript_extractor import context_evidence_architecture_design as design


class ProposalTests(unittest.TestCase):
    def fixture(self):
        d=json.loads((design.HERE/'decision-v1.json').read_text())
        p=json.loads((design.HERE/'proposal-v1.json').read_text())
        e=json.loads((design.HERE/'experiment-v1.json').read_text())
        return p,d,e

    def test_closed_architecture_and_design_only_authority(self):
        p,d,e=self.fixture();design.validate(p,d,e)
        d=deepcopy(d);d['authorized']['replacement_implementation']=True
        with self.assertRaises(ValueError):design.validate(p,d,e)

    def test_materializing_contexts_or_executing_probe_is_not_authorized(self):
        p,d,e=self.fixture()
        for field in ('implementation_authorized','execution_authorized','Jev_execution_authorized'):
            changed=deepcopy(e);changed[field]=True
            with self.assertRaises(ValueError):design.validate(p,d,changed)
        changed=deepcopy(e);changed['cases'][0]['source_context']='materialized'
        with self.assertRaises(ValueError):design.validate(p,d,changed)

    def test_exact_budget_and_route_controls_cannot_be_inflated(self):
        p,d,e=self.fixture();changed=deepcopy(e);changed['proposed_limits']['requests_max']=25
        with self.assertRaises(ValueError):design.validate(p,d,changed)
        changed=deepcopy(e);changed['cases'][0]['route']='G3_current'
        with self.assertRaises(ValueError):design.validate(p,d,changed)
        p['measurement_threshold']=.79
        with self.assertRaises(ValueError):design.validate(p,d,e)

    def test_manifest_hash_mismatch_rejected(self):
        with patch.object(design.old,'file_hash',return_value='changed'):
            with self.assertRaisesRegex(ValueError,'pin changed'):design.verify()

    def test_cli_delegates_original_design_without_changing_its_callback(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        from pastor_transcript_extractor.commands.analysis import content
        with patch.object(content,'analysis_collector_retrieval_design') as old:
            result=CliRunner().invoke(app,['analysis','collector-retrieval-design','--check-only'])
            self.assertEqual(0,result.exit_code,result.output);old.assert_called_once_with(True)

    def test_cli_proposal_only_never_loads_model(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        from pastor_transcript_extractor import collector_retrieval_encoder as encoder
        with patch.object(encoder,'LocalEncoder',side_effect=AssertionError('No model')):
            result=CliRunner().invoke(app,['analysis','collector-retrieval-design','--context-extraction-proposal','--check-only'])
        self.assertEqual(0,result.exit_code,result.output)
        self.assertIn('PROPOSAL_ONLY',result.output)
