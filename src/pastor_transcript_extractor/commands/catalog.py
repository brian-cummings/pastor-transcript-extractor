from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import shutil
import sqlite3

import typer
from rich.console import Console
from rich.table import Table

from pastor_transcript_extractor.artifact_namespace import resolve_video_artifact_paths
from pastor_transcript_extractor.commands.apps import (
    organization_app,
    pastor_app,
    root_app,
    source_ownership_app,
    source_app,
    video_app,
)
from pastor_transcript_extractor.commands.common import get_database, unknown_pastor_error
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.exporting import export_organization_review_markdown
from pastor_transcript_extractor.models import VideoStatus
from pastor_transcript_extractor.source_processing_report import (
    generate_source_processing_report,
)
from pastor_transcript_extractor.sources import UnsupportedSourceError, detect_source_type
from pastor_transcript_extractor.source_ownership import (
    apply_source_ownership_schema,
    audit_source_ownership,
    backfill_source_ownership,
)
from pastor_transcript_extractor.storage import Database


console = Console()


@root_app.command(help="Initialize the app data directory and SQLite database.")
def init(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir, remember=True)
    ensure_directories(paths)
    database = Database(paths.database)
    database.initialize()
    console.print(f"Initialized app data at [bold]{paths.root}[/bold]")


@source_ownership_app.command(
    "migrate",
    help="Apply or preview the replayable source-ownership migration.",
)
def source_ownership_migrate(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Run the migration and audit inside a rolled-back savepoint.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir, remember=True)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Database does not exist: {paths.database}. Run 'pte init' first."
        )
    database = Database(paths.database)
    with database.connect() as connection:
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sources'"
        ).fetchone() is None:
            raise typer.BadParameter(
                "Database is not initialized; run 'pte init' first."
            )
        if dry_run:
            connection.execute("SAVEPOINT source_ownership_preview")
        try:
            apply_source_ownership_schema(connection)
            result = backfill_source_ownership(connection)
            report = audit_source_ownership(connection, app_root=paths.root)
        finally:
            if dry_run:
                connection.execute("ROLLBACK TO source_ownership_preview")
                connection.execute("RELEASE source_ownership_preview")
    mode = "preview" if dry_run else "applied"
    console.print(
        f"Source ownership migration {mode}: "
        f"organizations={result.organizations_created}, "
        f"snapshots={result.snapshots_created}, "
        f"claims={result.affiliation_claims_created}, "
        f"source_targets={result.source_target_policies_created}, "
        f"video_targets={result.video_target_contexts_created}, "
        f"artifact_namespaces={result.artifact_namespaces_created}."
    )
    console.print(
        "Projected audit passed." if report.ok else "Projected audit failed."
    )
    if not report.ok:
        raise typer.Exit(code=1)

@source_ownership_app.command(
    "audit",
    help="Validate organization, target-context, and artifact-namespace projections.",
)
def source_ownership_audit(
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit unsuccessfully when any ownership invariant fails.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    with database.connect() as connection:
        report = audit_source_ownership(connection, app_root=paths.root)
    values = {
        "Foreign-key violations": report.foreign_key_violations,
        "Legacy imports without external refs": report.imported_refs_without_external_ref,
        "Imported links without organization": report.imported_links_without_organization,
        "Legacy sources without target policy": report.legacy_sources_without_target_policy,
        "Legacy videos without target context": report.legacy_videos_without_target_context,
        "Videos without artifact namespace": report.videos_without_artifact_namespace,
        "Artifact namespace path mismatches": report.artifact_namespace_path_mismatches,
    }
    table = Table(title="Source ownership audit")
    table.add_column("Invariant")
    table.add_column("Failures", justify="right")
    for label, value in values.items():
        table.add_row(label, str(value))
    console.print(table)
    console.print(
        "Source ownership audit passed."
        if report.ok
        else "Source ownership audit failed."
    )
    if strict and not report.ok:
        raise typer.Exit(code=1)


def add_source_service(
    url: str,
    pastor: str | None,
    notes: str | None = None,
    base_dir: Path | None = None,
    organization: str | None = None,
) -> None:
    database = get_database(base_dir)
    try:
        source_type = detect_source_type(url)
    except UnsupportedSourceError as error:
        raise ValueError(str(error)) from error

    pastor_record = database.get_pastor_by_slug(pastor) if pastor is not None else None
    if pastor is not None and pastor_record is None:
        raise ValueError(
            f"Unknown pastor slug: {pastor} (app root: {build_paths(base_dir).root})"
        )
    organization_record = (
        database.get_organization_by_slug(organization)
        if organization is not None
        else None
    )
    if organization is not None and organization_record is None:
        raise ValueError(f"Unknown organization slug: {organization}")

    source = database.add_source(
        url=url,
        source_type=source_type,
        pastor_id=pastor_record.id if pastor_record is not None else None,
        organization_id=(
            organization_record.id if organization_record is not None else None
        ),
        notes=notes,
    )
    if organization_record is not None:
        if (
            source.organization_id is not None
            and source.organization_id != organization_record.id
        ):
            current = database.get_organization_by_id(source.organization_id)
            current_label = current.slug if current is not None else source.organization_id
            raise ValueError(
                f"Source #{source.id} is already attached to organization "
                f"{current_label}; use 'pte source set-organization' to correct it"
            )
        database.set_source_organization(
            source.id,
            organization_record.id,
            actor="manual",
            reason="Organization selected while adding source",
            event_key=f"source-add:{source.id}:{organization_record.id}",
        )
        source = database.get_source_by_id(source.id) or source
    context = []
    if organization_record is not None:
        context.append(f"organization: {organization_record.slug}")
    if pastor_record is not None:
        context.append(f"target pastor: {pastor_record.slug}")
    suffix = f" ({', '.join(context)})" if context else " (organization unknown)"
    console.print(
        f"Added source #{source.id}: {source.source_type.value} -> {source.url}{suffix}"
    )


@root_app.command(help="Add a YouTube video, playlist, or channel source for a pastor.")
def add(
    url: str = typer.Argument(..., help="YouTube video, playlist, or channel URL."),
    pastor: str = typer.Option(..., help="Pastor slug to associate with this source."),
    notes: str | None = typer.Option(None, help="Optional notes for this source."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        add_source_service(url, pastor, notes, base_dir)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


@source_app.command(
    "add",
    help="Add a source with an optional publisher and optional target pastor.",
)
def source_add(
    url: str = typer.Argument(..., help="YouTube video, playlist, or channel URL."),
    organization: str | None = typer.Option(
        None,
        help="Publishing organization slug; omit when unknown.",
    ),
    target_pastor: str | None = typer.Option(
        None,
        "--target-pastor",
        help="Optional pastor query target; this is not source ownership.",
    ),
    notes: str | None = typer.Option(None, help="Optional source notes."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        add_source_service(
            url,
            target_pastor,
            notes,
            base_dir,
            organization=organization,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


@source_app.command(
    "set-organization",
    help="Attach or correct a source's current publishing organization.",
)
def source_set_organization(
    source_id: int = typer.Argument(..., help="Source id to update."),
    organization: str = typer.Argument(..., help="Publishing organization slug."),
    reason: str = typer.Option(
        "Manual publisher correction",
        help="Audit reason for the association.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    organization_record = database.get_organization_by_slug(organization)
    if organization_record is None:
        raise typer.BadParameter(f"Unknown organization slug: {organization}")
    try:
        database.set_source_organization(
            source_id,
            organization_record.id,
            actor="manual",
            reason=reason,
            event_key=f"manual-attach:{source_id}:{organization_record.id}:{reason}",
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Attached source #{source_id} to organization {organization_record.slug}."
    )


@source_app.command(
    "clear-organization",
    help="Mark a source's current publishing organization as unknown.",
)
def source_clear_organization(
    source_id: int = typer.Argument(..., help="Source id to update."),
    reason: str = typer.Option(
        "Manual publisher correction",
        help="Audit reason for clearing the association.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        database.set_source_organization(
            source_id,
            None,
            actor="manual",
            reason=reason,
            event_key=f"manual-detach:{source_id}:{reason}",
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"Cleared the publishing organization for source #{source_id}.")


def _set_source_processing_enabled(
    source_id: int,
    enabled: bool,
    base_dir: Path | None,
) -> None:
    database = get_database(base_dir)
    try:
        source = database.set_source_processing_enabled(source_id, enabled)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    state = "enabled" if enabled else "disabled"
    scope = "included in" if enabled else "excluded from"
    console.print(
        f"Source #{source.id} is {state} and will be {scope} all-source processing: "
        f"{source.url}"
    )


@source_app.command(
    "disable",
    help="Exclude a source from all-source processing such as `pte run --all`.",
)
def source_disable(
    source_id: int = typer.Argument(..., help="Source id to disable."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    _set_source_processing_enabled(source_id, False, base_dir)


@source_app.command(
    "enable",
    help="Include a source in all-source processing such as `pte run --all`.",
)
def source_enable(
    source_id: int = typer.Argument(..., help="Source id to enable."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    _set_source_processing_enabled(source_id, True, base_dir)


@root_app.command(help="Show database counts and queued sources.")
def status(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    counts = database.counts_by_table()
    sources = database.list_sources()

    summary = Table(title="Pastor Transcript Extractor")
    summary.add_column("Metric")
    summary.add_column("Value", justify="right")
    summary.add_row("Organizations", str(counts["organizations"]))
    summary.add_row(
        "Imported Affiliation Claims",
        str(counts["organization_affiliation_claims"]),
    )
    summary.add_row(
        "Pastor Affiliations",
        str(counts["pastor_organization_affiliations"]),
    )
    summary.add_row(
        "Affiliation Claim Reviews",
        str(counts["affiliation_claim_review_events"]),
    )
    summary.add_row("Sources", str(counts["sources"]))
    summary.add_row(
        "Processing-enabled Sources",
        str(sum(source.processing_enabled for source in sources)),
    )
    summary.add_row(
        "Processing-disabled Sources",
        str(sum(not source.processing_enabled for source in sources)),
    )
    summary.add_row("Imported Source References", str(counts["source_import_refs"]))
    summary.add_row("Pastors", str(counts["pastors"]))
    summary.add_row("Videos", str(counts["videos"]))
    summary.add_row("Transcripts", str(counts["transcript_artifacts"]))
    summary.add_row("Media Artifacts", str(counts["media_artifacts"]))
    summary.add_row("Media Acquisition Attempts", str(counts["media_acquisition_attempts"]))
    summary.add_row("Media Archive Entries", str(counts["media_archive_entries"]))
    summary.add_row("Media Archive Attempts", str(counts["media_archive_attempts"]))
    summary.add_row("Segments", str(counts["transcript_segments"]))
    summary.add_row("Extraction", str(counts["extraction_results"]))
    summary.add_row("Metadata Snapshots", str(counts["metadata_artifacts"]))
    summary.add_row("Identity Evidence", str(counts["identity_evidence"]))
    summary.add_row("Identity Assessments", str(counts["identity_assessments"]))
    summary.add_row("Speaker Profiles", str(counts["speaker_profiles"]))
    summary.add_row("Speaker Observations", str(counts["speaker_observations"]))
    summary.add_row("Speaker Name Claims", str(counts["speaker_name_claims"]))
    summary.add_row("Excluded", str(counts["excluded_videos"]))
    console.print(summary)

    if not sources:
        console.print("No sources queued.")
        return

    table = Table(title="Queued Sources")
    table.add_column("ID", justify="right")
    table.add_column("Organization")
    table.add_column("Target Pastor")
    table.add_column("Type")
    table.add_column("Processing")
    table.add_column("URL")
    for source in sources:
        organization_name = "-"
        if source.organization_id is not None:
            organization_record = database.get_organization_by_id(
                source.organization_id
            )
            organization_name = (
                organization_record.slug
                if organization_record is not None
                else str(source.organization_id)
            )
        pastor_name = "-"
        if source.pastor_id is not None:
            pastor_record = database.get_pastor_by_id(source.pastor_id)
            if pastor_record is not None:
                pastor_name = pastor_record.slug
            else:
                pastor_name = str(source.pastor_id)
        table.add_row(
            str(source.id),
            organization_name,
            pastor_name,
            source.source_type.value,
            "enabled" if source.processing_enabled else "disabled",
            source.url,
        )
    console.print(table)


@root_app.command(
    "source-processing-report",
    help="Write read-only per-source processing reports as Markdown and JSON.",
)
def source_processing_report(
    database_path: Path | None = typer.Option(
        None,
        "--database",
        help="Explicit application database path; defaults to the configured app database.",
    ),
    markdown_path: Path = typer.Option(
        Path("source_processing_report.md"),
        "--markdown",
        help="Markdown report output path.",
    ),
    json_path: Path = typer.Option(
        Path("source_processing_report.json"),
        "--json",
        help="JSON report output path.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory when --database is not supplied.",
    ),
) -> None:
    if database_path is not None and base_dir is not None:
        raise typer.BadParameter("use either --database or --base-dir, not both")
    resolved_database = (
        database_path.expanduser().resolve()
        if database_path is not None
        else build_paths(base_dir).database
    )
    try:
        report = generate_source_processing_report(
            resolved_database,
            markdown_path=markdown_path,
            json_path=json_path,
        )
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        raise typer.BadParameter(str(error)) from error

    summary = report["summary"]
    console.print(f"Wrote Markdown report to {markdown_path.expanduser().resolve()}")
    console.print(f"Wrote JSON report to {json_path.expanduser().resolve()}")
    console.print(
        f"Reported {summary['total_sources']} source(s) and "
        f"{summary['total_cataloged_videos']} cataloged video(s)."
    )


@source_app.command("list", help="List configured sources and downloaded recording counts.")
def source_list(
    include_queued: bool = typer.Option(
        False,
        "--include-queued",
        help="Count queued catalog entries in addition to downloaded recordings.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    sources = database.list_sources()
    recording_counts = database.count_recordings_by_source(
        include_queued=include_queued
    )

    if not sources:
        console.print("No sources configured.")
        return

    table = Table(title="Sources")
    table.add_column("ID", justify="right")
    table.add_column("Organization")
    table.add_column("Target Pastor")
    table.add_column("Type")
    table.add_column("Processing")
    table.add_column("Recordings", justify="right")
    table.add_column("URL")
    for source in sources:
        organization_name = "-"
        if source.organization_id is not None:
            organization_record = database.get_organization_by_id(
                source.organization_id
            )
            organization_name = (
                organization_record.slug
                if organization_record is not None
                else str(source.organization_id)
            )
        pastor_name = "-"
        if source.pastor_id is not None:
            pastor_record = database.get_pastor_by_id(source.pastor_id)
            pastor_name = pastor_record.slug if pastor_record is not None else str(source.pastor_id)
        table.add_row(
            str(source.id),
            organization_name,
            pastor_name,
            source.source_type.value,
            "enabled" if source.processing_enabled else "disabled",
            str(recording_counts.get(source.id, 0)),
            source.url,
        )
    console.print(table)


@organization_app.command("add", help="Create a publishing organization.")
def organization_add(
    slug: str = typer.Argument(..., help="Stable organization slug."),
    display_name: str = typer.Argument(..., help="Human-readable organization name."),
    organization_type: str = typer.Option(
        "church",
        "--type",
        help="Organization type, such as church, conference, ministry, school, or network.",
    ),
    notes: str | None = typer.Option(None, help="Optional organization notes."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    organization = database.add_organization(
        slug=slug,
        display_name=display_name,
        organization_type=organization_type,
        notes=notes,
    )
    console.print(
        f"Added organization #{organization.id}: {organization.slug} -> "
        f"{organization.display_name} ({organization.organization_type})"
    )


@organization_app.command("list", help="List publishing organizations.")
def organization_list(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    organizations = database.list_organizations()
    if not organizations:
        console.print("No organizations configured.")
        return
    table = Table(title="Organizations")
    table.add_column("ID", justify="right")
    table.add_column("Slug")
    table.add_column("Type")
    table.add_column("Display Name")
    for organization in organizations:
        table.add_row(
            str(organization.id),
            organization.slug,
            organization.organization_type,
            organization.display_name,
        )
    console.print(table)

@organization_app.command(
    "review",
    help="Build a publisher-scoped review without asserting speaker identity.",
)
def organization_review(
    organization: str = typer.Argument(..., help="Organization slug."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    try:
        result = export_organization_review_markdown(
            database,
            paths,
            organization,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"Wrote organization review markdown to {result.export_path}")
    console.print(f"Wrote organization review manifest to {result.manifest_path}")
    console.print(
        f"Included {result.video_count} video(s); skipped {result.skipped_count}."
    )


@organization_app.command(
    "claims",
    help="List imported affiliation claims without linking people by name.",
)
def organization_claims(
    organization: str | None = typer.Option(
        None,
        help="Only show claims for one organization slug.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    organization_id = None
    if organization is not None:
        organization_record = database.get_organization_by_slug(organization)
        if organization_record is None:
            raise typer.BadParameter(f"Unknown organization slug: {organization}")
        organization_id = organization_record.id
    claims = database.list_organization_affiliation_claims(organization_id)
    if not claims:
        console.print("No affiliation claims matched.")
        return
    table = Table(title="Organization Affiliation Claims")
    table.add_column("ID", justify="right")
    table.add_column("Organization")
    table.add_column("Claimed Name")
    table.add_column("Role")
    table.add_column("Review")
    for claim in claims:
        table.add_row(
            str(claim["id"]),
            str(claim["organization_slug"]),
            str(claim["claimed_person_name"]),
            str(claim["claimed_role"]),
            str(claim["review_status"] or "unreviewed"),
        )
    console.print(table)


@organization_app.command(
    "reject-affiliation-claim",
    help="Append a reviewed rejection without creating or linking a person.",
)
def organization_reject_affiliation_claim(
    claim_id: int = typer.Argument(..., help="Affiliation claim id."),
    reviewer: str = typer.Option(..., help="Reviewer name."),
    reason: str = typer.Option(..., help="Reason for rejection."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        event_id = database.review_organization_affiliation_claim(
            claim_id=claim_id,
            pastor_id=None,
            attach=False,
            reviewer=reviewer,
            reason=reason,
            review_event_key=f"reject:{claim_id}:{reviewer}:{reason}",
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"Recorded affiliation claim rejection event #{event_id}.")


@pastor_app.command("add", help="Create a pastor profile and folder namespace.")
def pastor_add(
    slug: str = typer.Argument(..., help="Slug for this pastor, used in folder paths."),
    display_name: str = typer.Argument(..., help="Human-readable pastor name."),
    notes: str | None = typer.Option(None, help="Optional notes for this pastor."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    pastor = database.add_pastor(slug=slug, display_name=display_name, notes=notes)
    console.print(f"Added pastor #{pastor.id}: {pastor.slug} -> {pastor.display_name}")


@pastor_app.command("list", help="List configured pastors.")
def pastor_list(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    pastors = database.list_pastors()

    if not pastors:
        console.print("No pastors configured.")
        return

    table = Table(title="Pastors")
    table.add_column("ID", justify="right")
    table.add_column("Slug")
    table.add_column("Display Name")
    for pastor in pastors:
        table.add_row(str(pastor.id), pastor.slug, pastor.display_name)
    console.print(table)


@pastor_app.command(
    "affiliate",
    help="Record a reviewed or manually grounded organization affiliation.",
)
def pastor_affiliate(
    pastor: str = typer.Argument(..., help="Pastor slug."),
    organization: str = typer.Argument(..., help="Organization slug."),
    role: str = typer.Option("pastor", help="Role held at the organization."),
    started_on: str | None = typer.Option(
        None,
        "--from",
        help="Inclusive start date in YYYY-MM-DD format.",
    ),
    ended_on: str | None = typer.Option(
        None,
        "--to",
        help="Exclusive end date in YYYY-MM-DD format.",
    ),
    temporal_status: str | None = typer.Option(
        None,
        "--status",
        help="Temporal status: current, former, bounded, or unknown.",
    ),
    notes: str | None = typer.Option(None, help="Optional affiliation notes."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    pastor_record = database.get_pastor_by_slug(pastor)
    if pastor_record is None:
        raise unknown_pastor_error(pastor, base_dir)
    organization_record = database.get_organization_by_slug(organization)
    if organization_record is None:
        raise typer.BadParameter(f"Unknown organization slug: {organization}")
    try:
        start_date = date.fromisoformat(started_on) if started_on is not None else None
        end_date = date.fromisoformat(ended_on) if ended_on is not None else None
    except ValueError as error:
        raise typer.BadParameter("Affiliation dates must use YYYY-MM-DD.") from error
    if start_date is not None and end_date is not None and end_date <= start_date:
        raise typer.BadParameter("--to must be later than --from.")
    inferred_status = (
        "bounded"
        if end_date is not None and start_date is not None
        else "former"
        if end_date is not None
        else "current"
        if start_date is not None
        else "unknown"
    )
    resolved_status = temporal_status or inferred_status
    if resolved_status not in {"current", "former", "bounded", "unknown"}:
        raise typer.BadParameter(
            "--status must be current, former, bounded, or unknown."
        )
    role_label = role.strip()
    if not role_label:
        raise typer.BadParameter("--role cannot be empty.")
    role_key = re.sub(r"[^a-z0-9]+", "_", role_label.lower()).strip("_")
    affiliation = database.add_pastor_organization_affiliation(
        pastor_id=pastor_record.id,
        organization_id=organization_record.id,
        role_key=role_key,
        role_label=role_label,
        started_on=started_on,
        ended_on=ended_on,
        temporal_status=resolved_status,
        provenance_kind="manual",
        notes=notes,
    )
    console.print(
        f"Recorded affiliation #{affiliation.id}: {pastor_record.slug} -> "
        f"{organization_record.slug} ({role_label}, {resolved_status})."
    )


@pastor_app.command(
    "affiliate-claim",
    help="Explicitly attach an imported affiliation claim to a selected pastor.",
)
def pastor_affiliate_claim(
    pastor: str = typer.Argument(..., help="Existing curated pastor slug."),
    claim_id: int = typer.Argument(..., help="Imported affiliation claim id."),
    reviewer: str = typer.Option(..., help="Reviewer name."),
    reason: str = typer.Option(..., help="Grounded reason for the attachment."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    pastor_record = database.get_pastor_by_slug(pastor)
    if pastor_record is None:
        raise unknown_pastor_error(pastor, base_dir)
    try:
        event_id = database.review_organization_affiliation_claim(
            claim_id=claim_id,
            pastor_id=pastor_record.id,
            attach=True,
            reviewer=reviewer,
            reason=reason,
            review_event_key=(
                f"attach:{claim_id}:{pastor_record.id}:{reviewer}:{reason}"
            ),
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Attached affiliation claim #{claim_id} to pastor "
        f"{pastor_record.slug} with review event #{event_id}."
    )


def _delete_video_tree(database: Database, paths: Path, video_id: int) -> None:
    video = database.get_video_by_id(video_id)
    if video is None:
        raise typer.BadParameter(f"Unknown video id: {video_id}")

    video_paths = resolve_video_artifact_paths(database, paths, video)
    if video_paths.root.exists():
        shutil.rmtree(video_paths.root)
    database.delete_video(video.id)


def _delete_source_tree(database: Database, paths: Path, source_id: int) -> int:
    source = database.get_source_by_id(source_id)
    if source is None:
        raise typer.BadParameter(f"Unknown source id: {source_id}")

    videos = database.list_videos_by_source_id(source_id)
    deleted_count = 0
    for video in videos:
        video_paths = resolve_video_artifact_paths(database, paths, video)
        if video_paths.root.exists():
            shutil.rmtree(video_paths.root)
        database.delete_video(video.id)
        deleted_count += 1

    database.delete_source(source_id)
    return deleted_count


def delete_source_service(
    source_id: int,
    force: bool = False,
    base_dir: Path | None = None,
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    source = database.get_source_by_id(source_id)
    if source is None:
        raise ValueError(f"Unknown source id: {source_id}")

    videos = database.list_videos_by_source_id(source_id)
    if videos and not force:
        raise ValueError(
            f"Source #{source_id} has {len(videos)} linked video(s). Use --force to delete them too."
        )

    deleted_videos = _delete_source_tree(database, paths, source_id)
    console.print(
        f"Deleted source #{source_id} ({source.url}); removed {deleted_videos} linked video(s) and artifacts."
    )


@source_app.command("delete", help="Delete a source and optionally all dependent videos and artifacts.")
def source_delete(
    source_id: int = typer.Argument(..., help="Source id to delete."),
    force: bool = typer.Option(False, "--force", help="Delete dependent videos and all related artifacts."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        delete_source_service(source_id, force, base_dir)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


@video_app.command("list", help="List discovered videos.")
def video_list(
    pastor: str | None = typer.Option(None, help="Filter by pastor slug."),
    organization: str | None = typer.Option(
        None,
        help="Filter by publishing organization slug.",
    ),
    source_id: int | None = typer.Option(None, help="Filter by source id."),
    status: VideoStatus | None = typer.Option(None, help="Filter by video status."),
    limit: int = typer.Option(50, min=1, help="Maximum number of videos to show."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    videos = database.list_videos()

    if pastor is not None:
        pastor_record = database.get_pastor_by_slug(pastor)
        if pastor_record is None:
            raise unknown_pastor_error(pastor, base_dir)
        target_video_ids = database.list_video_ids_for_target_pastor(
            pastor_record.id
        )
        videos = [video for video in videos if video.id in target_video_ids]

    if organization is not None:
        organization_record = database.get_organization_by_slug(organization)
        if organization_record is None:
            raise typer.BadParameter(
                f"Unknown organization slug: {organization}"
            )
        source_ids = {
            source.id
            for source in database.list_sources()
            if source.organization_id == organization_record.id
        }
        videos = [video for video in videos if video.source_id in source_ids]

    if source_id is not None:
        videos = [video for video in videos if video.source_id == source_id]

    if status is not None:
        videos = [video for video in videos if video.status == status]

    if not videos:
        console.print("No videos matched.")
        return

    videos = videos[:limit]
    table = Table(title="Videos")
    table.add_column("ID", justify="right")
    table.add_column("Publisher")
    table.add_column("Target Pastor")
    table.add_column("Status")
    table.add_column("Title")
    table.add_column("YouTube ID")

    for video in videos:
        source = database.get_source_by_id(video.source_id)
        publisher_name = "-"
        if source is not None and source.organization_id is not None:
            organization_record = database.get_organization_by_id(
                source.organization_id
            )
            publisher_name = (
                organization_record.slug
                if organization_record is not None
                else str(source.organization_id)
            )
        pastor_name = "-"
        if video.pastor_id is not None:
            pastor_record = database.get_pastor_by_id(video.pastor_id)
            pastor_name = pastor_record.slug if pastor_record is not None else str(video.pastor_id)
        table.add_row(
            str(video.id),
            publisher_name,
            pastor_name,
            video.status.value,
            video.title,
            video.youtube_video_id,
        )

    console.print(table)

@video_app.command("exclude", help="Delete a video's local artifacts and prevent it from being rediscovered.")
def video_exclude(
    video_id: int = typer.Argument(..., help="Video id to exclude."),
    notes: str | None = typer.Option(None, help="Optional exclusion notes."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    video = database.get_video_by_id(video_id)
    if video is None:
        raise typer.BadParameter(f"Unknown video id: {video_id}")

    database.add_excluded_video(
        pastor_id=video.pastor_id,
        source_id=video.source_id,
        youtube_video_id=video.youtube_video_id,
        title=video.title,
        url=video.url,
        notes=notes,
    )
    _delete_video_tree(database, paths, video.id)
    console.print(f"Excluded video #{video_id}: {video.title} ({video.youtube_video_id})")


@video_app.command("unexclude", help="Allow an excluded YouTube video to be rediscovered again.")
def video_unexclude(
    youtube_video_id: str = typer.Argument(..., help="YouTube video id to remove from the exclusion list."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    excluded = database.get_excluded_video_by_youtube_id(youtube_video_id)
    if excluded is None:
        raise typer.BadParameter(f"Unknown excluded video id: {youtube_video_id}")
    database.delete_excluded_video(youtube_video_id)
    console.print(f"Removed exclusion for {youtube_video_id}: {excluded.title}")


@video_app.command("excluded", help="List excluded YouTube videos.")
def video_excluded(
    pastor: str | None = typer.Option(None, help="Filter by pastor slug."),
    limit: int = typer.Option(50, min=1, help="Maximum number of excluded videos to show."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    excluded_videos = database.list_excluded_videos()

    if pastor is not None:
        pastor_record = database.get_pastor_by_slug(pastor)
        if pastor_record is None:
            raise unknown_pastor_error(pastor, base_dir)
        excluded_videos = [video for video in excluded_videos if video.pastor_id == pastor_record.id]

    if not excluded_videos:
        console.print("No excluded videos matched.")
        return

    table = Table(title="Excluded Videos")
    table.add_column("Pastor")
    table.add_column("Excluded")
    table.add_column("Title")
    table.add_column("YouTube ID")
    for video in excluded_videos[:limit]:
        pastor_name = "-"
        if video.pastor_id is not None:
            pastor_record = database.get_pastor_by_id(video.pastor_id)
            pastor_name = pastor_record.slug if pastor_record is not None else str(video.pastor_id)
        table.add_row(
            pastor_name,
            video.excluded_at.date().isoformat(),
            video.title,
            video.youtube_video_id,
        )
    console.print(table)
