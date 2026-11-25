"""One pastor's report CLI. Free: assembles saved Jev answers, free measures and summaries; no provider calls."""
from pathlib import Path

import typer

from ..apps import analysis_app
from .benchmark_explainer import ERRORS


@analysis_app.command('pastor-report')
def pastor_report(base_dir: Path = typer.Option(..., '--base-dir', help='Application base directory.'),
                  profile_id: int = typer.Option(..., '--profile-id', help='Speaker profile id; redirects resolve to the canonical profile.'),
                  concerns: Path | None = typer.Option(None, '--concerns', exists=True, dir_okay=False,
                                                       help="Optional church concerns JSON; adds that church's fit reading.")):
    """One pastor's distinctive traits, notable measures, church fit and Scripture usage from saved evidence (free; writes REPORT.md)."""
    from ...pastor_report import runner
    try:
        typer.echo(f'Written: {runner.run(base_dir, profile_id, concerns)}')
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error
