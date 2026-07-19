from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from pastor_transcript_extractor.models import utc_now
from pastor_transcript_extractor.sources import detect_source_type
from pastor_transcript_extractor.storage import Database


IMPORT_PROVIDER = "church-youtube-finder"
IMPORTER_VERSION = "church_database_import_v1"


class ChurchDatabaseImportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ChurchSourceRecord:
    external_record_id: str
    external_entity_key: str
    church_name: str
    church_source_url: str
    pastor_name: str
    channel_url: str
    external_updated_at: str | None
    fingerprint: str

    def payload(self) -> dict[str, object]:
        return {
            "church_name": self.church_name,
            "church_source_url": self.church_source_url,
            "channel_url": self.channel_url,
            "external_record_id": self.external_record_id,
            "external_updated_at": self.external_updated_at,
            "importer_version": IMPORTER_VERSION,
            "pastor_name": self.pastor_name,
        }


@dataclass(frozen=True, slots=True)
class ChurchImportItem:
    record: ChurchSourceRecord
    status: str
    source_id: int | None
    pastor_slug: str | None
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
    for suffix in ("/featured", "/streams", "/videos"):
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
            SELECT id, name, source_url, youtube_channel, pastor_name, updated_at
            FROM churches
            WHERE status = 'found'
              AND trim(coalesce(pastor_name, '')) <> ''
              AND trim(coalesce(youtube_channel, '')) <> ''
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
        try:
            channel_url = normalize_youtube_channel_url(str(row["youtube_channel"]))
        except ValueError as error:
            raise ChurchDatabaseImportError(
                f"church row {row['id']} has an invalid YouTube channel: {error}"
            ) from error
        channel_key = canonical_youtube_source_key(channel_url)
        prior_key = seen_channels.get(channel_key)
        if prior_key is not None:
            raise ChurchDatabaseImportError(
                f"YouTube channel belongs to multiple complete church records: "
                f"{prior_key}, {external_key}"
            )
        seen_channels[channel_key] = external_key
        fingerprint_payload = {
            "channel_key": channel_key,
            "church_name": str(row["name"]).strip(),
            "church_source_url": church_source_url,
            "pastor_name": str(row["pastor_name"]).strip(),
        }
        fingerprint = _canonical_hash(fingerprint_payload)
        records.append(
            ChurchSourceRecord(
                external_record_id=str(row["id"]),
                external_entity_key=external_key,
                church_name=str(row["name"]).strip(),
                church_source_url=church_source_url,
                pastor_name=str(row["pastor_name"]).strip(),
                channel_url=channel_url,
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
            SELECT DISTINCT source_id
            FROM source_import_refs
            WHERE provider = ?
            ORDER BY source_id
            """,
            (provider,),
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
        SELECT r.source_id, r.pastor_id, r.imported_fingerprint, p.slug
        FROM source_import_refs r
        JOIN pastors p ON p.id = r.pastor_id
        WHERE r.provider = ? AND r.external_entity_key = ?
        """,
        (IMPORT_PROVIDER, record.external_entity_key),
    ).fetchone()
    if existing_ref is not None:
        if str(existing_ref["imported_fingerprint"]) == record.fingerprint:
            return ChurchImportItem(
                record, "unchanged", int(existing_ref["source_id"]), str(existing_ref["slug"]),
                "external key and imported fingerprint match",
            )
        return ChurchImportItem(
            record, "conflict", int(existing_ref["source_id"]), str(existing_ref["slug"]),
            "external record changed; manual reconciliation required",
        )

    channel_key = canonical_youtube_source_key(record.channel_url)
    source_rows = connection.execute(
        """
        SELECT s.id, s.url, s.pastor_id, p.slug, p.display_name
        FROM sources s JOIN pastors p ON p.id = s.pastor_id
        ORDER BY s.id
        """
    ).fetchall()
    existing_source = next(
        (row for row in source_rows if canonical_youtube_source_key(str(row["url"])) == channel_key),
        None,
    )
    if existing_source is not None:
        if _normalized_name(str(existing_source["display_name"])) != _normalized_name(
            record.pastor_name
        ):
            return ChurchImportItem(
                record,
                "conflict",
                int(existing_source["id"]),
                str(existing_source["slug"]),
                "channel already exists with a different pastor assignment",
            )
        if not dry_run:
            _insert_import_ref(
                connection,
                record,
                source_id=int(existing_source["id"]),
                pastor_id=int(existing_source["pastor_id"]),
            )
        return ChurchImportItem(
            record,
            "reused",
            int(existing_source["id"]),
            str(existing_source["slug"]),
            "matched an existing channel and pastor assignment",
        )

    slug = _available_slug(connection, record)
    if dry_run:
        return ChurchImportItem(
            record, "created", None, slug, "would create pastor, source, and import reference"
        )
    now = utc_now().isoformat()
    pastor_cursor = connection.execute(
        "INSERT INTO pastors (slug, display_name, added_at, notes) VALUES (?, ?, ?, ?)",
        (
            slug,
            record.pastor_name,
            now,
            f"Imported from {IMPORT_PROVIDER}: {record.church_name}",
        ),
    )
    pastor_id = int(pastor_cursor.lastrowid)
    source_cursor = connection.execute(
        """
        INSERT INTO sources (pastor_id, url, source_type, added_at, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            pastor_id,
            record.channel_url,
            detect_source_type(record.channel_url).value,
            now,
            f"Imported from {IMPORT_PROVIDER}: {record.church_name}",
        ),
    )
    source_id = int(source_cursor.lastrowid)
    _insert_import_ref(connection, record, source_id=source_id, pastor_id=pastor_id)
    return ChurchImportItem(
        record, "created", source_id, slug, "created pastor, source, and import reference"
    )


def _insert_import_ref(
    connection: sqlite3.Connection,
    record: ChurchSourceRecord,
    *,
    source_id: int,
    pastor_id: int,
) -> None:
    connection.execute(
        """
        INSERT INTO source_import_refs (
            source_id, pastor_id, provider, external_entity_key, external_record_id,
            imported_fingerprint, import_payload_json, external_updated_at, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            pastor_id,
            IMPORT_PROVIDER,
            record.external_entity_key,
            record.external_record_id,
            record.fingerprint,
            json.dumps(record.payload(), sort_keys=True, separators=(",", ":")),
            record.external_updated_at,
            utc_now().isoformat(),
        ),
    )


def _available_slug(connection: sqlite3.Connection, record: ChurchSourceRecord) -> str:
    base = f"churchdb-{record.external_record_id}"
    row = connection.execute("SELECT display_name FROM pastors WHERE slug = ?", (base,)).fetchone()
    if row is None:
        return base
    suffix = hashlib.sha256(record.external_entity_key.encode("utf-8")).hexdigest()[:8]
    candidate = f"{base}-{suffix}"
    if connection.execute("SELECT 1 FROM pastors WHERE slug = ?", (candidate,)).fetchone():
        raise ChurchDatabaseImportError(f"could not allocate stable pastor slug for {record.church_name}")
    return candidate


def _normalized_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
