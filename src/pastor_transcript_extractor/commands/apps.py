from __future__ import annotations

from dataclasses import dataclass

import typer


root_app = typer.Typer(help="Pastor Transcript Extractor CLI")
pastor_app = typer.Typer(help="Manage pastors.")
organization_app = typer.Typer(help="Manage publishing organizations.")
source_app = typer.Typer(help="Manage queued sources.")
video_app = typer.Typer(help="Manage discovered videos.")
identity_app = typer.Typer(help="Manage speaker identity shadow artifacts.")
media_app = typer.Typer(help="Manage transcript-independent local media artifacts.")
analysis_app = typer.Typer(help="Analyze already-identified sermon content.")
source_ownership_app = typer.Typer(help="Migrate and audit source ownership data.")
benchmark_app = typer.Typer(help="Manage reviewed profile reference panels.")


@dataclass(frozen=True, slots=True)
class CommandGroup:
    name: str
    app: typer.Typer


COMMAND_GROUPS = (
    CommandGroup("pastor", pastor_app),
    CommandGroup("organization", organization_app),
    CommandGroup("source", source_app),
    CommandGroup("video", video_app),
    CommandGroup("identity", identity_app),
    CommandGroup("media", media_app),
    CommandGroup("analysis", analysis_app),
    CommandGroup("source-ownership", source_ownership_app),
    CommandGroup("benchmark", benchmark_app),
)


def attach_command_groups(root: typer.Typer) -> None:
    """Attach every public command group to the root CLI in display order."""
    for group in COMMAND_GROUPS:
        root.add_typer(group.app, name=group.name)
