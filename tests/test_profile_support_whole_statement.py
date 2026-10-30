import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from pastor_transcript_extractor import profile_support_regression as r
from test_profile_analysis_support_execution import packet,wire


class WholeStatementTests(unittest.TestCase):
    def row(self):return dict(id='synthetic',candidate='A seed grows.',scope='Excerpt only.',source='A seed grows.')

    def test_reference_is_rejected_at_runtime_boundary(self):
        with self.assertRaisesRegex(ValueError,'reference'):r.case(self.row()|dict(expected='supported'))
        case=r.case(self.row());spec=r.x.make_request(case,whole_statement=True)
        self.assertNotIn('expected',json.dumps(spec.body));self.assertNotIn('reference',spec.source_identity)
        self.assertEqual(spec.source_identity['judgment_procedure'],r.x.WHOLE_STATEMENT_VERSION)
        self.assertEqual(spec.body['reasoning_effort'],'none')

    def test_opt_in_preserves_legacy_schema_body_and_cache(self):
        case=r.case(self.row());old=r.x.make_request(case);new=r.x.make_request(case,whole_statement=True)
        self.assertNotEqual(old.fingerprint,new.fingerprint)
        self.assertEqual(old,r.x.make_request(case))
        self.assertEqual(old.body['response_format'],new.body['response_format'])
        self.assertEqual(old.body['messages'][1],new.body['messages'][1])
        self.assertEqual(old.body['messages'][0]['content'],r.x.INSTRUCTION)

    def test_statement_scope_changes_are_not_same_request(self):
        case=r.case(self.row());before=deepcopy(case);spec=r.x.make_request(case,whole_statement=True)
        changed=r.case(self.row()|dict(scope='All talks.',candidate='Every seed grows.'))
        self.assertNotEqual(spec.fingerprint,r.x.make_request(changed,whole_statement=True).fingerprint)
        self.assertEqual(before,case)

    def test_valid_uncertainty_does_not_trigger_mechanical_correction(self):
        with TemporaryDirectory() as folder:
            p,out=packet(folder);p['plan']['items']=p['plan']['items'][:1];p['tasks']=p['tasks'][:1]
            task=p['tasks'][0];spec=r.x.make_request(p['plan']['items'][0]['case'],whole_statement=True)
            from dataclasses import asdict
            task.update(request=asdict(spec),token_account=spec.preflight(),correction=r.x.correction.policy(spec,headroom=True));sent=[]
            def send(s):
                sent.append(s)
                return wire(s,json.dumps(dict(judgment='unresolved',evidence=[],qualifications=[],reason='No frequency inventory.')))
            result=r.x.recipe(p,out,send)
            self.assertEqual(len(sent),1);self.assertEqual(result['accounting']['contract_corrections'],0)
            self.assertEqual(result['coverage']['by_status'],dict(unresolved=1))
