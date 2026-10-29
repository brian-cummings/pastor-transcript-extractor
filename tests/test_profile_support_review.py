from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import json
import unittest
from pastor_transcript_extractor import profile_support_review as r


class ReviewPacketTests(unittest.TestCase):
    def test_reverse_packet_keeps_unselected_sermon_text_and_source_indexes(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'source.json';raw=dict(sermon_window=dict(start_seconds=30,end_seconds=700),segments=[dict(start_seconds=a,end_seconds=b,text=t) for a,b,t in [(0,10,'outside'),(20,40,'crossing'),(50,60,'not in cited blocks'),(650,690,'ending')]],classification={})
            path.write_text(json.dumps(raw));source=dict(video_id=8,title='Synthetic sermon',source_path=str(path),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            record=dict(source_identity=[source],observations=[dict(video_id=8,block_id=1)])
            with patch.object(r.core,'resolve_topic_analysis_artifact',return_value=dict(blocks=[dict(block_id=1,projection_eligibility=dict(eligible=True)),dict(block_id=2,projection_eligibility=dict(eligible=True))])):
                report=r.sources(record,Path(folder)/'review')
            row=report['sources'][0];self.assertEqual(row['segment_count'],3);self.assertEqual(row['unmaterialized_eligible_blocks'],[2]);self.assertEqual(len(row['review_files']),2)
            text=Path(row['review_files'][0]['path']).read_text();self.assertIn('not in cited blocks',text);self.assertNotIn('outside',text)
            saved=json.loads((Path(folder)/'review/video-8-part-01.json').read_text());self.assertEqual([s['index'] for s in saved['segments']],[1,2]);self.assertFalse(saved['runtime_evidence'])
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError,'changed'):r.sources(record,Path(folder)/'other')
