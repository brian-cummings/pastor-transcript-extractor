"""Review-only wire shapes. No collectors, provider clients, or profile estimators.

Pydantic is already a project dependency. Exported JSON Schema is the wire contract;
cross-record invariants are checked by check_packet.py, not by a production consumer.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Span(Record):
    role: Literal["target", "leading_context", "trailing_context"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    segment_id: str | None
    start_seconds: float | None
    end_seconds: float | None


class Source(Record):
    recording_id: str
    transcript_sha256: str | None
    target_sha256: str
    target_text: str
    leading_context: str
    trailing_context: str
    source_path: str | None
    source_pointer: str | None
    sermon_id: str | None
    sermon_date: str | None
    date_basis: Literal["reviewed_sermon_date", "unknown"]
    series_id: str | None
    period_id: str | None


class Eligibility(Record):
    membership: Literal["reviewed_member", "conflict", "unknown"]
    content: Literal["eligible", "excluded", "unknown"]
    policy_version: str
    review_ref: str | None


class Provenance(Record):
    origin: Literal["synthetic_design", "frozen_provider_output"]
    input_path: str | None
    input_pointer: str | None
    result_path: str | None
    result_pointer: str | None
    question_semantics: str
    question_version: str
    question_digest: str | None
    candidate_builder: str
    requested_model: str | None
    resolved_model: str | None
    model_resolution: Literal["not_applicable", "recorded", "unresolved"]
    decision_policy: str
    raw_output_ref: str | None
    answer_provenance_ref: str | None
    semantic_review: Literal["authored_expectation", "bounded_feasibility_review"]
    compatibility: Literal["compatible", "incompatible", "unresolved"]
    reused_from: list[str]


class Coverage(Record):
    local_boundary: Literal["sufficient", "incomplete", "unknown"]
    episode_boundary: Literal["reviewed_complete", "proposed", "unknown"]
    candidate_discovery: Literal["unknown", "frozen_catalog_only"]
    sermon_assessment: Literal["partial", "not_assessed"]
    opportunities: Literal["unknown", "not_defined"]


class Independence(Record):
    utterance_group: str
    episode_group: str | None
    recording_group: str
    sermon_group: str | None
    repeated_material_group: str | None
    group_review: Literal["authored", "unreviewed"]


class Leaf(Record):
    kind: Literal["leaf"]
    contract_id: str
    observed_statement: str


class Claim(Record):
    kind: Literal["claim_design_only"]
    object: str
    relation: str
    expression: Literal["affirmed", "rejected", "qualified", "explicitly_uncertain"]
    conditions: list[str]
    voice: str
    adoption: str


class Relation(Record):
    kind: Literal["relation"]
    relation: str
    left_span: int
    right_span: int
    decision: Literal["linked", "not_linked", "unclear", "incomplete"]
    left_voice: str
    right_voice: str
    adoption: str


class Address(Record):
    kind: Literal["address"]
    acts: dict[str, Literal["observed", "not_observed", "unclear", "incomplete"]]
    circumstance_relevance: Literal["relevant_in_target", "relevant_context_resolved", "not_relevant", "unclear", "incomplete"]
    recipient_binding: Literal["bound_in_target", "bound_context_resolved", "not_bound", "unclear", "incomplete"]
    addressee: Literal["God", "direct_current_listener", "reported_person", "general_hypothetical", "no_address", "unresolved", "unclear"]
    voice: Literal["preacher", "quoted_or_reported", "mixed", "unresolved", "unclear"]
    adoption: Literal["own_or_adopted", "explicitly_rejected", "not_adopted_report", "unresolved", "unclear"]
    qualifications: list[str]


Payload = Annotated[Leaf | Claim | Relation | Address, Field(discriminator="kind")]


class Evidence(Record):
    evidence_id: str
    capability: Literal["registry", "G1_design", "G2", "G3"]
    source: Source
    spans: list[Span] = Field(min_length=1)
    unit_id: str
    eligibility: Eligibility
    provenance: Provenance
    independence: Independence
    coverage: Coverage
    observation_state: Literal[
        "positive_local", "negative_in_unit", "judgment_withheld", "boundary_incomplete"
    ]
    payload: Payload


class FieldContract(Record):
    characteristic_id: str
    question: str
    target_statement: str
    estimand_ids: list[str]
    compatible_inputs: list[str]
    required_gates: list[str]
    missing_information: list[str]
    maximum_packet_claim: Literal["local_example", "unavailable"]
    forbidden_inference: str


class FieldEvidence(Record):
    characteristic_id: str
    subject_scope: Literal["supplied_passage"]
    estimand_id: str
    interpretation_version: str
    availability: Literal[
        "local_examples", "negative_in_unit", "not_collected", "measurement_unresolved", "incompatible",
        "excluded", "judgment_withheld", "boundary_incomplete", "downstream_held"
    ]
    claim_level: Literal["local_example", "unavailable"]
    supporting: list[str]
    counter: list[str]
    unresolved: list[str]
    required_missing: list[str]
    suppression_reasons: list[str]
    visible_wording: str
    uncertainty_wording: str
    population_rate: None
    recurring_characterization: None
    comparison: None
    quality_score: None


class ExpectedView(Record):
    fields: list[FieldEvidence]
    retained_evidence: list[str]
    unique_utterance_groups: int = Field(ge=0)
    independently_eligible_sermons: int | None
    series_period_note: str
    forbidden_wording: list[str]


class Case(Record):
    case_id: str
    purpose: str
    origin: Literal["synthetic_design", "frozen_provider_output", "mixed"]
    evidence: list[Evidence]
    expected: ExpectedView


class Estimand(Record):
    estimand_id: str
    target: str
    population: str
    numerator: str
    denominator: str
    weighting: str
    negatives_required: str
    missingness: str
    independence: str
    activation_requirements: list[str]
    status: Literal["descriptive_examples_only", "proposed_inactive"]


class FrozenArtifact(Record):
    path: str
    sha256: str


class Packet(Record):
    version: Literal["profile-evidence-consumer-v1"]
    status: Literal["prepared_for_design_review"]
    production_effect: Literal["none"]
    holds: list[str]
    sources: list[FrozenArtifact]
    field_contracts: list[FieldContract]
    downstream_holds: dict[str, str]
    estimands: list[Estimand]
    cases: list[Case]
