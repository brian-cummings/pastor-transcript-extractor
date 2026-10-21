from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor import connected_binding_diagnostics as d
from test_connected_proposition_binding import fixture,invitation
from test_connected_binding_development import fixture as panel_fixture,FakeProvider


class RejectionDiagnosticsTests(unittest.TestCase):
    def test_independent_failures_are_all_visible_without_repair_or_mutation(self):
        raw,source,_=fixture();raw['frames'][0]['evidence']=[]
        p=raw['propositions'][0];p['span']['occurrence_index']=27
        p['adoption'].update(status='adopted',basis='explicit_rejection',evidence=[])
        p['polarity']['evidence']=[];p['expression']['evidence']=[];p['unknowns']=['']
        before=deepcopy(raw);result=d.inspect_payload(raw,source['texts'])
        self.assertEqual(before,raw)
        self.assertIn('missing_attribution_evidence',result['frames'][0]['errors'])
        self.assertEqual('occurrence_index_out_of_range',result['propositions'][0]['span']['error'])
        for name in ('missing_adoption_evidence','adopted_with_incompatible_basis','missing_polarity_evidence','missing_expression_evidence','blank_unknowns'):
            self.assertIn(name,result['propositions'][0]['errors'])
        self.assertIsNone(result['propositions'][0]['span']['validated_span'])
        self.assertEqual([0],result['propositions'][0]['span']['available_starts'])

    def test_absent_text_is_distinct_from_bad_occurrence_and_impossible_parentage(self):
        raw,source,_=invitation();raw['frames'][0]['span']['text']='Can you say,'
        raw['frames'][1]['span']['occurrence_index']=90
        raw['propositions'][1]['span']['text']='The shepherd abandons me.'
        result=d.inspect_payload(raw,source['texts'])
        self.assertIn('no_literal_child_occurrence_fits_parent',result['frames'][1]['errors'])
        self.assertEqual('text_not_present',result['propositions'][1]['span']['error'])
        self.assertEqual([],result['propositions'][1]['span']['available_starts'])

    def test_valid_synthetic_frames_are_not_flagged_and_bad_schema_stays_visible(self):
        raw,source,_=invitation();result=d.inspect_payload(raw,source['texts'])
        self.assertTrue(all(not f['errors'] for f in result['frames']))
        self.assertTrue(all(not p['errors'] for p in result['propositions']))
        result=d.inspect_payload({'frames':[]},source['texts']);self.assertTrue(result['schema_error'])

    def test_cached_audit_cli_preserves_generated_records_and_requires_no_backend(self):
        from pastor_transcript_extractor.cli import app
        spec,ref=panel_fixture()
        with TemporaryDirectory() as root,patch.object(d.dev,'panel',return_value=(spec,ref)),patch.object(d.dev,'directory',return_value=Path(root)):
            generated,folder,_=d.dev.execute(provider_factory=FakeProvider)
            before=(folder/'generated-v1.json').read_bytes()
            with patch.object(d.dev,'urlopen',side_effect=AssertionError('No network')):
                result=CliRunner().invoke(app,['analysis','profile-connected-binding','--diagnostics','--json'])
            self.assertEqual(0,result.exit_code,result.output)
            output=json.loads(result.output);self.assertEqual(0,output['provider_requests']);self.assertEqual(0,output['metadata_reads'])
            self.assertEqual(3,output['summary']['raw_propositions'])
            self.assertEqual(before,(folder/'generated-v1.json').read_bytes())
            self.assertIn('not an accepted source quote',Path(output['path']).read_text())
            result=CliRunner().invoke(app,['analysis','profile-connected-binding','--diagnostics','--run']);self.assertEqual(2,result.exit_code)
