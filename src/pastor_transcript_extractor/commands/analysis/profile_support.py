"""Production-facing CLI for the experimental penultimate support stage."""
from pathlib import Path
import json
import typer
from httpx import HTTPError
from ..apps import analysis_app
from ... import profile_analysis_support_execution as execution

app=typer.Typer(help='Prepare and run evidence-linked profile analysis support before final document assembly.')
analysis_app.add_typer(app,name='profile-support')


@app.command('section-prepare')
def section_prepare(objective:Path=typer.Option(...,'--objective'),previous_allowance:Path=typer.Option(...,'--previous-allowance'),base_dir:Path=typer.Option(...,'--base-dir')):
    """Freeze the authorized six-window automatic section and superseding $3 allowance."""
    from ... import profile_section as section
    try:typer.echo(json.dumps(section.prepare(base_dir,objective,previous_allowance),indent=2))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('section-source')
def section_source(plan:Path=typer.Option(...,'--plan'),batch:str=typer.Option(...,'--batch'),approve_input:str=typer.Option(...,'--approve-input'),check_only:bool=typer.Option(False,'--check-only')):
    """Run one frozen source batch using shared binding, verification and accounting."""
    from ... import profile_section as section
    try:
        result=section.run_source(plan,batch,approve_input,check_only=check_only)
        typer.echo(json.dumps({k:v for k,v in result.items() if k!='observations'},indent=2))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('section-support-prepare')
def section_support_prepare(plan:Path=typer.Option(...,'--plan')):
    """Assemble machine observations and freeze bounded ordinary profile-support batches."""
    from ... import profile_section as section
    try:typer.echo(json.dumps(section.prepare_support(plan),indent=2))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('section-support')
def section_support(plan:Path=typer.Option(...,'--plan'),batch:str=typer.Option(...,'--batch'),approve_input:str=typer.Option(...,'--approve-input'),check_only:bool=typer.Option(False,'--check-only')):
    """Run one frozen section batch through the ordinary Qwen support recipe."""
    from ... import profile_section as section
    try:
        result=section.run_support(plan,batch,approve_input,check_only=check_only)
        typer.echo(json.dumps({k:v for k,v in result.items() if k!='results'},indent=2))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('section-render')
def section_render(plan:Path=typer.Option(...,'--plan')):
    """Deliver supported unchanged clauses, source links, trace and explicit unknowns."""
    from ... import profile_section as section
    try:typer.echo(json.dumps(section.render(plan),indent=2))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('section-report')
def section_report(plan:Path=typer.Option(...,'--plan'),as_json:bool=typer.Option(False,'--json')):
    """Inspect the saved section or pending batches offline, including historical freezes."""
    try:
        frozen=json.loads(plan.read_text());root=plan.parent
        if frozen['input_fingerprint']!=execution.digest({k:v for k,v in frozen.items() if k!='input_fingerprint'}):
            raise ValueError('Section freeze differs')
        if (root/'failure'/'assessment.json').exists():
            result=json.loads((root/'failure'/'assessment.json').read_text())
            typer.echo(json.dumps(result,indent=2) if as_json else (root/'failure'/'assessment.md').read_text())
        elif (root/'delivery.json').exists():
            result=json.loads((root/'delivery.json').read_text())
            typer.echo(json.dumps(result,indent=2) if as_json else (root/'draft-section.md').read_text())
        else:
            batches=[]
            for task in frozen['tasks']:
                path=root/'sources'/task['id']/'result.json'
                saved=json.loads(path.read_text()) if path.exists() else {}
                batches.append(dict(id=task['id'],status=saved.get('status','NOT_RUN'),eligible=saved.get('eligible'),reserved_usd=task['reserved_usd']))
            typer.echo(json.dumps(dict(status='PENDING',input_fingerprint=frozen['input_fingerprint'],budget=frozen['budget'],source_batches=batches),indent=2))
    except (ValueError,OSError,KeyError,TypeError) as error:raise typer.BadParameter(str(error)) from error


@app.command('section-failure-handoff')
def section_failure_handoff(plan:Path=typer.Option(...,'--plan')):
    """Finalize an unknown-usage stop into an explicit failed document handoff offline."""
    from ... import profile_section as section
    try:
        result=section.failure_handoff(plan)
        typer.echo(json.dumps({k:v for k,v in result.items() if k not in ('implementation_at_freeze','report_implementation','source_execution')},indent=2))
    except (ValueError,OSError,KeyError,TypeError) as error:raise typer.BadParameter(str(error)) from error


@app.command('prepare')
def prepare(profile_record:Path|None=typer.Option(None,'--profile-record'),validation_from:Path|None=typer.Option(None,'--validation-from',help='Freeze four saved contract regression cases from this run directory; no generation.'),base_dir:Path|None=typer.Option(None,'--base-dir'),check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Freeze an assembled profile or four saved regression cases; no generation."""
    try:
        packet,out=execution.prepare(base_dir,profile_record,validation_from=validation_from,check_only=check_only)
        result=execution.summary(packet,out)
        if check_only:result['status']='CHECKED_NO_WRITES'
        typer.echo(json.dumps(result,indent=2) if as_json else str(result))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('run')
def run(input_path:Path=typer.Option(...,'--input'),base_dir:Path|None=typer.Option(None,'--base-dir'),experimental:bool=typer.Option(False,'--experimental'),approve_input:str|None=typer.Option(None,'--approve-input'),max_usd:str=typer.Option('.55','--max-usd'),confirm_prices:bool=typer.Option(False,'--confirm-prices'),check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Run the frozen support stage with exact caches, bounded stream recovery and no expansion."""
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


@app.command('transport-info')
def transport_info(as_json:bool=typer.Option(False,'--json')):
    """Inspect Qwen streaming/cancellation settings offline; no provider requests."""
    import os
    from ...deepinfra_streaming import JSONWhitespaceDetector
    try:
        threshold=int(os.environ.get('PTE_DEEPINFRA_WHITESPACE_THRESHOLD','256'))
        JSONWhitespaceDetector(threshold)
        result=dict(transport='DeepInfra OpenAI-compatible SSE',stream=True,whitespace_threshold=threshold,json_string_aware=True,
            maximum_recovery_retries=1,retry_temperature='unchanged',budget_policy='Reserve both full attempts within existing ceilings; no recovery if insufficient',
            incomplete_cache_policy='Never successful',generation_calls=0)
        typer.echo(json.dumps(result,indent=2) if as_json else str(result))
    except ValueError as error:raise typer.BadParameter(str(error)) from error


@app.command('acceptance-prepare')
def acceptance_prepare(seed_run:Path=typer.Option(...,'--seed-run'),objective:Path=typer.Option(...,'--objective'),base_dir:Path|None=typer.Option(None,'--base-dir'),as_json:bool=typer.Option(False,'--json')):
    """Freeze whole-profile criteria, bounded batches and a separately authorized $2 allowance."""
    from ... import profile_support_acceptance as acceptance
    try:
        result=acceptance.prepare(seed_run,objective,base_dir)
        typer.echo(json.dumps(result,indent=2) if as_json else str(result))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('acceptance-run')
def acceptance_run(plan:Path=typer.Option(...,'--plan'),batch:str=typer.Option(...,'--batch'),approve_plan:str=typer.Option(...,'--approve-plan'),check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Execute one frozen acceptance batch within its recorded goal allowance."""
    from ... import profile_support_acceptance as acceptance
    try:
        result=acceptance.run(plan,batch,approve_plan=approve_plan,check_only=check_only,progress=lambda message:typer.echo(message,err=True))
        shown={k:v for k,v in result.items() if k!='results'}
        typer.echo(json.dumps(shown,indent=2) if as_json else str(shown))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('acceptance-assemble')
def acceptance_assemble(plan:Path=typer.Option(...,'--plan'),as_json:bool=typer.Option(False,'--json')):
    """Verify saved batches and assemble every original statement without inference."""
    from ... import profile_support_acceptance as acceptance
    try:
        result=acceptance.assemble(plan)
        typer.echo(json.dumps(result,indent=2) if as_json else str(result))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('acceptance-sources')
def acceptance_sources(plan:Path=typer.Option(...,'--plan'),canonical:bool=typer.Option(False,'--canonical',help='Use every existing canonical target block intersecting the sermon window, including projection exclusions.'),as_json:bool=typer.Option(False,'--json')):
    """Prepare complete declared-sermon text for reverse omission review; no inference."""
    from ... import profile_support_acceptance as acceptance
    from ... import profile_support_review as review
    try:
        packet,root=acceptance.load(plan)
        result=review.sources(execution.core.read_record(packet['profile_input']['path']),root/('source-review-canonical' if canonical else 'source-review'),canonical=canonical)
        typer.echo(json.dumps(result,indent=2) if as_json else str(result))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('acceptance-report')
def acceptance_report(plan:Path=typer.Option(...,'--plan'),as_json:bool=typer.Option(False,'--json')):
    """Read the saved whole-profile acceptance decision without inference."""
    from ... import profile_support_acceptance as acceptance
    try:
        packet=json.loads(plan.read_text());root=plan.parent
        if packet['input_fingerprint']!=execution.digest({k:v for k,v in packet.items() if k!='input_fingerprint'}):raise ValueError('Acceptance plan digest differs')
        result=json.loads((root/'acceptance-report.json').read_text())
        if result['plan_fingerprint']!=packet['input_fingerprint']:raise ValueError('Foreign acceptance report')
        typer.echo(json.dumps(result,indent=2) if as_json else (root/'acceptance-report.md').read_text())
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('readiness-prepare')
def readiness_prepare(prior_acceptance:Path=typer.Option(...,'--prior-acceptance'),objective:Path=typer.Option(...,'--objective'),base_dir:Path|None=typer.Option(None,'--base-dir'),as_json:bool=typer.Option(False,'--json')):
    """Freeze the authorized $3 readiness allowance and saved-answer capacity check."""
    from ... import profile_support_readiness as readiness
    try:
        result=readiness.prepare(prior_acceptance,objective,base_dir)
        typer.echo(json.dumps(result,indent=2) if as_json else str(result))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('readiness-run')
def readiness_run(input_path:Path=typer.Option(...,'--input'),approve_input:str=typer.Option(...,'--approve-input'),check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Execute one frozen readiness check; cached originals are never regenerated."""
    from ... import profile_support_readiness as readiness
    try:
        result=readiness.run(input_path,approve_input=approve_input,check_only=check_only,progress=lambda message:typer.echo(message,err=True))
        typer.echo(json.dumps({k:v for k,v in result.items() if k!='results'},indent=2) if as_json else str(result))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('readiness-regression-prepare')
def readiness_regression_prepare(root:Path=typer.Option(...,'--root'),as_json:bool=typer.Option(False,'--json')):
    """Freeze twelve preselected synthetic judgments in batches below fifty cents."""
    from ... import profile_support_regression as r
    try:
        result=r.prepare(root);typer.echo(json.dumps(result,indent=2) if as_json else str(result))
    except (ValueError,OSError,KeyError,TypeError) as error:raise typer.BadParameter(str(error)) from error


@app.command('readiness-regression-run')
def readiness_regression_run(input_path:Path=typer.Option(...,'--input'),approve_input:str=typer.Option(...,'--approve-input'),check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Run one frozen synthetic batch; no semantic retries or references in requests."""
    from ... import profile_support_regression as r
    try:
        result=r.run(input_path,approve_input,check_only=check_only,progress=lambda message:typer.echo(message,err=True))
        typer.echo(json.dumps({k:v for k,v in result.items() if k!='results'},indent=2) if as_json else str(result))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('readiness-regression-report')
def readiness_regression_report(root:Path=typer.Option(...,'--root'),as_json:bool=typer.Option(False,'--json')):
    """Compare completed synthetic outputs to separate evaluation references; no calls."""
    from ... import profile_support_regression as r
    try:
        result=r.report(root);typer.echo(json.dumps(result,indent=2) if as_json else str(result))
    except (ValueError,OSError,KeyError,TypeError) as error:raise typer.BadParameter(str(error)) from error


@app.command('readiness-diagnostic-prepare')
def readiness_diagnostic_prepare(root:Path=typer.Option(...,'--root'),as_json:bool=typer.Option(False,'--json')):
    """Freeze the two demonstrated profile judgment gaps; no expected answers in requests."""
    from ... import profile_support_readiness_review as r
    try:
        result=r.diagnostic_prepare(root);typer.echo(json.dumps(result,indent=2) if as_json else str(result))
    except (ValueError,OSError,KeyError,TypeError) as error:raise typer.BadParameter(str(error)) from error


@app.command('readiness-diagnostic-run')
def readiness_diagnostic_run(input_path:Path=typer.Option(...,'--input'),approve_input:str=typer.Option(...,'--approve-input'),check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Run only the frozen two-case judgment diagnostic, within the active goal budget."""
    from ... import profile_support_readiness_review as r
    try:
        result=r.diagnostic_run(input_path,approve_input,check_only=check_only,progress=lambda message:typer.echo(message,err=True))
        typer.echo(json.dumps({k:v for k,v in result.items() if k!='results'},indent=2) if as_json else str(result))
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:raise typer.BadParameter(str(error)) from error


@app.command('readiness-review')
def readiness_review(root:Path=typer.Option(...,'--root'),base_dir:Path|None=typer.Option(None,'--base-dir'),as_json:bool=typer.Option(False,'--json')):
    """Prepare concrete human decisions, exact cache audit and holdout prerequisites; no inference."""
    from ... import profile_support_readiness_review as r
    try:
        result=r.packet(root,base_dir);typer.echo(json.dumps(result,indent=2) if as_json else str(result))
    except (ValueError,OSError,KeyError,TypeError) as error:raise typer.BadParameter(str(error)) from error


@app.command('readiness-report')
def readiness_report(root:Path=typer.Option(...,'--root'),refresh:bool=typer.Option(False,'--refresh'),as_json:bool=typer.Option(False,'--json')):
    """Read the saved readiness decision, or audit completed receipts without inference."""
    from ... import profile_support_readiness_report as r
    try:
        result=r.prepare(root) if refresh else json.loads((root/'readiness-report.json').read_text())
        if result['report_fingerprint']!=execution.digest({k:v for k,v in result.items() if k!='report_fingerprint'}):raise ValueError('Readiness report changed')
        typer.echo(json.dumps(result,indent=2) if as_json else (root/'readiness-report.md').read_text())
    except (ValueError,OSError,KeyError,TypeError) as error:raise typer.BadParameter(str(error)) from error
