from __future__ import annotations

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


console = Console()


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
