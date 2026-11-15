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


@app.command('extract')
def extract_claims(strata_path: Path = typer.Option(..., '--strata', help='strata.json from the strata command.'),
                   producer: str = typer.Option(..., '--producer', help='pro (DeepSeek V4 Pro, reasoning none) or flash (V4.1 Flash control, reasoning none).'),
                   check_only: bool = typer.Option(False, '--check-only', help='Report requests and worst-case reservation; sends nothing.')):
    """Extract bound claims for the stratified blocks, one reserved request per block and no semantic retry."""
    from ...bound_claims import extract as extraction
    try:
        strata_path = strata_path.resolve()
        _echo(extraction.run(strata_path, producer, _ledger(strata_path.parent), check_only=check_only))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('verify')
def verify_claims(extraction: list[Path] = typer.Option(..., '--extraction', help='extraction.json from extract; repeat for each producer.'),
                  check_only: bool = typer.Option(False, '--check-only', help='Report requests and worst-case reservation; sends nothing.')):
    """Verify every distinct extracted claim with independent Jev Noul questions; no threshold is applied."""
    from ...bound_claims import verify as verification
    try:
        paths = [path.resolve() for path in extraction]
        _echo(verification.run(paths, _ledger(paths[0].parents[2]), check_only=check_only))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('review-queue')
def review_queue(pilot: Path = typer.Option(..., '--pilot', help='Pilot directory (<base>/evaluation/bound-claim-pilot-v1).'),
                 output: Path | None = typer.Option(None, '--output', help='Defaults to <pilot>/review.json.')):
    """Build the blind, shuffled review queue from both producers' claims; no provider call."""
    from ...bound_claims import review as reviewing
    try:
        _echo(reviewing.write_queue(pilot.resolve(), output))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('review')
def review_claims(pilot: Path = typer.Option(..., '--pilot', help='Pilot directory.'),
                  decisions: Path | None = typer.Option(None, '--decisions', help='Replay saved decisions instead of the interactive loop.')):
    """Accept or reject each queued claim; decisions append to decisions.jsonl and the command resumes."""
    from ...bound_claims import review as reviewing
    try:
        _echo(reviewing.replay(pilot.resolve(), decisions) if decisions else reviewing.interactive(pilot.resolve(), input, typer.echo))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('report')
def report_pilot(pilot: Path = typer.Option(..., '--pilot', help='Pilot directory.')):
    """Write REPORT.md/.json: producer precision, Jev threshold curves, controls and the acceptance table."""
    from ...bound_claims import report as reporting
    try:
        _echo(reporting.run(pilot.resolve()))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('render')
def render_section(pilot: Path = typer.Option(..., '--pilot', help='Pilot directory.'),
                   profile: int | None = typer.Option(None, '--profile', help='Profile id; defaults to the profile with the most accepted V4 Pro claims.')):
    """Present the accepted V4 Pro claims for one profile as Markdown with source links; no interpretation."""
    from ...bound_claims import render as rendering
    try:
        _echo(rendering.run(pilot.resolve(), profile))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('run')
def run_paid_steps(pilot: Path = typer.Option(..., '--pilot', help='Pilot directory holding the approved slice.json.'),
                   approve_slice: str = typer.Option(..., '--approve-slice', help='SHA-256 of the approved slice file.'),
                   check_only: bool = typer.Option(False, '--check-only', help='Census only; sends nothing.')):
    """Run leaf signals, strata, Pro and Flash extraction and verification in order; resumable, stops at the first hard stop."""
    from ...bound_claims import pipeline
    try:
        _echo(pipeline.run(pilot.resolve(), approve_slice, check_only=check_only))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('finish')
def finish(pilot: Path = typer.Option(..., '--pilot', help='Pilot directory.')):
    """After review: render the section for the best-supported profile, then write the report."""
    from ...bound_claims import render as rendering, report as reporting
    try:
        _echo(dict(render=rendering.run(pilot.resolve()), report=reporting.run(pilot.resolve())))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error
