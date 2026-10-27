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
fit_app=typer.Typer(help='Prepare frozen model-fit checks and bounded source-reading trials.')
app.add_typer(fit_app,name='model-fit')


@fit_app.command('role-decisions-prepare')
def role_decisions_prepare(base_dir:Path|None=typer.Option(None,'--base-dir'),check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Freeze unresolved direct choices with explicit role evidence; reuse compatible resolved choices."""
    from ... import role_decisions_check as check
    try:
        packet,out=check.prepare(base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('role-decisions-run')
def role_decisions_run(input_path:Path=typer.Option(...,'--input'),base_dir:Path|None=typer.Option(None,'--base-dir'),
                       experimental:bool=typer.Option(False,'--experimental'),approve_input:str|None=typer.Option(None,'--approve-input'),
                       max_usd:str=typer.Option('0.003','--max-usd'),confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                       check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Run one TypeSafe decision check without retries, new extraction or admission."""
    from ... import role_decisions_check as check
    try:
        if not check_only: typer.echo('TypeSafe 1/1: eleven unresolved field decisions; seven saved choices reused; no retries',err=True)
        result=check.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,max_usd=max_usd,confirm_prices=confirm_prices,check_only=check_only)
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('voice-context-prepare')
def voice_context_prepare(base_dir:Path|None=typer.Option(None,'--base-dir'),check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Freeze separate speaker-context evidence selection for six fixed saved propositions."""
    from ... import passage_voice_context as context
    try:
        packet,out=context.prepare(base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('voice-context-run')
def voice_context_run(input_path:Path=typer.Option(...,'--input'),base_dir:Path|None=typer.Option(None,'--base-dir'),
                       experimental:bool=typer.Option(False,'--experimental'),approve_input:str|None=typer.Option(None,'--approve-input'),
                       max_usd:str=typer.Option('0.04','--max-usd'),confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                       check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Select and assess speaker-context evidence without changing proposition or adoption evidence."""
    from ... import passage_voice_context as context
    try:
        result=context.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,max_usd=max_usd,confirm_prices=confirm_prices,check_only=check_only,progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('passage-audit-prepare')
def passage_audit_prepare(base_dir:Path|None=typer.Option(None,'--base-dir'),check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Freeze a source-cited diagnosis/action audit of six uncertain saved selections."""
    from ... import passage_source_audit as audit
    try:
        packet,out=audit.prepare(base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('passage-audit-run')
def passage_audit_run(input_path:Path=typer.Option(...,'--input'),base_dir:Path|None=typer.Option(None,'--base-dir'),
                       experimental:bool=typer.Option(False,'--experimental'),approve_input:str|None=typer.Option(None,'--approve-input'),
                       max_usd:str=typer.Option('0.04','--max-usd'),confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                       check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Execute one frozen source diagnosis/action audit and bounded TypeSafe assessment."""
    from ... import passage_source_audit as audit
    try:
        result=audit.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,max_usd=max_usd,confirm_prices=confirm_prices,check_only=check_only,progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('passage-review-prepare')
def passage_review_prepare(base_dir:Path|None=typer.Option(None,'--base-dir'),check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Freeze one semantic reconsideration of saved passages using TypeSafe uncertainty feedback."""
    from ... import passage_selection_review as review
    try:
        packet,out=review.prepare(base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('passage-review-run')
def passage_review_run(input_path:Path=typer.Option(...,'--input'),base_dir:Path|None=typer.Option(None,'--base-dir'),
                        experimental:bool=typer.Option(False,'--experimental'),approve_input:str|None=typer.Option(None,'--approve-input'),
                        max_usd:str=typer.Option('0.04','--max-usd'),confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                        check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Run the frozen single passage reconsideration, bounded mechanical retry and TypeSafe recheck."""
    from ... import passage_selection_review as review
    try:
        result=review.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,max_usd=max_usd,
            confirm_prices=confirm_prices,check_only=check_only,progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('passage-selection-contract')
def passage_selection_contract(base_dir:Path|None=typer.Option(None,'--base-dir'),as_json:bool=typer.Option(False,'--json')):
    """Export revised passage contract and neutral verifier specimen; no execution."""
    from ... import passage_selection_check as check
    try: emit(check.export_contract(base_dir),as_json)
    except (ValueError,OSError,KeyError,TypeError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('passage-selection-prepare')
def passage_selection_prepare(base_dir:Path|None=typer.Option(None,'--base-dir'),
                               check_only:bool=typer.Option(False,'--check-only'),
                               as_json:bool=typer.Option(False,'--json')):
    """Freeze the supervised complete-sentence selection check with a bounded per-run budget."""
    from ... import passage_selection_check as check
    try:
        packet,out=check.prepare(base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',input=str(out/'input.json'),
            input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('passage-selection-run')
def passage_selection_run(input_path:Path=typer.Option(...,'--input'),base_dir:Path|None=typer.Option(None,'--base-dir'),
                           experimental:bool=typer.Option(False,'--experimental'),approve_input:str|None=typer.Option(None,'--approve-input'),
                           max_usd:str=typer.Option('0.04','--max-usd'),confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                           check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Execute an approved frozen passage check or return its completed result; no automatic expansion."""
    from ... import passage_selection_check as check
    try:
        result=check.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,max_usd=max_usd,
            confirm_prices=confirm_prices,check_only=check_only,progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('voice-adoption-prepare')
def voice_adoption_prepare(base_dir:Path|None=typer.Option(None,'--base-dir'),
                           check_only:bool=typer.Option(False,'--check-only'),
                           as_json:bool=typer.Option(False,'--json')):
    """Freeze one direct TypeSafe voice/occurrence/adoption diagnostic; no model calls."""
    from ... import voice_adoption_check as check
    try:
        packet,out=check.prepare(base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',input=str(out/'input.json'),
            input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('voice-adoption-run')
def voice_adoption_run(input_path:Path=typer.Option(...,'--input'),base_dir:Path|None=typer.Option(None,'--base-dir'),
                        experimental:bool=typer.Option(False,'--experimental'),approve_input:str|None=typer.Option(None,'--approve-input'),
                        max_usd:str=typer.Option('0.003','--max-usd'),confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                        check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Execute one frozen direct voice/adoption request; no extraction, retries or correction."""
    from ... import voice_adoption_check as check
    try:
        result=check.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,max_usd=max_usd,
            confirm_prices=confirm_prices,check_only=check_only)
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('polarity-producer-materialize')
def polarity_producer_materialize(base_dir:Path|None=typer.Option(None,'--base-dir'),
                                  as_json:bool=typer.Option(False,'--json')):
    """Build unadmitted shadow observations from saved polarity decisions; no provider calls."""
    from ... import polarity_producer
    try: emit(polarity_producer.materialize(base_dir),as_json)
    except (ValueError,OSError,KeyError,TypeError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('polarity-choice-prepare')
def polarity_choice_prepare(base_dir:Path|None=typer.Option(None,'--base-dir'),
                            check_only:bool=typer.Option(False,'--check-only'),
                            as_json:bool=typer.Option(False,'--json')):
    """Freeze one TypeSafe Choice batch for six saved propositions plus four synthetic controls."""
    from ... import polarity_choice_check as check
    try:
        packet,out=check.prepare(base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',input=str(out/'input.json'),
            input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('polarity-choice-run')
def polarity_choice_run(input_path:Path=typer.Option(...,'--input'),base_dir:Path|None=typer.Option(None,'--base-dir'),
                        experimental:bool=typer.Option(False,'--experimental'),approve_input:str|None=typer.Option(None,'--approve-input'),
                        max_usd:str=typer.Option('0.003','--max-usd'),confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                        check_only:bool=typer.Option(False,'--check-only'),as_json:bool=typer.Option(False,'--json')):
    """Execute the frozen single TypeSafe polarity request; no DeepSeek, retries or correction."""
    from ... import polarity_choice_check as check
    try:
        result=check.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,max_usd=max_usd,
            confirm_prices=confirm_prices,check_only=check_only)
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('attachment-prepare')
def attachment_prepare(base_dir:Path|None=typer.Option(None,'--base-dir'),
                       check_only:bool=typer.Option(False,'--check-only'),
                       as_json:bool=typer.Option(False,'--json')):
    """Freeze three existing full-schema windows with Flash 1017 and the TypeSafe loop."""
    from ... import attachment_trial as trial
    try:
        packet,out=trial.prepare(base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            model=packet['model'],input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],
            budget=packet['budget'],selection=packet['selection'],execute_command=trial.command(out,packet,base_dir),
            generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('attachment-run')
def attachment_run(input_path:Path=typer.Option(...,'--input'),
                   base_dir:Path|None=typer.Option(None,'--base-dir'),
                   experimental:bool=typer.Option(False,'--experimental'),
                   approve_input:str|None=typer.Option(None,'--approve-input'),
                   max_usd:str=typer.Option('0.20','--max-usd'),
                   confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                   check_only:bool=typer.Option(False,'--check-only'),
                   as_json:bool=typer.Option(False,'--json')):
    """Run the frozen three-window Flash 1017 reading, binding and TypeSafe correction plan."""
    from ... import attachment_trial as trial
    try:
        result=trial.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,max_usd=max_usd,
            confirm_prices=confirm_prices,check_only=check_only,progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('guided-source-prepare')
def guided_source_prepare(prior_input:Path=typer.Option(...,'--from-input'),
                          base_dir:Path|None=typer.Option(None,'--base-dir'),
                          check_only:bool=typer.Option(False,'--check-only'),
                          as_json:bool=typer.Option(False,'--json')):
    """Prepare a guided reading or one saved-answer binding/semantic correction."""
    from ... import guided_source_check as check
    try:
        packet,out=check.prepare(prior_input,base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],
            execute_command=check.command(out,packet,base_dir),metadata_requests=1,generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('guided-source-run')
def guided_source_run(input_path:Path=typer.Option(...,'--input'),
                      base_dir:Path|None=typer.Option(None,'--base-dir'),
                      experimental:bool=typer.Option(False,'--experimental'),
                      approve_input:str|None=typer.Option(None,'--approve-input'),
                      max_usd:str=typer.Option('0.02','--max-usd'),
                      confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                      check_only:bool=typer.Option(False,'--check-only'),
                      as_json:bool=typer.Option(False,'--json')):
    """Execute the frozen guided response and conditional TypeSafe check; no further retry."""
    from ... import guided_source_check as check
    try:
        result=check.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,
            max_usd=max_usd,confirm_prices=confirm_prices,check_only=check_only,
            progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('deepinfra-enum-prepare')
def deepinfra_enum_prepare(prior_input:Path=typer.Option(...,'--from-input'),
                          base_dir:Path|None=typer.Option(None,'--base-dir'),
                          check_only:bool=typer.Option(False,'--check-only'),
                          as_json:bool=typer.Option(False,'--json')):
    """Prepare one synthetic nested adoption-field check; no inference."""
    from ... import source_enum_check as check
    try:
        packet,out=check.prepare(prior_input,base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],
            execute_command=check.command(out,packet,base_dir),metadata_requests=1,generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('deepinfra-enum-run')
def deepinfra_enum_run(input_path:Path=typer.Option(...,'--input'),
                      base_dir:Path|None=typer.Option(None,'--base-dir'),
                      experimental:bool=typer.Option(False,'--experimental'),
                      approve_input:str|None=typer.Option(None,'--approve-input'),
                      max_usd:str=typer.Option('0.003','--max-usd'),
                      confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                      check_only:bool=typer.Option(False,'--check-only'),
                      as_json:bool=typer.Option(False,'--json')):
    """Execute one frozen synthetic request; no source extraction, verifier or retry."""
    from ... import source_enum_check as check
    try:
        result=check.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,
            max_usd=max_usd,confirm_prices=confirm_prices,check_only=check_only,
            progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('source-context-contract')
def source_context_contract(base_dir:Path|None=typer.Option(None,'--base-dir'),
                            as_json:bool=typer.Option(False,'--json')):
    """Export the versioned abstention, condition-attachment and context contract offline."""
    from ... import source_context
    try: emit(source_context.export(base_dir),as_json)
    except (ValueError,OSError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('condition-contract-check')
def condition_contract_check(base_dir:Path|None=typer.Option(None,'--base-dir'),
                             as_json:bool=typer.Option(False,'--json')):
    """Check condition/qualification attachment with synthetic inputs offline; no model calls."""
    from ... import condition_contract_check as check
    try:
        result=check.export(base_dir);emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('condition-model-prepare')
def condition_model_prepare(base_dir:Path|None=typer.Option(None,'--base-dir'),
                            check_only:bool=typer.Option(False,'--check-only'),
                            as_json:bool=typer.Option(False,'--json')):
    """Freeze five synthetic attachment cases and a two-call budget; no inference."""
    from ... import condition_model_check as check
    try:
        packet,root=check.prepare(base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(root/'input.json'),input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],
            generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('condition-model-run')
def condition_model_run(input_path:Path=typer.Option(...,'--input'),
                        base_dir:Path|None=typer.Option(None,'--base-dir'),
                        experimental:bool=typer.Option(False,'--experimental'),
                        approve_input:str|None=typer.Option(None,'--approve-input'),
                        max_usd:str=typer.Option('0.02','--max-usd'),
                        confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                        check_only:bool=typer.Option(False,'--check-only'),
                        as_json:bool=typer.Option(False,'--json')):
    """Run one frozen synthetic Flash check and conditional TypeSafe assessment; no retries."""
    from ... import condition_model_check as check
    try:
        result=check.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,max_usd=max_usd,
            confirm_prices=confirm_prices,check_only=check_only,progress=lambda text:typer.echo(text,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('source-context-prepare')
def source_context_prepare(prior_input:Path=typer.Option(...,'--from-input'),
                           base_dir:Path|None=typer.Option(None,'--base-dir'),
                           check_only:bool=typer.Option(False,'--check-only'),
                           as_json:bool=typer.Option(False,'--json')):
    """Freeze the existing five windows under the abstention/context contract."""
    from ... import source_context_trial as trial
    try:
        packet,out=trial.prepare(prior_input,base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],
            execute_command=trial.command(out,packet,base_dir),metadata_requests=1,generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('source-context-run')
def source_context_run(input_path:Path=typer.Option(...,'--input'),
                       base_dir:Path|None=typer.Option(None,'--base-dir'),
                       experimental:bool=typer.Option(False,'--experimental'),
                       approve_input:str|None=typer.Option(None,'--approve-input'),
                       max_usd:str=typer.Option('1.02','--max-usd'),
                       confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                       check_only:bool=typer.Option(False,'--check-only'),
                       as_json:bool=typer.Option(False,'--json')):
    """Run the frozen context check with bounded binding and TypeSafe correction."""
    from ... import source_context_trial as trial
    try:
        result=trial.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,
            max_usd=max_usd,confirm_prices=confirm_prices,check_only=check_only,
            progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('remaining-five-prepare')
def remaining_five_prepare(prior_input:Path=typer.Option(...,'--from-input'),
                           base_dir:Path|None=typer.Option(None,'--base-dir'),
                           check_only:bool=typer.Option(False,'--check-only'),
                           as_json:bool=typer.Option(False,'--json')):
    """Freeze the five remaining windows with the TypeSafe uncertainty loop."""
    from ... import learning_demo_five_windows as five
    try:
        packet,out=five.prepare(prior_input,base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],
            selection=packet['selection'],metadata_requests=1,generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('remaining-five-run')
def remaining_five_run(input_path:Path=typer.Option(...,'--input'),
                       base_dir:Path|None=typer.Option(None,'--base-dir'),
                       experimental:bool=typer.Option(False,'--experimental'),
                       approve_input:str|None=typer.Option(None,'--approve-input'),
                       max_usd:str|None=typer.Option(None,'--max-usd',help='Ceiling from the frozen packet when omitted.'),
                       confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                       check_only:bool=typer.Option(False,'--check-only'),
                       as_json:bool=typer.Option(False,'--json')):
    """Execute fixed five-window validation, with at most one re-review each."""
    from ... import learning_demo_five_windows as five
    try:
        result=five.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,
            max_usd=max_usd,confirm_prices=confirm_prices,check_only=check_only,
            progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('uncertainty-prepare')
def uncertainty_prepare(prior_input:Path=typer.Option(...,'--from-input'),
                        base_dir:Path|None=typer.Option(None,'--base-dir'),
                        check_only:bool=typer.Option(False,'--check-only'),
                        as_json:bool=typer.Option(False,'--json')):
    """Prepare one Flash re-review from saved uncertainty and an unchanged recheck."""
    from ... import learning_demo_uncertainty as review
    try:
        packet,out=review.prepare(prior_input,base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],
            metadata_requests=1,generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('uncertainty-run')
def uncertainty_run(input_path:Path=typer.Option(...,'--input'),
                    base_dir:Path|None=typer.Option(None,'--base-dir'),
                    experimental:bool=typer.Option(False,'--experimental'),
                    approve_input:str|None=typer.Option(None,'--approve-input'),
                    max_usd:str=typer.Option('0.06','--max-usd'),
                    confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                    check_only:bool=typer.Option(False,'--check-only'),
                    as_json:bool=typer.Option(False,'--json')):
    """Execute one uncertainty-guided re-review and one fixed verifier recheck."""
    from ... import learning_demo_uncertainty as review
    try:
        result=review.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,
            max_usd=max_usd,confirm_prices=confirm_prices,check_only=check_only,
            progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('field-check-prepare')
def field_check_prepare(prior_input:Path=typer.Option(...,'--from-input'),
                        base_dir:Path|None=typer.Option(None,'--base-dir'),
                        check_only:bool=typer.Option(False,'--check-only'),
                        as_json:bool=typer.Option(False,'--json')):
    """Prepare one verifier request with explicit fields and literal passages."""
    from ... import learning_demo_field_check as check
    try:
        packet,out=check.prepare(prior_input,base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],
            provider_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('field-check-run')
def field_check_run(input_path:Path=typer.Option(...,'--input'),
                    base_dir:Path|None=typer.Option(None,'--base-dir'),
                    experimental:bool=typer.Option(False,'--experimental'),
                    approve_input:str|None=typer.Option(None,'--approve-input'),
                    max_usd:str=typer.Option('0.003','--max-usd'),
                    confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                    check_only:bool=typer.Option(False,'--check-only'),
                    as_json:bool=typer.Option(False,'--json')):
    """Execute one frozen TypeSafe presentation check; no correction or retry."""
    from ... import learning_demo_field_check as check
    try:
        result=check.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,
            max_usd=max_usd,confirm_prices=confirm_prices,check_only=check_only,
            progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('feedback-prepare')
def feedback_prepare(prior_input:Path=typer.Option(...,'--from-input'),
                     base_dir:Path|None=typer.Option(None,'--base-dir'),
                     check_only:bool=typer.Option(False,'--check-only'),
                     as_json:bool=typer.Option(False,'--json')):
    """Freeze TypeSafe check, one Flash correction, and TypeSafe recheck."""
    from ... import learning_demo_feedback as feedback
    try:
        packet,out=feedback.prepare(prior_input,base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],
            metadata_requests=1,generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('feedback-run')
def feedback_run(input_path:Path=typer.Option(...,'--input'),
                 base_dir:Path|None=typer.Option(None,'--base-dir'),
                 experimental:bool=typer.Option(False,'--experimental'),
                 approve_input:str|None=typer.Option(None,'--approve-input'),
                 max_usd:str=typer.Option('0.10','--max-usd'),
                 confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                 check_only:bool=typer.Option(False,'--check-only'),
                 as_json:bool=typer.Option(False,'--json')):
    """Execute at most two TypeSafe checks and one Flash correction."""
    from ... import learning_demo_feedback as feedback
    try:
        result=feedback.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,
            max_usd=max_usd,confirm_prices=confirm_prices,check_only=check_only,
            progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('corrective-prepare')
def corrective_prepare(prior_input:Path=typer.Option(...,'--from-input'),
                       base_dir:Path|None=typer.Option(None,'--base-dir'),
                       check_only:bool=typer.Option(False,'--check-only'),
                       as_json:bool=typer.Option(False,'--json')):
    """Freeze Flash 1017 with at most one schema/binding correction; no inference."""
    from ... import learning_demo_correction as correction
    try:
        packet,out=correction.prepare(prior_input,base_dir,check_only=check_only)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],
            model=packet['request']['body']['model'],budget=packet['budget'],
            metadata_requests=1,generation_calls=0,paid_calls=0),as_json)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('corrective-run')
def corrective_run(input_path:Path=typer.Option(...,'--input'),
                   base_dir:Path|None=typer.Option(None,'--base-dir'),
                   experimental:bool=typer.Option(False,'--experimental'),
                   approve_input:str|None=typer.Option(None,'--approve-input'),
                   max_usd:str=typer.Option('0.10','--max-usd'),
                   confirm_prices:bool=typer.Option(False,'--confirm-prices'),
                   check_only:bool=typer.Option(False,'--check-only'),
                   as_json:bool=typer.Option(False,'--json')):
    """Run the frozen initial request and at most one validation correction."""
    from ... import learning_demo_correction as correction
    try:
        result=correction.run(input_path,base_dir,experimental=experimental,approve_input=approve_input,
            max_usd=max_usd,confirm_prices=confirm_prices,check_only=check_only,
            progress=lambda message:typer.echo(message,err=True))
        emit(result,as_json)
        if result['status']=='FAIL(component)': raise typer.Exit(1)
    except (ValueError,OSError,KeyError,HTTPError) as error: raise typer.BadParameter(str(error)) from error


@fit_app.command('deepinfra-prepare')
def deepinfra_prepare(prior_input:Path=typer.Option(...,'--from-input'),
                     base_dir:Path|None=typer.Option(None,'--base-dir'),
                     expanded_output:bool=typer.Option(False,'--expanded-output',help='Prepare one generous-output request after the reviewed hosted length stop.'),
                     no_reasoning:bool=typer.Option(False,'--no-reasoning',help='Prepare the user-selected Flash 1017 check with reasoning disabled.'),
                     check_only:bool=typer.Option(False,'--check-only'),
                     as_json:bool=typer.Option(False,'--json')):
    """Prepare one hosted DeepSeek source check without provider calls."""
    from ... import learning_demo_deepinfra_fit as hosted
    try:
        packet,out=hosted.prepare(prior_input,base_dir,check_only=check_only,expanded_output=expanded_output,no_reasoning=no_reasoning)
        emit(dict(status='CHECKED_NO_WRITES' if check_only else 'FROZEN_NO_EXECUTION',
            input=str(out/'input.json'),input_fingerprint=packet['input_fingerprint'],
            model=packet['request']['body']['model'],reasoning_effort=packet['request']['body']['reasoning_effort'],
            budget=packet['budget'],provider_calls=int(expanded_output or no_reasoning),
            metadata_requests=int(expanded_output or no_reasoning),generation_calls=0,paid_calls=0,
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
