"""Source-bound machine observations; literal validity never confers admission."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

from .binding_evidence import context_digest, text_digest
from .theological_binding import VERSION as COMPILER_VERSION, bind

VERSION = 'pastor-evidence-v1'
PARTIAL_VERSION = 'pastor-evidence-partial-v1'
ROLE_OPTIONS = dict(voice={'preacher', 'quoted_or_reported', 'unresolved'},
    occurrence={'actual', 'projected', 'unresolved'},
    adoption={'own_assertion', 'adopted', 'reported_not_adopted', 'rejected', 'undetermined'})
EXPERIMENTAL = 'learning-demo-v3'
REQUIRED_CHECKS = ('proposition', 'voice', 'adoption', 'polarity', 'conditions',
                   'scope', 'qualifications', 'context_sufficiency', 'relations', 'address')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class SampleSpec:
    profile_id: int
    video_ids: tuple[int, ...]
    membership_fingerprint: str
    input_run_ids: tuple[int, ...] = ()
    occasion_independence: str = 'unknown'

    def __post_init__(self):
        if not self.video_ids or len(set(self.video_ids)) != len(self.video_ids) or not self.membership_fingerprint:
            raise ValueError('Sample needs unique recordings and membership lineage')


@dataclass(frozen=True)
class SourceWindow:
    id: str
    profile_id: int
    video_id: int
    source_sha256: str
    anchor_block_id: int
    blocks: tuple[dict, ...]
    stratum: str
    excluded_neighbors: tuple[int, ...] = ()
    builder_identity: str = 'saved-analysis-geometry'

    def target(self):
        """Join declared adjacent blocks with reversible Unicode character offsets."""
        parts, mapping, offset = [], [], 0
        for block in self.blocks:
            if parts:
                offset += 1
            text = block['target_text']
            mapping.append(dict(block_id=block['block_id'], start=offset, end=offset+len(text),
                target_sha256=text_digest(text), start_seconds=block['start_seconds'],
                end_seconds=block['end_seconds'], segment_indexes=block['segment_indexes']))
            parts.append(text)
            offset += len(text)
        return dict(target_text='\n'.join(parts), leading_context='', trailing_context=''), mapping


@dataclass(frozen=True)
class EvidencePolicy:
    namespace: str = EXPERIMENTAL
    threshold: float = .90
    require_production_admission: bool = False
    version: str = 'experimental-required-fields-090-v1'

    def permits(self, envelope):
        if envelope['namespace'] != self.namespace:
            return False, 'namespace_mismatch'
        if self.require_production_admission and envelope['production_admission'] != 'admitted':
            return False, 'not_production_admitted'
        if envelope.get('contract_version') == PARTIAL_VERSION:
            return False, 'partial_observation'
        checks = envelope['field_judgments']
        if set(checks) != set(REQUIRED_CHECKS):
            return False, 'missing_required_checks'
        for finding in checks.values():
            if (finding.get('resolved') is not True or type(finding.get('probability')) not in (int, float)
                    or not self.threshold <= finding['probability'] <= 1):
                return False, 'unresolved_or_below_threshold'
        return True, None


def observation_identity(row):
    if row['contract_version'] == PARTIAL_VERSION:
        return digest({k:row[k] for k in ('contract_version', 'namespace', 'source_refs',
            'producer', 'model', 'prompt_digest', 'raw_response_ref', 'origin',
            'binding', 'partial_binding', 'field_decisions')})
    return digest({k:row[k] for k in ('contract_version','namespace','source_refs','producer',
        'model','prompt_digest','raw_response_ref','origin','binding')})


@dataclass(frozen=True)
class ObservationEnvelope:
    payload: dict

    def __post_init__(self):
        row = self.payload
        for key in ('id', 'contract_version', 'source_refs', 'producer', 'model',
                    'prompt_digest', 'raw_response_ref', 'field_judgments', 'origin',
                    'experimental_eligibility', 'production_admission', 'uncertainty', 'namespace'):
            if key not in row:
                raise ValueError(f'Missing envelope field: {key}')
        if row['contract_version'] == PARTIAL_VERSION:
            if row.get('binding') is not None or row['production_admission'] != 'not_admitted':
                raise ValueError('Partial observations cannot contain full bindings or admission')
            partial = row['partial_binding']
            values, masks = role_values(row['field_decisions'])
            if partial['values'] != values or partial['masks'] != masks:
                raise ValueError('Partial values or masks differ from raw decisions')
            if row['experimental_eligibility'] != 'partial_only':
                raise ValueError('Partial observation cannot be eligible as a complete binding')
        if (row.get('binding') is not None or row['contract_version'] == PARTIAL_VERSION) and row['id'] != observation_identity(row):
            raise ValueError('Observation source/model/question identity changed')
        if row['origin'] == 'machine_generated' and row['production_admission'] != 'not_admitted':
            raise ValueError('Machine adapter cannot confer production authority')


@dataclass(frozen=True)
class EvidenceView:
    observations: tuple[dict, ...]
    policy: EvidencePolicy = EvidencePolicy()

    def partition(self):
        accepted, excluded = [], []
        for row in self.observations:
            ObservationEnvelope(row)
            ok, reason = self.policy.permits(row)
            (accepted if ok else excluded).append(row if ok else dict(id=row['id'], reason=reason))
        return accepted, excluded


LITERAL_LOCATOR_VERSION='unique-verbatim-unicode-v1'


def locate_literal_spans(value,texts):
    """Locate exact, unique quotations; never normalize, guess, or repair evidence."""
    if isinstance(value,list): return [locate_literal_spans(item,texts) for item in value]
    if not isinstance(value,dict): return value
    if set(value)=={'source_field','text'}:
        field,quote=value['source_field'],value['text']
        if field!='target_text' or not isinstance(quote,str) or not quote:
            raise ValueError('Invalid literal quotation field or empty text')
        text=texts[field];start=text.find(quote)
        if start<0: raise ValueError('Literal quotation absent; unresolved, no repair')
        if text.find(quote,start+1)>=0: raise ValueError('Literal quotation ambiguous; unresolved, no first-match selection')
        return dict(source_field=field,text=quote,start=start,end=start+len(quote))
    return {key:locate_literal_spans(item,texts) for key,item in value.items()}


def compile_machine_binding(window, proposal, *, model, prompt_digest, raw_response_ref,
                            field_judgments=None,locate_quotes=False):
    texts, mapping = window.target()
    provenance = dict(target_sha256=text_digest(texts['target_text']), texts_sha256=context_digest(texts))
    if locate_quotes: proposal=locate_literal_spans(proposal,texts)
    row = bind(texts, proposal, provenance)
    # V1's author-only stamps are not true of this new contract. Never expose them.
    row.update(version='machine-theological-binding-v1', authorship='machine_generated',
               automatic_binding=True, semantic_validation='literal_checked; verification separate')
    span = row['proposition']['span']
    coordinates = [dict(m, local_start=max(span['start'], m['start'])-m['start'],
        local_end=min(span['end'], m['end'])-m['start']) for m in mapping
        if span['start'] < m['end'] and span['end'] > m['start']]
    if not coordinates:
        raise ValueError('Claim lacks mapped source blocks')
    source_refs = [dict(video_id=window.video_id, source_sha256=window.source_sha256,
        window_id=window.id, stratum=window.stratum, anchor_block_id=window.anchor_block_id,
        **coordinate) for coordinate in coordinates]
    envelope = dict(id=digest(dict(source=source_refs, binding=row)), contract_version=VERSION,
        namespace=EXPERIMENTAL, source_refs=source_refs, producer=dict(compiler=COMPILER_VERSION,
        adapter=VERSION, literal_locator=LITERAL_LOCATOR_VERSION if locate_quotes else 'supplied_coordinates'), model=model, prompt_digest=prompt_digest, raw_response_ref=raw_response_ref,
        field_judgments=deepcopy(field_judgments or {}), origin='machine_generated',
        experimental_eligibility='pending_verification', production_admission='not_admitted',
        uncertainty=dict(expressed=row['epistemic_status'], model='diagnostic_not_calibrated',
                         sample_independence='unknown'), binding=row)
    envelope['id']=observation_identity(envelope)
    ObservationEnvelope(envelope)
    return envelope


def role_values(decisions):
    """Preserve raw judgments; mask uncertainty without synthesizing other fields."""
    if set(decisions) != set(ROLE_OPTIONS):
        raise ValueError('Partial observation needs exactly voice, occurrence and adoption')
    values, masks = {}, {}
    for field, options in ROLE_OPTIONS.items():
        row = decisions[field]
        probs = row['probabilities']; choice = row['choice']; confidence = row['confidence']
        if (row.get('type') != 'choice' or choice not in options or set(probs) != options
                or any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in probs.values())
                or abs(sum(probs.values())-1) > .025 or probs[choice] < max(probs.values())-1e-9
                or type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError('Invalid partial Choice distribution')
        for key in ('model', 'prompt_digest', 'raw_response_ref', 'request_fingerprint', 'response_digest', 'question_id'):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError('Missing partial decision provenance: '+key)
        # These are diagnostic gates, not calibration or full-observation verification.
        masks[field] = probs[choice] >= .90 and confidence >= .90 and choice not in ('unresolved', 'undetermined')
        values[field] = choice if masks[field] else None
    return values, masks


def compile_partial_observation(window, proposition, evidence, decisions, *, evidence_provenance):
    """Persist partial machine decisions without invoking the full binding compiler.

    A role label never supplies speaker identity, adoption basis, conditions,
    polarity or a warrant. Even all three known labels remain a partial record.
    """
    from .binding_evidence import target_span
    texts, mapping = window.target()
    if not isinstance(proposition['reading'], str) or not proposition['reading'].strip():
        raise ValueError('Partial observation needs its unchanged candidate reading')
    target_span(proposition['span'], texts)
    if set(evidence) != {'proposition', 'voice', 'adoption'} or evidence['proposition'] != dict(span=proposition['span']):
        raise ValueError('Partial evidence must preserve proposition and separate roles')
    for field in ('voice', 'adoption'):
        if set(evidence[field]) != {'evidence'}: raise ValueError('Evidence cannot supply semantic labels')
        for span in evidence[field]['evidence']: target_span(span, texts)
    for key in ('model', 'prompt_digest', 'raw_response_ref', 'request_fingerprint', 'response_digest'):
        if not isinstance(evidence_provenance.get(key), str) or not evidence_provenance[key]:
            raise ValueError('Missing role evidence provenance: '+key)
    values, masks = role_values(decisions)
    span = proposition['span']
    refs = [dict(video_id=window.video_id, source_sha256=window.source_sha256,
        window_id=window.id, stratum=window.stratum, anchor_block_id=window.anchor_block_id,
        **block, local_start=max(span['start'],block['start'])-block['start'],
        local_end=min(span['end'],block['end'])-block['start']) for block in mapping
        if span['start'] < block['end'] and span['end'] > block['start']]
    if not refs: raise ValueError('Partial proposition lacks source blocks')
    row = dict(contract_version=PARTIAL_VERSION, namespace=EXPERIMENTAL, source_refs=refs,
        producer=dict(adapter=PARTIAL_VERSION, source_context_digest=context_digest(texts), role_evidence=deepcopy(evidence_provenance)),
        model={field:decision['model'] for field,decision in decisions.items()},
        prompt_digest=digest({field:decision['prompt_digest'] for field,decision in decisions.items()}),
        raw_response_ref={field:decision['raw_response_ref'] for field,decision in decisions.items()},
        origin='machine_generated', experimental_eligibility='partial_only', production_admission='not_admitted',
        field_judgments={field:dict(resolved=False, probability=None, reason='Full semantic field not verified') for field in REQUIRED_CHECKS},
        uncertainty=dict(model='diagnostic_not_calibrated', sample_independence='unknown', expressed=None),
        binding=None, partial_binding=dict(proposition=deepcopy(proposition), evidence=deepcopy(evidence),
            values=values, masks=masks, speaker=None, adoption_basis=None,
            unassessed=['speaker', 'adoption_basis', 'polarity', 'expression', 'epistemic_status',
                'conditions', 'scope', 'qualifications', 'development_relations', 'address_acts', 'alignment'],
            evidence_sufficiency='Not established by full-source label choices'), field_decisions=deepcopy(decisions))
    row['id'] = observation_identity(row)
    ObservationEnvelope(row)
    return row


class EvidenceArtifactStore:
    """Immutable namespaced JSON. All roots are provided by application configuration."""
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, name):
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError('Artifact escapes store')
        return path

    def write_immutable(self, name, value):
        path = self._path(name)
        data = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open('x') as stream:
                stream.write(data)
        except FileExistsError:
            if path.read_text() != data:
                raise ValueError(f'Immutable artifact differs: {name}')
        return dict(path=str(path), sha256=hashlib.sha256(data.encode()).hexdigest())

    def read_exact(self, name, expected_digest):
        path = self._path(name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_digest:
            raise ValueError('Artifact digest changed')
        return json.loads(path.read_text())

    def list_input_refs(self):
        return [str(p.relative_to(self.root)) for p in sorted(self.root.rglob('*.json'))]
