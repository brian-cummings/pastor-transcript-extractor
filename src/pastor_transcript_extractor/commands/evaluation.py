from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from pastor_transcript_extractor.commands.apps import root_app
from pastor_transcript_extractor.commands.common import get_database
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.evaluation import (
    allocate_evaluation_run_directory,
    build_failure_analysis,
    build_failure_markdown,
    build_markdown_report,
    create_evaluation_run,
    evaluate_fixture_payload,
)
from pastor_transcript_extractor.evaluation_baseline import validate_localization_baseline
from pastor_transcript_extractor.evaluation_partitioning import (
    SourceFamilyRegistryError,
    assign_recording_partition,
    extend_source_family_registry,
    load_source_family_registry,
)
from pastor_transcript_extractor.fixture_validation import validate_fixture_directory
from pastor_transcript_extractor.ground_truth_review import write_json


console = Console()



@root_app.command(help="Validate manually reviewed sermon evaluation fixtures.")
def validate_fixtures(
    fixture_dir: Path = typer.Argument(
        Path("evaluation/fixtures"),
        help="Directory containing manually reviewed fixture JSON files.",
    ),
) -> None:
    fixtures = validate_fixture_directory(fixture_dir.expanduser().resolve())
    console.print(f"Validated {len(fixtures)} fixture(s); all video IDs are unique.")


@root_app.command(help="Validate a frozen sermon-localization baseline and its exact fixture corpus.")
def validate_baseline(
    manifest: Path = typer.Argument(
        Path("evaluation/baselines/sermon-localization-v1.json"),
        help="Frozen localization baseline manifest.",
    ),
    fixture_dir: Path = typer.Option(
        Path("evaluation/fixtures"),
        help="Directory containing the baseline fixture corpus.",
    ),
) -> None:
    baseline = validate_localization_baseline(
        manifest.expanduser().resolve(),
        fixture_dir.expanduser().resolve(),
    )
    console.print(
        f"Validated {baseline.baseline_id}: {baseline.fixture_count} fixture(s), "
        f"fingerprint={baseline.corpus_fingerprint}."
    )


@root_app.command(help="Validate source-family coverage and family-level evaluation partitions.")
def validate_source_families(
    registry_path: Path = typer.Argument(
        Path("evaluation/source-families.json"),
        help="Source-family registry JSON.",
    ),
    fixture_dir: Path = typer.Option(
        Path("evaluation/fixtures"),
        help="Fixture corpus whose source-family coverage should be checked.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        registry = load_source_family_registry(registry_path.expanduser().resolve())
        fixtures = validate_fixture_directory(fixture_dir.expanduser().resolve())
        paths = build_paths(base_dir)
        if not paths.database.exists():
            raise SourceFamilyRegistryError(
                f"application database does not exist: {paths.database}"
            )
        database = Database(paths.database, readonly=True)
        assignments = []
        for fixture in fixtures:
            video = database.get_video_by_youtube_id(fixture.video_id)
            if video is None:
                raise SourceFamilyRegistryError(f"fixture video is not in the database: {fixture.video_id}")
            source = database.get_source_by_id(video.source_id)
            if source is None:
                raise SourceFamilyRegistryError(f"video source is missing: {fixture.video_id}")
            transcript = database.get_latest_transcript_artifact_for_video(video.id)
            assignments.append(
                assign_recording_partition(
                    registry=registry,
                    video_id=fixture.video_id,
                    source_url=source.url,
                    caption_source=transcript.source_kind.value if transcript else "unknown",
                    recording_date=video.published_at,
                )
            )
    except (OSError, SourceFamilyRegistryError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error

    partition_counts: dict[str, int] = {}
    for assignment in assignments:
        partition_counts[assignment.partition.value] = (
            partition_counts.get(assignment.partition.value, 0) + 1
        )
    family_count = len({assignment.source_family_id for assignment in assignments})
    condition_count = len({assignment.recording_condition_group_id for assignment in assignments})
    counts = ", ".join(
        f"{partition}={count}" for partition, count in sorted(partition_counts.items())
    )
    console.print(
        f"Validated {len(assignments)} fixture(s) across {family_count} source families and "
        f"{condition_count} recording-condition groups; {counts}."
    )


@root_app.command(help="Deterministically register new database sources for evaluation partitioning.")
def sync_source_families(
    registry_path: Path = typer.Argument(
        Path("evaluation/source-families.json"),
        help="Source-family registry JSON to extend without changing existing assignments.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report additions without writing."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    path = registry_path.expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SourceFamilyRegistryError("source-family registry must be a JSON object")
        registry = load_source_family_registry(path)
        database = Database(build_paths(base_dir).database, readonly=True)
        extension = extend_source_family_registry(
            registry,
            payload,
            [(source.url, source.source_identity_key) for source in database.list_sources()],
        )
        if not dry_run and (extension.families_added or extension.aliases_added):
            write_json(path, extension.payload)
            load_source_family_registry(path)
    except (OSError, json.JSONDecodeError, SourceFamilyRegistryError) as error:
        raise typer.BadParameter(str(error)) from error
    action = "Would add" if dry_run else "Added"
    console.print(
        f"{action} {extension.families_added} source family(s) and "
        f"{extension.aliases_added} URL alias(es); "
        f"total={len(extension.payload['source_families'])}."
    )


@root_app.command(help="Evaluate existing production classification artifacts against frozen fixtures.")
def evaluate(
    fixture_dir: Path = typer.Option(Path("evaluation/fixtures"), help="Approved fixture directory."),
    results_dir: Path = typer.Option(Path("evaluation/results"), help="Generated result root."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    fixture_root = fixture_dir.expanduser().resolve()
    fixtures = validate_fixture_directory(fixture_root)
    results: list[dict[str, object]] = []
    failure_inputs: dict[str, tuple[dict[str, object], dict[str, object]]] = {}
    for validated in fixtures:
        fixture_path = validated.path
        fixture_payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        video = database.get_video_by_youtube_id(validated.video_id)
        if video is None:
            results.append(
                {
                    "video_id": validated.video_id,
                    "status": "video_not_in_database",
                    "fixture_path": str(fixture_path),
                }
            )
            continue
        extraction = database.get_latest_extraction_result_for_video(video.id)
        if extraction is None or not extraction.proposed_json_path:
            results.append(
                {
                    "video_id": validated.video_id,
                    "status": "missing_extraction_artifact",
                    "fixture_path": str(fixture_path),
                }
            )
            continue
        proposed_path = Path(extraction.proposed_json_path)
        try:
            proposed_payload = json.loads(proposed_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            results.append(
                {
                    "video_id": validated.video_id,
                    "status": "invalid_extraction_artifact",
                    "fixture_path": str(fixture_path),
                    "proposed_path": str(proposed_path),
                }
            )
            continue
        result = evaluate_fixture_payload(
            fixture_payload,
            proposed_payload,
            fixture_path=fixture_path,
            proposed_path=proposed_path,
        )
        results.append(result)
        if result.get("catastrophic_omission") or result.get("false_high_confidence_acceptance"):
            failure_inputs[validated.video_id] = (fixture_payload, proposed_payload)
    run = create_evaluation_run(results)
    output_dir = allocate_evaluation_run_directory(
        results_dir.expanduser().resolve(), run
    )
    json_path = output_dir / "results.json"
    markdown_path = output_dir / "report.md"
    json_path.write_text(json.dumps(run, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(build_markdown_report(run), encoding="utf-8")
    if failure_inputs:
        failure_dir = output_dir / "failures"
        failure_dir.mkdir()
        for video_id, (fixture_payload, proposed_payload) in failure_inputs.items():
            analysis = build_failure_analysis(fixture_payload, proposed_payload)
            (failure_dir / f"{video_id}.json").write_text(
                json.dumps(analysis, indent=2, sort_keys=True), encoding="utf-8"
            )
            (failure_dir / f"{video_id}.md").write_text(
                build_failure_markdown(analysis), encoding="utf-8"
            )
    aggregate = run["aggregate"]
    console.print(f"Wrote evaluation JSON to {json_path}")
    console.print(f"Wrote evaluation report to {markdown_path}")
    if failure_inputs:
        console.print(f"Wrote {len(failure_inputs)} failure analysis report(s) to {output_dir / 'failures'}")
    console.print(
        f"Evaluated {aggregate['evaluated_fixture_count']}/{aggregate['fixture_count']} fixture(s); "
        f"missing artifacts {aggregate['missing_artifact_count']}."
    )
