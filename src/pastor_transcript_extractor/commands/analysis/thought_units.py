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


@app.command('improve-pairs')
def improve_pairs(base_dir: Path = BASE):
    """Write the 60 fresh boundary-improvement positions from a sermon not yet used (fixed seed); no provider call."""
    from ...thought_units import improve
    try:
        _echo(improve.choose_pairs(base_dir))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('improve')
def improve_boundaries(base_dir: Path = BASE,
                       check_only: bool = typer.Option(False, '--check-only', help='Report questions, requests and estimated cost; sends nothing.')):
    """Run the baseline and three boundary approaches on the fresh set (Jev) and score them against the blind labels; one run only."""
    from ...thought_units import improve
    try:
        _echo(improve.run(base_dir, check_only=check_only))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('snap')
def snap(base_dir: Path = BASE,
         check_only: bool = typer.Option(False, '--check-only', help='Report candidates, questions and estimated cost; sends nothing.'),
         video: int = typer.Option(None, '--video', help='Run on this sermon for the downstream comparison (its own folder and ledger); default is the held-out sermon.')):
    """Score every candidate boundary in a sermon (Jev) and build the original, code, jev and jev_split arms (with the blind grading packet for the held-out sermon)."""
    from ...thought_units import snap as snapping
    try:
        _echo(snapping.run(base_dir, check_only=check_only, video=video))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('snap-review')
def snap_review(base_dir: Path = BASE, grader: str = typer.Option('brian', '--grader', help='Name recorded with the judgments.'),
                limit: int = typer.Option(15, '--limit', help='Edge comparisons to judge (the calibration set).')):
    """Judge the calibration edge comparisons (which cut is the better place to end a block); resumable."""
    from ...thought_units import snap as snapping, stage
    try:
        _, _, out = stage.paths(base_dir)
        done = snapping.judge(out, grader, ('edge_pair',), limit, input, typer.echo)
        _echo(dict(grader=grader, judged=len(done)))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('snap-report')
def snap_report(base_dir: Path = BASE, grader: str = typer.Option('claude', '--grader', help='Whose judgments score the bars.')):
    """Score the snap test bars from the saved judgments and write SNAP_REPORT.md and .json."""
    from ...thought_units import snap as snapping, stage
    try:
        _, _, out = stage.paths(base_dir)
        _echo(snapping.report(out, grader))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


ARM = typer.Option(..., '--arm', help='Comparison arm.')
CHECK = typer.Option(False, '--check-only', help='Report counts, requests and estimated cost; sends nothing.')
VARIANT = typer.Option('v1', '--variant', help='Registered instruction: v1 (section 17) or v2 (section 18).')


@app.command('arms')
def arms_units(base_dir: Path = BASE, check_only: bool = typer.Option(False, '--check-only', help='Report unit counts, segment mapping and the A1 integrity checks without writing units.json.')):
    """Build the time-block (b), snapped (s) and snapped-with-splits (x) units for sermon 281 from the snap result, and check integrity (A1); no provider call."""
    from ...thought_units import arms as comparison
    try:
        _echo(comparison.build_units(base_dir, check_only=check_only))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('assess')
def assess(base_dir: Path = BASE, arm: str = ARM, check_only: bool = CHECK):
    """Run the topic and public-life treatment packs (Jev) on the units of arm s or x in a new cache, reusing identical saved answers."""
    from ...thought_units import arms as comparison
    try:
        _echo(comparison.assess(base_dir, arm.lower(), check_only=check_only))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('extract')
def extract(base_dir: Path = BASE, arm: str = ARM, check_only: bool = CHECK):
    """One main-point request per flagged (unit, leaf) pair for arm b, s or x (V4.1 Flash, frozen instruction); no semantic retry."""
    from ...thought_units import main_point
    try:
        _echo(main_point.run(base_dir, arm.lower(), check_only=check_only))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('review')
def review(base_dir: Path = BASE, check_only: bool = typer.Option(False, '--check-only', help='Build the blind queue and report its size; label nothing.')):
    """Brian: label the blind, shuffled queue (accept or reject, plus component judgments on component records); resumable."""
    from ...thought_units import arms_review
    try:
        if check_only:
            _echo(arms_review.build_queue(base_dir))
        else:
            _echo(arms_review.interactive(base_dir, input, typer.echo))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('arms-report')
def arms_report(base_dir: Path = BASE):
    """Score A1 to A4 from the saved extraction, labels and ledgers and write ARMS_REPORT.md and .json."""
    from ...thought_units import arms_review
    try:
        _echo(arms_review.report(base_dir))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('leaf-extract')
def leaf_extract(base_dir: Path = BASE, check_only: bool = CHECK, variant: str = VARIANT):
    """Sections 17 and 18: write the leaf-conditioned supporting summary for arm B's flagged pairs (V4.1 Flash, frozen instruction); one run, no semantic retry."""
    from ...thought_units import leaf_evidence
    try:
        _echo(leaf_evidence.run(base_dir, check_only=check_only, variant=leaf_evidence.VARIANTS[variant]))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('leaf-review')
def leaf_review(base_dir: Path = BASE, check_only: bool = typer.Option(False, '--check-only', help='Build the blind queue and report its size; label nothing.'),
                variant: str = VARIANT):
    """Brian: label the blind queue of baseline and new records (accept or reject, leaf fit, then summary questions); resumable."""
    from ...thought_units import leaf_review as review_module
    try:
        chosen = review_module.leaf_evidence.VARIANTS[variant]
        _echo(review_module.build_queue(base_dir, chosen) if check_only else review_module.judge(base_dir, 'human', input, typer.echo, chosen))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('leaf-report')
def leaf_report(base_dir: Path = BASE, variant: str = VARIANT):
    """Score L1 to L4 from the saved extractions, labels and ledgers and write LEAF_REPORT.md and .json."""
    from ...thought_units import leaf_review as review_module
    try:
        _echo(review_module.report(base_dir, review_module.leaf_evidence.VARIANTS[variant]))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('set-find')
def set_find(base_dir: Path = BASE):
    """Section 19 step 1 (offline): rank analyzed sermons by public-life vocabulary density and choose the new set; no provider call."""
    from ...thought_units import public_set
    try:
        _echo(public_set.find(base_dir))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('set-score-topics')
def set_score_topics(base_dir: Path = BASE, check_only: bool = CHECK):
    """Section 19 step 2: the topic pack (Jev) on every sermon-labeled time block of the chosen sermons, in a new cache."""
    from ...thought_units import public_set
    try:
        _echo(public_set.score_topics(base_dir, check_only=check_only))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('set-score-leaves')
def set_score_leaves(base_dir: Path = BASE, check_only: bool = CHECK):
    """Section 19 step 3: the public-life treatment pack (Jev) on the blocks at or above the frozen topic gate."""
    from ...thought_units import public_set
    try:
        _echo(public_set.score_leaves(base_dir, check_only=check_only))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('set-pairs')
def set_pairs(base_dir: Path = BASE):
    """Section 19 step 4 (offline): apply the frozen flag rule to the scored blocks and write the pairs; no provider call."""
    from ...thought_units import public_set
    try:
        _echo(public_set.build_pairs(base_dir))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error
