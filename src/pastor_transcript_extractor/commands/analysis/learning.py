"""Thin CLI adapters for bounded V3 preparation and separately authorized execution."""
from pathlib import Path
import json
import typer
from ..apps import analysis_app
from ... import learning_demo

app=typer.Typer(help='Prepare V3 offline; paid execution requires a separate exact-input decision.')
analysis_app.add_typer(app,name='learning-demo')


def emit(value,as_json):
    typer.echo(json.dumps(value,indent=2,ensure_ascii=False) if as_json else str(value))


@app.command('prepare')
def prepare(proposal:Path=typer.Option(...,'--proposal'),
            base_dir:Path|None=typer.Option(None,'--base-dir'),
            check_only:bool=typer.Option(False,'--check-only'),
            as_json:bool=typer.Option(False,'--json')):
    try:
        packet,out=learning_demo.prepare(proposal,base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],
            coverage=packet['coverage'],budget=packet['budget'],provider_calls=0),as_json)
    except (ValueError,OSError,KeyError) as error: raise typer.BadParameter(str(error)) from error


@app.command('run')
def run(input_path:Path=typer.Option(...,'--input'),base_dir:Path|None=typer.Option(None,'--base-dir'),
        approve_input:str|None=typer.Option(None,'--approve-input'),
        experimental:bool=typer.Option(False,'--experimental'),
        max_usd:str=typer.Option('2.00','--max-usd'),
        confirm_proposal_prices:bool=typer.Option(False,'--confirm-proposal-prices'),
        check_only:bool=typer.Option(False,'--check-only'),
        as_json:bool=typer.Option(False,'--json')):
    try:
        result=learning_demo.run(input_path,base_dir,approve_input=approve_input,experimental=experimental,
            max_usd=max_usd,confirm_proposal_prices=confirm_proposal_prices,check_only=check_only)
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError) as error: raise typer.BadParameter(str(error)) from error


@app.command('report')
def report(run_dir:Path=typer.Option(...,'--run-dir'),audit:Path|None=typer.Option(None,'--audit'),
           base_dir:Path|None=typer.Option(None,'--base-dir'),
           as_json:bool=typer.Option(False,'--json')):
    try:
        emit(learning_demo.report(run_dir,audit=json.loads(audit.read_text()) if audit else None,base_dir=base_dir),as_json)
    except (ValueError,OSError,KeyError) as error: raise typer.BadParameter(str(error)) from error
