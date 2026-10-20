from copy import deepcopy
import json
import re
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
            choice=('complete' if key.endswith('__boundary') else 'include' if key==next(iter(inventory)) else 'exclude') if 'source_candidates' in state else defaults.get(name,'none' if 'none' in q['criteria'] else 'unresolved')
            answers[key]=dict(choice=choice,probabilities={k:float(k==choice) for k in q['criteria']})
        return dict(answers=answers,resolved_model=auto.MODEL,usage=dict(input_tokens=10,output_tokens=20))
    def close(self):pass


class DevelopmentTests(unittest.TestCase):
    def test_interpretation_consumes_prior_generated_frame_and_replay_detects_tampering(self):
        spec,reviewed=fixture()
        with TemporaryDirectory() as root,patch.object(dev,'panel',return_value=(spec,reviewed)),patch.object(dev,'directory',return_value=Path(root)):
            result,_,_=dev.execute(provider_factory=FakeProvider)
            records=[dev.read(p) for p in (Path(root)/'cache').glob('*.json')]
            dependent=next(r for r in records if any('frame_selection' in c for c in r['request']['state'].get('candidates',{}).values()))
            for c in dependent['request']['state']['candidates'].values():
                self.assertEqual('preacher',c['frame_selection']['decisions']['voice'])
            unit=spec['sources'][0]['units'][0]
            frame=next(r for r in records if 'candidates' in r['request']['state'] and all('frame_selection' not in c for c in r['request']['state']['candidates'].values()))
            bad=deepcopy(dependent);bad['request']['state']['candidates'][unit['candidate_id']]['frame_selection']['decisions']['voice']='quoted_or_reported'
            with self.assertRaisesRegex(ValueError,'frame linkage'):
                dev.compile_response(spec['sources'][0],unit,bad,spec,frame)

    def test_prepare_cli_never_constructs_provider_or_writes_files(self):
        from pastor_transcript_extractor.cli import app
        spec,reviewed=fixture()
        with patch.object(dev,'panel',return_value=(spec,reviewed)),patch.object(dev,'execute',side_effect=AssertionError('No model calls')),patch.object(Path,'write_text',side_effect=AssertionError('No writes')):
            result=CliRunner().invoke(app,['analysis','profile-binding-development','--prepare','--json'])
            self.assertEqual(0,result.exit_code,result.output)
            output=json.loads(result.output);self.assertEqual(0,output['provider_requests']);self.assertEqual(0,output['writes'])
            result=CliRunner().invoke(app,['analysis','profile-binding-development','--prepare','--run'])
            self.assertEqual(2,result.exit_code)

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
            self.assertEqual(3,first['unique_request_count'])
            self.assertEqual(dict(input_tokens=30,output_tokens=60),first['usage'])
            second,_,_=dev.execute(provider_factory=lambda:self.fail('Compatible cache must avoid provider construction'))
            self.assertEqual(first,second)
            self.assertEqual(9,dev.read(folder/'invocation-v1.json')['cache_hits'])
            cached,_,_=dev.cached();self.assertEqual(first,cached)
            self.assertEqual(3,len(list((Path(root)/'cache').glob('*.json'))))
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

    def test_resealed_generated_tampering_is_detected_by_replaying_cached_choices(self):
        spec,reviewed=fixture()
        with TemporaryDirectory() as root,patch.object(dev,'panel',return_value=(spec,reviewed)),patch.object(dev,'directory',return_value=Path(root)):
            result,folder,_=dev.execute(provider_factory=FakeProvider)
            result['cases'][0]['generated'][0]['binding']['polarity']['value']='denied'
            dev.save(folder/'generated-v1.json',result)
            with self.assertRaisesRegex(ValueError,'cached source decisions'):dev.cached()

    def test_complete_field_aware_comparison_and_source_links(self):
        spec,reviewed=fixture()
        with TemporaryDirectory() as root,patch.object(dev,'panel',return_value=(spec,reviewed)),patch.object(dev,'directory',return_value=Path(root)):
            result,folder,_=dev.execute(provider_factory=FakeProvider)
            rows=[]
            for c in reviewed['cases']:
                key=c['case_id']+'-auto-'+result['cases'][0]['generated'][0]['candidate_id']
                for r in c['readings']:
                    rows.append(dict(reference_id=r['binding']['binding_id'],generated_ids=[key],content_recovery='located',fully_faithful=True,summary='Authored fixture comparison, not a semantic evaluation.',correctly_unresolved='Permanent security is not established.',fields={f:dict(outcome='agreement',finding='Fixture source and generated field agree within scope.',evidence=[r['binding']['proposition']['span']]) for f in dev.FIELDS}))
            comparison=dict(generated_fingerprint=result['content_fingerprint'],reference_fingerprint=reviewed['content_fingerprint'],readings=rows,extra_generated={},decision=dict(answer='no',finding='Mock fixture only.',recommendation='No live performance inferred from this unit test.'))
            dev.save(folder/'semantic-review-v1.json',comparison)
            report,page=dev.report();html=page.read_text();md=page.with_name('review-v1.md').read_text()
            self.assertEqual('DEVELOPMENT_RUN_COMPARED',report['status'])
            self.assertEqual(dict(located=10,fully_faithful=10),report['development_summary'])
            self.assertEqual({f:{'agreement':10} for f in dev.FIELDS},report['field_outcomes'])
            ids=re.findall(r' id="([^"]+)"',html)
            self.assertEqual(len(ids),len(set(ids)))
            self.assertLessEqual(set(re.findall(r'href="#([^"]+)"',html)),set(ids))
            self.assertIn('Exact source evidence',md);self.assertIn('index.html#C0-target_text',md)
            bad=deepcopy(comparison);bad['readings'][0]['fields'].pop('adoption')
            with self.assertRaisesRegex(ValueError,'all fields'):dev.validate_comparison(bad,result,reviewed)
            bad=deepcopy(comparison);bad['readings'][0]['fully_faithful']=False;bad['readings'][0]['fields']['adoption'].update(outcome='attribution_adoption_error',evidence=[])
            with self.assertRaisesRegex(ValueError,'exact source evidence'):dev.validate_comparison(bad,result,reviewed)
            bad=deepcopy(comparison);bad['readings'][0]['generated_ids']=['foreign']
            with self.assertRaisesRegex(ValueError,'foreign candidate'):dev.validate_comparison(bad,result,reviewed)

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
