from copy import deepcopy
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor import profile_proposition_review as review
from pastor_transcript_extractor import profile_binding_pilot as pilot
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from test_profile_binding_pilot import fixture as old_fixture
from test_theological_binding import fixture as generic_fixture


def fixture():
    inputs,definitions,contexts=old_fixture()
    first=definitions['cases'][0]['readings'][0]
    for n in range(7):
        row=deepcopy(first);row['id']=f'extra-{n}';row['unit']['candidate_id']=row['id']
        definitions['cases'][0]['readings'].append(row)
    baseline=pilot.build(inputs,definitions,contexts)
    readings=[]
    for case in baseline['cases']:
        for old in case['readings']:
            _,row,_=generic_fixture(case['texts']['target_text'])
            row['binding_id']=old['id'];row['title']='<Review safely>'
            row['proposition']['node_id']=old['id']+':claim';row['evidence_nodes'][0]['node_id']=row['proposition']['node_id']
            readings.append(row)
    authored=dict(version='profile-proposition-source-readings-v1',baseline_report_fingerprint=baseline['content_fingerprint'],baseline_input_sha256='reviewed',readings=readings)
    return baseline,authored


class PropositionReviewTests(unittest.TestCase):
    def test_ten_bindings_preserve_all_original_G1_records_and_source_envelopes(self):
        baseline,authored=fixture();before=deepcopy((baseline,authored))
        report=review.build(baseline,authored)
        self.assertEqual(before,(baseline,authored))
        for source,case in zip(baseline['cases'],report['cases']):
            self.assertEqual(source['texts'],case['texts'])
            self.assertEqual(source['existing_observation'],case['existing_observation'])
            for old,new in zip(source['readings'],case['readings']):
                self.assertEqual(old['g1_record'],new['assurance_interpretation']['g1_record'])
                self.assertEqual(old['unit']['claim_span'],new['binding']['proposition']['span'])
                self.assertEqual(source['source_sha256'],new['binding']['provenance']['source_sha256'])
        self.assertEqual(10,sum(len(c['readings']) for c in report['cases']))
        for key in ('automatic_binding','new_measurements','new_discovery','broader_collection','profile_projection','benchmark_comparison','new_scoring','quote_execution'):
            self.assertFalse(report[key],key)

    def test_missing_duplicate_stale_or_retargeted_readings_are_rejected(self):
        for change in ('missing','duplicate','baseline','retarget'):
            baseline,authored=fixture()
            if change=='missing':authored['readings'].pop()
            elif change=='duplicate':authored['readings'][-1]=deepcopy(authored['readings'][0])
            elif change=='baseline':authored['baseline_report_fingerprint']='stale'
            else:authored['readings'][0]['proposition']['span']['text']='invented'
            with self.assertRaises(ValueError):review.build(baseline,authored)

    def test_narrow_no_match_does_not_erase_generic_proposition_or_copy_generic_adoption(self):
        baseline,authored=fixture()
        row=baseline['cases'][0]['readings'][0]
        row['authored_decisions'].update(relation='no_match',polarity='unclear',adoption='undetermined')
        row['g1_record']=pilot.compile_reading('C0',baseline['cases'][0]['texts'],row)['g1_record']
        baseline=seal(baseline);authored['baseline_report_fingerprint']=baseline['content_fingerprint']
        result=review.build(baseline,authored)['cases'][0]['readings'][0]
        self.assertEqual('own_assertion',result['binding']['adoption']['status'])
        self.assertEqual('no_match',result['assurance_interpretation']['mapping_status'])
        self.assertEqual('undetermined',result['assurance_interpretation']['g1_record']['adoption'])
        self.assertTrue(result['binding']['proposition']['reading'])

    def test_authored_ten_case_input_pins_the_unchanged_original_readings_and_reused_contracts(self):
        from pastor_transcript_extractor.evidence_pipeline_trace import digest,ROOT
        data=json.loads(review.READINGS_PATH.read_text());old=json.loads(pilot.READINGS_PATH.read_text())
        self.assertEqual(digest(pilot.READINGS_PATH),data['baseline_input_sha256'])
        self.assertEqual({r['id'] for c in old['cases'] for r in c['readings']},{r['binding_id'] for r in data['readings']})
        for path,sha in data['reused_contracts'].items():self.assertEqual(sha,digest(ROOT/path))
        readings={r['binding_id']:r for r in data['readings']}
        for key in ('P2-paul','P2-warning'):
            self.assertEqual('discourse_use',readings[key]['adoption']['basis'])
            self.assertEqual('adopted',readings[key]['adoption']['status'])
        self.assertEqual('projected',readings['P3-forgiveness']['voice']['occurrence'])
        self.assertEqual('question',readings['P3-invitation']['expression']['value'])
        self.assertEqual('not_stated',readings['P3-invitation']['epistemic_status']['value'])
        self.assertEqual([],readings['P2-saving-desire']['conditions'])
        self.assertTrue(readings['P2-saving-desire']['qualifications'])
        self.assertEqual('reason_supports_claim',readings['P2-warning']['development_relations'][0]['kind'])
        self.assertEqual('undetermined',readings['P2-middle-report']['adoption']['status'])

    def test_reported_speech_is_not_displayed_as_attested_historical_speech(self):
        self.assertEqual('reported speech',review.voice_label(dict(kind='quoted_or_reported',occurrence='actual')))
        self.assertEqual('projected speech',review.voice_label(dict(kind='quoted_or_reported',occurrence='projected')))

    def test_html_markdown_links_evidence_limits_and_escaping(self):
        report=review.build(*fixture());page=review.render(report);md=review.markdown(report)
        self.assertIn('&lt;Review safely&gt;',page);self.assertNotIn('<Review safely>',page)
        ids=re.findall(r' id="([^"]+)"',page)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertLessEqual(set(re.findall(r'href="#([^"]+)"',page)),set(ids))
        self.assertIn('At a glance',page);self.assertIn('Unknown or withheld',page)
        self.assertIn('Smallest next remedy',page);self.assertIn('Original G1 record unchanged',md)
        self.assertIn('profile-proposition-review --check-only',md)
        self.assertIn('characters 0',page)

    def test_cli_check_only_has_no_artifact_writes_and_generation_is_immutable(self):
        from pastor_transcript_extractor.cli import app
        report=review.build(*fixture())
        with patch.object(review,'load',return_value=report),patch.object(review,'prepare',side_effect=AssertionError('No artifact writes')):
            result=CliRunner().invoke(app,['analysis','profile-proposition-review','--check-only','--json'])
            self.assertEqual(0,result.exit_code,result.output);self.assertIsNone(json.loads(result.output)['path'])
        with TemporaryDirectory() as root,patch.object(review,'load',return_value=report),patch.object(review,'build_paths',return_value=SimpleNamespace(evaluation=Path(root))):
            result=CliRunner().invoke(app,['analysis','profile-proposition-review','--json'])
            self.assertEqual(0,result.exit_code,result.output)
            data=json.loads(result.output);page=Path(data['path'])
            self.assertTrue(page.is_file());self.assertEqual(10,data['proposed_readings'])
            self.assertEqual(report['content_fingerprint'],data['fingerprint'])
            manifest=json.loads(page.with_name('readings-v1.json').read_text())
            self.assertIn(str(Path(review.generic.__file__)),manifest['implementation_files'])
            self.assertEqual(report,manifest['report'])
            _,same=review.prepare();self.assertEqual(page,same)
            page.write_text('changed')
            with self.assertRaisesRegex(ValueError,'Immutable'):review.prepare()
