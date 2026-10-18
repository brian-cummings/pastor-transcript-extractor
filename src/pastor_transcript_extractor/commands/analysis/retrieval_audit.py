"""Add read-only audit mode while preserving the fingerprint-pinned run adapter.

The existing command name/options delegate to its immutable implementation.
This last registration extends its CLI without editing frozen content.py bytes.
"""
from pathlib import Path
import typer
from rich.console import Console
from pastor_transcript_extractor.commands.apps import analysis_app
from pastor_transcript_extractor.commands.analysis import content


@analysis_app.command('collector-retrieval-repair',help='Verify/preflight/run the frozen V1.1 packet or verify its sealed source audit without inference.')
def collector_retrieval_repair(
    check_only: bool=typer.Option(False,'--check-only',help='Verify the frozen implementation snapshot.'),
    preflight: bool=typer.Option(False,'--preflight',help='Frozen source/resource preflight only.'),
    run_development: bool=typer.Option(False,'--run-development',help='Delegate to the exact separately authorized frozen execution.'),
    approve_input: str|None=typer.Option(None,'--approve-input',help='Exact execution input fingerprint.'),
    base_dir: Path|None=typer.Option(None,'--base-dir',help='Configured application data directory.'),
    verify_audit: bool=typer.Option(False,'--verify-audit',help='Verify sealed V1.1 results, trace, source audit and original byte bindings; no encoder.'),
):
    if not verify_audit:
        return content.analysis_collector_retrieval_repair(check_only,preflight,run_development,approve_input,base_dir)
    if any((check_only,preflight,run_development,approve_input)):
        raise typer.BadParameter('Audit verification cannot be combined with another mode')
    from pastor_transcript_extractor import collector_retrieval_audit_v1_1 as audit
    try:
        review=audit.verify(base_dir)
    except (ValueError,OSError,KeyError) as error:
        raise typer.BadParameter(str(error)) from error
    Console().print(f"V1.1 source audit: {review['recommendation']}; G1 HOLD; provider_requests=0; fingerprint={review['content_fingerprint']}",markup=False)
    Console().print(str(audit.HERE/'DEVELOPMENT-SOURCE-AUDIT.md'),markup=False)
