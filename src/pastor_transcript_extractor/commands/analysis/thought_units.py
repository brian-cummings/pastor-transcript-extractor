"""Thought-unit experiment CLI: wording probe, Jev boundaries and units, and the boundary gate (docs/THOUGHT_UNIT_EXPERIMENT.md)."""
from pathlib import Path
import json

import typer
from httpx import HTTPError

from ..apps import analysis_app

app = typer.Typer(help='Run the thought-unit experiment: Jev-defined thought units against time blocks, with frozen gates.')
analysis_app.add_typer(app, name='thought-units')
ERRORS = (ValueError, OSError, KeyError, TypeError, StopIteration, HTTPError, RuntimeError, IndexError)
BASE = typer.Option(..., '--base-dir', help='Application base directory.')


def _echo(value) -> None:
    typer.echo(json.dumps(value, indent=2, ensure_ascii=False))


@app.command('probe-pairs')
def probe_pairs(base_dir: Path = BASE):
    """Write the 40 stage 0 probe pairs from a sermon other than 281 (fixed seed); no provider call."""
    from ...thought_units import stage
    try:
        _echo(stage.probe_pairs(base_dir))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('probe')
def probe(base_dir: Path = BASE,
          check_only: bool = typer.Option(False, '--check-only', help='Report questions, requests and estimated cost; sends nothing.')):
    """Stage 0: compare the candidate question wordings on the probe pairs (Jev); scores them when development labels exist."""
    from ...thought_units import stage
    try:
        _echo(stage.probe(base_dir, check_only=check_only))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('segment')
def segment(base_dir: Path = BASE, video: int = typer.Option(..., '--video', help='Video id of the sermon in the pilot leaf table.'),
            check_only: bool = typer.Option(False, '--check-only', help='Report candidates, questions and estimated cost; sends nothing.')):
    """Stage 1: ask Jev the frozen boundary questions and build thought units; no second wording round and no re-run."""
    from ...thought_units import stage
    try:
        _echo(stage.segment(base_dir, video, check_only=check_only))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('review-boundaries')
def review_boundaries(base_dir: Path = BASE):
    """G1: judge the sampled boundaries, non-boundaries and asides (resumable), then write the gate report."""
    from ...thought_units import stage
    try:
        _, _, out = stage.paths(base_dir)
        if not (out / 'g1_sample.json').exists():
            _echo(stage.g1_sample(base_dir))
        stage.judge(out, input, typer.echo)
        _echo(stage.g1_report(out))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error
