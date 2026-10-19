"""Nomination-only selected-window CLI; no implicit execution."""
import typer
from pathlib import Path
from rich.console import Console
from pastor_transcript_extractor.commands.apps import analysis_app
from pastor_transcript_extractor import typesafe_selection_packet as packet


@analysis_app.command('typesafe-position-selection', help='Prepare/check the fixed nomination-only packet; execution requires a separate fingerprint-bound authorization.')
def typesafe_position_selection(
    check_only: bool = typer.Option(False, '--check-only'),
    run: bool = typer.Option(False, '--run'),
    approve_input: str | None = typer.Option(None, '--approve-input'),
    as_json: bool = typer.Option(False, '--json'),
    base_dir: Path | None = typer.Option(None, '--base-dir'),
):
    if check_only and run or approve_input is not None and not run:
        raise typer.BadParameter('Choose preparation, --check-only, or --run --approve-input')
    try:
        if run:
            from pastor_transcript_extractor.typesafe_selection_execution import execute
            value, path = execute(approve_input, base_dir)
        else:
            value, path = packet.verify(base_dir) if check_only else packet.prepare(base_dir)
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise typer.BadParameter(str(error)) from error
    output = dict(status=value['status'], input_fingerprint=value.get('input_fingerprint', value['content_fingerprint']),
        provider_requests=value['provider_requests'], path=str(path))
    console = Console()
    if as_json:
        console.print_json(data=output)
    else:
        console.print(output, markup=False)
