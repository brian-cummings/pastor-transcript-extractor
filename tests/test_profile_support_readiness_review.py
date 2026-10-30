from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
from pastor_transcript_extractor import profile_support_readiness_review as r


class ReadinessReviewTests(unittest.TestCase):
    def test_reuse_inspects_existing_constituents_without_new_measurement(self):
        with TemporaryDirectory() as folder:
            source=Path(folder)/'source.json';source.write_text('{}')
            record=dict(profile=dict(id=7),source_identity=[dict(video_id=9)],evidence_supply=dict(reviewed_bound_records=[{}],reviewed_binding_checks=['unchanged']))
            inv=dict(sermons=[dict(video_id=9,source_path=str(source))],coverage=dict(approved_salvation_leaves=['approved'],unresolved_salvation_leaves=['held']))
            checks=[dict(attempts=[dict(state='absent_exact_identity')],matches=[])]
            with patch.object(r.inventory_module,'build',return_value=inv) as build,patch.object(r.supply,'inspect',return_value=checks) as inspect:
                result=r.reuse_audit(record,Path(folder))
            build.assert_called_once_with(Path(folder),profile_id=7,video_ids=[9]);inspect.assert_called_once_with(inv,{9:{}})
            self.assertEqual(result['exact_identities'],1);self.assertEqual(result['compatible_answers'],0)
            self.assertEqual(result['bound_reuse']['records'],1)
            self.assertEqual(result['compatible_materialized_layers']['unresolved_salvation_leaves'],['held'])
            self.assertIn('particular public-life proposition',result['missing_producer_contracts']['public-life-specificity']['existing'])

    def test_source_review_reference_is_exact(self):
        with TemporaryDirectory() as folder:
            p=Path(folder)/'source.json';p.write_text('{}');before=r.reference(p);p.write_text('{ }')
            self.assertNotEqual(before,r.reference(p))

    def test_holdout_metadata_does_not_silently_truncate_a_larger_inventory(self):
        from types import SimpleNamespace
        class Connection:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def execute(self,*args):return [dict(video_id=n,run_id=n) for n in range(13)]
        fake=SimpleNamespace(connect=lambda:Connection())
        with patch('pastor_transcript_extractor.storage.Database',return_value=fake),patch.object(r.inventory_module,'build') as build:
            with self.assertRaisesRegex(ValueError,'freeze a selection'):r.holdout_audit(Path('/tmp/test-base'),Path('/tmp/prior'))
        build.assert_not_called()
