from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pastor_transcript_extractor.commands.analysis.content import (
    _analysis_videos,
    get_database,
)
from pastor_transcript_extractor.commands.apps import analysis_app
from pastor_transcript_extractor.ground_truth_review import format_timestamp
from pastor_transcript_extractor.profile_analysis import (
    PROFILE_ANALYZER_KEY,
    PROFILE_ANALYZER_VERSION,
    build_profile_scripture_analysis,
    resolve_profile_sermon_scope,
)
from pastor_transcript_extractor.scripture_alignment_evaluation import (
    evaluate_scripture_alignment,
)
from pastor_transcript_extractor.scripture_reference_evaluation import (
    evaluate_scripture_detector,
)
from pastor_transcript_extractor.sermon_analysis import (
    ANALYZER_KEY as SERMON_ANALYZER_KEY,
)
from pastor_transcript_extractor.storage import Database


console = Console()


@analysis_app.command("show", help="Inspect persisted sermon measurements and Scripture evidence.")
def analysis_show(
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
    title = (
        f"Sermon Analysis — Speaker Profile #{resolved_profile_id}"
        if resolved_profile_id is not None
        else "Sermon Analysis"
    )
    summary = Table(title=title)
    summary.add_column("Video")
    summary.add_column("Version")
    summary.add_column("Words", justify="right")
    summary.add_column("Duration", justify="right")
    summary.add_column("References", justify="right")
    summary.add_column("Text alignments", justify="right")
    summary.add_column("Books", justify="right")
    found: list[tuple[object, object]] = []
    for video in videos:
        run = database.get_latest_sermon_analysis_run(video.id, SERMON_ANALYZER_KEY)
        if run is None:
            continue
        values = {
            item.metric_key: json.loads(item.value_json)
            for item in database.list_sermon_analysis_measurements(run.id)
        }
        duration = values.get("sermon_duration_seconds")
        duration_text = (
            format_timestamp(float(duration)) if isinstance(duration, (int, float)) else "—"
        )
        summary.add_row(
            video.youtube_video_id,
            run.analyzer_version,
            str(values.get("word_count", "—")),
            duration_text,
            str(values.get("scripture_reference_mentions", "—")),
            str(values.get("scripture_text_alignment_count", "—")),
            str(values.get("distinct_scripture_books", "—")),
        )
        found.append((video, run))
    if not found:
        console.print("No sermon analysis results found. Run 'pte analysis run' first.")
        return
    console.print(summary)

    if len(found) == 1:
        video, run = found[0]
        references = Table(title=f"Scripture Evidence — {video.youtube_video_id}")
        references.add_column("Reference")
        references.add_column("Class")
        references.add_column("Confidence")
        references.add_column("Time")
        references.add_column("Segment", justify="right")
        references.add_column("Transcript match")
        alignment_sources: set[str] = set()
        for item in database.list_sermon_analysis_evidence(run.id):
            payload = json.loads(item.payload_json)
            bible_source = payload.get("bible_source")
            if isinstance(bible_source, dict):
                alignment_sources.add(
                    f"{bible_source.get('translation_name', 'unknown')} "
                    f"({bible_source.get('translation_version', 'unknown')}; "
                    f"{bible_source.get('artifact_version', 'unknown')})"
                )
            references.add_row(
                str(payload.get("canonical_reference", "—")),
                str(
                    payload.get("detection_class")
                    or payload.get("alignment_class", "—")
                ),
                str(
                    payload.get("detection_confidence")
                    or payload.get("alignment_score", "—")
                ),
                format_timestamp(item.start_seconds) if item.start_seconds is not None else "—",
                str(item.segment_index) if item.segment_index is not None else "—",
                item.excerpt,
            )
        console.print(references)
        for source in sorted(alignment_sources):
            console.print(f"Bible alignment source: {source}")
        console.print(
            f"Provenance: run=#{run.id}; extraction=#{run.extraction_result_id}; "
            f"source_sha256={run.source_content_sha256}; input={run.input_fingerprint}"
        )


def _profile_analysis_values(database: Database, run_id: int) -> dict[str, object]:
    return {
        item.metric_key: json.loads(item.value_json)
        for item in database.list_speaker_profile_analysis_measurements(run_id)
    }


def _print_profile_scripture_summary(database: Database, run) -> None:
    values = _profile_analysis_values(database, run.id)
    coverage = Table(title=f"Scripture Usage — Speaker Profile #{run.profile_id}")
    coverage.add_column("Coverage")
    coverage.add_column("Value", justify="right")
    attached = values.get("sermons_attached", 0)
    analyzed = values.get("sermons_analyzed", 0)
    date_start = values.get("date_range_start")
    date_end = values.get("date_range_end")
    date_range = f"{date_start or '—'} to {date_end or '—'}"
    coverage.add_row("Sermons analyzed", f"{analyzed} / {attached}")
    coverage.add_row("Total sermon words", f"{values.get('total_sermon_words', 0):,}")
    coverage.add_row("Date range", date_range)
    coverage.add_row("Detected references", str(values.get("reference_mentions", 0)))
    coverage.add_row(
        "Explicit references", str(values.get("explicit_reference_mentions", 0))
    )
    coverage.add_row(
        "Contextual references", str(values.get("contextual_reference_mentions", 0))
    )
    coverage.add_row(
        "Scripture text alignments", str(values.get("scripture_text_alignments", 0))
    )
    coverage.add_row(
        "Aligned transcript span words",
        str(values.get("scripture_aligned_transcript_span_words", 0)),
    )
    diagnostics = values.get("reference_detection_diagnostics", {})
    if isinstance(diagnostics, dict):
        coverage.add_row(
            "Zero-reference sermons",
            str(diagnostics.get("sermons_with_zero_detected_references", 0)),
        )
        coverage.add_row(
            "Detection scope", str(diagnostics.get("detection_scope", "—"))
        )
        coverage.add_row(
            "Confidence counts",
            json.dumps(diagnostics.get("detection_confidence_counts", {}), sort_keys=True),
        )
        coverage.add_row(
            "References with placement",
            f"{diagnostics.get('references_with_placement', 0)} / "
            f"{values.get('reference_mentions', 0)}",
        )
    console.print(coverage)

    usage = Table(title="Usage")
    usage.add_column("Measurement")
    usage.add_column("Value", justify="right")
    usage.add_row(
        "References / 1k words",
        str(values.get("references_per_1000_words", 0.0)),
    )
    usage.add_row(
        "Old Testament",
        f"{values.get('old_testament_mentions', 0)} "
        f"({values.get('old_testament_percent', 0.0)}%)",
    )
    usage.add_row(
        "New Testament",
        f"{values.get('new_testament_mentions', 0)} "
        f"({values.get('new_testament_percent', 0.0)}%)",
    )
    console.print(usage)

    books = Table(title="Top Books")
    books.add_column("Book")
    books.add_column("Mentions", justify="right")
    top_books = values.get("top_scripture_books", [])
    if isinstance(top_books, list):
        for item in top_books[:10]:
            if isinstance(item, dict):
                books.add_row(str(item.get("book", "—")), str(item.get("mentions", 0)))
    console.print(books)

    repeated = Table(title="Repeated Chapters")
    repeated.add_column("Passage")
    repeated.add_column("Sermons", justify="right")
    repeated.add_column("Mentions", justify="right")
    repeated_chapters = values.get("repeated_scripture_chapters", [])
    if isinstance(repeated_chapters, list):
        for item in repeated_chapters:
            if isinstance(item, dict):
                repeated.add_row(
                    str(item.get("passage", "—")),
                    str(item.get("sermon_count", 0)),
                    str(item.get("mentions", 0)),
                )
    console.print(repeated)

    placement = Table(title="Placement")
    placement.add_column("Quarter")
    placement.add_column("Mentions", justify="right")
    placement.add_column("Percent", justify="right")
    placement_values = values.get("reference_placement_by_quarter", {})
    if isinstance(placement_values, dict):
        for quarter in ("Q1", "Q2", "Q3", "Q4"):
            item = placement_values.get(quarter, {})
            if isinstance(item, dict):
                placement.add_row(
                    quarter,
                    str(item.get("mentions", 0)),
                    f"{item.get('percent', 0.0)}%",
                )
    console.print(placement)

    structural = Table(title="Structural Scripture Features")
    structural.add_column("Feature")
    structural.add_column("Value", justify="right")
    structural_values = values.get("structural_scripture_features", {})
    if isinstance(structural_values, dict):
        for feature in (
            "book_breadth_per_10_references",
            "chapter_breadth_per_10_references",
            "book_concentration_hhi",
            "effective_book_count",
            "sustained_chapter_reference_ratio",
            "multi_verse_reference_ratio",
            "cross_sermon_anchor_coverage",
            "mean_pairwise_book_distribution_cosine",
            "reference_density_consistency",
            "scripture_text_engagement_fraction",
            "sermons_with_text_alignment_fraction",
            "anchored_text_alignment_fraction",
            "mean_scripture_text_alignment_score",
            "aligned_passage_concentration_hhi",
        ):
            value = structural_values.get(feature)
            structural.add_row(
                "Detected Bible-text span fraction"
                if feature == "scripture_text_engagement_fraction" else feature,
                "insufficient coverage" if value is None else str(value),
            )
    console.print(structural)

    emphasis = Table(title="Canonical Emphasis")
    emphasis.add_column("Division")
    emphasis.add_column("Mentions", justify="right")
    emphasis.add_column("Share", justify="right")
    division_values = values.get("canonical_division_emphasis", {})
    if isinstance(division_values, dict):
        for division, item in division_values.items():
            if isinstance(item, dict):
                share = item.get("share")
                emphasis.add_row(
                    str(division),
                    str(item.get("mentions", 0)),
                    "insufficient coverage" if share is None else str(share),
                )
    console.print(emphasis)

    structural_coverage = values.get("structural_coverage_diagnostics", {})
    if isinstance(structural_coverage, dict):
        console.print(
            "Structural coverage: "
            f"reference-bearing sermons="
            f"{structural_coverage.get('sermons_with_detected_references', 0)}/"
            f"{structural_coverage.get('sermons_analyzed', 0)}; "
            f"book-distribution pairs="
            f"{structural_coverage.get('reference_bearing_sermon_pairs_compared', 0)}; "
            f"text-aligned sermons="
            f"{structural_coverage.get('sermons_with_scripture_text_alignments', 0)}/"
            f"{structural_coverage.get('sermons_analyzed', 0)}; "
            "null means insufficient evidence."
        )
    console.print(
        f"Provenance: profile_analysis=#{run.id}; version={run.analyzer_version}; "
        f"membership={run.membership_fingerprint}; input={run.input_fingerprint}"
    )


@analysis_app.command(
    "summarize-profile",
    help="Materialize a deterministic Scripture-usage summary for a speaker profile.",
)
def analysis_summarize_profile(
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    analyzer_version: str = typer.Option(
        PROFILE_ANALYZER_VERSION,
        "--analyzer-version",
        help="Profile analyzer version recorded in provenance.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        outcome = build_profile_scripture_analysis(
            database, profile_id, analyzer_version=analyzer_version
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Profile analysis #{outcome.run.id} "
        f"{'created' if outcome.created else 'reused'}."
    )
    _print_profile_scripture_summary(database, outcome.run)


@analysis_app.command(
    "show-profile",
    help="Inspect the latest materialized Scripture summary for a speaker profile.",
)
def analysis_show_profile(
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        scope = resolve_profile_sermon_scope(database, profile_id)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    run = database.get_latest_speaker_profile_analysis_run(
        scope.profile_id, PROFILE_ANALYZER_KEY
    )
    if run is None:
        raise typer.BadParameter(
            f"Speaker profile {scope.profile_id} has no materialized profile analysis. "
            "Run 'pte analysis summarize-profile' first."
        )
    _print_profile_scripture_summary(database, run)


@analysis_app.command(
    "evaluate-scripture-detector",
    help="Evaluate explicit and contextual detection against the reviewed fixture.",
)
def analysis_evaluate_scripture_detector(
    fixture: Path = typer.Argument(
        Path("evaluation/scripture-references/contextual-v1.json"),
        help="Reviewed Scripture-reference evaluation fixture.",
    ),
) -> None:
    try:
        result = evaluate_scripture_detector(fixture)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    table = Table(title=f"Scripture Detector Evaluation — {result.corpus_version}")
    table.add_column("Class")
    table.add_column("TP", justify="right")
    table.add_column("FP", justify="right")
    table.add_column("FN", justify="right")
    table.add_column("Precision", justify="right")
    table.add_column("Recall", justify="right")
    for label, metrics in (("overall", result.overall), *result.by_class.items()):
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
        f"methods={json.dumps(result.method_detection_counts, sort_keys=True)}"
    )
    for failure in result.failures:
        console.print(
            f"Miss: {failure['case_id']}; expected={failure['expected']}; "
            f"detected={failure['detected']}",
            markup=False,
        )
@analysis_app.command(
    "evaluate-scripture-alignment",
    help="Evaluate conservative Bible-text alignment against the reviewed fixture.",
)
def analysis_evaluate_scripture_alignment(
    fixture: Path = typer.Argument(
        Path("evaluation/scripture-alignments/reviewed-v1.json"),
        help="Reviewed Scripture-text alignment evaluation fixture.",
    ),
) -> None:
    try:
        result = evaluate_scripture_alignment(fixture)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    table = Table(title=f"Scripture Alignment Evaluation — {result.corpus_version}")
    table.add_column("Class")
    table.add_column("TP", justify="right")
    table.add_column("FP", justify="right")
    table.add_column("FN", justify="right")
    table.add_column("Precision", justify="right")
    table.add_column("Recall", justify="right")
    for label, metrics in (("overall", result.overall), *result.by_class.items()):
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
        f"Bible source={result.bible_source['translation_name']} "
        f"({result.bible_source['translation_version']}, "
        f"{result.bible_source['artifact_version']})."
    )
    for failure in result.failures:
        console.print(
            f"Miss: {failure['case_id']}; expected={failure['expected']}; "
            f"detected={failure['detected']}",
            markup=False,
        )
