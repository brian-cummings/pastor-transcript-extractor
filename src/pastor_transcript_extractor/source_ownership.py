from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3

from pastor_transcript_extractor.models import utc_now


SOURCE_OWNERSHIP_MIGRATION_VERSION = 3


_AFFILIATION_REVIEW_DDL = (
    """
    CREATE TABLE IF NOT EXISTS affiliation_claim_review_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        claim_id INTEGER NOT NULL,
        pastor_id INTEGER NULL,
        action TEXT NOT NULL CHECK(action IN ('attach', 'reject')),
        reviewer TEXT NOT NULL,
        reason TEXT NOT NULL,
        event_fingerprint TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        FOREIGN KEY(claim_id) REFERENCES organization_affiliation_claims(id),
        FOREIGN KEY(pastor_id) REFERENCES pastors(id),
        CHECK(
            (action = 'attach' AND pastor_id IS NOT NULL)
            OR (action = 'reject' AND pastor_id IS NULL)
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_affiliation_claim_reviews_claim
    ON affiliation_claim_review_events(claim_id, id)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_affiliations_reviewed_claim
    ON pastor_organization_affiliations(
        pastor_id, organization_id, affiliation_claim_id
    )
    WHERE affiliation_claim_id IS NOT NULL
    """,
)


_SOURCE_OWNERSHIP_DDL = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS organizations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        organization_type TEXT NOT NULL,
        added_at TEXT NOT NULL,
        notes TEXT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS organization_external_refs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        organization_id INTEGER NOT NULL,
        provider TEXT NOT NULL,
        external_entity_key TEXT NOT NULL,
        external_record_id TEXT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(organization_id) REFERENCES organizations(id),
        UNIQUE(provider, external_entity_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS external_record_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        organization_external_ref_id INTEGER NOT NULL,
        imported_fingerprint TEXT NOT NULL,
        import_payload_json TEXT NOT NULL,
        external_updated_at TEXT NULL,
        observed_at TEXT NOT NULL,
        FOREIGN KEY(organization_external_ref_id) REFERENCES organization_external_refs(id),
        UNIQUE(organization_external_ref_id, imported_fingerprint)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_import_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL,
        organization_external_ref_id INTEGER NOT NULL UNIQUE,
        channel_identity_key TEXT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(source_id) REFERENCES sources(id),
        FOREIGN KEY(organization_external_ref_id) REFERENCES organization_external_refs(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_organization_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL,
        organization_id INTEGER NULL,
        action TEXT NOT NULL CHECK(action IN ('attach', 'detach')),
        actor TEXT NOT NULL,
        reason TEXT NOT NULL,
        external_record_snapshot_id INTEGER NULL,
        event_fingerprint TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        FOREIGN KEY(source_id) REFERENCES sources(id),
        FOREIGN KEY(organization_id) REFERENCES organizations(id),
        FOREIGN KEY(external_record_snapshot_id) REFERENCES external_record_snapshots(id),
        CHECK(
            (action = 'attach' AND organization_id IS NOT NULL)
            OR (action = 'detach' AND organization_id IS NULL)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS organization_affiliation_claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        organization_id INTEGER NOT NULL,
        external_record_snapshot_id INTEGER NULL,
        claimed_person_name TEXT NOT NULL,
        claimed_role TEXT NOT NULL,
        valid_from TEXT NULL,
        valid_to TEXT NULL,
        claim_fingerprint TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        FOREIGN KEY(organization_id) REFERENCES organizations(id),
        FOREIGN KEY(external_record_snapshot_id) REFERENCES external_record_snapshots(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pastor_organization_affiliations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pastor_id INTEGER NOT NULL,
        organization_id INTEGER NOT NULL,
        role_key TEXT NOT NULL,
        role_label TEXT NOT NULL,
        started_on TEXT NULL,
        ended_on TEXT NULL,
        temporal_status TEXT NOT NULL CHECK(
            temporal_status IN ('current', 'former', 'bounded', 'unknown')
        ),
        provenance_kind TEXT NOT NULL,
        affiliation_claim_id INTEGER NULL,
        notes TEXT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(pastor_id) REFERENCES pastors(id),
        FOREIGN KEY(organization_id) REFERENCES organizations(id),
        FOREIGN KEY(affiliation_claim_id) REFERENCES organization_affiliation_claims(id),
        CHECK(ended_on IS NULL OR started_on IS NULL OR ended_on > started_on)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_target_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL,
        pastor_id INTEGER NOT NULL,
        purpose TEXT NOT NULL,
        origin_kind TEXT NOT NULL,
        active INTEGER NOT NULL CHECK(active IN (0, 1)),
        created_at TEXT NOT NULL,
        FOREIGN KEY(source_id) REFERENCES sources(id),
        FOREIGN KEY(pastor_id) REFERENCES pastors(id),
        UNIQUE(source_id, pastor_id, purpose)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS video_target_contexts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id INTEGER NOT NULL,
        pastor_id INTEGER NOT NULL,
        source_target_policy_id INTEGER NULL,
        purpose TEXT NOT NULL,
        origin_kind TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(video_id) REFERENCES videos(id),
        FOREIGN KEY(pastor_id) REFERENCES pastors(id),
        FOREIGN KEY(source_target_policy_id) REFERENCES source_target_policies(id),
        UNIQUE(video_id, pastor_id, purpose)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS video_artifact_namespaces (
        video_id INTEGER PRIMARY KEY,
        scheme TEXT NOT NULL,
        relative_root TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        FOREIGN KEY(video_id) REFERENCES videos(id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sources_organization
    ON sources(organization_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_source_import_links_source
    ON source_import_links(source_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_affiliation_claims_organization
    ON organization_affiliation_claims(organization_id, id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pastor_affiliations_pastor
    ON pastor_organization_affiliations(pastor_id, organization_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_video_target_contexts_pastor
    ON video_target_contexts(pastor_id, video_id)
    """,
    *_AFFILIATION_REVIEW_DDL,
)


@dataclass(frozen=True, slots=True)
class SourceOwnershipBackfillResult:
    organizations_created: int
    external_refs_created: int
    snapshots_created: int
    source_links_created: int
    affiliation_claims_created: int
    source_events_created: int
    source_target_policies_created: int
    video_target_contexts_created: int
    artifact_namespaces_created: int


@dataclass(frozen=True, slots=True)
class SourceOwnershipAudit:
    foreign_key_violations: int
    imported_refs_without_external_ref: int
    imported_links_without_organization: int
    legacy_sources_without_target_policy: int
    legacy_videos_without_target_context: int
    videos_without_artifact_namespace: int
    artifact_namespace_path_mismatches: int

    @property
    def ok(self) -> bool:
        return not any(
            (
                self.foreign_key_violations,
                self.imported_refs_without_external_ref,
                self.imported_links_without_organization,
                self.legacy_sources_without_target_policy,
                self.legacy_videos_without_target_context,
                self.videos_without_artifact_namespace,
                self.artifact_namespace_path_mismatches,
            )
        )


def apply_source_ownership_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """
    )
    foundation_applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version = ?",
        (1,),
    ).fetchone()
    if foundation_applied is None:
        source_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(sources)").fetchall()
        }
        if "organization_id" not in source_columns:
            connection.execute(
                "ALTER TABLE sources ADD COLUMN organization_id INTEGER NULL "
                "REFERENCES organizations(id)"
            )
        for statement in _SOURCE_OWNERSHIP_DDL:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (
                1,
                "source_ownership_foundation",
                utc_now().isoformat(),
            ),
        )

    nullable_applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version = 2"
    ).fetchone()
    if nullable_applied is None:
        _relax_legacy_owner_nullability(connection)
        connection.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (2, ?, ?)",
            ("nullable_legacy_target_projections", utc_now().isoformat()),
        )

    review_applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version = 3"
    ).fetchone()
    if review_applied is None:
        for statement in _AFFILIATION_REVIEW_DDL:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (3, ?, ?)",
            ("affiliation_claim_review_events", utc_now().isoformat()),
        )


def backfill_source_ownership(connection: sqlite3.Connection) -> SourceOwnershipBackfillResult:
    before = _backfill_counts(connection)
    _backfill_imported_organizations(connection)
    _backfill_target_contexts(connection)
    _backfill_artifact_namespaces(connection)
    after = _backfill_counts(connection)
    return SourceOwnershipBackfillResult(
        **{key: after[key] - before[key] for key in before}
    )


def audit_source_ownership(
    connection: sqlite3.Connection,
    *,
    app_root: Path | None = None,
) -> SourceOwnershipAudit:
    foreign_key_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    imported_refs_without_external_ref = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM source_import_refs legacy
            LEFT JOIN organization_external_refs ref
              ON ref.provider = legacy.provider
             AND ref.external_entity_key = legacy.external_entity_key
            WHERE ref.id IS NULL
            """
        ).fetchone()[0]
    )
    imported_links_without_organization = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM source_import_links link
            JOIN organization_external_refs ref
              ON ref.id = link.organization_external_ref_id
            LEFT JOIN sources source ON source.id = link.source_id
            WHERE source.organization_id IS NULL
               OR source.organization_id <> ref.organization_id
            """
        ).fetchone()[0]
    )
    legacy_sources_without_target_policy = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM sources source
            WHERE source.pastor_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM source_target_policies policy
                  WHERE policy.source_id = source.id
                    AND policy.pastor_id = source.pastor_id
                    AND policy.purpose = 'legacy_primary_target'
                    AND policy.active = 1
              )
            """
        ).fetchone()[0]
    )
    legacy_videos_without_target_context = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM videos video
            WHERE video.pastor_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM video_target_contexts context
                  WHERE context.video_id = video.id
                    AND context.pastor_id = video.pastor_id
                    AND context.purpose = 'legacy_primary_target'
              )
            """
        ).fetchone()[0]
    )
    videos_without_artifact_namespace = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM videos video
            LEFT JOIN video_artifact_namespaces namespace
              ON namespace.video_id = video.id
            WHERE namespace.video_id IS NULL
            """
        ).fetchone()[0]
    )
    mismatches = 0
    if app_root is not None:
        rows = connection.execute(
            """
            SELECT namespace.relative_root, namespace.scheme, pastor.slug,
                   video.youtube_video_id
            FROM video_artifact_namespaces namespace
            JOIN videos video ON video.id = namespace.video_id
            LEFT JOIN pastors pastor ON pastor.id = video.pastor_id
            """
        ).fetchall()
        for row in rows:
            if str(row["scheme"]) != "legacy_pastor_v1" or row["slug"] is None:
                continue
            expected = app_root / "pastors" / str(row["slug"]) / "videos" / str(
                row["youtube_video_id"]
            )
            actual = app_root / PurePosixPath(str(row["relative_root"]))
            if actual != expected:
                mismatches += 1
    return SourceOwnershipAudit(
        foreign_key_violations=foreign_key_violations,
        imported_refs_without_external_ref=imported_refs_without_external_ref,
        imported_links_without_organization=imported_links_without_organization,
        legacy_sources_without_target_policy=legacy_sources_without_target_policy,
        legacy_videos_without_target_context=legacy_videos_without_target_context,
        videos_without_artifact_namespace=videos_without_artifact_namespace,
        artifact_namespace_path_mismatches=mismatches,
    )


def _backfill_imported_organizations(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT id, source_id, provider, external_entity_key, external_record_id,
               imported_fingerprint, import_payload_json, external_updated_at,
               imported_at
        FROM source_import_refs
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        payload = _json_object(str(row["import_payload_json"]))
        organization_name = _nonempty_text(payload.get("church_name")) or (
            f"Imported organization {row['external_record_id'] or row['id']}"
        )
        organization_id = _ensure_imported_organization(
            connection,
            provider=str(row["provider"]),
            external_entity_key=str(row["external_entity_key"]),
            external_record_id=(
                str(row["external_record_id"])
                if row["external_record_id"] is not None
                else None
            ),
            display_name=organization_name,
            added_at=str(row["imported_at"]),
        )
        external_ref = connection.execute(
            """
            SELECT id FROM organization_external_refs
            WHERE provider = ? AND external_entity_key = ?
            """,
            (str(row["provider"]), str(row["external_entity_key"])),
        ).fetchone()
        assert external_ref is not None
        external_ref_id = int(external_ref["id"])
        connection.execute(
            """
            INSERT OR IGNORE INTO external_record_snapshots (
                organization_external_ref_id, imported_fingerprint,
                import_payload_json, external_updated_at, observed_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                external_ref_id,
                str(row["imported_fingerprint"]),
                str(row["import_payload_json"]),
                row["external_updated_at"],
                str(row["imported_at"]),
            ),
        )
        snapshot = connection.execute(
            """
            SELECT id FROM external_record_snapshots
            WHERE organization_external_ref_id = ? AND imported_fingerprint = ?
            """,
            (external_ref_id, str(row["imported_fingerprint"])),
        ).fetchone()
        assert snapshot is not None
        snapshot_id = int(snapshot["id"])
        connection.execute(
            """
            INSERT OR IGNORE INTO source_import_links (
                source_id, organization_external_ref_id, channel_identity_key, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                int(row["source_id"]),
                external_ref_id,
                _nonempty_text(payload.get("channel_key")),
                str(row["imported_at"]),
            ),
        )
        source = connection.execute(
            "SELECT organization_id FROM sources WHERE id = ?",
            (int(row["source_id"]),),
        ).fetchone()
        if source is not None and source["organization_id"] is None:
            connection.execute(
                "UPDATE sources SET organization_id = ? WHERE id = ?",
                (organization_id, int(row["source_id"])),
            )
        event_fingerprint = stable_fingerprint(
            {
                "action": "attach",
                "source_id": int(row["source_id"]),
                "organization_id": organization_id,
                "snapshot_id": snapshot_id,
                "origin": "legacy_import_backfill",
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
                int(row["source_id"]),
                organization_id,
                "migration",
                "Backfilled from legacy source_import_refs",
                snapshot_id,
                event_fingerprint,
                str(row["imported_at"]),
            ),
        )
        pastor_name = _nonempty_text(payload.get("pastor_name"))
        if pastor_name is not None:
            claim_fingerprint = stable_fingerprint(
                {
                    "organization_id": organization_id,
                    "snapshot_id": snapshot_id,
                    "claimed_person_name": pastor_name,
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
                    pastor_name,
                    claim_fingerprint,
                    str(row["imported_at"]),
                ),
            )


def _backfill_target_contexts(connection: sqlite3.Connection) -> None:
    now = utc_now().isoformat()
    sources = connection.execute(
        "SELECT id, pastor_id, added_at FROM sources WHERE pastor_id IS NOT NULL ORDER BY id"
    ).fetchall()
    for source in sources:
        connection.execute(
            """
            INSERT OR IGNORE INTO source_target_policies (
                source_id, pastor_id, purpose, origin_kind, active, created_at
            ) VALUES (?, ?, 'legacy_primary_target', 'legacy_projection', 1, ?)
            """,
            (
                int(source["id"]),
                int(source["pastor_id"]),
                str(source["added_at"] or now),
            ),
        )
    videos = connection.execute(
        """
        SELECT id, source_id, pastor_id
        FROM videos
        WHERE pastor_id IS NOT NULL
        ORDER BY id
        """
    ).fetchall()
    for video in videos:
        policy = connection.execute(
            """
            SELECT id FROM source_target_policies
            WHERE source_id = ? AND pastor_id = ?
              AND purpose = 'legacy_primary_target'
            """,
            (int(video["source_id"]), int(video["pastor_id"])),
        ).fetchone()
        connection.execute(
            """
            INSERT OR IGNORE INTO video_target_contexts (
                video_id, pastor_id, source_target_policy_id, purpose,
                origin_kind, created_at
            ) VALUES (?, ?, ?, 'legacy_primary_target', 'legacy_projection', ?)
            """,
            (
                int(video["id"]),
                int(video["pastor_id"]),
                int(policy["id"]) if policy is not None else None,
                now,
            ),
        )


def _backfill_artifact_namespaces(connection: sqlite3.Connection) -> None:
    now = utc_now().isoformat()
    rows = connection.execute(
        """
        SELECT video.id, video.youtube_video_id, pastor.slug
        FROM videos video
        LEFT JOIN pastors pastor ON pastor.id = video.pastor_id
        ORDER BY video.id
        """
    ).fetchall()
    for row in rows:
        if row["slug"] is not None:
            scheme = "legacy_pastor_v1"
            relative_root = str(
                PurePosixPath("pastors")
                / str(row["slug"])
                / "videos"
                / str(row["youtube_video_id"])
            )
        else:
            scheme = "video_v1"
            relative_root = str(
                PurePosixPath("artifacts") / "videos" / str(row["youtube_video_id"])
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO video_artifact_namespaces (
                video_id, scheme, relative_root, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (int(row["id"]), scheme, relative_root, now),
        )


def _ensure_imported_organization(
    connection: sqlite3.Connection,
    *,
    provider: str,
    external_entity_key: str,
    external_record_id: str | None,
    display_name: str,
    added_at: str,
) -> int:
    existing = connection.execute(
        """
        SELECT organization_id FROM organization_external_refs
        WHERE provider = ? AND external_entity_key = ?
        """,
        (provider, external_entity_key),
    ).fetchone()
    if existing is not None:
        return int(existing["organization_id"])

    base = f"churchdb-org-{external_record_id}" if external_record_id else "churchdb-org"
    slug = _available_slug(connection, base, external_entity_key)
    cursor = connection.execute(
        """
        INSERT INTO organizations (
            slug, display_name, organization_type, added_at, notes
        ) VALUES (?, ?, 'church', ?, ?)
        """,
        (
            slug,
            display_name,
            added_at,
            f"Imported from {provider}",
        ),
    )
    organization_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO organization_external_refs (
            organization_id, provider, external_entity_key, external_record_id, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            organization_id,
            provider,
            external_entity_key,
            external_record_id,
            added_at,
        ),
    )
    return organization_id


def _available_slug(
    connection: sqlite3.Connection,
    base: str,
    external_entity_key: str,
) -> str:
    row = connection.execute(
        "SELECT 1 FROM organizations WHERE slug = ?",
        (base,),
    ).fetchone()
    if row is None:
        return base
    suffix = hashlib.sha256(external_entity_key.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{suffix}"


def _relax_legacy_owner_nullability(connection: sqlite3.Connection) -> None:
    if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 0:
        raise RuntimeError(
            "The nullable legacy-owner migration requires foreign-key enforcement "
            "to remain disabled until the existing database has been audited"
        )
    source_info = {
        str(row["name"]): row
        for row in connection.execute("PRAGMA table_info(sources)").fetchall()
    }
    if bool(source_info["pastor_id"]["notnull"]):
        connection.execute(
            """
            CREATE TABLE sources_nullable_owner (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pastor_id INTEGER NULL,
                url TEXT NOT NULL UNIQUE,
                source_identity_key TEXT NULL,
                source_type TEXT NOT NULL,
                added_at TEXT NOT NULL,
                notes TEXT NULL,
                organization_id INTEGER NULL,
                FOREIGN KEY(pastor_id) REFERENCES pastors(id),
                FOREIGN KEY(organization_id) REFERENCES organizations(id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO sources_nullable_owner (
                id, pastor_id, url, source_identity_key, source_type,
                added_at, notes, organization_id
            )
            SELECT id, pastor_id, url, source_identity_key, source_type,
                   added_at, notes, organization_id
            FROM sources
            """
        )
        connection.execute("DROP TABLE sources")
        connection.execute("ALTER TABLE sources_nullable_owner RENAME TO sources")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_identity_key
            ON sources(source_identity_key)
            WHERE source_identity_key IS NOT NULL
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_sources_organization ON sources(organization_id)"
        )

    video_info = {
        str(row["name"]): row
        for row in connection.execute("PRAGMA table_info(videos)").fetchall()
    }
    if bool(video_info["pastor_id"]["notnull"]):
        connection.execute(
            """
            CREATE TABLE videos_nullable_owner (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                pastor_id INTEGER NULL,
                youtube_video_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                channel_name TEXT NULL,
                published_at TEXT NULL,
                duration_seconds INTEGER NULL,
                status TEXT NOT NULL,
                failure_reason TEXT NULL,
                FOREIGN KEY(source_id) REFERENCES sources(id),
                FOREIGN KEY(pastor_id) REFERENCES pastors(id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO videos_nullable_owner (
                id, source_id, pastor_id, youtube_video_id, title, url,
                channel_name, published_at, duration_seconds, status, failure_reason
            )
            SELECT id, source_id, pastor_id, youtube_video_id, title, url,
                   channel_name, published_at, duration_seconds, status, failure_reason
            FROM videos
            """
        )
        connection.execute("DROP TABLE videos")
        connection.execute("ALTER TABLE videos_nullable_owner RENAME TO videos")


def _backfill_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = {
        "organizations_created": "organizations",
        "external_refs_created": "organization_external_refs",
        "snapshots_created": "external_record_snapshots",
        "source_links_created": "source_import_links",
        "affiliation_claims_created": "organization_affiliation_claims",
        "source_events_created": "source_organization_events",
        "source_target_policies_created": "source_target_policies",
        "video_target_contexts_created": "video_target_contexts",
        "artifact_namespaces_created": "video_artifact_namespaces",
    }
    return {
        key: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for key, table in tables.items()
    }


def _json_object(value: str) -> dict[str, object]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _nonempty_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def stable_fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
