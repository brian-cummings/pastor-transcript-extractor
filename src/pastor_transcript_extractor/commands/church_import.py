from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pastor_transcript_extractor.church_database_import import (
    ChurchDatabaseImportError,
    import_church_sources,
)
from pastor_transcript_extractor.commands.apps import root_app
from pastor_transcript_extractor.commands.common import get_database


console = Console()


@root_app.command(
    "import-church-db",
    help=(
        "Import complete pastor/channel pairs from church-youtube-finder "
        "with stable provenance."
    ),
)
def import_church_db(
    church_database: Path = typer.Argument(
        ...,
        help="Path to the church-youtube-finder SQLite database.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report changes without importing records.",
    ),
    show_all: bool = typer.Option(
        False,
        help="Show unchanged records in addition to changes and conflicts.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    database = get_database(base_dir)
    try:
        result = import_church_sources(
            database,
            church_database.expanduser().resolve(),
            dry_run=dry_run,
        )
    except (ChurchDatabaseImportError, OSError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error

    table = Table(title="Church database import" + (" (dry run)" if dry_run else ""))
    table.add_column("Status")
    table.add_column("Church")
    table.add_column("Pastor")
    table.add_column("Source")
    table.add_column("Reason")
    for item in result.items:
        if item.status == "unchanged" and not show_all:
            continue
        table.add_row(
            item.status,
            item.record.church_name,
            item.record.pastor_name,
            item.record.channel_url,
            item.reason,
        )
    console.print(table)
    counts = ", ".join(
        f"{status}={count}" for status, count in sorted(result.counts.items())
    )
    console.print(f"Church import complete: {counts or 'no complete records'}.")
