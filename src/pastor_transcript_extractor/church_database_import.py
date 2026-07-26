from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit, urlunsplit

from pastor_transcript_extractor.models import utc_now
from pastor_transcript_extractor.sources import detect_source_type
from pastor_transcript_extractor.storage import Database


IMPORT_PROVIDER = "church-youtube-finder"
IMPORTER_VERSION = "church_database_import_v2"


class ChurchDatabaseImportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ChurchSourceRecord:
    external_record_id: str
    external_entity_key: str
    church_name: str
    church_source_url: str
    pastor_name: str
    discovered_channel_url: str
    channel_url: str
    channel_id: str
    channel_key: str
    channel_resolver_version: str
    channel_resolved_at: str | None
    external_updated_at: str | None
    fingerprint: str

    def payload(self) -> dict[str, object]:
        return {
            "church_name": self.church_name,
            "church_source_url": self.church_source_url,
            "discovered_channel_url": self.discovered_channel_url,
            "channel_url": self.channel_url,
            "channel_id": self.channel_id,
            "channel_key": self.channel_key,
            "channel_resolved_at": self.channel_resolved_at,
            "channel_resolver_version": self.channel_resolver_version,
            "channel_resolution_error": "",
            "external_record_id": self.external_record_id,
            "external_updated_at": self.external_updated_at,
            "importer_version": IMPORTER_VERSION,
            "pastor_name": self.pastor_name,
            "source_status": "found",
        }


@dataclass(frozen=True, slots=True)
class ChurchImportItem:
    record: ChurchSourceRecord
    status: str
    source_id: int | None
    organization_slug: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class ChurchImportResult:
    dry_run: bool
    items: tuple[ChurchImportItem, ...]

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.status] = counts.get(item.status, 0) + 1
        return counts


def normalize_youtube_channel_url(url: str) -> str:
    value = url.strip()
    parsed = urlsplit(value)
    host = parsed.netloc.lower()
    if host == "youtube.com":
        host = "www.youtube.com"
    path = parsed.path.rstrip("/")
    for suffix in ("/featured", "/streams", "/videos", "/live"):
        if path.lower().endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            break
    normalized = urlunsplit(("https", host, path, "", ""))
    detect_source_type(normalized)
    return normalized


def canonical_youtube_source_key(url: str) -> str:
    normalized = normalize_youtube_channel_url(url)
    parsed = urlsplit(normalized)
    path = parsed.path.lower() if parsed.path.startswith("/@") else parsed.path
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def load_complete_church_sources(path: Path) -> tuple[ChurchSourceRecord, ...]:
    if not path.exists():
        raise ChurchDatabaseImportError(f"church database does not exist: {path}")
    uri = f"{path.expanduser().resolve().as_uri()}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(churches)").fetchall()
        }
        required = {
            "id",
            "name",
            "source_url",
            "youtube_channel",
            "youtube_channel_canonical_url",
            "youtube_channel_id",
            "youtube_channel_key",
            "youtube_channel_resolver_version",
            "youtube_channel_resolved_at",
            "youtube_channel_resolution_error",
            "pastor_name",
            "status",
            "updated_at",
        }
        missing = sorted(required - columns)
        if missing:
            raise ChurchDatabaseImportError(
                f"churches table is missing required columns: {', '.join(missing)}"
            )
        rows = connection.execute(
            """
            SELECT
                id, name, source_url, youtube_channel, pastor_name, updated_at,
                youtube_channel_canonical_url, youtube_channel_id, youtube_channel_key,
                youtube_channel_resolver_version, youtube_channel_resolved_at,
                youtube_channel_resolution_error
            FROM churches
            WHERE status = 'found'
              AND trim(coalesce(youtube_channel_key, '')) <> ''
              AND trim(coalesce(youtube_channel_id, '')) <> ''
              AND trim(coalesce(youtube_channel_canonical_url, '')) <> ''
              AND trim(coalesce(youtube_channel_resolution_error, '')) = ''
            ORDER BY id
            """
        ).fetchall()
    except sqlite3.Error as error:
        raise ChurchDatabaseImportError(f"could not read church database: {error}") from error
    finally:
        if "connection" in locals():
            connection.close()

    records: list[ChurchSourceRecord] = []
    seen_keys: set[str] = set()
    seen_channels: dict[str, str] = {}
    for row in rows:
        church_source_url = str(row["source_url"]).strip()
        external_key = "church-source-url:" + church_source_url.rstrip("/").lower()
        if external_key in seen_keys:
            raise ChurchDatabaseImportError(f"duplicate church entity key: {external_key}")
        seen_keys.add(external_key)
        discovered_channel_url = str(row["youtube_channel"] or "").strip()
        channel_url = str(row["youtube_channel_canonical_url"]).strip()
        channel_id = str(row["youtube_channel_id"]).strip()
        channel_key = str(row["youtube_channel_key"]).strip()
        resolver_version = str(row["youtube_channel_resolver_version"] or "").strip()
        try:
            channel_url = normalize_youtube_channel_url(channel_url)
            expected_key = youtube_channel_key_from_id(channel_id)
        except ValueError as error:
            raise ChurchDatabaseImportError(
                f"church row {row['id']} has invalid resolved YouTube identity: {error}"
            ) from error
        if channel_key != expected_key:
            raise ChurchDatabaseImportError(
                f"church row {row['id']} channel key does not match channel ID"
            )
        if _channel_id_from_url(channel_url) != channel_id:
            raise ChurchDatabaseImportError(
                f"church row {row['id']} canonical URL does not match channel ID"
            )
        if not resolver_version:
            raise ChurchDatabaseImportError(
                f"church row {row['id']} is missing youtube_channel_resolver_version"
            )
        prior_key = seen_channels.get(channel_key)
        if prior_key is not None:
            raise ChurchDatabaseImportError(
                f"YouTube channel belongs to multiple complete church records: "
                f"{prior_key}, {external_key}"
            )
        seen_channels[channel_key] = external_key
        fingerprint_payload = {
            "channel_key": channel_key,
            "channel_resolved_at": (
                str(row["youtube_channel_resolved_at"])
                if row["youtube_channel_resolved_at"] is not None
                else None
            ),
            "channel_resolver_version": resolver_version,
            "channel_url": channel_url,
            "church_name": str(row["name"]).strip(),
            "church_source_url": church_source_url,
            "discovered_channel_url": discovered_channel_url,
            "external_record_id": str(row["id"]),
            "external_updated_at": (
                str(row["updated_at"]) if row["updated_at"] is not None else None
            ),
            "pastor_name": str(row["pastor_name"] or "").strip(),
        }
        fingerprint = _canonical_hash(fingerprint_payload)
        records.append(
            ChurchSourceRecord(
                external_record_id=str(row["id"]),
                external_entity_key=external_key,
                church_name=str(row["name"]).strip(),
                church_source_url=church_source_url,
                pastor_name=str(row["pastor_name"] or "").strip(),
                discovered_channel_url=discovered_channel_url,
                channel_url=channel_url,
                channel_id=channel_id,
                channel_key=channel_key,
                channel_resolver_version=resolver_version,
                channel_resolved_at=(
                    str(row["youtube_channel_resolved_at"])
                    if row["youtube_channel_resolved_at"] is not None
                    else None
                ),
                external_updated_at=(
                    str(row["updated_at"]) if row["updated_at"] is not None else None
                ),
                fingerprint=fingerprint,
            )
        )
    return tuple(records)


def import_church_sources(
    database: Database,
    church_database_path: Path,
    *,
    dry_run: bool,
) -> ChurchImportResult:
    records = load_complete_church_sources(church_database_path)
    with database.connect() as connection:
        items = tuple(_import_record(connection, record, dry_run=dry_run) for record in records)
        if dry_run:
            connection.rollback()
    return ChurchImportResult(dry_run=dry_run, items=items)


def imported_source_ids(database: Database, provider: str = IMPORT_PROVIDER) -> list[int]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT source_id FROM (
                SELECT legacy.source_id
                FROM source_import_refs legacy
                WHERE legacy.provider = ?
                UNION
                SELECT link.source_id
                FROM source_import_links link
                JOIN organization_external_refs ref
                  ON ref.id = link.organization_external_ref_id
                WHERE ref.provider = ?
            )
            ORDER BY source_id
            """,
            (provider, provider),
        ).fetchall()
    return [int(row["source_id"]) for row in rows]


def _import_record(
    connection: sqlite3.Connection,
    record: ChurchSourceRecord,
    *,
    dry_run: bool,
) -> ChurchImportItem:
    existing_ref = connection.execute(
        """
        SELECT ref.id AS ref_id, ref.organization_id, organization.slug,
               link.source_id, link.channel_identity_key, source.source_identity_key
        FROM organization_external_refs ref
        JOIN organizations organization ON organization.id = ref.organization_id
        LEFT JOIN source_import_links link
          ON link.organization_external_ref_id = ref.id
        LEFT JOIN sources source ON source.id = link.source_id
        WHERE ref.provider = ? AND ref.external_entity_key = ?
        """,
        (IMPORT_PROVIDER, record.external_entity_key),
    ).fetchone()
    if existing_ref is not None:
        existing_snapshot = connection.execute(
            """
            SELECT id FROM external_record_snapshots
            WHERE organization_external_ref_id = ? AND imported_fingerprint = ?
            """,
            (int(existing_ref["ref_id"]), record.fingerprint),
        ).fetchone()
        if existing_snapshot is not None:
            return ChurchImportItem(
                record,
                "unchanged",
                (
                    int(existing_ref["source_id"])
                    if existing_ref["source_id"] is not None
                    else None
                ),
                str(existing_ref["slug"]),
                "external key and imported fingerprint match",
            )
        channel_keys = {
            str(value)
            for value in (
                existing_ref["channel_identity_key"],
                existing_ref["source_identity_key"],
            )
            if value is not None
        }
        conflict = bool(channel_keys and record.channel_key not in channel_keys)
        if not dry_run:
            snapshot_id = _insert_snapshot(
                connection,
                organization_external_ref_id=int(existing_ref["ref_id"]),
                record=record,
            )
            _insert_affiliation_claim(
                connection,
                organization_id=int(existing_ref["organization_id"]),
                snapshot_id=snapshot_id,
                record=record,
            )
        return ChurchImportItem(
            record,
            "conflict" if conflict else "updated",
            (
                int(existing_ref["source_id"])
                if existing_ref["source_id"] is not None
                else None
            ),
            str(existing_ref["slug"]),
            (
                "resolved channel identity changed; manual reconciliation required"
                if conflict
                else (
                    "would append a new external snapshot and affiliation claim"
                    if dry_run
                    else "appended a new external snapshot and affiliation claim"
                )
            ),
        )

    source_rows = connection.execute(
        """
        SELECT id, url, source_identity_key, organization_id
        FROM sources
        ORDER BY id
        """
    ).fetchall()
    existing_source = next(
        (
            row
            for row in source_rows
            if _source_matches_record(row, record)
        ),
        None,
    )
    if dry_run:
        if existing_source is not None and existing_source["organization_id"] is not None:
            organization = connection.execute(
                "SELECT slug FROM organizations WHERE id = ?",
                (int(existing_source["organization_id"]),),
            ).fetchone()
            organization_slug = (
                str(organization["slug"])
                if organization is not None
                else _available_slug(connection, record)
            )
        else:
            organization_slug = _available_slug(connection, record)
        return ChurchImportItem(
            record,
            "reused" if existing_source is not None else "created",
            int(existing_source["id"]) if existing_source is not None else None,
            organization_slug,
            (
                "would create organization provenance and reuse the channel"
                if existing_source is not None
                else "would create organization, source, provenance, and affiliation claim"
            ),
        )

    now = utc_now().isoformat()
    if existing_source is not None and existing_source["organization_id"] is not None:
        organization_id = int(existing_source["organization_id"])
        organization = connection.execute(
            "SELECT slug FROM organizations WHERE id = ?",
            (organization_id,),
        ).fetchone()
        if organization is None:
            raise ChurchDatabaseImportError(
                f"source {existing_source['id']} references an unknown organization"
            )
        slug = str(organization["slug"])
    else:
        slug = _available_slug(connection, record)
        organization_cursor = connection.execute(
            """
            INSERT INTO organizations (
                slug, display_name, organization_type, added_at, notes
            ) VALUES (?, ?, 'church', ?, ?)
            """,
            (
                slug,
                record.church_name,
                now,
                f"Imported from {IMPORT_PROVIDER}",
            ),
        )
        organization_id = int(organization_cursor.lastrowid)
    ref_cursor = connection.execute(
        """
        INSERT INTO organization_external_refs (
            organization_id, provider, external_entity_key,
            external_record_id, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            organization_id,
            IMPORT_PROVIDER,
            record.external_entity_key,
            record.external_record_id,
            now,
        ),
    )
    external_ref_id = int(ref_cursor.lastrowid)
    if existing_source is None:
        source_cursor = connection.execute(
            """
            INSERT INTO sources (
                pastor_id, organization_id, url, source_identity_key,
                source_type, added_at, notes
            ) VALUES (NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                record.channel_url,
                record.channel_key,
                detect_source_type(record.channel_url).value,
                now,
                f"Imported from {IMPORT_PROVIDER}: {record.church_name}",
            ),
        )
        source_id = int(source_cursor.lastrowid)
    else:
        source_id = int(existing_source["id"])
        connection.execute(
            """
            UPDATE sources
            SET organization_id = ?,
                source_identity_key = coalesce(source_identity_key, ?)
            WHERE id = ?
            """,
            (organization_id, record.channel_key, source_id),
        )
    snapshot_id = _insert_snapshot(
        connection,
        organization_external_ref_id=external_ref_id,
        record=record,
    )
    connection.execute(
        """
        INSERT INTO source_import_links (
            source_id, organization_external_ref_id,
            channel_identity_key, created_at
        ) VALUES (?, ?, ?, ?)
        """,
        (source_id, external_ref_id, record.channel_key, now),
    )
    _insert_source_organization_event(
        connection,
        source_id=source_id,
        organization_id=organization_id,
        snapshot_id=snapshot_id,
        record=record,
    )
    _insert_affiliation_claim(
        connection,
        organization_id=organization_id,
        snapshot_id=snapshot_id,
        record=record,
    )
    return ChurchImportItem(
        record,
        "reused" if existing_source is not None else "created",
        source_id,
        slug,
        (
            "created organization provenance and reused the channel"
            if existing_source is not None
            else "created organization, source, provenance, and affiliation claim"
        ),
    )


def _insert_snapshot(
    connection: sqlite3.Connection,
    *,
    organization_external_ref_id: int,
    record: ChurchSourceRecord,
) -> int:
    connection.execute(
        """
        INSERT OR IGNORE INTO external_record_snapshots (
            organization_external_ref_id, imported_fingerprint,
            import_payload_json, external_updated_at, observed_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            organization_external_ref_id,
            record.fingerprint,
            json.dumps(record.payload(), sort_keys=True, separators=(",", ":")),
            record.external_updated_at,
            utc_now().isoformat(),
        ),
    )
    row = connection.execute(
        """
        SELECT id FROM external_record_snapshots
        WHERE organization_external_ref_id = ? AND imported_fingerprint = ?
        """,
        (organization_external_ref_id, record.fingerprint),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def _insert_affiliation_claim(
    connection: sqlite3.Connection,
    *,
    organization_id: int,
    snapshot_id: int,
    record: ChurchSourceRecord,
) -> None:
    if not record.pastor_name:
        return
    fingerprint = _canonical_hash(
        {
            "organization_id": organization_id,
            "snapshot_id": snapshot_id,
            "claimed_person_name": record.pastor_name,
            "claimed_role": "pastor",
        }
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO organization_affiliation_claims (
            organization_id, external_record_snapshot_id,
            claimed_person_name, claimed_role, valid_from, valid_to,
            claim_fingerprint, created_at
        ) VALUES (?, ?, ?, 'pastor', NULL, NULL, ?, ?)
        """,
        (
            organization_id,
            snapshot_id,
            record.pastor_name,
            fingerprint,
            utc_now().isoformat(),
        ),
    )


def _insert_source_organization_event(
    connection: sqlite3.Connection,
    *,
    source_id: int,
    organization_id: int,
    snapshot_id: int,
    record: ChurchSourceRecord,
) -> None:
    fingerprint = _canonical_hash(
        {
            "source_id": source_id,
            "organization_id": organization_id,
            "snapshot_id": snapshot_id,
            "action": "attach",
        }
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO source_organization_events (
            source_id, organization_id, action, actor, reason,
            external_record_snapshot_id, event_fingerprint, created_at
        ) VALUES (?, ?, 'attach', ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            organization_id,
            f"import:{IMPORT_PROVIDER}",
            "Grounded external church/channel association",
            snapshot_id,
            fingerprint,
            utc_now().isoformat(),
        ),
    )


def _available_slug(connection: sqlite3.Connection, record: ChurchSourceRecord) -> str:
    base = f"churchdb-org-{record.external_record_id}"
    row = connection.execute(
        "SELECT display_name FROM organizations WHERE slug = ?", (base,)
    ).fetchone()
    if row is None:
        return base
    suffix = hashlib.sha256(record.external_entity_key.encode("utf-8")).hexdigest()[:8]
    candidate = f"{base}-{suffix}"
    if connection.execute(
        "SELECT 1 FROM organizations WHERE slug = ?", (candidate,)
    ).fetchone():
        raise ChurchDatabaseImportError(
            f"could not allocate stable organization slug for {record.church_name}"
        )
    return candidate


def youtube_channel_key_from_id(channel_id: str) -> str:
    value = channel_id.strip()
    if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", value):
        raise ChurchDatabaseImportError(f"invalid YouTube channel ID: {channel_id!r}")
    return f"youtube:channel:{value}"


def _channel_id_from_url(url: str) -> str | None:
    path = urlsplit(url).path.strip("/")
    parts = path.split("/")
    if len(parts) == 2 and parts[0].lower() == "channel":
        return parts[1]
    return None


def _source_matches_record(row: sqlite3.Row, record: ChurchSourceRecord) -> bool:
    identity_key = row["source_identity_key"]
    if identity_key is not None:
        return str(identity_key) == record.channel_key
    source_url = str(row["url"])
    channel_id = _channel_id_from_url(normalize_youtube_channel_url(source_url))
    if channel_id is not None:
        return youtube_channel_key_from_id(channel_id) == record.channel_key
    aliases = {
        canonical_youtube_source_key(record.discovered_channel_url),
        canonical_youtube_source_key(record.channel_url),
    }
    return canonical_youtube_source_key(source_url) in aliases


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
