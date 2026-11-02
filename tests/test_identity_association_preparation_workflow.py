from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from pastor_transcript_extractor.workflows.identity import association_preparation
from pastor_transcript_extractor.workflows.identity.association_preparation import (
    TranscriptGroundedSpanProvider,
    prepare_association_exemplars,
)
from pastor_transcript_extractor.identity_exemplar_preparation import ExemplarPreparationStateCache
from pastor_transcript_extractor.identity_prepared_profiles import PreparedProfileCache
from pastor_transcript_extractor.models import SpeakerObservation
from pastor_transcript_extractor.speaker_pair_diagnostics import SpanSpec
from pastor_transcript_extractor.speaker_shadow_association import (
    ProfileAssociationReadiness, evaluate_shadow_association, load_shadow_policy,
    select_staged_association_profiles,
)


class IdentityAssociationPreparationWorkflowTests(unittest.TestCase):
    def test_span_provider_returns_transcript_candidates_in_plan_only_mode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "transcript.json"
            transcript.write_text("{}", encoding="utf-8")
            database = SimpleNamespace(
                get_extraction_result=lambda _id: SimpleNamespace(
                    proposed_json_path=str(transcript)
                )
            )
            activity_cache = Mock()
            with patch.object(
                association_preparation,
                "select_transcript_grounded_span_candidates",
                return_value=("candidate",),
            ):
                provider = TranscriptGroundedSpanProvider(
                    database,
                    plan_only=True,
                    span_cache=Mock(),
                    activity_selection_cache=activity_cache,
                    embedding_cache=None,
                    backend=None,
                    policy_spec=SimpleNamespace(policy=object()),
                )
                spans, selection = provider(
                    7,
                    SimpleNamespace(
                        extraction_result_id=5,
                        input_fingerprint="fingerprint",
                    ),
                    Path("audio.wav"),
                    "audio-sha",
                )

        self.assertEqual(("candidate",), spans)
        self.assertIsNone(selection)
        activity_cache.get_or_prepare.assert_not_called()

    def test_span_provider_records_coherent_qualified_spans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "transcript.json"
            transcript.write_text("{}", encoding="utf-8")
            database = SimpleNamespace(
                get_extraction_result=lambda _id: SimpleNamespace(
                    proposed_json_path=str(transcript)
                )
            )
            qualified_span = SimpleNamespace(
                start_seconds=1.0, end_seconds=2.0
            )
            activity_cache = Mock()
            activity_cache.get_or_prepare.return_value = SimpleNamespace(
                span_specs=(qualified_span,),
                selection={"selected": True},
            )
            observation = SimpleNamespace(
                extraction_result_id=5,
                input_fingerprint="fingerprint",
            )
            with patch.object(
                association_preparation,
                "select_transcript_grounded_span_candidates",
                return_value=("candidate",),
            ):
                provider = TranscriptGroundedSpanProvider(
                    database,
                    plan_only=False,
                    span_cache=Mock(),
                    activity_selection_cache=activity_cache,
                    embedding_cache=object(),
                    backend="default-backend",
                    policy_spec=SimpleNamespace(policy="policy"),
                )
                spans, selection = provider(
                    7,
                    observation,
                    Path("audio.wav"),
                    "audio-sha",
                    acoustic_backend="worker-backend",
                )

        self.assertEqual((qualified_span,), spans)
        self.assertEqual(
            "worker-backend",
            activity_cache.get_or_prepare.call_args.kwargs["backend"],
        )
        self.assertEqual(
            "sermon_speaker_candidate:fingerprint",
            selection["coherent_sermon_speaker_spans"][0]["speaker_key"],
        )

    def test_exemplar_preparation_verifies_media_and_admits_spans(self) -> None:
        observation = SimpleNamespace(
            id=11,
            video_id=7,
            input_fingerprint="observation-fingerprint",
            extraction_result_id=5,
        )
        media = SimpleNamespace(
            id=3,
            input_fingerprint="media-fingerprint",
            content_sha256="audio-sha",
            artifact_path="audio.wav",
        )
        eligibility = SimpleNamespace(
            eligible=True,
            observation=observation,
            media_artifact=media,
            reason_code="eligible",
        )
        profile = SimpleNamespace(
            profile_id=8,
            review_ready=True,
            automatic_profile_ready=False,
            certified_exemplar_observation_ids=(),
            member_observation_ids=(11,),
        )
        database = SimpleNamespace(
            get_speaker_observation=lambda _id: observation,
            get_latest_extraction_result_for_video=lambda _id: None,
            get_effective_observation_review_action=lambda _id: None,
        )
        state_cache = SimpleNamespace(
            evidence_fingerprint=lambda _evidence: "evidence",
        )
        span_cache = Mock()
        progress = []
        with (
            patch.object(
                association_preparation,
                "assess_automatic_speaker_observation",
                side_effect=(eligibility, eligibility),
            ) as assess,
            patch.object(
                association_preparation,
                "select_profile_exemplars",
                side_effect=lambda _profile, exemplars, **_kwargs: tuple(
                    exemplars
                ),
            ),
        ):
            result = prepare_association_exemplars(
                database,
                (profile,),
                verification_cache=object(),
                span_cache=span_cache,
                state_cache=state_cache,
                videos_by_id={7: SimpleNamespace(youtube_video_id="video-7")},
                plan_only=True,
                model_fingerprint=None,
                policy_artifact_sha256="policy-sha",
                maximum_exemplars=3,
                minimum_same_exemplars=1,
                prepare_spans=lambda *_args: (
                    ("span",),
                    {"selection": True},
                ),
                profile_progress=lambda index, total, current: progress.append(
                    (index, total, current.profile_id)
                ),
            )

        self.assertEqual(2, assess.call_count)
        self.assertFalse(assess.call_args_list[0].kwargs["verify_media"])
        self.assertTrue(assess.call_args_list[1].kwargs["verify_media"])
        span_cache.remember_verified_source.assert_called_once_with(
            Path("audio.wav"), "audio-sha"
        )
        self.assertEqual(("span",), result.span_specs_by_observation_id[11])
        self.assertEqual({"eligible": 1}, result.counts)
        self.assertEqual(1, len(result.eligible_exemplars))
        self.assertEqual(1, len(result.usable_profiles))
        self.assertEqual([(1, 1, 8)], progress)

    def test_exemplar_preparation_reuses_deterministic_failure(self) -> None:
        observation = SimpleNamespace(
            id=11,
            video_id=7,
            input_fingerprint="observation-fingerprint",
            extraction_result_id=5,
        )
        eligibility = SimpleNamespace(
            eligible=False,
            observation=observation,
            media_artifact=None,
            reason_code="media_missing",
        )
        profile = SimpleNamespace(
            profile_id=8,
            review_ready=True,
            automatic_profile_ready=False,
            certified_exemplar_observation_ids=(),
            member_observation_ids=(11,),
        )
        database = SimpleNamespace(
            get_speaker_observation=lambda _id: observation,
            get_latest_extraction_result_for_video=lambda _id: None,
            get_effective_observation_review_action=lambda _id: None,
        )
        state_cache = SimpleNamespace(
            evidence_fingerprint=lambda _evidence: "evidence",
            unchanged_deterministic_failure=lambda **_kwargs: SimpleNamespace(
                stage="media_registration",
                reason_code="media_missing",
            ),
            record=Mock(),
        )
        with (
            patch.object(
                association_preparation,
                "assess_automatic_speaker_observation",
                return_value=eligibility,
            ) as assess,
            patch.object(
                association_preparation,
                "select_profile_exemplars",
                return_value=(),
            ),
        ):
            result = prepare_association_exemplars(
                database,
                (profile,),
                verification_cache=object(),
                span_cache=Mock(),
                state_cache=state_cache,
                videos_by_id={},
                plan_only=False,
                model_fingerprint="model",
                policy_artifact_sha256="policy",
                maximum_exemplars=3,
                minimum_same_exemplars=2,
                prepare_spans=Mock(),
            )

        self.assertEqual(1, assess.call_count)
        state_cache.record.assert_not_called()
        self.assertEqual(
            {"cached:media_registration:media_missing": 1}, result.counts
        )
        self.assertEqual((), result.eligible_exemplars)


class PreparedProfileWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = PreparedProfileCache(self.root / "cache")
        self.state_cache = ExemplarPreparationStateCache(self.root / "cache")
        self.observations, self.media, self.extractions, self.videos = {}, {}, {}, {}
        self.reviews, self.failures = {}, {}
        self.verify_calls = []
        for i in range(1, 6):
            audio = self.root / f"audio-{i}.wav"
            audio.write_bytes(f"audio {i}".encode())
            transcript = self.root / f"extraction-{i}.json"
            transcript.write_text('{"speech": "original"}')
            self.observations[i] = SpeakerObservation(
                i, i, i, "sermon_speaker", "single", 0.0, 120.0,
                str(audio), f"observation-hash-{i}", "extractor-v1",
                f"observation-{i}", datetime.now(timezone.utc),
            )
            self.media[i] = SimpleNamespace(
                id=i, input_fingerprint=f"media-{i}", content_sha256=f"audio-hash-{i}",
                artifact_path=str(audio),
            )
            self.extractions[i] = SimpleNamespace(
                id=i, video_id=i, version="extractor-v1", proposed_json_path=str(transcript),
            )
            self.videos[i] = SimpleNamespace(
                id=i, source_id=1 if i < 4 else i, youtube_video_id=f"video-{i}",
            )
        self.database = SimpleNamespace(
            get_speaker_observation=self.observations.get,
            get_extraction_result=self.extractions.get,
            get_latest_extraction_result_for_video=self.extractions.get,
            get_effective_observation_review_action=self.reviews.get,
        )
        self.profile = ProfileAssociationReadiness(
            profile_id=12, member_observation_ids=(1, 2, 3, 4),
            member_fingerprints=tuple(f"observation-{i}" for i in (1, 2, 3, 4)),
            recording_count=4, source_count=2, normalized_names=(), shadow_ready=True,
            automatic_profile_ready=False, shadow_blockers=(), automatic_blockers=(),
            review_ready=True,
        )
        self.prepare_spans = Mock(side_effect=lambda _v, o, _p, _h: (
            (SpanSpec(10.0, 20.0), SpanSpec(30.0, 40.0)),
            {"selected": [o.id], "version": "selection"},
        ))
        self.span_cache = Mock()
        self.assess_patch = patch.object(
            association_preparation, "assess_automatic_speaker_observation",
            side_effect=self._assess,
        )
        self.assess_patch.start()
        self.addCleanup(self.assess_patch.stop)

    def _assess(self, _database, video_id, *, observation_id, verify_media, **_kwargs):
        if verify_media:
            self.verify_calls.append(observation_id)
        failure = self.failures.get((observation_id, verify_media))
        review = self.reviews.get(observation_id)
        reason = failure or (f"reviewed_{review}" if review not in (None, "qualified_single_speaker") else "eligible")
        return SimpleNamespace(
            eligible=reason == "eligible", observation=self.observations[observation_id],
            media_artifact=self.media[video_id] if reason == "eligible" else None,
            reason_code=reason,
        )

    def _prepare(self, *, profile=None, cache=True, **overrides):
        kwargs = dict(
            verification_cache=Mock(), span_cache=self.span_cache,
            state_cache=self.state_cache, videos_by_id=self.videos,
            plan_only=False, model_fingerprint="model-v1", policy_artifact_sha256="policy-v1",
            maximum_exemplars=3, minimum_same_exemplars=2,
            prepare_spans=self.prepare_spans, profile_cache=self.cache if cache else None,
        )
        kwargs.update(overrides)
        return prepare_association_exemplars(self.database, (profile or self.profile,), **kwargs)

    def _assert_same_evidence(self, expected, actual):
        for field in ("eligible_exemplars", "usable_profiles", "span_specs_by_observation_id",
                      "span_selections_by_observation_id", "counts", "counts_by_profile"):
            self.assertEqual(getattr(expected, field), getattr(actual, field), field)

    def test_warm_profile_replays_identical_evidence_and_still_verifies_every_member(self):
        baseline = self._prepare(cache=False)
        cold = self._prepare()
        self._assert_same_evidence(baseline, cold)
        self.assertEqual([1, 4, 2], [e.observation.id for e in cold.usable_profiles[0][1]])
        self.prepare_spans.reset_mock()
        self.verify_calls.clear()
        with patch.object(self.state_cache, "record", wraps=self.state_cache.record) as record:
            warm = self._prepare()
        self._assert_same_evidence(cold, warm)
        self.prepare_spans.assert_not_called()
        record.assert_not_called()
        self.assertEqual([1, 2, 3, 4], self.verify_calls)
        self.assertEqual({"profiles_reused": 1, "profiles_rebuilt": 0,
                          "members_reused": 4, "members_prepared": 0}, warm.preparation_cache_counts)

    def test_member_growth_and_name_or_redirect_changes_reuse_compatible_successes(self):
        self._prepare()
        self.prepare_spans.reset_mock()
        grown = replace(self.profile, member_observation_ids=(1, 2, 3, 4, 5),
                        member_fingerprints=tuple(f"observation-{i}" for i in range(1, 6)),
                        recording_count=5, source_count=3)
        result = self._prepare(profile=grown)
        self.assertEqual(1, self.prepare_spans.call_count)
        self.assertEqual(5, self.prepare_spans.call_args.args[1].id)
        self.assertEqual(4, result.preparation_cache_counts["members_reused"])
        self.prepare_spans.reset_mock()
        renamed = replace(grown, normalized_names=("alice",), profile_id=99)
        renamed_result = self._prepare(profile=renamed)
        self.prepare_spans.assert_not_called()
        self.assertEqual(1, renamed_result.preparation_cache_counts["profiles_rebuilt"])
        self.assertTrue(all(e.profile_id == 99 for e in renamed_result.eligible_exemplars))
        self._assert_same_evidence(self._prepare(profile=renamed, cache=False), renamed_result)

    def test_changed_member_transcript_rebuilds_only_that_member(self):
        self._prepare()
        self.prepare_spans.reset_mock()
        Path(self.extractions[2].proposed_json_path).write_text('{"speech": "changed contents"}')
        result = self._prepare()
        self.assertEqual(1, self.prepare_spans.call_count)
        self.assertEqual(2, self.prepare_spans.call_args.args[1].id)
        self.assertEqual(3, result.preparation_cache_counts["members_reused"])

    def test_source_and_certified_subset_changes_refresh_selection(self):
        self._prepare()
        self.prepare_spans.reset_mock()
        self.videos[3].source_id = 3
        source_changed = self._prepare()
        self.prepare_spans.assert_not_called()
        self.assertEqual([1, 3, 4], [e.observation.id for e in source_changed.usable_profiles[0][1]])
        certified = replace(self.profile, automatic_profile_ready=True,
                            certified_exemplar_observation_ids=(2, 3, 4))
        limited = self._prepare(profile=certified)
        self.assertEqual([2, 3, 4], [e.observation.id for e in limited.eligible_exemplars])
        self.prepare_spans.assert_not_called()

    def test_review_or_media_failure_cannot_hide_behind_a_successful_snapshot(self):
        self._prepare()
        self.prepare_spans.reset_mock()
        self.reviews[1] = "multiple_speakers"
        self.failures[(2, True)] = "verified_normalized_media_unavailable"
        result = self._prepare()
        self.assertEqual([3, 4], [e.observation.id for e in result.eligible_exemplars])
        self.assertEqual(0, result.preparation_cache_counts["profiles_reused"])
        self.assertEqual(2, result.preparation_cache_counts["members_reused"])
        self.prepare_spans.assert_not_called()

    def test_warm_snapshot_does_not_skip_failed_byte_verification(self):
        self._prepare()
        self.prepare_spans.reset_mock()
        # Registered metadata remains identical; only byte verification fails.
        self.failures[(1, True)] = "verified_normalized_media_unavailable"
        result = self._prepare()
        self.assertEqual([2, 3, 4], [e.observation.id for e in result.eligible_exemplars])
        self.assertEqual(0, result.preparation_cache_counts["profiles_reused"])
        self.prepare_spans.assert_not_called()

    def test_changed_audio_model_and_policy_invalidate_acoustic_preparation(self):
        self._prepare()
        self.prepare_spans.reset_mock()
        self.media[2].content_sha256 = "replacement-audio"
        result = self._prepare()
        self.assertEqual(1, self.prepare_spans.call_count)
        self.assertEqual(2, self.prepare_spans.call_args.args[1].id)
        self.assertEqual(1, result.preparation_cache_counts["members_prepared"])
        self.prepare_spans.reset_mock()
        self._prepare(model_fingerprint="model-v2")
        self.assertEqual(4, self.prepare_spans.call_count)
        self.prepare_spans.reset_mock()
        self._prepare(policy_artifact_sha256="policy-v2")
        self.assertEqual(4, self.prepare_spans.call_count)

    def test_old_member_keeps_its_own_extraction_after_newer_extraction_arrives(self):
        self._prepare()
        self.prepare_spans.reset_mock()
        self.database.get_latest_extraction_result_for_video = lambda i: SimpleNamespace(
            id=i + 100, version="newer-extractor", proposed_json_path="other-file.json",
        )
        result = self._prepare()
        self.prepare_spans.assert_not_called()
        self.assertEqual(4, result.preparation_cache_counts["members_reused"])
        self.assertEqual(1, result.preparation_cache_counts["profiles_rebuilt"])

    def test_old_success_cannot_bypass_a_later_deterministic_failure(self):
        self._prepare()
        self.failures[(1, True)] = "verified_normalized_media_unavailable"
        self._prepare()
        self.assertEqual("blocked", self.state_cache.latest_for_observation(
            profile_id=12, observation_fingerprint="observation-1",
        ).outcome)
        self.failures.clear()
        self.prepare_spans.reset_mock()
        still_blocked = self._prepare()
        self.prepare_spans.assert_not_called()
        self.assertEqual(1, still_blocked.preparation_cache_counts["profiles_rebuilt"])
        self.assertNotIn(1, [e.observation.id for e in still_blocked.eligible_exemplars])
        self.assertEqual("blocked", self.state_cache.latest_for_observation(
            profile_id=12, observation_fingerprint="observation-1",
        ).outcome)
        # Normal repair policy permits retry only after evidence changes.
        self.media[1].input_fingerprint = "repaired-registration"
        repaired = self._prepare()
        self.assertEqual(1, self.prepare_spans.call_count)
        self.assertEqual(1, self.prepare_spans.call_args.args[1].id)
        self.assertEqual(4, len(repaired.eligible_exemplars))
        self.assertEqual("eligible", self.state_cache.latest_for_observation(
            profile_id=12, observation_fingerprint="observation-1",
        ).outcome)

    def test_corrupt_profile_and_member_payloads_rebuild_without_new_authority(self):
        self._prepare()
        self.prepare_spans.reset_mock()
        for path in self.cache.root.glob("profile-*/*.json"):
            path.write_text("[]")
        for path in (self.cache.root / "members").glob("*.json"):
            path.write_text("[]")
        result = self._prepare()
        self.assertEqual(4, self.prepare_spans.call_count)
        self.assertEqual(0, result.preparation_cache_counts["profiles_reused"])

    def test_partial_profile_reuses_successes_but_retries_transient_span_failure(self):
        original = self.prepare_spans.side_effect
        def flaky(video_id, observation, audio_path, sha):
            if observation.id == 2:
                raise RuntimeError("temporary decoder failure")
            return original(video_id, observation, audio_path, sha)
        self.prepare_spans.side_effect = flaky
        first = self._prepare()
        self.prepare_spans.reset_mock()
        second = self._prepare()
        self._assert_same_evidence(first, second)
        self.assertEqual(1, self.prepare_spans.call_count)
        self.assertEqual(2, self.prepare_spans.call_args.args[1].id)
        self.assertEqual(3, second.preparation_cache_counts["members_reused"])

    def test_plan_only_does_not_replay_acoustically_qualified_spans_or_write_snapshots(self):
        self._prepare()
        before = {p: p.read_bytes() for p in self.cache.root.rglob("*.json")}
        self.prepare_spans.reset_mock()
        plan = self._prepare(plan_only=True, model_fingerprint=None)
        self.assertEqual(4, self.prepare_spans.call_count)
        self.assertEqual({"profiles_not_checked_plan_only": 1, "profile_snapshots_present": 1},
                         plan.preparation_cache_counts)
        self.assertEqual(before, {p: p.read_bytes() for p in self.cache.root.rglob("*.json")})

    def test_same_routing_and_decisions_for_cold_and_warm_profiles(self):
        frozen_clock = patch("pastor_transcript_extractor.speaker_shadow_association.datetime")
        clock = frozen_clock.start()
        self.addCleanup(frozen_clock.stop)
        clock.now.return_value = datetime(2026, 11, 2, tzinfo=timezone.utc)
        named = replace(self.profile, normalized_names=("alice",))
        cold = self._prepare(profile=named)
        warm = self._prepare(profile=named)
        policy = load_shadow_policy(Path("evaluation/speaker-pairs/policies/campplus-development-candidate-v1.json"))
        candidate = replace(self.observations[5], id=100, input_fingerprint="candidate")
        observed_outcomes = set()
        for outcome in ("same_speaker", "different_speaker", "insufficient_evidence", "analysis_failed"):
            for names in ((), ("conflicting-name",)):
                for differences in ((), ((100, 1),)):
                    results = []
                    for prepared in (cold, warm):
                        routing = select_staged_association_profiles(
                            prepared.usable_profiles, candidate_source_id=5,
                            candidate_normalized_names=names,
                            source_id_by_video_id={i: v.source_id for i, v in self.videos.items()},
                            candidate_centroid=(1.0, 0.0),
                            exemplar_centroids={i: (1.0, 0.0) for i in self.observations},
                        )
                        report = evaluate_shadow_association(
                            candidate=candidate, candidate_audio_path=Path("candidate.wav"),
                            candidate_audio_sha256="candidate-sha", candidate_normalized_names=names,
                            profiles=routing.profiles, compare=lambda *_: {"outcome": outcome},
                            policy_spec=policy, model_fingerprint="model-v1",
                            reviewed_difference_pairs=differences,
                            span_selection={"exemplars": dict(prepared.span_selections_by_observation_id)},
                        )
                        results.append((routing, report))
                        observed_outcomes.add(report["outcome"])
                    self.assertEqual(results[0], results[1])
        self.assertTrue({"proposed_match", "no_match", "conflicting_attribution",
                         "insufficient_evidence", "analysis_failed"}.issubset(observed_outcomes))
        ambiguous_reports = []
        for prepared in (cold, warm):
            profile, selected = prepared.usable_profiles[0]
            alternatives = (
                (profile, selected),
                (replace(profile, profile_id=13), tuple(replace(e, profile_id=13) for e in selected)),
            )
            report = evaluate_shadow_association(
                candidate=candidate, candidate_audio_path=Path("candidate.wav"),
                candidate_audio_sha256="candidate-sha", candidate_normalized_names=(),
                profiles=alternatives, compare=lambda *_: {"outcome": "same_speaker"},
                policy_spec=policy, model_fingerprint="model-v1",
            )
            self.assertEqual("ambiguous", report["outcome"])
            self.assertFalse(report["registry_mutation_allowed"])
            self.assertFalse(report["automatic_assignment_allowed"])
            ambiguous_reports.append(report)
        self.assertEqual(*ambiguous_reports)

    def test_unreviewed_or_missing_member_does_not_acquire_cached_membership(self):
        self._prepare()
        self.prepare_spans.reset_mock()
        reduced = replace(self.profile, member_observation_ids=(2, 3, 4),
                          member_fingerprints=("observation-2", "observation-3", "observation-4"))
        result = self._prepare(profile=reduced)
        self.assertNotIn(1, [e.observation.id for e in result.eligible_exemplars])
        self.prepare_spans.assert_not_called()
        del self.observations[2]
        missing = self._prepare(profile=reduced)
        self.assertEqual([3, 4], [e.observation.id for e in missing.eligible_exemplars])
        held = self._prepare(profile=replace(self.profile, review_ready=False))
        self.assertEqual((), held.eligible_exemplars)


if __name__ == "__main__":
    unittest.main()
