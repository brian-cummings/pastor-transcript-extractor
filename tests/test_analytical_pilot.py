from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.analytical_pilot import (
    PACKET_SCHEMA, citation_audit, digest, evaluate_manifest, freeze_manifest,
    measure_segments, validate_review, write_new,
)
from pastor_transcript_extractor.sermon_analysis import ANALYZER_VERSION, SermonSegment


class AnalyticalPilotTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.base = Path(self.tempdir.name)
        self.paths = []
        for video in (1, 2):
            # A small, unequal caption duplication example. Uniform duplication
            # could cancel in density; here only the citation segment repeats.
            segments = [SermonSegment(0, 0, 10, 'John 3:16'),
                        SermonSegment(1, 10, 20, 'John 3:16'),
                        SermonSegment(2, 20, 60, 'We consider the passage together today and reflect upon its words.')]
            values = measure_segments(segments)
            packet = {
                'schema_version': PACKET_SCHEMA,
                'original': {'video_id': video, 'run_id': video, 'analyzer_version': ANALYZER_VERSION,
                             'start_seconds': 0, 'duration_seconds': 60,
                             'segments': [asdict(segment) for segment in segments],
                             'measurements': {'word_count': values['word_count'],
                                              'scripture_reference_mentions': values['detected_references'],
                                              'scripture_aligned_transcript_span_words': 0},
                             'evidence': [{'id': i, 'kind': 'scripture_reference'} for i in (1, 2)]},
                'review': {'status': 'unreviewed', 'reviewer': 'reviewer', 'reviewed_at': '2026-09-12',
                           'profile_id': video, 'identity_verified': True, 'audio_checked': True,
                           'boundaries_verified': True, 'whole_sermon_reviewed': True,
                           'transcript_method': 'rolling captions',
                           'segments': [dict(asdict(segment), source_segment_indexes=[segment.index]) for segment in segments],
                           'removed_source_segments': [],
                           'citation_episodes': [{'episode_id': 'e1', 'canonical_reference': 'John 3:16',
                                                 'source_segment_indexes': [0, 1], 'start_seconds': 0, 'end_seconds': 20}],
                           'citation_adjudications': [
                               {'evidence_id': 1, 'judgment': 'episode', 'episode_id': 'e1'},
                               {'evidence_id': 2, 'judgment': 'duplicate_caption', 'episode_id': 'e1'}]}}
            path = self.base / f'{video}.json'
            write_new(path, packet)
            self.paths.append(path)
        self.manifest = self.base / 'manifest.json'
        freeze_manifest(self.paths, self.manifest, rationale='targeted counterexamples',
                        density_iqr=1.5, span_iqr=.013, scale_source='synthetic frozen scale')

    def reviewed(self, *, remove_duplicate=False):
        for path in self.paths:
            packet = json.loads(path.read_text())
            packet['review']['status'] = 'reviewed'
            if remove_duplicate:
                packet['review']['segments'].pop(1)
                packet['review']['segments'][1]['index'] = 1
                packet['review']['removed_source_segments'] = [{'index': 1, 'reason': 'audio confirms caption duplicate'}]
            path.write_text(json.dumps(packet))

    def test_counterexample_changes_density_and_audits_duplicate_episode(self):
        self.reviewed(remove_duplicate=True)
        result = evaluate_manifest(self.manifest)
        self.assertEqual('counterexample_found', result['feature_outcomes']['references_per_1000_words'])
        self.assertEqual([], result['certified_features'])
        audit = result['sermons'][0]['citation_audit']
        self.assertEqual(.5, audit['distinct_episode_precision'])
        self.assertEqual(1, audit['episode_recall'])
        self.assertEqual(1, audit['duplicate_caption_mentions'])

    def test_unchanged_pairs_never_certify(self):
        self.reviewed()
        result = evaluate_manifest(self.manifest)
        self.assertTrue(all(value == 'not_falsified_in_selected_cases_not_certified'
                            for value in result['feature_outcomes'].values()))
        self.assertEqual([], result['certified_features'])

    def test_original_edits_and_unreviewed_packets_fail_before_detection(self):
        with patch('pastor_transcript_extractor.analytical_pilot.measure_segments') as detect:
            with self.assertRaisesRegex(ValueError, 'not reviewed'):
                evaluate_manifest(self.manifest)
            detect.assert_not_called()
        self.reviewed()
        packet = json.loads(self.paths[0].read_text())
        packet['original']['segments'][0]['text'] = 'Changed'
        self.paths[0].write_text(json.dumps(packet))
        with self.assertRaisesRegex(ValueError, 'original packet was modified'):
            evaluate_manifest(self.manifest)

    def test_duplicate_originals_cannot_expand_sample(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate original'):
            freeze_manifest([self.paths[0], self.paths[0]], self.base / 'bad.json',
                            rationale='duplicate', density_iqr=1, span_iqr=1, scale_source='test')

    def test_all_source_segments_and_detections_must_be_accounted_for(self):
        self.reviewed()
        packet = json.loads(self.paths[0].read_text())
        packet['review']['segments'].pop()
        with self.assertRaisesRegex(ValueError, 'Every original segment'):
            validate_review(packet)
        packet = json.loads(self.paths[0].read_text())
        packet['review']['citation_adjudications'].pop()
        with self.assertRaisesRegex(ValueError, 'Unreviewed citation'):
            citation_audit(packet)

    def test_genuine_repeated_spoken_citations_remain_distinct(self):
        packet = json.loads(self.paths[0].read_text())
        second = deepcopy(packet['review']['citation_episodes'][0])
        second['episode_id'] = 'e2'
        packet['review']['citation_episodes'].append(second)
        packet['review']['citation_adjudications'][1].update(judgment='episode', episode_id='e2')
        audit = citation_audit(packet)
        self.assertEqual(2, audit['reviewed_distinct_episodes'])
        self.assertEqual(1, audit['distinct_episode_precision'])
        self.assertEqual(0, audit['duplicate_caption_mentions'])

    def test_e1b_cannot_accidentally_use_e1a_as_certification(self):
        manifest = json.loads(self.manifest.read_text())
        manifest['stage'] = 'E1b_certification'
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'E1b certification is deferred'):
            evaluate_manifest(self.manifest)

    def test_code_drift_requires_a_new_design_freeze(self):
        manifest = json.loads(self.manifest.read_text())
        manifest['policy']['implementation_sha256']['sermon_analysis.py'] = 'old-code'
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'implementation changed'):
            evaluate_manifest(self.manifest)

    def test_output_is_append_only(self):
        with self.assertRaises(FileExistsError):
            write_new(self.manifest, {'replacement': True})


if __name__ == '__main__':
    unittest.main()
