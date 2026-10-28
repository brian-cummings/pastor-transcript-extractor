from __future__ import annotations

import tempfile
import unittest
import shlex
from dataclasses import replace
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedSpeakerEvidence,
    ObservationQualification,
    PairRelation,
    ReviewProvenance,
)
from pastor_transcript_extractor.source_profile_consolidation import (
    apply_source_profile_consolidation,
    build_source_profile_consolidation_plan,
    list_source_profile_cohorts,
    source_profile_candidates,
    source_profile_review_suggestions,
    source_profile_consolidation_payload,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
    ensure_configured_pastor_profile,
)
from pastor_transcript_extractor.storage import Database


class SourceProfileConsolidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = build_paths(self.root / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.source = self.database.add_source(
            "https://www.youtube.com/@source-cohort",
            SourceType.CHANNEL,
            pastor_id=None,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _evidence(self) -> ReviewedSpeakerEvidence:
        return ReviewedSpeakerEvidence(
            qualifications={},
            qualification_conflicts={},
            pair_relations={},
            pair_conflicts={},
            review_event_count=0,
        )

    def _observation(self, key: str):
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=None,
            youtube_video_id=f"video-{key}",
            title=f"Video {key}",
            url=f"https://www.youtube.com/watch?v=video-{key}",
            status=VideoStatus.EXTRACTED,
        )
        extraction = self.database.add_extraction_result(
            video_id=video.id,
            version=1,
            proposed_text_path=f"{key}.md",
            proposed_json_path=f"{key}.json",
        )
        return self.database.add_speaker_observation(
            video_id=video.id,
            extraction_result_id=extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="unknown",
            start_seconds=100.0,
            end_seconds=1000.0,
            artifact_path=f"{key}.speaker.json",
            content_sha256=f"content-{key}",
            extractor_version="speaker_evidence_v1",
            input_fingerprint=key,
        )

    def _profile(self, key: str):
        profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="reviewed pair",
            review_event_key=f"profile-{key}",
        )
        observations = tuple(
            self._observation(f"{key}-{index}") for index in range(2)
        )
        for observation in observations:
            attach_reviewed_observation(
                self.database,
                profile_id=profile.id,
                observation_id=observation.id,
                reviewer="reviewer",
                reason="reviewed pair",
                review_event_key=f"attach-{key}-{observation.id}",
            )
        return profile, observations

    def test_complete_link_profile_cohort_needs_one_proposal(self) -> None:
        profiles = [self._profile(key) for key in ("a", "b", "c")]
        candidates, excluded = source_profile_candidates(
            self.database,
            self._evidence(),
            source_id=self.source.id,
            exemplars_per_profile=2,
        )
        self.assertEqual((), excluded)
        comparisons = {
            tuple(sorted((left.id, right.id))): {
                "outcome": "same_speaker",
                "metrics": {"cross_p10": 0.80 + (left.id + right.id) / 1000},
            }
            for index, (_, left_observations) in enumerate(profiles)
            for _, right_observations in profiles[index + 1 :]
            for left in left_observations
            for right in right_observations
        }

        plan = build_source_profile_consolidation_plan(
            self.database,
            source_id=self.source.id,
            candidates=candidates,
            comparisons=comparisons,
        )

        self.assertEqual(1, len(plan.proposals))
        self.assertEqual(
            tuple(profile.id for profile, _ in profiles),
            plan.proposals[0].profile_ids,
        )
        self.assertEqual(12, plan.proposals[0].comparison_count)
        self.assertTrue(all(item.eligible for item in plan.pair_evidence))

    def test_source_inventory_lists_only_sources_meeting_minimum(self) -> None:
        profiles = [self._profile(key) for key in ("a", "b", "c")]
        other_source = self.database.add_source(
            "https://www.youtube.com/@single-profile",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        other_profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="reviewed pair",
            review_event_key="other-profile",
        )
        for index in range(2):
            video = self.database.add_video(
                source_id=other_source.id,
                pastor_id=None,
                youtube_video_id=f"other-{index}",
                title=f"Other {index}",
                url=f"https://www.youtube.com/watch?v=other-{index}",
                status=VideoStatus.EXTRACTED,
            )
            extraction = self.database.add_extraction_result(
                video_id=video.id,
                version=1,
                proposed_text_path=f"other-{index}.md",
                proposed_json_path=f"other-{index}.json",
            )
            observation = self.database.add_speaker_observation(
                video_id=video.id,
                extraction_result_id=extraction.id,
                role="principal_speaker_candidate",
                multiplicity_state="unknown",
                start_seconds=100.0,
                end_seconds=1000.0,
                artifact_path=f"other-{index}.speaker.json",
                content_sha256=f"content-other-{index}",
                extractor_version="speaker_evidence_v1",
                input_fingerprint=f"other-{index}",
            )
            attach_reviewed_observation(
                self.database,
                profile_id=other_profile.id,
                observation_id=observation.id,
                reviewer="reviewer",
                reason="reviewed pair",
                review_event_key=f"attach-other-{index}",
            )

        summaries = list_source_profile_cohorts(
            self.database,
            self._evidence(),
            exemplars_per_profile=2,
            minimum_profiles=2,
        )

        self.assertEqual(1, len(summaries))
        self.assertEqual(self.source.id, summaries[0].source_id)
        self.assertEqual(3, summaries[0].profile_count)
        self.assertEqual(6, summaries[0].member_count)
        self.assertEqual(6, summaries[0].exemplar_count)
        self.assertEqual(12, summaries[0].comparison_upper_bound)
        self.assertEqual(
            {profile.id for profile, _ in profiles},
            {
                candidate.profile_id
                for candidate in source_profile_candidates(
                    self.database,
                    self._evidence(),
                    source_id=self.source.id,
                    exemplars_per_profile=2,
                )[0]
            },
        )

    def test_ambiguous_edge_fails_closed_without_blocking_safe_pair(self) -> None:
        profiles = [self._profile(key) for key in ("a", "b", "c")]
        candidates, _ = source_profile_candidates(
            self.database,
            self._evidence(),
            source_id=self.source.id,
            exemplars_per_profile=2,
        )
        comparisons = {
            tuple(sorted((left.id, right.id))): {"outcome": "same_speaker"}
            for index, (_, left_observations) in enumerate(profiles)
            for _, right_observations in profiles[index + 1 :]
            for left in left_observations
            for right in right_observations
        }
        ambiguous_pair = tuple(
            sorted((profiles[0][1][0].id, profiles[2][1][0].id))
        )
        comparisons[ambiguous_pair] = {"outcome": "insufficient_evidence"}

        plan = build_source_profile_consolidation_plan(
            self.database,
            source_id=self.source.id,
            candidates=candidates,
            comparisons=comparisons,
        )

        self.assertEqual(
            (profiles[0][0].id, profiles[1][0].id),
            plan.proposals[0].profile_ids,
        )
        blocked = next(
            item
            for item in plan.pair_evidence
            if item.profile_ids == (profiles[0][0].id, profiles[2][0].id)
        )
        self.assertFalse(blocked.eligible)
        self.assertIn("incomplete_or_ambiguous_complete_link", blocked.blockers)

    def test_approved_cohort_merges_all_members_append_only(self) -> None:
        profiles = [self._profile(key) for key in ("a", "b", "c")]
        candidates, _ = source_profile_candidates(
            self.database,
            self._evidence(),
            source_id=self.source.id,
            exemplars_per_profile=2,
        )
        comparisons = {
            tuple(sorted((left.id, right.id))): {"outcome": "same_speaker"}
            for index, (_, left_observations) in enumerate(profiles)
            for _, right_observations in profiles[index + 1 :]
            for left in left_observations
            for right in right_observations
        }
        plan = build_source_profile_consolidation_plan(
            self.database,
            source_id=self.source.id,
            candidates=candidates,
            comparisons=comparisons,
        )

        canonical_id = apply_source_profile_consolidation(
            self.database,
            plan=plan,
            proposal=plan.proposals[0],
            reviewer="brian",
            artifact_sha256="a" * 64,
        )

        self.assertEqual(profiles[0][0].id, canonical_id)
        self.assertEqual(
            {canonical_id},
            {
                self.database.resolve_speaker_profile_id(profile.id)
                for profile, _ in profiles
            },
        )
        self.assertEqual(
            6,
            len(
                self.database.list_effective_observation_ids_for_profile(
                    canonical_id
                )
            ),
        )

    def test_apply_revalidates_attribution_conflicts(self) -> None:
        profiles = [self._profile(key) for key in ("a", "b")]
        candidates, _ = source_profile_candidates(
            self.database,
            self._evidence(),
            source_id=self.source.id,
            exemplars_per_profile=2,
        )
        comparisons = {
            tuple(sorted((left.id, right.id))): {"outcome": "same_speaker"}
            for left in profiles[0][1]
            for right in profiles[1][1]
        }
        plan = build_source_profile_consolidation_plan(
            self.database,
            source_id=self.source.id,
            candidates=candidates,
            comparisons=comparisons,
        )
        for index, (_, observations) in enumerate(profiles):
            observation = observations[0]
            claim = self.database.add_speaker_name_claim(
                video_id=observation.video_id,
                observation_id=observation.id,
                display_name=("Alex Example", "Jordan Example")[index],
                normalized_name=("alex example", "jordan example")[index],
                claim_kind="explicit_speaker_attribution",
                channel="metadata",
                explicit_speaker_attribution=True,
                correlation_group_id=f"group-{index}",
                provenance_json="{}",
                artifact_path=observation.artifact_path,
                claim_fingerprint=f"claim-{index}",
                extractor_version="speaker_evidence_v1",
            )
            self.database.add_profile_name_claim_event(
                profile_id=profiles[index][0].id, claim_id=claim.id, action="attach",
                reviewer="name-reviewer", reason="Confirmed identity", event_fingerprint=f"name:{index}",
            )
        conflicts: list[str] = []

        canonical_id = apply_source_profile_consolidation(
            self.database,
            plan=plan,
            proposal=plan.proposals[0],
            reviewer="brian",
            artifact_sha256="b" * 64,
            conflicts=conflicts,
        )

        self.assertIsNone(canonical_id)
        self.assertIn("--allow-confirmed-names", conflicts[0])
        self.assertEqual(
            {profile.id for profile, _ in profiles},
            {
                self.database.resolve_speaker_profile_id(profile.id)
                for profile, _ in profiles
            },
        )

    def _confirm_name(self, profile, observation, name):
        claim = self.database.add_speaker_name_claim(
            video_id=observation.video_id, observation_id=observation.id,
            display_name=name, normalized_name=name.lower(),
            claim_kind="explicit_speaker_attribution", channel="metadata",
            explicit_speaker_attribution=True, correlation_group_id=f"name-{profile.id}",
            provenance_json="{}", artifact_path=observation.artifact_path,
            claim_fingerprint=f"name-{profile.id}", extractor_version="speaker_evidence_v1",
        )
        self.database.add_profile_name_claim_event(
            profile_id=profile.id, claim_id=claim.id, action="attach",
            reviewer="brian", reason="Confirmed name",
            event_fingerprint=f"confirmed-name-{profile.id}",
        )
        return claim

    def _two_profile_plan(self, profiles, *, comparisons=None, evidence=None):
        candidates, excluded = source_profile_candidates(
            self.database, self._evidence(), source_id=self.source.id,
            exemplars_per_profile=2,
        )
        self.assertFalse(excluded)
        if comparisons is None:
            comparisons = {
                tuple(sorted((a.id, b.id))): {"outcome": "same_speaker"}
                for a in profiles[0][1] for b in profiles[1][1]
            }
        return build_source_profile_consolidation_plan(
            self.database, source_id=self.source.id, candidates=candidates,
            comparisons=comparisons, reviewed_evidence=evidence,
        ), comparisons

    def test_confirmed_variations_remain_candidates_and_merge_only_with_override(self):
        profiles = [self._profile(key) for key in ("alias-a", "alias-b")]
        claims = [self._confirm_name(p, observations[0], name)
                  for (p, observations), name in zip(profiles, ("Alex Smith", "Alexander Smith"))]
        plan, _ = self._two_profile_plan(profiles)
        self.assertTrue(plan.pair_evidence[0].eligible)
        self.assertIn("confirmed_name_claim", plan.pair_evidence[0].identity_warnings)
        self.assertIn("conflicting_explicit_attribution", plan.pair_evidence[0].identity_warnings)
        conflicts = []
        self.assertIsNone(apply_source_profile_consolidation(
            self.database, plan=plan, proposal=plan.proposals[0], reviewer="brian",
            artifact_sha256="c" * 64, conflicts=conflicts,
        ))
        self.assertIn("--allow-confirmed-names", conflicts[0])
        retained = profiles[1][0].id
        self.assertEqual(retained, apply_source_profile_consolidation(
            self.database, plan=plan, proposal=plan.proposals[0], reviewer="brian",
            artifact_sha256="c" * 64, allow_confirmed_names=True,
            canonical_profile_id=retained,
        ))
        self.assertEqual({claim.id for claim in claims}, set(self.database.list_effective_name_claim_ids_for_profile(retained)))
        self.assertEqual(retained, self.database.resolve_speaker_profile_id(profiles[0][0].id))

    def test_unconfirmed_profile_defaults_to_confirmed_target(self):
        profiles = [self._profile(key) for key in ("unnamed", "named")]
        self._confirm_name(profiles[1][0], profiles[1][1][0], "Alex Smith")
        plan, _ = self._two_profile_plan(profiles)
        self.assertEqual(profiles[1][0].id, apply_source_profile_consolidation(
            self.database, plan=plan, proposal=plan.proposals[0], reviewer="brian",
            artifact_sha256="d" * 64, allow_confirmed_names=True,
        ))

    def test_configured_name_variants_can_merge_with_preserved_bindings(self):
        profiles = []
        pastors = []
        for key, name in [("configured-a", "Alex Smith"), ("configured-b", "Alexander Smith")]:
            pastor = self.database.add_pastor(key, name)
            pastors.append(pastor)
            profile = ensure_configured_pastor_profile(self.database, pastor)
            observations = tuple(self._observation(f"{key}-{i}") for i in range(2))
            for observation in observations:
                attach_reviewed_observation(
                    self.database, profile_id=profile.id, observation_id=observation.id,
                    reviewer="brian", reason="Reviewed voice", review_event_key=f"configured-attach-{observation.id}",
                )
            profiles.append((profile, observations))
        plan, _ = self._two_profile_plan(profiles)
        self.assertTrue(plan.proposals)
        self.assertIn("configured_pastor_identity", plan.candidates[0].identity_warnings)
        canonical = apply_source_profile_consolidation(
            self.database, plan=plan, proposal=plan.proposals[0], reviewer="brian",
            artifact_sha256="e" * 64, allow_confirmed_names=True,
        )
        self.assertEqual(profiles[0][0].id, canonical)
        for pastor in pastors:
            self.assertEqual(canonical, self.database.resolve_speaker_profile_id(self.database.get_pastor_speaker_profile_id(pastor.id)))

    def test_name_override_never_bypasses_reviewed_difference(self):
        profiles = [self._profile(key) for key in ("difference-a", "difference-b")]
        plan, _ = self._two_profile_plan(profiles)
        self.database.add_speaker_observation_difference_event(
            observation_a_id=profiles[0][1][0].id,
            observation_b_id=profiles[1][1][0].id,
            action="assert", reviewer="brian", reason="Different voices",
            event_fingerprint="different-voices",
        )
        conflicts = []
        self.assertIsNone(apply_source_profile_consolidation(
            self.database, plan=plan, proposal=plan.proposals[0], reviewer="brian",
            artifact_sha256="f" * 64, allow_confirmed_names=True, conflicts=conflicts,
        ))
        self.assertIn("different-speaker", conflicts[0])
        self.assertEqual([p.id for p, _ in profiles], [self.database.resolve_speaker_profile_id(p.id) for p, _ in profiles])

    def test_ambiguous_review_command_pins_exact_windows_and_receipts(self):
        profiles = [self._profile(key) for key in ("review-a", "review-b")]
        plan, comparisons = self._two_profile_plan(profiles)
        pair = tuple(sorted((profiles[0][1][0].id, profiles[1][1][0].id)))
        comparisons[pair] = {"outcome": "insufficient_evidence", "reason": "ambiguous_similarity"}
        plan, _ = self._two_profile_plan(profiles, comparisons=comparisons)
        suggestions = source_profile_review_suggestions(
            self.database, plan, comparisons=comparisons, base_dir=self.paths.root,
            evaluation_root=self.paths.root / "evaluation/speaker-pairs",
            cache_dir=self.paths.root / "evaluation/speaker-pairs/cache",
        )
        self.assertEqual(1, len(suggestions))
        suggestion = suggestions[0]
        self.assertEqual(list(pair), suggestion["observation_ids"])
        args = shlex.split(suggestion["review_command"])
        self.assertEqual(profiles[0][1][0].input_fingerprint, args[args.index("--observation-fingerprint-a") + 1])
        self.assertEqual(profiles[1][1][0].input_fingerprint, args[args.index("--observation-fingerprint-b") + 1])
        self.assertIn("--", args)
        self.assertFalse(plan.proposals)
        provenance = (ReviewProvenance("exact-review-event", "pair-id", "brian"),)
        fingerprints = frozenset((profiles[0][1][0].input_fingerprint, profiles[1][1][0].input_fingerprint))
        evidence = replace(self._evidence(),
            qualifications={fp: ObservationQualification("qualified_single_speaker", provenance) for fp in fingerprints},
            pair_relations={fingerprints: PairRelation(fingerprints, "same_speaker", provenance)},
        )
        reviewed_plan, _ = self._two_profile_plan(profiles, comparisons=comparisons, evidence=evidence)
        self.assertTrue(reviewed_plan.proposals)
        self.assertEqual((pair,), reviewed_plan.pair_evidence[0].reviewed_same_pairs)
        self.assertEqual(("exact-review-event",), reviewed_plan.pair_evidence[0].review_event_ids)
        payload = source_profile_consolidation_payload(
            reviewed_plan, comparisons=comparisons, model_fingerprint="model", policy_fingerprint="policy",
        )
        self.assertEqual("insufficient_evidence", next(item for item in payload["comparisons"] if item["observation_ids"] == list(pair))["outcome"])
        self.assertEqual([[*pair]], payload["pair_evidence"][0]["reviewed_same_pairs"])

    def test_plan_only_cli_includes_confirmed_name_and_warns_without_override(self):
        profiles = [self._profile(key) for key in ("cli-a", "cli-b")]
        self._confirm_name(profiles[1][0], profiles[1][1][0], "Alex Smith")
        with patch("pastor_transcript_extractor.cli.load_shadow_policy"):
            result = CliRunner().invoke(app, [
                "identity", "consolidate-source-profiles", "--source-id", str(self.source.id),
                "--plan-only", "--base-dir", str(self.paths.root),
                "--evaluation-root", str(self.paths.root / "evaluation/speaker-pairs"),
            ])
        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn("profiles=2", result.output)
        self.assertIn("confirmed_name_claim", result.output)
        self.assertIn("--allow-confirmed-names", result.output)
        self.assertEqual(profiles[0][0].id, self.database.resolve_speaker_profile_id(profiles[0][0].id))

    def test_override_rolls_back_name_and_membership_events_on_failure(self):
        profiles = [self._profile(key) for key in ("rollback-a", "rollback-b")]
        claim = self._confirm_name(profiles[1][0], profiles[1][1][0], "Alex Smith")
        plan, _ = self._two_profile_plan(profiles)
        with patch("pastor_transcript_extractor.reviewed_speaker_evidence.attach_reviewed_observation", side_effect=ValueError("failed attachment")):
            with self.assertRaisesRegex(ValueError, "failed attachment"):
                apply_source_profile_consolidation(
                    self.database, plan=plan, proposal=plan.proposals[0], reviewer="brian",
                    artifact_sha256="a" * 64, allow_confirmed_names=True,
                    canonical_profile_id=profiles[0][0].id,
                )
        self.assertEqual([claim.id], self.database.list_effective_name_claim_ids_for_profile(profiles[1][0].id))
        self.assertFalse(self.database.list_effective_name_claim_ids_for_profile(profiles[0][0].id))
        for profile, observations in profiles:
            self.assertEqual(profile.id, self.database.resolve_speaker_profile_id(profile.id))
            self.assertEqual([o.id for o in observations], self.database.list_effective_observation_ids_for_profile(profile.id))

    def test_human_difference_blocks_even_before_registry_sync(self):
        profiles = [self._profile(key) for key in ("human-diff-a", "human-diff-b")]
        unsampled = []
        for index, (profile, _) in enumerate(profiles):
            observation = self._observation(f"unsampled-{index}")
            attach_reviewed_observation(
                self.database, profile_id=profile.id, observation_id=observation.id,
                reviewer="brian", reason="Reviewed voice", review_event_key=f"unsampled-{index}",
            )
            unsampled.append(observation)
        fingerprints = frozenset(observation.input_fingerprint for observation in unsampled)
        evidence = replace(self._evidence(), pair_relations={
            fingerprints: PairRelation(fingerprints, "different_speaker", ()),
        })
        plan, _ = self._two_profile_plan(profiles, evidence=evidence)
        self.assertTrue(all(observation.id not in candidate.exemplar_observation_ids
                            for candidate in plan.candidates for observation in unsampled))
        self.assertFalse(plan.proposals)
        self.assertIn("reviewed_different_speaker_constraint", plan.pair_evidence[0].blockers)

    def test_weakest_pair_uses_nested_acoustic_score(self):
        profiles = [self._profile(key) for key in ("score-a", "score-b")]
        _, comparisons = self._two_profile_plan(profiles)
        for result in comparisons.values():
            result["metrics"] = {"cross": {"p10": 0.8, "median": 0.85}}
        weakest = max(comparisons)
        comparisons[weakest]["metrics"]["cross"]["p10"] = 0.61
        plan, _ = self._two_profile_plan(profiles, comparisons=comparisons)
        self.assertEqual(weakest, plan.proposals[0].weakest_observation_pair)
        self.assertEqual(0.61, plan.proposals[0].weakest_score)


if __name__ == "__main__":
    unittest.main()
