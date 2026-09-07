from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.identity_automation import (
    build_identity_association_work_plan,
    classify_association_blocker,
    latest_association_reports,
)
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
)
from pastor_transcript_extractor.storage import Database


class IdentityAutomationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = build_paths(self.root / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.source = self.database.add_source(
            "https://www.youtube.com/@identity-automation",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        self.association_root = self.root / "associations"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _observation(self, key: str):
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=None,
            youtube_video_id=f"video-{key}",
            title=key,
            url=f"https://www.youtube.com/watch?v=video-{key}",
            status=VideoStatus.EXTRACTED,
        )
        extraction = self.database.add_extraction_result(
            video_id=video.id,
            version=1,
            proposed_text_path=str(self.root / f"{key}.md"),
            proposed_json_path=str(self.root / f"{key}.json"),
        )
        return self.database.add_speaker_observation(
            video_id=video.id,
            extraction_result_id=extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="unknown",
            start_seconds=10.0,
            end_seconds=100.0,
            artifact_path=str(self.root / f"{key}.speaker.json"),
            content_sha256=f"content-{key}",
            extractor_version="speaker_evidence_v2",
            input_fingerprint=f"fingerprint-{key}",
        )

    @staticmethod
    def _eligible(database, video_id, **_kwargs):
        observation = database.get_latest_speaker_observation_for_video(video_id)
        return SimpleNamespace(
            eligible=True,
            reason_code="eligible",
            observation=observation,
        )

    def _write_attempt(self, observation, suffix: str = "current") -> None:
        directory = self.association_root / observation.input_fingerprint[:16]
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "artifact_kind": "speaker_profile_shadow_association",
            "candidate": {
                "video_id": observation.video_id,
                "observation_id": observation.id,
                "input_fingerprint": observation.input_fingerprint,
            },
            "outcome": "insufficient_evidence",
            "created_at": suffix,
            "result_sha256": suffix,
        }
        (directory / f"{suffix}.json").write_text(json.dumps(payload))

    def test_selects_only_current_unprofiled_observations_without_current_result(self):
        ready = self._observation("ready")
        attempted = self._observation("attempted")
        profiled = self._observation("profiled")
        stale = self._observation("stale-old")
        replacement = self.database.add_speaker_observation(
            video_id=stale.video_id,
            extraction_result_id=stale.extraction_result_id,
            role=stale.role,
            multiplicity_state=stale.multiplicity_state,
            start_seconds=stale.start_seconds,
            end_seconds=stale.end_seconds,
            artifact_path=stale.artifact_path,
            content_sha256=stale.content_sha256,
            extractor_version=stale.extractor_version,
            input_fingerprint="fingerprint-stale-current",
        )
        self._write_attempt(attempted)
        self._write_attempt(stale, "old-observation-attempt")
        profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="test",
            review_event_key="profile",
        )
        attach_reviewed_observation(
            self.database,
            profile_id=profile.id,
            observation_id=profiled.id,
            reviewer="reviewer",
            reason="test",
            review_event_key="membership",
        )
        for index in range(2):
            member = self._observation(f"profiled-{index}")
            attach_reviewed_observation(
                self.database,
                profile_id=profile.id,
                observation_id=member.id,
                reviewer="reviewer",
                reason="test",
                review_event_key=f"membership-{index}",
            )

        with patch(
            "pastor_transcript_extractor.identity_automation."
            "assess_automatic_speaker_observation",
            side_effect=self._eligible,
        ):
            plan = build_identity_association_work_plan(
                self.database, self.association_root
            )

        states = {item.observation_id: item.state for item in plan.items}
        self.assertEqual("dispatch_ready", states[ready.id])
        self.assertEqual("associated", states[attempted.id])
        self.assertNotIn(profiled.id, states)
        self.assertNotIn(stale.id, states)
        self.assertEqual("dispatch_ready", states[replacement.id])

    def test_dispatch_is_blocked_when_no_profile_has_independent_seed(self):
        candidate = self._observation("candidate-without-profile-seed")

        with patch(
            "pastor_transcript_extractor.identity_automation."
            "assess_automatic_speaker_observation",
            side_effect=self._eligible,
        ):
            plan = build_identity_association_work_plan(
                self.database, self.association_root
            )

        item = next(
            item for item in plan.items if item.observation_id == candidate.id
        )
        self.assertEqual("profile_prerequisite_blocked", item.state)
        self.assertEqual("candidate_profile_eligibility", item.stage)
        self.assertEqual(
            "no_profile_has_three_independent_reviewed_recordings",
            item.reason_code,
        )
        self.assertFalse(item.retryable)

    def test_blocker_policy_separates_repairable_technical_from_terminal_policy(self):
        self.assertEqual(
            ("prerequisite_blocked", "backfill_existing_normalized_media", True),
            classify_association_blocker(
                "metadata_eligibility", "registered_normalized_media_unavailable"
            ),
        )
        state, operation, retryable = classify_association_blocker(
            "metadata_eligibility", "disposition_not_accepted"
        )
        self.assertEqual("admission_policy_terminal", state)
        self.assertEqual("review_policy_terminal", operation)
        self.assertFalse(retryable)

    def test_latest_report_filter_does_not_resurrect_superseded_proposal(self):
        directory = self.association_root / "candidate"
        directory.mkdir(parents=True)
        for created_at, outcome in (
            ("2026-01-01T00:00:00+00:00", "proposed_match"),
            ("2026-01-02T00:00:00+00:00", "insufficient_evidence"),
        ):
            payload = {
                "artifact_kind": "speaker_profile_shadow_association",
                "candidate": {"input_fingerprint": "candidate"},
                "created_at": created_at,
                "outcome": outcome,
            }
            (directory / f"{outcome}.json").write_text(json.dumps(payload))

        self.assertEqual(
            (),
            latest_association_reports(
                self.association_root, outcomes=("proposed_match",)
            ),
        )


if __name__ == "__main__":
    unittest.main()
