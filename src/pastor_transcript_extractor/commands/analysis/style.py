from __future__ import annotations

from dataclasses import replace
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
from pastor_transcript_extractor.config import build_llm_config
from pastor_transcript_extractor.ground_truth_review import format_timestamp
from pastor_transcript_extractor.local_llm import LocalLlmError, OllamaClient
from pastor_transcript_extractor.profile_analysis import resolve_profile_sermon_scope
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.style_analysis import (
    STYLE_ANALYZER_KEY,
    STYLE_ANALYZER_VERSION,
    STYLE_PROMPT_VERSION,
    analyze_sermon_style,
)
from pastor_transcript_extractor.style_evaluation import evaluate_style_model
from pastor_transcript_extractor.style_profile_analysis import (
    STYLE_PROFILE_ANALYZER_KEY,
    STYLE_PROFILE_ANALYZER_VERSION,
    build_profile_style_analysis,
)
from pastor_transcript_extractor.style_review import (
    create_style_review_packet,
    evaluate_style_boundaries,
    finalize_style_review,
)


console = Console()


@analysis_app.command(
    "style-run",
    help="Generate validated style support and candidate runs for a sermon or profile.",
)
def analysis_style_run(
    video_id: int | None = typer.Option(None, "--video-id", help="Database video id."),
    youtube_video_id: str | None = typer.Option(
        None, "--youtube-video-id", help="YouTube video id."
    ),
    profile_id: int | None = typer.Option(None, "--profile-id", help="Speaker profile id."),
    pastor: str | None = typer.Option(None, "--pastor", help="Compatibility profile alias."),
    model: str | None = typer.Option(None, "--model", help="Override configured Ollama model."),
    analyzer_version: str = typer.Option(
        STYLE_ANALYZER_VERSION, "--analyzer-version", help="Semantic analyzer version."
    ),
    prompt_version: str = typer.Option(
        STYLE_PROMPT_VERSION, "--prompt-version", help="Semantic prompt version."
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
    config = build_llm_config()
    if model is not None:
        config = replace(config, enabled=True, model=model)
    if not config.enabled:
        raise typer.BadParameter("Local LLM is disabled; enable it or pass --model.")
    client = OllamaClient(config)
    try:
        model_digest = client.model_digest()
    except LocalLlmError as error:
        raise typer.BadParameter(str(error)) from error
    if resolved_profile_id is not None:
        console.print(f"Speaker profile #{resolved_profile_id}: {len(videos)} sermon(s).")
    created = reused = skipped = 0
    for video in videos:
        try:
            outcome = analyze_sermon_style(
                database,
                video,
                client,
                model_digest=model_digest,
                context_size=config.context_size,
                analyzer_version=analyzer_version,
                prompt_version=prompt_version,
            )
        except (LocalLlmError, ValueError) as error:
            if len(videos) == 1:
                raise typer.BadParameter(str(error)) from error
            skipped += 1
            console.print(f"Skipped {video.youtube_video_id}: {error}", markup=False)
            continue
        created += int(outcome.created)
        reused += int(not outcome.created)
        console.print(
            f"{video.youtube_video_id}: style analysis #{outcome.run.id} "
            f"{'created' if outcome.created else 'reused'} "
            f"({outcome.run.analyzer_key}@{outcome.run.analyzer_version})"
        )
    console.print(
        f"Style analysis complete: created={created}, reused={reused}, skipped={skipped}."
    )


@analysis_app.command(
    "style-show", help="Inspect persisted semantic style evidence and measurements."
)
def analysis_style_show(
    video_id: int | None = typer.Option(None, "--video-id", help="Database video id."),
    youtube_video_id: str | None = typer.Option(
        None, "--youtube-video-id", help="YouTube video id."
    ),
    profile_id: int | None = typer.Option(None, "--profile-id", help="Speaker profile id."),
    pastor: str | None = typer.Option(None, "--pastor", help="Compatibility profile alias."),
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
    summary = Table(
        title=(
            f"Style Evidence — Speaker Profile #{resolved_profile_id}"
            if resolved_profile_id is not None
            else "Style Evidence"
        )
    )
    summary.add_column("Video")
    summary.add_column("Version")
    summary.add_column("Accepted evidence", justify="right")
    summary.add_column("Candidate runs", justify="right")
    summary.add_column("Analyzed", justify="right")
    found = []
    for video in videos:
        run = database.get_latest_sermon_analysis_run(video.id, STYLE_ANALYZER_KEY)
        if run is None:
            continue
        values = {
            item.metric_key: json.loads(item.value_json)
            for item in database.list_sermon_analysis_measurements(run.id)
        }
        summary.add_row(
            video.youtube_video_id,
            run.analyzer_version,
            str(values.get("semantic_evidence_count", 0)),
            str(values.get("candidate_style_run_count", 0)),
            f"{100 * float(values.get('semantic_analysis_coverage_fraction', 0)):.1f}%",
        )
        found.append((video, run, values))
    if not found:
        console.print("No style analysis found. Run 'pte analysis style-run' first.")
        return
    console.print(summary)
    if len(found) == 1:
        video, run, values = found[0]
        evidence_table = Table(title=f"Accepted Style Evidence — {video.youtube_video_id}")
        evidence_table.add_column("Dimension")
        evidence_table.add_column("Time")
        evidence_table.add_column("Scripture")
        evidence_table.add_column("Transcript evidence")
        for evidence in database.list_sermon_analysis_evidence(run.id):
            if evidence.evidence_kind != "semantic_style_evidence":
                continue
            payload = json.loads(evidence.payload_json)
            corroboration = payload.get("scripture_corroboration", [])
            references = sorted(
                {
                    str(item.get("canonical_reference"))
                    for item in corroboration
                    if isinstance(item, dict) and item.get("canonical_reference")
                }
            ) if isinstance(corroboration, list) else []
            evidence_table.add_row(
                str(payload.get("dimension", "—")),
                (
                    f"{format_timestamp(evidence.start_seconds)}–"
                    f"{format_timestamp(evidence.end_seconds)}"
                    if evidence.start_seconds is not None and evidence.end_seconds is not None
                    else "—"
                ),
                ", ".join(references) or "—",
                evidence.excerpt,
            )
        console.print(evidence_table)
        runs_table = Table(title=f"Candidate Representative Style Runs — {video.youtube_video_id}")
        runs_table.add_column("Dimension")
        runs_table.add_column("Time")
        runs_table.add_column("Boundary status")
        runs_table.add_column("Transcript run")
        for evidence in database.list_sermon_analysis_evidence(run.id):
            if evidence.evidence_kind != "semantic_style_run":
                continue
            payload = json.loads(evidence.payload_json)
            runs_table.add_row(
                str(payload.get("dimension", "—")),
                (
                    f"{format_timestamp(evidence.start_seconds)}–"
                    f"{format_timestamp(evidence.end_seconds)}"
                    if evidence.start_seconds is not None and evidence.end_seconds is not None
                    else "—"
                ),
                str(payload.get("boundary_status", "unreviewed")),
                evidence.excerpt,
            )
        console.print(runs_table)
        console.print(
            f"Provenance: run=#{run.id}; model="
            f"{json.dumps(values.get('model_provenance', {}), sort_keys=True)}; "
            f"prompt={json.dumps(values.get('prompt_provenance', {}), sort_keys=True)}"
        )


def _print_style_profile(database: Database, run) -> None:
    values = {
        item.metric_key: json.loads(item.value_json)
        for item in database.list_speaker_profile_analysis_measurements(run.id)
    }
    coverage = Table(title=f"Style Profile — Speaker Profile #{run.profile_id}")
    coverage.add_column("Coverage")
    coverage.add_column("Value", justify="right")
    coverage.add_row(
        "Sermons analyzed",
        f"{values.get('sermons_analyzed', 0)} / {values.get('sermons_attached', 0)}",
    )
    fraction = values.get("semantic_analysis_coverage_fraction")
    coverage.add_row(
        "Timestamped transcript analyzed",
        "insufficient coverage" if fraction is None else f"{100 * float(fraction):.1f}%",
    )
    console.print(coverage)
    styles = Table(title="Evidence-backed Style Dimensions")
    styles.add_column("Dimension")
    styles.add_column("Evidence", justify="right")
    styles.add_column("Sermons", justify="right")
    styles.add_column("Accepted evidence duration", justify="right")
    styles.add_column("Accepted evidence coverage", justify="right")
    styles.add_column("Candidate runs", justify="right")
    styles.add_column("Candidate run coverage", justify="right")
    dimensions = values.get("style_dimension_profiles", {})
    if isinstance(dimensions, dict):
        for dimension, metrics in dimensions.items():
            if not isinstance(metrics, dict):
                continue
            evidence_duration = metrics.get(
                "accepted_evidence_duration_seconds",
                metrics.get("duration_seconds", 0),
            )
            evidence_coverage = metrics.get(
                "accepted_evidence_coverage_fraction",
                metrics.get("duration_coverage_fraction"),
            )
            run_coverage = metrics.get("candidate_style_run_coverage_fraction")
            run_count = metrics.get("candidate_style_run_count")
            styles.add_row(
                str(dimension),
                str(metrics.get("evidence_count", 0)),
                f"{metrics.get('sermons_with_evidence', 0)}/{values.get('sermons_analyzed', 0)}",
                f"{float(evidence_duration):.1f}s",
                "—" if evidence_coverage is None else f"{100 * float(evidence_coverage):.1f}%",
                "—" if run_count is None else str(run_count),
                "—" if run_coverage is None else f"{100 * float(run_coverage):.1f}%*",
            )
    console.print(styles)
    console.print(
        "* Candidate run coverage uses unreviewed model boundaries; do not interpret it "
        "as representative profile coverage until boundary evaluation is complete."
    )
    console.print(
        f"Provenance: profile_analysis=#{run.id}; version={run.analyzer_version}; "
        f"membership={run.membership_fingerprint}; input={run.input_fingerprint}"
    )


@analysis_app.command(
    "style-summarize-profile",
    help="Materialize a profile summary from accepted sermon style evidence.",
)
def analysis_style_summarize_profile(
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    analyzer_version: str = typer.Option(
        STYLE_PROFILE_ANALYZER_VERSION,
        "--analyzer-version",
        help="Style profile analyzer version.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        outcome = build_profile_style_analysis(
            database, profile_id, analyzer_version=analyzer_version
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Style profile analysis #{outcome.run.id} "
        f"{'created' if outcome.created else 'reused'}."
    )
    _print_style_profile(database, outcome.run)


@analysis_app.command(
    "style-show-profile", help="Inspect the latest materialized style profile."
)
def analysis_style_show_profile(
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        scope = resolve_profile_sermon_scope(database, profile_id)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    run = database.get_latest_speaker_profile_analysis_run(
        scope.profile_id, STYLE_PROFILE_ANALYZER_KEY
    )
    if run is None:
        raise typer.BadParameter(
            "No materialized style profile. Run 'pte analysis style-summarize-profile' first."
        )
    _print_style_profile(database, run)


@analysis_app.command(
    "style-review-create",
    help="Create a full-sermon style-run adjudication packet.",
)
def analysis_style_review_create(
    youtube_video_id: str = typer.Option(
        ..., "--youtube-video-id", help="YouTube video id."
    ),
    output: Path = typer.Option(..., "--output", help="Review draft JSON path."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    video = database.get_video_by_youtube_id(youtube_video_id)
    if video is None:
        raise typer.BadParameter(f"Unknown YouTube video: {youtube_video_id}")
    try:
        payload = create_style_review_packet(database, video, output)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Created full-sermon style review draft with "
        f"{len(payload['segments'])} transcript segments and "
        f"{len(payload['candidate_style_runs'])} candidate runs: {output} "
        f"(inspection view: {output.with_suffix('.md')})"
    )


@analysis_app.command(
    "style-review-finalize",
    help="Validate an edited style review draft and mark it reviewed.",
)
def analysis_style_review_finalize(
    draft: Path = typer.Argument(..., help="Edited review draft JSON."),
    output: Path = typer.Option(..., "--output", help="Final reviewed JSON path."),
    reviewer: str = typer.Option(..., "--reviewer", help="Reviewer identity."),
) -> None:
    try:
        payload = finalize_style_review(draft, output, reviewer=reviewer)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Finalized style review with {len(payload['candidate_style_runs'])} "
        f"candidate adjudications and {len(payload['missed_style_runs'])} missed runs: "
        f"{output}"
    )


@analysis_app.command(
    "evaluate-style-boundaries",
    help="Evaluate run detection and boundaries from full-sermon reviewed packets.",
)
def analysis_evaluate_style_boundaries(
    reviews: list[Path] = typer.Argument(..., help="Reviewed style packet JSON files."),
) -> None:
    try:
        result = evaluate_style_boundaries(reviews)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    table = Table(title=f"Style Run Boundary Evaluation — {result.sermon_count} sermon(s)")
    table.add_column("Dimension")
    table.add_column("Run P", justify="right")
    table.add_column("Run R", justify="right")
    table.add_column("Reviewed duration recovered", justify="right")
    table.add_column("Accepted duration correct", justify="right")
    table.add_column("Duration IoU", justify="right")
    for label, metrics in (("overall", result.overall), *result.by_dimension.items()):
        table.add_row(
            label,
            f"{metrics.run_precision:.3f}",
            f"{metrics.run_recall:.3f}",
            f"{metrics.reviewed_duration_recall:.3f}",
            f"{metrics.accepted_duration_precision:.3f}",
            f"{metrics.duration_intersection_over_union:.3f}",
        )
    console.print(table)
    console.print(
        f"Judgments: {json.dumps(result.judgment_counts, sort_keys=True)}",
        markup=False,
    )
@analysis_app.command(
    "evaluate-style", help="Evaluate the configured semantic style model on reviewed cases."
)
def analysis_evaluate_style(
    fixture: Path = typer.Argument(
        Path("evaluation/sermon-style/reviewed-v2.json"), help="Reviewed style fixture."
    ),
    model: str | None = typer.Option(None, "--model", help="Override configured Ollama model."),
) -> None:
    config = build_llm_config()
    if model is not None:
        config = replace(config, enabled=True, model=model)
    client = OllamaClient(config)
    try:
        digest = client.model_digest()
        result = evaluate_style_model(fixture, client, model_digest=digest)
    except (LocalLlmError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    table = Table(title=f"Style Evaluation — {result.corpus_version}")
    table.add_column("Dimension")
    table.add_column("TP", justify="right")
    table.add_column("FP", justify="right")
    table.add_column("FN", justify="right")
    table.add_column("Precision", justify="right")
    table.add_column("Recall", justify="right")
    for label, metrics in (("overall", result.overall), *result.by_dimension.items()):
        table.add_row(
            label,
            str(metrics.true_positive),
            str(metrics.false_positive),
            str(metrics.false_negative),
            f"{metrics.precision:.3f}",
            f"{metrics.recall:.3f}",
        )
    console.print(table)
    console.print(
        f"Cases passed: {result.passed_case_count}/{result.case_count}; "
        f"negative controls passed: {result.overall.true_negative_cases}; "
        f"rejected proposals={result.rejected_proposal_count}; model={result.model}; "
        f"digest={result.model_digest}; prompt={result.prompt_version}."
    )
    for failure in result.failures:
        console.print(
            f"Miss: {failure['case_id']}; expected={failure['expected']}; "
            f"detected={failure['detected']}",
            markup=False,
        )
