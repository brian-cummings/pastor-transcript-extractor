from copy import deepcopy
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import minute_evidence_handoff as h


class ProposalTests(unittest.TestCase):
    def test_frozen_proposal_scope(self):
        import json
        p=json.loads((h.HERE/'proposal-v1.json').read_text());h.validate(p)
        for key,value in [('provider_execution_authorized',True),('semantics_changes',True),('nomination_backend','openai')]:
            changed=deepcopy(p);changed[key]=value
            with self.assertRaises(ValueError):h.validate(changed)
        changed=deepcopy(p);changed['context_policy']['automatic_expansion']=True
        with self.assertRaises(ValueError):h.validate(changed)
        changed=deepcopy(p);changed['measurement_admission']['automatic_authority_transfer']=True
        with self.assertRaises(ValueError):h.validate(changed)

    def test_cli_verifies_only_and_rejects_conflicting_modes(self):
        from pastor_transcript_extractor.cli import app
        with patch.object(h,'verify',return_value=dict(status='IMPLEMENTATION_PROPOSAL_ONLY',content_fingerprint='synthetic')):
            result=CliRunner().invoke(app,['analysis','structure-readiness','--handoff-proposal','--check-only'])
            self.assertEqual(0,result.exit_code,result.output);self.assertIn('provider_requests=0',result.output)
        result=CliRunner().invoke(app,['analysis','structure-readiness','--handoff-proposal','--evidence-trace'])
        self.assertEqual(2,result.exit_code)
