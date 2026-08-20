from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from pastor_transcript_extractor.models import (
    ExcludedVideo,
    ExtractionResult,
    IdentityAction,
    IdentityAssessment,
    IdentityEvidence,
    IdentityState,
    MediaAcquisitionAttempt,
    MediaArchiveAttempt,
    MediaArchiveDestination,
    MediaArchiveEntry,
    MediaArtifact,
    MetadataArtifact,
    Organization,
    Pastor,
    PastorOrganizationAffiliation,
    ReferencePanel,
    ReferencePanelMembershipEvent,
    ReferencePanelSnapshot,
    ReferencePanelSnapshotMember,
    SpeakerNameClaim,
    SpeakerObservation,
    SpeakerProfile,
    ReviewResult,
    SermonAnalysisEvidence,
    SermonAnalysisMeasurement,
    SermonAnalysisRun,
    SpeakerProfileAnalysisMeasurement,
    SpeakerProfileAnalysisRun,
    Source,
    SourceType,
    TranscriptSegment,
    TranscriptArtifact,
    TranscriptSourceKind,
    TranscriptSegmentLabel,
    Video,
    VideoStatus,
    parse_datetime,
    utc_now,
)
from pastor_transcript_extractor.source_ownership import (
    apply_source_ownership_schema,
    backfill_source_ownership,
    stable_fingerprint,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS pastors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    added_at TEXT NOT NULL,
    notes TEXT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pastor_id INTEGER NULL,
    url TEXT NOT NULL UNIQUE,
    source_identity_key TEXT NULL,
    source_type TEXT NOT NULL,
    added_at TEXT NOT NULL,
    notes TEXT NULL,
    processing_enabled INTEGER NOT NULL DEFAULT 1 CHECK(processing_enabled IN (0, 1)),
    FOREIGN KEY(pastor_id) REFERENCES pastors(id)
);

CREATE TABLE IF NOT EXISTS source_import_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    pastor_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    external_entity_key TEXT NOT NULL,
    external_record_id TEXT NULL,
    imported_fingerprint TEXT NOT NULL,
    import_payload_json TEXT NOT NULL,
    external_updated_at TEXT NULL,
    imported_at TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES sources(id),
    FOREIGN KEY(pastor_id) REFERENCES pastors(id),
    UNIQUE(provider, external_entity_key)
);

CREATE TABLE IF NOT EXISTS videos (
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
);

CREATE TABLE IF NOT EXISTS transcript_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    source_kind TEXT NOT NULL,
    raw_json_path TEXT NULL,
    raw_text_path TEXT NULL,
    audio_path TEXT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id)
);

CREATE TABLE IF NOT EXISTS media_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    parent_media_artifact_id INTEGER NULL,
    artifact_kind TEXT NOT NULL CHECK(artifact_kind IN ('source_audio', 'normalized_audio')),
    provenance_kind TEXT NOT NULL CHECK(provenance_kind IN ('original_download', 'derived', 'reconstructed_existing')),
    artifact_path TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    duration_seconds REAL NULL,
    format_name TEXT NULL,
    sample_rate_hz INTEGER NULL,
    channel_count INTEGER NULL,
    acquisition_tool TEXT NOT NULL,
    acquisition_tool_version TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(parent_media_artifact_id) REFERENCES media_artifacts(id)
);

CREATE TABLE IF NOT EXISTS media_acquisition_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    target_kind TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('verified', 'unavailable', 'failed')),
    reason_code TEXT NOT NULL,
    detail TEXT NULL,
    media_artifact_id INTEGER NULL,
    service_version TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(media_artifact_id) REFERENCES media_artifacts(id)
);

CREATE TABLE IF NOT EXISTS media_archive_destinations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archive_root TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL CHECK(active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_archive_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_artifact_id INTEGER NOT NULL UNIQUE,
    destination_id INTEGER NOT NULL,
    source_path TEXT NOT NULL,
    archive_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'archived', 'failed')),
    archived_at TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(media_artifact_id) REFERENCES media_artifacts(id),
    FOREIGN KEY(destination_id) REFERENCES media_archive_destinations(id)
);

CREATE TABLE IF NOT EXISTS media_archive_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archive_entry_id INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN (
        'archived', 'already_archived', 'destination_unavailable', 'failed'
    )),
    detail TEXT NULL,
    attempted_at TEXT NOT NULL,
    FOREIGN KEY(archive_entry_id) REFERENCES media_archive_entries(id)
);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    artifact_id INTEGER NOT NULL,
    start_seconds REAL NULL,
    end_seconds REAL NULL,
    text TEXT NOT NULL,
    speaker_hint TEXT NULL,
    label TEXT NOT NULL,
    confidence REAL NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(artifact_id) REFERENCES transcript_artifacts(id)
);

CREATE TABLE IF NOT EXISTS extraction_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    proposed_text_path TEXT NOT NULL,
    proposed_json_path TEXT NULL,
    notes TEXT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id)
);

CREATE TABLE IF NOT EXISTS review_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    extraction_result_id INTEGER NOT NULL,
    approved_text_path TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    review_notes TEXT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(extraction_result_id) REFERENCES extraction_results(id)
);

CREATE TABLE IF NOT EXISTS sermon_analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    extraction_result_id INTEGER NOT NULL,
    analyzer_key TEXT NOT NULL,
    analyzer_version TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_content_sha256 TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(extraction_result_id) REFERENCES extraction_results(id)
);

CREATE TABLE IF NOT EXISTS sermon_analysis_measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_run_id INTEGER NOT NULL,
    metric_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    unit TEXT NULL,
    FOREIGN KEY(analysis_run_id) REFERENCES sermon_analysis_runs(id) ON DELETE CASCADE,
    UNIQUE(analysis_run_id, metric_key)
);

CREATE TABLE IF NOT EXISTS sermon_analysis_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_run_id INTEGER NOT NULL,
    evidence_kind TEXT NOT NULL,
    evidence_key TEXT NOT NULL,
    segment_index INTEGER NULL,
    start_seconds REAL NULL,
    end_seconds REAL NULL,
    char_start INTEGER NULL,
    char_end INTEGER NULL,
    excerpt TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY(analysis_run_id) REFERENCES sermon_analysis_runs(id) ON DELETE CASCADE,
    UNIQUE(analysis_run_id, evidence_key)
);

CREATE INDEX IF NOT EXISTS idx_sermon_analysis_runs_video
ON sermon_analysis_runs(video_id, analyzer_key, id);

CREATE TABLE IF NOT EXISTS speaker_profile_analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    analyzer_key TEXT NOT NULL,
    analyzer_version TEXT NOT NULL,
    membership_fingerprint TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(profile_id) REFERENCES speaker_profiles(id)
);

CREATE TABLE IF NOT EXISTS speaker_profile_analysis_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_analysis_run_id INTEGER NOT NULL,
    sermon_analysis_run_id INTEGER NOT NULL,
    video_id INTEGER NOT NULL,
    FOREIGN KEY(profile_analysis_run_id)
        REFERENCES speaker_profile_analysis_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(sermon_analysis_run_id) REFERENCES sermon_analysis_runs(id),
    FOREIGN KEY(video_id) REFERENCES videos(id),
    UNIQUE(profile_analysis_run_id, sermon_analysis_run_id)
);

CREATE TABLE IF NOT EXISTS speaker_profile_analysis_measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_analysis_run_id INTEGER NOT NULL,
    metric_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    unit TEXT NULL,
    FOREIGN KEY(profile_analysis_run_id)
        REFERENCES speaker_profile_analysis_runs(id) ON DELETE CASCADE,
    UNIQUE(profile_analysis_run_id, metric_key)
);

CREATE INDEX IF NOT EXISTS idx_speaker_profile_analysis_runs_profile
ON speaker_profile_analysis_runs(profile_id, analyzer_key, id);

CREATE TABLE IF NOT EXISTS reference_panels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reference_panel_membership_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_id INTEGER NOT NULL,
    profile_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('attach', 'detach')),
    reviewer TEXT NOT NULL,
    rationale TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(panel_id) REFERENCES reference_panels(id),
    FOREIGN KEY(profile_id) REFERENCES speaker_profiles(id)
);

CREATE INDEX IF NOT EXISTS idx_reference_panel_membership_effective
ON reference_panel_membership_events(panel_id, profile_id, id);

CREATE TABLE IF NOT EXISTS reference_panel_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_id INTEGER NOT NULL,
    profile_analyzer_key TEXT NOT NULL,
    profile_analyzer_version TEXT NOT NULL,
    feature_schema_version TEXT NOT NULL,
    comparison_feature_names_json TEXT NOT NULL,
    coverage_feature_names_json TEXT NOT NULL,
    feature_family_assignments_json TEXT NOT NULL,
    panel_feature_statistics_json TEXT NOT NULL,
    eligibility_policy_version TEXT NOT NULL,
    eligibility_policy_json TEXT NOT NULL,
    snapshot_analyzer_version TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(panel_id) REFERENCES reference_panels(id)
);

CREATE INDEX IF NOT EXISTS idx_reference_panel_snapshots_panel
ON reference_panel_snapshots(panel_id, id);

CREATE TABLE IF NOT EXISTS reference_panel_snapshot_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    requested_profile_ids_json TEXT NOT NULL,
    membership_event_ids_json TEXT NOT NULL,
    resolved_profile_id INTEGER NOT NULL,
    resolved_display_label TEXT NOT NULL,
    profile_analysis_run_id INTEGER NULL,
    eligibility_status TEXT NOT NULL CHECK(eligibility_status IN ('eligible', 'ineligible')),
    exclusion_reasons_json TEXT NOT NULL,
    comparison_values_json TEXT NOT NULL,
    coverage_diagnostics_json TEXT NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES reference_panel_snapshots(id) ON DELETE CASCADE,
    FOREIGN KEY(resolved_profile_id) REFERENCES speaker_profiles(id),
    FOREIGN KEY(profile_analysis_run_id) REFERENCES speaker_profile_analysis_runs(id),
    UNIQUE(snapshot_id, resolved_profile_id)
);

CREATE TABLE IF NOT EXISTS excluded_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pastor_id INTEGER NULL,
    source_id INTEGER NULL,
    youtube_video_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    excluded_at TEXT NOT NULL,
    notes TEXT NULL
);

CREATE TABLE IF NOT EXISTS metadata_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    source_kind TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    UNIQUE(video_id, content_sha256, extractor_version)
);

CREATE TABLE IF NOT EXISTS identity_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    target_pastor_id INTEGER NOT NULL,
    evidence_type TEXT NOT NULL,
    source_family TEXT NOT NULL,
    polarity TEXT NOT NULL,
    strength TEXT NOT NULL,
    scope TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(target_pastor_id) REFERENCES pastors(id)
);

CREATE TABLE IF NOT EXISTS identity_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    target_pastor_id INTEGER NOT NULL,
    extraction_result_id INTEGER NOT NULL,
    state TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    shadow_mode INTEGER NOT NULL,
    policy_version TEXT NOT NULL,
    evidence_ledger_path TEXT NOT NULL,
    assessment_path TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(target_pastor_id) REFERENCES pastors(id),
    FOREIGN KEY(extraction_result_id) REFERENCES extraction_results(id)
);

CREATE TABLE IF NOT EXISTS speaker_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_key TEXT NOT NULL UNIQUE,
    display_label TEXT NULL,
    lifecycle_state TEXT NOT NULL,
    created_reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pastor_speaker_bindings (
    pastor_id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL UNIQUE,
    binding_kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(pastor_id) REFERENCES pastors(id),
    FOREIGN KEY(profile_id) REFERENCES speaker_profiles(id)
);

CREATE TABLE IF NOT EXISTS speaker_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    extraction_result_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    multiplicity_state TEXT NOT NULL,
    start_seconds REAL NOT NULL,
    end_seconds REAL NOT NULL,
    artifact_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(extraction_result_id) REFERENCES extraction_results(id)
);

CREATE TABLE IF NOT EXISTS speaker_name_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    observation_id INTEGER NULL,
    display_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    claim_kind TEXT NOT NULL,
    channel TEXT NOT NULL,
    explicit_speaker_attribution INTEGER NOT NULL,
    correlation_group_id TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    claim_fingerprint TEXT NOT NULL UNIQUE,
    extractor_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(observation_id) REFERENCES speaker_observations(id)
);

CREATE TABLE IF NOT EXISTS profile_observation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    observation_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('attach', 'detach')),
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(profile_id) REFERENCES speaker_profiles(id),
    FOREIGN KEY(observation_id) REFERENCES speaker_observations(id)
);

CREATE TABLE IF NOT EXISTS speaker_profile_creation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL UNIQUE,
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(profile_id) REFERENCES speaker_profiles(id)
);

CREATE TABLE IF NOT EXISTS speaker_profile_discovery_promotions (
    profile_id INTEGER PRIMARY KEY,
    component_id TEXT NOT NULL UNIQUE,
    discovery_result_sha256 TEXT NOT NULL,
    discovery_artifact_path TEXT NOT NULL,
    seed_observation_ids_json TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(profile_id) REFERENCES speaker_profiles(id)
);

CREATE TABLE IF NOT EXISTS speaker_profile_candidate_confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    observation_id INTEGER NOT NULL,
    association_result_sha256 TEXT NOT NULL,
    association_artifact_path TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(profile_id) REFERENCES speaker_profiles(id),
    FOREIGN KEY(observation_id) REFERENCES speaker_observations(id),
    UNIQUE(profile_id, observation_id)
);

CREATE TABLE IF NOT EXISTS speaker_machine_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER NOT NULL,
    profile_id INTEGER NOT NULL,
    candidate_input_fingerprint TEXT NOT NULL,
    association_result_sha256 TEXT NOT NULL,
    association_artifact_path TEXT NOT NULL,
    model_fingerprint TEXT NOT NULL,
    policy_fingerprint TEXT NOT NULL,
    profile_snapshot_fingerprint TEXT NOT NULL,
    exemplar_fingerprints_json TEXT NOT NULL,
    same_exemplar_count INTEGER NOT NULL,
    different_exemplar_count INTEGER NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('proposed_match')),
    evidence_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(observation_id) REFERENCES speaker_observations(id),
    FOREIGN KEY(profile_id) REFERENCES speaker_profiles(id)
);

CREATE TABLE IF NOT EXISTS speaker_machine_assignment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_evidence_id INTEGER NOT NULL,
    observation_id INTEGER NOT NULL,
    profile_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('activate', 'revoke', 'confirm')),
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(machine_evidence_id) REFERENCES speaker_machine_evidence(id),
    FOREIGN KEY(observation_id) REFERENCES speaker_observations(id),
    FOREIGN KEY(profile_id) REFERENCES speaker_profiles(id)
);

CREATE TABLE IF NOT EXISTS speaker_observation_review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN (
        'qualified_single_speaker',
        'unresolved',
        'multiple_speakers',
        'invalid'
    )),
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(observation_id) REFERENCES speaker_observations(id)
);

CREATE TABLE IF NOT EXISTS speaker_observation_grouping_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('defer', 'clear')),
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(observation_id) REFERENCES speaker_observations(id)
);

CREATE TABLE IF NOT EXISTS speaker_observation_difference_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_a_id INTEGER NOT NULL,
    observation_b_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('assert', 'clear')),
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(observation_a_id) REFERENCES speaker_observations(id),
    FOREIGN KEY(observation_b_id) REFERENCES speaker_observations(id),
    CHECK(observation_a_id < observation_b_id)
);

CREATE TABLE IF NOT EXISTS profile_name_claim_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NULL,
    claim_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('attach', 'reject')),
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(profile_id) REFERENCES speaker_profiles(id),
    FOREIGN KEY(claim_id) REFERENCES speaker_name_claims(id),
    CHECK((action = 'attach' AND profile_id IS NOT NULL) OR action = 'reject')
);

CREATE TABLE IF NOT EXISTS speaker_profile_redirect_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_profile_id INTEGER NOT NULL,
    to_profile_id INTEGER NULL,
    action TEXT NOT NULL CHECK(action IN ('redirect', 'clear')),
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(from_profile_id) REFERENCES speaker_profiles(id),
    FOREIGN KEY(to_profile_id) REFERENCES speaker_profiles(id),
    CHECK((action = 'redirect' AND to_profile_id IS NOT NULL) OR action = 'clear')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_identity_evidence_artifact
ON identity_evidence(video_id, target_pastor_id, evidence_type, artifact_path);

CREATE INDEX IF NOT EXISTS idx_speaker_claims_video
ON speaker_name_claims(video_id, observation_id);

CREATE INDEX IF NOT EXISTS idx_media_artifacts_video_kind
ON media_artifacts(video_id, artifact_kind, id);

CREATE INDEX IF NOT EXISTS idx_media_attempts_video
ON media_acquisition_attempts(video_id, id);

CREATE INDEX IF NOT EXISTS idx_media_archive_entries_status
ON media_archive_entries(status, id);

CREATE INDEX IF NOT EXISTS idx_media_archive_attempts_entry
ON media_archive_attempts(archive_entry_id, id);

CREATE INDEX IF NOT EXISTS idx_profile_observation_events_pair
ON profile_observation_events(profile_id, observation_id, id);

CREATE INDEX IF NOT EXISTS idx_speaker_machine_evidence_observation
ON speaker_machine_evidence(observation_id, id);

CREATE INDEX IF NOT EXISTS idx_speaker_machine_assignment_events_evidence
ON speaker_machine_assignment_events(machine_evidence_id, id);

CREATE INDEX IF NOT EXISTS idx_speaker_observation_review_events_observation
ON speaker_observation_review_events(observation_id, id);

CREATE INDEX IF NOT EXISTS idx_speaker_observation_grouping_events_observation
ON speaker_observation_grouping_events(observation_id, id);

CREATE INDEX IF NOT EXISTS idx_speaker_observation_difference_events_pair
ON speaker_observation_difference_events(observation_a_id, observation_b_id, id);

CREATE INDEX IF NOT EXISTS idx_profile_redirect_events_source
ON speaker_profile_redirect_events(from_profile_id, id);

CREATE INDEX IF NOT EXISTS idx_source_import_refs_provider
ON source_import_refs(provider, source_id);
"""


class Database:
    def __init__(self, database_path: Path, *, readonly: bool = False) -> None:
        self.database_path = database_path
        self.readonly = readonly

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if self.readonly:
            uri = f"{self.database_path.expanduser().resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, timeout=30.0, uri=True)
        else:
            connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        try:
            if self.readonly:
                connection.execute("PRAGMA query_only = ON")
            else:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA busy_timeout = 30000")
            yield connection
            if not self.readonly:
                connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._ensure_pastor_columns(connection)
            apply_source_ownership_schema(connection)
            self._ensure_source_processing_column(connection)
            backfill_source_ownership(connection)

    def _ensure_pastor_columns(self, connection: sqlite3.Connection) -> None:
        source_columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(sources)").fetchall()}
        if "pastor_id" not in source_columns:
            connection.execute("ALTER TABLE sources ADD COLUMN pastor_id INTEGER NULL")
        if "source_identity_key" not in source_columns:
            connection.execute("ALTER TABLE sources ADD COLUMN source_identity_key TEXT NULL")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_identity_key
            ON sources(source_identity_key)
            WHERE source_identity_key IS NOT NULL
            """
        )

        video_columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(videos)").fetchall()}
        if "pastor_id" not in video_columns:
            connection.execute("ALTER TABLE videos ADD COLUMN pastor_id INTEGER NULL")

    def _ensure_source_processing_column(self, connection: sqlite3.Connection) -> None:
        source_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(sources)").fetchall()
        }
        if "processing_enabled" not in source_columns:
            connection.execute(
                "ALTER TABLE sources ADD COLUMN processing_enabled INTEGER NOT NULL DEFAULT 1 "
                "CHECK(processing_enabled IN (0, 1))"
            )

    def _source_from_row(self, row: sqlite3.Row) -> Source:
        return Source(
            id=int(row["id"]),
            pastor_id=row["pastor_id"],
            organization_id=(
                row["organization_id"] if "organization_id" in row.keys() else None
            ),
            url=str(row["url"]),
            source_type=SourceType(str(row["source_type"])),
            added_at=parse_datetime(str(row["added_at"])) or utc_now(),
            notes=row["notes"],
            source_identity_key=(
                row["source_identity_key"] if "source_identity_key" in row.keys() else None
            ),
            processing_enabled=(
                bool(row["processing_enabled"])
                if "processing_enabled" in row.keys()
                else True
            ),
        )

    def _pastor_from_row(self, row: sqlite3.Row) -> Pastor:
        return Pastor(
            id=int(row["id"]),
            slug=str(row["slug"]),
            display_name=str(row["display_name"]),
            added_at=parse_datetime(str(row["added_at"])) or utc_now(),
            notes=row["notes"],
        )

    def _organization_from_row(self, row: sqlite3.Row) -> Organization:
        return Organization(
            id=int(row["id"]),
            slug=str(row["slug"]),
            display_name=str(row["display_name"]),
            organization_type=str(row["organization_type"]),
            added_at=parse_datetime(str(row["added_at"])) or utc_now(),
            notes=row["notes"],
        )

    def _pastor_organization_affiliation_from_row(
        self, row: sqlite3.Row
    ) -> PastorOrganizationAffiliation:
        return PastorOrganizationAffiliation(
            id=int(row["id"]),
            pastor_id=int(row["pastor_id"]),
            organization_id=int(row["organization_id"]),
            role_key=str(row["role_key"]),
            role_label=str(row["role_label"]),
            started_on=row["started_on"],
            ended_on=row["ended_on"],
            temporal_status=str(row["temporal_status"]),
            provenance_kind=str(row["provenance_kind"]),
            affiliation_claim_id=(
                int(row["affiliation_claim_id"])
                if row["affiliation_claim_id"] is not None
                else None
            ),
            notes=row["notes"],
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _video_from_row(self, row: sqlite3.Row) -> Video:
        return Video(
            id=int(row["id"]),
            source_id=int(row["source_id"]),
            pastor_id=row["pastor_id"],
            youtube_video_id=str(row["youtube_video_id"]),
            title=str(row["title"]),
            url=str(row["url"]),
            channel_name=row["channel_name"],
            published_at=parse_datetime(row["published_at"]),
            duration_seconds=row["duration_seconds"],
            status=VideoStatus(str(row["status"])),
            failure_reason=row["failure_reason"],
        )

    def _transcript_artifact_from_row(self, row: sqlite3.Row) -> TranscriptArtifact:
        return TranscriptArtifact(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            source_kind=TranscriptSourceKind(str(row["source_kind"])),
            raw_json_path=row["raw_json_path"],
            raw_text_path=row["raw_text_path"],
            audio_path=row["audio_path"],
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _media_artifact_from_row(self, row: sqlite3.Row) -> MediaArtifact:
        return MediaArtifact(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            parent_media_artifact_id=(
                int(row["parent_media_artifact_id"])
                if row["parent_media_artifact_id"] is not None
                else None
            ),
            artifact_kind=str(row["artifact_kind"]),
            provenance_kind=str(row["provenance_kind"]),
            artifact_path=str(row["artifact_path"]),
            manifest_path=str(row["manifest_path"]),
            content_sha256=str(row["content_sha256"]),
            byte_size=int(row["byte_size"]),
            duration_seconds=(
                float(row["duration_seconds"]) if row["duration_seconds"] is not None else None
            ),
            format_name=row["format_name"],
            sample_rate_hz=(
                int(row["sample_rate_hz"]) if row["sample_rate_hz"] is not None else None
            ),
            channel_count=(
                int(row["channel_count"]) if row["channel_count"] is not None else None
            ),
            acquisition_tool=str(row["acquisition_tool"]),
            acquisition_tool_version=str(row["acquisition_tool_version"]),
            input_fingerprint=str(row["input_fingerprint"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _media_acquisition_attempt_from_row(
        self, row: sqlite3.Row
    ) -> MediaAcquisitionAttempt:
        return MediaAcquisitionAttempt(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            target_kind=str(row["target_kind"]),
            outcome=str(row["outcome"]),
            reason_code=str(row["reason_code"]),
            detail=row["detail"],
            media_artifact_id=(
                int(row["media_artifact_id"])
                if row["media_artifact_id"] is not None
                else None
            ),
            service_version=str(row["service_version"]),
            input_fingerprint=str(row["input_fingerprint"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _media_archive_destination_from_row(
        self, row: sqlite3.Row
    ) -> MediaArchiveDestination:
        return MediaArchiveDestination(
            id=int(row["id"]),
            archive_root=str(row["archive_root"]),
            active=bool(row["active"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
            updated_at=parse_datetime(str(row["updated_at"])) or utc_now(),
        )

    def _media_archive_entry_from_row(self, row: sqlite3.Row) -> MediaArchiveEntry:
        return MediaArchiveEntry(
            id=int(row["id"]),
            media_artifact_id=int(row["media_artifact_id"]),
            destination_id=int(row["destination_id"]),
            source_path=str(row["source_path"]),
            archive_path=str(row["archive_path"]),
            content_sha256=str(row["content_sha256"]),
            byte_size=int(row["byte_size"]),
            status=str(row["status"]),
            archived_at=parse_datetime(row["archived_at"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
            updated_at=parse_datetime(str(row["updated_at"])) or utc_now(),
        )

    def _media_archive_attempt_from_row(self, row: sqlite3.Row) -> MediaArchiveAttempt:
        return MediaArchiveAttempt(
            id=int(row["id"]),
            archive_entry_id=int(row["archive_entry_id"]),
            outcome=str(row["outcome"]),
            detail=row["detail"],
            attempted_at=parse_datetime(str(row["attempted_at"])) or utc_now(),
        )

    def _transcript_segment_from_row(self, row: sqlite3.Row) -> TranscriptSegment:
        return TranscriptSegment(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            artifact_id=int(row["artifact_id"]),
            start_seconds=row["start_seconds"],
            end_seconds=row["end_seconds"],
            text=str(row["text"]),
            speaker_hint=row["speaker_hint"],
            label=TranscriptSegmentLabel(str(row["label"])),
            confidence=row["confidence"],
        )

    def _extraction_result_from_row(self, row: sqlite3.Row) -> ExtractionResult:
        return ExtractionResult(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            version=int(row["version"]),
            proposed_text_path=str(row["proposed_text_path"]),
            proposed_json_path=row["proposed_json_path"],
            notes=row["notes"],
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _review_result_from_row(self, row: sqlite3.Row) -> ReviewResult:
        return ReviewResult(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            extraction_result_id=int(row["extraction_result_id"]),
            approved_text_path=str(row["approved_text_path"]),
            reviewed_at=parse_datetime(str(row["reviewed_at"])) or utc_now(),
            review_notes=row["review_notes"],
        )

    def _sermon_analysis_run_from_row(self, row: sqlite3.Row) -> SermonAnalysisRun:
        return SermonAnalysisRun(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            extraction_result_id=int(row["extraction_result_id"]),
            analyzer_key=str(row["analyzer_key"]),
            analyzer_version=str(row["analyzer_version"]),
            source_kind=str(row["source_kind"]),
            source_path=str(row["source_path"]),
            source_content_sha256=str(row["source_content_sha256"]),
            input_fingerprint=str(row["input_fingerprint"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _speaker_profile_analysis_run_from_row(
        self, row: sqlite3.Row
    ) -> SpeakerProfileAnalysisRun:
        return SpeakerProfileAnalysisRun(
            id=int(row["id"]),
            profile_id=int(row["profile_id"]),
            analyzer_key=str(row["analyzer_key"]),
            analyzer_version=str(row["analyzer_version"]),
            membership_fingerprint=str(row["membership_fingerprint"]),
            input_fingerprint=str(row["input_fingerprint"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _excluded_video_from_row(self, row: sqlite3.Row) -> ExcludedVideo:
        return ExcludedVideo(
            id=int(row["id"]),
            pastor_id=row["pastor_id"],
            source_id=row["source_id"],
            youtube_video_id=str(row["youtube_video_id"]),
            title=str(row["title"]),
            url=str(row["url"]),
            excluded_at=parse_datetime(str(row["excluded_at"])) or utc_now(),
            notes=row["notes"],
        )

    def _metadata_artifact_from_row(self, row: sqlite3.Row) -> MetadataArtifact:
        return MetadataArtifact(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            schema_version=int(row["schema_version"]),
            source_kind=str(row["source_kind"]),
            artifact_path=str(row["artifact_path"]),
            content_sha256=str(row["content_sha256"]),
            extractor_version=str(row["extractor_version"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _identity_evidence_from_row(self, row: sqlite3.Row) -> IdentityEvidence:
        return IdentityEvidence(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            target_pastor_id=int(row["target_pastor_id"]),
            evidence_type=str(row["evidence_type"]),
            source_family=str(row["source_family"]),
            polarity=str(row["polarity"]),
            strength=str(row["strength"]),
            scope=str(row["scope"]),
            artifact_path=str(row["artifact_path"]),
            extractor_version=str(row["extractor_version"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _identity_assessment_from_row(self, row: sqlite3.Row) -> IdentityAssessment:
        return IdentityAssessment(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            target_pastor_id=int(row["target_pastor_id"]),
            extraction_result_id=int(row["extraction_result_id"]),
            state=IdentityState(str(row["state"])),
            recommended_action=IdentityAction(str(row["recommended_action"])),
            shadow_mode=bool(row["shadow_mode"]),
            policy_version=str(row["policy_version"]),
            evidence_ledger_path=str(row["evidence_ledger_path"]),
            assessment_path=str(row["assessment_path"]),
            input_fingerprint=str(row["input_fingerprint"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _speaker_profile_from_row(self, row: sqlite3.Row) -> SpeakerProfile:
        return SpeakerProfile(
            id=int(row["id"]),
            stable_key=str(row["stable_key"]),
            display_label=row["display_label"],
            lifecycle_state=str(row["lifecycle_state"]),
            created_reason=str(row["created_reason"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _speaker_observation_from_row(self, row: sqlite3.Row) -> SpeakerObservation:
        return SpeakerObservation(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            extraction_result_id=int(row["extraction_result_id"]),
            role=str(row["role"]),
            multiplicity_state=str(row["multiplicity_state"]),
            start_seconds=float(row["start_seconds"]),
            end_seconds=float(row["end_seconds"]),
            artifact_path=str(row["artifact_path"]),
            content_sha256=str(row["content_sha256"]),
            extractor_version=str(row["extractor_version"]),
            input_fingerprint=str(row["input_fingerprint"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _speaker_name_claim_from_row(self, row: sqlite3.Row) -> SpeakerNameClaim:
        return SpeakerNameClaim(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            observation_id=int(row["observation_id"]) if row["observation_id"] is not None else None,
            display_name=str(row["display_name"]),
            normalized_name=str(row["normalized_name"]),
            claim_kind=str(row["claim_kind"]),
            channel=str(row["channel"]),
            explicit_speaker_attribution=bool(row["explicit_speaker_attribution"]),
            correlation_group_id=str(row["correlation_group_id"]),
            provenance_json=str(row["provenance_json"]),
            artifact_path=str(row["artifact_path"]),
            claim_fingerprint=str(row["claim_fingerprint"]),
            extractor_version=str(row["extractor_version"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def add_pastor(self, slug: str, display_name: str, notes: str | None = None) -> Pastor:
        added_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO pastors (slug, display_name, added_at, notes) VALUES (?, ?, ?, ?)",
                    (slug, display_name, added_at, notes),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT id, slug, display_name, added_at, notes FROM pastors WHERE slug = ?",
                    (slug,),
                ).fetchone()
                if row is None:
                    raise
                return self._pastor_from_row(row)
            pastor_id = int(cursor.lastrowid)
        return Pastor(
            id=pastor_id,
            slug=slug,
            display_name=display_name,
            added_at=parse_datetime(added_at) or utc_now(),
            notes=notes,
        )

    def get_pastor_by_slug(self, slug: str) -> Pastor | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, slug, display_name, added_at, notes FROM pastors WHERE slug = ?",
                (slug,),
            ).fetchone()
        if row is None:
            return None
        return self._pastor_from_row(row)

    def get_pastor_by_id(self, pastor_id: int) -> Pastor | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, slug, display_name, added_at, notes FROM pastors WHERE id = ?",
                (pastor_id,),
            ).fetchone()
        if row is None:
            return None
        return self._pastor_from_row(row)

    def list_pastors(self) -> list[Pastor]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, slug, display_name, added_at, notes FROM pastors ORDER BY id"
            ).fetchall()
        return [self._pastor_from_row(row) for row in rows]

    def add_organization(
        self,
        slug: str,
        display_name: str,
        organization_type: str,
        notes: str | None = None,
    ) -> Organization:
        added_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO organizations (
                        slug, display_name, organization_type, added_at, notes
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (slug, display_name, organization_type, added_at, notes),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, slug, display_name, organization_type, added_at, notes
                    FROM organizations WHERE slug = ?
                    """,
                    (slug,),
                ).fetchone()
                if row is None:
                    raise
                return self._organization_from_row(row)
        return Organization(
            id=int(cursor.lastrowid),
            slug=slug,
            display_name=display_name,
            organization_type=organization_type,
            added_at=parse_datetime(added_at) or utc_now(),
            notes=notes,
        )

    def get_organization_by_slug(self, slug: str) -> Organization | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, slug, display_name, organization_type, added_at, notes
                FROM organizations WHERE slug = ?
                """,
                (slug,),
            ).fetchone()
        return self._organization_from_row(row) if row is not None else None

    def get_organization_by_id(self, organization_id: int) -> Organization | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, slug, display_name, organization_type, added_at, notes
                FROM organizations WHERE id = ?
                """,
                (organization_id,),
            ).fetchone()
        return self._organization_from_row(row) if row is not None else None

    def list_organizations(self) -> list[Organization]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, slug, display_name, organization_type, added_at, notes
                FROM organizations ORDER BY id
                """
            ).fetchall()
        return [self._organization_from_row(row) for row in rows]

    def add_source(
        self,
        url: str,
        source_type: SourceType,
        pastor_id: int | None,
        notes: str | None = None,
        organization_id: int | None = None,
    ) -> Source:
        added_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO sources (
                        pastor_id, organization_id, url, source_type, added_at, notes
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pastor_id,
                        organization_id,
                        url,
                        source_type.value,
                        added_at,
                        notes,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, pastor_id, organization_id, url, source_identity_key,
                           source_type, added_at, notes, processing_enabled
                    FROM sources WHERE url = ?
                    """,
                    (url,),
                ).fetchone()
                if row is None:
                    raise
                if pastor_id is not None and row["pastor_id"] is None:
                    connection.execute(
                        "UPDATE sources SET pastor_id = ? WHERE id = ?",
                        (pastor_id, int(row["id"])),
                    )
                    row = connection.execute(
                        """
                        SELECT id, pastor_id, organization_id, url,
                               source_identity_key, source_type, added_at, notes,
                               processing_enabled
                        FROM sources WHERE id = ?
                        """,
                        (int(row["id"]),),
                    ).fetchone()
                    assert row is not None
                if pastor_id is not None:
                    self._ensure_source_target_policy(
                        connection,
                        source_id=int(row["id"]),
                        pastor_id=pastor_id,
                        origin_kind="manual_compatibility",
                        created_at=added_at,
                    )
                return self._source_from_row(row)
            source_id = int(cursor.lastrowid)
            if pastor_id is not None:
                self._ensure_source_target_policy(
                    connection,
                    source_id=source_id,
                    pastor_id=pastor_id,
                    origin_kind="manual_compatibility",
                    created_at=added_at,
                )
        return Source(
            id=source_id,
            pastor_id=pastor_id,
            organization_id=organization_id,
            url=url,
            source_type=source_type,
            added_at=parse_datetime(added_at) or utc_now(),
            notes=notes,
            source_identity_key=None,
            processing_enabled=True,
        )

    def list_sources(self) -> list[Source]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, pastor_id, organization_id, url, source_identity_key, "
                "source_type, added_at, notes, processing_enabled "
                "FROM sources ORDER BY id"
            ).fetchall()
        return [self._source_from_row(row) for row in rows]

    def list_processing_enabled_sources(self) -> list[Source]:
        return [source for source in self.list_sources() if source.processing_enabled]

    def set_source_processing_enabled(self, source_id: int, enabled: bool) -> Source:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE sources SET processing_enabled = ? WHERE id = ?",
                (int(enabled), source_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown source id: {source_id}")
        source = self.get_source_by_id(source_id)
        assert source is not None
        return source

    def get_source_by_id(self, source_id: int) -> Source | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, pastor_id, organization_id, url, source_identity_key, "
                "source_type, added_at, notes, processing_enabled "
                "FROM sources WHERE id = ?",
                (source_id,),
            ).fetchone()
        if row is None:
            return None
        return self._source_from_row(row)

    def get_source_by_url(self, url: str) -> Source | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, pastor_id, organization_id, url, source_identity_key, "
                "source_type, added_at, notes, processing_enabled "
                "FROM sources WHERE url = ?",
                (url,),
            ).fetchone()
        if row is None:
            return None
        return self._source_from_row(row)

    def add_video(
        self,
        source_id: int,
        pastor_id: int | None,
        youtube_video_id: str,
        title: str,
        url: str,
        channel_name: str | None = None,
        published_at: str | None = None,
        duration_seconds: int | None = None,
        status: VideoStatus = VideoStatus.DISCOVERED,
        failure_reason: str | None = None,
    ) -> Video:
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO videos (
                        source_id, pastor_id, youtube_video_id, title, url, channel_name,
                        published_at, duration_seconds, status, failure_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        pastor_id,
                        youtube_video_id,
                        title,
                        url,
                        channel_name,
                        published_at,
                        duration_seconds,
                        status.value,
                        failure_reason,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, source_id, pastor_id, youtube_video_id, title, url, channel_name,
                           published_at, duration_seconds, status, failure_reason
                    FROM videos
                    WHERE youtube_video_id = ?
                    """,
                    (youtube_video_id,),
                ).fetchone()
                if row is None:
                    raise
                return self._video_from_row(row)

            video_id = int(cursor.lastrowid)
            self._ensure_video_artifact_namespace(
                connection,
                video_id=video_id,
                pastor_id=pastor_id,
                youtube_video_id=youtube_video_id,
            )
            policies = connection.execute(
                """
                SELECT id, pastor_id, purpose, origin_kind
                FROM source_target_policies
                WHERE source_id = ? AND active = 1
                ORDER BY id
                """,
                (source_id,),
            ).fetchall()
            for policy in policies:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO video_target_contexts (
                        video_id, pastor_id, source_target_policy_id, purpose,
                        origin_kind, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        int(policy["pastor_id"]),
                        int(policy["id"]),
                        str(policy["purpose"]),
                        str(policy["origin_kind"]),
                        utc_now().isoformat(),
                    ),
                )
        return Video(
            id=video_id,
            source_id=source_id,
            pastor_id=pastor_id,
            youtube_video_id=youtube_video_id,
            title=title,
            url=url,
            channel_name=channel_name,
            published_at=parse_datetime(published_at),
            duration_seconds=duration_seconds,
            status=status,
            failure_reason=failure_reason,
        )

    def set_source_organization(
        self,
        source_id: int,
        organization_id: int | None,
        *,
        actor: str,
        reason: str,
        event_key: str,
    ) -> None:
        created_at = utc_now().isoformat()
        action = "attach" if organization_id is not None else "detach"
        fingerprint = stable_fingerprint(
            {
                "event_key": event_key,
                "source_id": source_id,
                "organization_id": organization_id,
                "action": action,
            }
        )
        with self.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM sources WHERE id = ?", (source_id,)
            ).fetchone() is None:
                raise ValueError(f"Unknown source id: {source_id}")
            if organization_id is not None and connection.execute(
                "SELECT 1 FROM organizations WHERE id = ?", (organization_id,)
            ).fetchone() is None:
                raise ValueError(f"Unknown organization id: {organization_id}")
            connection.execute(
                """
                INSERT OR IGNORE INTO source_organization_events (
                    source_id, organization_id, action, actor, reason,
                    external_record_snapshot_id, event_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    source_id,
                    organization_id,
                    action,
                    actor,
                    reason,
                    fingerprint,
                    created_at,
                ),
            )
            connection.execute(
                "UPDATE sources SET organization_id = ? WHERE id = ?",
                (organization_id, source_id),
            )

    def add_pastor_organization_affiliation(
        self,
        *,
        pastor_id: int,
        organization_id: int,
        role_key: str,
        role_label: str,
        started_on: str | None,
        ended_on: str | None,
        temporal_status: str,
        provenance_kind: str,
        notes: str | None = None,
        affiliation_claim_id: int | None = None,
    ) -> PastorOrganizationAffiliation:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO pastor_organization_affiliations (
                    pastor_id, organization_id, role_key, role_label,
                    started_on, ended_on, temporal_status, provenance_kind,
                    affiliation_claim_id, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pastor_id,
                    organization_id,
                    role_key,
                    role_label,
                    started_on,
                    ended_on,
                    temporal_status,
                    provenance_kind,
                    affiliation_claim_id,
                    notes,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM pastor_organization_affiliations WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        assert row is not None
        return self._pastor_organization_affiliation_from_row(row)

    def list_pastor_organization_affiliations(
        self, pastor_id: int | None = None
    ) -> list[PastorOrganizationAffiliation]:
        with self.connect() as connection:
            if pastor_id is None:
                rows = connection.execute(
                    "SELECT * FROM pastor_organization_affiliations ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM pastor_organization_affiliations
                    WHERE pastor_id = ? ORDER BY id
                    """,
                    (pastor_id,),
                ).fetchall()
        return [
            self._pastor_organization_affiliation_from_row(row) for row in rows
        ]

    def list_organization_affiliation_claims(
        self, organization_id: int | None = None
    ) -> list[sqlite3.Row]:
        with self.connect() as connection:
            if organization_id is None:
                rows = connection.execute(
                    """
                    SELECT claim.*, organization.slug AS organization_slug,
                           (
                               SELECT review.action
                               FROM affiliation_claim_review_events review
                               WHERE review.claim_id = claim.id
                               ORDER BY review.id DESC LIMIT 1
                           ) AS review_status
                    FROM organization_affiliation_claims claim
                    JOIN organizations organization
                      ON organization.id = claim.organization_id
                    ORDER BY claim.id
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT claim.*, organization.slug AS organization_slug,
                           (
                               SELECT review.action
                               FROM affiliation_claim_review_events review
                               WHERE review.claim_id = claim.id
                               ORDER BY review.id DESC LIMIT 1
                           ) AS review_status
                    FROM organization_affiliation_claims claim
                    JOIN organizations organization
                      ON organization.id = claim.organization_id
                    WHERE claim.organization_id = ?
                    ORDER BY claim.id
                    """,
                    (organization_id,),
                ).fetchall()
        return rows

    def review_organization_affiliation_claim(
        self,
        *,
        claim_id: int,
        pastor_id: int | None,
        attach: bool,
        reviewer: str,
        reason: str,
        review_event_key: str,
    ) -> int:
        action = "attach" if attach else "reject"
        if attach and pastor_id is None:
            raise ValueError("Attaching an affiliation claim requires a pastor")
        if not attach and pastor_id is not None:
            raise ValueError("Rejecting an affiliation claim cannot select a pastor")
        created_at = utc_now().isoformat()
        fingerprint = stable_fingerprint(
            {
                "review_event_key": review_event_key,
                "claim_id": claim_id,
                "pastor_id": pastor_id,
                "action": action,
            }
        )
        with self.connect() as connection:
            claim = connection.execute(
                """
                SELECT id, organization_id, claimed_role, valid_from, valid_to
                FROM organization_affiliation_claims
                WHERE id = ?
                """,
                (claim_id,),
            ).fetchone()
            if claim is None:
                raise ValueError(f"Unknown affiliation claim id: {claim_id}")
            if pastor_id is not None and connection.execute(
                "SELECT 1 FROM pastors WHERE id = ?", (pastor_id,)
            ).fetchone() is None:
                raise ValueError(f"Unknown pastor id: {pastor_id}")
            connection.execute(
                """
                INSERT OR IGNORE INTO affiliation_claim_review_events (
                    claim_id, pastor_id, action, reviewer, reason,
                    event_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    pastor_id,
                    action,
                    reviewer,
                    reason,
                    fingerprint,
                    created_at,
                ),
            )
            event = connection.execute(
                """
                SELECT id FROM affiliation_claim_review_events
                WHERE event_fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()
            assert event is not None
            if attach:
                role_label = str(claim["claimed_role"])
                role_key = (
                    "".join(
                        character if character.isalnum() else "_"
                        for character in role_label.lower()
                    ).strip("_")
                    or "affiliated"
                )
                started_on = claim["valid_from"]
                ended_on = claim["valid_to"]
                temporal_status = (
                    "bounded"
                    if started_on is not None and ended_on is not None
                    else "former"
                    if ended_on is not None
                    else "current"
                    if started_on is not None
                    else "unknown"
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO pastor_organization_affiliations (
                        pastor_id, organization_id, role_key, role_label,
                        started_on, ended_on, temporal_status, provenance_kind,
                        affiliation_claim_id, notes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'reviewed_import', ?, ?, ?)
                    """,
                    (
                        pastor_id,
                        int(claim["organization_id"]),
                        role_key,
                        role_label,
                        started_on,
                        ended_on,
                        temporal_status,
                        claim_id,
                        reason,
                        created_at,
                    ),
                )
        return int(event["id"])

    def list_video_ids_for_target_pastor(self, pastor_id: int) -> set[int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT video_id
                FROM video_target_contexts
                WHERE pastor_id = ?
                """,
                (pastor_id,),
            ).fetchall()
        return {int(row["video_id"]) for row in rows}

    def _ensure_source_target_policy(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: int,
        pastor_id: int,
        origin_kind: str,
        created_at: str,
    ) -> int:
        connection.execute(
            """
            INSERT OR IGNORE INTO source_target_policies (
                source_id, pastor_id, purpose, origin_kind, active, created_at
            ) VALUES (?, ?, 'legacy_primary_target', ?, 1, ?)
            """,
            (source_id, pastor_id, origin_kind, created_at),
        )
        row = connection.execute(
            """
            SELECT id FROM source_target_policies
            WHERE source_id = ? AND pastor_id = ?
              AND purpose = 'legacy_primary_target'
            """,
            (source_id, pastor_id),
        ).fetchone()
        assert row is not None
        policy_id = int(row["id"])
        primary = connection.execute(
            "SELECT pastor_id FROM sources WHERE id = ?",
            (source_id,),
        ).fetchone()
        if primary is not None and primary["pastor_id"] == pastor_id:
            connection.execute(
                """
                UPDATE videos SET pastor_id = ?
                WHERE source_id = ? AND pastor_id IS NULL
                """,
                (pastor_id, source_id),
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO video_target_contexts (
                video_id, pastor_id, source_target_policy_id, purpose,
                origin_kind, created_at
            )
            SELECT video.id, ?, ?, 'legacy_primary_target', ?, ?
            FROM videos video
            WHERE video.source_id = ?
            """,
            (
                pastor_id,
                policy_id,
                origin_kind,
                created_at,
                source_id,
            ),
        )
        return policy_id

    def _ensure_video_artifact_namespace(
        self,
        connection: sqlite3.Connection,
        *,
        video_id: int,
        pastor_id: int | None,
        youtube_video_id: str,
    ) -> None:
        if pastor_id is None:
            scheme = "video_v1"
            relative_root = f"artifacts/videos/{youtube_video_id}"
        else:
            row = connection.execute(
                "SELECT slug FROM pastors WHERE id = ?", (pastor_id,)
            ).fetchone()
            if row is None:
                scheme = "video_v1"
                relative_root = f"artifacts/videos/{youtube_video_id}"
            else:
                scheme = "legacy_pastor_v1"
                relative_root = (
                    f"pastors/{row['slug']}/videos/{youtube_video_id}"
                )
        connection.execute(
            """
            INSERT OR IGNORE INTO video_artifact_namespaces (
                video_id, scheme, relative_root, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (video_id, scheme, relative_root, utc_now().isoformat()),
        )

    def update_video_status(self, video_id: int, status: VideoStatus, failure_reason: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE videos SET status = ?, failure_reason = ? WHERE id = ?",
                (status.value, failure_reason, video_id),
            )

    def update_video_status_if_current(
        self,
        video_id: int,
        current_status: VideoStatus,
        new_status: VideoStatus,
        failure_reason: str | None = None,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE videos SET status = ?, failure_reason = ? WHERE id = ? AND status = ?",
                (new_status.value, failure_reason, video_id, current_status.value),
            )
        return cursor.rowcount > 0

    def list_videos(self) -> list[Video]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, source_id, pastor_id, youtube_video_id, title, url, channel_name,
                       published_at, duration_seconds, status, failure_reason
                FROM videos
                ORDER BY id
                """
            ).fetchall()
        return [self._video_from_row(row) for row in rows]

    def get_video_by_youtube_id(self, youtube_video_id: str) -> Video | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, source_id, pastor_id, youtube_video_id, title, url, channel_name,
                       published_at, duration_seconds, status, failure_reason
                FROM videos
                WHERE youtube_video_id = ?
                """,
                (youtube_video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._video_from_row(row)

    def get_video_by_id(self, video_id: int) -> Video | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, source_id, pastor_id, youtube_video_id, title, url, channel_name,
                       published_at, duration_seconds, status, failure_reason
                FROM videos
                WHERE id = ?
                """,
                (video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._video_from_row(row)

    def list_videos_by_source_id(self, source_id: int) -> list[Video]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, source_id, pastor_id, youtube_video_id, title, url, channel_name,
                       published_at, duration_seconds, status, failure_reason
                FROM videos
                WHERE source_id = ?
                ORDER BY id
                """,
                (source_id,),
            ).fetchall()
        return [self._video_from_row(row) for row in rows]

    def add_transcript_artifact(
        self,
        video_id: int,
        source_kind: TranscriptSourceKind,
        audio_path: str | None,
        raw_json_path: str | None = None,
        raw_text_path: str | None = None,
    ) -> TranscriptArtifact:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO transcript_artifacts (
                    video_id, source_kind, raw_json_path, raw_text_path, audio_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (video_id, source_kind.value, raw_json_path, raw_text_path, audio_path, created_at),
            )
        return TranscriptArtifact(
            id=int(cursor.lastrowid),
            video_id=video_id,
            source_kind=source_kind,
            raw_json_path=raw_json_path,
            raw_text_path=raw_text_path,
            audio_path=audio_path,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def add_media_artifact(
        self,
        *,
        video_id: int,
        parent_media_artifact_id: int | None,
        artifact_kind: str,
        provenance_kind: str,
        artifact_path: str,
        manifest_path: str,
        content_sha256: str,
        byte_size: int,
        duration_seconds: float | None,
        format_name: str | None,
        sample_rate_hz: int | None,
        channel_count: int | None,
        acquisition_tool: str,
        acquisition_tool_version: str,
        input_fingerprint: str,
    ) -> MediaArtifact:
        created_at = utc_now().isoformat()
        values = (
            video_id,
            parent_media_artifact_id,
            artifact_kind,
            provenance_kind,
            artifact_path,
            manifest_path,
            content_sha256,
            byte_size,
            duration_seconds,
            format_name,
            sample_rate_hz,
            channel_count,
            acquisition_tool,
            acquisition_tool_version,
            input_fingerprint,
            created_at,
        )
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO media_artifacts (
                        video_id, parent_media_artifact_id, artifact_kind, provenance_kind,
                        artifact_path, manifest_path, content_sha256, byte_size,
                        duration_seconds, format_name, sample_rate_hz, channel_count,
                        acquisition_tool, acquisition_tool_version, input_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM media_artifacts WHERE input_fingerprint = ?",
                    (input_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return self._media_artifact_from_row(row)
        return MediaArtifact(
            id=int(cursor.lastrowid),
            video_id=video_id,
            parent_media_artifact_id=parent_media_artifact_id,
            artifact_kind=artifact_kind,
            provenance_kind=provenance_kind,
            artifact_path=artifact_path,
            manifest_path=manifest_path,
            content_sha256=content_sha256,
            byte_size=byte_size,
            duration_seconds=duration_seconds,
            format_name=format_name,
            sample_rate_hz=sample_rate_hz,
            channel_count=channel_count,
            acquisition_tool=acquisition_tool,
            acquisition_tool_version=acquisition_tool_version,
            input_fingerprint=input_fingerprint,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def list_media_artifacts_for_video(self, video_id: int) -> list[MediaArtifact]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM media_artifacts WHERE video_id = ? ORDER BY id",
                (video_id,),
            ).fetchall()
        return [self._media_artifact_from_row(row) for row in rows]

    def get_latest_media_artifact(
        self, video_id: int, artifact_kind: str
    ) -> MediaArtifact | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM media_artifacts
                WHERE video_id = ? AND artifact_kind = ?
                ORDER BY id DESC LIMIT 1
                """,
                (video_id, artifact_kind),
            ).fetchone()
        return self._media_artifact_from_row(row) if row is not None else None

    def add_media_acquisition_attempt(
        self,
        *,
        video_id: int,
        target_kind: str,
        outcome: str,
        reason_code: str,
        detail: str | None,
        media_artifact_id: int | None,
        service_version: str,
        input_fingerprint: str,
    ) -> MediaAcquisitionAttempt:
        created_at = utc_now().isoformat()
        values = (
            video_id,
            target_kind,
            outcome,
            reason_code,
            detail,
            media_artifact_id,
            service_version,
            input_fingerprint,
            created_at,
        )
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO media_acquisition_attempts (
                        video_id, target_kind, outcome, reason_code, detail,
                        media_artifact_id, service_version, input_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM media_acquisition_attempts WHERE input_fingerprint = ?",
                    (input_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return self._media_acquisition_attempt_from_row(row)
        return MediaAcquisitionAttempt(
            id=int(cursor.lastrowid),
            video_id=video_id,
            target_kind=target_kind,
            outcome=outcome,
            reason_code=reason_code,
            detail=detail,
            media_artifact_id=media_artifact_id,
            service_version=service_version,
            input_fingerprint=input_fingerprint,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def list_media_acquisition_attempts(
        self, video_id: int | None = None
    ) -> list[MediaAcquisitionAttempt]:
        with self.connect() as connection:
            if video_id is None:
                rows = connection.execute(
                    "SELECT * FROM media_acquisition_attempts ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM media_acquisition_attempts WHERE video_id = ? ORDER BY id",
                    (video_id,),
                ).fetchall()
        return [self._media_acquisition_attempt_from_row(row) for row in rows]

    def get_latest_media_acquisition_attempt(
        self, video_id: int
    ) -> MediaAcquisitionAttempt | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM media_acquisition_attempts
                WHERE video_id = ? ORDER BY id DESC LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        return self._media_acquisition_attempt_from_row(row) if row is not None else None

    def configure_media_archive_destination(
        self, archive_root: str
    ) -> MediaArchiveDestination:
        now = utc_now().isoformat()
        with self.connect() as connection:
            connection.execute("UPDATE media_archive_destinations SET active = 0, updated_at = ?", (now,))
            connection.execute(
                """
                INSERT INTO media_archive_destinations (
                    archive_root, active, created_at, updated_at
                ) VALUES (?, 1, ?, ?)
                ON CONFLICT(archive_root) DO UPDATE SET active = 1, updated_at = excluded.updated_at
                """,
                (archive_root, now, now),
            )
            row = connection.execute(
                "SELECT * FROM media_archive_destinations WHERE archive_root = ?",
                (archive_root,),
            ).fetchone()
        assert row is not None
        return self._media_archive_destination_from_row(row)

    def get_active_media_archive_destination(self) -> MediaArchiveDestination | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM media_archive_destinations WHERE active = 1 ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return self._media_archive_destination_from_row(row) if row is not None else None

    def upsert_media_archive_entry(
        self,
        *,
        media_artifact_id: int,
        destination_id: int,
        source_path: str,
        archive_path: str,
        content_sha256: str,
        byte_size: int,
    ) -> MediaArchiveEntry:
        now = utc_now().isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO media_archive_entries (
                    media_artifact_id, destination_id, source_path, archive_path,
                    content_sha256, byte_size, status, archived_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?)
                ON CONFLICT(media_artifact_id) DO NOTHING
                """,
                (
                    media_artifact_id,
                    destination_id,
                    source_path,
                    archive_path,
                    content_sha256,
                    byte_size,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM media_archive_entries WHERE media_artifact_id = ?",
                (media_artifact_id,),
            ).fetchone()
        assert row is not None
        return self._media_archive_entry_from_row(row)

    def update_media_archive_entry_status(
        self, entry_id: int, status: str
    ) -> MediaArchiveEntry:
        now = utc_now().isoformat()
        archived_at = now if status == "archived" else None
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE media_archive_entries
                SET status = ?, archived_at = COALESCE(archived_at, ?), updated_at = ?
                WHERE id = ?
                """,
                (status, archived_at, now, entry_id),
            )
            row = connection.execute(
                "SELECT * FROM media_archive_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown media archive entry: {entry_id}")
        return self._media_archive_entry_from_row(row)

    def list_media_archive_entries(self) -> list[MediaArchiveEntry]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM media_archive_entries ORDER BY id"
            ).fetchall()
        return [self._media_archive_entry_from_row(row) for row in rows]

    def add_media_archive_attempt(
        self, *, archive_entry_id: int, outcome: str, detail: str | None
    ) -> MediaArchiveAttempt:
        attempted_at = utc_now().isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO media_archive_attempts (
                    archive_entry_id, outcome, detail, attempted_at
                ) VALUES (?, ?, ?, ?)
                """,
                (archive_entry_id, outcome, detail, attempted_at),
            )
        return MediaArchiveAttempt(
            id=int(cursor.lastrowid),
            archive_entry_id=archive_entry_id,
            outcome=outcome,
            detail=detail,
            attempted_at=parse_datetime(attempted_at) or utc_now(),
        )

    def list_media_archive_attempts(self) -> list[MediaArchiveAttempt]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM media_archive_attempts ORDER BY id"
            ).fetchall()
        return [self._media_archive_attempt_from_row(row) for row in rows]

    def delete_transcript_segments_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM transcript_segments WHERE video_id = ?", (video_id,))

    def delete_review_results_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM review_results WHERE video_id = ?", (video_id,))

    def delete_extraction_results_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM identity_assessments WHERE video_id = ?", (video_id,))
            self._delete_sermon_analysis_records_for_video(connection, video_id)
            self._delete_speaker_records_for_video(connection, video_id)
            connection.execute("DELETE FROM extraction_results WHERE video_id = ?", (video_id,))

    def _delete_sermon_analysis_records_for_video(
        self, connection: sqlite3.Connection, video_id: int
    ) -> None:
        profile_run_rows = connection.execute(
            """
            SELECT DISTINCT input.profile_analysis_run_id
            FROM speaker_profile_analysis_inputs input
            JOIN sermon_analysis_runs sermon
              ON sermon.id = input.sermon_analysis_run_id
            WHERE sermon.video_id = ?
            """,
            (video_id,),
        ).fetchall()
        profile_run_ids = [int(row[0]) for row in profile_run_rows]
        for profile_run_id in profile_run_ids:
            connection.execute(
                "DELETE FROM speaker_profile_analysis_measurements "
                "WHERE profile_analysis_run_id = ?",
                (profile_run_id,),
            )
            connection.execute(
                "DELETE FROM speaker_profile_analysis_inputs "
                "WHERE profile_analysis_run_id = ?",
                (profile_run_id,),
            )
            connection.execute(
                "DELETE FROM speaker_profile_analysis_runs WHERE id = ?",
                (profile_run_id,),
            )
        connection.execute(
            """
            DELETE FROM sermon_analysis_measurements
            WHERE analysis_run_id IN (
                SELECT id FROM sermon_analysis_runs WHERE video_id = ?
            )
            """,
            (video_id,),
        )
        connection.execute(
            """
            DELETE FROM sermon_analysis_evidence
            WHERE analysis_run_id IN (
                SELECT id FROM sermon_analysis_runs WHERE video_id = ?
            )
            """,
            (video_id,),
        )
        connection.execute(
            "DELETE FROM sermon_analysis_runs WHERE video_id = ?", (video_id,)
        )

    def delete_transcript_artifacts_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM transcript_artifacts WHERE video_id = ?", (video_id,))

    def delete_identity_records_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM identity_assessments WHERE video_id = ?", (video_id,))
            connection.execute("DELETE FROM identity_evidence WHERE video_id = ?", (video_id,))
            connection.execute("DELETE FROM metadata_artifacts WHERE video_id = ?", (video_id,))
            self._delete_speaker_records_for_video(connection, video_id)

    def _delete_speaker_records_for_video(
        self, connection: sqlite3.Connection, video_id: int
    ) -> None:
        connection.execute(
            """
            DELETE FROM speaker_observation_difference_events
            WHERE observation_a_id IN (
                SELECT id FROM speaker_observations WHERE video_id = ?
            ) OR observation_b_id IN (
                SELECT id FROM speaker_observations WHERE video_id = ?
            )
            """,
            (video_id, video_id),
        )
        connection.execute(
            """
            DELETE FROM speaker_observation_grouping_events
            WHERE observation_id IN (SELECT id FROM speaker_observations WHERE video_id = ?)
            """,
            (video_id,),
        )
        connection.execute(
            """
            DELETE FROM speaker_observation_review_events
            WHERE observation_id IN (SELECT id FROM speaker_observations WHERE video_id = ?)
            """,
            (video_id,),
        )
        connection.execute(
            """
            DELETE FROM profile_name_claim_events
            WHERE claim_id IN (SELECT id FROM speaker_name_claims WHERE video_id = ?)
            """,
            (video_id,),
        )
        connection.execute(
            """
            DELETE FROM profile_observation_events
            WHERE observation_id IN (SELECT id FROM speaker_observations WHERE video_id = ?)
            """,
            (video_id,),
        )
        connection.execute("DELETE FROM speaker_name_claims WHERE video_id = ?", (video_id,))
        connection.execute("DELETE FROM speaker_observations WHERE video_id = ?", (video_id,))

    def delete_video(self, video_id: int) -> None:
        self.delete_identity_records_for_video(video_id)
        self.delete_review_results_for_video(video_id)
        self.delete_extraction_results_for_video(video_id)
        self.delete_transcript_segments_for_video(video_id)
        self.delete_transcript_artifacts_for_video(video_id)
        with self.connect() as connection:
            connection.execute(
                """
                DELETE FROM media_archive_attempts
                WHERE archive_entry_id IN (
                    SELECT mae.id FROM media_archive_entries mae
                    JOIN media_artifacts ma ON ma.id = mae.media_artifact_id
                    WHERE ma.video_id = ?
                )
                """,
                (video_id,),
            )
            connection.execute(
                """
                DELETE FROM media_archive_entries
                WHERE media_artifact_id IN (
                    SELECT id FROM media_artifacts WHERE video_id = ?
                )
                """,
                (video_id,),
            )
            connection.execute("DELETE FROM media_acquisition_attempts WHERE video_id = ?", (video_id,))
            connection.execute("DELETE FROM media_artifacts WHERE video_id = ?", (video_id,))
            connection.execute("DELETE FROM videos WHERE id = ?", (video_id,))

    def delete_source(self, source_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    def add_excluded_video(
        self,
        youtube_video_id: str,
        title: str,
        url: str,
        pastor_id: int | None = None,
        source_id: int | None = None,
        notes: str | None = None,
    ) -> ExcludedVideo:
        excluded_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO excluded_videos (
                        pastor_id, source_id, youtube_video_id, title, url, excluded_at, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (pastor_id, source_id, youtube_video_id, title, url, excluded_at, notes),
                )
            except sqlite3.IntegrityError:
                connection.execute(
                    """
                    UPDATE excluded_videos
                    SET pastor_id = ?, source_id = ?, title = ?, url = ?, excluded_at = ?, notes = ?
                    WHERE youtube_video_id = ?
                    """,
                    (pastor_id, source_id, title, url, excluded_at, notes, youtube_video_id),
                )
                row = connection.execute(
                    """
                    SELECT id, pastor_id, source_id, youtube_video_id, title, url, excluded_at, notes
                    FROM excluded_videos
                    WHERE youtube_video_id = ?
                    """,
                    (youtube_video_id,),
                ).fetchone()
                if row is None:
                    raise
                return self._excluded_video_from_row(row)
        return ExcludedVideo(
            id=int(cursor.lastrowid),
            pastor_id=pastor_id,
            source_id=source_id,
            youtube_video_id=youtube_video_id,
            title=title,
            url=url,
            excluded_at=parse_datetime(excluded_at) or utc_now(),
            notes=notes,
        )

    def list_excluded_videos(self) -> list[ExcludedVideo]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, pastor_id, source_id, youtube_video_id, title, url, excluded_at, notes
                FROM excluded_videos
                ORDER BY excluded_at DESC, id DESC
                """
            ).fetchall()
        return [self._excluded_video_from_row(row) for row in rows]

    def get_excluded_video_by_youtube_id(self, youtube_video_id: str) -> ExcludedVideo | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, pastor_id, source_id, youtube_video_id, title, url, excluded_at, notes
                FROM excluded_videos
                WHERE youtube_video_id = ?
                """,
                (youtube_video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._excluded_video_from_row(row)

    def delete_excluded_video(self, youtube_video_id: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM excluded_videos WHERE youtube_video_id = ?", (youtube_video_id,))

    def add_transcript_segment(
        self,
        video_id: int,
        artifact_id: int,
        start_seconds: float | None,
        end_seconds: float | None,
        text: str,
        label: TranscriptSegmentLabel,
        speaker_hint: str | None = None,
        confidence: float | None = None,
    ) -> TranscriptSegment:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO transcript_segments (
                    video_id, artifact_id, start_seconds, end_seconds, text, speaker_hint, label, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (video_id, artifact_id, start_seconds, end_seconds, text, speaker_hint, label.value, confidence),
            )
        return TranscriptSegment(
            id=int(cursor.lastrowid),
            video_id=video_id,
            artifact_id=artifact_id,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            text=text,
            speaker_hint=speaker_hint,
            label=label,
            confidence=confidence,
        )

    def list_transcript_segments(self, video_id: int) -> list[TranscriptSegment]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, artifact_id, start_seconds, end_seconds, text, speaker_hint, label, confidence
                FROM transcript_segments
                WHERE video_id = ?
                ORDER BY id
                """,
                (video_id,),
            ).fetchall()
        return [self._transcript_segment_from_row(row) for row in rows]

    def list_transcript_artifacts(self) -> list[TranscriptArtifact]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, source_kind, raw_json_path, raw_text_path, audio_path, created_at
                FROM transcript_artifacts
                ORDER BY id
                """
            ).fetchall()
        return [self._transcript_artifact_from_row(row) for row in rows]

    def list_transcript_artifacts_for_video(self, video_id: int) -> list[TranscriptArtifact]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, source_kind, raw_json_path, raw_text_path, audio_path, created_at
                FROM transcript_artifacts
                WHERE video_id = ?
                ORDER BY id
                """,
                (video_id,),
            ).fetchall()
        return [self._transcript_artifact_from_row(row) for row in rows]

    def get_latest_transcript_artifact_for_video(self, video_id: int) -> TranscriptArtifact | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, source_kind, raw_json_path, raw_text_path, audio_path, created_at
                FROM transcript_artifacts
                WHERE video_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._transcript_artifact_from_row(row)

    def get_latest_audio_transcript_artifact_for_video(
        self, video_id: int
    ) -> TranscriptArtifact | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, source_kind, raw_json_path, raw_text_path, audio_path, created_at
                FROM transcript_artifacts
                WHERE video_id = ? AND audio_path IS NOT NULL AND audio_path != ''
                ORDER BY id DESC
                LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._transcript_artifact_from_row(row)

    def add_extraction_result(
        self,
        video_id: int,
        version: int,
        proposed_text_path: str,
        proposed_json_path: str | None = None,
        notes: str | None = None,
    ) -> ExtractionResult:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO extraction_results (
                    video_id, version, proposed_text_path, proposed_json_path, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (video_id, version, proposed_text_path, proposed_json_path, notes, created_at),
            )
        return ExtractionResult(
            id=int(cursor.lastrowid),
            video_id=video_id,
            version=version,
            proposed_text_path=proposed_text_path,
            proposed_json_path=proposed_json_path,
            notes=notes,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def list_extraction_results(self) -> list[ExtractionResult]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, version, proposed_text_path, proposed_json_path, notes, created_at
                FROM extraction_results
                ORDER BY id
                """
            ).fetchall()
        return [self._extraction_result_from_row(row) for row in rows]

    def get_latest_extraction_result_for_video(self, video_id: int) -> ExtractionResult | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, version, proposed_text_path, proposed_json_path, notes, created_at
                FROM extraction_results
                WHERE video_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._extraction_result_from_row(row)

    def add_review_result(
        self,
        video_id: int,
        extraction_result_id: int,
        approved_text_path: str,
        review_notes: str | None = None,
    ) -> ReviewResult:
        reviewed_at = utc_now().isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO review_results (
                    video_id, extraction_result_id, approved_text_path, reviewed_at, review_notes
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (video_id, extraction_result_id, approved_text_path, reviewed_at, review_notes),
            )
        return ReviewResult(
            id=int(cursor.lastrowid),
            video_id=video_id,
            extraction_result_id=extraction_result_id,
            approved_text_path=approved_text_path,
            reviewed_at=parse_datetime(reviewed_at) or utc_now(),
            review_notes=review_notes,
        )

    def list_review_results(self) -> list[ReviewResult]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, extraction_result_id, approved_text_path, reviewed_at, review_notes
                FROM review_results
                ORDER BY id
                """
            ).fetchall()
        return [self._review_result_from_row(row) for row in rows]

    def get_latest_review_result_for_video(self, video_id: int) -> ReviewResult | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, extraction_result_id, approved_text_path, reviewed_at, review_notes
                FROM review_results
                WHERE video_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._review_result_from_row(row)

    def get_sermon_analysis_run_by_fingerprint(
        self, input_fingerprint: str
    ) -> SermonAnalysisRun | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sermon_analysis_runs WHERE input_fingerprint = ?",
                (input_fingerprint,),
            ).fetchone()
        return self._sermon_analysis_run_from_row(row) if row is not None else None

    def add_sermon_analysis_run(
        self,
        *,
        video_id: int,
        extraction_result_id: int,
        analyzer_key: str,
        analyzer_version: str,
        source_kind: str,
        source_path: str,
        source_content_sha256: str,
        input_fingerprint: str,
        measurements: list[tuple[str, str, str | None]],
        evidence: list[
            tuple[
                str,
                str,
                int | None,
                float | None,
                float | None,
                int | None,
                int | None,
                str,
                str,
            ]
        ],
    ) -> tuple[SermonAnalysisRun, bool]:
        """Atomically persist a complete analysis or reuse its fingerprint."""
        existing = self.get_sermon_analysis_run_by_fingerprint(input_fingerprint)
        if existing is not None:
            return existing, False

        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO sermon_analysis_runs (
                        video_id, extraction_result_id, analyzer_key,
                        analyzer_version, source_kind, source_path,
                        source_content_sha256, input_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        extraction_result_id,
                        analyzer_key,
                        analyzer_version,
                        source_kind,
                        source_path,
                        source_content_sha256,
                        input_fingerprint,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM sermon_analysis_runs WHERE input_fingerprint = ?",
                    (input_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return self._sermon_analysis_run_from_row(row), False

            run_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO sermon_analysis_measurements (
                    analysis_run_id, metric_key, value_json, unit
                ) VALUES (?, ?, ?, ?)
                """,
                [(run_id, key, value, unit) for key, value, unit in measurements],
            )
            connection.executemany(
                """
                INSERT INTO sermon_analysis_evidence (
                    analysis_run_id, evidence_kind, evidence_key,
                    segment_index, start_seconds, end_seconds,
                    char_start, char_end, excerpt, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(run_id, *item) for item in evidence],
            )

            row = connection.execute(
                "SELECT * FROM sermon_analysis_runs WHERE id = ?", (run_id,)
            ).fetchone()
            assert row is not None
            return self._sermon_analysis_run_from_row(row), True

    def list_sermon_analysis_runs(
        self, *, video_id: int | None = None
    ) -> list[SermonAnalysisRun]:
        query = "SELECT * FROM sermon_analysis_runs"
        parameters: tuple[object, ...] = ()
        if video_id is not None:
            query += " WHERE video_id = ?"
            parameters = (video_id,)
        query += " ORDER BY id"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._sermon_analysis_run_from_row(row) for row in rows]

    def get_latest_sermon_analysis_run(
        self,
        video_id: int,
        analyzer_key: str,
        analyzer_version: str | None = None,
    ) -> SermonAnalysisRun | None:
        version_clause = " AND analyzer_version = ?" if analyzer_version is not None else ""
        parameters: tuple[object, ...] = (video_id, analyzer_key)
        if analyzer_version is not None:
            parameters += (analyzer_version,)
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM sermon_analysis_runs
                WHERE video_id = ? AND analyzer_key = ?
                {version_clause}
                ORDER BY id DESC LIMIT 1
                """,
                parameters,
            ).fetchone()
        return self._sermon_analysis_run_from_row(row) if row is not None else None

    def list_sermon_analysis_measurements(
        self, analysis_run_id: int
    ) -> list[SermonAnalysisMeasurement]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sermon_analysis_measurements
                WHERE analysis_run_id = ? ORDER BY metric_key
                """,
                (analysis_run_id,),
            ).fetchall()
        return [
            SermonAnalysisMeasurement(
                id=int(row["id"]),
                analysis_run_id=int(row["analysis_run_id"]),
                metric_key=str(row["metric_key"]),
                value_json=str(row["value_json"]),
                unit=row["unit"],
            )
            for row in rows
        ]

    def list_sermon_analysis_evidence(
        self, analysis_run_id: int
    ) -> list[SermonAnalysisEvidence]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sermon_analysis_evidence
                WHERE analysis_run_id = ? ORDER BY segment_index, char_start, id
                """,
                (analysis_run_id,),
            ).fetchall()
        return [
            SermonAnalysisEvidence(
                id=int(row["id"]),
                analysis_run_id=int(row["analysis_run_id"]),
                evidence_kind=str(row["evidence_kind"]),
                evidence_key=str(row["evidence_key"]),
                segment_index=(
                    int(row["segment_index"])
                    if row["segment_index"] is not None
                    else None
                ),
                start_seconds=(
                    float(row["start_seconds"])
                    if row["start_seconds"] is not None
                    else None
                ),
                end_seconds=(
                    float(row["end_seconds"])
                    if row["end_seconds"] is not None
                    else None
                ),
                char_start=(
                    int(row["char_start"]) if row["char_start"] is not None else None
                ),
                char_end=(
                    int(row["char_end"]) if row["char_end"] is not None else None
                ),
                excerpt=str(row["excerpt"]),
                payload_json=str(row["payload_json"]),
            )
            for row in rows
        ]

    def get_speaker_profile_analysis_run_by_fingerprint(
        self, input_fingerprint: str
    ) -> SpeakerProfileAnalysisRun | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM speaker_profile_analysis_runs WHERE input_fingerprint = ?",
                (input_fingerprint,),
            ).fetchone()
        return (
            self._speaker_profile_analysis_run_from_row(row)
            if row is not None
            else None
        )

    def add_speaker_profile_analysis_run(
        self,
        *,
        profile_id: int,
        analyzer_key: str,
        analyzer_version: str,
        membership_fingerprint: str,
        input_fingerprint: str,
        inputs: list[tuple[int, int]],
        measurements: list[tuple[str, str, str | None]],
    ) -> tuple[SpeakerProfileAnalysisRun, bool]:
        existing = self.get_speaker_profile_analysis_run_by_fingerprint(
            input_fingerprint
        )
        if existing is not None:
            return existing, False

        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO speaker_profile_analysis_runs (
                        profile_id, analyzer_key, analyzer_version,
                        membership_fingerprint, input_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id,
                        analyzer_key,
                        analyzer_version,
                        membership_fingerprint,
                        input_fingerprint,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM speaker_profile_analysis_runs "
                    "WHERE input_fingerprint = ?",
                    (input_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return self._speaker_profile_analysis_run_from_row(row), False

            run_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO speaker_profile_analysis_inputs (
                    profile_analysis_run_id, sermon_analysis_run_id, video_id
                ) VALUES (?, ?, ?)
                """,
                [(run_id, sermon_run_id, video_id) for sermon_run_id, video_id in inputs],
            )
            connection.executemany(
                """
                INSERT INTO speaker_profile_analysis_measurements (
                    profile_analysis_run_id, metric_key, value_json, unit
                ) VALUES (?, ?, ?, ?)
                """,
                [(run_id, key, value, unit) for key, value, unit in measurements],
            )
            row = connection.execute(
                "SELECT * FROM speaker_profile_analysis_runs WHERE id = ?", (run_id,)
            ).fetchone()
            assert row is not None
            return self._speaker_profile_analysis_run_from_row(row), True

    def get_latest_speaker_profile_analysis_run(
        self, profile_id: int, analyzer_key: str
    ) -> SpeakerProfileAnalysisRun | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM speaker_profile_analysis_runs
                WHERE profile_id = ? AND analyzer_key = ?
                ORDER BY id DESC LIMIT 1
                """,
                (profile_id, analyzer_key),
            ).fetchone()
        return (
            self._speaker_profile_analysis_run_from_row(row)
            if row is not None
            else None
        )

    def list_speaker_profile_analysis_measurements(
        self, profile_analysis_run_id: int
    ) -> list[SpeakerProfileAnalysisMeasurement]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM speaker_profile_analysis_measurements
                WHERE profile_analysis_run_id = ? ORDER BY metric_key
                """,
                (profile_analysis_run_id,),
            ).fetchall()
        return [
            SpeakerProfileAnalysisMeasurement(
                id=int(row["id"]),
                profile_analysis_run_id=int(row["profile_analysis_run_id"]),
                metric_key=str(row["metric_key"]),
                value_json=str(row["value_json"]),
                unit=row["unit"],
            )
            for row in rows
        ]

    def list_speaker_profile_analysis_input_run_ids(
        self, profile_analysis_run_id: int
    ) -> list[int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT sermon_analysis_run_id
                FROM speaker_profile_analysis_inputs
                WHERE profile_analysis_run_id = ?
                ORDER BY sermon_analysis_run_id
                """,
                (profile_analysis_run_id,),
            ).fetchall()
        return [int(row["sermon_analysis_run_id"]) for row in rows]

    def get_compatible_speaker_profile_analysis_run(
        self, profile_id: int, analyzer_key: str, analyzer_version: str
    ) -> SpeakerProfileAnalysisRun | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM speaker_profile_analysis_runs
                WHERE profile_id = ? AND analyzer_key = ? AND analyzer_version = ?
                ORDER BY id DESC LIMIT 1
                """,
                (profile_id, analyzer_key, analyzer_version),
            ).fetchone()
        return (
            self._speaker_profile_analysis_run_from_row(row)
            if row is not None
            else None
        )

    def _reference_panel_from_row(self, row: sqlite3.Row) -> ReferencePanel:
        return ReferencePanel(
            id=int(row["id"]),
            key=str(row["panel_key"]),
            display_name=str(row["display_name"]),
            description=str(row["description"]),
            provenance=str(row["provenance"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def ensure_reference_panel(
        self,
        *,
        key: str,
        display_name: str,
        description: str,
        provenance: str,
    ) -> tuple[ReferencePanel, bool]:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO reference_panels (
                        panel_key, display_name, description, provenance, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (key, display_name, description, provenance, created_at),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM reference_panels WHERE panel_key = ?", (key,)
                ).fetchone()
                if row is None:
                    raise
                panel = self._reference_panel_from_row(row)
                if (
                    panel.display_name != display_name
                    or panel.description != description
                    or panel.provenance != provenance
                ):
                    raise ValueError(
                        f"Reference panel key {key!r} already exists with different metadata"
                    )
                return panel, False
            row = connection.execute(
                "SELECT * FROM reference_panels WHERE id = ?", (int(cursor.lastrowid),)
            ).fetchone()
            assert row is not None
            return self._reference_panel_from_row(row), True

    def get_reference_panel(self, key: str) -> ReferencePanel | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reference_panels WHERE panel_key = ?", (key,)
            ).fetchone()
        return self._reference_panel_from_row(row) if row is not None else None

    def list_reference_panels(self) -> list[ReferencePanel]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reference_panels ORDER BY panel_key"
            ).fetchall()
        return [self._reference_panel_from_row(row) for row in rows]

    def add_reference_panel_membership_event(
        self,
        *,
        panel_id: int,
        profile_id: int,
        action: str,
        reviewer: str,
        rationale: str,
        event_fingerprint: str,
    ) -> tuple[ReferencePanelMembershipEvent, bool]:
        if action not in {"attach", "detach"}:
            raise ValueError(f"Unsupported reference-panel membership action: {action}")
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO reference_panel_membership_events (
                        panel_id, profile_id, action, reviewer, rationale,
                        event_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        panel_id,
                        profile_id,
                        action,
                        reviewer,
                        rationale,
                        event_fingerprint,
                        created_at,
                    ),
                )
                created = True
                row = connection.execute(
                    "SELECT * FROM reference_panel_membership_events WHERE id = ?",
                    (int(cursor.lastrowid),),
                ).fetchone()
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM reference_panel_membership_events
                    WHERE event_fingerprint = ?
                    """,
                    (event_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                expected = (panel_id, profile_id, action, reviewer, rationale)
                actual = tuple(
                    row[name]
                    for name in ("panel_id", "profile_id", "action", "reviewer", "rationale")
                )
                if actual != expected:
                    raise ValueError("Reference-panel event fingerprint collision")
                created = False
            assert row is not None
        return ReferencePanelMembershipEvent(
            id=int(row["id"]),
            panel_id=int(row["panel_id"]),
            profile_id=int(row["profile_id"]),
            action=str(row["action"]),
            reviewer=str(row["reviewer"]),
            rationale=str(row["rationale"]),
            event_fingerprint=str(row["event_fingerprint"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        ), created

    def list_effective_reference_panel_profile_ids(self, panel_id: int) -> list[int]:
        return [
            event.profile_id
            for event in self.list_effective_reference_panel_membership_events(panel_id)
        ]

    def list_effective_reference_panel_membership_events(
        self, panel_id: int
    ) -> list[ReferencePanelMembershipEvent]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT event.*
                FROM reference_panel_membership_events AS event
                WHERE event.panel_id = ?
                  AND event.id = (
                    SELECT MAX(latest.id)
                    FROM reference_panel_membership_events AS latest
                    WHERE latest.panel_id = event.panel_id
                      AND latest.profile_id = event.profile_id
                  )
                  AND event.action = 'attach'
                ORDER BY event.profile_id
                """,
                (panel_id,),
            ).fetchall()
        return [
            ReferencePanelMembershipEvent(
                id=int(row["id"]),
                panel_id=int(row["panel_id"]),
                profile_id=int(row["profile_id"]),
                action=str(row["action"]),
                reviewer=str(row["reviewer"]),
                rationale=str(row["rationale"]),
                event_fingerprint=str(row["event_fingerprint"]),
                created_at=parse_datetime(str(row["created_at"])) or utc_now(),
            )
            for row in rows
        ]

    def _reference_panel_snapshot_from_row(
        self, row: sqlite3.Row
    ) -> ReferencePanelSnapshot:
        return ReferencePanelSnapshot(
            id=int(row["id"]),
            panel_id=int(row["panel_id"]),
            profile_analyzer_key=str(row["profile_analyzer_key"]),
            profile_analyzer_version=str(row["profile_analyzer_version"]),
            feature_schema_version=str(row["feature_schema_version"]),
            comparison_feature_names_json=str(row["comparison_feature_names_json"]),
            coverage_feature_names_json=str(row["coverage_feature_names_json"]),
            feature_family_assignments_json=str(row["feature_family_assignments_json"]),
            panel_feature_statistics_json=str(row["panel_feature_statistics_json"]),
            eligibility_policy_version=str(row["eligibility_policy_version"]),
            eligibility_policy_json=str(row["eligibility_policy_json"]),
            snapshot_analyzer_version=str(row["snapshot_analyzer_version"]),
            input_fingerprint=str(row["input_fingerprint"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def get_reference_panel_snapshot_by_fingerprint(
        self, input_fingerprint: str
    ) -> ReferencePanelSnapshot | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reference_panel_snapshots WHERE input_fingerprint = ?",
                (input_fingerprint,),
            ).fetchone()
        return self._reference_panel_snapshot_from_row(row) if row is not None else None

    def get_latest_reference_panel_snapshot(
        self, panel_id: int
    ) -> ReferencePanelSnapshot | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM reference_panel_snapshots
                WHERE panel_id = ? ORDER BY id DESC LIMIT 1
                """,
                (panel_id,),
            ).fetchone()
        return self._reference_panel_snapshot_from_row(row) if row is not None else None

    def add_reference_panel_snapshot(
        self,
        *,
        panel_id: int,
        profile_analyzer_key: str,
        profile_analyzer_version: str,
        feature_schema_version: str,
        comparison_feature_names_json: str,
        coverage_feature_names_json: str,
        feature_family_assignments_json: str,
        panel_feature_statistics_json: str,
        eligibility_policy_version: str,
        eligibility_policy_json: str,
        snapshot_analyzer_version: str,
        input_fingerprint: str,
        members: list[tuple[str, str, int, str, int | None, str, str, str, str]],
    ) -> tuple[ReferencePanelSnapshot, bool]:
        existing = self.get_reference_panel_snapshot_by_fingerprint(input_fingerprint)
        if existing is not None:
            return existing, False
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO reference_panel_snapshots (
                        panel_id, profile_analyzer_key, profile_analyzer_version,
                        feature_schema_version, comparison_feature_names_json,
                        coverage_feature_names_json, feature_family_assignments_json,
                        panel_feature_statistics_json, eligibility_policy_version,
                        eligibility_policy_json, snapshot_analyzer_version,
                        input_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        panel_id,
                        profile_analyzer_key,
                        profile_analyzer_version,
                        feature_schema_version,
                        comparison_feature_names_json,
                        coverage_feature_names_json,
                        feature_family_assignments_json,
                        panel_feature_statistics_json,
                        eligibility_policy_version,
                        eligibility_policy_json,
                        snapshot_analyzer_version,
                        input_fingerprint,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM reference_panel_snapshots WHERE input_fingerprint = ?",
                    (input_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return self._reference_panel_snapshot_from_row(row), False
            snapshot_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO reference_panel_snapshot_members (
                    snapshot_id, requested_profile_ids_json, membership_event_ids_json,
                    resolved_profile_id,
                    resolved_display_label,
                    profile_analysis_run_id, eligibility_status,
                    exclusion_reasons_json, comparison_values_json,
                    coverage_diagnostics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(snapshot_id, *member) for member in members],
            )
            row = connection.execute(
                "SELECT * FROM reference_panel_snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
            assert row is not None
            return self._reference_panel_snapshot_from_row(row), True

    def list_reference_panel_snapshot_members(
        self, snapshot_id: int
    ) -> list[ReferencePanelSnapshotMember]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM reference_panel_snapshot_members
                WHERE snapshot_id = ? ORDER BY resolved_profile_id
                """,
                (snapshot_id,),
            ).fetchall()
        return [
            ReferencePanelSnapshotMember(
                id=int(row["id"]),
                snapshot_id=int(row["snapshot_id"]),
                requested_profile_ids_json=str(row["requested_profile_ids_json"]),
                membership_event_ids_json=str(row["membership_event_ids_json"]),
                resolved_profile_id=int(row["resolved_profile_id"]),
                resolved_display_label=str(row["resolved_display_label"]),
                profile_analysis_run_id=(
                    int(row["profile_analysis_run_id"])
                    if row["profile_analysis_run_id"] is not None
                    else None
                ),
                eligibility_status=str(row["eligibility_status"]),
                exclusion_reasons_json=str(row["exclusion_reasons_json"]),
                comparison_values_json=str(row["comparison_values_json"]),
                coverage_diagnostics_json=str(row["coverage_diagnostics_json"]),
            )
            for row in rows
        ]

    def add_metadata_artifact(
        self,
        *,
        video_id: int,
        schema_version: int,
        source_kind: str,
        artifact_path: str,
        content_sha256: str,
        extractor_version: str,
    ) -> MetadataArtifact:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO metadata_artifacts (
                        video_id, schema_version, source_kind, artifact_path, content_sha256,
                        extractor_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        schema_version,
                        source_kind,
                        artifact_path,
                        content_sha256,
                        extractor_version,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, video_id, schema_version, source_kind, artifact_path, content_sha256,
                           extractor_version, created_at
                    FROM metadata_artifacts
                    WHERE video_id = ? AND content_sha256 = ? AND extractor_version = ?
                    """,
                    (video_id, content_sha256, extractor_version),
                ).fetchone()
                if row is None:
                    raise
                return self._metadata_artifact_from_row(row)
        return MetadataArtifact(
            id=int(cursor.lastrowid),
            video_id=video_id,
            schema_version=schema_version,
            source_kind=source_kind,
            artifact_path=artifact_path,
            content_sha256=content_sha256,
            extractor_version=extractor_version,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def get_latest_metadata_artifact_for_video(self, video_id: int) -> MetadataArtifact | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, schema_version, source_kind, artifact_path, content_sha256,
                       extractor_version, created_at
                FROM metadata_artifacts
                WHERE video_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        return self._metadata_artifact_from_row(row) if row is not None else None

    def add_identity_evidence(
        self,
        *,
        video_id: int,
        target_pastor_id: int,
        evidence_type: str,
        source_family: str,
        polarity: str,
        strength: str,
        scope: str,
        artifact_path: str,
        extractor_version: str,
    ) -> IdentityEvidence:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO identity_evidence (
                        video_id, target_pastor_id, evidence_type, source_family, polarity,
                        strength, scope, artifact_path, extractor_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        target_pastor_id,
                        evidence_type,
                        source_family,
                        polarity,
                        strength,
                        scope,
                        artifact_path,
                        extractor_version,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, video_id, target_pastor_id, evidence_type, source_family, polarity,
                           strength, scope, artifact_path, extractor_version, created_at
                    FROM identity_evidence
                    WHERE video_id = ? AND target_pastor_id = ? AND evidence_type = ?
                      AND artifact_path = ?
                    """,
                    (video_id, target_pastor_id, evidence_type, artifact_path),
                ).fetchone()
                if row is None:
                    raise
                return self._identity_evidence_from_row(row)
        return IdentityEvidence(
            id=int(cursor.lastrowid),
            video_id=video_id,
            target_pastor_id=target_pastor_id,
            evidence_type=evidence_type,
            source_family=source_family,
            polarity=polarity,
            strength=strength,
            scope=scope,
            artifact_path=artifact_path,
            extractor_version=extractor_version,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def list_identity_evidence_for_video(self, video_id: int) -> list[IdentityEvidence]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, target_pastor_id, evidence_type, source_family, polarity,
                       strength, scope, artifact_path, extractor_version, created_at
                FROM identity_evidence
                WHERE video_id = ?
                ORDER BY id
                """,
                (video_id,),
            ).fetchall()
        return [self._identity_evidence_from_row(row) for row in rows]

    def get_identity_assessment_by_fingerprint(self, input_fingerprint: str) -> IdentityAssessment | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, target_pastor_id, extraction_result_id, state,
                       recommended_action, shadow_mode, policy_version, evidence_ledger_path,
                       assessment_path, input_fingerprint, created_at
                FROM identity_assessments
                WHERE input_fingerprint = ?
                """,
                (input_fingerprint,),
            ).fetchone()
        return self._identity_assessment_from_row(row) if row is not None else None

    def add_identity_assessment(
        self,
        *,
        video_id: int,
        target_pastor_id: int,
        extraction_result_id: int,
        state: IdentityState,
        recommended_action: IdentityAction,
        shadow_mode: bool,
        policy_version: str,
        evidence_ledger_path: str,
        assessment_path: str,
        input_fingerprint: str,
    ) -> IdentityAssessment:
        existing = self.get_identity_assessment_by_fingerprint(input_fingerprint)
        if existing is not None:
            return existing
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO identity_assessments (
                        video_id, target_pastor_id, extraction_result_id, state, recommended_action,
                        shadow_mode, policy_version, evidence_ledger_path, assessment_path,
                        input_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        target_pastor_id,
                        extraction_result_id,
                        state.value,
                        recommended_action.value,
                        1 if shadow_mode else 0,
                        policy_version,
                        evidence_ledger_path,
                        assessment_path,
                        input_fingerprint,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, video_id, target_pastor_id, extraction_result_id, state,
                           recommended_action, shadow_mode, policy_version, evidence_ledger_path,
                           assessment_path, input_fingerprint, created_at
                    FROM identity_assessments
                    WHERE input_fingerprint = ?
                    """,
                    (input_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return self._identity_assessment_from_row(row)
        return IdentityAssessment(
            id=int(cursor.lastrowid),
            video_id=video_id,
            target_pastor_id=target_pastor_id,
            extraction_result_id=extraction_result_id,
            state=state,
            recommended_action=recommended_action,
            shadow_mode=shadow_mode,
            policy_version=policy_version,
            evidence_ledger_path=evidence_ledger_path,
            assessment_path=assessment_path,
            input_fingerprint=input_fingerprint,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def get_latest_identity_assessment_for_video(self, video_id: int) -> IdentityAssessment | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, target_pastor_id, extraction_result_id, state,
                       recommended_action, shadow_mode, policy_version, evidence_ledger_path,
                       assessment_path, input_fingerprint, created_at
                FROM identity_assessments
                WHERE video_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        return self._identity_assessment_from_row(row) if row is not None else None

    def ensure_speaker_profile(
        self,
        *,
        stable_key: str,
        display_label: str | None,
        lifecycle_state: str,
        created_reason: str,
    ) -> SpeakerProfile:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO speaker_profiles (
                        stable_key, display_label, lifecycle_state, created_reason, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (stable_key, display_label, lifecycle_state, created_reason, created_at),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, stable_key, display_label, lifecycle_state, created_reason, created_at
                    FROM speaker_profiles WHERE stable_key = ?
                    """,
                    (stable_key,),
                ).fetchone()
                if row is None:
                    raise
                return self._speaker_profile_from_row(row)
        return SpeakerProfile(
            id=int(cursor.lastrowid),
            stable_key=stable_key,
            display_label=display_label,
            lifecycle_state=lifecycle_state,
            created_reason=created_reason,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def get_speaker_profile(self, profile_id: int) -> SpeakerProfile | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, stable_key, display_label, lifecycle_state, created_reason, created_at
                FROM speaker_profiles WHERE id = ?
                """,
                (profile_id,),
            ).fetchone()
        return self._speaker_profile_from_row(row) if row is not None else None

    def list_speaker_profiles(self) -> list[SpeakerProfile]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, stable_key, display_label, lifecycle_state, created_reason, created_at
                FROM speaker_profiles ORDER BY id
                """
            ).fetchall()
        return [self._speaker_profile_from_row(row) for row in rows]

    def ensure_pastor_speaker_binding(self, pastor_id: int, profile_id: int) -> int:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO pastor_speaker_bindings (
                    pastor_id, profile_id, binding_kind, created_at
                ) VALUES (?, ?, 'configured_requested_identity', ?)
                """,
                (pastor_id, profile_id, created_at),
            )
            row = connection.execute(
                "SELECT profile_id FROM pastor_speaker_bindings WHERE pastor_id = ?",
                (pastor_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Pastor speaker binding was not persisted")
        return int(row["profile_id"])

    def get_pastor_speaker_profile_id(self, pastor_id: int) -> int | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT profile_id
                FROM pastor_speaker_bindings
                WHERE pastor_id = ?
                """,
                (pastor_id,),
            ).fetchone()
        return int(row["profile_id"]) if row is not None else None

    def add_speaker_observation(
        self,
        *,
        video_id: int,
        extraction_result_id: int,
        role: str,
        multiplicity_state: str,
        start_seconds: float,
        end_seconds: float,
        artifact_path: str,
        content_sha256: str,
        extractor_version: str,
        input_fingerprint: str,
    ) -> SpeakerObservation:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO speaker_observations (
                        video_id, extraction_result_id, role, multiplicity_state,
                        start_seconds, end_seconds, artifact_path, content_sha256,
                        extractor_version, input_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        extraction_result_id,
                        role,
                        multiplicity_state,
                        start_seconds,
                        end_seconds,
                        artifact_path,
                        content_sha256,
                        extractor_version,
                        input_fingerprint,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, video_id, extraction_result_id, role, multiplicity_state,
                           start_seconds, end_seconds, artifact_path, content_sha256,
                           extractor_version, input_fingerprint, created_at
                    FROM speaker_observations WHERE input_fingerprint = ?
                    """,
                    (input_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return self._speaker_observation_from_row(row)
        return SpeakerObservation(
            id=int(cursor.lastrowid),
            video_id=video_id,
            extraction_result_id=extraction_result_id,
            role=role,
            multiplicity_state=multiplicity_state,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            artifact_path=artifact_path,
            content_sha256=content_sha256,
            extractor_version=extractor_version,
            input_fingerprint=input_fingerprint,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def get_speaker_observation_by_fingerprint(
        self, input_fingerprint: str
    ) -> SpeakerObservation | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, extraction_result_id, role, multiplicity_state,
                       start_seconds, end_seconds, artifact_path, content_sha256,
                       extractor_version, input_fingerprint, created_at
                FROM speaker_observations WHERE input_fingerprint = ?
                """,
                (input_fingerprint,),
            ).fetchone()
        return self._speaker_observation_from_row(row) if row is not None else None

    def get_speaker_observation(self, observation_id: int) -> SpeakerObservation | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, extraction_result_id, role, multiplicity_state,
                       start_seconds, end_seconds, artifact_path, content_sha256,
                       extractor_version, input_fingerprint, created_at
                FROM speaker_observations WHERE id = ?
                """,
                (observation_id,),
            ).fetchone()
        return self._speaker_observation_from_row(row) if row is not None else None

    def list_speaker_observations(self) -> list[SpeakerObservation]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, extraction_result_id, role, multiplicity_state,
                       start_seconds, end_seconds, artifact_path, content_sha256,
                       extractor_version, input_fingerprint, created_at
                FROM speaker_observations
                ORDER BY id
                """
            ).fetchall()
        return [self._speaker_observation_from_row(row) for row in rows]

    def get_latest_speaker_observation_for_video(
        self, video_id: int
    ) -> SpeakerObservation | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, extraction_result_id, role, multiplicity_state,
                       start_seconds, end_seconds, artifact_path, content_sha256,
                       extractor_version, input_fingerprint, created_at
                FROM speaker_observations WHERE video_id = ? ORDER BY id DESC LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        return self._speaker_observation_from_row(row) if row is not None else None

    def get_speaker_observation_for_extraction_window(
        self,
        video_id: int,
        extraction_result_id: int,
        *,
        start_seconds: float,
        end_seconds: float,
        tolerance_seconds: float = 0.001,
    ) -> SpeakerObservation | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, extraction_result_id, role, multiplicity_state,
                       start_seconds, end_seconds, artifact_path, content_sha256,
                       extractor_version, input_fingerprint, created_at
                FROM speaker_observations
                WHERE video_id = ?
                  AND extraction_result_id = ?
                  AND ABS(start_seconds - ?) <= ?
                  AND ABS(end_seconds - ?) <= ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    video_id,
                    extraction_result_id,
                    start_seconds,
                    tolerance_seconds,
                    end_seconds,
                    tolerance_seconds,
                ),
            ).fetchone()
        return self._speaker_observation_from_row(row) if row is not None else None

    def add_speaker_name_claim(
        self,
        *,
        video_id: int,
        observation_id: int | None,
        display_name: str,
        normalized_name: str,
        claim_kind: str,
        channel: str,
        explicit_speaker_attribution: bool,
        correlation_group_id: str,
        provenance_json: str,
        artifact_path: str,
        claim_fingerprint: str,
        extractor_version: str,
    ) -> SpeakerNameClaim:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO speaker_name_claims (
                        video_id, observation_id, display_name, normalized_name, claim_kind,
                        channel, explicit_speaker_attribution, correlation_group_id,
                        provenance_json, artifact_path, claim_fingerprint, extractor_version,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        observation_id,
                        display_name,
                        normalized_name,
                        claim_kind,
                        channel,
                        1 if explicit_speaker_attribution else 0,
                        correlation_group_id,
                        provenance_json,
                        artifact_path,
                        claim_fingerprint,
                        extractor_version,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, video_id, observation_id, display_name, normalized_name,
                           claim_kind, channel, explicit_speaker_attribution,
                           correlation_group_id, provenance_json, artifact_path,
                           claim_fingerprint, extractor_version, created_at
                    FROM speaker_name_claims WHERE claim_fingerprint = ?
                    """,
                    (claim_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return self._speaker_name_claim_from_row(row)
        return SpeakerNameClaim(
            id=int(cursor.lastrowid),
            video_id=video_id,
            observation_id=observation_id,
            display_name=display_name,
            normalized_name=normalized_name,
            claim_kind=claim_kind,
            channel=channel,
            explicit_speaker_attribution=explicit_speaker_attribution,
            correlation_group_id=correlation_group_id,
            provenance_json=provenance_json,
            artifact_path=artifact_path,
            claim_fingerprint=claim_fingerprint,
            extractor_version=extractor_version,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def list_speaker_name_claims_for_video(self, video_id: int) -> list[SpeakerNameClaim]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, observation_id, display_name, normalized_name,
                       claim_kind, channel, explicit_speaker_attribution,
                       correlation_group_id, provenance_json, artifact_path,
                       claim_fingerprint, extractor_version, created_at
                FROM speaker_name_claims WHERE video_id = ? ORDER BY id
                """,
                (video_id,),
            ).fetchall()
        return [self._speaker_name_claim_from_row(row) for row in rows]

    def list_speaker_name_claims(self) -> list[SpeakerNameClaim]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, observation_id, display_name, normalized_name,
                       claim_kind, channel, explicit_speaker_attribution,
                       correlation_group_id, provenance_json, artifact_path,
                       claim_fingerprint, extractor_version, created_at
                FROM speaker_name_claims
                ORDER BY id
                """
            ).fetchall()
        return [self._speaker_name_claim_from_row(row) for row in rows]

    def get_speaker_name_claim(self, claim_id: int) -> SpeakerNameClaim | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, observation_id, display_name, normalized_name,
                       claim_kind, channel, explicit_speaker_attribution,
                       correlation_group_id, provenance_json, artifact_path,
                       claim_fingerprint, extractor_version, created_at
                FROM speaker_name_claims WHERE id = ?
                """,
                (claim_id,),
            ).fetchone()
        return self._speaker_name_claim_from_row(row) if row is not None else None

    def add_profile_observation_event(
        self,
        *,
        profile_id: int,
        observation_id: int,
        action: str,
        reviewer: str,
        reason: str,
        event_fingerprint: str,
    ) -> int:
        return self._add_registry_event(
            table="profile_observation_events",
            columns=("profile_id", "observation_id", "action", "reviewer", "reason"),
            values=(profile_id, observation_id, action, reviewer, reason),
            event_fingerprint=event_fingerprint,
        )

    def add_speaker_profile_creation_event(
        self,
        *,
        profile_id: int,
        reviewer: str,
        reason: str,
        event_fingerprint: str,
    ) -> int:
        return self._add_registry_event(
            table="speaker_profile_creation_events",
            columns=("profile_id", "reviewer", "reason"),
            values=(profile_id, reviewer, reason),
            event_fingerprint=event_fingerprint,
        )

    def add_speaker_profile_discovery_promotion(
        self,
        *,
        profile_id: int,
        component_id: str,
        discovery_result_sha256: str,
        discovery_artifact_path: str,
        seed_observation_ids_json: str,
        event_fingerprint: str,
    ) -> int:
        created_at = utc_now().isoformat()
        values = (
            profile_id,
            component_id,
            discovery_result_sha256,
            discovery_artifact_path,
            seed_observation_ids_json,
            event_fingerprint,
            created_at,
        )
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO speaker_profile_discovery_promotions (
                        profile_id, component_id, discovery_result_sha256,
                        discovery_artifact_path, seed_observation_ids_json,
                        event_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT profile_id, component_id, discovery_result_sha256,
                           discovery_artifact_path, seed_observation_ids_json
                    FROM speaker_profile_discovery_promotions
                    WHERE event_fingerprint = ?
                    """,
                    (event_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                persisted = (
                    int(row["profile_id"]),
                    str(row["component_id"]),
                    str(row["discovery_result_sha256"]),
                    str(row["discovery_artifact_path"]),
                    str(row["seed_observation_ids_json"]),
                )
                if persisted != values[:5]:
                    raise ValueError(
                        "Discovery promotion event fingerprint collision"
                    )
                return int(row["profile_id"])
        return int(cursor.lastrowid)

    def get_speaker_profile_discovery_promotion(
        self, profile_id: int
    ) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT profile_id, component_id, discovery_result_sha256,
                       discovery_artifact_path, seed_observation_ids_json,
                       event_fingerprint, created_at
                FROM speaker_profile_discovery_promotions
                WHERE profile_id = ?
                """,
                (profile_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def add_speaker_profile_candidate_confirmation(
        self,
        *,
        profile_id: int,
        observation_id: int,
        association_result_sha256: str,
        association_artifact_path: str,
        event_fingerprint: str,
    ) -> int:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO speaker_profile_candidate_confirmations (
                        profile_id, observation_id, association_result_sha256,
                        association_artifact_path, event_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id,
                        observation_id,
                        association_result_sha256,
                        association_artifact_path,
                        event_fingerprint,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, profile_id, observation_id,
                           association_result_sha256, association_artifact_path
                    FROM speaker_profile_candidate_confirmations
                    WHERE event_fingerprint = ?
                    """,
                    (event_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                persisted = (
                    int(row["profile_id"]),
                    int(row["observation_id"]),
                    str(row["association_result_sha256"]),
                    str(row["association_artifact_path"]),
                )
                expected = (
                    profile_id,
                    observation_id,
                    association_result_sha256,
                    association_artifact_path,
                )
                if persisted != expected:
                    raise ValueError(
                        "Candidate confirmation event fingerprint collision"
                    )
                return int(row["id"])
        return int(cursor.lastrowid)

    def list_speaker_profile_candidate_confirmations(
        self, profile_id: int
    ) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, profile_id, observation_id,
                       association_result_sha256, association_artifact_path,
                       event_fingerprint, created_at
                FROM speaker_profile_candidate_confirmations
                WHERE profile_id = ?
                ORDER BY id
                """,
                (profile_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_speaker_machine_evidence(
        self,
        *,
        observation_id: int,
        profile_id: int,
        candidate_input_fingerprint: str,
        association_result_sha256: str,
        association_artifact_path: str,
        model_fingerprint: str,
        policy_fingerprint: str,
        profile_snapshot_fingerprint: str,
        exemplar_fingerprints_json: str,
        same_exemplar_count: int,
        different_exemplar_count: int,
        decision: str,
        evidence_fingerprint: str,
    ) -> int:
        created_at = utc_now().isoformat()
        values = (
            observation_id,
            profile_id,
            candidate_input_fingerprint,
            association_result_sha256,
            association_artifact_path,
            model_fingerprint,
            policy_fingerprint,
            profile_snapshot_fingerprint,
            exemplar_fingerprints_json,
            same_exemplar_count,
            different_exemplar_count,
            decision,
            evidence_fingerprint,
            created_at,
        )
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO speaker_machine_evidence (
                        observation_id, profile_id,
                        candidate_input_fingerprint,
                        association_result_sha256,
                        association_artifact_path, model_fingerprint,
                        policy_fingerprint, profile_snapshot_fingerprint,
                        exemplar_fingerprints_json, same_exemplar_count,
                        different_exemplar_count, decision,
                        evidence_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, observation_id, profile_id,
                           candidate_input_fingerprint,
                           association_result_sha256,
                           association_artifact_path, model_fingerprint,
                           policy_fingerprint, profile_snapshot_fingerprint,
                           exemplar_fingerprints_json, same_exemplar_count,
                           different_exemplar_count, decision
                    FROM speaker_machine_evidence
                    WHERE evidence_fingerprint = ?
                    """,
                    (evidence_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                persisted = tuple(row[key] for key in row.keys() if key != "id")
                if persisted != values[:12]:
                    raise ValueError(
                        "Machine evidence fingerprint collision"
                    )
                return int(row["id"])
        return int(cursor.lastrowid)

    def add_speaker_machine_assignment_event(
        self,
        *,
        machine_evidence_id: int,
        observation_id: int,
        profile_id: int,
        action: str,
        actor: str,
        reason: str,
        event_fingerprint: str,
    ) -> int:
        return self._add_registry_event(
            table="speaker_machine_assignment_events",
            columns=(
                "machine_evidence_id",
                "observation_id",
                "profile_id",
                "action",
                "actor",
                "reason",
            ),
            values=(
                machine_evidence_id,
                observation_id,
                profile_id,
                action,
                actor,
                reason,
            ),
            event_fingerprint=event_fingerprint,
        )

    def list_speaker_machine_evidence(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, observation_id, profile_id,
                       candidate_input_fingerprint,
                       association_result_sha256,
                       association_artifact_path, model_fingerprint,
                       policy_fingerprint, profile_snapshot_fingerprint,
                       exemplar_fingerprints_json, same_exemplar_count,
                       different_exemplar_count, decision,
                       evidence_fingerprint, created_at
                FROM speaker_machine_evidence
                ORDER BY id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_speaker_machine_assignment_events(
        self,
    ) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, machine_evidence_id, observation_id, profile_id,
                       action, actor, reason, event_fingerprint, created_at
                FROM speaker_machine_assignment_events
                ORDER BY id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def add_speaker_observation_review_event(
        self,
        *,
        observation_id: int,
        action: str,
        reviewer: str,
        reason: str,
        event_fingerprint: str,
    ) -> int:
        return self._add_registry_event(
            table="speaker_observation_review_events",
            columns=("observation_id", "action", "reviewer", "reason"),
            values=(observation_id, action, reviewer, reason),
            event_fingerprint=event_fingerprint,
        )

    def add_speaker_observation_grouping_event(
        self,
        *,
        observation_id: int,
        action: str,
        reviewer: str,
        reason: str,
        event_fingerprint: str,
    ) -> int:
        return self._add_registry_event(
            table="speaker_observation_grouping_events",
            columns=("observation_id", "action", "reviewer", "reason"),
            values=(observation_id, action, reviewer, reason),
            event_fingerprint=event_fingerprint,
        )

    def add_speaker_observation_difference_event(
        self,
        *,
        observation_a_id: int,
        observation_b_id: int,
        action: str,
        reviewer: str,
        reason: str,
        event_fingerprint: str,
    ) -> int:
        return self._add_registry_event(
            table="speaker_observation_difference_events",
            columns=(
                "observation_a_id",
                "observation_b_id",
                "action",
                "reviewer",
                "reason",
            ),
            values=(
                observation_a_id,
                observation_b_id,
                action,
                reviewer,
                reason,
            ),
            event_fingerprint=event_fingerprint,
        )

    def add_profile_name_claim_event(
        self,
        *,
        profile_id: int | None,
        claim_id: int,
        action: str,
        reviewer: str,
        reason: str,
        event_fingerprint: str,
    ) -> int:
        return self._add_registry_event(
            table="profile_name_claim_events",
            columns=("profile_id", "claim_id", "action", "reviewer", "reason"),
            values=(profile_id, claim_id, action, reviewer, reason),
            event_fingerprint=event_fingerprint,
        )

    def add_profile_redirect_event(
        self,
        *,
        from_profile_id: int,
        to_profile_id: int | None,
        action: str,
        reviewer: str,
        reason: str,
        event_fingerprint: str,
    ) -> int:
        return self._add_registry_event(
            table="speaker_profile_redirect_events",
            columns=("from_profile_id", "to_profile_id", "action", "reviewer", "reason"),
            values=(from_profile_id, to_profile_id, action, reviewer, reason),
            event_fingerprint=event_fingerprint,
        )

    def _add_registry_event(
        self,
        *,
        table: str,
        columns: tuple[str, ...],
        values: tuple[object, ...],
        event_fingerprint: str,
    ) -> int:
        allowed_tables = {
            "profile_observation_events",
            "speaker_profile_creation_events",
            "speaker_observation_review_events",
            "speaker_observation_grouping_events",
            "speaker_observation_difference_events",
            "profile_name_claim_events",
            "speaker_profile_redirect_events",
            "speaker_machine_assignment_events",
        }
        if table not in allowed_tables:
            raise ValueError(f"Unsupported registry event table: {table}")
        created_at = utc_now().isoformat()
        column_sql = ", ".join((*columns, "event_fingerprint", "created_at"))
        placeholders = ", ".join("?" for _ in range(len(columns) + 2))
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
                    (*values, event_fingerprint, created_at),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    f"SELECT id, {', '.join(columns)} FROM {table} "
                    "WHERE event_fingerprint = ?",
                    (event_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                persisted_values = tuple(row[column] for column in columns)
                if persisted_values != values:
                    raise ValueError(
                        f"Registry event fingerprint collision in {table}"
                    )
                return int(row["id"])
        return int(cursor.lastrowid)

    def get_effective_profile_redirect(self, from_profile_id: int) -> int | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT action, to_profile_id
                FROM speaker_profile_redirect_events
                WHERE from_profile_id = ? ORDER BY id DESC LIMIT 1
                """,
                (from_profile_id,),
            ).fetchone()
        if row is None or str(row["action"]) == "clear":
            return None
        return int(row["to_profile_id"])

    def resolve_speaker_profile_id(self, profile_id: int) -> int:
        if self.get_speaker_profile(profile_id) is None:
            raise ValueError(f"Unknown speaker profile: {profile_id}")
        visited: set[int] = set()
        current = profile_id
        while True:
            if current in visited:
                raise ValueError("Speaker profile redirect cycle detected")
            visited.add(current)
            redirected = self.get_effective_profile_redirect(current)
            if redirected is None:
                return current
            current = redirected

    def get_effective_name_claim_review(
        self, claim_id: int
    ) -> tuple[str, int | None] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT action, profile_id
                FROM profile_name_claim_events
                WHERE claim_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (claim_id,),
            ).fetchone()
        if row is None:
            return None
        profile_id = row["profile_id"]
        return (
            str(row["action"]),
            int(profile_id) if profile_id is not None else None,
        )

    def list_effective_name_claim_ids_for_profile(
        self, profile_id: int
    ) -> list[int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT event.claim_id
                FROM profile_name_claim_events event
                JOIN (
                    SELECT claim_id, MAX(id) AS event_id
                    FROM profile_name_claim_events
                    GROUP BY claim_id
                ) latest ON latest.event_id = event.id
                WHERE event.action = 'attach' AND event.profile_id = ?
                ORDER BY event.claim_id
                """,
                (profile_id,),
            ).fetchall()
        return [int(row["claim_id"]) for row in rows]

    def is_observation_attached(self, profile_id: int, observation_id: int) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT action FROM profile_observation_events
                WHERE profile_id = ? AND observation_id = ? ORDER BY id DESC LIMIT 1
                """,
                (profile_id, observation_id),
            ).fetchone()
        return row is not None and str(row["action"]) == "attach"

    def list_effective_profile_ids_for_observation(
        self, observation_id: int
    ) -> list[int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT event.profile_id
                FROM profile_observation_events event
                JOIN (
                    SELECT profile_id, observation_id, MAX(id) AS event_id
                    FROM profile_observation_events
                    WHERE observation_id = ?
                    GROUP BY profile_id, observation_id
                ) latest ON latest.event_id = event.id
                WHERE event.action = 'attach'
                ORDER BY event.profile_id
                """,
                (observation_id,),
            ).fetchall()
        return [int(row["profile_id"]) for row in rows]

    def list_effective_observation_ids_for_profile(self, profile_id: int) -> list[int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT event.observation_id
                FROM profile_observation_events event
                JOIN (
                    SELECT profile_id, observation_id, MAX(id) AS event_id
                    FROM profile_observation_events
                    WHERE profile_id = ?
                    GROUP BY profile_id, observation_id
                ) latest ON latest.event_id = event.id
                WHERE event.action = 'attach'
                ORDER BY event.observation_id
                """,
                (profile_id,),
            ).fetchall()
        return [int(row["observation_id"]) for row in rows]

    def get_effective_observation_review_action(
        self, observation_id: int
    ) -> str | None:
        event = self.get_effective_observation_review_event(observation_id)
        return event[0] if event is not None else None

    def get_effective_observation_review_event(
        self, observation_id: int
    ) -> tuple[str, str, str] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT action, reviewer, reason
                FROM speaker_observation_review_events
                WHERE observation_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (observation_id,),
            ).fetchone()
        if row is None:
            return None
        return (
            str(row["action"]),
            str(row["reviewer"]),
            str(row["reason"]),
        )

    def get_effective_observation_grouping_action(
        self, observation_id: int
    ) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT action
                FROM speaker_observation_grouping_events
                WHERE observation_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (observation_id,),
            ).fetchone()
        return str(row["action"]) if row is not None else None

    def list_effective_observation_difference_pairs(self) -> list[tuple[int, int]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT event.observation_a_id, event.observation_b_id
                FROM speaker_observation_difference_events event
                JOIN (
                    SELECT observation_a_id, observation_b_id, MAX(id) AS event_id
                    FROM speaker_observation_difference_events
                    GROUP BY observation_a_id, observation_b_id
                ) latest ON latest.event_id = event.id
                WHERE event.action = 'assert'
                ORDER BY event.observation_a_id, event.observation_b_id
                """
            ).fetchall()
        return [
            (int(row["observation_a_id"]), int(row["observation_b_id"]))
            for row in rows
        ]

    def counts_by_table(self) -> dict[str, int]:
        with self.connect() as connection:
            organization_count = connection.execute(
                "SELECT COUNT(*) FROM organizations"
            ).fetchone()[0]
            affiliation_claim_count = connection.execute(
                "SELECT COUNT(*) FROM organization_affiliation_claims"
            ).fetchone()[0]
            pastor_affiliation_count = connection.execute(
                "SELECT COUNT(*) FROM pastor_organization_affiliations"
            ).fetchone()[0]
            affiliation_review_count = connection.execute(
                "SELECT COUNT(*) FROM affiliation_claim_review_events"
            ).fetchone()[0]
            source_count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            source_import_ref_count = connection.execute(
                "SELECT COUNT(*) FROM source_import_refs"
            ).fetchone()[0]
            pastor_count = connection.execute("SELECT COUNT(*) FROM pastors").fetchone()[0]
            video_count = connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            transcript_count = connection.execute("SELECT COUNT(*) FROM transcript_artifacts").fetchone()[0]
            segment_count = connection.execute("SELECT COUNT(*) FROM transcript_segments").fetchone()[0]
            extraction_count = connection.execute("SELECT COUNT(*) FROM extraction_results").fetchone()[0]
            review_count = connection.execute("SELECT COUNT(*) FROM review_results").fetchone()[0]
            excluded_count = connection.execute("SELECT COUNT(*) FROM excluded_videos").fetchone()[0]
            metadata_count = connection.execute("SELECT COUNT(*) FROM metadata_artifacts").fetchone()[0]
            identity_evidence_count = connection.execute("SELECT COUNT(*) FROM identity_evidence").fetchone()[0]
            identity_assessment_count = connection.execute("SELECT COUNT(*) FROM identity_assessments").fetchone()[0]
            speaker_profile_count = connection.execute("SELECT COUNT(*) FROM speaker_profiles").fetchone()[0]
            speaker_observation_count = connection.execute("SELECT COUNT(*) FROM speaker_observations").fetchone()[0]
            speaker_name_claim_count = connection.execute("SELECT COUNT(*) FROM speaker_name_claims").fetchone()[0]
            media_artifact_count = connection.execute("SELECT COUNT(*) FROM media_artifacts").fetchone()[0]
            media_attempt_count = connection.execute("SELECT COUNT(*) FROM media_acquisition_attempts").fetchone()[0]
            media_archive_entry_count = connection.execute("SELECT COUNT(*) FROM media_archive_entries").fetchone()[0]
            media_archive_attempt_count = connection.execute("SELECT COUNT(*) FROM media_archive_attempts").fetchone()[0]
        return {
            "organizations": int(organization_count),
            "organization_affiliation_claims": int(affiliation_claim_count),
            "pastor_organization_affiliations": int(pastor_affiliation_count),
            "affiliation_claim_review_events": int(affiliation_review_count),
            "sources": int(source_count),
            "source_import_refs": int(source_import_ref_count),
            "pastors": int(pastor_count),
            "videos": int(video_count),
            "transcript_artifacts": int(transcript_count),
            "transcript_segments": int(segment_count),
            "extraction_results": int(extraction_count),
            "review_results": int(review_count),
            "excluded_videos": int(excluded_count),
            "metadata_artifacts": int(metadata_count),
            "identity_evidence": int(identity_evidence_count),
            "identity_assessments": int(identity_assessment_count),
            "speaker_profiles": int(speaker_profile_count),
            "speaker_observations": int(speaker_observation_count),
            "speaker_name_claims": int(speaker_name_claim_count),
            "media_artifacts": int(media_artifact_count),
            "media_acquisition_attempts": int(media_attempt_count),
            "media_archive_entries": int(media_archive_entry_count),
            "media_archive_attempts": int(media_archive_attempt_count),
        }
