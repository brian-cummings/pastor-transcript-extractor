from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.discovery import DiscoveredVideo
from pastor_transcript_extractor.extraction import extract_video
from pastor_transcript_extractor.exporting import (
    export_organization_review_markdown,
    export_pastor_review_markdown,
)
from pastor_transcript_extractor.models import (
    SourceType,
    TranscriptSourceKind,
    VideoStatus,
)
from pastor_transcript_extractor.source_ownership import (
    audit_source_ownership,
    backfill_source_ownership,
)
from pastor_transcript_extractor.storage import Database


class SourceOwnershipMigrationTests(unittest.TestCase):
    def test_not_null_legacy_owner_columns_are_relaxed_without_changing_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.db"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE pastors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    notes TEXT NULL
                );
                CREATE TABLE sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pastor_id INTEGER NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    source_identity_key TEXT NULL,
                    source_type TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    notes TEXT NULL
                );
                CREATE TABLE videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL,
                    pastor_id INTEGER NOT NULL,
                    youtube_video_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    channel_name TEXT NULL,
                    published_at TEXT NULL,
                    duration_seconds INTEGER NULL,
                    status TEXT NOT NULL,
                    failure_reason TEXT NULL
                );
                INSERT INTO pastors VALUES (
                    7, 'legacy', 'Legacy Pastor', '2026-01-01T00:00:00Z', NULL
                );
                INSERT INTO sources VALUES (
                    11, 7, 'https://www.youtube.com/@legacy', NULL,
                    'channel', '2026-01-01T00:00:00Z', NULL
                );
                INSERT INTO videos VALUES (
                    13, 11, 7, 'legacyvid01', 'Legacy Video',
                    'https://www.youtube.com/watch?v=legacyvid01',
                    'Legacy Church', NULL, 1200, 'discovered', NULL
                );
                """
            )
            connection.commit()
            connection.close()

            database = Database(path)
            database.initialize()

            with database.connect() as connection:
                source_info = {
                    row["name"]: row
                    for row in connection.execute(
                        "PRAGMA table_info(sources)"
                    ).fetchall()
                }
                video_info = {
                    row["name"]: row
                    for row in connection.execute(
                        "PRAGMA table_info(videos)"
                    ).fetchall()
                }
                source = connection.execute(
                    "SELECT id, pastor_id FROM sources"
                ).fetchone()
                video = connection.execute(
                    "SELECT id, pastor_id FROM videos"
                ).fetchone()

            self.assertEqual(0, source_info["pastor_id"]["notnull"])
            self.assertEqual(0, video_info["pastor_id"]["notnull"])
            self.assertEqual((11, 7), (source["id"], source["pastor_id"]))
            self.assertEqual((13, 7), (video["id"], video["pastor_id"]))

    def test_legacy_manual_source_gets_target_projection_but_no_organization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = Database(root / "app.db")
            database.initialize()
            pastor = database.add_pastor("manual-target", "Manual Target")
            source = database.add_source(
                "https://www.youtube.com/@manual",
                SourceType.CHANNEL,
                pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="manualvideo1",
                title="Manual Video",
                url="https://www.youtube.com/watch?v=manualvideo1",
            )

            database.initialize()

            with database.connect() as connection:
                stored_source = connection.execute(
                    "SELECT organization_id FROM sources WHERE id = ?",
                    (source.id,),
                ).fetchone()
                policies = connection.execute(
                    "SELECT * FROM source_target_policies WHERE source_id = ?",
                    (source.id,),
                ).fetchall()
                contexts = connection.execute(
                    "SELECT * FROM video_target_contexts WHERE video_id = ?",
                    (video.id,),
                ).fetchall()
                namespace = connection.execute(
                    "SELECT * FROM video_artifact_namespaces WHERE video_id = ?",
                    (video.id,),
                ).fetchone()
                report = audit_source_ownership(connection, app_root=root)

            self.assertIsNone(stored_source["organization_id"])
            self.assertEqual(1, len(policies))
            self.assertEqual(pastor.id, policies[0]["pastor_id"])
            self.assertEqual(1, len(contexts))
            self.assertEqual(pastor.id, contexts[0]["pastor_id"])
            self.assertEqual("legacy_pastor_v1", namespace["scheme"])
            self.assertEqual(
                "pastors/manual-target/videos/manualvideo1",
                namespace["relative_root"],
            )
            self.assertTrue(report.ok)

    def test_legacy_import_backfills_grounded_organization_and_unlinked_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = Database(root / "app.db")
            database.initialize()
            pastor = database.add_pastor("legacy-import", "Imported Pastor")
            source = database.add_source(
                "https://www.youtube.com/@imported",
                SourceType.CHANNEL,
                pastor.id,
            )
            payload = {
                "church_name": "Imported Church",
                "pastor_name": "Imported Pastor",
                "channel_key": "youtube:channel:UCaaaaaaaaaaaaaaaaaaaaaa",
            }
            with database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO source_import_refs (
                        source_id, pastor_id, provider, external_entity_key,
                        external_record_id, imported_fingerprint,
                        import_payload_json, external_updated_at, imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source.id,
                        pastor.id,
                        "church-youtube-finder",
                        "church-source-url:https://directory.test/church/9",
                        "9",
                        "fingerprint-9",
                        json.dumps(payload, sort_keys=True),
                        "2026-07-19T00:00:00Z",
                        "2026-07-20T00:00:00Z",
                    ),
                )

            database.initialize()

            with database.connect() as connection:
                organization = connection.execute(
                    "SELECT * FROM organizations"
                ).fetchone()
                stored_source = connection.execute(
                    "SELECT organization_id FROM sources WHERE id = ?",
                    (source.id,),
                ).fetchone()
                snapshot_count = connection.execute(
                    "SELECT COUNT(*) FROM external_record_snapshots"
                ).fetchone()[0]
                claim = connection.execute(
                    "SELECT * FROM organization_affiliation_claims"
                ).fetchone()
                profile_count = connection.execute(
                    "SELECT COUNT(*) FROM speaker_profiles"
                ).fetchone()[0]
                affiliation_count = connection.execute(
                    "SELECT COUNT(*) FROM pastor_organization_affiliations"
                ).fetchone()[0]

            self.assertEqual("Imported Church", organization["display_name"])
            self.assertEqual(organization["id"], stored_source["organization_id"])
            self.assertEqual(1, snapshot_count)
            self.assertEqual("Imported Pastor", claim["claimed_person_name"])
            self.assertEqual(0, profile_count)
            self.assertEqual(0, affiliation_count)

    def test_backfill_replay_creates_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "app.db")
            database.initialize()
            pastor = database.add_pastor("target", "Target")
            source = database.add_source(
                "https://www.youtube.com/@target",
                SourceType.CHANNEL,
                pastor.id,
            )
            database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="targetvideo1",
                title="Target Video",
                url="https://www.youtube.com/watch?v=targetvideo1",
            )
            database.initialize()

            with database.connect() as connection:
                replay = backfill_source_ownership(connection)

            self.assertEqual(
                {0},
                {
                    replay.organizations_created,
                    replay.external_refs_created,
                    replay.snapshots_created,
                    replay.source_links_created,
                    replay.affiliation_claims_created,
                    replay.source_events_created,
                    replay.source_target_policies_created,
                    replay.video_target_contexts_created,
                    replay.artifact_namespaces_created,
                },
            )

    def test_cli_strict_audit_passes(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(
                app,
                ["source-ownership", "audit", "--strict", "--base-dir", tmp],
            )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("Source ownership audit passed.", result.output)

    def test_cli_migration_dry_run_rolls_back(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "app.db")
            database.initialize()
            before = database.counts_by_table()

            result = runner.invoke(
                app,
                [
                    "source-ownership",
                    "migrate",
                    "--dry-run",
                    "--base-dir",
                    tmp,
                ],
            )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("migration preview", result.output)
            self.assertIn("Projected audit passed.", result.output)
            self.assertEqual(before, database.counts_by_table())

    def test_manual_source_can_start_unknown_and_later_attach_organization(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            add_source = runner.invoke(
                app,
                [
                    "source",
                    "add",
                    "https://www.youtube.com/@unknownpublisher",
                    "--base-dir",
                    tmp,
                ],
            )
            self.assertEqual(0, add_source.exit_code, msg=add_source.output)
            database = Database(Path(tmp) / "app.db")
            source = database.get_source_by_url(
                "https://www.youtube.com/@unknownpublisher"
            )
            self.assertIsNotNone(source)
            self.assertIsNone(source.pastor_id)
            self.assertIsNone(source.organization_id)

            add_organization = runner.invoke(
                app,
                [
                    "organization",
                    "add",
                    "manual-church",
                    "Manual Church",
                    "--base-dir",
                    tmp,
                ],
            )
            attach = runner.invoke(
                app,
                [
                    "source",
                    "set-organization",
                    str(source.id),
                    "manual-church",
                    "--base-dir",
                    tmp,
                ],
            )

            self.assertEqual(0, add_organization.exit_code, msg=add_organization.output)
            self.assertEqual(0, attach.exit_code, msg=attach.output)
            updated = database.get_source_by_id(source.id)
            organization = database.get_organization_by_slug("manual-church")
            self.assertEqual(organization.id, updated.organization_id)
            with database.connect() as connection:
                events = connection.execute(
                    "SELECT * FROM source_organization_events WHERE source_id = ?",
                    (source.id,),
                ).fetchall()
            self.assertEqual(1, len(events))

    def test_legacy_add_pastor_is_target_context_not_organization(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "app.db")
            database.initialize()
            pastor = database.add_pastor("target-pastor", "Target Pastor")

            result = runner.invoke(
                app,
                [
                    "add",
                    "https://www.youtube.com/@targetsource",
                    "--pastor",
                    pastor.slug,
                    "--base-dir",
                    tmp,
                ],
            )

            self.assertEqual(0, result.exit_code, msg=result.output)
            source = database.get_source_by_url(
                "https://www.youtube.com/@targetsource"
            )
            self.assertEqual(pastor.id, source.pastor_id)
            self.assertIsNone(source.organization_id)
            with database.connect() as connection:
                policy_count = connection.execute(
                    """
                    SELECT COUNT(*) FROM source_target_policies
                    WHERE source_id = ? AND pastor_id = ?
                    """,
                    (source.id, pastor.id),
                ).fetchone()[0]
            self.assertEqual(1, policy_count)

    def test_manual_affiliation_does_not_create_speaker_membership(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "app.db")
            database.initialize()
            pastor = database.add_pastor("affiliated", "Affiliated Pastor")
            organization = database.add_organization(
                "affiliation-church",
                "Affiliation Church",
                "church",
            )

            result = runner.invoke(
                app,
                [
                    "pastor",
                    "affiliate",
                    pastor.slug,
                    organization.slug,
                    "--role",
                    "Senior Pastor",
                    "--from",
                    "2024-01-01",
                    "--status",
                    "current",
                    "--base-dir",
                    tmp,
                ],
            )

            self.assertEqual(0, result.exit_code, msg=result.output)
            affiliations = database.list_pastor_organization_affiliations(pastor.id)
            self.assertEqual(1, len(affiliations))
            self.assertEqual("senior_pastor", affiliations[0].role_key)
            with database.connect() as connection:
                profile_count = connection.execute(
                    "SELECT COUNT(*) FROM speaker_profiles"
                ).fetchone()[0]
            self.assertEqual(0, profile_count)

    def test_imported_name_requires_explicit_claim_review_to_link_pastor(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "app.db")
            database.initialize()
            pastor = database.add_pastor("selected-person", "Selected Person")
            organization = database.add_organization(
                "claim-church",
                "Claim Church",
                "church",
            )
            with database.connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO organization_affiliation_claims (
                        organization_id, external_record_snapshot_id,
                        claimed_person_name, claimed_role, valid_from, valid_to,
                        claim_fingerprint, created_at
                    ) VALUES (?, NULL, ?, 'pastor', NULL, NULL, ?, ?)
                    """,
                    (
                        organization.id,
                        "Name That Is Not Used For Matching",
                        "explicit-claim-fingerprint",
                        "2026-07-26T00:00:00Z",
                    ),
                )
                claim_id = int(cursor.lastrowid)

            arguments = [
                "pastor",
                "affiliate-claim",
                pastor.slug,
                str(claim_id),
                "--reviewer",
                "Reviewer",
                "--reason",
                "Verified external record against curated person",
                "--base-dir",
                tmp,
            ]
            first = runner.invoke(app, arguments)
            replay = runner.invoke(app, arguments)

            self.assertEqual(0, first.exit_code, msg=first.output)
            self.assertEqual(0, replay.exit_code, msg=replay.output)
            affiliations = database.list_pastor_organization_affiliations(pastor.id)
            self.assertEqual(1, len(affiliations))
            self.assertEqual(claim_id, affiliations[0].affiliation_claim_id)
            with database.connect() as connection:
                review_count = connection.execute(
                    "SELECT COUNT(*) FROM affiliation_claim_review_events"
                ).fetchone()[0]
                profile_count = connection.execute(
                    "SELECT COUNT(*) FROM speaker_profiles"
                ).fetchone()[0]
            self.assertEqual(1, review_count)
            self.assertEqual(0, profile_count)

    def test_targetless_source_discovery_uses_neutral_artifact_namespace(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = Database(root / "app.db")
            database.initialize()
            organization = database.add_organization(
                "publisher",
                "Publisher",
                "network",
            )
            source = database.add_source(
                "https://www.youtube.com/@publisher",
                SourceType.CHANNEL,
                pastor_id=None,
                organization_id=organization.id,
            )
            discovered = DiscoveredVideo(
                youtube_video_id="neutral001x",
                title="Neutral Intake",
                url="https://www.youtube.com/watch?v=neutral001x",
                channel_name="Publisher",
                published_at=None,
                duration_seconds=1200,
            )

            with patch(
                "pastor_transcript_extractor.cli.extract_discovered_videos",
                return_value=[discovered],
            ):
                result = runner.invoke(
                    app,
                    ["discover", "--source-id", str(source.id), "--base-dir", tmp],
                )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("for publisher publisher", result.output)
            video = database.get_video_by_youtube_id("neutral001x")
            self.assertIsNotNone(video)
            self.assertIsNone(video.pastor_id)
            with database.connect() as connection:
                namespace = connection.execute(
                    """
                    SELECT scheme, relative_root
                    FROM video_artifact_namespaces WHERE video_id = ?
                    """,
                    (video.id,),
                ).fetchone()
                metadata = connection.execute(
                    "SELECT artifact_path FROM metadata_artifacts WHERE video_id = ?",
                    (video.id,),
                ).fetchone()
            self.assertEqual("video_v1", namespace["scheme"])
            self.assertEqual(
                "artifacts/videos/neutral001x", namespace["relative_root"]
            )
            self.assertTrue(
                str(metadata["artifact_path"]).startswith(
                    str(root.resolve() / "artifacts" / "videos" / "neutral001x")
                )
            )

    def test_targetless_video_extracts_in_neutral_namespace_without_identity_assessment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_paths(root)
            database = Database(paths.database)
            database.initialize()
            organization = database.add_organization(
                "publisher",
                "Publisher",
                "network",
            )
            source = database.add_source(
                "https://www.youtube.com/@publisher",
                SourceType.CHANNEL,
                pastor_id=None,
                organization_id=organization.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=None,
                youtube_video_id="neutralextract1",
                title="Sunday Message",
                url="https://www.youtube.com/watch?v=neutralextract1",
                status=VideoStatus.TRANSCRIBED_LOCAL,
            )
            video_root = root / "artifacts" / "videos" / video.youtube_video_id
            raw_root = video_root / "raw"
            raw_root.mkdir(parents=True)
            raw_json_path = raw_root / "captions.json"
            raw_text_path = raw_root / "captions.txt"
            raw_json_path.write_text(
                json.dumps(
                    {
                        "text": "Turn in your Bibles. The word of God shows us grace.",
                        "segments": [
                            {
                                "start": 0.0,
                                "end": 600.0,
                                "text": "Turn in your Bibles to Romans chapter five.",
                            },
                            {
                                "start": 600.0,
                                "end": 1200.0,
                                "text": "The word of God shows us grace in this passage.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            raw_text_path.write_text(
                "Turn in your Bibles.\nThe word of God shows us grace.",
                encoding="utf-8",
            )
            database.add_transcript_artifact(
                video_id=video.id,
                source_kind=TranscriptSourceKind.CAPTIONS,
                audio_path=None,
                raw_json_path=str(raw_json_path),
                raw_text_path=str(raw_text_path),
            )

            result = extract_video(database, paths, video.id)

            proposed = json.loads(
                result.proposed_json_path.read_text(encoding="utf-8")
            )
            refreshed = database.get_video_by_id(video.id)
            organization_review = export_organization_review_markdown(
                database,
                paths,
                organization.slug,
            )
            self.assertEqual(
                video_root.resolve() / "extracted" / "proposed.json",
                result.proposed_json_path,
            )
            self.assertIsNone(proposed["pastor_slug"])
            self.assertFalse(proposed["guest_speaker_suspected"])
            self.assertEqual(VideoStatus.EXTRACTED, refreshed.status)
            self.assertIsNone(
                database.get_latest_identity_assessment_for_video(video.id)
            )
            self.assertEqual(1, organization_review.video_count)

    def test_organization_b_video_can_attach_to_pastor_a_without_republishing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_paths(root)
            database = Database(paths.database)
            database.initialize()
            organization_b = database.add_organization(
                "organization-b",
                "Organization B",
                "conference",
            )
            pastor_a = database.add_pastor("pastor-a", "Pastor A")
            source = database.add_source(
                "https://www.youtube.com/@organizationb",
                SourceType.CHANNEL,
                pastor_id=pastor_a.id,
                organization_id=organization_b.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor_a.id,
                youtube_video_id="orgbvideo01",
                title="Guest Sermon",
                url="https://www.youtube.com/watch?v=orgbvideo01",
            )
            with database.connect() as connection:
                namespace = connection.execute(
                    """
                    SELECT relative_root FROM video_artifact_namespaces
                    WHERE video_id = ?
                    """,
                    (video.id,),
                ).fetchone()
            video_root = paths.root.joinpath(*Path(namespace["relative_root"]).parts)
            proposed_md = video_root / "extracted" / "proposed.md"
            proposed_json = video_root / "extracted" / "proposed.json"
            proposed_md.parent.mkdir(parents=True, exist_ok=True)
            proposed_md.write_text("# Guest Sermon\n\nSermon body.", encoding="utf-8")
            proposed_json.write_text(
                json.dumps(
                    {
                        "sermon_window": {
                            "start_seconds": 10.0,
                            "end_seconds": 100.0,
                        },
                        "segments": [
                            {
                                "start_seconds": 10.0,
                                "end_seconds": 100.0,
                                "text": "Sermon body.",
                            }
                        ],
                        "final_disposition": {"status": "accepted_sermon"},
                    }
                ),
                encoding="utf-8",
            )
            extraction = database.add_extraction_result(
                video_id=video.id,
                version=1,
                proposed_text_path=str(proposed_md),
                proposed_json_path=str(proposed_json),
            )
            profile = database.ensure_speaker_profile(
                stable_key="pastor-a-profile",
                display_label="Pastor A",
                lifecycle_state="curated",
                created_reason="manual_review",
            )
            database.ensure_pastor_speaker_binding(pastor_a.id, profile.id)
            observation = database.add_speaker_observation(
                video_id=video.id,
                extraction_result_id=extraction.id,
                role="principal_speaker",
                multiplicity_state="single",
                start_seconds=10.0,
                end_seconds=100.0,
                artifact_path=str(proposed_json),
                content_sha256="observation-content",
                extractor_version="test",
                input_fingerprint="organization-b-pastor-a-observation",
            )
            database.add_profile_observation_event(
                profile_id=profile.id,
                observation_id=observation.id,
                action="attach",
                reviewer="reviewer",
                reason="Verified guest speaker",
                event_fingerprint="organization-b-pastor-a-review",
            )

            organization_review = export_organization_review_markdown(
                database,
                paths,
                organization_b.slug,
            )
            pastor_review = export_pastor_review_markdown(
                database,
                paths,
                pastor_a.slug,
            )

            unchanged_source = database.get_source_by_id(source.id)
            self.assertEqual(organization_b.id, unchanged_source.organization_id)
            self.assertTrue(
                database.is_observation_attached(profile.id, observation.id)
            )
            self.assertEqual(1, organization_review.video_count)
            self.assertEqual(1, pastor_review.video_count)


if __name__ == "__main__":
    unittest.main()
