"""Versioned fresh-packet adapter. No provider path, old-panel rewrite or oracle.

G2/G3 retain V4/A1 invariants. G1 is independently source-reviewed under its
closed assurance fields; it never receives the atomic G3 boundary exception.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from pastor_transcript_extractor import fresh_discovery_preparation as prep
from pastor_transcript_extractor import g3_atomic_admission as a1
from pastor_transcript_extractor import sermon_g1_feasibility_revision as g1

v4=a1.v4
VERSION='fresh-semantic-packet-v1'
G1_VERSION='fresh-reviewed-assurance-evidence-v1'


def request(case,shape):
    value=dict(version='fresh-semantic-request-v1',case_id=case['case_id'],capability=case['capability'],
        model=prep.MODEL,phase=shape['phase'],state=shape['state'],questions=shape['questions'],question_version=shape['question_version'])
    value['request_key']=prep.baseline.fp(value)
    return value


def materialize_case(source,entry):
    c,env=entry['candidate'],entry['automatic_envelope']
    if env['status']!='prepared_not_attested':raise ValueError('Deferred envelope cannot supply requests')
    cap=c['capability']
    if cap=='G1':
        candidate={**c,'endpoints':dict(claim=c['claim'])}
        lo=c['target']['start']-len(c['leading_context']);hi=c['target']['end']+len(c['trailing_context'])
        envelope=dict(start=lo,end=hi,text=source['text'][lo:hi])
        state={k:c[k] for k in ('leading_context','trailing_context')}
        state.update(target_text=c['target']['text'],phrase_pools=c['phrase_pools'],
                     candidate=dict(candidate_id=c['candidate_id'],claim_span=c['local_claim']))
        shapes=[dict(phase='G1_claim_and_source',state=state,questions=g1.questions(c['phrase_pools']),question_version=g1.VERSION)]
    else:
        built=v4.materialize(source,cap,c['endpoints'],{k:env[k] for k in ('start','end','text')})
        candidate,envelope,shapes=built['candidate'],built['source_envelope'],built['shapes']
    case=dict(case_id='FDR1:'+c['candidate_id'],video_id=source['video_id'],capability=cap,
        natural_candidate_id=c['candidate_id'],candidate=candidate,source_envelope=envelope,request_keys=[])
    reqs=[request(case,s) for s in shapes];case['request_keys']=[r['request_key'] for r in reqs]
    return case,reqs


def validate_packet(packet):
    if (packet.get('version')!=VERSION or packet.get('model')!=prep.MODEL
            or packet.get('content_fingerprint')!=prep.baseline.fp({k:v for k,v in packet.items() if k!='content_fingerprint'})
            or packet.get('provider_calls_authorized') is not False):
        raise ValueError('Unknown or changed fresh preparation packet')
    root=Path(packet['runtime_root']).resolve()
    inventory_path=root/'natural-inventory-v1.json'
    inventory=v4.sealed(inventory_path)
    if (packet['inventory_fingerprint']!=inventory['content_fingerprint']
            or packet['inventory_sha256']!=a1.file_hash(inventory_path)
            or packet['source_files']!=inventory['source_files']):
        raise ValueError('Fresh packet must use the sealed natural inventory')
    for name,digest in packet['code_hashes'].items():
        path=(prep.proposal.ROOT/name).resolve()
        if not path.is_relative_to(prep.proposal.ROOT.resolve()) or a1.file_hash(path)!=digest:
            raise ValueError('Fresh adapter/question/policy code changed')
    sources={}
    for vid,info in packet['source_files'].items():
        path=Path(info['path']).resolve()
        if not path.is_relative_to(root) or a1.file_hash(path)!=info['sha256']:
            raise ValueError('Foreign/changed fresh source snapshot')
        sources[int(vid)]=v4.sealed(path)
    entries={e['candidate']['candidate_id']:e for col in inventory['inventories'] for e in col['entries']}
    queue=[q for q in inventory['queue'] if q['status']=='prepared']
    if [c['natural_candidate_id'] for c in packet['cases']]!=[q['candidate_id'] for q in queue]:
        raise ValueError('Fresh cases differ from the frozen source-only queue')
    requests=[]
    for case in packet['cases']:
        expected,rs=materialize_case(sources[case['video_id']],entries[case['natural_candidate_id']])
        if case!=expected:raise ValueError('Fresh source/role/target/phase/context changed')
        requests.extend(rs)
    if requests!=packet['requests'] or len({r['request_key'] for r in requests})!=len(requests):
        raise ValueError('Fresh canonical question/state/order changed')
    if len(packet['cases'])>120 or len(requests)>240:
        raise ValueError('Fresh queue exceeds authorization bounds')


class MeasurementBoundary(v4.Boundary):
    def __init__(self,packet,expected_packet_fingerprint,authority=None):
        validate_packet(packet)
        if packet['content_fingerprint']!=expected_packet_fingerprint:
            raise ValueError('Fresh packet is not the caller-approved input')
        if authority is not None and type(authority) is not v4.ReviewAuthority:
            raise ValueError('Fresh review authority must be accepted receipt-bound source review')
        self._packet_json=v4.canonical(packet);self.authority=authority

    def _revalidate(self,measurement):
        validate_packet(self.packet)
        if type(measurement) is not v4.Measurement:raise ValueError('Expected sealed receipt-bound measurement')
        doc=measurement.document
        if self.measure(doc['case_id'],doc['receipts'])!=measurement:
            raise ValueError('Fresh measurement identity/decisions changed')
        return doc

    def admit(self,measurement):
        if measurement.document['capability']=='G1':
            self._revalidate(measurement)
            return v4.Admission(('G1_requires_separate_closed_assurance_admission',))
        return super().admit(measurement)


@dataclass(frozen=True)
class AssuranceEvidence:
    document_json:str
    measurement:v4.Measurement


class Boundary(a1.Boundary):
    def __init__(self,packet,expected_packet_fingerprint,source_authority,policy_authority,claim_authority=None):
        if type(policy_authority) is not a1.PolicyAuthority or type(source_authority) is not v4.ReviewAuthority:
            raise ValueError('Typed accepted source/policy authorities required')
        if claim_authority is not None and type(claim_authority) is not a1.ClaimAuthority:
            raise ValueError('Prepared oracle is not accepted atomic authority')
        self.base=MeasurementBoundary(packet,expected_packet_fingerprint,source_authority)
        self.policy_authority=policy_authority;self.claim_authority=claim_authority

    def admit(self,measurement):
        if measurement.document['capability']!='G1':return super().admit(measurement)
        self.policy_authority.check(self.base.packet,self.base.authority)
        d=self.base._revalidate(measurement)
        witness=self.base.authority.witness(self.base.packet['content_fingerprint'],measurement)
        if witness is None:return a1.AtomicAdmission(('no_accepted_G1_source_witness',))
        facts=witness['facts'];choices=d['decisions']
        envelope=d['binding']['source_envelope']
        source_info=self.base.packet['source_files'][str(next(c['video_id'] for c in self.base.packet['cases'] if c['case_id']==d['case_id']))]
        text=v4.sealed(Path(source_info['path']))['text']
        support=witness.get('source_support',[])
        if not any(s['start']<=envelope['start']<envelope['end']<=s['end'] and text[s['start']:s['end']]==s['text'] for s in support):
            return a1.AtomicAdmission(('missing_G1_supplied_source_support',))
        compatible=(choices.get('voice')=='preacher' and facts.get('origin')=='present_preacher'
                    or choices.get('voice') in {'reported_teachers','reported_other','mayor'}
                    and facts.get('origin') in {'reported','historical','hypothetical','quoted'})
        stance=(choices.get('voice')=='preacher' and choices.get('adoption')=='own_assertion'
                or choices.get('voice') in {'reported_teachers','reported_other','mayor'}
                and choices.get('adoption') in {'explicitly_adopted','reported_not_adopted','explicitly_rejected'}
                or choices.get('expression') in {'question','open_issue'} and choices.get('adoption')=='undetermined')
        if (facts.get('context_complete') is not True or facts.get('target_complete') is not True
                or choices.get('subject')!='salvation_acceptance'
                or choices.get('relation') not in {'acceptance_knowable_now','loss_possible','retention'}
                or choices.get('boundary')!='local_sufficient' or not compatible or not stance
                or any(v in {None,'unclear','no_expression','no_match'} for v in choices.values())
                or facts.get('g1_decisions')!=choices):
            return a1.AtomicAdmission(('unsupported_incomplete_or_withheld_G1_assurance_fields',))
        item=dict(version=G1_VERSION,namespace='G1_reviewed_local_assurance',packet_fingerprint=self.base.packet['content_fingerprint'],
            measurement_fingerprint=measurement.fingerprint,claim=d['binding']['roles']['claim'],decisions=choices,
            source_review_decision_sha256=self.base.authority.decision_sha256,
            circumstance_claim=None,pastor_projection=None,quality_score=None)
        return a1.AtomicAdmission((),AssuranceEvidence(v4.canonical(item),measurement))

    def export(self,item):
        if type(item) is not AssuranceEvidence:return super().export(item)
        if self.admit(item.measurement).item!=item:raise ValueError('Forged/stale G1 assurance item')
        return v4.canonical(dict(version=G1_VERSION,item=json.loads(item.document_json),measurement=item.measurement.document))

    def deserialize(self,wire):
        value=json.loads(wire)
        if isinstance(value,dict) and value.get('version')==G1_VERSION:
            if set(value)!={'version','item','measurement'}:raise ValueError('Unknown G1 wire schema')
            item=AssuranceEvidence(v4.canonical(value['item']),v4.Measurement(v4.canonical(value['measurement'])))
            self.export(item);return item
        return super().deserialize(wire)

    def consume_local(self,wires):
        items=[json.loads(self.export(self.deserialize(w)))['item'] for w in wires]
        if len({i['measurement_fingerprint'] for i in items})!=len(items):raise ValueError('Duplicate local evidence')
        return dict(version='fresh-reviewed-local-evidence-v1',scope='reviewed_local_only',items=items,
                    circumstance_claim=None,pastor_projection=None,quality_score=None)
