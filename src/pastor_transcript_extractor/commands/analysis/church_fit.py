"""Church fit reading CLI (concerns framework). Free: reads saved Jev answers; no provider calls."""
from pathlib import Path

import typer

from ..apps import analysis_app
from .benchmark_explainer import ERRORS


@analysis_app.command('church-fit')
def church_fit(base_dir: Path = typer.Option(..., '--base-dir', help='Application base directory.'),
               concerns: Path = typer.Option(..., '--concerns', exists=True, dir_okay=False,
                                             help="A church's approved concerns JSON (want and avoid concerns with their measures).")):
    """Rank pastors on a church's want concerns and list avoid-concern passages for review (free; writes FIT.md)."""
    from ...church_fit import runner
    try:
        typer.echo(f'Written: {runner.run(base_dir, concerns)}')
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error
