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
SET = typer.Option('v1', '--set', help='v1 is the first six sermons; v2 is the confirmatory set of eight unused sermons (section 24).')


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


COMPARE_VARIANT = typer.Option('v2', '--variant', help='Registered instruction used for the comparison (section 22 uses v2 unless a later decision says otherwise).')
ARM = typer.Option(..., '--arm', help='Comparison arm.')
CHECK = typer.Option(False, '--check-only', help='Report counts, requests and estimated cost; sends nothing.')
VARIANT = typer.Option('v1', '--variant', help='Registered instruction: v1 (section 17), v2 (section 18), v3 (section 21) or v4 (section 23, several records).')


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
def set_find(base_dir: Path = BASE, set_id: str = SET):
    """Section 19 step 1 (offline): rank analyzed sermons by public-life vocabulary density and choose the new set; no provider call."""
    from ...thought_units import public_set
    try:
        _echo(public_set.find(base_dir, set_id))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('set-score-topics')
def set_score_topics(base_dir: Path = BASE, check_only: bool = CHECK, set_id: str = SET):
    """Section 19 step 2: the topic pack (Jev) on every sermon-labeled time block of the chosen sermons, in a new cache."""
    from ...thought_units import public_set
    try:
        _echo(public_set.score_topics(base_dir, check_only=check_only, set_id=set_id))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('set-score-leaves')
def set_score_leaves(base_dir: Path = BASE, check_only: bool = CHECK, set_id: str = SET):
    """Section 19 step 3: the public-life treatment pack (Jev) on the blocks at or above the frozen topic gate."""
    from ...thought_units import public_set
    try:
        _echo(public_set.score_leaves(base_dir, check_only=check_only, set_id=set_id))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('set-pairs')
def set_pairs(base_dir: Path = BASE, top: int = typer.Option(2, '--top', help='Leaves kept per unit: 2 is the frozen rule (pairs.json); 3 is section 23 (pairs-top3.json).'), set_id: str = SET):
    """Section 19 step 4 (offline): apply the frozen flag rule to the scored blocks and write the pairs; no provider call."""
    from ...thought_units import public_set
    try:
        if top not in (2, 3):
            raise ValueError('--top must be 2 or 3')
        _echo(public_set.build_pairs(base_dir, top, set_id))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


HALF = typer.Option(..., '--half', help='development or held-out (the split recorded in the new set\'s pairs.json).')
TOP = typer.Option(2, '--top', help='Leaves kept per unit: 2 (frozen rule) or 3 (section 23, uses pairs-top3.json).')


def _half(value: str, top: int = 2) -> str:
    half = value.replace('-', '_')
    if half not in ('development', 'held_out', 'confirm'):
        raise typer.BadParameter('--half must be development, held-out or confirm')
    if top not in (2, 3):
        raise typer.BadParameter('--top must be 2 or 3')
    if half == 'confirm' and top != 3:
        raise typer.BadParameter('--half confirm uses the three-leaf pairs: pass --top 3')
    return half if top == 2 else f'{half}_top3'


@app.command('set-leaf-extract')
def set_leaf_extract(base_dir: Path = BASE, half: str = HALF, check_only: bool = CHECK, variant: str = VARIANT, top: int = TOP):
    """Section 20: write leaf-conditioned supporting summaries for one half of the new set's pairs (frozen instruction, own folder and ledger); one run, no retry."""
    from ...thought_units import leaf_evidence
    try:
        _echo(leaf_evidence.run(base_dir, check_only=check_only, variant=leaf_evidence.VARIANTS[variant], scope=leaf_evidence.SCOPES[_half(half, top)]))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


SPOT = typer.Option(False, '--spot-check', help='Section 24.8: the ten-item spot check of the delegated labels instead of the full queue.')


@app.command('set-leaf-review')
def set_leaf_review(base_dir: Path = BASE, half: str = HALF, check_only: bool = typer.Option(False, '--check-only', help='Build the blind queue and report its size; label nothing.'), top: int = TOP, spot_check: bool = SPOT):
    """Brian: label the blind queue for one half of the new set (records and no-record pairs first, then summaries); resumable. With --spot-check, label only the ten spot-check items."""
    from ...thought_units import set_review
    try:
        if spot_check:
            _echo(set_review.build_spot_queue(base_dir, _half(half, top)) if check_only else set_review.judge_spot(base_dir, _half(half, top), input, typer.echo))
        else:
            _echo(set_review.build_queue(base_dir, _half(half, top), wide=True) if check_only else set_review.judge(base_dir, _half(half, top), 'human', input, typer.echo, wide=True))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('set-leaf-report')
def set_leaf_report(base_dir: Path = BASE, half: str = HALF, top: int = TOP, spot_check: bool = SPOT):
    """Score L1 to L4 per version from the saved extractions and labels for one half and write SET_REPORT.md and .json with the defect table. With --spot-check, compare Brian's ten labels with mine."""
    from ...thought_units import set_review
    try:
        _echo(set_review.spot_report(base_dir, _half(half, top)) if spot_check else set_review.report(base_dir, _half(half, top)))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('set-graded-review')
def set_graded_review(base_dir: Path = BASE, half: str = HALF, top: int = TOP, check_only: bool = typer.Option(False, '--check-only', help='Build the graded queue and report its size; label nothing.'),
                      count: int = typer.Option(12, '--count', help='How many summary items to grade, first by sha256 of the item id.')):
    """Section 25: grade summaries as complete, accurate but incomplete (with a flag) or wrong, and distinct-point pairs as distinct, overlapping or the same point twice; wide display; resumable."""
    from ...thought_units import graded_review
    try:
        if check_only:
            _echo(graded_review.build(base_dir, _half(half, top), count))
        else:
            _echo(graded_review.judge(base_dir, _half(half, top), 'human', input, typer.echo))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('set-graded-report')
def set_graded_report(base_dir: Path = BASE, half: str = HALF, top: int = TOP):
    """Section 25: counts and readings from the graded labels, with the cross-tab against the earlier yes/no fidelity labels on the same items."""
    from ...thought_units import graded_review, leaf_evidence, leaf_review, set_review
    try:
        scope = _half(half, top)
        old = leaf_review.load_decisions(base_dir, leaf_evidence.V2, set_review.paths_for(base_dir, scope))
        _echo(graded_review.report(base_dir, scope, compare_with=old))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


ARM = typer.Option(..., '--arm', help='b (time blocks), s (snapped units) or x (snapped units with splits).')


@app.command('compare-passages')
def compare_passages(base_dir: Path = BASE):
    """Section 22 step 1 (offline): list every passage any arm flagged on sermon 281 and the unit each arm holds it in; no provider call."""
    from ...thought_units import unit_compare
    try:
        _echo(unit_compare.build(base_dir))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('compare-extract')
def compare_extract(base_dir: Path = BASE, arm: str = ARM, check_only: bool = CHECK, variant: str = COMPARE_VARIANT):
    """Section 22 step 2: leaf-evidence extraction for one arm's unit on every passage (own folder and ledger); one run, no retry."""
    from ...thought_units import leaf_evidence
    try:
        if arm not in leaf_evidence.COMPARE:
            raise ValueError('--arm must be b, s or x')
        _echo(leaf_evidence.run(base_dir, check_only=check_only, variant=leaf_evidence.VARIANTS[variant], scope=leaf_evidence.COMPARE[arm]))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('compare-review')
def compare_review(base_dir: Path = BASE, check_only: bool = typer.Option(False, '--check-only', help='Build the blind queue and report its size; label nothing.'),
                   variant: str = COMPARE_VARIANT):
    """Brian: label the blind same-passage queue (defensible and single point per option, then the best option); resumable."""
    from ...thought_units import compare_review as module
    try:
        chosen = module.leaf_evidence.VARIANTS[variant]
        _echo(module.build_queue(base_dir, chosen) if check_only else module.judge(base_dir, 'human', input, typer.echo, chosen))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('compare-report')
def compare_report(base_dir: Path = BASE, variant: str = COMPARE_VARIANT):
    """Score the same-passage comparison from the saved extractions and labels and write COMPARE_REPORT.md and .json."""
    from ...thought_units import compare_review as module
    try:
        _echo(module.report(base_dir, module.leaf_evidence.VARIANTS[variant]))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error

