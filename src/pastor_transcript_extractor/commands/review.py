from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import typer
from rich.console import Console

from pastor_transcript_extractor import application, config
from pastor_transcript_extractor.commands import common as command_common
from pastor_transcript_extractor.commands.apps import root_app
from pastor_transcript_extractor.config import build_pastor_paths
from pastor_transcript_extractor.inference_defaults import (
    DEFAULT_CLASSIFIER,
    DEFAULT_RECORDING_VERIFIER_BACKEND,
)


console = Console()


@root_app.command(
    help="Build or refresh the pastor-scoped Markdown review file from extracted videos.",
    rich_help_panel="Workflows",
)
def review(
    pastor: str | None = typer.Argument(
        None,
        help="Pastor slug whose extracted videos should be assembled into review Markdown.",
    ),
    all_pastors: bool = typer.Option(
        False,
        "--all",
        help="Build a combined review across all pastors.",
    ),
    edit: bool = typer.Option(
        False,
        "--edit",
        help="Open the generated review Markdown in an editor.",
    ),
    classifier: str = typer.Option(
        DEFAULT_CLASSIFIER,
        "--classifier",
        help="Content classifier for missing extractions: auto, rules, llm, or typesafe.",
    ),
    llm_model: str | None = typer.Option(
        None,
        "--llm-model",
        help="Override the configured local Ollama model.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    database = command_common.get_database(base_dir)
    paths = config.build_paths(base_dir, remember=True)
    if all_pastors and pastor is not None:
        raise typer.BadParameter("Do not pass a pastor slug when using --all.")
    if not all_pastors and pastor is None:
        raise typer.BadParameter("A pastor slug is required unless you use --all.")

    if pastor is not None and database.get_pastor_by_slug(pastor) is None:
        raise command_common.unknown_pastor_error(pastor, base_dir)
    try:
        batch = application.prepare_review_exports(
            database,
            paths,
            pastor_slug=pastor,
            all_pastors=all_pastors,
            classifier=classifier,
            llm_model=llm_model,
            recording_verifier_backend=DEFAULT_RECORDING_VERIFIER_BACKEND,
            event_callback=lambda message: console.print(message, markup=False),
            progress_callback=lambda stage, current, total: console.print(
                f"  {stage} block {current}/{total}"
            ),
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    for pastor_result in batch.pastors:
        result = pastor_result.export
        console.print(f"Wrote pastor review markdown to {result.export_path}")
        console.print(f"Wrote review manifest to {result.manifest_path}")
        console.print(
            f"Included {result.video_count} video(s); skipped {result.skipped_count}."
        )
    if batch.prepared or batch.failed:
        console.print(
            f"Prepared {batch.prepared} video(s) for review; failed {batch.failed}."
        )
    if all_pastors:
        console.print(
            f"Built review artifacts for {len(batch.pastors)} pastor(s); "
            f"included {sum(item.export.video_count for item in batch.pastors)} video(s); "
            f"skipped {sum(item.export.skipped_count for item in batch.pastors)}."
        )

    if edit:
        assert pastor is not None
        review_path = build_pastor_paths(paths, pastor).exports / "review.md"
        editor = shutil.which("code") or shutil.which("nano") or shutil.which("vim")
        if editor is None:
            raise RuntimeError("No editor found on PATH")
        subprocess.run([editor, str(review_path)], check=True)
