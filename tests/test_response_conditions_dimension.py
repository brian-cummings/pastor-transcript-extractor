from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import response_conditions_dimension as dimension
from pastor_transcript_extractor import response_growth_binding as producer
from pastor_transcript_extractor import profile_section as section
from test_profile_section import reading


class ResponseConditionsTests(unittest.TestCase):
    def test_selection_ignores_order_text_and_answers_excludes_development_and_overlap(self):
        sources=[dict(video_id=v,eligible_block_ids=list(range(1,140)),text='ignored',answers=[1])
            for v in (281,3973,4589)]
        selected=dimension.select_confirmation(sources)
        changed=deepcopy(list(reversed(sources)))
        for s in changed:
            s['text']='different';s['answers']=[0];s['eligible_block_ids'].reverse()
        self.assertEqual(selected,dimension.select_confirmation(changed))
        self.assertEqual(4,len(selected));seen=set()
        development={(v,b) for v,a,z in section.WINDOWS for b in range(a,z+1)}
        for c in selected:
            keys={(c['video_id'],b) for b in range(c['first'],c['last']+1)}
            self.assertFalse(keys & (seen|development));seen.update(keys)

    def test_opt_in_recipe_changes_only_source_request_preserves_old_request_and_verifier(self):
        window,spec,_,checked=reading()
        revised=producer.request(window,response_conditions=True)
        self.assertNotEqual(spec.fingerprint,revised.fingerprint)
        self.assertEqual(spec,producer.request(window))
        self.assertEqual(spec.body['response_format'],revised.body['response_format'])
        self.assertEqual(spec.body['model'],revised.body['model'])
        self.assertEqual(asdict(producer.dimension_verification(window,checked['observations'])),
            asdict(producer.dimension_verification(window,deepcopy(checked['observations']))))
        self.assertIn('meaning-changing condition',revised.body['messages'][0]['content'])
        self.assertIn('reported or performed',revised.body['messages'][0]['content'])

    def test_sample_keeps_withheld_points_saturation_and_no_score_or_false_denominator(self):
        window,_,_,checked=reading();o=checked['observations'][0]
        finding=dict(observation_id=o['id'],field='requested_response',value='A proposed response',
            eligible=False,checks={'requested_response':dict(resolved=False)},verification_request='request')
        p=dict(profile=dict(id=318,membership_fingerprint='member'),
            response_conditions_goal=dict(phase='development',freeze={'path':'frozen'}),
            tasks=[dict(id=window.id,window=asdict(window))],limitation='Selected sample')
        with TemporaryDirectory() as directory:
            root=Path(directory);dest=root/'sources'/window.id;dest.mkdir(parents=True)
            (dest/'result.json').write_text(json.dumps(dict(status='COMPLETE',source_status='saturated',observations=[o])))
            record=dict(machine_observations=[o],dimension_findings=[finding],dimension_packets={window.id:{'result':'proof'}})
            result=dimension.sample_record(p,root,record)
            self.assertEqual('withheld',result['findings'][0]['eligibility'])
            self.assertIsNone(result['aggregation']['score']);self.assertIsNone(result['aggregation']['denominator'])
            self.assertEqual([],result['aggregation']['eligible_finding_ids'])
            self.assertEqual('saturated',result['opportunities'][0]['recovery_state'])
            self.assertFalse(result['opportunities'][0]['absence_proven'])
            self.assertNotIn('conditions',result['findings'][0])

    def test_confirmation_cannot_run_changed_implementation(self):
        freeze=dict(development=[[281,1,3]],confirmation=[dict(video_id=281,first=5,last=7)])
        p=dict(response_conditions_goal=dict(phase='confirmation',freeze=dict(path='selection',sha256='sha'),
            module_sha256='sha',implementation_freeze=dict(path='lock',sha256='sha')),code_identity={'changed':1})
        with patch.object(dimension,'read_freeze',return_value=freeze),patch.object(dimension,'file_hash',return_value='sha'),\
             patch.object(Path,'read_text',return_value=json.dumps(dict(code_identity={'original':1},module_sha256='sha'))):
            with self.assertRaisesRegex(ValueError,'unchanged'):
                dimension.validate_plan(p)
