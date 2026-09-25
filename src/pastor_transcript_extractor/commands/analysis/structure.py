from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pastor_transcript_extractor.commands.analysis.common import (
    _analysis_videos,
    get_database,
)
from pastor_transcript_extractor.commands.apps import analysis_app
from pastor_transcript_extractor.structure_analysis import (
    FEATURE_EXPLANATIONS as STRUCTURE_FEATURE_EXPLANATIONS,
    FEATURE_NAMES as STRUCTURE_FEATURE_NAMES,
    PROFILE_STRUCTURE_ANALYZER_KEY,
    PROFILE_STRUCTURE_ANALYZER_VERSION,
    STRUCTURE_ANALYZER_KEY,
    STRUCTURE_ANALYZER_VERSION,
    analyze_sermon_structure,
    build_profile_structure_analysis,
)
from pastor_transcript_extractor.structure_population_analysis import (
    build_structure_population_snapshot,
    load_structure_population_snapshot,
)
from pastor_transcript_extractor.structure_readiness import (
    build_structure_readiness,
    run_structure_backfill,
)


console = Console()


@analysis_app.command(
    "structure-run",
    help="Measure deterministic transcript stylometry and sermon organization.",
)
def analysis_structure_run(
    video_id: int | None = typer.Option(None, "--video-id"),
    youtube_video_id: str | None = typer.Option(None, "--youtube-video-id"),
    profile_id: int | None = typer.Option(None, "--profile-id"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    videos, resolved_profile_id = _analysis_videos(
        database,
        video_id=video_id,
        youtube_video_id=youtube_video_id,
        profile_id=profile_id,
        pastor_slug=None,
    )
    created = reused = skipped = 0
    for video in videos:
        try:
            outcome = analyze_sermon_structure(database, video)
        except ValueError as error:
            if len(videos) == 1:
                raise typer.BadParameter(str(error)) from error
            skipped += 1
            console.print(f"Skipped {video.youtube_video_id}: {error}", markup=False)
            continue
        created += int(outcome.created)
        reused += int(not outcome.created)
        console.print(
            f"{video.youtube_video_id}: structure analysis #{outcome.run.id} "
            f"{'created' if outcome.created else 'reused'}"
        )
    if resolved_profile_id is not None:
        profile = build_profile_structure_analysis(database, resolved_profile_id)
        console.print(
            f"Profile structure analysis #{profile.run.id} "
            f"{'created' if profile.created else 'reused'}."
        )
    console.print(
        f"Structure analysis complete: created={created}, reused={reused}, skipped={skipped}."
    )


@analysis_app.command("structure-show", help="Inspect deterministic structure measurements.")
def analysis_structure_show(
    youtube_video_id: str | None = typer.Option(None, "--youtube-video-id"),
    profile_id: int | None = typer.Option(None, "--profile-id"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if (youtube_video_id is None) == (profile_id is None):
        raise typer.BadParameter("Choose exactly one of --youtube-video-id or --profile-id")
    database = get_database(base_dir)
    if profile_id is not None:
        resolved = database.resolve_speaker_profile_id(profile_id)
        run = database.get_compatible_speaker_profile_analysis_run(
            resolved,
            PROFILE_STRUCTURE_ANALYZER_KEY,
            PROFILE_STRUCTURE_ANALYZER_VERSION,
        )
        if run is None:
            raise typer.BadParameter("No profile structure analysis; run structure-run first")
        values = {
            item.metric_key: json.loads(item.value_json)
            for item in database.list_speaker_profile_analysis_measurements(run.id)
        }
        summaries = values["feature_summaries"]
        console.print(
            f"Profile #{resolved}: structure analysis #{run.id}; "
            f"sermons={values['sermons_analyzed']}/{values['sermons_attached']}"
        )
        table = Table(title="Deterministic Sermon Structure Profile")
        table.add_column("Feature")
        table.add_column("Mean", justify="right")
        table.add_column("Median", justify="right")
        table.add_column("SD", justify="right")
        table.add_column("Observed", justify="right")
        for name in STRUCTURE_FEATURE_NAMES:
            item = summaries[name]
            table.add_row(
                name,
                "—" if item["mean"] is None else f"{item['mean']:.4f}",
                "—" if item["median"] is None else f"{item['median']:.4f}",
                "—" if item["standard_deviation"] is None else f"{item['standard_deviation']:.4f}",
                str(item["observed_sermons"]),
            )
        console.print(table)
        return
    video = database.get_video_by_youtube_id(str(youtube_video_id))
    if video is None:
        raise typer.BadParameter(f"Unknown YouTube video: {youtube_video_id}")
    run = database.get_latest_sermon_analysis_run(
        video.id, STRUCTURE_ANALYZER_KEY, STRUCTURE_ANALYZER_VERSION
    )
    if run is None:
        raise typer.BadParameter("No sermon structure analysis; run structure-run first")
    values = {
        item.metric_key: json.loads(item.value_json)
        for item in database.list_sermon_analysis_measurements(run.id)
    }
    vector = values["feature_vector"]["by_name"]
    table = Table(title=f"Deterministic Sermon Structure — {youtube_video_id}")
    table.add_column("Feature")
    table.add_column("Value", justify="right")
    table.add_column("Operational meaning")
    for name in STRUCTURE_FEATURE_NAMES:
        value = vector[name]
        table.add_row(
            name,
            "—" if value is None else f"{value:.4f}",
            STRUCTURE_FEATURE_EXPLANATIONS[name],
        )
    console.print(table)
    console.print(
        f"Provenance: structure_run=#{run.id}; source={run.source_content_sha256}; "
        f"scripture_run={values['source_diagnostics']['scripture_analysis_run_id']}"
    )


def _print_structure_readiness(report: object) -> None:
    table = Table(title="Deterministic Structure Analysis Readiness")
    for heading in ("Profile", "Sermons", "Current", "Missing", "Stale", "Blocked", "Aggregate"):
        table.add_column(heading, justify="right" if heading not in {"Profile", "Aggregate"} else "left")
    for item in report.profiles:
        table.add_row(
            f"#{item.profile_id} {item.display_label or ''}".rstrip(),
            str(item.sermon_count), str(item.current_sermons), str(item.missing_sermons),
            str(item.stale_sermons), str(item.blocked_sermons), item.aggregate_state,
        )
    console.print(table)
    totals = report.totals
    console.print(
        f"Profiles={totals['profiles']}; attached sermon instances={totals['sermons']}; "
        f"current={totals['current']}; missing={totals['missing']}; "
        f"stale={totals['stale']}; blocked={totals['blocked']}; "
        f"current aggregates={totals['current_aggregates']}."
    )


@analysis_app.command("structure-readiness", help="Report structure analysis readiness.")
def analysis_structure_readiness(
    as_json: bool = typer.Option(False, "--json"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    report = build_structure_readiness(get_database(base_dir))
    if as_json:
        console.print_json(data=report.payload())
    else:
        _print_structure_readiness(report)


@analysis_app.command(
    "structure-backfill",
    help="Safely backfill current deterministic structure runs and profile summaries.",
)
def analysis_structure_backfill(
    minimum_sermons: int = typer.Option(3, "--minimum-sermons", min=1),
    dry_run: bool = typer.Option(False, "--dry-run"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    result = run_structure_backfill(
        get_database(base_dir), dry_run=dry_run, minimum_sermons=minimum_sermons
    )
    if dry_run:
        target_ids = {
            state["video_id"]
            for profile in result.before.profiles
            if profile.sermon_count >= minimum_sermons
            for state in profile.sermon_states
            if state["state"] in {"missing", "stale"}
        }
        console.print(
            f"Dry run: {len(target_ids)} unique sermon(s) need structure analysis; "
            f"{sum(profile.sermon_count >= minimum_sermons and profile.aggregate_state != 'current' for profile in result.before.profiles)} "
            "profile aggregate(s) need refresh."
        )
        _print_structure_readiness(result.before)
        return
    for video_id, error in result.sermon_failures:
        console.print(f"Failed sermon video #{video_id}: {error}", markup=False)
    for profile_id, error in result.profile_failures:
        console.print(f"Failed profile #{profile_id}: {error}", markup=False)
    console.print(
        f"Structure backfill complete: sermon created={result.created_sermon_runs}, "
        f"reused={result.reused_sermon_runs}, failed={len(result.sermon_failures)}; "
        f"profile created={result.created_profile_runs}, "
        f"reused={result.reused_profile_runs}, failed={len(result.profile_failures)}."
    )
    assert result.after is not None
    _print_structure_readiness(result.after)


def _print_structure_population(snapshot: object, report: dict[str, object]) -> None:
    population = report["population"]
    console.print(
        f"Structure population snapshot #{snapshot.id}: profiles={population['profile_count']}, "
        f"sermons={population['sermon_count']}, fingerprint={snapshot.input_fingerprint[:12]}…"
    )
    table = Table(title="Preliminary Structure Feature Diagnostics")
    for heading in ("Feature", "N", "Missing", "LOO", "Between/within", "Size r", "Recommendation"):
        table.add_column(heading, justify="right" if heading in {"N", "Missing", "Between/within", "Size r"} else "left")
    for name in report["feature_names"]:
        item = report["feature_diagnostics"][name]
        distribution = item["distribution"]
        ratio = item["between_to_within_variance_ratio"]
        size = item["corpus_size_pearson"]
        table.add_row(
            name, str(distribution["observed_count"]), str(distribution["missing_count"]),
            item["leave_one_out"]["stability"], "—" if ratio is None else f"{ratio:.2f}",
            "—" if size is None else f"{size:.2f}", item["recommendation"],
        )
    console.print(table)
    metadata = report["metadata_coverage"]
    console.print(
        f"Strong correlations: {len(report['strong_correlations'])}. "
        f"Dated sermons={metadata['dated_sermons']}/{metadata['total_sermons']}; "
        f"multi-source profiles={metadata['multi_source_profiles']}. "
        "Advisory only; no comparison schema, PCA, ranking, or clustering changed."
    )


@analysis_app.command("structure-population-build", help="Freeze structure population diagnostics.")
def analysis_structure_population_build(
    minimum_sermons: int = typer.Option(3, "--minimum-sermons", min=2),
    as_json: bool = typer.Option(False, "--json"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        outcome = build_structure_population_snapshot(
            get_database(base_dir), minimum_sermons=minimum_sermons
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    if as_json:
        console.print_json(data={"snapshot_id": outcome.snapshot.id, "created": outcome.created, "report": outcome.report})
    else:
        console.print("Created." if outcome.created else "Reused unchanged snapshot.")
        _print_structure_population(outcome.snapshot, outcome.report)


@analysis_app.command("structure-population-show", help="Inspect a structure population snapshot.")
def analysis_structure_population_show(
    snapshot_id: int | None = typer.Option(None, "--snapshot-id"),
    as_json: bool = typer.Option(False, "--json"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        snapshot, report = load_structure_population_snapshot(
            get_database(base_dir), snapshot_id
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    if as_json:
        console.print_json(data={"snapshot_id": snapshot.id, "report": report})
    else:
        _print_structure_population(snapshot, report)
