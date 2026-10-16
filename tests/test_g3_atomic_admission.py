"""Focused A1 real guard/export tests with synthetic receipts and test trust roots.

Synthetic receipt seals are confined to tests; real replay reads immutable V4 bytes.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor import g3_atomic_admission as a1
from pastor_transcript_extractor import evidence_boundary_admission as v4
from pastor_transcript_extractor import evidence_supply_boundary_v4 as panel
import test_evidence_boundary_admission as helpers


def write_sealed(path, value):
    value = {k: v for k, v in value.items() if k != 'content_fingerprint'}
    value['content_fingerprint'] = panel.old.frozen.fp(value)
    path.write_text(json.dumps(value, indent=2) + '\n')
    return value


def claim_row(measurement, facts, policy):
    d = measurement.document
    target = d['binding']['roles']['utterance']
    ns = 'G3_current_preacher_act' if facts['origin'] == 'present_preacher' else 'G3_reported_local_act'
    return dict(version=a1.WITNESS, case_id=d['case_id'], policy_fingerprint=policy['content_fingerprint'],
        measurement_fingerprint=measurement.fingerprint, binding=d['binding'], scope='atomic_act_only', namespace=ns,
        utterance=target, acts={a: dict(support=target, rationale='Test exact-utterance support.')
            for a in v4.ACTS if d['decisions'].get(a) == 'observed'},
        source_voice={k: d['decisions'][k] for k in ('voice', 'addressee', 'adoption')},
        conditions_and_limits=dict(complete=True, spans=[], rationale='Test explicit completeness; whole exact utterance retained.'),
        provenance_support={k: dict(value=facts[k], span=d['binding']['source_envelope'], rationale='Test supplied-envelope identity.')
            for k in ('origin', 'voice', 'addressee', 'adoption')},
        complete_for_exported_acts=True, no_omitted_act_or_qualifier_required=True,
        context_used_only_for_identity_stance_and_interpretation=True,
        excluded_claims=['circumstance_connection', 'pastor_projection', 'quality', 'outcome'], rationale='Test bounded authority.')


class AtomicAdmissionTests(unittest.TestCase):
    measurement = helpers.AdmissionTests.measurement
    facts = helpers.AdmissionTests.facts
    authority = helpers.AdmissionTests.authority

    @classmethod
    def setUpClass(cls):
        cls.packet = json.loads(panel.INPUT.read_text())
        cls.oracle = json.loads((panel.HERE / 'source-oracle-v4.json').read_text())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.boundary = v4.Boundary(self.packet)

    def current(self, **changes):
        return self.measurement('B4-R018', {'boundary': 'unclear', 'challenge': 'observed', 'invitation': 'observed', **changes})

    def reported(self):
        return self.measurement('B4-R053', {'boundary': 'unclear', 'challenge': 'observed', 'reassurance': 'observed',
            'voice': 'quoted_or_reported', 'addressee': 'reported_person', 'adoption': 'not_adopted_report',
            'circumstance_relevance': 'unclear', 'recipient_circumstance_binding': 'unclear'})

    def configured(self, measurements, edit=None, overrides=None, accepted=True):
        source = self.authority(measurements, overrides)
        policy = write_sealed(self.root / 'policy.json', dict(version=a1.POLICY, item_version=a1.VERSION,
            witness_version=a1.WITNESS, scope='atomic_act_only', implementation_sha256=a1.file_hash(Path(a1.__file__)),
            threshold=.80, allowed_boundary_decisions=['local_sufficient', 'unclear'], provider_calls=0, circumstance_claim=None,
            packet_fingerprint=self.packet['content_fingerprint'], source_review_decision_sha256=source.decision_sha256))
        write_sealed(self.root / 'authorization.json', dict(version='atomic-a1-implementation-replay-authorization', status='AUTHORIZED',
            decision_owner='Brian', implementation_authorized=True, provider_free_replay_authorized=True, provider_calls_authorized=False,
            policy_fingerprint=policy['content_fingerprint'], policy_file_sha256=a1.file_hash(self.root / 'policy.json')))
        pa = a1.PolicyAuthority.load(self.root / 'policy.json', self.root / 'authorization.json', a1.file_hash(self.root / 'authorization.json'))
        rows = [claim_row(m, source.witness(self.packet['content_fingerprint'], m)['facts'], policy)
                for m in measurements if m.document['capability'] == 'G3']
        if edit: edit(rows)
        rp, dp = self.root / 'claims.json', self.root / 'claims-accepted.json'
        review = write_sealed(rp, dict(version=a1.WITNESS, policy_fingerprint=policy['content_fingerprint'],
            packet_fingerprint=self.packet['content_fingerprint'], rows=rows))
        write_sealed(dp, dict(version='atomic-claim-review-acceptance-a1', status='ACCEPTED' if accepted else 'PREPARED',
            closed=True, decision_owner='Brian', scope='bounded_atomic_local_replay_only', review_file_sha256=a1.file_hash(rp),
            review_fingerprint=review['content_fingerprint'], policy_fingerprint=policy['content_fingerprint']))
        ca = a1.ClaimAuthority.load(rp, dp, a1.file_hash(dp), policy)
        return a1.Boundary(self.packet, source, pa, ca)

    def test_current_reported_and_unchanged_G2_reach_actual_consumer(self):
        measurements = [self.current(), self.reported(), self.measurement('B4-R003')]
        b = self.configured(measurements)
        wires = []
        for m in measurements:
            raw = m.document_json
            item = b.admit(m).item
            self.assertIsNotNone(item)
            wires.append(b.export(item))
            self.assertEqual(raw, m.document_json)
        result = b.consume_local(wires)
        self.assertEqual({'G3_current_preacher_act', 'G3_reported_local_act', 'G2_adopted_bible_explanation'},
                         {i['namespace'] for i in result['items']})
        self.assertTrue(all(i['circumstance_claim'] is None for i in result['items']))
        self.assertEqual(b.base.export(b.base.admit(measurements[2]).item), wires[2])
        with self.assertRaisesRegex(ValueError, 'Duplicate'): b.consume_local(wires + wires[:1])

    def test_missing_review_and_missing_witness_block(self):
        m = self.current(); b = self.configured([m])
        b.claim_authority = None
        self.assertIsNone(b.admit(m).item)
        b = self.configured([m], lambda rows: rows.clear())
        self.assertIsNone(b.admit(m).item)
        with self.assertRaises(ValueError): self.configured([m], accepted=False)

    def test_definite_continuation_required_cannot_be_overridden(self):
        m = self.current(boundary='continuation_required'); b = self.configured([m])
        self.assertIn('atomic_boundary_requires_deferral', b.admit(m).reasons)

    def test_local_sufficient_still_needs_new_claim_authority(self):
        m = self.current(boundary='local_sufficient'); b = self.configured([m])
        self.assertIsNotNone(b.base.admit(m).item)
        b.claim_authority = None
        self.assertIsNone(b.admit(m).item)

    def test_review_cannot_fill_unknown_or_incompatible_measurements(self):
        for changes in ({'voice': 'unresolved'}, {'addressee': 'unresolved'}, {'adoption': 'unresolved'},
                        {'voice': 'quoted_or_reported'}, {'recipient_circumstance_binding': 'bound_in_target'},
                        {'concrete_care': 'observed'}):
            with self.subTest(changes=changes):
                m = self.current(**changes); b = self.configured([m])
                self.assertIsNone(b.admit(m).item)

    def test_review_cannot_manufacture_a_withheld_act(self):
        m = self.current(invitation='unclear', challenge='not_observed'); b = self.configured([m])
        self.assertIsNone(b.admit(m).item)

    def test_each_observed_act_requires_exact_claim_coverage(self):
        for edit in (lambda row: row['acts'].pop('challenge'),
                     lambda row: row['acts'].update(concrete_care=dict(support=row['utterance'], rationale='extra'))):
            m = self.current(); b = self.configured([m], lambda rows: edit(rows[0]))
            with self.assertRaisesRegex(ValueError, 'every measured positive'): b.admit(m)

    def test_missing_unknown_and_wrong_scope_sufficiency_block(self):
        edits = [lambda r: r.pop('complete_for_exported_acts'),
                 lambda r: r.update(complete_for_exported_acts=None),
                 lambda r: r.update(scope='circumstance_connection'),
                 lambda r: r.update(measurement_fingerprint='different'),
                 lambda r: r.update(policy_fingerprint='different'),
                 lambda r: r.update(namespace='G3_reported_local_act')]
        for edit in edits:
            with self.subTest(edit=edit):
                m = self.current(); b = self.configured([m], lambda rows: edit(rows[0]))
                with self.assertRaises((ValueError, KeyError)): b.admit(m)

    def test_context_cannot_lend_act_provenance_or_qualifier(self):
        m = self.current()
        for edit in (lambda r: r['acts']['invitation'].update(support=m.document['binding']['source_envelope']),
                     lambda r: r['conditions_and_limits'].update(spans=[m.document['binding']['source_envelope']]),
                     lambda r: r['provenance_support']['voice'].update(span=dict(start=0,end=1,text='x'))):
            b = self.configured([m], lambda rows: edit(rows[0]))
            with self.assertRaises(ValueError): b.admit(m)

    def test_incomplete_targets_or_context_cannot_be_waived(self):
        for facts in ({'target_complete': False}, {'context_complete': None}):
            m = self.current(); b = self.configured([m], overrides={'B4-R018': facts})
            self.assertIsNone(b.admit(m).item)

    def test_actual_wire_cannot_forge_scope_fields_or_drop_conditions(self):
        m = self.current(); b = self.configured([m]); item = b.admit(m).item
        for key, value in [('namespace', 'G3_reported_local_act'), ('circumstance_claim', 'bound'),
                           ('conditions_and_limits', {}), ('evidence_scope', 'pastor_profile'),
                           ('policy_fingerprint', 'different'), ('claim_review_decision_sha256', 'different')]:
            wire = json.loads(b.export(item)); wire['item'][key] = value
            with self.subTest(key=key):
                with self.assertRaises(ValueError): b.consume_local([json.dumps(wire)])
        with self.assertRaises(ValueError): b.base.deserialize(b.export(item))
        with self.assertRaises(ValueError): b.deserialize(json.dumps(m.document))
        with self.assertRaises(ValueError): b.export(m.document)

    def test_V4_G3_wire_cannot_fallback_into_A1(self):
        m = self.current(boundary='local_sufficient'); b = self.configured([m])
        old_wire = b.base.export(b.base.admit(m).item)
        with self.assertRaisesRegex(ValueError, 'fallback'): b.consume_local([old_wire])

    def test_post_load_policy_review_receipt_and_envelope_edits_rejected(self):
        m = self.current(); b = self.configured([m]); item = b.admit(m).item
        for key in ('receipts', 'binding', 'decisions'):
            doc = m.document
            if key == 'receipts': doc[key][0]['fingerprint'] = 'changed'
            elif key == 'binding': doc[key]['source_envelope']['text'] += 'x'
            else: doc[key]['boundary'] = 'local_sufficient'
            with self.assertRaises(ValueError): b.admit(v4.Measurement(v4.canonical(doc)))
        b.claim_authority.review_path.write_text('{}')
        with self.assertRaises(ValueError): b.export(item)
        b = self.configured([m]); item = b.admit(m).item
        b.policy_authority.policy_path.write_text('{}')
        with self.assertRaises(ValueError): b.export(item)

    def test_critical_cases_block_even_with_positive_synthetic_raw_and_claim_reviews(self):
        for rid in ('R021', 'R080', 'R078', 'R073', 'R111', 'R114', 'R076'):
            with self.subTest(case=rid):
                m = self.measurement('B4-' + rid, {'challenge': 'observed', 'invitation': 'observed',
                    'reassurance': 'observed', 'boundary': 'unclear'})
                b = self.configured([m])
                self.assertIsNone(b.admit(m).item)
                with self.assertRaises(ValueError): b.export(a1.AtomicLocalEvidence('{}', m))
