from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import segment_profile_view as v
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal


def fixture():
    text='An exact segment <script>doBadThings()</script>.'
    block=dict(block_id=1,start_seconds=60,end_seconds=120,context=dict(target_text=text))
    s=dict(video_id=1,title='A sermon <unsafe>',url='https://www.youtube.com/watch?v=test',eligible_blocks=1,
        salvation_measured_blocks=1,eligible_block_ids=[1],treatment=[dict(block_id=1,probabilities={k:0.5 for k in v.SEMANTIC_DIMENSIONS})],
        salvation=[dict(block_id=1,probabilities={'divine_grace_initiative':0.1},observations=[])],
        topic_examples=[dict(block_id=1,label='God',topic='god',full_target_text=text,start_seconds=60,end_seconds=120,
            existing_sermon_measurement=dict(developed_emphasis_probability=0.6))])
    inventory=seal(dict(selected_profile=dict(id=318),coverage=dict(eligible_topic_blocks=1,salvation_measured_blocks=1),gaps=['Unknown position'],sermons=[s]))
    sources={1:dict(classification=dict(search=dict(topic_analysis=dict(blocks=[block]))))}
    return inventory,sources


class ProfileViewTests(unittest.TestCase):
    def test_full_source_is_escaped_and_not_treated_as_html(self):
        inventory,sources=fixture();view=v.build_view(inventory,sources);page=v.render(view)
        self.assertIn('&lt;script&gt;doBadThings()',page);self.assertNotIn('<script>doBadThings()',page)
        self.assertIn('A sermon &lt;unsafe&gt;',page);self.assertIn('measured below threshold',page)
        self.assertFalse(view['new_measurements']);self.assertFalse(view['quote_extraction'])

    def test_changed_or_ineligible_segment_fails(self):
        inventory,sources=fixture();sources[1]['classification']['search']['topic_analysis']['blocks'][0]['context']['target_text']='changed'
        with self.assertRaises(ValueError):v.build_view(inventory,sources)
        inventory,sources=fixture();body=deepcopy(inventory);body['sermons'][0]['eligible_block_ids']=[]
        with self.assertRaises(ValueError):v.build_view(seal(body),sources)

    def test_nonrecording_links_are_rejected(self):
        for url in ('javascript:alert(1)','https://example.com/fake','https://www.youtube.com.example.org/'):
            with self.assertRaises(ValueError):v.source_url(url,60)
        self.assertEqual('https://youtu.be/test?t=60',v.source_url('https://youtu.be/test',60))

    def test_cli_check_only_has_no_output_writes(self):
        from pastor_transcript_extractor.cli import app
        inventory,sources=fixture()
        with patch.object(v,'load',return_value=(inventory,sources)),patch.object(v,'prepare',side_effect=AssertionError('No writes')):
            result=CliRunner().invoke(app,['analysis','structure-readiness','--segment-view','--check-only','--json'])
            self.assertEqual(0,result.exit_code,result.output)
        result=CliRunner().invoke(app,['analysis','structure-readiness','--segment-view','--run-selection'])
        self.assertEqual(2,result.exit_code)
