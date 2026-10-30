from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
from pastor_transcript_extractor import profile_support_budget as g
from test_profile_support_acceptance import allowance


class AllowanceV2Tests(unittest.TestCase):
    def test_new_allowance_supersedes_unused_credit_and_cannot_reset_baseline(self):
        with TemporaryDirectory() as folder:
            base=Path(folder);spend=base/'evaluation/qualified-observations';spend.mkdir(parents=True)
            old=allowance(folder,str(spend));goal=base/'new-goal.md';goal.write_text('Additional $3 supersedes prior unused credit')
            ref,value=g.authorize_readiness(base,goal,old['path'])
            self.assertEqual(value['additional_usd'],'3');self.assertEqual(value['starting_conservative_usd'],'0.364501596')
            packet=dict(acceptance_authorization=ref,budget=dict(spend_root=str(spend),cumulative_ceiling_usd=value['cumulative_ceiling_usd']))
            self.assertEqual(str(g.ceiling(packet)),'3.364501596')
            old_packet=dict(acceptance_authorization=old,budget=dict(spend_root=str(spend),cumulative_ceiling_usd='2.5'))
            with self.assertRaisesRegex(ValueError,'superseded'):g.ceiling(old_packet)
            second,again=g.authorize_readiness(base,goal,old['path']);self.assertEqual((ref,value),(second,again))
            self.assertEqual(g.ceiling(dict(budget={})),1)
            Path(ref['path']).write_text('{}')
            with self.assertRaisesRegex(ValueError,'changed'):g.ceiling(packet)
