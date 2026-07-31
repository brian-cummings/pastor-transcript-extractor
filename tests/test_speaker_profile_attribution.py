from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_profile_attribution import (
    apply_reviewed_profile_attribution,
    list_unnamed_profile_attribution_candidates,
    write_profile_attribution_packet,
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
        paths = build_paths(self.root / "app")
        ensure_directories(paths)
        self.database = Database(paths.database)
        self.database.initialize()
        source = self.database.add_source(
            "https://www.youtube.com/@attribution",
            SourceType.CHANNEL,
            pastor_id=None,
        )
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


if __name__ == "__main__":
    unittest.main()
