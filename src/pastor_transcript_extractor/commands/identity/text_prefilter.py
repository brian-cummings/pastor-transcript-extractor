"""`pte identity text-prefilter-check`: free registry-scale recall check for the text pre-filter."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from pastor_transcript_extractor.commands.apps import identity_app


@identity_app.command(
    "text-prefilter-check",
    help=(
        "Measure, at registry scale, how often each voice- or review-assigned profile falls in the "
        "stylometric text top N, and how many cross-source profile comparisons text would prune. "
        "Free: no voice, model or provider call. Writes REPORT.md and report.json under "
        "<base>/evaluation/identity-text-prefilter-v1/."
    ),
)
def text_prefilter_check_command(
    top: list[int] = typer.Option(
        [3, 5, 10], "--top", min=1,
        help="Top-N cutoffs to measure; repeatable. N = 5 (the acceptance cutoff) is always included.",
    ),
    association_root: Path | None = typer.Option(
        None, help="Shadow-association reports checked for text pre-filter use (circularity rule).",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    from pastor_transcript_extractor import identity_text_prefilter_check as check

    try:
        result = check.run(base_dir, top, association_root=association_root, echo=typer.echo)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(json.dumps(result, indent=2))
