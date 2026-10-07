from __future__ import annotations

import json
from pathlib import Path

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
