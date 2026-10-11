"""Render the registered CLI tree as a deterministic Markdown reference."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from typer.core import TyperArgument

from pastor_transcript_extractor.commands.apps import docs_app


def _usage(command: Any, context: typer.Context) -> str:
    """Return Click's usage metadata without its display-only prefix."""
    return command.get_usage(context).removeprefix("Usage: ").strip()


def _default(parameter: Any, context: typer.Context) -> str:
    """Format an explicit Click default, if one is available."""
    value = parameter.get_default(context, call=False)
    if value is None:
        return "—"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) or "—"
    return str(value)


def _parameter_rows(command: Any, context: typer.Context, *, arguments: bool) -> list[str]:
    rows: list[str] = []
    for parameter in command.get_params(context):
        is_argument = isinstance(parameter, TyperArgument)
        if is_argument != arguments:
            continue
        help_record = parameter.get_help_record(context)
        if help_record is None:
            continue
        name, description = help_record
        required = "yes" if parameter.required else "no"
        description = description or "—"
        rows.append(
            f"| `{name}` | {description} | {required} | {_default(parameter, context)} |"
        )
    return rows


def _render_command(
    command: Any,
    *,
    path: tuple[str, ...],
    parent_context: typer.Context | None,
    lines: list[str],
) -> None:
    # A fixed wide formatter prevents terminal width from changing generated usage.
    context = typer.Context(
        command,
        info_name=path[-1],
        parent=parent_context,
        terminal_width=10_000,
    )
    lines.extend((f"{'#' * len(path)} `{ ' '.join(path) }`", ""))
    description = command.help or command.short_help
    if description:
        lines.extend((description.strip(), ""))
    section_heading = "#" * (len(path) + 1)
    lines.extend(
        (f"{section_heading} Usage", "", "```console", _usage(command, context), "```", "")
    )

    for title, arguments in (("Arguments", True), ("Options", False)):
        rows = _parameter_rows(command, context, arguments=arguments)
        if rows:
            lines.extend(
                (
                    f"{section_heading} {title}",
                    "",
                    "| Name | Description | Required | Default |",
                    "| --- | --- | --- | --- |",
                    *rows,
                    "",
                )
            )

    commands = getattr(command, "commands", None)
    if commands:
        for name, child in commands.items():
            _render_command(
                child,
                path=(*path, name),
                parent_context=context,
                lines=lines,
            )


def render_cli_reference(command: Any, *, program_name: str = "pte") -> str:
    """Render a complete, ordered CLI reference from Click command metadata."""
    lines = [
        "# PTE CLI Reference",
        "",
        "This file is generated from the registered CLI and its help metadata.",
        "Regenerate it with `pte docs cli --output docs/CLI_REFERENCE.md`.",
        "",
    ]
    _render_command(command, path=(program_name,), parent_context=None, lines=lines)
    return "\n".join(lines).rstrip() + "\n"


@docs_app.command("cli", help="Generate a consolidated Markdown reference for the complete CLI.")
def generate_cli_reference(
    context: typer.Context,
    output: Path = typer.Option(
        Path("docs/CLI_REFERENCE.md"),
        "--output",
        "-o",
        help="Destination Markdown file.",
    ),
) -> None:
    """Write reference documentation using the active root command tree."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_cli_reference(context.find_root().command),
        encoding="utf-8",
    )
    typer.echo(f"Wrote CLI reference to {output}")
