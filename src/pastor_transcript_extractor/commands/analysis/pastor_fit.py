"""Pastor fit experiment CLI (docs/PASTOR_FIT_EXPERIMENT.md): local text fingerprints, no provider calls."""
from pathlib import Path
import json

import typer

from ..apps import analysis_app

app = typer.Typer(help='Run the pastor fit experiment: can local text fingerprints tell pastors apart and find who fits a church?')
analysis_app.add_typer(app, name='pastor-fit')
ERRORS = (ValueError, OSError, KeyError, TypeError, RuntimeError)
BASE = typer.Option(..., '--base-dir', help='Application base directory.')


def _echo(value) -> None:
    typer.echo(json.dumps(value, indent=2, ensure_ascii=False))


@app.command('census')
def census(base_dir: Path = BASE):
    """List eligible profiles, same-church pairs and church-fit cases; computes and writes nothing."""
    from ...pastor_fit import runner
    try:
        _echo(runner.run_census(base_dir))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('fingerprints')
def fingerprints(base_dir: Path = BASE):
    """Load sermon text, remove channel boilerplate and vocabulary, count words and embed chunks locally (runs once)."""
    from ...pastor_fit import runner
    try:
        _echo(runner.build_fingerprints(base_dir, echo=typer.echo))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('match')
def match(base_dir: Path = BASE):
    """Part 1 (split-half distinctness) and Part 1b (identity pre-filter) from saved fingerprints (runs once)."""
    from ...pastor_fit import runner
    try:
        _echo(runner.run_match(base_dir))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('church-fit')
def church_fit(base_dir: Path = BASE):
    """Part 2: rank every pastor against each church described by its other preachers (runs once)."""
    from ...pastor_fit import runner
    try:
        _echo(runner.run_church_fit(base_dir))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('report')
def report(base_dir: Path = BASE):
    """Write REPORT.md and REPORT.json with the verdicts against the pre-stated pass marks."""
    from ...pastor_fit import runner
    try:
        typer.echo(f'Report: {runner.write_report(base_dir)}')
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error
