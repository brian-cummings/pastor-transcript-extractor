"""A1 atomic G3 admission. Frozen V4 measurements/guard are never modified.

Claim reviews are explicitly trusted source-controlled safety oracles. Digests bind
that trust to exact evidence and code; they do not automatically attest semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from pastor_transcript_extractor import evidence_boundary_admission as v4

POLICY = 'g3-atomic-admission-a1'
VERSION = 'reviewed-atomic-local-evidence-a1'
WITNESS = 'receipt-bound-atomic-act-sufficiency-a1'
canonical = v4.canonical
file_hash = v4.old.frozen.v1.file_hash


@dataclass(frozen=True)
class PolicyAuthority:
    policy_path: Path
    authorization_path: Path
    authorization_sha256: str
    policy_json: str

    @classmethod
    def load(cls, policy_path, authorization_path, expected_sha256):
        pp, ap = Path(policy_path), Path(authorization_path)
        if file_hash(ap) != expected_sha256:
            raise ValueError('Untrusted A1 authorization identity')
        p, a = v4.sealed(pp), v4.sealed(ap)
        if (a.get('version') != 'atomic-a1-implementation-replay-authorization'
                or a.get('status') != 'AUTHORIZED' or a.get('decision_owner') != 'Brian'
                or a.get('implementation_authorized') is not True or a.get('provider_free_replay_authorized') is not True
                or a.get('provider_calls_authorized') is not False
                or a.get('policy_fingerprint') != p['content_fingerprint']
                or a.get('policy_file_sha256') != file_hash(pp)
                or p.get('version') != POLICY or p.get('item_version') != VERSION
                or p.get('witness_version') != WITNESS or p.get('scope') != 'atomic_act_only'
                or p.get('implementation_sha256') != file_hash(Path(__file__))
                or p.get('threshold') != .80 or p.get('allowed_boundary_decisions') != ['local_sufficient', 'unclear']
                or p.get('provider_calls') != 0 or p.get('circumstance_claim') is not None):
            raise ValueError('Missing or mismatched accepted A1 policy')
        return cls(pp, ap, expected_sha256, canonical(p))

    def check(self, packet, source_authority):
        current = type(self).load(self.policy_path, self.authorization_path, self.authorization_sha256)
        p = json.loads(self.policy_json)
        if (current != self or p['packet_fingerprint'] != packet['content_fingerprint']
                or p['source_review_decision_sha256'] != source_authority.decision_sha256):
            raise ValueError('Stale A1 policy/source authority')
        return p


@dataclass(frozen=True)
class AtomicWitness:
    """Parsed claim-specific authority, with per-act exact evidence and qualifiers."""
    case_id: str
    acts: tuple[str, ...]
    namespace: str
    conditions_json: str
    source_voice_json: str
    document_json: str

    @classmethod
    def parse(cls, row, measurement, source_witness, policy):
        d = measurement.document
        fields = {'version', 'case_id', 'policy_fingerprint', 'measurement_fingerprint', 'binding',
                  'scope', 'namespace', 'utterance', 'acts', 'source_voice', 'conditions_and_limits',
                  'provenance_support', 'complete_for_exported_acts', 'no_omitted_act_or_qualifier_required',
                  'context_used_only_for_identity_stance_and_interpretation', 'excluded_claims', 'rationale'}
        if (set(row) != fields or row['version'] != WITNESS or row['scope'] != 'atomic_act_only'
                or row['policy_fingerprint'] != policy['content_fingerprint']
                or row['case_id'] != d['case_id'] or row['measurement_fingerprint'] != measurement.fingerprint
                or row['binding'] != d['binding'] or row['utterance'] != d['binding']['roles']['utterance']
                or not all(row[k] is True for k in ('complete_for_exported_acts',
                    'no_omitted_act_or_qualifier_required', 'context_used_only_for_identity_stance_and_interpretation'))
                or row['excluded_claims'] != ['circumstance_connection', 'pastor_projection', 'quality', 'outcome']
                or not isinstance(row['rationale'], str) or not row['rationale'].strip()):
            raise ValueError('Incomplete or stale atomic claim sufficiency')
        decisions = d['decisions']
        source_voice = {k: decisions[k] for k in ('voice', 'addressee', 'adoption')}
        if row['source_voice'] != source_voice:
            raise ValueError('Claim review cannot replace measured provenance')
        facts = source_witness['facts']
        if facts.get('context_complete') is not True or facts.get('target_complete') is not True:
            raise ValueError('Incomplete target/context cannot be repaired by claim review')
        namespace = ('G3_current_preacher_act' if facts.get('origin') == 'present_preacher'
                     and source_voice == dict(voice='preacher', addressee='direct_current_listener', adoption='own_or_adopted')
                     else 'G3_reported_local_act' if facts.get('origin') in {'reported', 'historical', 'hypothetical', 'quoted'}
                     and source_voice['voice'] == 'quoted_or_reported'
                     and source_voice['addressee'] in {'reported_person', 'general_hypothetical'}
                     else None)
        if namespace is None or row['namespace'] != namespace:
            raise ValueError('Incompatible atomic source/recipient namespace')
        observed = {a for a in v4.ACTS if decisions.get(a) == 'observed'}
        if (not isinstance(row['acts'], dict) or set(row['acts']) != observed or not observed
                or not observed <= set(facts.get('supported_acts', []))):
            raise ValueError('Claim review must cover every measured positive act')
        utterance = row['utterance']
        envelope = d['binding']['source_envelope']
        def supplied_span(s, container):
            return (isinstance(s, dict) and set(s) == {'start', 'end', 'text'}
                    and type(s['start']) is int and type(s['end']) is int
                    and container['start'] <= s['start'] < s['end'] <= container['end']
                    and container['text'][s['start']-container['start']:s['end']-container['start']] == s['text'])
        for claim in row['acts'].values():
            if (not isinstance(claim, dict) or set(claim) != {'support', 'rationale'}
                    or not supplied_span(claim['support'], utterance)
                    or not isinstance(claim['rationale'], str) or not claim['rationale'].strip()):
                raise ValueError('Act evidence must be within exact utterance')
        if (not isinstance(row['conditions_and_limits'], dict)
                or set(row['conditions_and_limits']) != {'complete', 'spans', 'rationale'}
                or row['conditions_and_limits']['complete'] is not True
                or not isinstance(row['conditions_and_limits']['spans'], list)
                or not isinstance(row['conditions_and_limits']['rationale'], str)
                or not row['conditions_and_limits']['rationale'].strip()
                or any(not supplied_span(s, utterance) for s in row['conditions_and_limits']['spans'])):
            raise ValueError('Incomplete or borrowed claim conditions')
        if (not isinstance(row['provenance_support'], dict)
                or set(row['provenance_support']) != {'origin', 'voice', 'addressee', 'adoption'}):
            raise ValueError('Missing provenance support')
        for key, support in row['provenance_support'].items():
            if (not isinstance(support, dict) or set(support) != {'value', 'span', 'rationale'}
                    or support['value'] != facts.get(key)
                    or not supplied_span(support['span'], envelope)
                    or not isinstance(support['rationale'], str) or not support['rationale'].strip()):
                raise ValueError('Unsupported or outside-envelope provenance review')
        return cls(row['case_id'], tuple(sorted(observed)), namespace,
                   canonical(row['conditions_and_limits']), canonical(source_voice), canonical(row))


@dataclass(frozen=True)
class ClaimAuthority:
    review_path: Path
    decision_path: Path
    decision_sha256: str
    review_json: str

    @classmethod
    def load(cls, review_path, decision_path, expected_sha256, policy):
        rp, dp = Path(review_path), Path(decision_path)
        if file_hash(dp) != expected_sha256:
            raise ValueError('Untrusted A1 claim-review decision')
        review, decision = v4.sealed(rp), v4.sealed(dp)
        if (decision.get('version') != 'atomic-claim-review-acceptance-a1'
                or decision.get('status') != 'ACCEPTED' or decision.get('closed') is not True
                or decision.get('decision_owner') != 'Brian' or decision.get('scope') != 'bounded_atomic_local_replay_only'
                or decision.get('review_file_sha256') != file_hash(rp)
                or decision.get('review_fingerprint') != review['content_fingerprint']
                or decision.get('policy_fingerprint') != policy['content_fingerprint']
                or review.get('policy_fingerprint') != policy['content_fingerprint']
                or review.get('packet_fingerprint') != policy['packet_fingerprint']
                or review.get('version') != WITNESS or not isinstance(review.get('rows'), list)):
            raise ValueError('Missing accepted A1 claim-specific source review')
        ids = [r['case_id'] for r in review['rows']]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate atomic witness')
        return cls(rp, dp, expected_sha256, canonical(review))

    def witness(self, measurement, source_witness, policy):
        current = type(self).load(self.review_path, self.decision_path, self.decision_sha256, policy)
        if current != self:
            raise ValueError('Accepted A1 claim review changed after load')
        rows = json.loads(self.review_json)['rows']
        row = next((r for r in rows if r['case_id'] == measurement.document['case_id']), None)
        return AtomicWitness.parse(row, measurement, source_witness, policy) if row else None


@dataclass(frozen=True)
class AtomicLocalEvidence:
    document_json: str
    measurement: v4.Measurement


@dataclass(frozen=True)
class AtomicAdmission:
    reasons: tuple[str, ...]
    item: AtomicLocalEvidence | v4.LocalEvidence | None = None


class Boundary:
    """Explicit dispatcher: G2 stays V4; G3 must use accepted A1 claim authority."""
    def __init__(self, packet, source_authority, policy_authority, claim_authority=None):
        if type(policy_authority) is not PolicyAuthority or type(source_authority) is not v4.ReviewAuthority:
            raise ValueError('Accepted typed A1 policy and V4 source authority required')
        if claim_authority is not None and type(claim_authority) is not ClaimAuthority:
            raise ValueError('Prepared exhibits are not accepted A1 claim authority')
        self.base = v4.Boundary(packet, source_authority)
        self.policy_authority = policy_authority
        self.claim_authority = claim_authority

    def admit(self, measurement):
        policy = self.policy_authority.check(self.base.packet, self.base.authority)
        original = self.base.admit(measurement)  # Rebuilds all raw decisions from exact receipts.
        doc = measurement.document
        if doc['capability'] == 'G2':
            return original  # Same type, item and reason list; no A1 fallback.
        if doc['capability'] != 'G3':
            raise ValueError('Unknown capability')
        # Reuse all frozen invariants without changing any raw field. Only the
        # shared broader boundary prerequisite is replaced by atomic sufficiency.
        reasons = [r for r in original.reasons if r != 'raw_boundary_not_sufficient']
        if doc['decisions'].get('boundary') not in policy['allowed_boundary_decisions']:
            reasons.append('atomic_boundary_requires_deferral')
        if reasons:
            return AtomicAdmission(tuple(reasons))
        if self.claim_authority is None:
            return AtomicAdmission(('no_accepted_atomic_claim_review',))
        source = self.base.authority.witness(self.base.packet['content_fingerprint'], measurement)
        witness = self.claim_authority.witness(measurement, source, policy)
        if witness is None:
            return AtomicAdmission(('no_atomic_claim_sufficiency_witness',))
        item = dict(version=VERSION, policy=POLICY, policy_fingerprint=policy['content_fingerprint'],
                    authorization_sha256=self.policy_authority.authorization_sha256,
                    packet_fingerprint=self.base.packet['content_fingerprint'], measurement_fingerprint=measurement.fingerprint,
                    namespace=witness.namespace, evidence_scope='atomic_act_only',
                    positive_facts={a: 'observed' for a in witness.acts},
                    utterance=doc['binding']['roles']['utterance'], conditions_and_limits=json.loads(witness.conditions_json),
                    source_voice=json.loads(witness.source_voice_json),
                    source_review_decision_sha256=self.base.authority.decision_sha256,
                    claim_review_decision_sha256=self.claim_authority.decision_sha256,
                    claim_witness_fingerprint=v4.old.frozen.fp(json.loads(witness.document_json)),
                    circumstance_claim=None, pastor_projection=None, quality_score=None)
        return AtomicAdmission((), AtomicLocalEvidence(canonical(item), measurement))

    def export(self, item):
        if type(item) is v4.LocalEvidence:
            if item.measurement.document['capability'] != 'G2':
                raise ValueError('No V4 G3 fallback into A1 consumer')
            self.policy_authority.check(self.base.packet, self.base.authority)
            return self.base.export(item)
        if type(item) is not AtomicLocalEvidence:
            raise ValueError('Only typed A1 local evidence can be exported')
        admitted = self.admit(item.measurement)
        if admitted.item != item:
            raise ValueError('Forged, stale or unsupported A1 item')
        return canonical(dict(version=VERSION, item=json.loads(item.document_json), measurement=item.measurement.document))

    def deserialize(self, wire):
        value = json.loads(wire)
        if not isinstance(value, dict) or set(value) != {'version', 'item', 'measurement'}:
            raise ValueError('Unknown A1 wire schema')
        if value['version'] == v4.VERSION:
            item = self.base.deserialize(wire)
            self.export(item)  # Explicit G2-only route.
            return item
        if value['version'] != VERSION:
            raise ValueError('Unknown A1 item version')
        item = AtomicLocalEvidence(canonical(value['item']), v4.Measurement(canonical(value['measurement'])))
        self.export(item)
        return item

    def consume_local(self, wires):
        items = [json.loads(self.export(self.deserialize(w)))['item'] for w in wires]
        ids = [i['measurement_fingerprint'] for i in items]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate local evidence cannot inflate counts')
        return dict(version=VERSION, scope='bounded_reviewed_local_evidence_only', items=items,
                    circumstance_claim=None, pastor_projection=None, quality_score=None)
