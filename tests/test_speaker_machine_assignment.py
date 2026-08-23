from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_machine_assignment import (
    MachineAssignmentPolicy,
    active_machine_assignment_evidence,
    apply_machine_assignment_plan,
    load_machine_assignment_policy,
    machine_assignment_status,
    plan_machine_assignments,
    reconcile_machine_assignments,
    rollback_machine_assignments,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
    record_observation_difference,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    ProfileAssociationReadiness,
    SHADOW_ASSOCIATION_VERSION,
)
from pastor_transcript_extractor.storage import Database


class SpeakerMachineAssignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = build_paths(self.root / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.source = self.database.add_source(
            "https://www.youtube.com/@machine",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        self.members = [self._observation(key) for key in ("a", "b", "c")]
        self.profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="test profile",
            review_event_key="test-profile",
        )
        for observation in self.members:
            attach_reviewed_observation(
                self.database,
                profile_id=self.profile.id,
                observation_id=observation.id,
                reviewer="reviewer",
                reason="test member",
                review_event_key=f"member-{observation.input_fingerprint}",
            )
        self.readiness = (
            ProfileAssociationReadiness(
                profile_id=self.profile.id,
                member_observation_ids=tuple(item.id for item in self.members),
                member_fingerprints=tuple(
                    item.input_fingerprint for item in self.members
                ),
                recording_count=3,
                source_count=1,
                normalized_names=(),
                shadow_ready=True,
                automatic_profile_ready=True,
                shadow_blockers=(),
                automatic_blockers=(),
            ),
        )
        self.shadow_policy = MachineAssignmentPolicy(
            version="shadow-v1",
            mode="shadow",
            minimum_same_exemplars=2,
            require_unique_profile=True,
            require_automatic_profile_ready=True,
            allow_provisional_activation=False,
            artifact_sha256="1" * 64,
        )
        self.canary_policy = MachineAssignmentPolicy(
            version="canary-v1",
            mode="canary_provisional",
            minimum_same_exemplars=2,
            require_unique_profile=True,
            require_automatic_profile_ready=True,
            allow_provisional_activation=True,
            artifact_sha256="2" * 64,
            maximum_active_assignments=2,
            allowed_association_policy_sha256=("association-policy-hash",),
            allowed_model_fingerprints=("model-v1",),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

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
            proposed_text_path=str(self.root / f"{key}.md"),
            proposed_json_path=str(self.root / f"{key}.json"),
        )
        return self.database.add_speaker_observation(
            video_id=video.id,
            extraction_result_id=extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="unknown",
            start_seconds=100.0,
            end_seconds=1000.0,
            artifact_path=str(self.root / f"{key}.speaker.json"),
            content_sha256=f"content-{key}",
            extractor_version="speaker_evidence_v2",
            input_fingerprint=key,
        )

    def _report(self, candidate, suffix: str) -> Path:
        comparisons = [
            {
                "exemplar_observation_id": member.id,
                "exemplar_fingerprint": member.input_fingerprint,
                "exemplar_normalized_audio_sha256": (
                    f"audio-{member.input_fingerprint}"
                ),
                "outcome": "same_speaker",
                "reason": "approved_policy_same_band",
                "registry_mutation_allowed": False,
            }
            for member in self.members[:2]
        ]
        payload = {
            "artifact_kind": "speaker_profile_shadow_association",
            "association_version": SHADOW_ASSOCIATION_VERSION,
            "shadow_mode": True,
            "registry_mutation_allowed": False,
            "automatic_assignment_allowed": False,
            "span_selection": {
                "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
            },
            "candidate": {
                "observation_id": candidate.id,
                "video_id": candidate.video_id,
                "input_fingerprint": candidate.input_fingerprint,
                "normalized_audio_sha256": (
                    f"audio-{candidate.input_fingerprint}"
                ),
            },
            "model_fingerprint": "model-v1",
            "policy": {
                "version": "association-policy-v1",
                "artifact_sha256": "association-policy-hash",
            },
            "outcome": "proposed_match",
            "proposed_profile_id": self.profile.id,
            "profiles": [
                {
                    "profile_id": self.profile.id,
                    "meets_multi_exemplar_match": True,
                    "comparisons": comparisons,
                }
            ],
        }
        payload["result_sha256"] = _sha256(payload)
        path = self.root / f"association-{suffix}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _eligibility(self, database, video_id, **_kwargs):
        observation = database.get_latest_speaker_observation_for_video(video_id)
        return SimpleNamespace(
            eligible=observation is not None,
            observation=observation,
            media_artifact=(
                SimpleNamespace(
                    content_sha256=f"audio-{observation.input_fingerprint}"
                )
                if observation is not None
                else None
            ),
        )

    def _plan(self, candidates, policy):
        paths = [self._report(item, item.input_fingerprint) for item in candidates]
        with patch(
            "pastor_transcript_extractor.speaker_machine_assignment."
            "assess_automatic_speaker_observation",
            side_effect=self._eligibility,
        ):
            return plan_machine_assignments(
                self.database,
                paths,
                readiness=self.readiness,
                policy=policy,
            )

    def test_shadow_plan_records_evidence_without_membership(self) -> None:
        candidate = self._observation("candidate")
        plan = self._plan((candidate,), self.shadow_policy)

        result = apply_machine_assignment_plan(
            self.database,
            plan,
            activate_canary=False,
        )

        self.assertEqual(1, result.evidence_recorded)
        self.assertEqual(0, result.assignments_activated)
        self.assertEqual((), active_machine_assignment_evidence(self.database))
        self.assertEqual(
            [],
            self.database.list_effective_profile_ids_for_observation(
                candidate.id
            ),
        )
        self.assertEqual(
            1,
            machine_assignment_status(self.database)["counts"][
                "evidence_only"
            ],
        )

        replay = apply_machine_assignment_plan(
            self.database,
            plan,
            activate_canary=False,
        )
        self.assertEqual(0, replay.evidence_recorded)
        self.assertEqual(1, replay.evidence_reused)
        self.assertEqual(1, len(self.database.list_speaker_machine_evidence()))

    def test_nonexhaustive_shortlist_proposal_is_not_machine_evidence(self) -> None:
        candidate = self._observation("shortlisted")
        path = self._report(candidate, "shortlisted")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("result_sha256")
        payload["routing"] = {
            "route": "source_name_priority_with_global_centroid_shortlist",
            "exhaustive": False,
        }
        payload["result_sha256"] = _sha256(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")

        with patch(
            "pastor_transcript_extractor.speaker_machine_assignment."
            "assess_automatic_speaker_observation",
            side_effect=self._eligibility,
        ):
            plan = plan_machine_assignments(
                self.database,
                [path],
                readiness=self.readiness,
                policy=self.shadow_policy,
            )

        self.assertEqual((), plan.candidates)
        self.assertEqual(
            1,
            plan.skipped_counts["stale_or_nonproposal_artifact"],
        )
        self.assertEqual([], self.database.list_speaker_machine_evidence())

    def test_canary_confirmation_requires_reviewed_membership(self) -> None:
        candidate = self._observation("candidate")
        plan = self._plan((candidate,), self.canary_policy)
        apply_machine_assignment_plan(
            self.database,
            plan,
            activate_canary=True,
        )
        self.assertEqual(1, len(active_machine_assignment_evidence(self.database)))
        self.assertEqual(
            [],
            self.database.list_effective_profile_ids_for_observation(
                candidate.id
            ),
        )

        attach_reviewed_observation(
            self.database,
            profile_id=self.profile.id,
            observation_id=candidate.id,
            reviewer="reviewer",
            reason="confirmed canary",
            review_event_key="confirm-canary",
        )
        with patch(
            "pastor_transcript_extractor.speaker_machine_assignment."
            "assess_automatic_speaker_observation",
            side_effect=self._eligibility,
        ):
            result = reconcile_machine_assignments(self.database)

        self.assertEqual(1, result.confirmed)
        self.assertEqual(0, len(active_machine_assignment_evidence(self.database)))
        self.assertEqual(
            1,
            machine_assignment_status(self.database)["counts"]["confirmed"],
        )

    def test_contradiction_trips_policy_and_revokes_other_active_assignments(
        self,
    ) -> None:
        candidate_a = self._observation("candidate-a")
        candidate_b = self._observation("candidate-b")
        plan = self._plan((candidate_a, candidate_b), self.canary_policy)
        apply_machine_assignment_plan(
            self.database,
            plan,
            activate_canary=True,
        )
        record_observation_difference(
            self.database,
            observation_a_id=candidate_a.id,
            observation_b_id=self.members[0].id,
            different=True,
            reviewer="reviewer",
            reason="canary contradiction",
            review_event_key="canary-different",
        )

        with patch(
            "pastor_transcript_extractor.speaker_machine_assignment."
            "assess_automatic_speaker_observation",
            side_effect=self._eligibility,
        ):
            result = reconcile_machine_assignments(self.database)

        self.assertEqual(1, result.revoked)
        self.assertEqual(1, result.circuit_breaker_revoked)
        self.assertEqual(0, len(active_machine_assignment_evidence(self.database)))
        self.assertEqual(1, len(result.tripped_policy_fingerprints))

    def test_manual_policy_rollback_is_append_only(self) -> None:
        candidate = self._observation("candidate")
        plan = self._plan((candidate,), self.canary_policy)
        apply_machine_assignment_plan(
            self.database,
            plan,
            activate_canary=True,
        )
        policy_fingerprint = str(
            self.database.list_speaker_machine_evidence()[0][
                "policy_fingerprint"
            ]
        )

        revoked = rollback_machine_assignments(
            self.database,
            policy_fingerprint=policy_fingerprint,
        )

        self.assertEqual(1, revoked)
        self.assertEqual(0, len(active_machine_assignment_evidence(self.database)))
        self.assertEqual(2, len(self.database.list_speaker_machine_assignment_events()))

    def test_canary_activation_respects_global_cap(self) -> None:
        candidates = tuple(
            self._observation(f"candidate-{index}") for index in range(3)
        )
        plan = self._plan(candidates, self.canary_policy)

        result = apply_machine_assignment_plan(
            self.database,
            plan,
            activate_canary=True,
        )

        self.assertEqual(2, result.assignments_activated)
        self.assertEqual(1, result.activation_blocked)
        self.assertEqual(2, len(active_machine_assignment_evidence(self.database)))

    def test_terminal_evidence_cannot_be_reactivated(self) -> None:
        candidate = self._observation("candidate")
        plan = self._plan((candidate,), self.canary_policy)
        apply_machine_assignment_plan(
            self.database,
            plan,
            activate_canary=True,
        )
        policy_fingerprint = str(
            self.database.list_speaker_machine_evidence()[0][
                "policy_fingerprint"
            ]
        )
        rollback_machine_assignments(
            self.database,
            policy_fingerprint=policy_fingerprint,
        )

        replay = self._plan((candidate,), self.canary_policy)

        self.assertEqual((), replay.candidates)
        self.assertEqual(1, replay.skipped_counts["candidate_evidence_terminal"])

    def test_stale_or_rejected_observation_is_revoked_without_tripping_policy(
        self,
    ) -> None:
        candidate = self._observation("candidate")
        plan = self._plan((candidate,), self.canary_policy)
        apply_machine_assignment_plan(
            self.database,
            plan,
            activate_canary=True,
        )
        with patch(
            "pastor_transcript_extractor.speaker_machine_assignment."
            "assess_automatic_speaker_observation",
            return_value=SimpleNamespace(eligible=False, observation=None),
        ):
            result = reconcile_machine_assignments(self.database)

        self.assertEqual(1, result.revoked)
        self.assertEqual((), result.tripped_policy_fingerprints)
        self.assertEqual(0, len(active_machine_assignment_evidence(self.database)))

    def test_changed_profile_snapshot_revokes_provisional_assignment(self) -> None:
        candidate = self._observation("candidate")
        plan = self._plan((candidate,), self.canary_policy)
        apply_machine_assignment_plan(
            self.database,
            plan,
            activate_canary=True,
        )
        new_member = self._observation("new-member")
        attach_reviewed_observation(
            self.database,
            profile_id=self.profile.id,
            observation_id=new_member.id,
            reviewer="reviewer",
            reason="profile changed after machine evidence",
            review_event_key="new-member-after-machine-evidence",
        )
        with patch(
            "pastor_transcript_extractor.speaker_machine_assignment."
            "assess_automatic_speaker_observation",
            side_effect=self._eligibility,
        ):
            result = reconcile_machine_assignments(self.database)

        self.assertEqual(1, result.revoked)
        self.assertEqual((), result.tripped_policy_fingerprints)

    def test_held_out_candidate_is_excluded(self) -> None:
        candidate = self._observation("candidate")
        path = self._report(candidate, "held-out")
        with patch(
            "pastor_transcript_extractor.speaker_machine_assignment."
            "assess_automatic_speaker_observation",
            side_effect=self._eligibility,
        ):
            plan = plan_machine_assignments(
                self.database,
                (path,),
                readiness=self.readiness,
                policy=self.shadow_policy,
                excluded_observation_fingerprints=frozenset(("candidate",)),
            )

        self.assertEqual((), plan.candidates)
        self.assertEqual(
            1,
            plan.skipped_counts[
                "candidate_stale_or_evaluation_reserved"
            ],
        )

    def test_single_video_plan_excludes_other_observations(self) -> None:
        included = self._observation("included")
        outside = self._observation("outside")
        paths = (
            self._report(included, "included"),
            self._report(outside, "outside"),
        )
        with patch(
            "pastor_transcript_extractor.speaker_machine_assignment."
            "assess_automatic_speaker_observation",
            side_effect=self._eligibility,
        ):
            plan = plan_machine_assignments(
                self.database,
                paths,
                readiness=self.readiness,
                policy=self.shadow_policy,
                included_observation_ids=frozenset((included.id,)),
            )

        self.assertEqual(
            (included.id,),
            tuple(item.observation_id for item in plan.candidates),
        )
        self.assertEqual(1, plan.skipped_counts["candidate_outside_run_scope"])

    def test_canary_policy_requires_cap_and_pinned_provenance(self) -> None:
        policy_path = self.root / "unsafe-canary.json"
        policy_path.write_text(
            json.dumps(
                {
                    "policy_version": "unsafe-canary",
                    "mode": "canary_provisional",
                    "minimum_same_exemplars": 2,
                    "require_unique_profile": True,
                    "require_automatic_profile_ready": True,
                    "allow_provisional_activation": True,
                    "maximum_active_assignments": 1,
                    "allowed_association_policy_sha256": [],
                    "allowed_model_fingerprints": [],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "pin approved"):
            load_machine_assignment_policy(policy_path)

    def test_checked_in_human_on_loop_policy_is_pinned_and_bounded(self) -> None:
        policy = load_machine_assignment_policy(
            Path(
                "evaluation/speaker-associations/policies/"
                "machine-assignment-human-on-loop-v1.json"
            )
        )

        self.assertEqual("canary_provisional", policy.mode)
        self.assertTrue(policy.allow_provisional_activation)
        self.assertEqual(600, policy.maximum_active_assignments)
        self.assertEqual(1, len(policy.allowed_association_policy_sha256))
        self.assertEqual(1, len(policy.allowed_model_fingerprints))


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    unittest.main()
