"""V4 local-evidence boundary. No provider, discovery or pastor estimator.

Trusted review files are a human/source-controlled safety oracle, not automatic
attestation. Hashes bind that trust decision to evidence; they are not signatures.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from pastor_transcript_extractor import evidence_supply_boundary_validation as old
from pastor_transcript_extractor.sermon_g3_feasibility_review import ACTS

VERSION = 'reviewed-local-evidence-v4'


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def sealed(path):
    value = json.loads(Path(path).read_text())
    if value.get('content_fingerprint') != old.frozen.fp({k: v for k, v in value.items() if k != 'content_fingerprint'}):
        raise ValueError('Review/packet fingerprint mismatch')
    return value


class EnvelopeUnavailable(ValueError):
    """Required context is unavailable; never silently truncate."""


def materialize(source, capability, roles, context, maximum=6000):
    """Preserve exact roles and phase targets; add natural-order context only."""
    candidate = old.design.represent(source, capability, roles)
    if candidate['status'] != 'represented':
        raise EnvelopeUnavailable(candidate['reason'])
    frame = candidate['relation_frame']
    lo = min(context['start'], frame['start'])
    hi = max(context['end'], frame['end'])
    text = source['text']
    if (text[context['start']:context['end']] != context['text']
            or not source['main_span']['start'] <= lo < hi <= source['main_span']['end']):
        raise EnvelopeUnavailable('Context is not exact main-source evidence')
    if hi - lo > maximum:
        raise EnvelopeUnavailable('Required contiguous envelope exceeds bound; defer whole candidate')
    envelope = dict(start=lo, end=hi, text=text[lo:hi])
    shapes = old.design.request_shapes(candidate)
    for shape in shapes:
        target = candidate['act_target'] if shape['phase'] == 'G3_acts_and_source_only' else frame
        # Use the original target verbatim; context never changes local role offsets.
        if shape['state']['target_text'] != target['text']:
            raise ValueError('Unexpected phase target')
        shape['state']['leading_context'] = text[lo:target['start']]
        shape['state']['trailing_context'] = text[target['end']:hi]
        if shape['state']['leading_context'] + shape['state']['target_text'] + shape['state']['trailing_context'] != envelope['text']:
            raise ValueError('Noncontiguous or duplicated source context')
    return dict(candidate=candidate, source_envelope=envelope, shapes=shapes)


@dataclass(frozen=True)
class Measurement:
    """Canonical immutable raw/derived record. It conveys no admission authority."""
    document_json: str

    @property
    def document(self):
        return json.loads(self.document_json)

    @property
    def fingerprint(self):
        return old.frozen.fp(self.document)


@dataclass(frozen=True)
class LocalEvidence:
    """Only Boundary.export may serialize this type for a consumer."""
    document_json: str
    measurement: Measurement


@dataclass(frozen=True)
class Admission:
    reasons: tuple[str, ...]
    item: LocalEvidence | None = None


@dataclass(frozen=True)
class ReviewAuthority:
    """An explicitly trusted accepted decision, loaded from source-review files.

    expected_decision_sha256 must come from the approved review decision, never
    from a candidate/receipt's self-declared trust or metadata.
    """
    review_path: Path
    decision_path: Path
    decision_sha256: str
    review_json: str

    @classmethod
    def load(cls, review_path, decision_path, expected_decision_sha256):
        review_path, decision_path = Path(review_path), Path(decision_path)
        if old.frozen.v1.file_hash(decision_path) != expected_decision_sha256:
            raise ValueError('Untrusted review decision identity')
        review, decision = sealed(review_path), sealed(decision_path)
        if (decision.get('version') != 'source-review-acceptance-v4'
                or decision.get('status') != 'ACCEPTED' or decision.get('closed') is not True
                or decision.get('decision_owner') != 'Brian'
                or decision.get('scope') != 'local_boundary_admission_only'
                or decision.get('review_file_sha256') != old.frozen.v1.file_hash(review_path)
                or decision.get('review_fingerprint') != review['content_fingerprint']
                or decision.get('packet_fingerprint') != review.get('packet_fingerprint')
                or review.get('version') != 'receipt-bound-source-review-v4'):
            raise ValueError('Missing accepted receipt-bound source review')
        return cls(review_path, decision_path, expected_decision_sha256, canonical(review))

    def witness(self, packet_fingerprint, measurement):
        # Detect post-load edits as well as stale request/receipt bindings.
        current = type(self).load(self.review_path, self.decision_path, self.decision_sha256)
        if current.review_json != self.review_json:
            raise ValueError('Accepted review changed after load')
        review = json.loads(self.review_json)
        if review['packet_fingerprint'] != packet_fingerprint:
            raise ValueError('Review belongs to another packet')
        rows = review.get('rows', [])
        ids = [r['case_id'] for r in rows]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate review witness')
        matched = [r for r in rows if r['case_id'] == measurement.document['case_id']]
        if not matched:
            return None
        witness = matched[0]
        if (witness.get('measurement_fingerprint') != measurement.fingerprint
                or witness.get('binding') != measurement.document['binding']):
            raise ValueError('Stale source/role/context/question/model/receipt review witness')
        return witness


class Boundary:
    """Every V4 G2/G3 item, serialized import and local consumer uses this gate."""
    def __init__(self, packet, authority=None):
        from pastor_transcript_extractor.evidence_supply_boundary_v4 import validate_packet
        validate_packet(packet)
        if authority is not None and type(authority) is not ReviewAuthority:
            raise ValueError('Prepared notes/metadata are not accepted review authority')
        self._packet_json = canonical(packet)
        self.authority = authority

    @property
    def packet(self):
        return json.loads(self._packet_json)

    def measure(self, case_id, receipts):
        packet = self.packet
        case = next((c for c in packet['cases'] if c['case_id'] == case_id), None)
        if case is None:
            raise ValueError('Unknown V4 case')
        requests = [r for r in packet['requests'] if r['case_id'] == case_id]
        if len(receipts) != len(requests):
            raise ValueError('Incomplete/duplicate phase receipt inventory')
        phases, decisions = [], {}
        for request, receipt in zip(requests, receipts, strict=True):
            old.frozen._verify_seal(receipt)
            if receipt['input_fingerprint'] != packet['content_fingerprint'] or receipt['request_key'] != request['request_key']:
                raise ValueError('Wrong packet/state/phase receipt')
            response = old.frozen.validate_response(receipt['response'], request)
            selected = {k.removeprefix('p0_'): old.decision(v) for k, v in response['answers'].items()}
            if set(selected) & set(decisions):
                raise ValueError('Phase overwrite')
            if request['phase'] == 'G3_relevance_and_recipient_binding_only' and set(selected) != {'circumstance_relevance', 'recipient_circumstance_binding'}:
                raise ValueError('Binding phase cannot introduce act/source fields')
            decisions.update(selected)
            phases.append(dict(phase=request['phase'], request_key=request['request_key'],
                               raw_answers=response['answers'], decisions=selected, model=response['model'], usage=response['usage']))
        binding = dict(packet_fingerprint=packet['content_fingerprint'], case_id=case_id,
                       source_snapshot_sha256=packet['source_files'][str(case['video_id'])]['sha256'],
                       roles=case['candidate']['endpoints'], source_envelope=case['source_envelope'],
                       request_keys=[r['request_key'] for r in requests], receipt_fingerprints=[r['fingerprint'] for r in receipts])
        return Measurement(canonical(dict(case_id=case_id, capability=case['capability'], binding=binding,
                                           phases=phases, decisions=decisions, receipts=receipts)))

    def _revalidate(self, measurement):
        from pastor_transcript_extractor.evidence_supply_boundary_v4 import validate_packet
        validate_packet(self.packet)
        if type(measurement) is not Measurement:
            raise ValueError('Raw dictionary is not a receipt-bound Measurement')
        document = measurement.document
        rebuilt = self.measure(document['case_id'], document['receipts'])
        if rebuilt != measurement:
            raise ValueError('Measurement decisions/identity changed')
        return document

    def admit(self, measurement):
        doc = self._revalidate(measurement)
        if self.authority is None:
            return Admission(('no_accepted_source_review',))
        witness = self.authority.witness(self.packet['content_fingerprint'], measurement)
        if witness is None:
            return Admission(('unreviewed_candidate',))
        case = next(c for c in self.packet['cases'] if c['case_id'] == doc['case_id'])
        source_info = self.packet['source_files'][str(case['video_id'])]
        source = json.loads((old.frozen.ROOT / source_info['path']).read_text())['text']
        support = witness.get('source_support', [])
        if not support or any(not 0 <= s['start'] < s['end'] <= len(source) or source[s['start']:s['end']] != s['text'] for s in support):
            return Admission(('missing_or_invalid_source_support',))
        envelope = doc['binding']['source_envelope']
        if not any(s['start'] <= envelope['start'] < envelope['end'] <= s['end'] for s in support):
            return Admission(('review_does_not_cover_supplied_envelope',))
        facts, d = witness.get('facts', {}), doc['decisions']
        reasons = []
        if facts.get('context_complete') is not True or facts.get('target_complete') is not True:
            reasons.append('unresolved_context_or_target')
        if d.get('boundary') != 'local_sufficient':
            reasons.append('raw_boundary_not_sufficient')
        if doc['capability'] == 'G2':
            if d.get('explains_text') != 'linked':
                reasons.append('no_measured_explanation')
            if facts.get('anchor_family') != 'biblical':
                reasons.append('ineligible_or_unknown_Bible_anchor')
            if facts.get('edge_kind') != 'explanatory':
                reasons.append('reading_or_unresolved_explanatory_edge')
            for field in ('left_voice', 'right_voice', 'adoption'):
                if d.get(field) in {None, 'unclear', 'unresolved'} or d.get(field) != facts.get(field):
                    reasons.append('unsupported_' + field)
            if d.get('adoption') != 'own_or_adopted':
                reasons.append('no_measured_adoption')
            namespace = 'G2_adopted_bible_explanation'
            positive = {'explains_text': 'linked'}
        else:
            if case['candidate']['admission'] == 'narration_control_only_no_positive_export':
                reasons.append('narration_veto')
            if facts.get('addressed_human_utterance') is not True:
                reasons.append('no_supported_addressed_human_utterance')
            for field in ('voice', 'addressee', 'adoption'):
                if d.get(field) in {None, 'unclear', 'unresolved', 'no_address', 'God'} or d.get(field) != facts.get(field):
                    reasons.append('unsupported_' + field)
            positive = {act: 'observed' for act in ACTS if d.get(act) == 'observed'}
            if not positive:
                reasons.append('no_measured_act')
            supported = facts.get('supported_acts', [])
            if not set(positive) <= set(supported) or not set(supported) <= set(ACTS):
                reasons.append('unsupported_positive_act')
            circumstance = case['candidate']['endpoints']['circumstance']
            relevance = d.get('circumstance_relevance')
            binding = d.get('recipient_circumstance_binding')
            if circumstance is None:
                if relevance != 'not_relevant' or binding != 'not_bound':
                    reasons.append('incompatible_null_circumstance')
            else:
                if relevance in {'relevant_in_target', 'relevant_context_resolved'} and facts.get('circumstance_relevance_supported') is not True:
                    reasons.append('unsupported_circumstance_relevance')
                if binding in {'bound_in_target', 'bound_context_resolved'} and facts.get('same_human_recipient_binding_supported') is not True:
                    reasons.append('unsupported_recipient_circumstance_binding')
            if facts.get('origin') == 'present_preacher' and d.get('voice') == 'preacher' and d.get('addressee') == 'direct_current_listener' and d.get('adoption') == 'own_or_adopted':
                namespace = 'G3_current_preacher_act'
            elif facts.get('origin') in {'historical', 'reported', 'hypothetical', 'quoted'} and d.get('voice') == 'quoted_or_reported' and d.get('addressee') in {'reported_person', 'general_hypothetical'}:
                namespace = 'G3_reported_local_act'
            else:
                namespace = None
                reasons.append('incompatible_source_recipient_adoption_scope')
        if reasons:
            return Admission(tuple(dict.fromkeys(reasons)))
        # No circumstance claim is exported by the minimal local-act route. All
        # original independent decisions/conditions remain immutable in Measurement.
        item = dict(version=VERSION, packet_fingerprint=self.packet['content_fingerprint'],
                    measurement_fingerprint=measurement.fingerprint, namespace=namespace,
                    positive_facts=positive, roles=doc['binding']['roles'],
                    source_voice={k: d[k] for k in ('voice', 'addressee', 'adoption', 'left_voice', 'right_voice') if k in d},
                    circumstance_claim=None, review_decision_sha256=self.authority.decision_sha256,
                    pastor_projection=None, quality_score=None)
        return Admission((), LocalEvidence(canonical(item), measurement))

    def export(self, item):
        """Only real export path: re-admit, never trust a previously typed object."""
        if type(item) is not LocalEvidence:
            raise ValueError('Raw/quarantine data cannot be exported as local evidence')
        admitted = self.admit(item.measurement)
        if admitted.item != item:
            raise ValueError('Item is forged, stale or no longer admitted')
        return canonical(dict(version=VERSION, item=json.loads(item.document_json), measurement=item.measurement.document))

    def deserialize(self, wire):
        value = json.loads(wire)
        if set(value) != {'version', 'item', 'measurement'} or value['version'] != VERSION:
            raise ValueError('Unknown evidence schema or raw payload')
        item = LocalEvidence(canonical(value['item']), Measurement(canonical(value['measurement'])))
        self.export(item)
        return item

    def consume_local(self, wires):
        """Local evidence consumer only; no profile, traits, scoring or legacy adapter."""
        items = [json.loads(self.export(self.deserialize(wire)))['item'] for wire in wires]
        ids = [i['measurement_fingerprint'] for i in items]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate local evidence cannot inflate counts')
        return dict(version=VERSION, scope='reviewed_local_evidence_only', items=items,
                    pastor_projection=None, quality_score=None)
