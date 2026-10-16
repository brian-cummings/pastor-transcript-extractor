"""Small synthetic fresh sources; never reopen the old panel or call a provider."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor import fresh_evidence_adapter as fresh
from pastor_transcript_extractor import g3_atomic_admission as a1
from pastor_transcript_extractor import fresh_discovery_preparation as prep
import test_g3_atomic_admission as helpers
import test_evidence_boundary_admission as receipt_helpers


class FreshAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.source=prep.seal(dict(video_id=900001,text='Salvation can be lost. Matthew 5:1 says grace. This means grace is a gift. Will you come to Christ?',
            main_span=dict(start=0,end=97)))
        self.source['main_span']['end']=len(self.source['text']);self.source=prep.seal(self.source)
        self.path=self.root/'source.json';helpers.write_sealed(self.path,self.source)
        t=self.source['text'];span=lambda phrase:dict(start=t.index(phrase),end=t.index(phrase)+len(phrase),text=phrase)
        g1=next(c for c in prep.baseline.discover(self.source)[0] if c['capability']=='G1')
        g2=prep.collector.represent(self.source,'G2',dict(left=span('Matthew 5:1 says grace.'),right=span('This means grace is a gift.')))
        g2['candidate_id']='900001:G2:test'
        g3=prep.collector.represent(self.source,'G3',dict(utterance=span('Will you come to Christ?'),circumstance=None))
        g3['candidate_id']='900001:G3:test'
        entries=[dict(candidate=g1,automatic_envelope=dict(status='prepared_not_attested'))]
        entries += [dict(candidate=c,automatic_envelope=prep.automatic_envelope(self.source,c)) for c in (g2,g3)]
        cases=[];requests=[]
        for e in entries:
            c,rs=fresh.materialize_case(self.source,e);cases.append(c);requests.extend(rs)
        info={'900001':dict(path=str(self.path),sha256=a1.file_hash(self.path))}
        inventory=prep.seal(dict(source_files=info,inventories=[dict(entries=entries)],queue=[dict(status='prepared',candidate_id=e['candidate']['candidate_id']) for e in entries]))
        prep.save_new(self.root/'natural-inventory-v1.json',inventory)
        self.packet=prep.seal(dict(version=fresh.VERSION,model=prep.MODEL,provider_calls_authorized=False,runtime_root=str(self.root),
            inventory_fingerprint=inventory['content_fingerprint'],inventory_sha256=a1.file_hash(self.root/'natural-inventory-v1.json'),
            source_files=info,code_hashes={str(Path(fresh.__file__).relative_to(prep.proposal.ROOT)):a1.file_hash(Path(fresh.__file__))},cases=cases,requests=requests))
        self.base=fresh.MeasurementBoundary(self.packet,self.packet['content_fingerprint'])

    def measurement(self,cap,changes=None):
        c=next(c for c in self.packet['cases'] if c['capability']==cap)
        return self.base.measure(c['case_id'],[receipt_helpers.receipt(r,self.packet,changes) for r in self.packet['requests'] if r['case_id']==c['case_id']])

    def configured(self,m,facts):
        review=helpers.write_sealed(self.root/'review.json',dict(version='receipt-bound-source-review-v4',packet_fingerprint=self.packet['content_fingerprint'],rows=[dict(case_id=m.document['case_id'],measurement_fingerprint=m.fingerprint,binding=m.document['binding'],source_support=[m.document['binding']['source_envelope']],facts=facts)]))
        rp=self.root/'review.json';dp=self.root/'decision.json'
        helpers.write_sealed(dp,dict(version='source-review-acceptance-v4',status='ACCEPTED',closed=True,decision_owner='Brian',scope='local_boundary_admission_only',review_file_sha256=a1.file_hash(rp),review_fingerprint=review['content_fingerprint'],packet_fingerprint=self.packet['content_fingerprint']))
        source=a1.v4.ReviewAuthority.load(rp,dp,a1.file_hash(dp))
        pp=self.root/'policy.json';ap=self.root/'auth.json'
        p=helpers.write_sealed(pp,dict(version=a1.POLICY,item_version=a1.VERSION,witness_version=a1.WITNESS,scope='atomic_act_only',implementation_sha256=a1.file_hash(Path(a1.__file__)),threshold=.8,allowed_boundary_decisions=['local_sufficient','unclear'],provider_calls=0,circumstance_claim=None,packet_fingerprint=self.packet['content_fingerprint'],source_review_decision_sha256=source.decision_sha256))
        helpers.write_sealed(ap,dict(version='atomic-a1-implementation-replay-authorization',status='AUTHORIZED',decision_owner='Brian',implementation_authorized=True,provider_free_replay_authorized=True,provider_calls_authorized=False,policy_fingerprint=p['content_fingerprint'],policy_file_sha256=a1.file_hash(pp)))
        policy=a1.PolicyAuthority.load(pp,ap,a1.file_hash(ap))
        claims=None
        if m.document['capability']=='G3':
            cr=self.root/'claims.json';ca=self.root/'claim-accepted.json'
            value=helpers.write_sealed(cr,dict(version=a1.WITNESS,policy_fingerprint=p['content_fingerprint'],packet_fingerprint=self.packet['content_fingerprint'],rows=[helpers.claim_row(m,facts,p)]))
            helpers.write_sealed(ca,dict(version='atomic-claim-review-acceptance-a1',status='ACCEPTED',closed=True,decision_owner='Brian',scope='bounded_atomic_local_replay_only',review_file_sha256=a1.file_hash(cr),review_fingerprint=value['content_fingerprint'],policy_fingerprint=p['content_fingerprint']))
            claims=a1.ClaimAuthority.load(cr,ca,a1.file_hash(ca),p)
        return fresh.Boundary(self.packet,self.packet['content_fingerprint'],source,policy,claims)

    def test_fresh_identity_is_not_a_V4_packet_or_caller_self_upgrade(self):
        fresh.validate_packet(self.packet)
        with self.assertRaises(ValueError):fresh.MeasurementBoundary(self.packet,'wrong-approved-fingerprint')
        from pastor_transcript_extractor import evidence_supply_boundary_v4 as old
        with self.assertRaises(ValueError):old.validate_packet(self.packet)

    def test_resealed_question_or_context_changes_rejected(self):
        for field in ('questions','state'):
            p=deepcopy(self.packet);r=p['requests'][0]
            if field=='questions':r[field]['boundary']['instructions']['task']='easier question'
            else:r[field]['target_text']='different target'
            p=prep.seal(p)
            with self.assertRaisesRegex(ValueError,'question/state'):fresh.validate_packet(p)

    def test_positive_G2_and_atomic_G3_traverse_real_fresh_consumer(self):
        for cap in ('G2','G3'):
            changes={'invitation':'observed','boundary':'unclear'} if cap=='G3' else {}
            m=self.measurement(cap,changes)
            facts=dict(context_complete=True,target_complete=True,origin='present_preacher',voice='preacher',addressee='direct_current_listener',adoption='own_or_adopted',addressed_human_utterance=True,supported_acts=['invitation']) if cap=='G3' else dict(context_complete=True,target_complete=True,anchor_family='biblical',edge_kind='explanatory',left_voice='quoted_or_reported',right_voice='preacher',adoption='own_or_adopted')
            b=self.configured(m,facts);item=b.admit(m).item
            self.assertIsNotNone(item)
            self.assertEqual(1,len(b.consume_local([b.export(item)])['items']))
            wire=json.loads(b.export(item));wire['item']['namespace']='fake-current-pastor'
            with self.assertRaises(ValueError):b.consume_local([json.dumps(wire)])

    def test_unsupported_G3_act_or_unknown_provenance_stays_blocked(self):
        for change in ({'invitation':'observed','voice':'unresolved'},{'invitation':'observed','concrete_care':'observed'}):
            m=self.measurement('G3',change)
            facts=dict(context_complete=True,target_complete=True,origin='present_preacher',voice='preacher',addressee='direct_current_listener',adoption='own_or_adopted',addressed_human_utterance=True,supported_acts=['invitation'])
            self.assertIsNone(self.configured(m,facts).admit(m).item)

    def test_G1_does_not_receive_atomic_boundary_exception(self):
        c=next(c for c in self.packet['cases'] if c['capability']=='G1')
        selected={k:next(iter(q['criteria'])) for r in self.packet['requests'] if r['case_id']==c['case_id'] for k,q in r['questions'].items()}
        selected.update(subject='salvation_acceptance',relation='loss_possible',polarity='affirmed',expression='assertion',voice='preacher',adoption='own_assertion',boundary='local_sufficient',epistemic_status='not_stated')
        m=self.measurement('G1',selected)
        facts=dict(context_complete=True,target_complete=True,origin='present_preacher',g1_decisions=m.document['decisions'])
        b=self.configured(m,facts);item=b.admit(m).item
        self.assertIsNotNone(item)
        self.assertEqual('G1_reviewed_local_assurance',b.consume_local([b.export(item)])['items'][0]['namespace'])
        selected['boundary']='unclear';m=self.measurement('G1',selected);facts['g1_decisions']=m.document['decisions']
        self.assertIsNone(self.configured(m,facts).admit(m).item)

    def test_materializer_preserves_exact_utterance_and_contiguous_context(self):
        c=next(c for c in self.packet['cases'] if c['capability']=='G3')
        acts=next(r for r in self.packet['requests'] if r['case_id']==c['case_id'] and r['phase']=='G3_acts_and_source_only')
        self.assertEqual(c['candidate']['endpoints']['utterance']['text'],acts['state']['target_text'])
        self.assertEqual(c['source_envelope']['text'],''.join(acts['state'][k] for k in ('leading_context','target_text','trailing_context')))
