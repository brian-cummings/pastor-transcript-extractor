from dataclasses import replace
from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
import json
import unittest
from pastor_transcript_extractor import profile_analysis_support_execution as x
from test_profile_analysis_support import plan
from test_profile_analysis_support_execution import packet,wire


class CorrectionHeadroomTests(unittest.TestCase):
    def test_frozen_larger_tier_preserves_prefix_initial_identity_and_schema(self):
        spec=x.make_request(plan()['items'][0]['case']);old=deepcopy(spec);policy=x.correction.policy(spec,headroom=True)
        revised=x.correction.request(spec,'x'*22000,[dict(path='$',message='Bad JSON')],policy)
        self.assertGreater(revised.runtime_identity['input_cap'],spec.runtime_identity['input_cap'])
        self.assertEqual(revised.body['messages'][:2],spec.body['messages'])
        self.assertEqual(revised.body['messages'][2]['content'],'x'*22000)
        self.assertEqual(revised.source_identity['correction_of'],spec.fingerprint)
        self.assertEqual(revised.body['response_format'],spec.body['response_format']);self.assertEqual(spec,old)
        self.assertLessEqual(x.requests.request_reservation(revised),x.Decimal(policy['reserved_usd']))
        revised.preflight()
        with self.assertRaisesRegex(ValueError,'input exceeds'):x.correction.request(spec,'x'*22000,[],x.correction.policy(spec))

    def test_existing_successful_correction_request_is_exactly_reused(self):
        spec=x.make_request(plan()['items'][0]['case']);errors=[dict(path='$.reason',message='Missing')]
        old=x.correction.request(spec,'{}',errors,x.correction.policy(spec))
        new=x.correction.request(spec,'{}',errors,x.correction.policy(spec,headroom=True))
        self.assertEqual(old,new);self.assertEqual(old.fingerprint,new.fingerprint)

    def test_no_arbitrary_tier_or_second_correction_and_total_overflow_stops(self):
        spec=x.make_request(plan()['items'][0]['case']);policy=x.correction.policy(spec,headroom=True)
        bad=deepcopy(policy);bad['allowed_tiers'].reverse()
        with self.assertRaisesRegex(ValueError,'policy differs'):x.correction.request(spec,'{}',[],bad)
        with self.assertRaisesRegex(ValueError,'no truncation'):x.correction.request(spec,'x'*150000,[],policy)
        revised=x.correction.request(spec,'{}',[],policy)
        with self.assertRaisesRegex(ValueError,'Only one'):x.correction.request(revised,'{}',[],x.correction.policy(revised,headroom=True))

    def test_saved_initial_failure_gets_one_correction_without_regenerating_initial(self):
        with TemporaryDirectory() as folder:
            p,out=packet(folder);p['plan']['items']=p['plan']['items'][:1];p['tasks']=p['tasks'][:1];task=p['tasks'][0];spec=x.requests.RequestSpec(**task['request']);store=x._store(p,spec)
            x.requests.execute(spec,x.provider.OneRequestLedger(str(x.requests.request_reservation(spec)),spec.version),store,lambda s:wire(s,'x'*22000))
            task['correction']=x.correction.policy(spec,headroom=True);sent=[]
            def send(s):sent.append(s);return wire(s)
            r=x.recipe(p,out,send)
            self.assertEqual(len(sent),1);self.assertEqual(sent[0].source_identity['correction_of'],spec.fingerprint)
            self.assertEqual(r['results'][0]['status'],'complete')
            self.assertEqual(x.recipe(p,out,lambda s:self.fail('no duplicate')),r)
