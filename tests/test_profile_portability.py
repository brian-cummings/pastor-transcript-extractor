"""Focused selection, withholding and CLI checks; no application dataset access."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor import profile_portability as p
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from test_profile_description import fixture


def sample():
    inv, sources = fixture()
    inv = deepcopy(inv)
    sermon = inv['sermons'][0]
    inv['selected_profile']['id'] = 130
    inv['sermons'] = [dict(deepcopy(sermon), video_id=vid) for vid in p.VIDEO_IDS]
    inv['coverage']['eligible_topic_blocks'] = 3
    return seal(inv), {vid: deepcopy(sources[9]) for vid in p.VIDEO_IDS}


class PortabilityTests(unittest.TestCase):
    def test_only_prepared_case_is_allowed_before_database_access(self):
        with patch.object(p.segment_cache_inventory, 'build', side_effect=AssertionError('Must not read')):
            for invalid in (318, 80, -1):
                with self.assertRaisesRegex(ValueError, 'Only prepared'):
                    p.load(profile_id=invalid)

    def test_foreign_or_incomplete_sample_is_rejected(self):
        inv, sources = fixture()
        with self.assertRaisesRegex(ValueError, 'Foreign'):
            p.assemble(inv, sources, [], {})
        inv, sources = sample(); inv['sermons'].pop()
        with self.assertRaisesRegex(ValueError, 'Foreign'):
            p.assemble(seal(inv), sources, [], {})

    def test_changed_or_missing_authored_support_cannot_inherit_318(self):
        inv, sources = sample()
        packet = json.loads(p.INPUT_PATH.read_text())
        result = p.assemble(inv, sources, [], packet)
        self.assertFalse(result['reader']['portrait']['entries'])
        self.assertFalse(result['evidence_supply']['reviewed_bound_records'])
        self.assertFalse(result['authoring_disclosure']['automatic_discovery'])
        self.assertEqual(['adopted theological center', 'pastoral posture'], result['authoring_disclosure']['unknown_facets'])
        self.assertEqual(3, len(result['reader']['portrait']['withheld']))
        rows = {r['label']: r for r in result['reader']['at_a_glance']}
        self.assertEqual('gap-style', rows['Potential strength']['target'])
        self.assertIn('unknown', rows['Pastoral approach']['description'])
        self.assertFalse(result['provider_requests'])
        self.assertFalse(result['new_measurements'])

    def test_cli_routes_only_explicit_selection_and_check_only_never_prepares(self):
        from pastor_transcript_extractor.cli import app
        from pastor_transcript_extractor import profile_description as baseline
        inv, sources = sample()
        record = p.assemble(inv, sources, [], json.loads(p.INPUT_PATH.read_text()))
        with patch.object(p, 'load', return_value=record) as selected, patch.object(p, 'prepare', side_effect=AssertionError('No write')), patch.object(baseline, 'load', side_effect=AssertionError('No baseline fallback')):
            result = CliRunner().invoke(app, ['analysis','structure-readiness','--segment-view','--description','--profile-id','130','--check-only','--json'])
            self.assertEqual(0, result.exit_code, result.output)
            selected.assert_called_once_with(None, profile_id=130)
            self.assertEqual(list(p.VIDEO_IDS), json.loads(result.output)['recording_ids'])
        result = CliRunner().invoke(app, ['analysis','structure-readiness','--profile-id','130'])
        self.assertNotEqual(0, result.exit_code)
        self.assertIn('requires', result.output)
