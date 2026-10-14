from __future__ import annotations

import json
from pathlib import Path
import shlex
from typing import Mapping

import typer
from rich.console import Console
from rich.table import Table

from pastor_transcript_extractor.analysis_readiness import (
    ReadinessReport,
    build_readiness_report,
    refresh_profile_analyses,
    run_deterministic_backfill,
)
from pastor_transcript_extractor.commands.analysis.common import (
    _analysis_videos,
    get_database,
)
from pastor_transcript_extractor.commands.apps import analysis_app
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.inference_defaults import DEFAULT_TYPESAFE_MODEL
from pastor_transcript_extractor.population_analysis import (
    POPULATION_ANALYZER_VERSION,
    PopulationPolicy,
    build_population_snapshot,
    load_population_snapshot_report,
)
from pastor_transcript_extractor.profile_analysis import (
    PROFILE_ANALYZER_VERSION,
)
from pastor_transcript_extractor.sermon_analysis import (
    ANALYZER_VERSION as SERMON_ANALYZER_VERSION,
    analyze_sermon,
)
from pastor_transcript_extractor.sermon_salvation_routing import (
    DEFAULT_SALVATION_ROUTING_REVIEW_OUTPUT,
    build_salvation_routing_review_packet,
    write_salvation_routing_review,
)
from pastor_transcript_extractor.sermon_salvation_relationship_review import (
    DEFAULT_SALVATION_OBEDIENCE_CALIBRATION_OUTPUT,
    DEFAULT_SALVATION_FINAL_CALIBRATION_OUTPUT,
    DEFAULT_SALVATION_RELATIONSHIP_REVIEW_OUTPUT,
    DEFAULT_SALVATION_SEMANTIC_CALIBRATION_OUTPUT,
    DEFAULT_SALVATION_V5_CALIBRATION_OUTPUT,
    DEFAULT_SALVATION_V5_THRESHOLD_REVIEW_OUTPUT,
    DEFAULT_SALVATION_V6_REPENTANCE_CALIBRATION_OUTPUT,
    DEFAULT_SALVATION_V7_REPENTANCE_CALIBRATION_OUTPUT,
    DEFAULT_SALVATION_V8_CONVERSION_CALIBRATION_OUTPUT,
    DEFAULT_SALVATION_FINAL_BOUNDARY_CALIBRATION_OUTPUT,
    DEFAULT_SALVATION_CONDITION_BOUNDARY_REVIEW_OUTPUT,
    DEFAULT_SALVATION_CONSEQUENCE_BOUNDARY_REVIEW_OUTPUT,
    build_salvation_consequence_boundary_review,
    build_salvation_condition_boundary_review,
    build_salvation_v5_threshold_review,
    evaluate_obedience_consequence_calibration,
    evaluate_salvation_final_calibration,
    evaluate_salvation_relationship_review,
    evaluate_salvation_semantic_calibration,
    evaluate_salvation_v5_calibration,
    evaluate_salvation_v6_repentance_calibration,
    evaluate_salvation_v7_repentance_calibration,
    evaluate_salvation_v8_conversion_calibration,
    evaluate_salvation_final_boundary_calibration,
    load_salvation_v5_calibration,
    load_salvation_v6_repentance_calibration,
    load_salvation_final_boundary_calibration,
    write_obedience_consequence_calibration,
    write_salvation_final_calibration,
    write_salvation_relationship_review,
    write_salvation_semantic_calibration,
    write_salvation_v5_calibration,
    write_salvation_v5_threshold_review,
    write_salvation_v6_repentance_calibration,
    write_salvation_v7_repentance_calibration,
    write_salvation_v8_conversion_calibration,
    write_salvation_final_boundary_calibration,
    write_salvation_condition_boundary_review,
    write_salvation_consequence_boundary_review,
)
from pastor_transcript_extractor.sermon_salvation_observation_threshold import (
    DEFAULT_SALVATION_OBSERVATION_THRESHOLD,
    DEFAULT_SALVATION_OBSERVATION_BOUNDARIES_REVIEW_OUTPUT,
    DEFAULT_SALVATION_OBSERVATION_THRESHOLD_REVIEW_OUTPUT,
    DEFAULT_SALVATION_RELATIONSHIP_REVIEW_INPUTS,
    build_salvation_observation_boundaries_review,
    build_salvation_observation_threshold_review,
    write_salvation_observation_boundaries_review,
    write_salvation_observation_threshold_review,
)
from pastor_transcript_extractor.sermon_salvation_observation_review import (
    DEFAULT_SALVATION_BOUNDARY_RECALIBRATION_OUTPUT,
    DEFAULT_SALVATION_COLLECTION_RECALIBRATION_OUTPUT,
    DEFAULT_SALVATION_COLLECTED_OBSERVATION_REVIEW_OUTPUT,
    DEFAULT_SALVATION_CONVERSION_RECALIBRATION_OUTPUT,
    DEFAULT_SALVATION_FINAL_COLLECTION_CHECK_OUTPUT,
    evaluate_salvation_boundary_recalibration,
    evaluate_salvation_collection_recalibration,
    evaluate_salvation_collected_observations_review,
    evaluate_salvation_conversion_recalibration,
    evaluate_salvation_final_collection_check,
    load_salvation_collected_observations_review,
    write_salvation_boundary_recalibration,
    write_salvation_collection_recalibration,
    write_salvation_collected_observations_review,
    write_salvation_conversion_recalibration,
    write_salvation_final_collection_check,
)
from pastor_transcript_extractor.sermon_salvation_profile_analysis import (
    APPROVED_SALVATION_COLLECTION_REVIEW_FINGERPRINT,
    DEFAULT_SALVATION_PROFILE_REPEATABILITY_OUTPUT,
    evaluate_salvation_profile_repeatability,
    write_salvation_profile_repeatability,
)
from pastor_transcript_extractor.sermon_salvation_repeatability_expansion import (
    DEFAULT_SALVATION_ANALYTICAL_BACKFILL_PLAN_OUTPUT,
    DEFAULT_SALVATION_CANDIDATE_DISCOVERY_AUDIT_OUTPUT,
    DEFAULT_SALVATION_REPEATABILITY_EXPANSION_OUTPUT,
    build_salvation_analytical_backfill_plan,
    evaluate_salvation_candidate_discovery_audit,
    evaluate_salvation_repeatability_expansion_plan,
    load_salvation_candidate_discovery_audit,
    load_salvation_repeatability_expansion_plan,
    write_salvation_analytical_backfill_plan,
    write_salvation_candidate_discovery_audit,
    write_salvation_repeatability_expansion_plan,
)
from pastor_transcript_extractor.sermon_salvation_exact_cohort import (
    DEFAULT_OUTPUT as DEFAULT_SALVATION_EXACT_COHORT_OUTPUT,
    DEFAULT_EVIDENCE_CACHE as DEFAULT_SALVATION_EXACT_COHORT_EVIDENCE_CACHE,
    DEFAULT_INTEGRITY_REVIEW as DEFAULT_SALVATION_EXACT_COHORT_INTEGRITY_REVIEW,
    build_exact_cohort_proposal,
    collect_exact_cohort_evidence,
    write_exact_cohort_proposal,
)
from pastor_transcript_extractor.sermon_salvation_convergence import (
    DEFAULT_OUTPUT as DEFAULT_SALVATION_CONVERGENCE_OUTPUT,
    DEFAULT_MEASUREMENT_CACHE as DEFAULT_SALVATION_MEASUREMENT_CACHE,
    build_convergence,
    collect_cohort_measurements,
    write_convergence,
)
from pastor_transcript_extractor.sermon_salvation_uncertainty import (
    DEFAULT_OUTPUT as DEFAULT_SALVATION_UNCERTAINTY_OUTPUT,
    build_uncertainty,
    write_uncertainty,
)
from pastor_transcript_extractor.sermon_salvation_rollout_inventory import (
    DEFAULT_DECISION as DEFAULT_SALVATION_ROLLOUT_DECISION,
    DEFAULT_OUTPUT as DEFAULT_SALVATION_ROLLOUT_INVENTORY_OUTPUT,
    evaluate_rollout_inventory,
    reusable_inventory,
    write_rollout_inventory,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.sermon_topic_evaluation import (
    DEFAULT_TOPIC_BEHAVIOR_FIXTURE,
    default_topic_behavior_output_path,
    evaluate_topic_behavior_fixture,
    load_topic_behavior_fixture,
    write_topic_behavior_report,
)
from pastor_transcript_extractor.sermon_topic_review import (
    DEFAULT_PROSPECTIVE_REVIEW_CASES,
    KNOWN_TOPIC_REVIEW_CASES,
    KNOWN_REVIEW_POLICY_VERSION,
    PROSPECTIVE_TOPIC_REVIEW_DEFAULT_FILENAME,
    PROSPECTIVE_REVIEW_POLICY_VERSION,
    TOPIC_REVIEW_DEFAULT_FILENAME,
    WHOLE_SERMON_REVIEW_POLICY_VERSION,
    WHOLE_SERMON_TOPIC_REVIEW_DEFAULT_FILENAME,
    build_topic_review_packet,
    build_topic_review_transcript_provenance,
    derive_prospective_topic_review_cases,
    derive_whole_sermon_topic_review_case,
    write_topic_review_packet,
)
from pastor_transcript_extractor.sermon_topic_review_adjudication import (
    create_topic_review_adjudication_draft,
    finalize_topic_review_adjudication,
)
from pastor_transcript_extractor.sermon_topic_projection import (
    assess_topic_profile_projection,
)
from pastor_transcript_extractor.sermon_topic_profile_analysis import (
    TOPIC_PROFILE_ANALYZER_KEY,
    TOPIC_PROFILE_ANALYZER_VERSION,
    build_profile_topic_analysis,
)
from pastor_transcript_extractor.sermon_topic_stage4 import (
    DEFAULT_TOPIC_STAGE4_COHORT,
    assess_topic_stage4_readiness,
    evaluate_topic_stage4,
    load_topic_stage4_cohort,
    write_topic_stage4_report,
)
from pastor_transcript_extractor.recording_verifier_typesafe import (
    TypeSafeSdkAdapter,
)


console = Console()


class _LazyTopicBehaviorClient:
    """Avoid requiring credentials when every fixture answer is already cached."""

    def __init__(self, *, model: str, timeout_seconds: float) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._client = None

    def assess_blocks(self, *args, **kwargs):
        if self._client is None:
            self._client = TypeSafeSdkAdapter(
                model=self.model,
                timeout_seconds=self.timeout_seconds,
            )
        return self._client.assess_blocks(*args, **kwargs)


def _print_topic_profile(database, run) -> None:
    values = {
        item.metric_key: json.loads(item.value_json)
        for item in database.list_speaker_profile_analysis_measurements(run.id)
    }
    coverage = Table(
        title=f"TypeSafe Topic Profile — Speaker Profile #{run.profile_id}"
    )
    coverage.add_column("Coverage")
    coverage.add_column("Value", justify="right")
    coverage.add_row(
        "Sermons analyzed",
        f"{values.get('sermons_analyzed', 0)} / {values.get('sermons_attached', 0)}",
    )
    coverage.add_row("Sermons blocked", str(values.get("sermons_blocked", 0)))
    coverage.add_row("Status", str(values.get("analytical_status", "unknown")))
    console.print(coverage)

    topics = Table(title="Equal-sermon Topic Measurements")
    topics.add_column("Topic")
    topics.add_column("Developed emphasis", justify="right")
    topics.add_column("Expected prominence*", justify="right")
    topic_profiles = values.get("topic_profiles", {})
    if isinstance(topic_profiles, dict):
        ordered = sorted(
            topic_profiles.items(),
            key=lambda item: float(
                item[1].get("developed_emphasis_probability", 0.0)
                if isinstance(item[1], dict)
                else 0.0
            ),
            reverse=True,
        )
        for topic, metrics in ordered:
            if not isinstance(metrics, dict):
                continue
            topics.add_row(
                str(topic),
                f"{float(metrics.get('developed_emphasis_probability', 0.0)):.3f}",
                (
                    f"{float(metrics.get('normalized_expected_prominence_sensitivity', 0.0)):.3f}"
                ),
            )
    console.print(topics)
    console.print(
        "* Expected prominence includes incidental level-1 probability and is a "
        "secondary sensitivity measure. Developed emphasis is primary."
    )
    console.print(
        "Exploratory only: Stage 4 cross-sermon repeatability is pending, so this "
        "profile must not be used for pastor comparisons."
    )
    console.print(
        f"Provenance: profile_analysis=#{run.id}; version={run.analyzer_version}; "
        f"membership={run.membership_fingerprint}; input={run.input_fingerprint}"
    )


def _topic_review_command(*, video_id: object, base_dir: Path) -> str:
    return shlex.join(
        [
            "pte",
            "analysis",
            "topic-review",
            "--video-id",
            str(video_id),
            "--whole-sermon",
            "--base-dir",
            str(base_dir),
        ]
    )


def _print_topic_stage4_readiness(
    report: Mapping[str, object],
    *,
    base_dir: Path | None = None,
) -> None:
    table = Table(title="TypeSafe Topic Stage 4 Readiness")
    table.add_column("Pastor")
    table.add_column("Profiles")
    table.add_column("Eligible", justify="right")
    table.add_column("Series", justify="right")
    table.add_column("Periods", justify="right")
    table.add_column("State")
    for pastor in report["pastors"]:
        sermons = pastor["sermons"]
        eligible = sum(bool(item["eligible"]) for item in sermons)
        blockers = pastor["blockers"]
        table.add_row(
            str(pastor.get("display_name") or pastor.get("slug") or "unknown"),
            ",".join(str(value) for value in pastor["effective_profile_ids"])
            or "—",
            f"{eligible}/{len(sermons)}",
            str(len(pastor["series_keys"])),
            str(len(pastor["period_keys"])),
            "ready" if not blockers else ", ".join(str(item) for item in blockers),
        )
    console.print(table)
    console.print(
        f"Overall: {'ready' if report['ready'] else 'blocked'}; "
        f"fingerprint={str(report['input_fingerprint'])[:12]}…"
    )
    actions = report.get("review_actions")
    if not isinstance(actions, list) or not actions:
        return

    resolved_base_dir = build_paths(base_dir).root
    pair_count = 0
    console.print("\nBounded next actions (no relation or boundary is pre-approved):")
    for index, action in enumerate(actions, start=1):
        if not isinstance(action, Mapping):
            continue
        action_type = action.get("action_type")
        pastor = action.get("pastor")
        pastor_name = (
            pastor.get("display_name")
            if isinstance(pastor, Mapping)
            else "unknown pastor"
        )
        if action_type == "review_speaker_pair":
            video_a = action.get("video_a")
            video_b = action.get("video_b")
            if not isinstance(video_a, Mapping) or not isinstance(video_b, Mapping):
                continue
            pair_count += 1
            command = shlex.join(
                [
                    "pte",
                    "identity",
                    "review-speaker-pair",
                    str(video_a["youtube_video_id"]),
                    str(video_b["youtube_video_id"]),
                    "--base-dir",
                    str(resolved_base_dir),
                ]
            )
            console.print(
                f"{index}. Identity review for {pastor_name}:\n   {command}",
                markup=False,
            )
        elif action_type == "prepare_topic_evidence":
            model = str(report.get("model") or DEFAULT_TYPESAFE_MODEL)
            reclassify = shlex.join(
                [
                    "pte",
                    "reclassify",
                    "--video-id",
                    str(action["video_id"]),
                    "--force",
                    "--jobs",
                    "1",
                    "--recording-verifier-backend",
                    "typesafe",
                    "--recording-verifier-model",
                    model,
                    "--base-dir",
                    str(resolved_base_dir),
                ]
            )
            review = _topic_review_command(
                video_id=action["video_id"], base_dir=resolved_base_dir
            )
            console.print(
                f"{index}. Cached topic evidence for {pastor_name}:\n"
                f"   {reclassify}\n"
                "   If the refreshed disposition is accepted_sermon:\n"
                f"   {review}\n"
                "   If it is review_required, do not create a provisional "
                "packet; rerun readiness for the boundary-first handoff.\n"
                "   Packet creation does not count as review; return an "
                "eligible packet for a fingerprinted decision.",
                markup=False,
            )
        elif action_type == "review_topic_evidence":
            review = _topic_review_command(
                video_id=action["video_id"], base_dir=resolved_base_dir
            )
            packet_path = action.get("packet_path")
            draft = (
                shlex.join(
                    [
                        "pte",
                        "analysis",
                        "topic-review-draft",
                        str(packet_path),
                    ]
                )
                if isinstance(packet_path, str) and packet_path.strip()
                else None
            )
            draft_step = (
                f"\n   Create or reuse its protected review draft:\n   {draft}"
                if draft is not None
                else ""
            )
            console.print(
                f"{index}. Whole-sermon topic review for {pastor_name}:\n"
                "   Cached TypeSafe observations are current; do not "
                "reclassify this sermon.\n"
                "   Reuse or prepare its fingerprint-bound packet:\n"
                f"   {review}{draft_step}\n"
                "   Inspect the draft Markdown and finalize only after the "
                "required whole-sermon checks.",
                markup=False,
            )
        elif action_type == "review_sermon_boundary":
            model = str(report.get("model") or DEFAULT_TYPESAFE_MODEL)
            command = shlex.join(
                [
                    "pte",
                    "review-ground-truth",
                    str(action["youtube_video_id"]),
                    "--base-dir",
                    str(resolved_base_dir),
                ]
            )
            apply_command = shlex.join(
                [
                    "pte",
                    "apply-fixture-correction",
                    str(action["youtube_video_id"]),
                    "--recording-verifier-backend",
                    "typesafe",
                    "--recording-verifier-model",
                    model,
                    "--base-dir",
                    str(resolved_base_dir),
                ]
            )
            pending_topic_reasons = action.get("pending_topic_reason_codes")
            topic_follow_up = ""
            if isinstance(pending_topic_reasons, list) and pending_topic_reasons:
                review_command = _topic_review_command(
                    video_id=action["video_id"], base_dir=resolved_base_dir
                )
                topic_follow_up = (
                    "\n   After the correction succeeds, prepare the final "
                    "fingerprint-bound topic packet:\n"
                    f"   {review_command}\n"
                    "   Packet creation does not count as review; return the "
                    "packet for a fingerprinted decision."
                )
            console.print(
                f"{index}. Sermon-boundary review for {pastor_name}:\n"
                f"   {command}\n"
                "   If that review approves one continuous sermon window:\n"
                f"   {apply_command}{topic_follow_up}",
                markup=False,
            )
        elif action_type == "supply_period_metadata":
            sermons = action.get("sermons")
            identifiers = ", ".join(
                f"#{item['video_id']} ({item['youtube_video_id']})"
                for item in sermons
                if isinstance(item, Mapping)
            ) if isinstance(sermons, list) else ""
            console.print(
                f"{index}. Trusted period metadata for {pastor_name}: "
                f"{identifiers or '—'}. Do not infer missing dates from order "
                "or identity.",
                markup=False,
            )
    if pair_count:
        sync_command = shlex.join(
            [
                "pte",
                "identity",
                "sync-reviewed-speaker-evidence",
                "--base-dir",
                str(resolved_base_dir),
            ]
        )
        console.print(
            "\nAfter adjudicating the pair packets, synchronize their reviewed "
            f"evidence once:\n   {sync_command}",
            markup=False,
        )
    recheck_command = shlex.join(
        [
            "pte",
            "analysis",
            "topic-stability-readiness",
            "--base-dir",
            str(resolved_base_dir),
        ]
    )
    console.print(
        f"\nThen recheck the immutable readiness inputs:\n   {recheck_command}",
        markup=False,
    )


def _print_analysis_readiness(report: ReadinessReport) -> None:
    table = Table(title="Deterministic Scripture Analysis Readiness")
    for heading in (
        "Profile", "State", "Effective", "Eligible", "Current", "Missing",
        "Stale", "Blocked", "Aggregate", "Depth",
    ):
        table.add_column(heading, justify="right" if heading not in {"Profile", "State", "Aggregate", "Depth"} else "left")
    for item in report.profiles:
        depth = (
            "decision (8+)" if item.eligible_sermons >= 8
            else "approaching (5+)" if item.approaching_decision_depth
            else "exploratory (3+)" if item.exploratory_eligible
            else "sparse"
        )
        table.add_row(
            f"#{item.profile_id} {item.display_label or ''}".rstrip(),
            item.lifecycle_state,
            str(item.effective_sermons),
            str(item.eligible_sermons),
            str(item.current_sermons),
            str(item.missing_sermons),
            str(item.stale_sermons),
            str(item.blocked_sermons),
            item.aggregate_state,
            depth,
        )
    console.print(table)
    aggregate_counts = {
        state: sum(item.aggregate_state == state for item in report.profiles)
        for state in ("current", "stale", "missing")
    }
    console.print(
        f"Coverage: eligible={report.eligible_sermons}, current={report.current_sermons}, "
        f"missing={report.missing_sermons}, stale={report.stale_sermons}, "
        f"blocked={report.blocked_sermons}, current={report.coverage_percent:.1f}%"
    )
    console.print(
        "Profile depth: "
        + ", ".join(
            f">={minimum}: {report.depth_count(minimum)}"
            for minimum in (3, 5, 8, 10)
        )
    )
    console.print(
        "Aggregates: "
        + ", ".join(f"{state}={count}" for state, count in aggregate_counts.items())
    )
    gate_profiles = [item for item in report.profiles if item.eligible_sermons >= 3]
    aggregate_gate = all(
        item.aggregate_state == "current" or item.blocked_sermons > 0
        for item in gate_profiles
    )
    console.print(
        "Readiness gate: "
        f"coverage>=90%={'yes' if report.coverage_percent >= 90 else 'no'}, "
        f">=3-sermon aggregates current-or-blocked={'yes' if aggregate_gate else 'no'}."
    )


@analysis_app.command("status", help="Report deterministic analysis readiness by profile.")
def analysis_status(
    all_profiles: bool = typer.Option(
        False, "--all-profiles", help="Include all active and provisional profiles."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    analyzer_version: str = typer.Option(
        SERMON_ANALYZER_VERSION, "--analyzer-version", help="Required sermon analyzer version."
    ),
    profile_analyzer_version: str = typer.Option(
        PROFILE_ANALYZER_VERSION,
        "--profile-analyzer-version",
        help="Required profile analyzer version.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if not all_profiles:
        raise typer.BadParameter("Pass --all-profiles to confirm corpus-wide scope.")
    report = build_readiness_report(
        get_database(base_dir),
        analyzer_version=analyzer_version,
        profile_analyzer_version=profile_analyzer_version,
    )
    if as_json:
        console.print_json(data=report.to_dict())
    else:
        _print_analysis_readiness(report)


@analysis_app.command(
    "backfill", help="Run a resumable deterministic sermon-analysis backfill."
)
def analysis_backfill(
    all_attached: bool = typer.Option(
        False, "--all-attached", help="Analyze eligible sermons attached to active/provisional profiles."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the exact plan without writes."),
    minimum_sermons: int = typer.Option(
        3, "--minimum-sermons", min=1, help="Minimum profile depth for aggregate refresh."
    ),
    analyzer_version: str = typer.Option(
        SERMON_ANALYZER_VERSION, "--analyzer-version", help="Sermon analyzer version to run."
    ),
    profile_analyzer_version: str = typer.Option(
        PROFILE_ANALYZER_VERSION,
        "--profile-analyzer-version",
        help="Profile analyzer version to build.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if not all_attached:
        raise typer.BadParameter("Pass --all-attached to confirm corpus-wide scope.")
    database = get_database(base_dir)
    report = build_readiness_report(
        database,
        analyzer_version=analyzer_version,
        profile_analyzer_version=profile_analyzer_version,
    )
    pending = [item for item in report.sermons if item.state != "current"]
    affected = sorted({profile_id for item in pending for profile_id in item.profile_ids})
    refresh_needed = [
        item.profile_id for item in report.profiles
        if item.eligible_sermons >= minimum_sermons
        and item.aggregate_state != "current"
    ]
    refresh_ready = [
        item.profile_id for item in report.profiles
        if item.profile_id in refresh_needed
        and item.current_sermons == item.eligible_sermons
    ]
    console.print(
        f"Plan: eligible={report.eligible_sermons}, current={report.current_sermons}, "
        f"missing={report.missing_sermons}, stale={report.stale_sermons}; "
        f"sermons_to_run={len(pending)}, affected_profiles={len(affected)}, "
        f"profiles_needing_refresh={len(refresh_needed)}, "
        f"profiles_already_ready_to_refresh={len(refresh_ready)}."
    )
    if dry_run:
        console.print(
            "Affected profiles: "
            + (", ".join(f"#{profile_id}" for profile_id in affected) or "none")
        )
        for item in pending:
            profiles = ",".join(f"#{profile_id}" for profile_id in item.profile_ids)
            suffix = f"; blocked: {item.blocking_reason}" if item.blocking_reason else ""
            console.print(
                f"Would analyze {item.youtube_video_id} (video #{item.video_id}, "
                f"{item.state}, profiles {profiles}){suffix}",
                markup=False,
            )
        if refresh_needed:
            console.print(
                "Would refresh after required sermon runs succeed: "
                + ", ".join(f"#{profile_id}" for profile_id in refresh_needed)
            )
        console.print("Dry run: no analysis or profile rows were written.")
        return
    result = run_deterministic_backfill(
        database,
        minimum_sermons=minimum_sermons,
        analyzer_version=analyzer_version,
        profile_analyzer_version=profile_analyzer_version,
    )
    for video_id, error in result.failed_sermons:
        console.print(f"Failed video #{video_id}: {error}", markup=False)
    for profile_id, error in result.failed_profiles:
        console.print(f"Failed profile #{profile_id}: {error}", markup=False)
    console.print(
        f"Backfill complete: sermon_created={result.created_sermon_runs}, "
        f"sermon_reused={result.reused_sermon_runs}, "
        f"sermon_skipped_current={result.before.current_sermons}, "
        f"sermon_failed={len(result.failed_sermons)}, "
        f"profile_created={result.created_profile_runs}, "
        f"profile_reused={result.reused_profile_runs}, "
        f"profile_failed={len(result.failed_profiles)}."
    )
    _print_analysis_readiness(result.after)


@analysis_app.command(
    "refresh-profiles", help="Refresh stale deterministic profile aggregates only."
)
def analysis_refresh_profiles(
    minimum_sermons: int = typer.Option(
        3, "--minimum-sermons", min=1, help="Minimum eligible sermons per profile."
    ),
    analyzer_version: str = typer.Option(
        SERMON_ANALYZER_VERSION, "--analyzer-version", help="Required sermon analyzer version."
    ),
    profile_analyzer_version: str = typer.Option(
        PROFILE_ANALYZER_VERSION,
        "--profile-analyzer-version",
        help="Profile analyzer version to build.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    created, reused, failures = refresh_profile_analyses(
        database,
        minimum_sermons=minimum_sermons,
        analyzer_version=analyzer_version,
        profile_analyzer_version=profile_analyzer_version,
    )
    for profile_id, error in failures:
        console.print(f"Failed profile #{profile_id}: {error}", markup=False)
    console.print(
        f"Profile refresh complete: created={created}, reused={reused}, "
        f"failed={len(failures)}."
    )
    _print_analysis_readiness(
        build_readiness_report(
            database,
            analyzer_version=analyzer_version,
            profile_analyzer_version=profile_analyzer_version,
        )
    )


def _print_population_analysis(snapshot: object, report: dict[str, object]) -> None:
    population = report["population"]
    console.print(
        f"Population snapshot #{snapshot.id}: profiles={population['profile_count']}, "
        f"sermons={population['sermon_count']}, "
        f"fingerprint={snapshot.input_fingerprint[:12]}…"
    )
    depth = population["depth_counts"]
    console.print(
        "Depth: "
        + ", ".join(f">={minimum}: {depth[str(minimum)]}" for minimum in (3, 5, 8, 10))
    )
    table = Table(title="Scripture Feature Diagnostics")
    table.add_column("Feature")
    table.add_column("N", justify="right")
    table.add_column("Missing", justify="right")
    table.add_column("Zero", justify="right")
    table.add_column("Deletion sensitivity")
    table.add_column("Size r", justify="right")
    table.add_column("Strong corr.", justify="right")
    table.add_column("Outliers", justify="right")
    table.add_column("Advisory recommendation")
    console.print("LOO measures aggregate deletion sensitivity, not pastor reliability. Depth cohorts are not learning curves.")
    diagnostics = report["feature_diagnostics"]
    for name in report["feature_names"]:
        item = diagnostics[name]
        distribution = item["distribution"]
        correlation = item["corpus_size_pearson"]
        table.add_row(
            name,
            str(distribution["observed_count"]),
            str(distribution["missing_count"]),
            str(distribution["zero_count"]),
            str(item["leave_one_out"].get("deletion_sensitivity",
                "historical stability label: " + str(item["leave_one_out"].get("stability")))),
            f"{correlation:.2f}" if correlation is not None else "—",
            str(len(item["highly_correlated_with"])),
            str(len(item["outliers"])),
            str(item["recommendation"]),
        )
    console.print(table)
    parity_failures = sum(
        (profile["recomputation_parity_max_absolute_delta"] or 0) > 0.000001
        for profile in report["profiles"]
    )
    console.print(
        f"Strong-correlation pairs: {len(report.get('strong_correlations', []))}; "
        f"high-correlation pairs: {len(report['high_correlations'])}; "
        f"profile recomputation parity failures: {parity_failures}."
    )
    metadata = report.get("metadata_coverage", {})
    if metadata:
        console.print(
            f"Metadata diagnostics: dated_sermons={metadata['dated_sermons']}/"
            f"{metadata['total_sermons']}, "
            f"date_split_profiles={metadata['profiles_eligible_for_date_split']}, "
            f"multi_source_profiles={metadata['multi_source_profiles']}."
        )
    console.print(
        "Recommendations are advisory; reviewed schema roles are recorded, but no "
        "similarity weights, rankings, or clusters were created."
    )


@analysis_app.command(
    "population-build",
    help="Freeze current profile runs and build deterministic population diagnostics.",
)
def analysis_population_build(
    minimum_sermons: int = typer.Option(
        3, "--minimum-sermons", min=2, help="Minimum current sermons per profile."
    ),
    bootstrap_samples: int = typer.Option(
        200, "--bootstrap-samples", min=20, help="Deterministic resamples per profile."
    ),
    analyzer_version: str = typer.Option(
        POPULATION_ANALYZER_VERSION,
        "--analyzer-version",
        help="Population diagnostic implementation version.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit the complete report as JSON."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        outcome = build_population_snapshot(
            get_database(base_dir),
            policy=PopulationPolicy(
                minimum_sermons=minimum_sermons,
                bootstrap_samples=bootstrap_samples,
            ),
            analyzer_version=analyzer_version,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    if as_json:
        console.print_json(
            data={
                "snapshot": {
                    "id": outcome.snapshot.id,
                    "created": outcome.created,
                    "created_at": outcome.snapshot.created_at.isoformat(),
                    "input_fingerprint": outcome.snapshot.input_fingerprint,
                },
                "report": outcome.report,
            }
        )
        return
    console.print("Created." if outcome.created else "Reused unchanged snapshot.")
    _print_population_analysis(outcome.snapshot, outcome.report)


@analysis_app.command(
    "population-show", help="Inspect a persisted population diagnostic snapshot."
)
def analysis_population_show(
    snapshot_id: int | None = typer.Option(None, "--snapshot-id", help="Default: latest."),
    as_json: bool = typer.Option(False, "--json", help="Emit the complete report as JSON."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        snapshot, report = load_population_snapshot_report(
            get_database(base_dir), snapshot_id=snapshot_id
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    if as_json:
        console.print_json(
            data={
                "snapshot": {
                    "id": snapshot.id,
                    "created_at": snapshot.created_at.isoformat(),
                    "input_fingerprint": snapshot.input_fingerprint,
                    "analyzer_version": snapshot.analyzer_version,
                },
                "report": report,
            }
        )
        return
    _print_population_analysis(snapshot, report)


@analysis_app.command(
    "run", help="Analyze one identified sermon or a speaker profile's attached sermons."
)
def analysis_run(
    video_id: int | None = typer.Option(None, "--video-id", help="Database video id."),
    youtube_video_id: str | None = typer.Option(
        None, "--youtube-video-id", help="YouTube video id."
    ),
    profile_id: int | None = typer.Option(
        None,
        "--profile-id",
        help="Canonical speaker profile id; selects effectively attached sermons.",
    ),
    pastor: str | None = typer.Option(
        None,
        "--pastor",
        help="Compatibility alias resolved through the pastor's speaker-profile binding.",
    ),
    analyzer_version: str = typer.Option(
        SERMON_ANALYZER_VERSION,
        "--analyzer-version",
        help="Version recorded in provenance; change this when analyzer behavior changes.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    videos, resolved_profile_id = _analysis_videos(
        database,
        video_id=video_id,
        youtube_video_id=youtube_video_id,
        profile_id=profile_id,
        pastor_slug=pastor,
    )
    if resolved_profile_id is not None:
        console.print(f"Speaker profile #{resolved_profile_id}: {len(videos)} sermon(s).")
    created = reused = skipped = 0
    for video in videos:
        try:
            outcome = analyze_sermon(
                database, video, analyzer_version=analyzer_version
            )
        except ValueError as error:
            if len(videos) == 1:
                raise typer.BadParameter(str(error)) from error
            skipped += 1
            console.print(f"Skipped {video.youtube_video_id}: {error}", markup=False)
            continue
        if outcome.created:
            created += 1
            state = "created"
        else:
            reused += 1
            state = "reused"
        console.print(
            f"{video.youtube_video_id}: analysis #{outcome.run.id} {state} "
            f"({outcome.run.analyzer_key}@{outcome.run.analyzer_version})"
        )
    console.print(
        f"Analysis complete: created={created}, reused={reused}, skipped={skipped}."
    )


@analysis_app.command(
    "topic-review",
    help="Build or reuse a bounded review packet from cached TypeSafe topic observations.",
)
def analysis_topic_review(
    video_id: int | None = typer.Option(None, "--video-id", help="Database video id."),
    youtube_video_id: str | None = typer.Option(
        None, "--youtube-video-id", help="YouTube video id."
    ),
    output_path: Path | None = typer.Option(
        None,
        "--output",
        help="JSON output path; defaults beside the video's extraction artifacts.",
    ),
    prospective: bool = typer.Option(
        False,
        "--prospective",
        help=(
            "Use the deterministic prospective sampler even when named regression "
            "cases exist."
        ),
    ),
    maximum_cases: int = typer.Option(
        DEFAULT_PROSPECTIVE_REVIEW_CASES,
        "--maximum-cases",
        min=1,
        max=20,
        help="Maximum cases selected in prospective mode.",
    ),
    whole_sermon: bool = typer.Option(
        False,
        "--whole-sermon",
        help="Include every cached topic block for whole-sermon analytical review.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    videos, _ = _analysis_videos(
        database,
        video_id=video_id,
        youtube_video_id=youtube_video_id,
        profile_id=None,
        pastor_slug=None,
    )
    video = videos[0]
    extraction = database.get_latest_extraction_result_for_video(video.id)
    proposed_path = (
        Path(extraction.proposed_json_path)
        if extraction is not None and extraction.proposed_json_path
        else None
    )
    if proposed_path is None:
        raise typer.BadParameter(f"Video #{video.id} has no extraction artifact")
    classification_path = proposed_path.parent / "llm-classification-v1.json"
    try:
        classification = json.loads(classification_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise typer.BadParameter(
            f"Cannot read classification artifact: {classification_path}"
        ) from error
    if not isinstance(classification, dict):
        raise typer.BadParameter(
            f"Classification artifact is not an object: {classification_path}"
        )
    try:
        proposed = json.loads(proposed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise typer.BadParameter(
            f"Cannot read extraction artifact: {proposed_path}"
        ) from error
    if not isinstance(proposed, dict):
        raise typer.BadParameter(
            f"Extraction artifact is not an object: {proposed_path}"
        )
    try:
        if whole_sermon and prospective:
            raise ValueError("Choose either --whole-sermon or --prospective, not both")
        prepared_cases = KNOWN_TOPIC_REVIEW_CASES.get(video.youtube_video_id)
        if whole_sermon:
            whole_case = derive_whole_sermon_topic_review_case(classification)
            cases = (whole_case,)
            selection = {
                "mode": "whole_sermon",
                "policy_version": WHOLE_SERMON_REVIEW_POLICY_VERSION,
                "maximum_cases": 1,
                "selected_block_count": len(whole_case.block_ids),
            }
            default_filename = WHOLE_SERMON_TOPIC_REVIEW_DEFAULT_FILENAME
        elif prospective or not prepared_cases:
            cases = derive_prospective_topic_review_cases(
                classification,
                maximum_cases=maximum_cases,
            )
            selection = {
                "mode": "prospective",
                "policy_version": PROSPECTIVE_REVIEW_POLICY_VERSION,
                "maximum_cases": maximum_cases,
            }
            default_filename = PROSPECTIVE_TOPIC_REVIEW_DEFAULT_FILENAME
        else:
            cases = prepared_cases
            selection = {
                "mode": "prepared_regression",
                "policy_version": KNOWN_REVIEW_POLICY_VERSION,
                "maximum_cases": len(cases),
            }
            default_filename = TOPIC_REVIEW_DEFAULT_FILENAME
        profile_projection_gate = assess_topic_profile_projection(
            database,
            video,
        )
        packet = build_topic_review_packet(
            classification,
            video_id=video.id,
            youtube_video_id=video.youtube_video_id,
            title=video.title,
            cases=cases,
            source_artifact_path=classification_path,
            profile_projection_gate=profile_projection_gate.to_dict(),
            selection=selection,
            transcript_provenance=build_topic_review_transcript_provenance(proposed),
        )
        result = write_topic_review_packet(
            output_path or proposed_path.parent / default_filename,
            packet,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    state = "Reused" if result.reused else "Wrote"
    console.print(
        f"{state} topic review packet: {result.json_path} and "
        f"{result.markdown_path} ({result.case_count} cases, "
        f"{result.block_count} blocks, mode={selection['mode']}, "
        f"fingerprint={result.input_fingerprint[:12]}…)",
        markup=False,
    )


@analysis_app.command(
    "topic-review-draft",
    help="Create a protected adjudication draft for a cached topic review packet.",
)
def analysis_topic_review_draft(
    packet: Path = typer.Argument(..., help="Topic review packet JSON file."),
    output_path: Path | None = typer.Option(
        None,
        "--output",
        help="Draft JSON path; defaults beside the source packet.",
    ),
    proposal: Path | None = typer.Option(
        None,
        "--proposal",
        help="Optional fingerprint-bound proposal used to prefill review corrections.",
    ),
) -> None:
    packet = packet.expanduser().resolve()
    output = output_path or packet.with_name(f"{packet.stem}.review-draft.json")
    try:
        result = create_topic_review_adjudication_draft(
            packet,
            output,
            proposal_path=proposal,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    state = "Reused" if result.reused else "Created"
    console.print(
        f"{state} topic review adjudication draft: {result.json_path} "
        f"(instructions: {result.markdown_path}, "
        f"packet={result.source_packet_fingerprint[:12]}…)",
        markup=False,
    )


@analysis_app.command(
    "topic-review-finalize",
    help="Validate and freeze a topic review separately from cached evidence.",
)
def analysis_topic_review_finalize(
    draft: Path = typer.Argument(..., help="Topic review adjudication draft JSON."),
    reviewer: str = typer.Option(..., "--reviewer", help="Reviewer identity."),
    output_path: Path | None = typer.Option(
        None,
        "--output",
        help="Final reviewed JSON path; defaults beside the draft.",
    ),
    accept_as_reviewed: bool = typer.Option(
        False,
        "--accept-as-reviewed",
        help="Confirm all required checks after inspecting the source packet.",
    ),
) -> None:
    draft = draft.expanduser().resolve()
    default_stem = (
        draft.stem[: -len(".review-draft")]
        if draft.stem.endswith(".review-draft")
        else draft.stem
    )
    output = output_path or draft.with_name(f"{default_stem}.reviewed.json")
    try:
        result = finalize_topic_review_adjudication(
            draft,
            output,
            reviewer=reviewer,
            accept_as_reviewed=accept_as_reviewed,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    state = "Reused" if result.reused else "Finalized"
    console.print(
        f"{state} topic review adjudication: {result.json_path} "
        f"(topic_corrections={result.topic_correction_count}, "
        f"projection_corrections={result.projection_correction_count}, "
        f"fingerprint={result.review_fingerprint[:12]}…)",
        markup=False,
    )


@analysis_app.command(
    "topic-summarize-profile",
    help=(
        "Materialize an exploratory equal-sermon profile from cached TypeSafe "
        "topic projections."
    ),
)
def analysis_topic_summarize_profile(
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    analyzer_version: str = typer.Option(
        TOPIC_PROFILE_ANALYZER_VERSION,
        "--analyzer-version",
        help="Topic profile analyzer version.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        outcome = build_profile_topic_analysis(
            database,
            profile_id,
            analyzer_version=analyzer_version,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"TypeSafe topic profile analysis #{outcome.run.id} "
        f"{'created' if outcome.created else 'reused'}."
    )
    _print_topic_profile(database, outcome.run)


@analysis_app.command(
    "topic-show-profile",
    help="Inspect the latest materialized exploratory TypeSafe topic profile.",
)
def analysis_topic_show_profile(
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        resolved_profile_id = database.resolve_speaker_profile_id(profile_id)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    run = database.get_latest_speaker_profile_analysis_run(
        resolved_profile_id, TOPIC_PROFILE_ANALYZER_KEY
    )
    if run is None:
        raise typer.BadParameter(
            "No materialized TypeSafe topic profile. Run "
            "'pte analysis topic-summarize-profile' first."
        )
    _print_topic_profile(database, run)


@analysis_app.command(
    "topic-stability-readiness",
    help=(
        "Audit reviewed identity, cached topic projections, and Stage 4 series/"
        "period strata without inference or writes."
    ),
)
def analysis_topic_stability_readiness(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Frozen topic cohort JSON with series and period metadata.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        report = assess_topic_stage4_readiness(database, cohort)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    _print_topic_stage4_readiness(report, base_dir=base_dir)


@analysis_app.command(
    "evaluate-topic-stability",
    help=(
        "Write cached Stage 4 equal-sermon, series, and period repeatability "
        "diagnostics after readiness passes."
    ),
)
def analysis_evaluate_topic_stability(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Frozen topic cohort JSON with series and period metadata.",
    ),
    output_path: Path = typer.Option(
        Path("evaluation/sermon-topics/stage4-topic-stability-v1.json"),
        "--output",
        help="Fingerprint-bound JSON report path; Markdown is written beside it.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        report = evaluate_topic_stage4(database, cohort)
        json_path, markdown_path, reused = write_topic_stage4_report(
            output_path,
            report,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} TypeSafe topic stability report: "
        f"{json_path} and {markdown_path}; status={report['status']}; "
        f"fingerprint={report['input_fingerprint'][:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-routing-review",
    help=(
        "Write a provider-free calibration packet for the conditional salvation "
        "leaf route."
    ),
)
def analysis_salvation_routing_review(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying cached broad observations.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_ROUTING_REVIEW_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        packet = build_salvation_routing_review_packet(database, cohort)
        json_path, markdown_path, reused = write_salvation_routing_review(
            output_path,
            packet,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    route_counts = ",".join(
        f"{threshold}:{count}"
        for threshold, count in packet["route_counts_by_threshold"].items()
    )
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation routing review: "
        f"{json_path} and {markdown_path}; "
        f"eligible_blocks={packet['candidate_count']}; "
        f"projected_routes={route_counts}; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-relationships-review",
    help=(
        "Evaluate a bounded, independently cached salvation relationship leaf sample."
    ),
)
def analysis_salvation_relationships_review(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying cached broad observations.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_RELATIONSHIP_REVIEW_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    model: str = typer.Option(
        DEFAULT_TYPESAFE_MODEL,
        "--model",
        help="Pinned TypeSafe model id used for the leaf judgments.",
    ),
    timeout_seconds: float = typer.Option(
        45.0,
        "--timeout-seconds",
        min=1.0,
        help="Timeout for each uncached TypeSafe request.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        packet, execution = evaluate_salvation_relationship_review(
            database,
            cohort,
            model=model,
            client=_LazyTopicBehaviorClient(
                model=model,
                timeout_seconds=timeout_seconds,
            ),
        )
        json_path, markdown_path, reused = write_salvation_relationship_review(
            output_path,
            packet,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation relationship review: "
        f"{json_path} and {markdown_path}; "
        f"cases={len(packet['cases'])}; "
        f"cache_hits={execution['hits']}; "
        f"cache_misses={execution['misses']}; "
        f"provider_requests={execution['provider_requests']}; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-obedience-calibration",
    help=(
        "Evaluate a final cache-first sample for obedience as consequence or "
        "evidence."
    ),
)
def analysis_salvation_obedience_calibration(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying cached broad observations.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_OBEDIENCE_CALIBRATION_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    model: str = typer.Option(
        DEFAULT_TYPESAFE_MODEL,
        "--model",
        help="Pinned TypeSafe model id used for the leaf judgments.",
    ),
    timeout_seconds: float = typer.Option(
        45.0,
        "--timeout-seconds",
        min=1.0,
        help="Timeout for each uncached TypeSafe request.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        packet, execution = evaluate_obedience_consequence_calibration(
            database,
            cohort,
            model=model,
            client=_LazyTopicBehaviorClient(
                model=model,
                timeout_seconds=timeout_seconds,
            ),
        )
        json_path, markdown_path, reused = (
            write_obedience_consequence_calibration(output_path, packet)
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} obedience-consequence calibration: "
        f"{json_path} and {markdown_path}; "
        f"attempted={len(packet['attempted_cases'])}; "
        f"probes={len(packet['probes'])}; "
        f"cache_hits={execution['hits']}; "
        f"cache_misses={execution['misses']}; "
        f"provider_requests={execution['provider_requests']}; "
        f"status={packet['status']}; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-semantic-calibration",
    help=(
        "Evaluate revised salvation leaf semantics on regressions and fresh held-out "
        "boundaries, plus a cached assurance search."
    ),
)
def analysis_salvation_semantic_calibration(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying routed blocks and reviewed v2 evidence.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_SEMANTIC_CALIBRATION_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    model: str = typer.Option(
        DEFAULT_TYPESAFE_MODEL,
        "--model",
        help="Pinned TypeSafe model id used for revised leaf judgments.",
    ),
    timeout_seconds: float = typer.Option(
        45.0,
        "--timeout-seconds",
        min=1.0,
        help="Timeout for each uncached TypeSafe request.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        packet, execution = evaluate_salvation_semantic_calibration(
            database,
            cohort,
            model=model,
            client=_LazyTopicBehaviorClient(
                model=model,
                timeout_seconds=timeout_seconds,
            ),
        )
        json_path, markdown_path, reused = write_salvation_semantic_calibration(
            output_path,
            packet,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation semantic calibration: "
        f"{json_path} and {markdown_path}; "
        f"regressions={len(packet['regression_probes'])}; "
        f"held_out={len(packet['heldout_probes'])}; "
        f"assurance_cached={len(packet['assurance_upward_probes'])}; "
        f"cache_hits={execution['hits']}; "
        f"cache_misses={execution['misses']}; "
        f"provider_requests={execution['provider_requests']}; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-final-calibration",
    help=(
        "Run the bounded faith-recall and repentance-ordering acceptance check."
    ),
)
def analysis_salvation_final_calibration(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying routed blocks and reviewed v2 evidence.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_FINAL_CALIBRATION_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    model: str = typer.Option(
        DEFAULT_TYPESAFE_MODEL,
        "--model",
        help="Pinned TypeSafe model id used for revised leaf judgments.",
    ),
    timeout_seconds: float = typer.Option(
        45.0,
        "--timeout-seconds",
        min=1.0,
        help="Timeout for each uncached TypeSafe request.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        packet, execution = evaluate_salvation_final_calibration(
            database,
            cohort,
            model=model,
            client=_LazyTopicBehaviorClient(
                model=model,
                timeout_seconds=timeout_seconds,
            ),
        )
        json_path, markdown_path, reused = write_salvation_final_calibration(
            output_path,
            packet,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation final calibration: "
        f"{json_path} and {markdown_path}; "
        f"faith={len(packet['faith_probes'])}; "
        f"repentance={len(packet['repentance_probes'])}; "
        f"cache_hits={execution['hits']}; "
        f"cache_misses={execution['misses']}; "
        f"provider_requests={execution['provider_requests']}; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-v5-calibration",
    help=(
        "Evaluate four revised salvation questions on reviewed and held-out cases."
    ),
)
def analysis_salvation_v5_calibration(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying routed blocks and v4 evidence.",
    ),
    boundary_review_path: Path = typer.Option(
        Path("evaluation/sermon-topics/salvation-boundary-recalibration-v1.json"),
        "--boundary-review",
        help="Reviewed four-leaf v4 boundary packet.",
    ),
    collection_review_path: Path = typer.Option(
        DEFAULT_SALVATION_COLLECTED_OBSERVATION_REVIEW_OUTPUT,
        "--collection-review",
        help="Reviewed ordinary-classification packet used to exclude prior cases.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_V5_CALIBRATION_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    model: str = typer.Option(
        DEFAULT_TYPESAFE_MODEL,
        "--model",
        help="Pinned TypeSafe model id used for revised leaf judgments.",
    ),
    timeout_seconds: float = typer.Option(
        45.0,
        "--timeout-seconds",
        min=1.0,
        help="Timeout for each uncached TypeSafe request.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        boundary_review = load_salvation_collected_observations_review(
            boundary_review_path
        )
        collection_review = load_salvation_collected_observations_review(
            collection_review_path
        )
        packet, execution = evaluate_salvation_v5_calibration(
            database,
            cohort,
            boundary_review,
            collection_review,
            model=model,
            client=_LazyTopicBehaviorClient(
                model=model,
                timeout_seconds=timeout_seconds,
            ),
        )
        json_path, markdown_path, reused = write_salvation_v5_calibration(
            output_path,
            packet,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation v5 calibration: "
        f"{json_path} and {markdown_path}; "
        f"regressions={len(packet['regression_probes'])}; "
        f"held_out={len(packet['heldout_probes'])}; "
        f"cache_hits={execution['hits']}; "
        f"cache_misses={execution['misses']}; "
        f"provider_requests={execution['provider_requests']}; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-v5-threshold-review",
    help="Build the provider-free final threshold review from cached v5 judgments.",
)
def analysis_salvation_v5_threshold_review(
    input_path: Path = typer.Option(
        DEFAULT_SALVATION_V5_CALIBRATION_OUTPUT,
        "--input",
        help="Reviewed v5 calibration packet.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_V5_THRESHOLD_REVIEW_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
) -> None:
    try:
        calibration = load_salvation_v5_calibration(input_path)
        packet = build_salvation_v5_threshold_review(calibration)
        json_path, markdown_path, reused = write_salvation_v5_threshold_review(
            output_path,
            packet,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation v5 threshold review: "
        f"{json_path} and {markdown_path}; "
        f"probes={len(packet['probes'])}; "
        f"cases={len(packet['cases'])}; "
        "provider_requests=0; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-v6-repentance-calibration",
    help="Run the bounded v6 repentance-entry regression and held-out check.",
)
def analysis_salvation_v6_repentance_calibration(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying routed evidence.",
    ),
    final_check_path: Path = typer.Option(
        DEFAULT_SALVATION_FINAL_COLLECTION_CHECK_OUTPUT,
        "--final-check",
        help="Reviewed final collection boundary check.",
    ),
    v5_calibration_path: Path = typer.Option(
        DEFAULT_SALVATION_V5_CALIBRATION_OUTPUT,
        "--v5-calibration",
        help="Reviewed v5 semantic calibration used to exclude prior cases.",
    ),
    collection_review_path: Path = typer.Option(
        DEFAULT_SALVATION_COLLECTED_OBSERVATION_REVIEW_OUTPUT,
        "--collection-review",
        help="Reviewed ordinary-classification packet used to exclude prior cases.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_V6_REPENTANCE_CALIBRATION_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    model: str = typer.Option(
        DEFAULT_TYPESAFE_MODEL,
        "--model",
        help="Pinned TypeSafe model id used for revised leaf judgments.",
    ),
    timeout_seconds: float = typer.Option(
        45.0,
        "--timeout-seconds",
        min=1.0,
        help="Timeout for each uncached TypeSafe request.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        final_check = load_salvation_collected_observations_review(final_check_path)
        v5_calibration = load_salvation_v5_calibration(v5_calibration_path)
        collection_review = load_salvation_collected_observations_review(
            collection_review_path
        )
        packet, execution = evaluate_salvation_v6_repentance_calibration(
            database,
            cohort,
            final_check,
            v5_calibration,
            collection_review,
            model=model,
            client=_LazyTopicBehaviorClient(
                model=model,
                timeout_seconds=timeout_seconds,
            ),
        )
        json_path, markdown_path, reused = (
            write_salvation_v6_repentance_calibration(output_path, packet)
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation v6 repentance calibration: "
        f"{json_path} and {markdown_path}; "
        f"regressions={len(packet['regression_probes'])}; "
        f"held_out={len(packet['heldout_probes'])}; "
        f"cache_hits={execution['hits']}; "
        f"cache_misses={execution['misses']}; "
        f"provider_requests={execution['provider_requests']}; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-v7-repentance-calibration",
    help="Run the final bounded observational repentance calibration.",
)
def analysis_salvation_v7_repentance_calibration(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying routed evidence.",
    ),
    v6_calibration_path: Path = typer.Option(
        DEFAULT_SALVATION_V6_REPENTANCE_CALIBRATION_OUTPUT,
        "--v6-calibration",
        help="Reviewed v6 repentance packet supplying regressions and exclusions.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_V7_REPENTANCE_CALIBRATION_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    model: str = typer.Option(
        DEFAULT_TYPESAFE_MODEL,
        "--model",
        help="Pinned TypeSafe model id used for revised leaf judgments.",
    ),
    timeout_seconds: float = typer.Option(
        45.0,
        "--timeout-seconds",
        min=1.0,
        help="Timeout for each uncached TypeSafe request.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        v6_calibration = load_salvation_v6_repentance_calibration(
            v6_calibration_path
        )
        packet, execution = evaluate_salvation_v7_repentance_calibration(
            database,
            cohort,
            v6_calibration,
            model=model,
            client=_LazyTopicBehaviorClient(
                model=model,
                timeout_seconds=timeout_seconds,
            ),
        )
        json_path, markdown_path, reused = (
            write_salvation_v7_repentance_calibration(output_path, packet)
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation v7 repentance calibration: "
        f"{json_path} and {markdown_path}; "
        f"regressions={len(packet['regression_probes'])}; "
        f"held_out={len(packet['heldout_probes'])}; "
        f"cache_hits={execution['hits']}; "
        f"cache_misses={execution['misses']}; "
        f"provider_requests={execution['provider_requests']}; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-v8-conversion-calibration",
    help="Run the bounded v8 saving-state-transition conversion calibration.",
)
def analysis_salvation_v8_conversion_calibration(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying routed v7 evidence.",
    ),
    conversion_review_path: Path = typer.Option(
        DEFAULT_SALVATION_CONVERSION_RECALIBRATION_OUTPUT,
        "--conversion-review",
        help="Reviewed conversion-only packet supplying regressions and exclusions.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_V8_CONVERSION_CALIBRATION_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    model: str = typer.Option(
        DEFAULT_TYPESAFE_MODEL,
        "--model",
        help="Pinned TypeSafe model id used for revised leaf judgments.",
    ),
    timeout_seconds: float = typer.Option(
        45.0,
        "--timeout-seconds",
        min=1.0,
        help="Timeout for each uncached TypeSafe request.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        conversion_review = load_salvation_collected_observations_review(
            conversion_review_path
        )
        packet, execution = evaluate_salvation_v8_conversion_calibration(
            database,
            cohort,
            conversion_review,
            model=model,
            client=_LazyTopicBehaviorClient(
                model=model,
                timeout_seconds=timeout_seconds,
            ),
        )
        json_path, markdown_path, reused = (
            write_salvation_v8_conversion_calibration(output_path, packet)
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation v8 conversion calibration: "
        f"{json_path} and {markdown_path}; "
        f"regressions={len(packet['regression_probes'])}; "
        f"held_out={len(packet['heldout_probes'])}; "
        f"cache_hits={execution['hits']}; "
        f"cache_misses={execution['misses']}; "
        f"provider_requests={execution['provider_requests']}; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-final-boundary-calibration",
    help="Run the final bounded atonement, judgment, consequence, and transcript review.",
)
def analysis_salvation_final_boundary_calibration(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying routed V8 evidence.",
    ),
    collection_review_path: Path = typer.Option(
        DEFAULT_SALVATION_COLLECTED_OBSERVATION_REVIEW_OUTPUT,
        "--collection-review",
        help="Reviewed V8 ordinary-classification boundary packet.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_FINAL_BOUNDARY_CALIBRATION_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    model: str = typer.Option(
        DEFAULT_TYPESAFE_MODEL,
        "--model",
        help="Pinned TypeSafe model id used for revised consequence judgments.",
    ),
    timeout_seconds: float = typer.Option(
        45.0,
        "--timeout-seconds",
        min=1.0,
        help="Timeout for each uncached TypeSafe request.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        collection_review = load_salvation_collected_observations_review(
            collection_review_path
        )
        packet, execution = evaluate_salvation_final_boundary_calibration(
            database,
            cohort,
            collection_review,
            model=model,
            client=_LazyTopicBehaviorClient(
                model=model,
                timeout_seconds=timeout_seconds,
            ),
        )
        json_path, markdown_path, reused = (
            write_salvation_final_boundary_calibration(output_path, packet)
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} final salvation boundary calibration: "
        f"{json_path} and {markdown_path}; "
        f"numeric={len(packet['numeric_probes'])}; "
        f"consequence_regressions={len(packet['consequence_regression_probes'])}; "
        f"consequence_held_out={len(packet['consequence_heldout_probes'])}; "
        f"cache_hits={execution['hits']}; "
        f"cache_misses={execution['misses']}; "
        f"provider_requests={execution['provider_requests']}; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-condition-boundary-review",
    help="Build the provider-free final condition/means probability-tail review.",
)
def analysis_salvation_condition_boundary_review(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying routed V8 evidence.",
    ),
    final_boundary_path: Path = typer.Option(
        DEFAULT_SALVATION_FINAL_BOUNDARY_CALIBRATION_OUTPUT,
        "--final-boundary",
        help="Reviewed final boundary packet containing the transcription case.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_CONDITION_BOUNDARY_REVIEW_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        final_boundary = load_salvation_final_boundary_calibration(
            final_boundary_path
        )
        packet = build_salvation_condition_boundary_review(
            database,
            cohort,
            final_boundary,
        )
        json_path, markdown_path, reused = write_salvation_condition_boundary_review(
            output_path,
            packet,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation condition/means boundary review: "
        f"{json_path} and {markdown_path}; "
        f"probes={len(packet['probes'])}; provider_requests=0; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-consequence-boundary-review",
    help="Build the provider-free final V9 consequence/evidence ordering review.",
)
def analysis_salvation_consequence_boundary_review(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying routed V9 evidence.",
    ),
    collection_review_path: Path = typer.Option(
        DEFAULT_SALVATION_COLLECTED_OBSERVATION_REVIEW_OUTPUT,
        "--collection-review",
        help="Reviewed V9 collected-observation packet containing the regressions.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_CONSEQUENCE_BOUNDARY_REVIEW_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        collection_review = load_salvation_collected_observations_review(
            collection_review_path
        )
        packet = build_salvation_consequence_boundary_review(
            database,
            cohort,
            collection_review,
        )
        json_path, markdown_path, reused = (
            write_salvation_consequence_boundary_review(output_path, packet)
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation consequence/evidence "
        f"boundary review: {json_path} and {markdown_path}; "
        f"regressions={len(packet['regression_labels'])}; "
        f"fresh={packet['fresh_probe_count']}; provider_requests=0; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-observation-threshold-review",
    help=(
        "Build a provider-free boundary review for the salvation leaf collection "
        "threshold."
    ),
)
def analysis_salvation_observation_threshold_review(
    input_paths: list[Path] = typer.Option(
        list(DEFAULT_SALVATION_RELATIONSHIP_REVIEW_INPUTS),
        "--input",
        help="Reviewed salvation relationship packet; repeat for each packet.",
    ),
    candidate_threshold: float = typer.Option(
        DEFAULT_SALVATION_OBSERVATION_THRESHOLD,
        "--candidate-threshold",
        min=0.01,
        max=0.99,
        help="Proposed probability boundary for affirmative leaf observations.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_OBSERVATION_THRESHOLD_REVIEW_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
) -> None:
    try:
        packet = build_salvation_observation_threshold_review(
            input_paths,
            candidate_threshold=candidate_threshold,
        )
        json_path, markdown_path, reused = (
            write_salvation_observation_threshold_review(output_path, packet)
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation observation threshold review: "
        f"{json_path} and {markdown_path}; "
        f"judgments={packet['judgment_count']}; "
        f"probes={len(packet['probes'])}; "
        f"candidate_threshold={float(packet['candidate_threshold']):.2f}; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-observation-boundaries-review",
    help=(
        "Build a provider-free focused review for per-relationship salvation leaf "
        "boundaries."
    ),
)
def analysis_salvation_observation_boundaries_review(
    input_paths: list[Path] = typer.Option(
        list(DEFAULT_SALVATION_RELATIONSHIP_REVIEW_INPUTS),
        "--input",
        help="Reviewed salvation relationship packet; repeat for each packet.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_OBSERVATION_BOUNDARIES_REVIEW_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
) -> None:
    try:
        packet = build_salvation_observation_boundaries_review(input_paths)
        json_path, markdown_path, reused = (
            write_salvation_observation_boundaries_review(output_path, packet)
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation observation boundaries review: "
        f"{json_path} and {markdown_path}; "
        f"settled_leaves={len(packet['settled_thresholds'])}; "
        f"ambiguous_leaves={len(packet['ambiguous_calibration'])}; "
        f"probes={len(packet['probes'])}; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-collected-observations-review",
    help=(
        "Build a provider-free boundary review from collected salvation observations."
    ),
)
def analysis_salvation_collected_observations_review(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying ordinary classification artifacts.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_COLLECTED_OBSERVATION_REVIEW_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        readiness = assess_topic_stage4_readiness(database, cohort)
        if not readiness["ready"]:
            _print_topic_stage4_readiness(readiness, base_dir=base_dir)
        packet = evaluate_salvation_collected_observations_review(
            database,
            cohort,
            readiness=readiness,
        )
        json_path, markdown_path, reused = (
            write_salvation_collected_observations_review(output_path, packet)
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    collected = sum(
        int(counts["collected"])
        for counts in packet["counts_by_relationship"].values()
    )
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation collected observations review: "
        f"{json_path} and {markdown_path}; "
        f"videos={packet['source_video_count']}; "
        f"routed_blocks={packet['routed_block_count']}; "
        f"collected_observations={collected}; "
        f"probes={len(packet['probes'])}; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-profile-repeatability",
    help=(
        "Build provider-free equal-sermon repeatability diagnostics for the "
        "approved salvation observations."
    ),
)
def analysis_salvation_profile_repeatability(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying current salvation artifacts.",
    ),
    review_path: Path = typer.Option(
        DEFAULT_SALVATION_COLLECTED_OBSERVATION_REVIEW_OUTPUT,
        "--collection-review",
        help=(
            "Approved nine-leaf collection review; its fingerprint must be "
            f"{APPROVED_SALVATION_COLLECTION_REVIEW_FINGERPRINT[:12]}…."
        ),
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_PROFILE_REPEATABILITY_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON report path; Markdown is written beside it.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        review = load_salvation_collected_observations_review(review_path)
        report = evaluate_salvation_profile_repeatability(database, cohort, review)
        json_path, markdown_path, reused = write_salvation_profile_repeatability(
            output_path,
            report,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation profile repeatability: "
        f"{json_path} and {markdown_path}; "
        f"pastors={len(report['pastors'])}; "
        f"measured_leaves={len(report['measured_relationships'])}; "
        f"unresolved_leaves={len(report['unresolved_relationships'])}; "
        f"provider_requests={report['provider_requests']}; "
        f"fingerprint={str(report['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-repeatability-expansion-plan",
    help=(
        "Inventory provider-free eligible candidates for the larger salvation "
        "repeatability cohort."
    ),
)
def analysis_salvation_repeatability_expansion_plan(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen three-sermon baseline cohort.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_REPEATABILITY_EXPANSION_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON candidate inventory; Markdown is written beside it.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        report = evaluate_salvation_repeatability_expansion_plan(database, cohort)
        json_path, markdown_path, reused = (
            write_salvation_repeatability_expansion_plan(output_path, report)
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation repeatability expansion plan: "
        f"{json_path} and {markdown_path}; "
        f"pastors={len(report['pastors'])}; "
        f"eligible_candidates={sum(int(item['eligible_candidate_count']) for item in report['pastors'])}; "
        f"provider_requests={report['provider_requests']}; "
        f"fingerprint={str(report['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-exact-cohort-proposal",
    help="Build a cached, provider-free exact-cohort packet with provenance and shortfalls.",
)
def analysis_salvation_exact_cohort_proposal(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT, "--cohort", help="Reviewed baseline cohort."
    ),
    inventory_path: Path = typer.Option(
        DEFAULT_SALVATION_REPEATABILITY_EXPANSION_OUTPUT,
        "--inventory", help="Current candidate inventory.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_EXACT_COHORT_OUTPUT,
        "--output", help="Fingerprint-bound JSON and Markdown proposal.",
    ),
    integrity_review_path: Path = typer.Option(
        DEFAULT_SALVATION_EXACT_COHORT_INTEGRITY_REVIEW,
        "--integrity-review", help="Bounded source-backed cohort integrity evidence.",
    ),
    base_dir: Path | None = typer.Option(
        None, "--base-dir", help="Application data directory containing app.db."
    ),
) -> None:
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        inventory = load_salvation_repeatability_expansion_plan(inventory_path)
        integrity_review = json.loads(integrity_review_path.read_text(encoding="utf-8"))
        database = Database(build_paths(base_dir).database, readonly=True)
        evidence, cache_hit = collect_exact_cohort_evidence(
            database, inventory, DEFAULT_SALVATION_EXACT_COHORT_EVIDENCE_CACHE
        )
        report = build_exact_cohort_proposal(inventory, cohort, evidence, integrity_review)
        json_path, markdown_path, reused = write_exact_cohort_proposal(output_path, report)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation exact-cohort proposal: "
        f"{json_path} and {markdown_path}; status={report['status']}; "
        f"evidence_cache={'hit' if cache_hit else 'miss'}; "
        f"provider_requests={report['provider_requests']}; "
        f"fingerprint={str(report['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-nine-leaf-convergence",
    help="Analyze frozen exact cohorts at every supported provider-free checkpoint.",
)
def analysis_salvation_nine_leaf_convergence(
    proposal_path: Path = typer.Option(
        DEFAULT_SALVATION_EXACT_COHORT_OUTPUT,
        "--proposal",
        help="Frozen v3 independent-sermon proposal.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_CONVERGENCE_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON and Markdown convergence report.",
    ),
    cache_path: Path = typer.Option(
        DEFAULT_SALVATION_MEASUREMENT_CACHE, "--measurement-cache",
        help="Shared frozen-cohort measurement cache, validated against current source evidence.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db.",
    ),
) -> None:
    try:
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        database = Database(build_paths(base_dir).database, readonly=True)
        sermons, cache_hit = collect_cohort_measurements(database, proposal, cache_path)
        report = build_convergence(proposal, sermons)
        json_path, markdown_path, reused = write_convergence(output_path, report)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation nine-leaf convergence: "
        f"{json_path} and {markdown_path}; "
        f"sermons={[pastor['sermon_count'] for pastor in report['pastors']]}; "
        f"measurement_cache={'hit' if cache_hit else 'miss'}; "
        f"provider_requests={report['provider_requests']}; "
        f"fingerprint={str(report['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-pastor-uncertainty",
    help="Prepare frozen-cohort omission, checkpoint, strata, and denominator sensitivity without inference.",
)
def analysis_salvation_pastor_uncertainty(
    proposal_path: Path = typer.Option(
        DEFAULT_SALVATION_EXACT_COHORT_OUTPUT, "--proposal", help="Frozen v3 independent-sermon proposal.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_UNCERTAINTY_OUTPUT, "--output", help="Fingerprint-bound JSON and Markdown review packet.",
    ),
    cache_path: Path = typer.Option(
        DEFAULT_SALVATION_MEASUREMENT_CACHE, "--measurement-cache",
        help="Shared frozen-cohort measurement cache, validated against current source evidence.",
    ),
    base_dir: Path | None = typer.Option(None, "--base-dir", help="Application-data directory containing app.db."),
) -> None:
    try:
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        database = Database(build_paths(base_dir).database, readonly=True)
        sermons, cache_hit = collect_cohort_measurements(database, proposal, cache_path)
        report = build_uncertainty(proposal, sermons)
        json_path, markdown_path, reused = write_uncertainty(output_path, report)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation pastor uncertainty: {json_path} and {markdown_path}; "
        f"measurement_cache={'hit' if cache_hit else 'miss'}; provider_requests=0; "
        f"fingerprint={str(report['input_fingerprint'])[:12]}…", markup=False,
    )


@analysis_app.command(
    "salvation-broader-rollout-inventory",
    help="Inventory frozen nine-leaf cache coverage and bounded missing work without provider calls.",
)
def analysis_salvation_broader_rollout_inventory(
    decision_path: Path = typer.Option(
        DEFAULT_SALVATION_ROLLOUT_DECISION,
        "--decision",
        help="Approved nine-question stage-gate decision.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_ROLLOUT_INVENTORY_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON and Markdown inventory.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db.",
    ),
) -> None:
    try:
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        database = Database(build_paths(base_dir).database, readonly=True)
        report = reusable_inventory(output_path, database.database_path, decision)
        cache_hit = report is not None
        if report is None:
            report = evaluate_rollout_inventory(database, decision)
        json_path, markdown_path, reused = write_rollout_inventory(output_path, report)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation broader rollout inventory: "
        f"{json_path} and {markdown_path}; "
        f"cache={'hit' if cache_hit else 'miss'}; "
        f"ready={report['counts']['nine_leaf_ready']}/"
        f"{report['counts']['content_gate_eligible']}; "
        f"missing_blocks={report['work_estimate']['missing_routed_block_count']}; "
        f"provider_requests={report['provider_requests']}; "
        f"fingerprint={str(report['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-candidate-discovery-audit",
    help=(
        "Explain whether salvation repeatability candidates are missing at "
        "ingestion, identity, eligibility, analytical, query, or metadata gates."
    ),
)
def analysis_salvation_candidate_discovery_audit(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen three-sermon baseline cohort.",
    ),
    inventory_path: Path = typer.Option(
        DEFAULT_SALVATION_REPEATABILITY_EXPANSION_OUTPUT,
        "--inventory",
        help="Current provider-free expansion candidate inventory.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_CANDIDATE_DISCOVERY_AUDIT_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON audit path; Markdown is written beside it.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        inventory = load_salvation_repeatability_expansion_plan(inventory_path)
        report = evaluate_salvation_candidate_discovery_audit(
            database,
            cohort,
            inventory,
        )
        json_path, markdown_path, reused = write_salvation_candidate_discovery_audit(
            output_path,
            report,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation candidate-discovery audit: "
        f"{json_path} and {markdown_path}; "
        f"associated_videos={sum(int(item['ingested_associated_count']) for item in report['pastors'])}; "
        f"current_candidates={sum(len(item['current_candidate_video_ids']) for item in report['pastors'])}; "
        f"blockers={','.join(report['blockers']) or 'none'}; "
        f"provider_requests={report['provider_requests']}; "
        f"fingerprint={str(report['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-analytical-backfill-plan",
    help=(
        "Prepare exact cache-aware reclassification commands for linked, "
        "production-eligible topic-analysis-only blockers."
    ),
)
def analysis_salvation_analytical_backfill_plan(
    audit_path: Path = typer.Option(
        DEFAULT_SALVATION_CANDIDATE_DISCOVERY_AUDIT_OUTPUT,
        "--audit",
        help="Reviewed provider-free candidate-discovery audit.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_ANALYTICAL_BACKFILL_PLAN_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON backfill plan; Markdown is written beside it.",
    ),
) -> None:
    try:
        audit = load_salvation_candidate_discovery_audit(audit_path)
        report = build_salvation_analytical_backfill_plan(audit)
        json_path, markdown_path, reused = write_salvation_analytical_backfill_plan(
            output_path,
            report,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation analytical backfill plan: "
        f"{json_path} and {markdown_path}; "
        f"targets={len(report['video_ids'])}; "
        f"profiles={sum(bool(item['backfill_target_count']) for item in report['pastors'])}; "
        f"provider_requests={report['provider_requests_during_planning']}; "
        f"fingerprint={str(report['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-conversion-recalibration",
    help="Build the provider-free conversion-only boundary ordering check.",
)
def analysis_salvation_conversion_recalibration(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying ordinary classification artifacts.",
    ),
    prior_review_path: Path = typer.Option(
        DEFAULT_SALVATION_COLLECTED_OBSERVATION_REVIEW_OUTPUT,
        "--prior-review",
        help="Reviewed current collected-observation packet.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_CONVERSION_RECALIBRATION_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        readiness = assess_topic_stage4_readiness(database, cohort)
        if not readiness["ready"]:
            _print_topic_stage4_readiness(readiness, base_dir=base_dir)
        prior_review = load_salvation_collected_observations_review(
            prior_review_path
        )
        packet = evaluate_salvation_conversion_recalibration(
            database,
            cohort,
            prior_review,
            readiness=readiness,
        )
        json_path, markdown_path, reused = (
            write_salvation_conversion_recalibration(output_path, packet)
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    fresh = sum(
        probe["probe_role"] == "fresh_cached_neighbor"
        for probe in packet["probes"]
    )
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation conversion recalibration: "
        f"{json_path} and {markdown_path}; "
        f"fresh_probes={fresh}; "
        f"watch_fixtures={len(packet['frozen_watch_fixtures'])}; "
        "provider_requests=0; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-final-collection-check",
    help="Build the provider-free final check for four localized leaf boundaries.",
)
def analysis_salvation_final_collection_check(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying ordinary classification artifacts.",
    ),
    prior_review_path: Path = typer.Option(
        DEFAULT_SALVATION_COLLECTED_OBSERVATION_REVIEW_OUTPUT,
        "--prior-review",
        help="Reviewed ordinary-classification boundary packet.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_FINAL_COLLECTION_CHECK_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        readiness = assess_topic_stage4_readiness(database, cohort)
        if not readiness["ready"]:
            _print_topic_stage4_readiness(readiness, base_dir=base_dir)
        prior_review = load_salvation_collected_observations_review(
            prior_review_path
        )
        packet = evaluate_salvation_final_collection_check(
            database,
            cohort,
            prior_review,
            readiness=readiness,
        )
        json_path, markdown_path, reused = write_salvation_final_collection_check(
            output_path,
            packet,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation final collection check: "
        f"{json_path} and {markdown_path}; "
        f"probes={len(packet['probes'])}; "
        f"cases={len(packet['cases'])}; "
        "provider_requests=0; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-collection-recalibration",
    help=(
        "Build a provider-free follow-up for the four unsettled salvation leaves."
    ),
)
def analysis_salvation_collection_recalibration(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying ordinary classification artifacts.",
    ),
    prior_review_path: Path = typer.Option(
        DEFAULT_SALVATION_COLLECTED_OBSERVATION_REVIEW_OUTPUT,
        "--prior-review",
        help="Reviewed ordinary-classification boundary packet.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_COLLECTION_RECALIBRATION_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        prior_review = load_salvation_collected_observations_review(
            prior_review_path
        )
        readiness = assess_topic_stage4_readiness(database, cohort)
        if not readiness["ready"]:
            _print_topic_stage4_readiness(readiness, base_dir=base_dir)
        packet = evaluate_salvation_collection_recalibration(
            database,
            cohort,
            prior_review,
            readiness=readiness,
        )
        json_path, markdown_path, reused = (
            write_salvation_collection_recalibration(output_path, packet)
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation collection recalibration: "
        f"{json_path} and {markdown_path}; "
        f"leaves={len(packet['current_thresholds'])}; "
        f"probes={len(packet['probes'])}; "
        f"provider_requests=0; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "salvation-boundary-recalibration",
    help=(
        "Build a provider-free focused review for four disputed salvation leaves."
    ),
)
def analysis_salvation_boundary_recalibration(
    cohort_path: Path = typer.Option(
        DEFAULT_TOPIC_STAGE4_COHORT,
        "--cohort",
        help="Ready frozen topic cohort supplying ordinary classification artifacts.",
    ),
    prior_review_path: Path = typer.Option(
        DEFAULT_SALVATION_COLLECTED_OBSERVATION_REVIEW_OUTPUT,
        "--prior-review",
        help="Reviewed ordinary-classification boundary packet.",
    ),
    output_path: Path = typer.Option(
        DEFAULT_SALVATION_BOUNDARY_RECALIBRATION_OUTPUT,
        "--output",
        help="Fingerprint-bound JSON packet path; Markdown is written beside it.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help="Application-data directory containing app.db; pass the directory, not the database file.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        cohort = load_topic_stage4_cohort(cohort_path)
        prior_review = load_salvation_collected_observations_review(
            prior_review_path
        )
        readiness = assess_topic_stage4_readiness(database, cohort)
        if not readiness["ready"]:
            _print_topic_stage4_readiness(readiness, base_dir=base_dir)
        packet = evaluate_salvation_boundary_recalibration(
            database,
            cohort,
            prior_review,
            readiness=readiness,
        )
        json_path, markdown_path, reused = write_salvation_boundary_recalibration(
            output_path,
            packet,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    fresh = sum(
        probe["probe_role"] == "fresh_probability_neighbor"
        for probe in packet["probes"]
    )
    console.print(
        f"{'Reused' if reused else 'Wrote'} salvation boundary recalibration: "
        f"{json_path} and {markdown_path}; "
        f"anchors={len(packet['reviewed_boundary_anchors'])}; "
        f"fresh={fresh}; "
        f"watch=1; provider_requests=0; "
        f"fingerprint={str(packet['input_fingerprint'])[:12]}…",
        markup=False,
    )


@analysis_app.command(
    "evaluate-topic-behavior",
    help="Run or validate the bounded synthetic TypeSafe topic behavior contract.",
)
def analysis_evaluate_topic_behavior(
    fixture_path: Path = typer.Option(
        DEFAULT_TOPIC_BEHAVIOR_FIXTURE,
        "--fixture",
        help="Frozen synthetic topic fixture JSON.",
    ),
    model: str = typer.Option(
        DEFAULT_TYPESAFE_MODEL,
        "--model",
        help="Pinned TypeSafe model id.",
    ),
    cache_dir: Path | None = typer.Option(
        None,
        "--cache-dir",
        help="Content-addressed answer cache; defaults beside the fixture.",
    ),
    output_path: Path | None = typer.Option(
        None,
        "--output",
        help="Result JSON path; Markdown is written beside it.",
    ),
    timeout_seconds: float = typer.Option(
        45.0,
        "--timeout-seconds",
        min=1.0,
        help="Provider timeout for an uncached request.",
    ),
    validate_only: bool = typer.Option(
        False,
        "--validate-only",
        help="Validate frozen coverage without calling TypeSafe or writing results.",
    ),
) -> None:
    try:
        fixture = load_topic_behavior_fixture(fixture_path)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--fixture") from error
    expectation_count = sum(
        len(case["expectations"]) for case in fixture["cases"]
    )
    if validate_only:
        console.print(
            "Topic behavior fixture valid: "
            f"cases={len(fixture['cases'])}, expectations={expectation_count}, "
            f"fingerprint={fixture['fixture_sha256'][:12]}…",
            markup=False,
        )
        return

    fixture_path = Path(fixture["fixture_path"])
    resolved_cache_dir = cache_dir or fixture_path.parent / "cache"
    client = _LazyTopicBehaviorClient(
        model=model,
        timeout_seconds=timeout_seconds,
    )
    try:
        report = evaluate_topic_behavior_fixture(
            fixture,
            cache_dir=resolved_cache_dir,
            model=model,
            client=client,
        )
        json_path, markdown_path, reused = write_topic_behavior_report(
            output_path or default_topic_behavior_output_path(fixture_path, model),
            report,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    state = "Reused" if reused else "Wrote"
    summary = report["summary"]
    execution = report["execution"]
    console.print(
        f"{state} topic behavior report: {json_path} and {markdown_path}; "
        f"status={report['status']}, cases={summary['passed_cases']}/"
        f"{summary['case_count']}, expectations={summary['passed_expectations']}/"
        f"{summary['expectation_count']}, cache_hits={execution['cache_hits']}, "
        f"cache_misses={execution['cache_misses']}, "
        f"provider_requests={execution['provider_requests']}",
        markup=False,
    )
    if report["status"] != "passed":
        raise typer.Exit(code=1)
    build_salvation_analytical_backfill_plan,
    load_salvation_candidate_discovery_audit,
    write_salvation_analytical_backfill_plan,


@analysis_app.command(
    "listener-directives-review",
    help="Record or reuse the approved listener-directive completion decision without inference.",
)
def analysis_listener_directives_review(
    output_path: Path = typer.Option(Path("evaluation/sermon-topics/listener-directive-stage-gate-v3.json"), "--output"),
) -> None:
    from pastor_transcript_extractor.sermon_listener_directive_review import (
        build_listener_completion, write_listener_completion,
    )
    try:
        decision = build_listener_completion()
        json_path, markdown_path, reused = write_listener_completion(output_path, decision)
    except (ValueError, OSError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"{'Reused' if reused else 'Wrote'} approved listener decision: "
                  f"{json_path} and {markdown_path}; provider_requests=0", markup=False)


@analysis_app.command(
    "public-life-treatment-review",
    help="Record or reuse approved public-life question readiness without inference.",
)
def analysis_public_life_treatment_review(
    output_path: Path = typer.Option(Path("evaluation/sermon-topics/public-life-treatment-stage-gate-v2.json"), "--output"),
) -> None:
    from pastor_transcript_extractor.sermon_public_life_review import build_public_completion, write_public_policy_report
    try:
        report = build_public_completion()
        json_path, markdown_path, reused = write_public_policy_report(output_path, report)
    except (ValueError, OSError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"{'Reused' if reused else 'Wrote'} public-life question decision: "
                  f"{json_path} and {markdown_path}; provider_requests=0", markup=False)


@analysis_app.command(
    "public-life-routing-review",
    help="Compare .55 and eligibility-only routing using saved V2 answers; no inference or database reads.",
)
def analysis_public_life_routing_review(
    output_path: Path = typer.Option(Path("evaluation/sermon-topics/public-life-routing-comparison-v2.json"), "--output"),
) -> None:
    from pastor_transcript_extractor.sermon_public_life_review import build_public_routing_comparison, write_public_policy_report
    try:
        report = build_public_routing_comparison()
        json_path, markdown_path, reused = write_public_policy_report(output_path, report)
    except (ValueError, OSError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"{'Reused' if reused else 'Wrote'} public-life routing comparison: "
                  f"{json_path} and {markdown_path}; provider_requests=0", markup=False)


@analysis_app.command(
    "source-material-review",
    help="Prepare or evaluate bounded source/material questions using independent cached answers.",
)
def analysis_source_material_review(
    output_path: Path = typer.Option(Path("evaluation/sermon-topics/source-material-review-v1.json"), "--output"),
    base_dir: Path | None = typer.Option(None, "--base-dir", help="Application-data directory containing app.db."),
    model: str = typer.Option(DEFAULT_TYPESAFE_MODEL, "--model"),
    timeout_seconds: float = typer.Option(45.0, "--timeout-seconds", min=1.0),
    prepare_only: bool = typer.Option(False, "--prepare-only", help="Write proposed cases without provider inference."),
) -> None:
    from pastor_transcript_extractor.sermon_leaf_packs import SOURCE_MATERIAL
    from pastor_transcript_extractor.sermon_listener_directive_review import evaluate_review, write_review
    from pastor_transcript_extractor.sermon_source_material_review import prepare_source_review

    try:
        database = Database(build_paths(base_dir).database, readonly=True)
        packet = prepare_source_review(database, model=model,
                                       probe_cache=output_path.parent / "source-material-probe-cache")
        execution = {"hits": 0, "misses": 0, "provider_requests": 0}
        if not prepare_only:
            packet, execution = evaluate_review(packet, pack=SOURCE_MATERIAL,
                client=_LazyTopicBehaviorClient(model=model, timeout_seconds=timeout_seconds))
        json_path, markdown_path, reused = write_review(output_path, packet,
                                                       title="Source/material bounded review V1")
    except (ValueError, OSError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"{'Reused' if reused else 'Wrote'} source/material review: "
                  f"{json_path} and {markdown_path}; cases={len(packet['cases'])}; "
                  f"cache_hits={execution['hits']}; cache_misses={execution['misses']}; "
                  f"provider_requests={execution['provider_requests']}", markup=False)


@analysis_app.command(
    "source-material-stage-gate",
    help="Record or reuse the accepted source/material V1 PASS from frozen evidence; no inference or database reads.",
)
def analysis_source_material_stage_gate(
    output_path: Path = typer.Option(Path("evaluation/sermon-topics/source-material-stage-gate-v1.json"), "--output"),
) -> None:
    from pastor_transcript_extractor.sermon_source_material_review import build_source_completion, write_source_completion

    try:
        report = build_source_completion()
        json_path, markdown_path, reused = write_source_completion(output_path, report)
    except (ValueError, OSError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"{'Reused' if reused else 'Wrote'} source/material PASS: "
                  f"{json_path} and {markdown_path}; provider_requests=0", markup=False)


@analysis_app.command(
    "g1-feasibility-review",
    help="Run the fixed bounded G1 proposition-binding pilot; no expansion, collection or pastor projection.",
)
def analysis_g1_feasibility_review(
    prepare_only: bool = typer.Option(False, "--prepare-only", help="Prepare the fixed source packet without provider calls."),
    check_only: bool = typer.Option(False, "--check-only", help="Check packet integrity without provider calls."),
    revision: str = typer.Option("v1", "--revision", help="Frozen G1 revision: v1 or the single focused v2 refinement."),
    replace_lost_response: bool = typer.Option(False, "--replace-lost-response", help="Approve one replacement for the recorded lost V2 response; cumulative ceiling 38, unchanged cases/questions."),
) -> None:
    if replace_lost_response and (revision != "v2" or prepare_only or check_only):
        raise typer.BadParameter("--replace-lost-response requires V2 evaluation")
    if revision == "v1":
        from pastor_transcript_extractor.sermon_g1_feasibility_review import run
    elif revision == "v2":
        from pastor_transcript_extractor.sermon_g1_feasibility_revision import run
    else:
        raise typer.BadParameter("--revision must be v1 or v2")

    if prepare_only and check_only:
        raise typer.BadParameter("Choose at most one of --prepare-only and --check-only")
    try:
        mode = "prepare" if prepare_only else "check" if check_only else "evaluate"
        if replace_lost_response:
            run(mode, replace_lost_response=True)
        else:
            run(mode)
    except (ValueError, OSError, RuntimeError) as error:
        raise typer.BadParameter(str(error)) from error


@analysis_app.command(
    "g2-feasibility-review",
    help="Run the fixed bounded G2 semantic-edge pilot; no broader collection or profile projection.",
)
def analysis_g2_feasibility_review(
    prepare_only: bool = typer.Option(False, "--prepare-only", help="Prepare fixed inputs without provider inference."),
    check_only: bool = typer.Option(False, "--check-only", help="Check local proposal integrity without provider inference."),
    revision: str = typer.Option("v1", "--revision", help="Frozen pilot revision: v1 or the single adjudicated v2 cycle."),
) -> None:
    if revision == "v1":
        from pastor_transcript_extractor.sermon_g2_feasibility_review import run
    elif revision == "v2":
        from pastor_transcript_extractor.sermon_g2_feasibility_revision import run
    else:
        raise typer.BadParameter("--revision must be v1 or v2")

    if prepare_only and check_only:
        raise typer.BadParameter("Choose at most one of --prepare-only and --check-only")
    try:
        run("prepare" if prepare_only else "check" if check_only else "evaluate")
    except (ValueError, OSError, RuntimeError) as error:
        raise typer.BadParameter(str(error)) from error


@analysis_app.command(
    "profile-evidence-check",
    help="Check the shared evidence/field review packet locally; no provider calls or profile projection.",
)
def analysis_profile_evidence_check() -> None:
    import subprocess
    import sys

    packet_dir = Path(__file__).resolve().parents[4] / "docs/review-proposals/profile-evidence-v1"
    checker = packet_dir / "check_packet.py"
    if not checker.is_file():
        raise typer.BadParameter("The profile evidence review packet requires the repository checkout.")
    result = subprocess.run(
        [sys.executable, str(checker)], capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise typer.BadParameter(result.stderr.strip() or result.stdout.strip() or "Packet integrity check failed.")
    console.print(result.stdout.strip(), markup=False)


@analysis_app.command(
    "observed-profile-review",
    help="Render and check the 17 supplied-passage consumer cases; no inference, collection or pastor projection.",
)
def analysis_observed_profile_review(
    case_id: str = typer.Option("A01", "--case", help="Case to preview in the terminal; all 17 are checked and included in the report."),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="Directory for the Markdown partial views and JSON acceptance results."),
    check_only: bool = typer.Option(False, "--check-only", help="Check consumer acceptance without writing reports."),
) -> None:
    from pastor_transcript_extractor.observed_profile_review import (
        DEFAULT_OUTPUT, build_review, console_preview, write_review,
    )

    try:
        report = build_review()
        preview = console_preview(report, case_id)
        console.print(
            f"Consumer invariants: {report['invariant_passes']}/{report['case_count']}; "
            f"exact frozen state/link matches: {report['exact_oracle_matches']}/{report['case_count']}; "
            "provider_requests=0", markup=False,
        )
        for case in report["cases"]:
            outcome = case["acceptance"]
            if outcome["oracle_differences"]:
                console.print(f"{case['case_id']}: frozen expectation differences: " + json.dumps(outcome["oracle_differences"]), markup=False)
        if report["invariant_passes"] != report["case_count"]:
            raise ValueError("Consumer contract invariants failed; no accepted profile report was written.")
        if not check_only:
            json_path, markdown_path = write_review(report, output_dir or DEFAULT_OUTPUT)
            console.print(f"Wrote {markdown_path} and {json_path}", markup=False)
            console.print(preview, markup=False)
        console.print("State/link differences remain disclosed for review. Prose usefulness requires human review; all collection/projection/scoring holds remain.", markup=False)
    except (ValueError, OSError, RuntimeError) as error:
        raise typer.BadParameter(str(error)) from error


@analysis_app.command(
    "g3-feasibility-review",
    help="Run the fixed bounded G3 address pilot; no collection, projection or scoring.",
)
def analysis_g3_feasibility_review(
    prepare_only: bool = typer.Option(False, "--prepare-only", help="Prepare fixed inputs without provider inference."),
    check_only: bool = typer.Option(False, "--check-only", help="Check proposal integrity without provider inference."),
    revision: str = typer.Option("v1", "--revision", help="Frozen G3 revision: v1 or the narrow binding revision v2."),
) -> None:
    if revision == "v1":
        from pastor_transcript_extractor.sermon_g3_feasibility_review import run
    elif revision == "v2":
        from pastor_transcript_extractor.sermon_g3_feasibility_revision import run
    else:
        raise typer.BadParameter("--revision must be v1 or v2")

    if prepare_only and check_only:
        raise typer.BadParameter("Choose at most one of --prepare-only and --check-only")
    try:
        run("prepare" if prepare_only else "check" if check_only else "evaluate")
    except (ValueError, OSError, RuntimeError) as error:
        raise typer.BadParameter(str(error)) from error
