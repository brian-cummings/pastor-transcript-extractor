"""Thin CLI adapters for bounded V3 preparation and separately authorized execution."""
from pathlib import Path
import json
import typer
from httpx import HTTPError
from ..apps import analysis_app
from ... import learning_demo
from ... import learning_demo_model_fit as model_fit
from ... import ollama_conformance

app=typer.Typer(help='Prepare V3 offline; paid execution requires a separate exact-input decision.')
analysis_app.add_typer(app,name='learning-demo')
fit_app=typer.Typer(help='Prepare and inspect a six-window, local-only source-reading model-fit trial.')
app.add_typer(fit_app,name='model-fit')


@fit_app.command('deepinfra-prepare')
def deepinfra_prepare(prior_input:Path=typer.Option(...,'--from-input'),
                     base_dir:Path|None=typer.Option(None,'--base-dir'),
                     expanded_output:bool=typer.Option(False,'--expanded-output',help='Prepare one generous-output request after the reviewed hosted length stop.'),
                     check_only:bool=typer.Option(False,'--check-only'),
                     as_json:bool=typer.Option(False,'--json')):
    """Prepare one hosted DeepSeek source check without provider calls."""
    from ... import learning_demo_deepinfra_fit as hosted
    try:
        packet,out=hosted.prepare(prior_input,base_dir,check_only=check_only,expanded_output=expanded_output)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],
            model=packet['request']['body']['model'],budget=packet['budget'],provider_calls=int(expanded_output),
            metadata_requests=int(expanded_output),generation_calls=0,paid_calls=0,
            credentials=packet['credentials']),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('deepinfra-run')
def deepinfra_run(input_path:Path=typer.Option(...,'--input'),
                 base_dir:Path|None=typer.Option(None,'--base-dir'),
                 experimental:bool=typer.Option(False,'--experimental'),
                 approve_input:str|None=typer.Option(None,'--approve-input'),
                 max_usd:str=typer.Option('0.25','--max-usd'),
                 confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                 check_only:bool=typer.Option(False,'--check-only'),
                 as_json:bool=typer.Option(False,'--json')):
    """Execute exactly one frozen paid request; no fallback or retries."""
    from ... import learning_demo_deepinfra_fit as hosted
    try:
        result=hosted.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,
            max_usd=max_usd,confirm_prices=confirm_prices,check_only=check_only,
            progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('thinking-prepare')
def thinking_prepare(prior_input:Path=typer.Option(...,'--from-input'),
                     base_dir:Path|None=typer.Option(None,'--base-dir'),
                     check_only:bool=typer.Option(False,'--check-only'),
                     as_json:bool=typer.Option(False,'--json')):
    """Freeze one complete reviewed window with thinking enabled and two claims."""
    from ... import learning_demo_thinking_check as thinking
    from httpx import HTTPError
    try:
        packet,out=thinking.prepare(prior_input,base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],
            budget=packet['budget'],execution_policy=packet['token_account']['execution_policy'],model_calls=0),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('thinking-run')
def thinking_run(input_path:Path=typer.Option(...,'--input'),
                 base_dir:Path|None=typer.Option(None,'--base-dir'),
                 experimental:bool=typer.Option(False,'--experimental'),
                 approve_input:str|None=typer.Option(None,'--approve-input'),
                 check_only:bool=typer.Option(False,'--check-only'),
                 as_json:bool=typer.Option(False,'--json')):
    """Execute the frozen one-request thinking diagnostic; no paid calls or retries."""
    from ... import learning_demo_thinking_check as thinking
    from httpx import HTTPError
    try:
        result=thinking.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,
            check_only=check_only,progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


def emit(value,as_json):
    typer.echo(json.dumps(value,indent=2,ensure_ascii=False) if as_json else str(value))


@app.command('prepare')
def prepare(proposal:Path=typer.Option(...,'--proposal'),
            base_dir:Path|None=typer.Option(None,'--base-dir'),
            model:str|None=typer.Option(None,'--model',help='Installed Ollama model; defaults to PTE_LLM_MODEL, then gemma3:4b.'),
            restart_from:Path|None=typer.Option(None,'--restart-from'),
            contract_round_from:Path|None=typer.Option(None,'--contract-round-from'),
            check_only:bool=typer.Option(False,'--check-only'),
            as_json:bool=typer.Option(False,'--json')):
    try:
        packet,out=learning_demo.prepare(proposal,base_dir,check_only=check_only,restart_from=restart_from,contract_round_from=contract_round_from,model=model)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],
            coverage=packet['coverage'],budget=packet['budget'],provider_calls=0),as_json)
    except (ValueError,OSError,KeyError) as error: raise typer.BadParameter(str(error)) from error


@app.command('run')
def run(input_path:Path=typer.Option(...,'--input'),base_dir:Path|None=typer.Option(None,'--base-dir'),
        approve_input:str|None=typer.Option(None,'--approve-input'),
        experimental:bool=typer.Option(False,'--experimental'),
        max_usd:str=typer.Option('0.10','--max-usd'),
        confirm_proposal_prices:bool=typer.Option(False,'--confirm-verifier-price','--confirm-proposal-prices'),
        check_only:bool=typer.Option(False,'--check-only'),
        as_json:bool=typer.Option(False,'--json')):
    try:
        result=learning_demo.run(input_path,base_dir,approve_input=approve_input,experimental=experimental,
            max_usd=max_usd,confirm_proposal_prices=confirm_proposal_prices,check_only=check_only,
            progress=lambda message:typer.echo(message,err=True))
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


@app.command('model-info')
def model_info(model:str|None=typer.Option(None,'--model'),
               as_json:bool=typer.Option(False,'--json')):
    """Inspect and hash an installed local model without loading it or running inference."""
    try:
        runtime=learning_demo.ollama_runtime_identity(model=model)
        emit(dict(status='INSTALLED_MODEL_CHECKED',runtime=runtime,
            selection='--model overrides PTE_LLM_MODEL; frozen inputs retain their selection',
            metadata_requests=1,model_calls=0,generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError) as error: raise typer.BadParameter(str(error)) from error


@app.command('runtime-check')
def runtime_check(base_dir:Path|None=typer.Option(None,'--base-dir'),
                  model:str=typer.Option('qwen3.5:9b','--model'),
                  input_path:Path|None=typer.Option(None,'--input'),
                  execute:bool=typer.Option(False,'--execute',help='Execute the frozen two-request synthetic check; no source data or paid calls.'),
                  as_json:bool=typer.Option(False,'--json')):
    """Prepare or execute a synthetic Ollama schema enforcement check."""
    from httpx import HTTPError
    try:
        if execute:
            if input_path is None: raise ValueError('--execute requires a frozen --input')
            result=ollama_conformance.run(input_path,base_dir,progress=lambda message:typer.echo(message,err=True))
        else:
            if input_path is not None: raise ValueError('--input requires --execute')
            result=ollama_conformance.prepare(base_dir,model=model)
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('prepare')
def fit_prepare(prior_input:Path=typer.Option(...,'--from-input'),
                base_dir:Path|None=typer.Option(None,'--base-dir'),
                model:str=typer.Option('qwen3.5:9b','--model'),
                runtime_repeat:bool=typer.Option(False,'--runtime-repeat',help='Prepare the authorized same-six-window repeat after the saved runtime conformance PASS.'),
                check_only:bool=typer.Option(False,'--check-only'),
                as_json:bool=typer.Option(False,'--json')):
    try:
        if runtime_repeat:
            from ...learning_demo_runtime_repeat import prepare as repeat_prepare
            packet,out=repeat_prepare(prior_input,base_dir,model=model,check_only=check_only)
        else:
            packet,out=model_fit.prepare(prior_input,base_dir,model=model,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],
            selection=packet['selection'],budget=packet['budget'],model_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('run')
def fit_run(input_path:Path=typer.Option(...,'--input'),base_dir:Path|None=typer.Option(None,'--base-dir'),
            approve_input:str|None=typer.Option(None,'--approve-input'),
            experimental:bool=typer.Option(False,'--experimental'),
            max_usd:str=typer.Option('0','--max-usd'),check_only:bool=typer.Option(False,'--check-only'),
            as_json:bool=typer.Option(False,'--json')):
    try:
        result=model_fit.run(input_path,base_dir,approve_input=approve_input,experimental=experimental,
            max_usd=max_usd,check_only=check_only,progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('report')
def fit_report(run_dir:Path=typer.Option(...,'--run-dir'),base_dir:Path|None=typer.Option(None,'--base-dir'),
               as_json:bool=typer.Option(False,'--json')):
    try: emit(model_fit.report(run_dir,base_dir),as_json)
    except (ValueError,OSError,KeyError) as error: raise typer.BadParameter(str(error)) from error
