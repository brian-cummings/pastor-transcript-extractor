from __future__ import annotations

from dataclasses import replace
import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    PairRelation,
    ReviewProvenance,
    ReviewedSpeakerEvidence,
)
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    DecisionPolicy,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
    record_observation_difference,
    record_profile_redirect,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    ProfileAssociationReadiness,
    SHADOW_ASSOCIATION_FINGERPRINT_VERSION,
    ShadowExemplar,
    ShadowPolicySpec,
    assess_profile_association_readiness,
    build_shadow_association_input_fingerprint,
    evaluate_shadow_association,
    load_reusable_shadow_association,
    load_shadow_policy,
    plan_pending_discovery_confirmation_routes,
    select_profile_exemplars,
    select_routed_association_profiles,
    select_staged_association_profiles,
    summarize_shadow_associations,
    write_shadow_association,
)
from pastor_transcript_extractor.storage import Database


class SpeakerShadowAssociationTests(unittest.TestCase):
    def test_candidate_edge_flag_is_promoted_to_report_diagnostics(self) -> None:
        candidate = self._observation("edge-flag")
        flag = {
            "flag": "speaker_inconsistent_edge",
            "edge": "end",
            "start_seconds": 980.0,
            "end_seconds": 992.0,
            "automatic_boundary_change_allowed": False,
        }

        report = evaluate_shadow_association(
            candidate=candidate,
            candidate_audio_path=Path("candidate.wav"),
            candidate_audio_sha256="candidate-audio",
            candidate_normalized_names=(),
            profiles=(),
            compare=lambda *_args: {},
            policy_spec=self._policy_spec(),
            model_fingerprint="model",
            span_selection={
                "candidate_selection": {
                    "sermon_window_quality_flags": [flag]
                }
            },
        )

        self.assertEqual([flag], report["sermon_window_quality_flags"])
        self.assertFalse(
            report["sermon_window_quality_flags"][0][
                "automatic_boundary_change_allowed"
            ]
        )

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = build_paths(self.root / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.source = self.database.add_source(
            "https://www.youtube.com/@shadow",
            SourceType.CHANNEL,
            pastor_id=None,
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

    def _profile(self, observations):
        profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="reviewed component",
            review_event_key=f"profile-{observations[0].input_fingerprint}",
        )
        for observation in observations:
            attach_reviewed_observation(
                self.database,
                profile_id=profile.id,
                observation_id=observation.id,
                reviewer="reviewer",
                reason="reviewed component",
                review_event_key=f"attach-{observation.input_fingerprint}",
            )
        return profile

    def _evidence(self, pairs):
        provenance = (ReviewProvenance("event", "pair", "reviewer"),)
        return ReviewedSpeakerEvidence(
            qualifications={},
            qualification_conflicts={},
            pair_relations={
                frozenset(pair): PairRelation(
                    frozenset(pair),
                    "same_speaker",
                    provenance,
                )
                for pair in pairs
            },
            pair_conflicts={},
            review_event_count=len(pairs),
        )

    def _policy_spec(self):
        return ShadowPolicySpec(
            policy=DecisionPolicy(
                version="test-policy",
                min_valid_spans=2,
                min_within_median=0.7,
                same_min_cross_p10=0.6,
                same_min_cross_median=0.7,
                different_max_cross_p90=0.3,
            ),
            review_status="experimental_candidate",
            artifact_sha256="a" * 64,
            automatic_use_allowed=False,
        )

    def test_shadow_readiness_precedes_redundant_automatic_readiness(self) -> None:
        observations = [self._observation(key) for key in ("a", "b", "c")]
        profile = self._profile(observations)

        chain = assess_profile_association_readiness(
            self.database,
            self._evidence((("a", "b"), ("b", "c"))),
        )[0]
        triangle = assess_profile_association_readiness(
            self.database,
            self._evidence((("a", "b"), ("b", "c"), ("a", "c"))),
        )[0]

        self.assertEqual(chain.profile_id, profile.id)
        self.assertTrue(chain.shadow_ready)
        self.assertFalse(chain.automatic_profile_ready)
        self.assertIn(
            "reviewed_same_graph_contains_bridge",
            chain.automatic_blockers,
        )
        self.assertTrue(triangle.shadow_ready)
        self.assertTrue(triangle.automatic_profile_ready)

    def test_two_member_profile_is_review_ready_but_not_shadow_ready(self) -> None:
        observations = [self._observation(key) for key in ("a", "b")]
        self._profile(observations)

        readiness = assess_profile_association_readiness(
            self.database,
            self._evidence((("a", "b"),)),
        )[0]

        self.assertTrue(readiness.review_ready)
        self.assertFalse(readiness.shadow_ready)
        self.assertFalse(readiness.automatic_profile_ready)
        self.assertIn(
            "fewer_than_three_profile_members",
            readiness.shadow_blockers,
        )

    def test_certified_core_survives_bridge_only_member(self) -> None:
        observations = {
            key: self._observation(key) for key in ("a", "b", "c", "leaf")
        }
        profile = self._profile(list(observations.values()))
        readiness = assess_profile_association_readiness(
            self.database,
            self._evidence(
                (("a", "b"), ("b", "c"), ("a", "c"), ("c", "leaf"))
            ),
        )[0]

        self.assertTrue(readiness.automatic_profile_ready)
        self.assertEqual(
            {observations[key].id for key in ("a", "b", "c")},
            set(readiness.certified_exemplar_observation_ids),
        )
        exemplars = tuple(
            ShadowExemplar(
                profile.id,
                observation,
                Path(f"{observation.id}.wav"),
                f"audio-{observation.id}",
            )
            for observation in observations.values()
        )
        selected = select_profile_exemplars(
            readiness,
            exemplars,
            videos_by_id={
                video.id: video for video in self.database.list_videos()
            },
        )
        self.assertNotIn(
            observations["leaf"].id,
            {item.observation.id for item in selected},
        )

    def test_merged_certified_components_remain_ready(self) -> None:
        left = [self._observation(key) for key in ("a", "b", "c")]
        right = [self._observation(key) for key in ("d", "e", "f")]
        left_profile = self._profile(left)
        right_profile = self._profile(right)
        record_profile_redirect(
            self.database,
            from_profile_id=left_profile.id,
            to_profile_id=right_profile.id,
            reviewer="reviewer",
            reason="reviewed duplicate profiles",
            review_event_key="merge-certified-components",
        )

        readiness = assess_profile_association_readiness(
            self.database,
            self._evidence(
                (
                    ("a", "b"),
                    ("b", "c"),
                    ("a", "c"),
                    ("d", "e"),
                    ("e", "f"),
                    ("d", "f"),
                    ("c", "d"),
                )
            ),
        )

        self.assertEqual(1, len(readiness))
        self.assertEqual(right_profile.id, readiness[0].profile_id)
        self.assertTrue(readiness[0].automatic_profile_ready)
        self.assertEqual(
            {item.id for item in (*left, *right)},
            set(readiness[0].certified_exemplar_observation_ids),
        )
        record_profile_redirect(
            self.database,
            from_profile_id=left_profile.id,
            to_profile_id=None,
            reviewer="reviewer",
            reason="reverse merge direction",
            review_event_key="clear-merge-certified-components",
        )
        record_profile_redirect(
            self.database,
            from_profile_id=right_profile.id,
            to_profile_id=left_profile.id,
            reviewer="reviewer",
            reason="reviewed duplicate profiles",
            review_event_key="reverse-merge-certified-components",
        )

        reversed_readiness = assess_profile_association_readiness(
            self.database,
            self._evidence(
                (
                    ("a", "b"),
                    ("b", "c"),
                    ("a", "c"),
                    ("d", "e"),
                    ("e", "f"),
                    ("d", "f"),
                    ("c", "d"),
                )
            ),
        )
        self.assertEqual(left_profile.id, reversed_readiness[0].profile_id)
        self.assertTrue(reversed_readiness[0].automatic_profile_ready)
        self.assertEqual(
            {item.id for item in (*left, *right)},
            set(reversed_readiness[0].certified_exemplar_observation_ids),
        )

    def test_reviewed_difference_suspends_certified_core(self) -> None:
        observations = [self._observation(key) for key in ("a", "b", "c")]
        profile = self._profile(observations)
        conflicting = self._observation("conflicting")
        conflicting_profile = self._profile((conflicting,))
        record_observation_difference(
            self.database,
            observation_a_id=observations[0].id,
            observation_b_id=conflicting.id,
            different=True,
            reviewer="reviewer",
            reason="reviewed contradiction",
            review_event_key="certified-core-contradiction",
        )
        record_profile_redirect(
            self.database,
            from_profile_id=conflicting_profile.id,
            to_profile_id=profile.id,
            reviewer="reviewer",
            reason="later profile merge",
            review_event_key="contradictory-profile-merge",
        )

        readiness = assess_profile_association_readiness(
            self.database,
            self._evidence((("a", "b"), ("b", "c"), ("a", "c"))),
        )[0]

        self.assertFalse(readiness.automatic_profile_ready)
        self.assertIn(
            "internal_reviewed_difference",
            readiness.automatic_blockers,
        )

    def test_review_ready_profile_can_propose_human_confirmation(self) -> None:
        candidate = self._observation("candidate")
        exemplars = [self._observation(key) for key in ("a", "b")]
        profile = self._profile(exemplars)
        readiness = ProfileAssociationReadiness(
            profile_id=profile.id,
            member_observation_ids=tuple(item.id for item in exemplars),
            member_fingerprints=tuple(
                item.input_fingerprint for item in exemplars
            ),
            recording_count=2,
            source_count=1,
            normalized_names=(),
            shadow_ready=False,
            automatic_profile_ready=False,
            shadow_blockers=("fewer_than_three_profile_members",),
            automatic_blockers=("fewer_than_three_profile_members",),
            review_ready=True,
        )

        report = evaluate_shadow_association(
            candidate=candidate,
            candidate_audio_path=Path("candidate.wav"),
            candidate_audio_sha256="candidate-audio",
            candidate_normalized_names=(),
            profiles=(
                (
                    readiness,
                    tuple(
                        ShadowExemplar(
                            profile.id,
                            exemplar,
                            Path(f"{exemplar.id}.wav"),
                            f"audio-{exemplar.id}",
                        )
                        for exemplar in exemplars
                    ),
                ),
            ),
            compare=lambda *_args: {"outcome": "same_speaker"},
            policy_spec=self._policy_spec(),
            model_fingerprint="model",
        )

        self.assertEqual("proposed_match", report["outcome"])
        self.assertFalse(
            report["profiles"][0]["profile_readiness"][
                "automatic_profile_ready"
            ]
        )

    def test_immature_review_targets_require_source_or_name_routing(self) -> None:
        observations = [
            self._observation(key) for key in ("mature", "local", "distant")
        ]

        def profile_input(index, *, shadow_ready=False, names=()):
            readiness = ProfileAssociationReadiness(
                profile_id=index + 1,
                member_observation_ids=(observations[index].id,),
                member_fingerprints=(
                    observations[index].input_fingerprint,
                ),
                recording_count=2,
                source_count=1,
                normalized_names=names,
                shadow_ready=shadow_ready,
                automatic_profile_ready=shadow_ready,
                shadow_blockers=(),
                automatic_blockers=(),
                review_ready=True,
            )
            return (
                readiness,
                (
                    ShadowExemplar(
                        readiness.profile_id,
                        observations[index],
                        Path(f"{index}.wav"),
                        f"audio-{index}",
                    ),
                ),
            )

        profiles = (
            profile_input(0, shadow_ready=True),
            profile_input(1),
            profile_input(2, names=("alice example",)),
        )
        selected = select_routed_association_profiles(
            profiles,
            candidate_source_id=7,
            candidate_normalized_names=("alice example",),
            source_id_by_video_id={
                observations[0].video_id: 1,
                observations[1].video_id: 7,
                observations[2].video_id: 9,
            },
        )

        self.assertEqual(
            {1, 2, 3},
            {readiness.profile_id for readiness, _ in selected},
        )

        unrelated = select_routed_association_profiles(
            profiles,
            candidate_source_id=8,
            candidate_normalized_names=(),
            source_id_by_video_id={
                observation.video_id: index + 1
                for index, observation in enumerate(observations)
            },
        )
        self.assertEqual(
            {1},
            {readiness.profile_id for readiness, _ in unrelated},
        )

    def test_unconfirmed_discovery_profile_is_not_a_global_target(self) -> None:
        observation = self._observation("unconfirmed")
        readiness = ProfileAssociationReadiness(
            profile_id=93,
            member_observation_ids=(observation.id,),
            member_fingerprints=(observation.input_fingerprint,),
            recording_count=3,
            source_count=1,
            normalized_names=(),
            shadow_ready=True,
            automatic_profile_ready=False,
            shadow_blockers=(),
            automatic_blockers=("discovery_candidate_unconfirmed",),
            review_ready=True,
        )
        profiles = (
            (
                readiness,
                (
                    ShadowExemplar(
                        93,
                        observation,
                        Path("unconfirmed.wav"),
                        "audio-unconfirmed",
                    ),
                ),
            ),
        )

        unrelated = select_routed_association_profiles(
            profiles,
            candidate_source_id=8,
            candidate_normalized_names=(),
            source_id_by_video_id={observation.video_id: 7},
        )
        local = select_routed_association_profiles(
            profiles,
            candidate_source_id=7,
            candidate_normalized_names=(),
            source_id_by_video_id={observation.video_id: 7},
        )

        self.assertEqual((), unrelated)
        self.assertEqual((profiles[0],), local)

        candidate_a = self._observation("candidate-a")
        candidate_b = self._observation("candidate-b")
        same_recording = self._observation("same-recording")
        confirmation_routes = plan_pending_discovery_confirmation_routes(
            profiles,
            candidate_centroids={
                candidate_a.id: (1.0, 0.0),
                candidate_b.id: (0.8, 0.2),
                same_recording.id: (1.0, 0.0),
            },
            candidate_video_ids={
                candidate_a.id: candidate_a.video_id,
                candidate_b.id: candidate_b.video_id,
                same_recording.id: observation.video_id,
            },
            exemplar_centroids={observation.id: (1.0, 0.0)},
            candidates_per_profile=2,
        )
        self.assertEqual(
            {
                candidate_a.id: (93,),
                candidate_b.id: (93,),
            },
            confirmation_routes,
        )

        forced = select_staged_association_profiles(
            profiles,
            candidate_source_id=8,
            candidate_normalized_names=(),
            source_id_by_video_id={observation.video_id: 7},
            candidate_centroid=(1.0, 0.0),
            exemplar_centroids={observation.id: (1.0, 0.0)},
            maximum_global_profiles=1,
            confirmation_priority_profile_ids=frozenset((93,)),
        )
        self.assertEqual((profiles[0],), forced.profiles)
        self.assertEqual((93,), forced.confirmation_priority_profile_ids)

    def test_staged_routing_keeps_local_and_shortlists_nearest_global(self) -> None:
        observations = [self._observation(str(index)) for index in range(5)]

        def profile_input(index: int):
            readiness = ProfileAssociationReadiness(
                profile_id=index + 1,
                member_observation_ids=(observations[index].id,),
                member_fingerprints=(observations[index].input_fingerprint,),
                recording_count=3,
                source_count=1,
                normalized_names=(),
                shadow_ready=True,
                automatic_profile_ready=True,
                shadow_blockers=(),
                automatic_blockers=(),
                review_ready=True,
            )
            return (
                readiness,
                (
                    ShadowExemplar(
                        readiness.profile_id,
                        observations[index],
                        Path(f"{index}.wav"),
                        f"audio-{index}",
                    ),
                ),
            )

        profiles = tuple(profile_input(index) for index in range(5))
        routing = select_staged_association_profiles(
            profiles,
            candidate_source_id=99,
            candidate_normalized_names=(),
            source_id_by_video_id={
                observations[0].video_id: 99,
                observations[1].video_id: 1,
                observations[2].video_id: 2,
                observations[3].video_id: 3,
                observations[4].video_id: 4,
            },
            candidate_centroid=(1.0, 0.0),
            exemplar_centroids={
                observations[0].id: (0.0, 1.0),
                observations[1].id: (0.9, 0.1),
                observations[2].id: (0.8, 0.2),
                observations[3].id: (0.7, 0.3),
                observations[4].id: (-1.0, 0.0),
            },
            maximum_global_profiles=2,
        )

        self.assertEqual((1,), routing.priority_profile_ids)
        self.assertEqual((2, 3), routing.shortlisted_profile_ids)
        self.assertEqual(
            {1, 2, 3},
            {readiness.profile_id for readiness, _ in routing.profiles},
        )
        self.assertFalse(routing.exhaustive)
        self.assertEqual(5, routing.total_routable_profiles)
        funnel = routing.candidate_funnel
        self.assertIsNotNone(funnel)
        entries = {
            item["profile_id"]: item
            for item in funnel["retrieval_candidates"]
        }
        self.assertEqual(["source"], entries[1]["retrieval_sources"])
        self.assertTrue(entries[1]["selected_for_comparison"])
        self.assertEqual(1, entries[2]["acoustic_rank"])
        self.assertTrue(entries[2]["passed_shortlist_cutoff"])
        self.assertEqual(3, entries[4]["acoustic_rank"])
        self.assertFalse(entries[4]["passed_shortlist_cutoff"])
        self.assertFalse(entries[4]["selected_for_comparison"])
        self.assertEqual([1, 2, 3], funnel["profiles_selected_for_comparison"])

    def test_multi_exemplar_unique_match_is_shadow_proposal_only(self) -> None:
        candidate = self._observation("candidate")
        matching = [self._observation(key) for key in ("a", "b", "c")]
        other = [self._observation(key) for key in ("d", "e", "f")]
        matching_profile = self._profile(matching)
        other_profile = self._profile(other)
        readiness = [
            ProfileAssociationReadiness(
                profile_id=matching_profile.id,
                member_observation_ids=tuple(item.id for item in matching),
                member_fingerprints=tuple(item.input_fingerprint for item in matching),
                recording_count=3,
                source_count=1,
                normalized_names=("alice example",),
                shadow_ready=True,
                automatic_profile_ready=True,
                shadow_blockers=(),
                automatic_blockers=(),
            ),
            ProfileAssociationReadiness(
                profile_id=other_profile.id,
                member_observation_ids=tuple(item.id for item in other),
                member_fingerprints=tuple(item.input_fingerprint for item in other),
                recording_count=3,
                source_count=1,
                normalized_names=("bob example",),
                shadow_ready=True,
                automatic_profile_ready=True,
                shadow_blockers=(),
                automatic_blockers=(),
            ),
        ]
        profiles = [
            (
                readiness[0],
                [
                    ShadowExemplar(
                        matching_profile.id,
                        observation,
                        Path(f"{observation.id}.wav"),
                        f"audio-{observation.input_fingerprint}",
                    )
                    for observation in matching
                ],
            ),
            (
                readiness[1],
                [
                    ShadowExemplar(
                        other_profile.id,
                        observation,
                        Path(f"{observation.id}.wav"),
                        f"audio-{observation.input_fingerprint}",
                    )
                    for observation in other
                ],
            ),
        ]

        def compare(_candidate, exemplar, _candidate_path, _exemplar_path):
            outcome = (
                "same_speaker"
                if exemplar.input_fingerprint in {"a", "b", "c"}
                else "different_speaker"
            )
            return {"outcome": outcome, "reason": "test"}

        report = evaluate_shadow_association(
            candidate=candidate,
            candidate_audio_path=Path("candidate.wav"),
            candidate_audio_sha256="candidate-audio",
            candidate_normalized_names=("alice example",),
            profiles=profiles,
            compare=compare,
            policy_spec=self._policy_spec(),
            model_fingerprint="model",
        )

        self.assertEqual(report["outcome"], "proposed_match")
        self.assertEqual(report["proposed_profile_id"], matching_profile.id)
        self.assertFalse(report["automatic_assignment_allowed"])
        self.assertFalse(report["registry_mutation_allowed"])
        self.assertEqual(
            report["candidate"]["normalized_audio_sha256"],
            "candidate-audio",
        )
        self.assertEqual(
            report["input_fingerprint_version"],
            SHADOW_ASSOCIATION_FINGERPRINT_VERSION,
        )
        destination = write_shadow_association(self.root / "runs", report)
        precomputed_fingerprint = build_shadow_association_input_fingerprint(
            candidate=candidate,
            candidate_audio_sha256="candidate-audio",
            candidate_normalized_names=("alice example",),
            profiles=profiles,
            policy_spec=self._policy_spec(),
            model_fingerprint="model",
            minimum_same_exemplars=2,
        )
        self.assertEqual(report["input_fingerprint"], precomputed_fingerprint)
        reusable = load_reusable_shadow_association(
            self.root / "runs",
            candidate_fingerprint=candidate.input_fingerprint,
            input_fingerprint=precomputed_fingerprint,
        )
        self.assertIsNotNone(reusable)
        assert reusable is not None
        self.assertEqual(destination, reusable[0])
        self.assertEqual(report, reusable[1])
        self.assertEqual(
            write_shadow_association(self.root / "runs", report),
            destination,
        )
        self.assertEqual(
            json.loads(destination.read_text(encoding="utf-8"))["result_sha256"],
            report["result_sha256"],
        )
        changed_audio_report = evaluate_shadow_association(
            candidate=candidate,
            candidate_audio_path=Path("candidate.wav"),
            candidate_audio_sha256="corrected-candidate-audio",
            candidate_normalized_names=("alice example",),
            profiles=profiles,
            compare=compare,
            policy_spec=self._policy_spec(),
            model_fingerprint="model",
        )
        changed_audio_destination = write_shadow_association(
            self.root / "runs", changed_audio_report
        )
        self.assertNotEqual(
            changed_audio_report["input_fingerprint"], report["input_fingerprint"]
        )
        self.assertNotEqual(changed_audio_destination, destination)
        self.assertTrue(destination.exists())

        changed_readiness = replace(
            readiness[0],
            automatic_profile_ready=False,
            automatic_blockers=("reviewed_same_graph_contains_bridge",),
        )
        changed_readiness_report = evaluate_shadow_association(
            candidate=candidate,
            candidate_audio_path=Path("candidate.wav"),
            candidate_audio_sha256="candidate-audio",
            candidate_normalized_names=("alice example",),
            profiles=(
                (changed_readiness, profiles[0][1]),
                profiles[1],
            ),
            compare=compare,
            policy_spec=self._policy_spec(),
            model_fingerprint="model",
        )
        self.assertNotEqual(
            changed_readiness_report["input_fingerprint"],
            report["input_fingerprint"],
        )
        changed_readiness_destination = write_shadow_association(
            self.root / "runs",
            changed_readiness_report,
        )
        self.assertNotEqual(changed_readiness_destination, destination)

        changed_constraint_report = evaluate_shadow_association(
            candidate=candidate,
            candidate_audio_path=Path("candidate.wav"),
            candidate_audio_sha256="candidate-audio",
            candidate_normalized_names=("alice example",),
            profiles=profiles,
            compare=compare,
            policy_spec=self._policy_spec(),
            model_fingerprint="model",
            reviewed_difference_pairs=((candidate.id, matching[0].id),),
        )
        self.assertNotEqual(
            changed_constraint_report["input_fingerprint"],
            report["input_fingerprint"],
        )

        changed_attribution_report = evaluate_shadow_association(
            candidate=candidate,
            candidate_audio_path=Path("candidate.wav"),
            candidate_audio_sha256="candidate-audio",
            candidate_normalized_names=("alice example",),
            profiles=(
                (
                    replace(
                        readiness[0],
                        normalized_names=("changed name",),
                    ),
                    profiles[0][1],
                ),
                profiles[1],
            ),
            compare=compare,
            policy_spec=self._policy_spec(),
            model_fingerprint="model",
        )
        self.assertNotEqual(
            changed_attribution_report["input_fingerprint"],
            report["input_fingerprint"],
        )
        pending = summarize_shadow_associations(self.database, (report,))
        self.assertEqual(
            pending["validation_counts"]["pending_proposal"],
            1,
        )
        attach_reviewed_observation(
            self.database,
            profile_id=matching_profile.id,
            observation_id=candidate.id,
            reviewer="reviewer",
            reason="later reviewed match",
            review_event_key="attach-candidate",
        )
        confirmed = summarize_shadow_associations(self.database, (report,))
        self.assertEqual(
            confirmed["validation_counts"]["confirmed_proposal"],
            1,
        )
        self.assertEqual(confirmed["decided_proposal_precision"], 1.0)

    def test_conflicting_explicit_name_blocks_acoustic_proposal(self) -> None:
        candidate = self._observation("candidate")
        exemplars = [self._observation(key) for key in ("a", "b")]
        readiness = ProfileAssociationReadiness(
            profile_id=1,
            member_observation_ids=tuple(item.id for item in exemplars),
            member_fingerprints=tuple(item.input_fingerprint for item in exemplars),
            recording_count=3,
            source_count=1,
            normalized_names=("alice example",),
            shadow_ready=True,
            automatic_profile_ready=False,
            shadow_blockers=(),
            automatic_blockers=("reviewed_same_graph_contains_bridge",),
        )

        report = evaluate_shadow_association(
            candidate=candidate,
            candidate_audio_path=Path("candidate.wav"),
            candidate_audio_sha256="candidate-audio",
            candidate_normalized_names=("bob example",),
            profiles=(
                (
                    readiness,
                    tuple(
                        ShadowExemplar(
                            1,
                            observation,
                            Path(f"{observation.id}.wav"),
                            f"audio-{observation.input_fingerprint}",
                        )
                        for observation in exemplars
                    ),
                ),
            ),
            compare=lambda *_args: {
                "outcome": "same_speaker",
                "reason": "test",
            },
            policy_spec=self._policy_spec(),
            model_fingerprint="model",
        )

        self.assertEqual(report["outcome"], "conflicting_attribution")
        self.assertIsNone(report["proposed_profile_id"])

    def test_experimental_policy_is_accepted_only_for_shadow_use(self) -> None:
        path = self.root / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "review_status": "experimental_candidate",
                    "registry_mutation_allowed": False,
                    "policy": {
                        "version": "candidate",
                        "min_valid_spans": 2,
                        "min_within_median": 0.7,
                        "same_min_cross_p10": 0.6,
                        "same_min_cross_median": 0.7,
                        "different_max_cross_p90": 0.3,
                    },
                }
            ),
            encoding="utf-8",
        )

        policy = load_shadow_policy(path)

        self.assertEqual(policy.review_status, "experimental_candidate")
        self.assertFalse(policy.automatic_use_allowed)
        self.assertEqual(policy.policy.version, "candidate")


if __name__ == "__main__":
    unittest.main()
