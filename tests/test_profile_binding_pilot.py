from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor import profile_binding_pilot as p


TEXT = 'You can know now that you are accepted by God.'  # Existing frozen G1 A01 control.


def span(text, phrase, field='target_text'):
    start = text.index(phrase)
    return dict(source_field=field,start=start,end=start+len(phrase),text=phrase)


def row():
    claim = span(TEXT,TEXT)
    return dict(id='reading',title='A supplied assertion',proposed_reading='Present acceptance can be known.',
        unit=dict(candidate_id='reading',claim_span=claim),
        phrase_pools=dict(objects={'object':span(TEXT,'accepted by God')},conditions={},uncertainty={},scopes={'scope':span(TEXT,'now')},frames={'voice':claim,'adoption':claim}),
        authored_decisions=dict(subject='salvation_acceptance',relation='acceptance_knowable_now',polarity='affirmed',expression='assertion',voice='preacher',adoption='own_assertion',epistemic_status='not_stated',boundary='local_sufficient',object_anchor='object',epistemic_evidence='none',scope_evidence='scope',voice_evidence='voice',adoption_evidence='adoption'),
        field_review={field:dict(status='supported',finding='Authored control reading <unsafe>.',evidence=[claim]) for field in p.FIELDS},additional_binding_evidence=[],withheld_conclusions=['Permanent security is not stated.'],contract_gap_ids=[])


def fixture():
    contexts = {}; supplied = []; authored = []
    for index in range(3):
        key = f'e-{index}'
        context = dict(target_text=TEXT,leading_context='A supplied preceding statement.',trailing_context='',diagnostics={'trailing':{'available':False}})
        contexts[key] = context
        supplied.append(dict(evidence_id=key,title='Supplied source',sermon_title='A sermon <unsafe>',video_id=index,block_id=1,source_sha256='source',full_target_text=TEXT,start_seconds=0,end_seconds=60,watch_url='https://youtu.be/test?t=0',current_state='measured_below_threshold',probability=.1,threshold=.7))
        reading = row();reading['id']=f'reading-{index}';reading['unit']['candidate_id']=reading['id']
        authored.append(dict(case_id=f'C{index}',evidence_id=key,source_sha256='source',target_sha256=p.text_digest(TEXT),context_sha256=p.text_digest(json.dumps(context,sort_keys=True,ensure_ascii=False)),readings=[reading]))
    record = dict(inventory_fingerprint='inventory',profile={'membership_fingerprint':'membership'},capability_review={'cases':supplied})
    definitions = dict(inventory_fingerprint='inventory',membership_fingerprint='membership',cases=authored)
    return record,definitions,contexts


class BindingPilotTests(unittest.TestCase):
    def test_existing_positive_control_uses_unchanged_composer(self):
        texts = dict(target_text=TEXT,leading_context='',trailing_context='')
        original = row();before=deepcopy(original)
        result = p.compile_reading('A01',texts,original)
        self.assertEqual(before,original)
        self.assertEqual('local_claim',result['g1_record']['observation_state'])
        self.assertTrue(result['g1_record']['provisional_adopted_local_assertion'])
        self.assertEqual('now',result['g1_record']['scope_text'])

    def test_no_match_retains_known_voice_and_adoption_without_inventing_position(self):
        reading=row();reading['authored_decisions'].update(relation='no_match',polarity='unclear')
        result=p.compile_reading('control',dict(target_text=TEXT,leading_context='',trailing_context=''),reading)['g1_record']
        self.assertEqual('no_in_scope_claim',result['observation_state'])
        self.assertEqual('preacher',result['voice']);self.assertEqual('own_assertion',result['adoption'])
        self.assertFalse(result['provisional_adopted_local_assertion'])
        self.assertIsNone(result['pastor_projection'])

    def test_fabricated_or_context_only_assertions_are_rejected(self):
        texts=dict(target_text=TEXT,leading_context=TEXT,trailing_context='')
        reading=row();reading['unit']['claim_span']['text']='Unconditional permanent security'
        with self.assertRaises(ValueError):p.compile_reading('control',texts,reading)
        reading=row();reading['unit']['claim_span']['source_field']='leading_context'
        with self.assertRaisesRegex(ValueError,'target claim'):p.compile_reading('control',texts,reading)
        reading=row();reading['phrase_pools']['frames']['voice']=dict(reading['phrase_pools']['frames']['voice'],source_field='leading_context')
        with self.assertRaisesRegex(ValueError,'framing'):p.compile_reading('control',texts,reading)

    def test_new_vocabulary_and_unsupported_uncertainty_are_rejected(self):
        texts=dict(target_text=TEXT,leading_context='',trailing_context='')
        reading=row();reading['authored_decisions']['relation']='mercy_as_saving_ground'
        with self.assertRaisesRegex(ValueError,'new G1 choice'):p.compile_reading('control',texts,reading)
        reading=row();reading['authored_decisions']['epistemic_status']='expressed_uncertainty'
        with self.assertRaisesRegex(ValueError,'uncertainty requires'):p.compile_reading('control',texts,reading)

    def test_unrelated_or_context_condition_is_not_silently_bound(self):
        texts=dict(target_text=TEXT,leading_context='if trust continues',trailing_context='')
        reading=row();reading['phrase_pools']['conditions']['c']=span(texts['leading_context'],'if trust continues','leading_context')
        reading['authored_decisions']['bind_c']='bound'
        with self.assertRaisesRegex(ValueError,'context-only'):p.compile_reading('control',texts,reading)
        reading['authored_decisions']['bind_c']='not_bound'
        self.assertEqual([],p.compile_reading('control',texts,reading)['g1_record']['conditions'])

    def test_source_membership_context_and_fixed_case_changes_fail_closed(self):
        for change in ('membership','source','context','case'):
            record,definitions,contexts=fixture()
            if change=='membership':record['profile']['membership_fingerprint']='changed'
            elif change=='source':record['capability_review']['cases'][0]['source_sha256']='changed'
            elif change=='context':contexts['e-0']['leading_context']='changed'
            else:definitions['cases'].pop()
            with self.assertRaises(ValueError):p.build(record,definitions,contexts)

    def test_pilot_does_not_mutate_observations_publish_profiles_or_execute_models(self):
        inputs=fixture();before=deepcopy(inputs)
        with patch('pastor_transcript_extractor.sermon_g1_feasibility_review.Provider',side_effect=AssertionError('No provider')):
            report=p.build(*inputs)
        self.assertEqual(before,inputs)
        self.assertEqual([],report['published_profile_positions'])
        for key in ('automatic_binding','new_measurements','new_discovery','broader_collection','collector_changes','threshold_changes','profile_projection','quote_execution','contract_extended'):
            self.assertFalse(report[key],key)
        self.assertTrue(report['source_review_executed'])

    def test_all_fields_literal_evidence_and_internal_links_are_present(self):
        report=p.build(*fixture());page=p.render(report)
        self.assertIn('&lt;unsafe&gt;',page);self.assertNotIn('<unsafe>',page)
        ids=re.findall(r' id="([^"]+)"',page)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertLessEqual(set(re.findall(r'href="#([^"]+)"',page)),set(ids))
        for case in report['cases']:
            for reading in case['readings']:
                self.assertEqual(set(p.FIELDS),set(reading['field_review']))
                for review in reading['field_review'].values():
                    for evidence in review['evidence']:p.validate_span(evidence,case['texts'])
        self.assertIn('No unambiguous positive condition/exception',page)

    def test_check_only_has_no_writes_and_default_emits_actual_results(self):
        from pastor_transcript_extractor.cli import app
        report=p.build(*fixture())
        with patch.object(p,'load',return_value=report),patch.object(p,'prepare',side_effect=AssertionError('No writes')):
            result=CliRunner().invoke(app,['analysis','profile-binding-review','--check-only','--json'])
            self.assertEqual(0,result.exit_code,result.output)
        with TemporaryDirectory() as root,patch.object(p,'load',return_value=report),patch.object(p,'build_paths',return_value=SimpleNamespace(evaluation=Path(root))):
            result=CliRunner().invoke(app,['analysis','profile-binding-review','--json'])
            self.assertEqual(0,result.exit_code,result.output)
            data=json.loads(result.output);self.assertEqual(3,data['passages'])
            self.assertEqual(report['content_fingerprint'],data['fingerprint'])
            directory=Path(data['path']).parent
            self.assertTrue((directory/'readings-v1.md').exists())
            self.assertTrue((directory/'readings-v1.json').exists())
            before=(directory/'index.html').read_bytes();p.prepare()
            self.assertEqual(before,(directory/'index.html').read_bytes())

    def test_authored_readings_do_not_extend_the_frozen_g1_contract(self):
        definitions=json.loads(p.READINGS_PATH.read_text())
        self.assertEqual(definitions['contract_sha256'],p.trace.digest(p.trace.ROOT/definitions['contract_path']))
        self.assertEqual(definitions['composer_sha256'],p.trace.digest(p.trace.ROOT/definitions['composer_path']))
        self.assertEqual(3,len(definitions['cases']))
        self.assertEqual('source_reviewed_theological_proposition_binding',definitions['capability'])
