"""Benchmark explainer CLI (docs/BENCHMARK_EXPLAINER.md). Only `score` calls a provider (Jev)."""
from pathlib import Path
import json

from httpx import HTTPError
import typer

from ..apps import analysis_app

app = typer.Typer(help='Explain what is distinctive and stable about a benchmark pastor, and rank other pastors on the dimensions you pick.')
analysis_app.add_typer(app, name='benchmark-explainer')
ERRORS = (ValueError, OSError, KeyError, TypeError, RuntimeError, HTTPError)
BASE = typer.Option(..., '--base-dir', help='Application base directory.')


def _call(function, *args, **kwargs) -> None:
    try:
        value = function(*args, **kwargs)
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(f'Written: {value}' if isinstance(value, Path) else json.dumps(value, indent=2, ensure_ascii=False, default=str))


@app.command('census')
def census(base_dir: Path = BASE):
    """Count the comparison pastors and the benchmarks' sermons; reads only."""
    from ...benchmark_explainer import runner
    _call(runner.census, base_dir)


@app.command('sermon-check')
def sermon_check(base_dir: Path = BASE):
    """Step 1 and 2 (free, local): flag benchmark sermons that may not be him, and measure the free dimensions of every sermon."""
    from ...benchmark_explainer import runner
    _call(runner.sermon_check, base_dir, echo=typer.echo)


@app.command('sermon-review')
def sermon_review(base_dir: Path = BASE,
                  all_recordings: bool = typer.Option(False, '--all', help='Review every benchmark recording, not only flagged ones, each with a proposal from its title.'),
                  open_browser: bool = typer.Option(True, '--open/--no-open', help='Open each recording on YouTube as it comes up.')):
    """Keep or drop each flagged benchmark sermon, or every one with --all (resumable; Enter accepts the proposal)."""
    from ...benchmark_explainer import runner
    import webbrowser
    _call(runner.sermon_review, base_dir, echo=typer.echo, all_recordings=all_recordings,
          open_url=(lambda url: webbrowser.open(url, new=2, autoraise=True)) if open_browser else None)


@app.command('score')
def score(base_dir: Path = BASE,
          check_only: bool = typer.Option(False, '--check-only', help='Count saved answers and worst-case requests; sends nothing and copies nothing.')):
    """Step 3 (Jev, paid; $15 ceiling): every pack on the blocks of every kept sermon, reusing saved answers."""
    from ...benchmark_explainer import runner
    _call(runner.run_score, base_dir, check_only=check_only, echo=typer.echo)


@app.command('explain')
def explain(base_dir: Path = BASE):
    """Steps 4 to 6 (free): pastor values, distinctive and stable dimensions with evidence; writes EXPLAINER.md."""
    from ...benchmark_explainer import runner
    _call(runner.explain, base_dir)


@app.command('review')
def review(base_dir: Path = BASE):
    """Step 7: mark each explained dimension true, not true or can't tell (resumable)."""
    from ...benchmark_explainer import runner
    _call(runner.review, base_dir, echo=typer.echo)


@app.command('rank')
def rank(base_dir: Path = BASE):
    """Steps 8 and 9: pick dimensions you'd want, then judge the top 5 pastors' evidence (resumable)."""
    from ...benchmark_explainer import runner
    _call(runner.rank, base_dir, echo=typer.echo)


@app.command('report')
def report(base_dir: Path = BASE):
    """Write REPORT.md and REPORT.json with the verdicts against the pre-stated pass marks."""
    from ...benchmark_explainer import runner
    _call(runner.report, base_dir)
