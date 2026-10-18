"""Extend the existing design CLI without editing frozen experiment adapters."""
from __future__ import annotations
import typer
from rich.console import Console
from pastor_transcript_extractor.commands.apps import analysis_app
from pastor_transcript_extractor.commands.analysis import content


@analysis_app.command('collector-retrieval-design',help='Verify original retrieval design or the design-only context/extraction replacement proposal.')
def collector_retrieval_design(
    check_only: bool=typer.Option(False,'--check-only',help='Read-only proposal/baseline verification.'),
    context_extraction_proposal: bool=typer.Option(False,'--context-extraction-proposal',help='Verify the replacement proposal; never materialize contexts, load models or run inference.'),
):
    if not context_extraction_proposal:
        return content.analysis_collector_retrieval_design(check_only)
    from pastor_transcript_extractor import context_evidence_architecture_design as design
    try:
        _,_,packet=design.verify()
    except (ValueError,OSError,KeyError) as error:
        raise typer.BadParameter(str(error)) from error
    Console().print(f"Context/extraction architecture: PROPOSAL_ONLY; implementation/execution HELD; provider_requests=0; fingerprint={packet['content_fingerprint']}",markup=False)
    Console().print(str(design.HERE/'PROPOSAL.md'),markup=False)
