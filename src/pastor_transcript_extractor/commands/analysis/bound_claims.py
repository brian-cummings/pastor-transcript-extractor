"""Bound-claim pilot CLI: slice, leaf signals, strata, extraction, verification, review and report."""
from pathlib import Path
import json

import typer
from httpx import HTTPError

from ..apps import analysis_app

app = typer.Typer(help='Run the bound-claim pilot: stratified extraction, Jev verification and human-labeled evaluation.')
analysis_app.add_typer(app, name='bound-claims')
ERRORS = (ValueError, OSError, KeyError, TypeError, StopIteration, HTTPError, RuntimeError)


def _echo(value) -> None:
    typer.echo(json.dumps(value, indent=2, ensure_ascii=False))


def _ledger(directory: Path):
    from ...bound_claims.ledger import PilotLedger
    return PilotLedger(Path(directory) / 'ledger.json')


@app.command('slice-propose')
def slice_propose(base_dir: Path = typer.Option(..., '--base-dir', help='Application base directory.'),
                  output: Path | None = typer.Option(None, '--output', help='Defaults to <base>/evaluation/bound-claim-pilot-v1/slice.json.')):
    """Propose the pilot's pastors and sermons from cached topic projections; no provider call."""
    from ...bound_claims import slice as slicing
    try:
        _echo(slicing.propose(base_dir, output))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('leaf-run')
def leaf_run(slice_path: Path = typer.Option(..., '--slice', help='Approved slice.json.'),
             approve_slice: str = typer.Option(..., '--approve-slice', help='SHA-256 of the approved slice file.'),
             packs: str = typer.Option('TSPH', '--packs', help='Leaf packs: T topics, S salvation, P public life, H style, L listener directives, M source material.'),
             check_only: bool = typer.Option(False, '--check-only', help='Census saved answers and worst-case requests; opens no client.')):
    """Collect saved and missing Jev leaf signals for every slice block, with reservations and a hard ceiling."""
    from ...bound_claims import leaf_pass
    try:
        slice_path = slice_path.resolve()
        _echo(leaf_pass.run(slice_path, approve_slice, _ledger(slice_path.parent), check_only=check_only, letters=packs))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('strata')
def strata(slice_path: Path = typer.Option(..., '--slice', help='Approved slice.json.'),
           leaf: Path = typer.Option(..., '--leaf', help='leaf_observations.json from leaf-run.'),
           output: Path = typer.Option(..., '--output', help='strata.json to write.')):
    """Select the 100 stratified blocks deterministically from the leaf table; no provider call."""
    from ...bound_claims import strata as selection
    try:
        _echo(selection.run(slice_path, leaf, output))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error
