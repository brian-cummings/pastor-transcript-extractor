from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_profile_attribution import (
    apply_reviewed_profile_attribution,
    load_profile_attribution_clip_timestamps,
    load_profile_attribution_deferrals,
    list_proposed_profile_attribution_candidates,
    list_unnamed_profile_attribution_candidates,
    record_profile_attribution_deferral,
    write_profile_attribution_packet,
)
from pastor_transcript_extractor.speaker_profile_metadata_attribution import (
    ProfileMetadataAttribution,
    ProfileMetadataEvidence,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    ensure_configured_pastor_profile,
)
from pastor_transcript_extractor.storage import Database


class SpeakerProfileAttributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = build_paths(self.root / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        source = self.database.add_source(
            "https://www.youtube.com/@attribution",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        self.source = source
        self.observations = []
        for index in range(1, 4):
            video = self.database.add_video(
                source_id=source.id,
                pastor_id=None,
                youtube_video_id=f"video-{index}",
                title=f"Sermon {index}",
                url=f"https://www.youtube.com/watch?v=video-{index}",
                status=VideoStatus.EXTRACTED,
            )
            extraction = self.database.add_extraction_result(
                video_id=video.id,
                version=1,
                proposed_text_path=f"{index}.md",
                proposed_json_path=f"{index}.json",
            )
            self.observations.append(
                self.database.add_speaker_observation(
                    video_id=video.id,
                    extraction_result_id=extraction.id,
                    role="principal_speaker_candidate",
                    multiplicity_state="unknown",
                    start_seconds=100.0 + index,
                    end_seconds=1000.0,
                    artifact_path=f"{index}.speaker.json",
                    content_sha256=f"content-{index}",
                    extractor_version="speaker_evidence_v1",
                    input_fingerprint=f"fingerprint-{index}",
                )
            )
        self.profile = self.database.ensure_speaker_profile(
            stable_key="speaker:discovery:test-attribution",
            display_label=None,
            lifecycle_state="provisional",
            created_reason="shadow_discovery_candidate",
        )
        for observation in self.observations:
            attach_reviewed_observation(
                self.database,
                profile_id=self.profile.id,
                observation_id=observation.id,
                reviewer="system:profile-discovery-promotion",
                reason="Test seed",
                review_event_key=f"seed:{observation.id}",
            )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_review_packet_presents_backing_videos(self) -> None:
        candidate = list_unnamed_profile_attribution_candidates(
            self.database
        )[0]

        path = write_profile_attribution_packet(
            candidate,
            self.root / "profile.html",
        )
        packet = path.read_text(encoding="utf-8")

        self.assertEqual(self.profile.id, candidate.profile_id)
        self.assertEqual(3, candidate.member_count)
        self.assertIn("Sermon 1", packet)
        self.assertIn("i.ytimg.com/vi/video-1/hqdefault.jpg", packet)
        self.assertIn("watch?v=video-1&amp;t=101s", packet)
        self.assertNotIn("<iframe", packet)

    def test_persisted_identity_clip_controls_review_timestamp(self) -> None:
        cache_root = self.root / "cache"
        cache_directory = cache_root / "observation-span-selections"
        cache_directory.mkdir(parents=True)
        result = {
            "outcome": "prepared",
            "span_specs": [
                {"start_seconds": 210.5, "end_seconds": 225.5},
                {"start_seconds": 610.25, "end_seconds": 625.25},
                {"start_seconds": 410.75, "end_seconds": 425.75},
            ],
            "selection": {"strategy": "test"},
        }
        encoded = json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        payload = {
            "schema_version": 1,
            "cache_key": "test",
            "input": {
                "observation_fingerprint": self.observations[0].input_fingerprint,
            },
            "result_sha256": hashlib.sha256(encoded).hexdigest(),
            "result": result,
        }
        (cache_directory / "test.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

        timestamps = load_profile_attribution_clip_timestamps(cache_root)
        candidates = list_unnamed_profile_attribution_candidates(
            self.database,
            clip_timestamps=timestamps,
        )

        self.assertEqual(
            {self.observations[0].input_fingerprint: 410},
            timestamps,
        )
        self.assertEqual(1, len(candidates[0].evidence))
        self.assertEqual(410, candidates[0].evidence[0].timestamp_seconds)
        self.assertEqual(
            "persisted_identity_clip_selection",
            candidates[0].evidence[0].timestamp_source,
        )

    def test_missing_identity_clip_excludes_unaligned_evidence(self) -> None:
        self.assertEqual(
            (),
            list_unnamed_profile_attribution_candidates(
                self.database,
                clip_timestamps={},
            ),
        )

    def test_metadata_proposal_flows_into_attribution_packet(self) -> None:
        initial = list_unnamed_profile_attribution_candidates(self.database)[0]
        proposal = ProfileMetadataAttribution(
            profile_id=self.profile.id,
            membership_fingerprint=initial.membership_fingerprint,
            input_fingerprint="metadata-input",
            decision="propose_name",
            routing="human_confirmation_available",
            proposed_name="Curt DeWitt",
            normalized_name="curt dewitt",
            reason_codes=("repeated_name_across_recordings",),
            evidence=(
                ProfileMetadataEvidence(
                    "video-1",
                    "video.title",
                    "Curt DeWitt",
                ),
            ),
            conflicting_names=(),
            supporting_recording_count=2,
            artifact_path=self.root / "metadata.json",
            cache_hit=True,
        )

        candidate = list_unnamed_profile_attribution_candidates(
            self.database,
            metadata_attributions={initial.membership_fingerprint: proposal},
        )[0]
        packet_path = write_profile_attribution_packet(
            candidate,
            self.root / "metadata-profile.html",
        )

        self.assertEqual(proposal, candidate.metadata_attribution)
        self.assertEqual(
            (candidate,),
            list_proposed_profile_attribution_candidates(
                self.database,
                metadata_attributions={
                    initial.membership_fingerprint: proposal
                },
            ),
        )
        self.assertIn(
            "Metadata proposal:</strong> Curt DeWitt",
            packet_path.read_text(encoding="utf-8"),
        )

    def test_all_proposals_cli_reviews_and_applies_every_proposal(self) -> None:
        initial = list_unnamed_profile_attribution_candidates(self.database)[0]
        proposal = ProfileMetadataAttribution(
            profile_id=self.profile.id,
            membership_fingerprint=initial.membership_fingerprint,
            input_fingerprint="metadata-input",
            decision="propose_name",
            routing="human_confirmation_available",
            proposed_name="Curt DeWitt",
            normalized_name="curt dewitt",
            reason_codes=("repeated_name_across_recordings",),
            evidence=(
                ProfileMetadataEvidence(
                    "video-1",
                    "video.title",
                    "Curt DeWitt",
                ),
            ),
            conflicting_names=(),
            supporting_recording_count=2,
            artifact_path=self.root / "metadata.json",
            cache_hit=True,
        )
        timestamps = {
            observation.input_fingerprint: int(observation.start_seconds)
            for observation in self.observations
        }

        with (
            patch(
                "pastor_transcript_extractor.cli."
                "load_profile_metadata_attributions",
                return_value={initial.membership_fingerprint: proposal},
            ),
            patch(
                "pastor_transcript_extractor.cli."
                "load_profile_attribution_clip_timestamps",
                return_value=timestamps,
            ),
        ):
            result = CliRunner().invoke(
                app,
                [
                    "identity",
                    "review-profile-attribution",
                    "--all-proposals",
                    "--reviewer",
                    "Brian Cummings",
                    "--no-open-packet",
                    "--base-dir",
                    str(self.paths.root),
                ],
                input="\n\n\n\n",
            )

        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn(
            "Metadata proposal review complete: approved=1 deferred=0 "
            "cancelled=0.",
            result.output,
        )
        self.assertEqual(
            (),
            list_unnamed_profile_attribution_candidates(self.database),
        )

    def test_reviewed_name_claim_links_unique_configured_pastor(self) -> None:
        pastor = self.database.add_pastor("andrew-korp", "Andrew Korp")
        configured = ensure_configured_pastor_profile(self.database, pastor)
        packet = self.root / "profile.html"
        packet.write_text("packet", encoding="utf-8")

        result = apply_reviewed_profile_attribution(
            self.database,
            profile_id=self.profile.id,
            observation_id=self.observations[0].id,
            display_name="Andrew Korp",
            reviewer="Brian Cummings",
            reason="Visually identified in the backing sermon video",
            packet_path=packet,
        )

        self.assertEqual("andrew korp", result.normalized_name)
        self.assertEqual("linked", result.link_status)
        self.assertEqual("andrew-korp", result.linked_pastor_slug)
        self.assertEqual(
            self.profile.id,
            self.database.resolve_speaker_profile_id(configured.id),
        )
        self.assertEqual(
            [result.claim_id],
            self.database.list_effective_name_claim_ids_for_profile(
                self.profile.id
            ),
        )
        self.assertEqual(
            (),
            list_unnamed_profile_attribution_candidates(self.database),
        )

    def test_deferral_applies_only_to_exact_profile_membership(self) -> None:
        candidate = list_unnamed_profile_attribution_candidates(
            self.database
        )[0]
        root = self.root / "deferrals"

        event = record_profile_attribution_deferral(
            candidate,
            reviewer="Brian Cummings",
            root=root,
        )

        self.assertTrue(event.is_file())
        self.assertEqual(
            frozenset((candidate.membership_fingerprint,)),
            load_profile_attribution_deferrals(root),
        )
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=None,
            youtube_video_id="video-new-evidence",
            title="New evidence",
            url="https://www.youtube.com/watch?v=video-new-evidence",
            status=VideoStatus.EXTRACTED,
        )
        extraction = self.database.add_extraction_result(
            video_id=video.id,
            version=1,
            proposed_text_path="new.md",
            proposed_json_path="new.json",
        )
        observation = self.database.add_speaker_observation(
            video_id=video.id,
            extraction_result_id=extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="unknown",
            start_seconds=100.0,
            end_seconds=1000.0,
            artifact_path="new.speaker.json",
            content_sha256="new-content",
            extractor_version="speaker_evidence_v1",
            input_fingerprint="new-fingerprint",
        )
        attach_reviewed_observation(
            self.database,
            profile_id=self.profile.id,
            observation_id=observation.id,
            reviewer="Brian Cummings",
            reason="New reviewed evidence",
            review_event_key="new-reviewed-evidence",
        )

        changed = list_unnamed_profile_attribution_candidates(
            self.database
        )[0]
        self.assertNotEqual(
            candidate.membership_fingerprint,
            changed.membership_fingerprint,
        )


if __name__ == "__main__":
    unittest.main()
