from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Mapping, Sequence

from pastor_transcript_extractor.config import AppPaths
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedEvidenceSyncResult,
    ReviewedSpeakerEvidence,
    load_reviewed_speaker_evidence,
    sync_reviewed_speaker_evidence,
)
from pastor_transcript_extractor.media_artifacts import MediaVerificationCache
from pastor_transcript_extractor.identity_stage_cache import association_refresh_mode
from pastor_transcript_extractor.identity_exemplar_preparation import (
    ExemplarPreparationState,
    ExemplarPreparationStateCache,
)
from pastor_transcript_extractor.speaker_machine_assignment import (
    MachineAssignmentApplyResult,
    MachineAssignmentPlan,
    MachineAssignmentPolicy,
    MachineAssignmentReconciliationResult,
    apply_machine_assignment_plan,
    load_machine_assignment_policy,
    plan_machine_assignments,
    reconcile_machine_assignments,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    ProfileAssociationReadiness,
    assess_profile_association_readiness,
)
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class IdentityWorkflowRequest:
    """Validated command input for one guarded identity workflow run."""

    youtube_video_id: str | None
    all_extractions: bool
    plan_only: bool
    skip_discovery: bool
    apply_automatic: bool
    apply_confirmations: bool
    apply_promotions: bool
    apply_machine_canary: bool
    machine_assignment_policy_path: Path | None
    review_prewarm_limit: int
    base_dir: Path | None
    jobs: int


@dataclass(frozen=True, slots=True)
class IdentityWorkflowPolicy:
    """Derived mutation gates after request-level safety validation."""

    apply_confirmations: bool
    apply_promotions: bool
    apply_machine_assignments: bool


@dataclass(frozen=True, slots=True)
class ReviewedEvidenceStageResult:
    """Reviewed evidence loaded for the run and its optional applied sync."""

    evidence: ReviewedSpeakerEvidence
    sync: ReviewedEvidenceSyncResult | None


@dataclass(frozen=True, slots=True)
class AssociationCacheDecision:
    """Whether association can reuse a checkpoint or must execute."""

    cached_reports: tuple[Path, ...] | None
    refresh_mode: str
    checkpoint_needs_refresh: bool

    @property
    def incremental(self) -> bool:
        return self.refresh_mode == "incremental"


@dataclass(frozen=True, slots=True)
class AssociationExecutionRequest:
    """Inputs needed to invoke the pinned shadow-association adapter."""

    youtube_video_id: str | None
    all_extractions: bool
    plan_only: bool
    jobs: int
    model_sha256: str
    policy_path: Path
    evaluation_root: Path
    cache_dir: Path
    output_root: Path
    base_dir: Path | None


@dataclass(frozen=True, slots=True)
class AssociationRepairStageResult:
    """Association reports plus whether repair invalidated the checkpoint."""

    reports: tuple[Path, ...]
    checkpoint_needs_refresh: bool
    repair_attempted: bool


@dataclass(frozen=True, slots=True)
class MachineAssignmentStageResult:
    """Machine-assignment plan and its optional durable application."""

    policy: MachineAssignmentPolicy
    readiness: tuple[ProfileAssociationReadiness, ...]
    plan: MachineAssignmentPlan
    applied: MachineAssignmentApplyResult | None


@dataclass(frozen=True, slots=True)
class DiscoveryExecutionDecision:
    """Corpus discovery action after scope, skip, and cache checks."""

    mode: str
    cached_reports: tuple[Path, ...] | None


@dataclass(frozen=True, slots=True)
class DiscoveryReportSelection:
    """Available discovery reports and the newest promotion candidate."""

    reports: tuple[Path, ...]
    latest: Path | None


@dataclass(frozen=True, slots=True)
class DiscoveryExecutionRequest:
    """Inputs needed to invoke the pinned shadow-discovery adapter."""

    plan_only: bool
    jobs: int
    model_sha256: str
    consistency_policy_path: Path
    association_policy_path: Path
    evaluation_root: Path
    cache_dir: Path
    output_root: Path
    base_dir: Path | None


def validate_identity_workflow_request(
    request: IdentityWorkflowRequest,
) -> IdentityWorkflowPolicy:
    """Validate cross-option invariants before opening storage or running stages."""
    if (request.youtube_video_id is None) == (not request.all_extractions):
        raise ValueError("Pass exactly one YouTube video ID or --all.")
    if request.plan_only and (
        request.apply_automatic
        or request.apply_confirmations
        or request.apply_promotions
        or request.apply_machine_canary
    ):
        raise ValueError(
            "--plan-only cannot be combined with registry mutation flags"
        )

    apply_confirmations = request.apply_automatic or request.apply_confirmations
    apply_promotions = request.apply_automatic or request.apply_promotions
    apply_machine_assignments = (
        request.apply_automatic or request.apply_machine_canary
    )
    if not request.all_extractions and apply_promotions:
        raise ValueError("automatic profile promotion requires --all")
    if not request.all_extractions and request.apply_machine_canary:
        raise ValueError("machine canary activation requires --all")
    if request.review_prewarm_limit < 0:
        raise ValueError("review prewarm limit cannot be negative")
    if request.jobs < 1:
        raise ValueError("identity jobs must be at least one")

    return IdentityWorkflowPolicy(
        apply_confirmations=apply_confirmations,
        apply_promotions=apply_promotions,
        apply_machine_assignments=apply_machine_assignments,
    )


def synchronize_reviewed_evidence_stage(
    database_path: Path,
    *,
    plan_only: bool,
    evaluation_root: Path = Path("evaluation/speaker-pairs"),
) -> ReviewedEvidenceStageResult:
    """Load reviewed evidence and apply it only for an executing run."""
    try:
        evidence = load_reviewed_speaker_evidence(evaluation_root.resolve())
        sync_result = None
        if not plan_only:
            database = Database(database_path)
            database.initialize()
            sync_result = sync_reviewed_speaker_evidence(database, evidence)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"reviewed-evidence sync failed: {error}") from error
    return ReviewedEvidenceStageResult(evidence=evidence, sync=sync_result)


def reconcile_machine_assignments_stage(
    database_path: Path,
    *,
    verification_cache: MediaVerificationCache,
    plan_only: bool,
) -> MachineAssignmentReconciliationResult | None:
    """Reconcile durable assignment evidence unless the run is plan-only."""
    if plan_only:
        return None
    return reconcile_machine_assignments(
        Database(database_path),
        verification_cache=verification_cache,
    )


def index_current_association_results(
    report_paths: Sequence[Path],
) -> dict[int, str]:
    """Index valid persisted association results by candidate observation."""
    results: dict[int, str] = {}
    for report_path in report_paths:
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        candidate = payload.get("candidate")
        observation_id = (
            candidate.get("observation_id")
            if isinstance(candidate, Mapping)
            else None
        )
        result_sha256 = payload.get("result_sha256")
        if isinstance(observation_id, int) and isinstance(result_sha256, str):
            results[observation_id] = result_sha256
    return results


def reconcile_current_assignment_results_stage(
    database_path: Path,
    *,
    verification_cache: MediaVerificationCache,
    result_sha256_by_observation: Mapping[int, str],
    plan_only: bool,
) -> MachineAssignmentReconciliationResult | None:
    """Reconcile assignments against the selected current association results."""
    if plan_only:
        return None
    return reconcile_machine_assignments(
        Database(database_path),
        verification_cache=verification_cache,
        current_association_result_sha256_by_observation=(
            result_sha256_by_observation
        ),
    )


def decide_association_cache(
    *,
    cached_reports: Sequence[Path] | None,
    previous_input_state: Mapping[str, object] | None,
    current_input_state: Mapping[str, object] | None,
    all_extractions: bool,
) -> AssociationCacheDecision:
    """Choose checkpoint reuse, incremental execution, or a full refresh."""
    cached = tuple(cached_reports) if cached_reports is not None else None
    checkpoint_needs_refresh = cached is None or (
        current_input_state is not None and previous_input_state is None
    )
    if cached is not None:
        refresh_mode = "cached"
    elif all_extractions:
        refresh_mode = association_refresh_mode(
            previous_input_state,
            current_input_state,
        )
    else:
        refresh_mode = "full"
    return AssociationCacheDecision(
        cached_reports=cached,
        refresh_mode=refresh_mode,
        checkpoint_needs_refresh=checkpoint_needs_refresh,
    )


def execute_association_stage(
    request: AssociationExecutionRequest,
    decision: AssociationCacheDecision,
    *,
    associator: Callable[..., Sequence[Path]],
) -> tuple[Path, ...]:
    """Reuse cached reports or invoke the shadow associator with pinned policy."""
    if decision.cached_reports is not None:
        return decision.cached_reports
    reports = associator(
        youtube_video_id=request.youtube_video_id,
        all_eligible=request.all_extractions,
        unattempted_only=decision.incremental,
        neighborhood_profile_id=[],
        include_profiled=False,
        limit=None,
        plan_only=request.plan_only,
        minimum_profile_members=3,
        maximum_exemplars=3,
        minimum_same_exemplars=2,
        maximum_global_profiles=1,
        jobs=request.jobs,
        model_path=Path(
            "evaluation/speaker-pairs/models/"
            "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
        ),
        model_sha256=request.model_sha256,
        policy_path=request.policy_path,
        evaluation_root=request.evaluation_root,
        cache_dir=request.cache_dir,
        output_root=request.output_root,
        base_dir=request.base_dir,
    )
    return tuple(reports)


def select_pending_exemplar_repairs(
    state_cache: ExemplarPreparationStateCache,
    *,
    database_video_id: int | None,
    plan_only: bool,
) -> tuple[ExemplarPreparationState, ...]:
    """Select pending repairs in scope without reading them during plan-only runs."""
    if plan_only:
        return ()
    return tuple(
        state
        for state in state_cache.pending_automatic_repairs()
        if database_video_id is None or state.video_id == database_video_id
    )


def repair_association_stage(
    *,
    pending_repairs: Sequence[ExemplarPreparationState],
    current_reports: Sequence[Path],
    youtube_video_id: str | None,
    all_extractions: bool,
    paths: AppPaths,
    base_dir: Path | None,
    state_cache: ExemplarPreparationStateCache,
    jobs: int,
    repairer: Callable[..., Sequence[Path]],
) -> AssociationRepairStageResult:
    """Run one bounded repair/retry pass and invalidate its old checkpoint."""
    if not pending_repairs:
        return AssociationRepairStageResult(
            reports=tuple(current_reports),
            checkpoint_needs_refresh=False,
            repair_attempted=False,
        )
    repaired_reports = repairer(
        pending_exemplar_repairs=pending_repairs,
        current_association_reports=tuple(current_reports),
        youtube_video_id=youtube_video_id,
        all_extractions=all_extractions,
        paths=paths,
        base_dir=base_dir,
        state_cache=state_cache,
        jobs=jobs,
    )
    return AssociationRepairStageResult(
        reports=tuple(repaired_reports),
        checkpoint_needs_refresh=True,
        repair_attempted=True,
    )


def persist_association_checkpoint_stage(
    *,
    plan_only: bool,
    checkpoint_needs_refresh: bool,
    all_extractions: bool,
    reports: Sequence[Path],
    fingerprint_factory: Callable[[], str | None],
    input_state_factory: Callable[[], Mapping[str, object] | None],
    checkpoint_writer: Callable[
        [str, tuple[Path, ...], Mapping[str, object] | None], None
    ],
) -> bool:
    """Recompute and persist a refreshed association checkpoint when eligible."""
    if plan_only or not checkpoint_needs_refresh:
        return False
    fingerprint = fingerprint_factory()
    input_state = input_state_factory() if all_extractions else None
    if fingerprint is None:
        return False
    checkpoint_writer(fingerprint, tuple(reports), input_state)
    return True


def run_machine_assignment_stage(
    database_path: Path,
    *,
    reports: Sequence[Path],
    reviewed_evidence: ReviewedSpeakerEvidence,
    policy_path: Path,
    verification_cache: MediaVerificationCache,
    excluded_observation_fingerprints: frozenset[str],
    database_video_id: int | None,
    plan_only: bool,
    activate_canary: bool,
) -> MachineAssignmentStageResult:
    """Plan current evidence and optionally append reversible assignment state."""
    policy = load_machine_assignment_policy(policy_path)
    database = Database(database_path, readonly=True)
    readiness = tuple(
        assess_profile_association_readiness(database, reviewed_evidence)
    )
    included_observation_ids = None
    if database_video_id is not None:
        observation = database.get_latest_speaker_observation_for_video(
            database_video_id
        )
        included_observation_ids = frozenset(
            (observation.id,) if observation is not None else ()
        )
    plan = plan_machine_assignments(
        database,
        reports,
        readiness=readiness,
        policy=policy,
        verification_cache=verification_cache,
        excluded_observation_fingerprints=excluded_observation_fingerprints,
        included_observation_ids=included_observation_ids,
    )
    applied = None
    if not plan_only:
        applied = apply_machine_assignment_plan(
            Database(database_path),
            plan,
            activate_canary=activate_canary,
        )
    return MachineAssignmentStageResult(
        policy=policy,
        readiness=readiness,
        plan=plan,
        applied=applied,
    )


def decide_discovery_execution(
    *,
    all_extractions: bool,
    skip_discovery: bool,
    cached_reports: Sequence[Path] | None,
) -> DiscoveryExecutionDecision:
    """Choose deferred, skipped, cached, or executing corpus discovery."""
    cached = tuple(cached_reports) if cached_reports is not None else None
    if not all_extractions:
        mode = "deferred"
    elif skip_discovery:
        mode = "skipped"
    elif cached is not None:
        mode = "cached"
    else:
        mode = "execute"
    return DiscoveryExecutionDecision(mode=mode, cached_reports=cached)


def select_discovery_reports(
    *,
    cached_reports: Sequence[Path] | None,
    generated_report: Path | None,
    discovery_root: Path,
) -> DiscoveryReportSelection:
    """Select available reports and their deterministic newest artifact."""
    if cached_reports is not None:
        reports = tuple(cached_reports)
    elif generated_report is not None:
        reports = (generated_report,)
    else:
        reports = tuple(discovery_root.resolve().glob("*/*.json"))
    latest = (
        max(reports, key=lambda path: (path.stat().st_mtime_ns, str(path)))
        if reports
        else None
    )
    return DiscoveryReportSelection(reports=reports, latest=latest)


def execute_discovery_stage(
    request: DiscoveryExecutionRequest,
    decision: DiscoveryExecutionDecision,
    *,
    discoverer: Callable[..., Path | None],
) -> Path | None:
    """Invoke corpus discovery only for an uncached executable decision."""
    if decision.mode != "execute":
        return None
    return discoverer(
        plan_only=request.plan_only,
        limit=None,
        nearest_neighbors=8,
        maximum_pairs=None,
        closure_candidates_per_same_pair=8,
        source_complete_link_limit=12,
        source_nearest_neighbors=4,
        borderline_deferred_minimum=0.50,
        borderline_deferred_maximum=0.60,
        borderline_deferred_candidates_per_same_pair=4,
        staged_review_candidates_per_component=2,
        staged_review_maximum_same_boundary_distance=0.15,
        jobs=request.jobs,
        minimum_component_members=3,
        consistency_report=None,
        minimum_consistency_score=None,
        consistency_policy=request.consistency_policy_path,
        include_deferred=False,
        model_path=Path(
            "evaluation/speaker-pairs/models/"
            "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
        ),
        model_sha256=request.model_sha256,
        policy_path=request.association_policy_path,
        evaluation_root=request.evaluation_root,
        cache_dir=request.cache_dir,
        output_root=request.output_root,
        base_dir=request.base_dir,
    )
