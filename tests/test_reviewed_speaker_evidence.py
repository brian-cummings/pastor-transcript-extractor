from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    load_reviewed_speaker_evidence,
    sync_reviewed_speaker_evidence,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    ensure_configured_pastor_profile,
    record_name_claim_review,
    record_observation_disposition,
)
from pastor_transcript_extractor.speaker_review_invalidation import (
    invalidate_reviews_for_videos,
)
from pastor_transcript_extractor.storage import Database


class ReviewedSpeakerEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = build_paths(self.root / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.source = self.database.add_source(
            "https://www.youtube.com/@reviewed",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        self.observations = {
            fingerprint: self._add_observation(index, fingerprint)
            for index, fingerprint in enumerate(("a", "b", "c", "d"), start=1)
        }
        self.evaluation_root = self.root / "speaker-pairs"
        (self.evaluation_root / "fixtures").mkdir(parents=True)
        (self.evaluation_root / "drafts").mkdir(parents=True)
        (self.evaluation_root / "reviews").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _add_observation(self, index: int, fingerprint: str):
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=None,
            youtube_video_id=f"video-{fingerprint}",
            title=f"Video {fingerprint}",
            url=f"https://www.youtube.com/watch?v=video-{fingerprint}",
            status=VideoStatus.EXTRACTED,
        )
        extraction = self.database.add_extraction_result(
            video_id=video.id,
            version=1,
            proposed_text_path=f"{fingerprint}.md",
            proposed_json_path=f"{fingerprint}.json",
        )
        return self.database.add_speaker_observation(
            video_id=video.id,
            extraction_result_id=extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="unknown",
            start_seconds=100.0,
            end_seconds=1000.0,
            artifact_path=f"{fingerprint}.speaker.json",
            content_sha256=f"content-{fingerprint}",
            extractor_version="speaker_evidence_v1",
            input_fingerprint=fingerprint,
        )

    def _write_fixture(
        self,
        pair_id: str,
        fingerprint_a: str,
        fingerprint_b: str,
        outcome: str,
    ) -> None:
        payload = {
            "schema_version": 1,
            "review_status": "approved",
            "pair_id": pair_id,
            "review_event_id": f"event-{pair_id}",
            "reviewer": "Reviewer One",
            "expected_outcome": outcome,
            "qualification": {
                "A": "qualified_single_speaker",
                "B": "qualified_single_speaker",
            },
            "observations": {
                "a": {"input_fingerprint": fingerprint_a},
                "b": {"input_fingerprint": fingerprint_b},
            },
        }
        (self.evaluation_root / "fixtures" / f"{pair_id}.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def _add_explicit_claim(
        self,
        fingerprint: str,
        normalized_name: str,
    ):
        observation = self.observations[fingerprint]
        return self.database.add_speaker_name_claim(
            video_id=observation.video_id,
            observation_id=observation.id,
            display_name=normalized_name.title(),
            normalized_name=normalized_name,
            claim_kind="explicit_speaker_attribution",
            channel="metadata",
            explicit_speaker_attribution=True,
            correlation_group_id=f"group-{fingerprint}-{normalized_name}",
            provenance_json="{}",
            artifact_path=f"{fingerprint}.speaker.json",
            claim_fingerprint=f"claim-{fingerprint}-{normalized_name}",
            extractor_version="speaker_evidence_v1",
        )

    def _write_review(
        self,
        *,
        pair_id: str,
        event_id: str,
        fingerprint_a: str,
        fingerprint_b: str,
        qualification_a: str,
        qualification_b: str,
    ) -> None:
        draft = {
            "schema_version": 1,
            "review_status": "draft",
            "pair_id": pair_id,
            "draft_id": f"draft-{pair_id}",
            "observations": {
                "source_a": {"input_fingerprint": fingerprint_a},
                "source_b": {"input_fingerprint": fingerprint_b},
            },
            "presentation": {
                "A": {"source_key": "source_a"},
                "B": {"source_key": "source_b"},
            },
        }
        (self.evaluation_root / "drafts" / f"{pair_id}.json").write_text(
            json.dumps(draft),
            encoding="utf-8",
        )
        review_dir = self.evaluation_root / "reviews" / pair_id
        review_dir.mkdir(parents=True, exist_ok=True)
        review = {
            "schema_version": 1,
            "event_kind": "speaker_pair_human_review",
            "pair_id": pair_id,
            "draft_id": draft["draft_id"],
            "review_event_id": event_id,
            "reviewer": "Reviewer Two",
            "qualification": {
                "A": qualification_a,
                "B": qualification_b,
            },
            "pair_judgment": "cannot_determine",
            "approval_confirmed": False,
            "fixture_eligible": False,
        }
        (review_dir / f"{event_id}.json").write_text(
            json.dumps(review),
            encoding="utf-8",
        )

    def test_sync_materializes_reviewed_components_and_constraints_idempotently(self) -> None:
        self._write_fixture("pair-ab", "a", "b", "same_speaker")
        self._write_fixture("pair-bc", "b", "c", "same_speaker")
        self._write_fixture("pair-cd", "c", "d", "different_speaker")

        evidence = load_reviewed_speaker_evidence(self.evaluation_root)
        first = sync_reviewed_speaker_evidence(self.database, evidence)
        replay = sync_reviewed_speaker_evidence(self.database, evidence)

        profile_ids = {
            fingerprint: self.database.list_effective_profile_ids_for_observation(
                observation.id
            )
            for fingerprint, observation in self.observations.items()
        }
        self.assertEqual(1, len(profile_ids["a"]))
        self.assertEqual(profile_ids["a"], profile_ids["b"])
        self.assertEqual(profile_ids["b"], profile_ids["c"])
        self.assertEqual([], profile_ids["d"])
        self.assertEqual(1, first.profiles_added)
        self.assertEqual(3, first.membership_events_added)
        self.assertEqual(
            [
                (
                    self.observations["c"].id,
                    self.observations["d"].id,
                )
            ],
            self.database.list_effective_observation_difference_pairs(),
        )
        self.assertEqual(0, replay.profiles_added)
        self.assertEqual(0, replay.membership_events_added)
        self.assertEqual(0, replay.difference_events_added)
        self.assertEqual(0, replay.qualification_events_added)
        self.assertEqual((), replay.conflicts)

    def test_provenance_invalidation_revokes_review_and_clears_registry_effects(self) -> None:
        pair_id = "pair-ab"
        draft = {
            "schema_version": 1,
            "review_status": "draft",
            "pair_id": pair_id,
            "draft_id": "draft-ab",
            "observations": {
                "source_a": {
                    "youtube_video_id": "video-a",
                    "input_fingerprint": "a",
                },
                "source_b": {
                    "youtube_video_id": "video-b",
                    "input_fingerprint": "b",
                },
            },
            "presentation": {
                "A": {"source_key": "source_a"},
                "B": {"source_key": "source_b"},
            },
        }
        (self.evaluation_root / "drafts" / f"{pair_id}.json").write_text(
            json.dumps(draft), encoding="utf-8"
        )
        self._write_fixture(pair_id, "a", "b", "different_speaker")
        sync_reviewed_speaker_evidence(
            self.database,
            load_reviewed_speaker_evidence(self.evaluation_root),
        )
        self.assertEqual(
            [(self.observations["a"].id, self.observations["b"].id)],
            self.database.list_effective_observation_difference_pairs(),
        )

        result = invalidate_reviews_for_videos(
            self.database,
            evaluation_root=self.evaluation_root,
            youtube_video_ids={"video-a"},
            reviewer="provenance-repair",
            reason="Wrong normalized audio was reviewed.",
        )

        self.assertEqual(("draft-ab",), result.revoked_draft_ids)
        self.assertEqual(("event-pair-ab",), result.revoked_review_event_ids)
        self.assertEqual(1, result.differences_cleared)
        self.assertEqual(
            "unresolved",
            self.database.get_effective_observation_review_action(
                self.observations["a"].id
            ),
        )
        self.assertEqual(
            [], self.database.list_effective_observation_difference_pairs()
        )
        active = load_reviewed_speaker_evidence(self.evaluation_root)
        self.assertEqual({}, active.pair_relations)
        self.assertNotIn("a", active.qualifications)
        replay = invalidate_reviews_for_videos(
            self.database,
            evaluation_root=self.evaluation_root,
            youtube_video_ids={"video-a"},
            reviewer="provenance-repair",
            reason="Wrong normalized audio was reviewed.",
        )
        self.assertEqual(0, replay.dispositions_reset)
        self.assertEqual((), replay.affected_observation_fingerprints)

    def test_provenance_invalidation_detaches_affected_profile_membership(self) -> None:
        pair_id = "pair-ab"
        draft = {
            "pair_id": pair_id,
            "draft_id": "draft-ab",
            "review_status": "draft",
            "observations": {
                "source_a": {
                    "youtube_video_id": "video-a",
                    "input_fingerprint": "a",
                },
                "source_b": {
                    "youtube_video_id": "video-b",
                    "input_fingerprint": "b",
                },
            },
        }
        (self.evaluation_root / "drafts" / f"{pair_id}.json").write_text(
            json.dumps(draft), encoding="utf-8"
        )
        self._write_fixture(pair_id, "a", "b", "same_speaker")
        sync_reviewed_speaker_evidence(
            self.database,
            load_reviewed_speaker_evidence(self.evaluation_root),
        )
        self.assertTrue(
            self.database.list_effective_profile_ids_for_observation(
                self.observations["a"].id
            )
        )

        result = invalidate_reviews_for_videos(
            self.database,
            evaluation_root=self.evaluation_root,
            youtube_video_ids={"video-a"},
            reviewer="provenance-repair",
            reason="Wrong normalized audio was reviewed.",
        )

        self.assertEqual(1, result.memberships_detached)
        self.assertEqual(
            [],
            self.database.list_effective_profile_ids_for_observation(
                self.observations["a"].id
            ),
        )

    def test_visual_identity_review_replays_without_acoustic_fixture(self) -> None:
        self._write_review(
            pair_id="pair-ab",
            event_id="event-ab",
            fingerprint_a="a",
            fingerprint_b="b",
            qualification_a="qualified_single_speaker",
            qualification_b="qualified_single_speaker",
        )
        path = (
            self.evaluation_root
            / "reviews"
            / "pair-ab"
            / "event-ab.json"
        )
        review = json.loads(path.read_text(encoding="utf-8"))
        review.update(
            {
                "pair_judgment": "same_speaker",
                "approval_confirmed": True,
                "review_evidence_mode": "audio_plus_visual",
                "identity_evidence_eligible": True,
                "fixture_eligible": False,
            }
        )
        path.write_text(json.dumps(review), encoding="utf-8")

        evidence = load_reviewed_speaker_evidence(self.evaluation_root)
        result = sync_reviewed_speaker_evidence(self.database, evidence)

        self.assertEqual(
            "same_speaker",
            evidence.pair_relations[frozenset(("a", "b"))].outcome,
        )
        self.assertEqual(1, result.profiles_added)
        self.assertEqual(2, result.membership_events_added)
        self.assertFalse(
            (self.evaluation_root / "fixtures" / "pair-ab.json").exists()
        )

    def test_sync_attaches_consistent_name_and_links_configured_identity(
        self,
    ) -> None:
        pastor = self.database.add_pastor("andrew-korp", "Andrew Korp")
        configured = ensure_configured_pastor_profile(self.database, pastor)
        claim_a = self._add_explicit_claim("a", "andrew korp")
        claim_b = self._add_explicit_claim("b", "andrew korp")
        self._write_fixture("pair-ab", "a", "b", "same_speaker")

        evidence = load_reviewed_speaker_evidence(self.evaluation_root)
        first = sync_reviewed_speaker_evidence(self.database, evidence)
        replay = sync_reviewed_speaker_evidence(self.database, evidence)

        profile_id = self.database.list_effective_profile_ids_for_observation(
            self.observations["a"].id
        )[0]
        self.assertEqual(
            [claim_a.id, claim_b.id],
            self.database.list_effective_name_claim_ids_for_profile(
                profile_id
            ),
        )
        self.assertEqual(
            profile_id,
            self.database.get_effective_profile_redirect(configured.id),
        )
        self.assertEqual(2, first.name_claim_events_added)
        self.assertEqual(1, first.profile_redirect_events_added)
        self.assertEqual(0, replay.name_claim_events_added)
        self.assertEqual(0, replay.profile_redirect_events_added)
        self.assertEqual((), replay.conflicts)

    def test_sync_blocks_name_spanning_multiple_reviewed_profiles(
        self,
    ) -> None:
        pastor = self.database.add_pastor("jordan-fowler", "Jordan Fowler")
        configured = ensure_configured_pastor_profile(self.database, pastor)
        claims = [
            self._add_explicit_claim(fingerprint, "jordan fowler")
            for fingerprint in ("a", "b", "c", "d")
        ]
        self._write_fixture("pair-ab", "a", "b", "same_speaker")
        self._write_fixture("pair-cd", "c", "d", "same_speaker")

        result = sync_reviewed_speaker_evidence(
            self.database,
            load_reviewed_speaker_evidence(self.evaluation_root),
        )

        self.assertEqual(0, result.name_claim_events_added)
        self.assertEqual(0, result.profile_redirect_events_added)
        self.assertIsNone(
            self.database.get_effective_profile_redirect(configured.id)
        )
        self.assertTrue(
            any(
                "spans reviewed profiles" in candidate
                for candidate in result.merge_candidates
            )
        )
        self.assertEqual((), result.conflicts)
        self.assertTrue(
            all(
                self.database.get_effective_name_claim_review(claim.id)
                is None
                for claim in claims
            )
        )

    def test_confirmed_bridge_merges_reviewed_profiles_and_reconciles_name(
        self,
    ) -> None:
        pastor = self.database.add_pastor("jordan-fowler", "Jordan Fowler")
        configured = ensure_configured_pastor_profile(self.database, pastor)
        claims = [
            self._add_explicit_claim(fingerprint, "jordan fowler")
            for fingerprint in ("a", "b", "c", "d")
        ]
        self._write_fixture("pair-ab", "a", "b", "same_speaker")
        self._write_fixture("pair-cd", "c", "d", "same_speaker")
        first_evidence = load_reviewed_speaker_evidence(
            self.evaluation_root
        )
        sync_reviewed_speaker_evidence(self.database, first_evidence)
        first_profile_id = (
            self.database.list_effective_profile_ids_for_observation(
                self.observations["a"].id
            )[0]
        )
        second_profile_id = (
            self.database.list_effective_profile_ids_for_observation(
                self.observations["c"].id
            )[0]
        )
        self.assertNotEqual(first_profile_id, second_profile_id)

        self._write_fixture("pair-bc", "b", "c", "same_speaker")
        result = sync_reviewed_speaker_evidence(
            self.database,
            load_reviewed_speaker_evidence(self.evaluation_root),
        )

        canonical_profile_id = min(first_profile_id, second_profile_id)
        retired_profile_id = max(first_profile_id, second_profile_id)
        for observation in self.observations.values():
            self.assertEqual(
                [canonical_profile_id],
                self.database.list_effective_profile_ids_for_observation(
                    observation.id
                ),
            )
        self.assertEqual(
            canonical_profile_id,
            self.database.get_effective_profile_redirect(retired_profile_id),
        )
        self.assertEqual(
            canonical_profile_id,
            self.database.get_effective_profile_redirect(configured.id),
        )
        self.assertEqual(
            sorted(claim.id for claim in claims),
            self.database.list_effective_name_claim_ids_for_profile(
                canonical_profile_id
            ),
        )
        self.assertEqual(4, result.name_claim_events_added)
        self.assertEqual(2, result.profile_redirect_events_added)
        self.assertEqual((), result.conflicts)

    def test_confirmed_bridge_merges_discovery_profile_into_linked_profile(
        self,
    ) -> None:
        pastor = self.database.add_pastor("andrew-korp", "Andrew Korp")
        configured = ensure_configured_pastor_profile(self.database, pastor)
        claims = [
            self._add_explicit_claim(fingerprint, "andrew korp")
            for fingerprint in ("a", "b", "c", "d")
        ]
        discovery = self.database.ensure_speaker_profile(
            stable_key="speaker:discovery:test-component",
            display_label=None,
            lifecycle_state="provisional",
            created_reason="shadow_discovery_candidate",
        )
        for fingerprint in ("c", "d"):
            attach_reviewed_observation(
                self.database,
                profile_id=discovery.id,
                observation_id=self.observations[fingerprint].id,
                reviewer="system:profile-discovery-promotion",
                reason="Test discovery seed membership",
                review_event_key=f"test-discovery:{fingerprint}",
            )

        self._write_fixture("pair-ab", "a", "b", "same_speaker")
        sync_reviewed_speaker_evidence(
            self.database,
            load_reviewed_speaker_evidence(self.evaluation_root),
        )
        linked_profile_id = self.database.resolve_speaker_profile_id(
            configured.id
        )
        self.assertNotEqual(discovery.id, linked_profile_id)
        self.assertGreater(linked_profile_id, discovery.id)

        self._write_fixture("pair-bc", "b", "c", "same_speaker")
        result = sync_reviewed_speaker_evidence(
            self.database,
            load_reviewed_speaker_evidence(self.evaluation_root),
        )

        self.assertEqual(
            linked_profile_id,
            self.database.get_effective_profile_redirect(discovery.id),
        )
        self.assertEqual(
            linked_profile_id,
            self.database.resolve_speaker_profile_id(configured.id),
        )
        for observation in self.observations.values():
            self.assertEqual(
                [linked_profile_id],
                self.database.list_effective_profile_ids_for_observation(
                    observation.id
                ),
            )
        self.assertEqual(
            sorted(claim.id for claim in claims),
            self.database.list_effective_name_claim_ids_for_profile(
                linked_profile_id
            ),
        )
        self.assertEqual(1, result.profile_redirect_events_added)
        self.assertEqual((), result.conflicts)

    def test_same_name_profiles_with_different_constraint_are_a_conflict(
        self,
    ) -> None:
        for fingerprint in ("a", "b", "c", "d"):
            self._add_explicit_claim(fingerprint, "jordan fowler")
        self._write_fixture("pair-ab", "a", "b", "same_speaker")
        self._write_fixture("pair-cd", "c", "d", "same_speaker")
        self._write_fixture("pair-bc", "b", "c", "different_speaker")

        result = sync_reviewed_speaker_evidence(
            self.database,
            load_reviewed_speaker_evidence(self.evaluation_root),
        )

        self.assertEqual((), result.merge_candidates)
        self.assertTrue(
            any(
                "effective different-speaker constraint" in conflict
                for conflict in result.conflicts
            )
        )

    def test_bridge_does_not_merge_multiple_configured_identities(self) -> None:
        configured_profiles = []
        for slug, display_name, fingerprints in (
            ("alice-example", "Alice Example", ("a", "b")),
            ("bob-example", "Bob Example", ("c", "d")),
        ):
            pastor = self.database.add_pastor(slug, display_name)
            configured_profiles.append(
                ensure_configured_pastor_profile(self.database, pastor)
            )
            for fingerprint in fingerprints:
                self._add_explicit_claim(
                    fingerprint,
                    display_name.lower(),
                )
            self._write_fixture(
                f"pair-{fingerprints[0]}{fingerprints[1]}",
                fingerprints[0],
                fingerprints[1],
                "same_speaker",
            )
        sync_reviewed_speaker_evidence(
            self.database,
            load_reviewed_speaker_evidence(self.evaluation_root),
        )
        linked_profile_ids = {
            self.database.resolve_speaker_profile_id(profile.id)
            for profile in configured_profiles
        }
        self.assertEqual(2, len(linked_profile_ids))

        self._write_fixture("pair-bc", "b", "c", "same_speaker")
        result = sync_reviewed_speaker_evidence(
            self.database,
            load_reviewed_speaker_evidence(self.evaluation_root),
        )

        self.assertTrue(
            any(
                "multiple configured pastor identities" in conflict
                for conflict in result.conflicts
            ),
            result.conflicts,
        )
        self.assertEqual(
            linked_profile_ids,
            {
                self.database.resolve_speaker_profile_id(profile.id)
                for profile in configured_profiles
            },
        )

    def test_manual_claim_review_blocks_automatic_reconciliation(self) -> None:
        pastor = self.database.add_pastor("andrew-korp", "Andrew Korp")
        configured = ensure_configured_pastor_profile(self.database, pastor)
        claim_a = self._add_explicit_claim("a", "andrew korp")
        self._add_explicit_claim("b", "andrew korp")
        record_name_claim_review(
            self.database,
            claim_id=claim_a.id,
            profile_id=None,
            attach=False,
            reviewer="Manual Reviewer",
            reason="Explicit attribution was not the principal speaker",
            review_event_key="manual-reject-claim-a",
        )
        self._write_fixture("pair-ab", "a", "b", "same_speaker")

        result = sync_reviewed_speaker_evidence(
            self.database,
            load_reviewed_speaker_evidence(self.evaluation_root),
        )

        self.assertEqual(0, result.name_claim_events_added)
        self.assertEqual(0, result.profile_redirect_events_added)
        self.assertIsNone(
            self.database.get_effective_profile_redirect(configured.id)
        )
        self.assertTrue(
            any(
                "conflicts with effective claim review" in conflict
                for conflict in result.conflicts
            )
        )

    def test_conflicting_qualifications_are_not_materialized(self) -> None:
        self._write_review(
            pair_id="pair-ab",
            event_id="event-single",
            fingerprint_a="a",
            fingerprint_b="b",
            qualification_a="qualified_single_speaker",
            qualification_b="qualified_single_speaker",
        )
        self._write_review(
            pair_id="pair-ac",
            event_id="event-multiple",
            fingerprint_a="a",
            fingerprint_b="c",
            qualification_a="multiple_speakers",
            qualification_b="qualified_single_speaker",
        )

        evidence = load_reviewed_speaker_evidence(self.evaluation_root)
        result = sync_reviewed_speaker_evidence(self.database, evidence)

        self.assertEqual(
            ("multiple_speakers", "qualified_single_speaker"),
            evidence.qualification_conflicts["a"],
        )
        self.assertIsNone(
            self.database.get_effective_observation_review_action(
                self.observations["a"].id
            )
        )
        self.assertTrue(
            any("qualification conflict for a" in value for value in result.conflicts)
        )

    def test_manual_qualification_override_blocks_component_materialization(self) -> None:
        self._write_fixture("pair-ab", "a", "b", "same_speaker")
        record_observation_disposition(
            self.database,
            observation_id=self.observations["a"].id,
            action="multiple_speakers",
            reviewer="Manual Reviewer",
            reason="Manual correction after pair review",
            review_event_key="manual-override-a",
        )

        evidence = load_reviewed_speaker_evidence(self.evaluation_root)
        result = sync_reviewed_speaker_evidence(self.database, evidence)

        self.assertEqual(
            "multiple_speakers",
            self.database.get_effective_observation_review_action(
                self.observations["a"].id
            ),
        )
        self.assertEqual([], self.database.list_speaker_profiles())
        self.assertTrue(
            any(
                "without effective single-speaker qualification" in value
                for value in result.conflicts
            )
        )

    def test_manual_adjudication_resolves_artifact_qualification_conflict(self) -> None:
        self._write_fixture("pair-ab", "a", "b", "same_speaker")
        self._write_review(
            pair_id="pair-ac",
            event_id="event-multiple",
            fingerprint_a="a",
            fingerprint_b="c",
            qualification_a="multiple_speakers",
            qualification_b="qualified_single_speaker",
        )
        record_observation_disposition(
            self.database,
            observation_id=self.observations["a"].id,
            action="qualified_single_speaker",
            reviewer="Adjudicator",
            reason="Resolved conflicting historical qualifications",
            review_event_key="adjudicate-a",
        )

        evidence = load_reviewed_speaker_evidence(self.evaluation_root)
        result = sync_reviewed_speaker_evidence(self.database, evidence)

        self.assertIn("a", evidence.qualification_conflicts)
        self.assertEqual(1, result.profiles_added)
        self.assertEqual(
            self.database.list_effective_profile_ids_for_observation(
                self.observations["a"].id
            ),
            self.database.list_effective_profile_ids_for_observation(
                self.observations["b"].id
            ),
        )
        self.assertFalse(
            any(
                "same component contains qualification conflict" in value
                for value in result.conflicts
            )
        )


if __name__ == "__main__":
    unittest.main()
