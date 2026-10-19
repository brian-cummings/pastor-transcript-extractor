"""Bounded probe CLI extension; all historical command callbacks remain intact."""
from pathlib import Path
import typer
from rich.console import Console
from pastor_transcript_extractor.commands.apps import analysis_app
from pastor_transcript_extractor.commands.analysis import context_design


@analysis_app.command('collector-retrieval-design',help='Verify historical design or the retired Context Extraction V1 archive; prepare/run are superseded.')
def collector_retrieval_design(
    check_only: bool=typer.Option(False,'--check-only',help='Read-only document/request/source verification.'),
    context_extraction_proposal: bool=typer.Option(False,'--context-extraction-proposal',help='Verify design-only architecture packet.'),
    context_extraction_probe: bool=typer.Option(False,'--context-extraction-probe',help='Use the bounded nomination-feasibility probe, not the retired collector.'),
    prepare: bool=typer.Option(False,'--prepare',help='Retired probe option; no longer permitted.'),
    run: bool=typer.Option(False,'--run',help='Retired probe option; no longer permitted.'),
    approve_input: str|None=typer.Option(None,'--approve-input',help='Exact probe fingerprint; does not grant authorization.'),
    base_dir: Path|None=typer.Option(None,'--base-dir',help='Application base for isolated tokenizer runtime, prepared artifacts and receipts.'),
):
    if not context_extraction_probe:
        if any((prepare,run,approve_input,base_dir)):raise typer.BadParameter('Probe options require --context-extraction-probe')
        return context_design.collector_retrieval_design(check_only,context_extraction_proposal)
    if context_extraction_proposal or sum((check_only,prepare,run))>1 or bool(approve_input)!=bool(run):
        raise typer.BadParameter('Choose one probe mode; execution needs its exact fingerprint and separate authorization')
    from pastor_transcript_extractor import evidence_probe_retirement as retired
    try:
        retired.closure()
        if prepare or run:
            raise ValueError('RETIRED: Context Extraction V1 is SUPERSEDED_UNEXECUTED; prepare/run are blocked. See minute-evidence-handoff-v1/PROPOSAL.md')
        result = retired.verify(base_dir)
        Console().print(f"Retired probe: {result['status']}; read-only frozen Git snapshot verified; provider_requests=0; input={result['input_fingerprint']}", markup=False)
    except (ValueError,OSError,KeyError) as error:
        raise typer.BadParameter(str(error)) from error
