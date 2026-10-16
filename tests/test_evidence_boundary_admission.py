"""Actual V4 guard/export integration with injected receipts, never provider calls.

Temporary ACCEPTED review decisions are explicit test trust roots, not real reviews.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import evidence_boundary_admission as gate
from pastor_transcript_extractor import evidence_supply_boundary_v4 as panel


def receipt(request, packet, changes=None):
    selected = {'explains_text': 'linked', 'left_voice': 'quoted_or_reported', 'right_voice': 'preacher',
                'voice': 'preacher', 'addressee': 'direct_current_listener', 'adoption': 'own_or_adopted',
                'boundary': 'local_sufficient', 'circumstance_relevance': 'not_relevant',
                'recipient_circumstance_binding': 'not_bound', **(changes or {})}
    answers = {}
    for key, question in request['questions'].items():
        name = key.removeprefix('p0_')
        choice = selected.get(name, 'not_observed')
        answers[key] = dict(type='choice', choice=choice, confidence=.99,
                            probabilities={option: float(option == choice) for option in question['criteria']})
    return panel.old.seal(dict(input_fingerprint=packet['content_fingerprint'], request_key=request['request_key'],
                               response=dict(status_code=200, body=json.dumps(dict(model=packet['model'], answers=answers,
                                                                                 usage=dict(input_tokens=1, output_tokens=1))))))


class AdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = json.loads(panel.INPUT.read_text())
        cls.oracle = json.loads((panel.HERE / 'source-oracle-v4.json').read_text())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.boundary = gate.Boundary(self.packet)

    def measurement(self, case_id, changes=None):
        requests = [r for r in self.packet['requests'] if r['case_id'] == case_id]
        return self.boundary.measure(case_id, [receipt(r, self.packet, changes) for r in requests])

    def facts(self, case_id):
        return deepcopy(next(r['preliminary_facts'] for r in self.oracle['rows'] if r['case_id'] == case_id))

    def authority(self, measurements, overrides=None):
        rows = []
        for m in measurements:
            d = m.document
            facts = self.facts(d['case_id'])
            facts.update((overrides or {}).get(d['case_id'], {}))
            rows.append(dict(case_id=d['case_id'], binding=d['binding'], measurement_fingerprint=m.fingerprint,
                             source_support=[d['binding']['source_envelope']], facts=facts))
        review = dict(version='receipt-bound-source-review-v4', packet_fingerprint=self.packet['content_fingerprint'], rows=rows)
        review['content_fingerprint'] = panel.old.frozen.fp(review)
        rp = self.root / 'review.json'; rp.write_text(json.dumps(review))
        decision = dict(version='source-review-acceptance-v4',status='ACCEPTED', closed=True, decision_owner='Brian', scope='local_boundary_admission_only',
                        packet_fingerprint=self.packet['content_fingerprint'], review_fingerprint=review['content_fingerprint'],
                        review_file_sha256=panel.old.frozen.v1.file_hash(rp))
        decision['content_fingerprint'] = panel.old.frozen.fp(decision)
        dp = self.root / 'decision.json'; dp.write_text(json.dumps(decision))
        return gate.ReviewAuthority.load(rp, dp, panel.old.frozen.v1.file_hash(dp))

    def test_seven_critical_mechanisms_block_real_export_with_positive_raw_answers(self):
        cases = {'R021': {}, 'R080': {}, 'R053': {'challenge': 'observed', 'reassurance': 'observed'},
                 'R078': {'reassurance': 'observed'}, 'R111': {'invitation': 'observed', 'concrete_care': 'observed'},
                 'R114': {'invitation': 'observed'}, 'R076': {'challenge': 'observed'}}
        for rid, changes in cases.items():
            with self.subTest(case=rid):
                m = self.measurement('B4-' + rid, changes)
                before = m.document_json
                boundary = gate.Boundary(self.packet, self.authority([m]))
                verdict = boundary.admit(m)
                self.assertIsNone(verdict.item)
                self.assertTrue(verdict.reasons)
                self.assertEqual(before, m.document_json)
                with self.assertRaises(ValueError):
                    boundary.export(gate.LocalEvidence(gate.canonical({'positive_facts': {'challenge': 'observed'}}), m))

    def test_positive_G2_current_and_reported_reach_real_serialized_consumer(self):
        measured = [self.measurement('B4-R003'), self.measurement('B4-R018', {'challenge': 'observed', 'invitation': 'observed'}),
                    self.measurement('B4-R073', {'challenge': 'observed', 'voice': 'quoted_or_reported', 'addressee': 'reported_person',
                                                'adoption': 'not_adopted_report', 'circumstance_relevance': 'relevant_in_target',
                                                'recipient_circumstance_binding': 'bound_in_target'})]
        boundary = gate.Boundary(self.packet, self.authority(measured))
        wires = []
        for m in measured:
            verdict = boundary.admit(m)
            self.assertEqual((), verdict.reasons)
            wires.append(boundary.export(verdict.item))
        view = boundary.consume_local(wires)
        self.assertEqual({'G2_adopted_bible_explanation', 'G3_current_preacher_act', 'G3_reported_local_act'}, {i['namespace'] for i in view['items']})
        self.assertTrue(all(i['circumstance_claim'] is None for i in view['items']))
        self.assertIsNone(view['pastor_projection'])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            boundary.consume_local(wires + wires[:1])

    def test_prepared_oracle_and_missing_review_cannot_admit(self):
        m = self.measurement('B4-R003')
        self.assertIsNone(self.boundary.admit(m).item)
        with self.assertRaisesRegex(ValueError, 'not accepted'):
            gate.Boundary(self.packet, self.oracle)
        with self.assertRaises(ValueError):
            self.boundary.export(m.document)
        with self.assertRaises(ValueError):
            self.boundary.deserialize(json.dumps(m.document))

    def test_deserialize_rechecks_modified_namespace_and_positive_facts(self):
        m = self.measurement('B4-R073', {'challenge': 'observed', 'voice': 'quoted_or_reported', 'addressee': 'reported_person',
                                       'adoption': 'not_adopted_report', 'circumstance_relevance': 'relevant_in_target',
                                       'recipient_circumstance_binding': 'bound_in_target'})
        b = gate.Boundary(self.packet, self.authority([m])); item = b.admit(m).item
        wire = json.loads(b.export(item)); wire['item']['namespace'] = 'G3_current_preacher_act'
        with self.assertRaises(ValueError): b.deserialize(json.dumps(wire))
        wire = json.loads(b.export(item)); wire['item']['positive_facts']['reassurance'] = 'observed'
        with self.assertRaises(ValueError): b.deserialize(json.dumps(wire))
        wire = json.loads(b.export(item)); wire['version'] = 'future-unknown'
        with self.assertRaises(ValueError): b.deserialize(json.dumps(wire))

    def test_changed_measurement_and_new_receipt_cannot_reuse_witness(self):
        m = self.measurement('B4-R003'); b = gate.Boundary(self.packet, self.authority([m]))
        changed = m.document; changed['decisions']['adoption'] = 'not_adopted_report'
        with self.assertRaisesRegex(ValueError, 'changed'):
            b.admit(gate.Measurement(gate.canonical(changed)))
        different = self.measurement('B4-R003', {'right_voice': 'quoted_or_reported'})
        with self.assertRaisesRegex(ValueError, 'Stale'):
            b.admit(different)
        with self.assertRaises(ValueError):
            b.admit(m.document)

    def test_accepted_review_edits_after_load_are_rejected(self):
        m = self.measurement('B4-R003'); authority = self.authority([m]); b = gate.Boundary(self.packet, authority)
        authority.review_path.write_text('{}')
        with self.assertRaises(ValueError): b.admit(m)

    def test_null_binding_and_unsupported_extra_act_quarantine_whole_row(self):
        for changes in ({'invitation': 'observed', 'recipient_circumstance_binding': 'bound_in_target'},
                        {'invitation': 'observed', 'concrete_care': 'observed'}):
            m = self.measurement('B4-R018', changes); b = gate.Boundary(self.packet, self.authority([m]))
            self.assertIsNone(b.admit(m).item)

    def test_withholding_not_filled_from_witness(self):
        for changes in ({'invitation': 'observed', 'voice': 'unresolved'},
                        {'invitation': 'observed', 'adoption': 'unresolved'},
                        {'invitation': 'observed', 'boundary': 'unclear'}):
            m = self.measurement('B4-R018', changes); b = gate.Boundary(self.packet, self.authority([m]))
            self.assertIsNone(b.admit(m).item)

    def test_probability_gate_not_confidence_controls_decisions(self):
        case_id = 'B4-R018'; requests = [r for r in self.packet['requests'] if r['case_id'] == case_id]
        values = [receipt(r, self.packet, {'invitation': 'observed'}) for r in requests]
        raw = json.loads(values[0]['response']['body']); a = raw['answers']['invitation']; a['confidence'] = .999
        a['probabilities'] = {'observed': .79, 'not_observed': .21, 'incomplete': 0., 'unclear': 0.}
        values[0]['response']['body'] = json.dumps(raw); values[0] = panel.old.seal({k:v for k,v in values[0].items() if k!='fingerprint'})
        m = self.boundary.measure(case_id, values)
        self.assertEqual('unclear', m.document['decisions']['invitation'])
        self.assertEqual('observed', m.document['phases'][0]['raw_answers']['invitation']['choice'])
        b = gate.Boundary(self.packet, self.authority([m])); self.assertIsNone(b.admit(m).item)

    def test_binding_phase_inserted_act_wrong_order_and_cross_case_receipts_rejected(self):
        reqs = [r for r in self.packet['requests'] if r['case_id']=='B4-R018']; values = [receipt(r,self.packet) for r in reqs]
        with self.assertRaises(ValueError): self.boundary.measure('B4-R018',list(reversed(values)))
        with self.assertRaises(ValueError): self.boundary.measure('B4-R057',values)
        raw=json.loads(values[1]['response']['body']);raw['answers']['challenge']=dict(type='choice',choice='observed',confidence=1.,probabilities={'observed':1.,'not_observed':0.,'incomplete':0.,'unclear':0.})
        values[1]['response']['body']=json.dumps(raw);values[1]=panel.old.seal({k:v for k,v in values[1].items() if k!='fingerprint'})
        with self.assertRaises(ValueError): self.boundary.measure('B4-R018',values)

    def test_narration_next_to_real_reassurance_keeps_exact_act_target(self):
        case = next(c for c in self.packet['cases'] if c['case_id']=='B4-R078')
        info=self.packet['source_files']['4430'];source=json.loads((panel.old.frozen.ROOT/info['path']).read_text())
        lo=source['text'].index('if you confess your sins',29000);hi=case['source_envelope']['end']
        context=dict(start=lo,end=hi,text=source['text'][lo:hi]); built=gate.materialize(source,'G3',case['candidate']['endpoints'],context)
        act=built['shapes'][0]['state'];self.assertIn('faithful and just',act['leading_context'])
        self.assertEqual('And I encouraged him and we prayed together',act['target_text'])
        self.assertEqual(context['text'],act['leading_context']+act['target_text']+act['trailing_context'])
        with self.assertRaises(gate.EnvelopeUnavailable):gate.materialize(source,'G3',case['candidate']['endpoints'],context,maximum=10)

    def test_full_G2_G3_interpretation_uses_real_export_and_consumer(self):
        changes = {'B4-R018': {'invitation':'observed'}, 'B4-R073': {'challenge':'observed', 'voice':'quoted_or_reported',
                   'addressee':'reported_person', 'adoption':'not_adopted_report', 'circumstance_relevance':'relevant_in_target',
                   'recipient_circumstance_binding':'bound_in_target'}}
        receipts = [receipt(r,self.packet,changes.get(r['case_id'])) for r in self.packet['requests']]
        bykey = {r['request_key']:r for r in receipts}
        measurements = [self.boundary.measure(c['case_id'],[bykey[k] for k in c['request_keys']]) for c in self.packet['cases']]
        authority = self.authority(measurements)
        with patch.object(gate.Boundary, 'export', autospec=True, side_effect=gate.Boundary.export) as export:
            result = panel.interpret_receipts(self.packet,receipts,authority)
        self.assertEqual(24,len(result['observations']))
        namespaces={i['namespace'] for i in result['local_evidence']['items']}
        self.assertEqual({'G2_adopted_bible_explanation','G3_current_preacher_act','G3_reported_local_act'},namespaces)
        self.assertGreater(export.call_count,3)
        self.assertIsNone(result['pastor_projection'])
        self.assertEqual('pending_full_source_audit',result['raw_semantic_verdict'])
        with self.assertRaises(ValueError):panel.interpret_receipts(self.packet,receipts[:-1],authority)
        with self.assertRaises(ValueError):panel.interpret_receipts(self.packet,receipts+[receipts[0]],authority)

    def test_conditions_cannot_be_stripped_during_export(self):
        m=self.measurement('B4-R077-complete-promise',{'reassurance':'observed','voice':'quoted_or_reported','addressee':'reported_person',
           'adoption':'not_adopted_report','circumstance_relevance':'relevant_in_target','recipient_circumstance_binding':'bound_in_target'})
        b=gate.Boundary(self.packet,self.authority([m]));item=b.admit(m).item
        self.assertIsNotNone(item)
        wire=json.loads(b.export(item));self.assertTrue(wire['item']['roles']['utterance']['text'].startswith('if you confess'))
        wire['item']['roles']['utterance']['text']='he is faithful and just to forgive your sins'
        with self.assertRaises(ValueError):b.deserialize(json.dumps(wire))

    def test_wrong_trust_digest_and_unaccepted_review_rejected(self):
        m=self.measurement('B4-R003');auth=self.authority([m])
        with self.assertRaises(ValueError):gate.ReviewAuthority.load(auth.review_path,auth.decision_path,'untrusted')
        value=json.loads(auth.decision_path.read_text());value['status']='PREPARED'
        value['content_fingerprint']=panel.old.frozen.fp({k:v for k,v in value.items() if k!='content_fingerprint'})
        auth.decision_path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):gate.ReviewAuthority.load(auth.review_path,auth.decision_path,panel.old.frozen.v1.file_hash(auth.decision_path))

    def test_unknown_source_support_and_scope_cannot_become_current_credit(self):
        m=self.measurement('B4-R018',{'invitation':'observed'})
        for facts in ({'context_complete':None},{'target_complete':False},{'origin':None},
                      {'voice':None},{'addressee':None},{'adoption':None}):
            b=gate.Boundary(self.packet,self.authority([m],{'B4-R018':facts}))
            self.assertIsNone(b.admit(m).item)

    def test_raw_V4_and_serialized_item_cannot_bypass_through_legacy_consumer(self):
        from pastor_transcript_extractor import observed_profile
        m=self.measurement('B4-R003');b=gate.Boundary(self.packet,self.authority([m]))
        item=b.admit(m).item
        for raw in (m.document,json.loads(item.document_json),json.loads(b.export(item))):
            with self.assertRaises(ValueError):observed_profile._validate_evidence([raw])
