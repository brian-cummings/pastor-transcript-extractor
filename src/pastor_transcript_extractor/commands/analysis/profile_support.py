"""Production-facing CLI for the experimental penultimate support stage."""
from pathlib import Path
import json
import typer
from httpx import HTTPError
from ..apps import analysis_app
from ... import profile_analysis_support_execution as execution

app=typer.Typer(help='Prepare and run evidence-linked profile analysis support before final document assembly.')
analysis_app.add_typer(app,name='profile-support')


@app.command('prepare')
def prepare(profile_record:Path=typer.Option(...,'--profile-record'),base_dir:Path|None=typer.Option(None,'--base-dir'),check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Freeze every analytical statement in an assembled profile; no generation."""
    try:
        packet,out=execution.prepare(base_dir,profile_record,check_only=check_only)
        result=execution.summary(packet,out)
        if check_only:result['status']='CHECKED_NO_WRITES'
        typer.echo(json.dumps(result,indent=2) if as_json else str(result))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('run')
def run(input_path:Path=typer.Option(...,'--input'),base_dir:Path|None=typer.Option(None,'--base-dir'),experimental:bool=typer.Option(False,'--experimental'),approve_input:str|None=typer.Option(None,'--approve-input'),max_usd:str=typer.Option('.55','--max-usd'),confirm_prices:bool=typer.Option(False,'--confirm-prices'),check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Run the frozen support stage with exact caches and no retries or expansion."""
    try:
        result=execution.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,max_usd=max_usd,confirm_prices=confirm_prices,check_only=check_only,progress=lambda message:typer.echo(message,err=True))
        # Full per-statement judgments remain in immutable results/document input.
        shown={k:v for k,v in result.items() if k!='results'}
        typer.echo(json.dumps(shown,indent=2) if as_json else str(shown))
        if result['status']=='FAIL(component)':raise typer.Exit(1)
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('report')
def report(run_dir:Path=typer.Option(...,'--run-dir'),as_json:bool=typer.Option(False,'--json')):
    """Read saved support outcomes and final-document handoff without provider calls."""
    try:
        value=json.loads((run_dir/'results.json').read_text())
        shown={k:v for k,v in value.items() if k!='results'}
        typer.echo(json.dumps(shown,indent=2) if as_json else (run_dir/'analysis-support.md').read_text())
    except (ValueError,OSError,KeyError,TypeError) as error:raise typer.BadParameter(str(error)) from error
