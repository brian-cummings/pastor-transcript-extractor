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
    observation_profile_lineage_exclusion,
    select_superseded_profile_member_review,
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

    def _claim(self, observation, name: str, key: str) -> None:
        self.database.add_speaker_name_claim(
            video_id=observation.video_id,
            observation_id=observation.id,
            display_name=name,
            normalized_name=name.casefold(),
            claim_kind="explicit_speaker_attribution",
            channel="test",
            explicit_speaker_attribution=True,
            correlation_group_id=f"claim-group-{key}",
            provenance_json="{}",
            artifact_path=str(self.root / f"claim-{key}.json"),
            claim_fingerprint=f"claim-{key}",
            extractor_version="test",
        )

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
            "no_profile_has_two_current_reviewed_acoustic_exemplars",
            item.reason_code,
        )
        self.assertFalse(item.retryable)

    def test_selects_one_review_to_restore_second_current_exemplar(self):
        members = [self._observation(f"member-{index}") for index in range(3)]
        profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="test",
            review_event_key="profile-for-restoration",
        )
        for index, member in enumerate(members):
            attach_reviewed_observation(
                self.database,
                profile_id=profile.id,
                observation_id=member.id,
                reviewer="reviewer",
                reason="test",
                review_event_key=f"restoration-member-{index}",
            )
        replacements = []
        for index, member in enumerate(members[1:], start=1):
            replacements.append(
                self.database.add_speaker_observation(
                    video_id=member.video_id,
                    extraction_result_id=member.extraction_result_id,
                    role=member.role,
                    multiplicity_state=member.multiplicity_state,
                    start_seconds=member.start_seconds,
                    end_seconds=member.end_seconds,
                    artifact_path=member.artifact_path,
                    content_sha256=member.content_sha256,
                    extractor_version=member.extractor_version,
                    input_fingerprint=f"replacement-{index}",
                )
            )

        with patch(
            "pastor_transcript_extractor.identity_automation."
            "assess_automatic_speaker_observation",
            side_effect=self._eligible,
        ):
            candidate = select_superseded_profile_member_review(self.database)

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(profile.id, candidate.profile_id)
        self.assertEqual(members[0].id, candidate.anchor_observation_id)
        self.assertIn(
            candidate.replacement_observation_id,
            {replacement.id for replacement in replacements},
        )
        self.assertEqual(1, candidate.current_exemplar_count)

    def test_selects_named_lineage_bridge_when_replacements_are_profiled(self):
        old_members = [self._observation(f"old-{index}") for index in range(2)]
        old_profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="test",
            review_event_key="old-profile",
        )
        successor_profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="test",
            review_event_key="successor-profile",
        )
        replacements = []
        for index, old_member in enumerate(old_members):
            attach_reviewed_observation(
                self.database,
                profile_id=old_profile.id,
                observation_id=old_member.id,
                reviewer="reviewer",
                reason="test",
                review_event_key=f"old-member-{index}",
            )
            replacement = self.database.add_speaker_observation(
                video_id=old_member.video_id,
                extraction_result_id=old_member.extraction_result_id,
                role=old_member.role,
                multiplicity_state=old_member.multiplicity_state,
                start_seconds=old_member.start_seconds,
                end_seconds=old_member.end_seconds,
                artifact_path=old_member.artifact_path,
                content_sha256=old_member.content_sha256,
                extractor_version=old_member.extractor_version,
                input_fingerprint=f"replacement-profiled-{index}",
            )
            replacements.append(replacement)
            attach_reviewed_observation(
                self.database,
                profile_id=successor_profile.id,
                observation_id=replacement.id,
                reviewer="reviewer",
                reason="test",
                review_event_key=f"successor-member-{index}",
            )
        self._claim(old_members[0], "Ron Clouzet", "old")
        self._claim(replacements[0], "Ron Clouzet", "successor")

        with patch(
            "pastor_transcript_extractor.identity_automation."
            "assess_automatic_speaker_observation",
            side_effect=self._eligible,
        ):
            candidate = select_superseded_profile_member_review(
                self.database,
                profile_id=old_profile.id,
            )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual("lineage_profile_consolidation", candidate.selection_kind)
        self.assertEqual(old_profile.id, candidate.profile_id)
        self.assertEqual(successor_profile.id, candidate.successor_profile_id)
        self.assertIn(candidate.anchor_observation_id, {item.id for item in old_members})
        self.assertIn(
            candidate.replacement_observation_id,
            {item.id for item in replacements},
        )
        anchor = self.database.get_speaker_observation(
            candidate.anchor_observation_id
        )
        replacement = self.database.get_speaker_observation(
            candidate.replacement_observation_id
        )
        assert anchor is not None and replacement is not None
        self.assertNotEqual(anchor.video_id, replacement.video_id)
        self.assertEqual(("ron clouzet",), candidate.shared_normalized_names)

        reverse_candidate = select_superseded_profile_member_review(
            self.database,
            profile_id=successor_profile.id,
        )
        self.assertIsNotNone(reverse_candidate)
        assert reverse_candidate is not None
        self.assertEqual(
            "lineage_profile_consolidation",
            reverse_candidate.selection_kind,
        )
        self.assertEqual(successor_profile.id, reverse_candidate.profile_id)
        self.assertEqual(old_profile.id, reverse_candidate.successor_profile_id)
        self.assertEqual(2, reverse_candidate.lineage_overlap_count)
        reverse_anchor = self.database.get_speaker_observation(
            reverse_candidate.anchor_observation_id
        )
        assert reverse_anchor is not None
        self.assertIn(
            reverse_anchor.id,
            {item.id for item in replacements},
        )

    def test_discovery_excludes_current_observation_with_profile_lineage(self):
        old = self._observation("lineage-owned")
        profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="test",
            review_event_key="lineage-owner",
        )
        attach_reviewed_observation(
            self.database,
            profile_id=profile.id,
            observation_id=old.id,
            reviewer="reviewer",
            reason="test",
            review_event_key="lineage-owned-member",
        )
        replacement = self.database.add_speaker_observation(
            video_id=old.video_id,
            extraction_result_id=old.extraction_result_id,
            role=old.role,
            multiplicity_state=old.multiplicity_state,
            start_seconds=old.start_seconds,
            end_seconds=old.end_seconds,
            artifact_path=old.artifact_path,
            content_sha256=old.content_sha256,
            extractor_version=old.extractor_version,
            input_fingerprint="lineage-owned-replacement",
        )

        self.assertEqual(
            "superseded_profile_lineage",
            observation_profile_lineage_exclusion(
                self.database,
                video_id=replacement.video_id,
                observation_id=replacement.id,
            ),
        )

    def test_selects_targeted_bridge_for_two_fully_superseded_named_profiles(self):
        profiles = [
            create_anonymous_profile(
                self.database,
                reviewer="reviewer",
                reason="test",
                review_event_key=f"named-stale-profile-{index}",
            )
            for index in range(2)
        ]
        members_by_profile = []
        for profile_index, profile in enumerate(profiles):
            members = [
                self._observation(
                    f"named-stale-{profile_index}-{member_index}"
                )
                for member_index in range(2)
            ]
            members_by_profile.append(members)
            for member_index, member in enumerate(members):
                attach_reviewed_observation(
                    self.database,
                    profile_id=profile.id,
                    observation_id=member.id,
                    reviewer="reviewer",
                    reason="test",
                    review_event_key=(
                        f"named-stale-member-{profile_index}-{member_index}"
                    ),
                )
                self.database.add_speaker_observation(
                    video_id=member.video_id,
                    extraction_result_id=member.extraction_result_id,
                    role=member.role,
                    multiplicity_state=member.multiplicity_state,
                    start_seconds=member.start_seconds,
                    end_seconds=member.end_seconds,
                    artifact_path=member.artifact_path,
                    content_sha256=member.content_sha256,
                    extractor_version=member.extractor_version,
                    input_fingerprint=(
                        f"unprofiled-current-{profile_index}-{member_index}"
                    ),
                )
            self._claim(
                members[0], "Danail Tchakarov", f"named-{profile_index}"
            )

        self.assertIsNone(
            select_superseded_profile_member_review(self.database)
        )
        candidate = select_superseded_profile_member_review(
            self.database,
            profile_id=profiles[0].id,
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(
            "superseded_named_profile_consolidation",
            candidate.selection_kind,
        )
        self.assertEqual(profiles[1].id, candidate.successor_profile_id)
        self.assertIn(
            candidate.anchor_observation_id,
            {item.id for item in members_by_profile[0]},
        )
        self.assertIn(
            candidate.replacement_observation_id,
            {item.id for item in members_by_profile[1]},
        )
        self.assertIsNone(
            select_superseded_profile_member_review(
                self.database,
                profile_id=profiles[0].id,
                excluded_pairs=tuple(
                    frozenset(
                        (left.input_fingerprint, right.input_fingerprint)
                    )
                    for left in members_by_profile[0]
                    for right in members_by_profile[1]
                ),
            )
        )

    def test_targeted_named_bridge_does_not_replace_current_profile_review(self):
        profiles = [
            create_anonymous_profile(
                self.database,
                reviewer="reviewer",
                reason="test",
                review_event_key=f"current-named-profile-{index}",
            )
            for index in range(2)
        ]
        for profile_index, profile in enumerate(profiles):
            for member_index in range(2):
                member = self._observation(
                    f"current-named-{profile_index}-{member_index}"
                )
                attach_reviewed_observation(
                    self.database,
                    profile_id=profile.id,
                    observation_id=member.id,
                    reviewer="reviewer",
                    reason="test",
                    review_event_key=(
                        f"current-named-member-{profile_index}-{member_index}"
                    ),
                )
                if member_index == 0:
                    self._claim(
                        member,
                        "Current Example",
                        f"current-name-{profile_index}",
                    )

        candidate = select_superseded_profile_member_review(
            self.database,
            profile_id=profiles[0].id,
        )

        self.assertIsNone(candidate)

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
