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
    description: bool = typer.Option(False, "--description", help="Add a readable, claim-linked descriptive profile to --segment-view; no inference."),
    segment_view: bool = typer.Option(False, "--segment-view", help="Render the reviewed cached segment sample as a read-only profile view; no models or database writes."),
    segment_inventory: bool = typer.Option(False, "--segment-inventory", help="Inventory at most 12 current cached topic sources and render a bounded segment-backed sample; no inference or database writes."),
    segment_plan: bool = typer.Option(False, "--segment-plan", help="Verify the current segment-first plan and closed-experiment registry; no inference."),
    unit_span_check: bool = typer.Option(False, "--unit-span-check", help="Provider-free check of whole existing source-unit spans in the selected windows; no inference."),
    typesafe_selection: bool = typer.Option(False, "--typesafe-selection", help="Prepare/check the nomination-only packet; no inference unless separately authorized with --run-selection."),
    run_selection: bool = typer.Option(False, "--run-selection"),
    approve_input: str | None = typer.Option(None, "--approve-input"),
    typesafe_windows: bool = typer.Option(False, "--typesafe-windows", help="Prepare/check a no-call TypeSafe bridge and exact cache/usage plan for the selected windows."),
    reviewed_membership: bool = typer.Option(False, "--reviewed-membership", help="Use the explicit retired-fixture source-review membership overlay, never a production update."),
    prepare_handoff: bool = typer.Option(False, "--prepare-handoff", help="Materialize the fixed minute-block mapping/context fixtures; no model calls."),
    check_handoff: bool = typer.Option(False, "--check-handoff", help="Verify the provider-free minute-block preparation."),
    handoff_proposal: bool = typer.Option(False, "--handoff-proposal", help="Verify the minute-block evidence handoff proposal and probe supersession; no inference."),
    evidence_trace: bool = typer.Option(False, "--evidence-trace", help="Trace only the 24 existing evidence opportunities through persisted/reconstructed blocks; no inference."),
    check_only: bool = typer.Option(False, "--check-only", help="Verify a saved evidence trace without rebuilding it."),
    as_json: bool = typer.Option(False, "--json"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if description and not segment_view:
        raise typer.BadParameter("--description requires --segment-view")
    if segment_view:
        if any((segment_inventory, segment_plan, unit_span_check, typesafe_selection, run_selection, typesafe_windows, reviewed_membership, prepare_handoff, check_handoff, handoff_proposal, evidence_trace)) or approve_input is not None:
            raise typer.BadParameter("--segment-view is a separate read-only presentation mode")
        from pastor_transcript_extractor import segment_profile_view as view
        if description:
            from pastor_transcript_extractor import profile_description as view
        try:
            if check_only and description:
                result = view.load(base_dir)
                fingerprint = result["content_fingerprint"]
                path = None
            elif check_only:
                inventory, sources = view.load(base_dir)
                result = view.build_view(inventory, sources)
                fingerprint = result['content_fingerprint']
                path = None
            else:
                result, path = view.prepare(base_dir)
                fingerprint = result['description']['content_fingerprint'] if description else result['content_fingerprint']
        except (ValueError, OSError, KeyError, TypeError) as error:
            raise typer.BadParameter(str(error)) from error
        output = dict(status='READ_ONLY_PASTOR_PROFILE_DESCRIPTION' if description else 'READ_ONLY_EXISTING_SEGMENT_EVIDENCE_VIEW',fingerprint=fingerprint,provider_requests=0,database_writes=0,path=str(path) if path else None)
        if description:
            record = result if check_only else result['description']
            examples = record.get('supporting_examples', [])
            output.update(profile_version=record['version'],
                recording_ids=[source['video_id'] for source in record['source_identity']],
                reader_claims=len(record['reader']['claims']), consequential_gaps=len(record['gaps']),
                reused_raw_leaf_observations=len(record.get('evidence_supply', {}).get('supplied_observation_ids', [])),
                supporting_examples={state: sum(item['status'] == state for item in examples)
                    for state in ('selected', 'partial', 'unknown')},
                explanatory_points=len(record['reader'].get('explanatory_descriptions', {}).get('points', [])),
                withheld_descriptions=len(record['reader'].get('explanatory_descriptions', {}).get('withheld', [])),
                editorial_points=len(record['reader'].get('editorial_review', {}).get('applied_point_ids', [])),
                withheld_editorial_points=len(record['reader'].get('editorial_review', {}).get('withheld', [])),
                reader_acceptance='pending_concrete_wording_review',
                new_measurements=False, quote_execution=False)
        console.print_json(data=output) if as_json else console.print(output,markup=False)
        return
    if segment_inventory:
        if any((segment_plan, unit_span_check, typesafe_selection, run_selection, typesafe_windows, reviewed_membership, prepare_handoff, check_handoff, handoff_proposal, evidence_trace)) or approve_input is not None:
            raise typer.BadParameter("--segment-inventory is a separate provider-free mode")
        from pastor_transcript_extractor import segment_cache_inventory as inventory
        try:
            if check_only:
                result = inventory.build(base_dir)
                path = None
            else:
                result, path = inventory.prepare(base_dir)
        except (ValueError, OSError, KeyError, TypeError) as error:
            raise typer.BadParameter(str(error)) from error
        output = dict(status=result['status'], fingerprint=result['content_fingerprint'], selected_profile=result['selected_profile']['id'], coverage=result['coverage'], provider_requests=0, database_writes=0, path=str(path) if path else None)
        console.print_json(data=output) if as_json else console.print(output, markup=False)
        return
    if segment_plan:
        if any((unit_span_check, typesafe_selection, run_selection, typesafe_windows, reviewed_membership, prepare_handoff, check_handoff, handoff_proposal, evidence_trace, check_only)) or approve_input is not None:
            raise typer.BadParameter("--segment-plan is a separate read-only mode")
        from pastor_transcript_extractor.segment_evidence_plan import verify
        try:
            plan, path = verify()
        except (ValueError, OSError, KeyError) as error:
            raise typer.BadParameter(str(error)) from error
        output = dict(status=plan['status'], fingerprint=plan['content_fingerprint'], path=str(path), implementation_path=str(path.parent/Path(plan['implementation_path']).name), pipeline_order=plan['pipeline_order'], product_order=plan['product_order'], analytical_families=plan['analytical_families'], next_deliverables=plan['next_deliverables'], next_step=plan['next_step'], retired_paths=plan['retired_paths'], provider_requests=0)
        console.print_json(data=output) if as_json else console.print(output, markup=False)
        return
    if unit_span_check:
        if any((typesafe_selection, run_selection, typesafe_windows, reviewed_membership, prepare_handoff, check_handoff, handoff_proposal, evidence_trace, check_only)) or approve_input is not None:
            raise typer.BadParameter("--unit-span-check is a separate provider-free mode")
        from pastor_transcript_extractor.unit_span_readiness import prepare
        try:
            result, path = prepare(base_dir)
        except (ValueError, OSError, KeyError) as error:
            raise typer.BadParameter(str(error)) from error
        output = dict(status=result['status'], input_fingerprint=result['content_fingerprint'], counts=result['counts'], provider_requests=0, path=str(path))
        console.print_json(data=output) if as_json else console.print(output, markup=False)
        return
    if typesafe_selection:
        if any((typesafe_windows, reviewed_membership, prepare_handoff, check_handoff, handoff_proposal, evidence_trace)) or (run_selection and check_only) or (approve_input is not None and not run_selection):
            raise typer.BadParameter("Choose nomination preparation, --check-only, or --run-selection --approve-input")
        from pastor_transcript_extractor import typesafe_selection_packet as selection
        try:
            if run_selection:
                from pastor_transcript_extractor.typesafe_selection_execution import execute
                result, path = execute(approve_input, base_dir)
            else:
                if check_only and (selection.HERE/'execution-repair-v1.json').exists():
                    from pastor_transcript_extractor.typesafe_selection_resume import check_repair
                    result, path = check_repair(base_dir)
                else:
                    result, path = selection.verify(base_dir) if check_only else selection.prepare(base_dir)
        except (ValueError, OSError, KeyError, TypeError) as error:
            raise typer.BadParameter(str(error)) from error
        output = dict(status=result['status'], input_fingerprint=result.get('input_fingerprint', result['content_fingerprint']), provider_requests=result['provider_requests'], path=str(path))
        console.print_json(data=output) if as_json else console.print(output, markup=False)
        return
    if run_selection or approve_input is not None:
        raise typer.BadParameter("Execution options require --typesafe-selection")
    if typesafe_windows:
        if any((reviewed_membership, prepare_handoff, check_handoff, handoff_proposal, evidence_trace)):
            raise typer.BadParameter("TypeSafe window review is a separate provider-free mode")
        from pastor_transcript_extractor import typesafe_window_review as window_review
        try:
            if check_only:
                from pastor_transcript_extractor.typesafe_selection_packet import verify_bridge
                result, path = verify_bridge(base_dir)
            else:
                result, path = window_review.prepare(base_dir)
        except (ValueError, OSError, KeyError) as error:
            raise typer.BadParameter(str(error)) from error
        summary={"status":result['status'],"fingerprint":result['content_fingerprint'],"provider_requests":0,"usage_bounds":result['usage_bounds'],"report":str(path)}
        if as_json:
            console.print_json(data=summary)
        else:
            console.print(f"TypeSafe window bridge prepared; provider_requests=0; exact targets pending; fingerprint={result['content_fingerprint']}",markup=False)
            console.print(str(path),markup=False)
        return
    if reviewed_membership and not (prepare_handoff or check_handoff):
        raise typer.BadParameter("--reviewed-membership requires --prepare-handoff or --check-handoff")
    if prepare_handoff or check_handoff:
        if sum((prepare_handoff, check_handoff, handoff_proposal, evidence_trace)) != 1 or check_only:
            raise typer.BadParameter("Choose one handoff preparation/check mode")
        from pastor_transcript_extractor import minute_evidence_preparation as prep
        try:
            if reviewed_membership:
                from pastor_transcript_extractor import minute_evidence_membership as membership
                if prepare_handoff:
                    result, path = membership.prepare(base_dir)
                else:
                    from pastor_transcript_extractor.typesafe_window_review import selected_windows
                    result, path = selected_windows(base_dir)
            elif prepare_handoff:
                result, path = prep.prepare(base_dir)
            else:
                from pastor_transcript_extractor.minute_evidence_membership import verify_baseline
                result, path = verify_baseline(base_dir)
        except (ValueError, OSError, KeyError) as error:
            raise typer.BadParameter(str(error)) from error
        summary = {"status": result['status'], "fingerprint": result['content_fingerprint'], "counts": result['counts'], "provider_requests": 0, "report": str(path)}
        if as_json:
            console.print_json(data=summary)
        else:
            console.print(f"Minute handoff prepared; provider_requests=0; inference/measurement/admission disabled; fingerprint={result['content_fingerprint']}", markup=False)
            console.print(str(path), markup=False)
        return
    if handoff_proposal:
        if evidence_trace:
            raise typer.BadParameter("Choose handoff proposal or evidence trace")
        from pastor_transcript_extractor import minute_evidence_handoff as handoff
        try:
            from pastor_transcript_extractor.minute_evidence_preparation import verify_proposal
            result = verify_proposal()
        except (ValueError, OSError, KeyError) as error:
            raise typer.BadParameter(str(error)) from error
        if as_json:
            console.print_json(data={"status": result['status'], "fingerprint": result['content_fingerprint'], "provider_requests": 0})
        else:
            console.print(f"Minute-block handoff: IMPLEMENTATION_PROPOSAL_ONLY; probe superseded; provider_requests=0; fingerprint={result['content_fingerprint']}", markup=False)
            console.print(str(handoff.HERE/'PROPOSAL.md'), markup=False)
        return
    if evidence_trace:
        from pastor_transcript_extractor import evidence_pipeline_trace as trace
        try:
            if check_only:
                result, path = trace.verify(base_dir)
            else:
                result = trace.build(base_dir)
                path = trace.save_report(result, base_dir)
        except (ValueError, OSError, KeyError) as error:
            raise typer.BadParameter(str(error)) from error
        if as_json:
            console.print_json(data={"status": result["status"], "fingerprint": result["content_fingerprint"], "report": str(path), "adequate_footprint_diagnostics": result["adequate_footprint_diagnostics"]})
        else:
            console.print(f"24-case pipeline trace; provider_requests=0; no semantic/discovery credit; fingerprint={result['content_fingerprint']}", markup=False)
            console.print(str(path), markup=False)
        return
    if check_only:
        raise typer.BadParameter("--check-only requires --evidence-trace")
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


@analysis_app.command('profile-binding-review', help='Render the completed source-reviewed proposition-binding pilot on the three prepared passages; no providers or automatic binding.')
def analysis_profile_binding_review(
    check_only: bool = typer.Option(False, '--check-only', help='Verify current source identity and authored literal evidence without writing artifacts.'),
    as_json: bool = typer.Option(False, '--json'),
    base_dir: Path | None = typer.Option(None, help='Override app data directory.'),
) -> None:
    from pastor_transcript_extractor import profile_binding_pilot as pilot
    try:
        if check_only:
            report = pilot.load(base_dir)
            path = None
        else:
            report, path = pilot.prepare(base_dir)
    except (ValueError, OSError, KeyError, TypeError, StopIteration) as error:
        raise typer.BadParameter(str(error)) from error
    output = dict(status=report['status'], fingerprint=report['content_fingerprint'],
        passages=len(report['cases']), proposed_readings=sum(len(c['readings']) for c in report['cases']),
        verdict=report['conclusion']['verdict'], provider_requests=0, database_writes=0,
        path=str(path) if path else None)
    console.print_json(data=output) if as_json else console.print(output,markup=False)


@analysis_app.command('profile-synthesis', help='Prepare or review one local Ollama editorial synthesis of profile 318; no new measurements or comparisons.')
def analysis_profile_synthesis(
    prepare_only: bool = typer.Option(False, '--prepare', help='Inspect the bounded request without model probes, generation or writes.'),
    run_model: bool = typer.Option(False, '--run', help='Make at most one local synthesis request; cache reuse, no retries, pulls or fallback.'),
    check_only: bool = typer.Option(False, '--check-only', help='Verify cached raw response and source/request identity without network or writes.'),
    as_json: bool = typer.Option(False, '--json'),
    base_dir: Path | None = typer.Option(None, help='Override app data directory.'),
) -> None:
    if sum((prepare_only,run_model,check_only)) > 1:
        raise typer.BadParameter('--prepare, --run and --check-only are mutually exclusive')
    from pastor_transcript_extractor import profile_synthesis as synthesis
    try:
        if prepare_only:output = synthesis.prepare(base_dir)
        elif check_only:
            result,folder,_ = synthesis.cached(base_dir)
            output = dict(status=result['status'],fingerprint=result['content_fingerprint'],
                provider_requests=0,metadata_reads=0,writes=0,semantic_acceptance=False,path=str(folder))
        else:
            result,path,invocation = synthesis.report(base_dir,run_model=run_model)
            output = dict(status=result['status'],fingerprint=result['content_fingerprint'],
                provider_requests=invocation['provider_requests'],invocation=invocation,
                usage=result['generated']['usage'],semantic_acceptance=False,
                comparison_available=False,confidence_calibrated=False,
                new_measurements=False,quote_execution=False,path=str(path))
    except (ValueError,OSError,KeyError,TypeError,RuntimeError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print_json(data=output) if as_json else console.print(output,markup=False)


@analysis_app.command('profile-connected-binding', help='Extract connected propositions from only the same three supplied passages with the configured local Ollama backend.')
def analysis_profile_connected_binding(
    diagnostics_only: bool = typer.Option(False, '--diagnostics', help='Write exhaustive rejection diagnostics from cached raw responses; no generation or metadata probes.'),
    prepare_only: bool = typer.Option(False, '--prepare', help='Read-only source/request preflight; no Ollama probes, generation or writes.'),
    run_model: bool = typer.Option(False, '--run', help='Execute/resume at most one extraction per supplied passage; no retries or model downloads.'),
    check_only: bool = typer.Option(False, '--check-only', help='Reconstruct cached records and verify comparison without providers or writes.'),
    as_json: bool = typer.Option(False, '--json'),
    base_dir: Path | None = typer.Option(None, help='Override app data directory.'),
) -> None:
    from pastor_transcript_extractor import connected_binding_development as dev
    if sum((diagnostics_only,prepare_only,run_model,check_only))>1:raise typer.BadParameter('--diagnostics, --prepare, --run and --check-only are mutually exclusive')
    try:
        if diagnostics_only:
            from pastor_transcript_extractor import connected_binding_diagnostics as diagnostics
            result,path=diagnostics.prepare(base_dir)
            output=dict(status='CACHED_REJECTION_DIAGNOSTICS_COMPLETE',fingerprint=result['content_fingerprint'],summary=result['summary'],provider_requests=0,metadata_reads=0,path=str(path))
        elif prepare_only:output=dev.prepare(base_dir)
        elif check_only:
            result,folder,reference=dev.cached(base_dir)
            path=folder/'semantic-review-v1.json'
            if path.exists():dev.review.validate_comparison(dev.review.read(path),result,reference)
            output=dict(status='CONNECTED_RUN_COMPARED' if path.exists() else 'GENERATED_AWAITING_CODEX_SEMANTIC_COMPARISON',provider_requests=0,writes=0,generated_fingerprint=result['content_fingerprint'])
        else:
            result,path=dev.report(base_dir,run_model=run_model)
            output=dict(status=result['status'],fingerprint=result['content_fingerprint'],passages=3,generated_candidates=result['generated_candidates'],structurally_valid_candidates=result['structurally_valid_candidates'],passage_rejections=result['passage_rejections'],invocation=result['invocation'],usage=result['generated']['usage'],path=str(path))
            if result.get('comparison') and result['comparison'].get('raw_output_diagnostics'):
                raw=result['comparison']['raw_output_diagnostics']
                output.update(raw_model_propositions=raw['raw_propositions'],raw_model_frames=raw['raw_frames'])
    except (ValueError,OSError,KeyError,TypeError,RuntimeError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print_json(data=output) if as_json else console.print(output,markup=False)


@analysis_app.command('profile-proposition-review', help='Review the same ten source readings through reusable proposition bindings and unchanged assurance interpretation; no providers.')
def analysis_profile_proposition_review(
    check_only: bool = typer.Option(False, '--check-only', help='Verify exact source/evidence and unchanged G1 mapping without writing artifacts.'),
    as_json: bool = typer.Option(False, '--json'),
    base_dir: Path | None = typer.Option(None, help='Override app data directory.'),
) -> None:
    from pastor_transcript_extractor import profile_proposition_review as review
    try:
        if check_only:
            report = review.load(base_dir)
            path = None
        else:
            report, path = review.prepare(base_dir)
    except (ValueError, OSError, KeyError, TypeError, StopIteration) as error:
        raise typer.BadParameter(str(error)) from error
    output = dict(status=report['status'],fingerprint=report['content_fingerprint'],
        passages=len(report['cases']),proposed_readings=sum(len(c['readings']) for c in report['cases']),
        original_g1_records_unchanged=report['original_g1_records_unchanged'],
        provider_requests=0,database_writes=0,path=str(path) if path else None)
    console.print_json(data=output) if as_json else console.print(output,markup=False)


@analysis_app.command('profile-binding-development', help='Run/review automatic generic binding on only the three supplied development passages; references never enter model state.')
def analysis_profile_binding_development(
    prepare_only: bool = typer.Option(False, '--prepare', help='Read-only V2 source/request preflight; no provider calls or file writes.'),
    run_model: bool = typer.Option(False, '--run', help='Execute/resume the authorized bounded model run, reusing compatible request caches.'),
    check_only: bool = typer.Option(False, '--check-only', help='Verify current sources and cached results/comparison without providers or writes.'),
    as_json: bool = typer.Option(False, '--json'),
    base_dir: Path | None = typer.Option(None, help='Override app data directory.'),
) -> None:
    from pastor_transcript_extractor import profile_binding_development as dev
    if sum((prepare_only,run_model,check_only))>1:raise typer.BadParameter('--prepare, --run and --check-only are mutually exclusive')
    try:
        if prepare_only:
            output=dev.prepare(base_dir)
        elif check_only:
            result,folder,reviewed=dev.cached(base_dir)
            path=folder/'semantic-review-v1.json'
            comparison=dev.validate_comparison(dev.read(path),result,reviewed) if path.exists() else None
            output=dict(status='DEVELOPMENT_RUN_COMPARED' if comparison else 'GENERATED_AWAITING_CODEX_SEMANTIC_COMPARISON',
                generated_fingerprint=result['content_fingerprint'],passages=len(result['cases']),reviewed_readings=10,
                generated_candidates=sum(len(c['generated']) for c in result['cases']),provider_requests=0,writes=0,path=None)
        else:
            report,path=dev.report(base_dir,run_model=run_model)
            output=dict(status=report['status'],fingerprint=report['content_fingerprint'],passages=3,reviewed_readings=10,
                generated_candidates=report['generated_candidates'],structurally_valid_candidates=report['structurally_valid_candidates'],
                invocation=report['invocation'],usage=report['generated']['usage'],path=str(path))
    except (ValueError,OSError,KeyError,TypeError,StopIteration) as error:
        raise typer.BadParameter(str(error)) from error
    console.print_json(data=output) if as_json else console.print(output,markup=False)
