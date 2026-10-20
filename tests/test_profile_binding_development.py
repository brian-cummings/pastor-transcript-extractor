from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor import profile_binding_development as dev
from pastor_transcript_extractor import automatic_proposition_binding as auto
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from test_profile_proposition_review import fixture as reference_fixture
from pastor_transcript_extractor import profile_proposition_review


def fixture():
    reviewed=profile_proposition_review.build(*reference_fixture());sources=[]
    for c in reviewed['cases']:
        source={k:deepcopy(v) for k,v in c.items() if k not in ('readings','existing_observation')}
        source['units']=auto.source_units(source['texts']);sources.append(source)
    return seal(dict(version=dev.VERSION,model=auto.MODEL,sources=sources,source_inventory_fingerprint='inventory',membership_fingerprint='membership',reference_fingerprint=reviewed['content_fingerprint'])),reviewed


class FakeProvider:
    calls=0
    def assess(self,state,inventory):
        type(self).calls+=1;answers={}
        defaults=dict(voice='preacher',speaker='preacher',occurrence='actual',adoption='own_assertion',basis='own_speech',polarity='affirmed',expression='assertion',uncertainty='not_stated',voice_evidence='e0',adoption_evidence='e0',condition_kind='none',relation='none',address='none',addressee='no_address',address_voice='preacher',address_adoption='own_or_adopted')
        for key,q in inventory.items():
            name=key.split('__')[-1]
            choice=('include' if key==next(iter(inventory)) else 'exclude') if 'source_candidates' in state else defaults.get(name,'none' if 'none' in q['criteria'] else 'unresolved')
            answers[key]=dict(choice=choice,probabilities={k:float(k==choice) for k in q['criteria']})
        return dict(answers=answers,resolved_model=auto.MODEL,usage=dict(input_tokens=10,output_tokens=20))
    def close(self):pass


class DevelopmentTests(unittest.TestCase):
    def test_no_reference_or_assurance_judgments_enter_generation_and_size_is_bounded(self):
        spec,_=fixture()
        for s in spec['sources']:
            for body in (dev.discovery_request(s),dev.binding_request(s,s['units'][:2])):
                dev.validate_request(body)
                serialized=json.dumps(body)
                for forbidden in ('reference_id','field_review','reviewed_subject_mapping','g1_record','authored_decisions'):
                    self.assertNotIn(forbidden,serialized)
            body=dev.discovery_request(s);body['state']['reviewed_answers']={}
            with self.assertRaises(ValueError):dev.validate_request(body)

    def test_cache_resume_is_provider_free_and_preserves_raw_responses_and_run_identity(self):
        spec,reviewed=fixture()
        with TemporaryDirectory() as root,patch.object(dev,'panel',return_value=(spec,reviewed)),patch.object(dev,'directory',return_value=Path(root)):
            first,folder,_=dev.execute(provider_factory=FakeProvider)
            self.assertEqual(2,first['unique_request_count'])
            self.assertEqual(dict(input_tokens=20,output_tokens=40),first['usage'])
            second,_,_=dev.execute(provider_factory=lambda:self.fail('Compatible cache must avoid provider construction'))
            self.assertEqual(first,second)
            self.assertEqual(6,dev.read(folder/'invocation-v1.json')['cache_hits'])
            cached,_,_=dev.cached();self.assertEqual(first,cached)
            self.assertEqual(2,len(list((Path(root)/'cache').glob('*.json'))))
            self.assertFalse(first['accepted_observations']);self.assertFalse(first['profile_projection'])
            for c in first['cases']:self.assertTrue(c['generated'][0]['binding']['automatic_binding'])

    def test_interrupted_attempt_is_not_silently_repeated(self):
        spec,reviewed=fixture()
        class FailingProvider(FakeProvider):
            def assess(self,*args):raise TimeoutError('Simulated transport interruption')
        with TemporaryDirectory() as root,patch.object(dev,'panel',return_value=(spec,reviewed)),patch.object(dev,'directory',return_value=Path(root)):
            with self.assertRaises(TimeoutError):dev.execute(provider_factory=FailingProvider)
            with self.assertRaisesRegex(ValueError,'ambiguous retry'):dev.execute(provider_factory=lambda:self.fail('No repeat'))

    def test_cache_seal_corruption_and_foreign_review_fail_closed(self):
        spec,reviewed=fixture()
        with TemporaryDirectory() as root,patch.object(dev,'panel',return_value=(spec,reviewed)),patch.object(dev,'directory',return_value=Path(root)):
            result,folder,_=dev.execute(provider_factory=FakeProvider)
            with self.assertRaisesRegex(ValueError,'different generated'):dev.validate_comparison(dict(generated_fingerprint='foreign',reference_fingerprint='foreign'),result,reviewed)
            path=next((Path(root)/'cache').glob('*.json'));record=json.loads(path.read_text());record['request']['state']['target_text']='foreign';path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'seal'):dev.cached()

    def test_cli_default_has_no_model_calls_and_check_only_has_no_writes(self):
        from pastor_transcript_extractor.cli import app
        spec,reviewed=fixture()
        with TemporaryDirectory() as root,patch.object(dev,'panel',return_value=(spec,reviewed)),patch.object(dev,'directory',return_value=Path(root)):
            dev.execute(provider_factory=FakeProvider)
            with patch.object(dev,'execute',side_effect=AssertionError('No model calls')):
                result=CliRunner().invoke(app,['analysis','profile-binding-development','--json']);self.assertEqual(0,result.exit_code,result.output)
            with patch.object(Path,'write_text',side_effect=AssertionError('No writes')):
                result=CliRunner().invoke(app,['analysis','profile-binding-development','--check-only','--json']);self.assertEqual(0,result.exit_code,result.output)
            result=CliRunner().invoke(app,['analysis','profile-binding-development','--run','--check-only']);self.assertEqual(2,result.exit_code)
