from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import (
    SourceType,
    TranscriptSegmentLabel,
    TranscriptSourceKind,
    VideoStatus,
)
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedSpeakerEvidence,
)
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    DecisionPolicy,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    DiscoveryCandidate,
    DiscoverySignature,
    NominatedPair,
    evaluate_shadow_profile_discovery,
    write_shadow_profile_discovery,
)
from pastor_transcript_extractor.speaker_profile_promotion_typesafe import (
    PromotionProbabilityPolicy,
    TypeSafeSdkPromotionProvider,
    TypeSafePromotionJudgment,
    build_promotion_evidence,
    build_promotion_groupings,
    evaluate_profile_promotions,
)
from pastor_transcript_extractor.speaker_profile_promotion import (
    apply_discovery_promotions,
    plan_discovery_promotions,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    ShadowPolicySpec,
    assess_profile_association_readiness,
)
from pastor_transcript_extractor.storage import Database


class FakeProvider:
    def __init__(self, probability: float = 0.9, *, fail: bool = False) -> None:
        self.model = "jev-test"
        self.model_digest = "jev-test-digest"
        self.probability = probability
        self.fail = fail
        self.calls = 0

    def assess(self, state):
        self.calls += 1
        if self.fail:
            raise RuntimeError("service unavailable")
        return TypeSafePromotionJudgment(
            probability=self.probability,
            resolved_model_id=self.model_digest,
            input_tokens=100,
            output_tokens=1,
        )


class SpeakerProfilePromotionTypeSafeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = build_paths(self.root / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.source = self.database.add_source(
            "https://www.youtube.com/@probability-promotion",
            SourceType.CHANNEL,
            pastor_id=None,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _signature(self, key: str, centroid: tuple[float, ...]):
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=None,
            youtube_video_id=f"video-{key}",
            title=f"Sermon {key}",
            url=f"https://youtube.test/{key}",
            status=VideoStatus.EXTRACTED,
        )
        extraction = self.database.add_extraction_result(
            video_id=video.id,
            version=1,
            proposed_text_path=f"{key}.md",
            proposed_json_path=f"{key}.json",
        )
        observation = self.database.add_speaker_observation(
            video_id=video.id,
            extraction_result_id=extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="unknown",
            start_seconds=10.0,
            end_seconds=100.0,
            artifact_path=f"{key}.speaker.json",
            content_sha256=f"content-{key}",
            extractor_version="speaker_evidence_v1",
            input_fingerprint=f"fingerprint-{key}",
        )
        return DiscoverySignature(
            candidate=DiscoveryCandidate(
                observation=observation,
                audio_path=Path(f"{key}.wav"),
                source_id=self.source.id,
            ),
            centroid=centroid,
            span_evidence=(),
            consistency_metrics={"weakest_clip_coherence": 0.9},
            signature_sha256=f"signature-{key}",
        )

    def _policy(self) -> ShadowPolicySpec:
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

    def _two_member_report(self) -> tuple[Path, tuple[DiscoverySignature, ...]]:
        signatures = (
            self._signature("a", (1.0, 0.0)),
            self._signature("b", (0.99, 0.01)),
        )
        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=(
                NominatedPair(
                    signatures[0],
                    signatures[1],
                    centroid_similarity=0.99,
                ),
            ),
            compare=lambda *_args: {
                "outcome": "same_speaker",
                "reason": "test_same",
            },
            policy_spec=self._policy(),
            model_fingerprint="speaker-model",
        )
        return (
            write_shadow_profile_discovery(self.root / "discoveries", report),
            signatures,
        )

    def test_two_member_component_gets_probability_and_reuses_cache(self) -> None:
        report_path, _signatures = self._two_member_report()
        provider = FakeProvider(0.9)
        output_root = self.root / "judgments"
        progress_events = []

        first = evaluate_profile_promotions(
            self.database,
            report_path,
            output_root,
            provider,
            progress_callback=lambda completed, total, grouping, status: (
                progress_events.append(
                    (completed, total, grouping.group_id, status)
                )
            ),
        )
        second = evaluate_profile_promotions(
            self.database,
            report_path,
            output_root,
            provider,
        )

        self.assertEqual(1, provider.calls)
        self.assertEqual(1, first.model_calls)
        self.assertEqual(0, first.cache_hits)
        self.assertEqual(0, second.model_calls)
        self.assertEqual(1, second.cache_hits)
        self.assertFalse(first.assessments[0].cache_hit)
        self.assertTrue(second.assessments[0].cache_hit)
        self.assertTrue(second.assessments[0].qualifies)
        self.assertEqual("checking_cache", progress_events[0][3])
        self.assertEqual("calling_jev", progress_events[1][3])
        self.assertEqual((1, 1, "evaluated"), (
            progress_events[-1][0],
            progress_events[-1][1],
            progress_events[-1][3],
        ))

    def test_default_policy_is_approved_cost_three_policy(self) -> None:
        policy = PromotionProbabilityPolicy()

        self.assertEqual("profile-promotion-utility-v2", policy.version)
        self.assertEqual(3.0, policy.contaminated_profile_cost)
        self.assertTrue(policy.automatic_use_allowed)
        self.assertGreater(policy.utility(0.76), 0.0)
        self.assertEqual(0.0, policy.utility(0.75))

    def test_run_scoped_context_preserves_public_evidence_identity(self) -> None:
        report_path, _signatures = self._two_member_report()
        provider = FakeProvider(0.9)
        evaluation = evaluate_profile_promotions(
            self.database,
            report_path,
            self.root / "judgments",
            provider,
        )
        report = __import__(
            "pastor_transcript_extractor.speaker_profile_discovery",
            fromlist=["load_verified_shadow_profile_discovery"],
        ).load_verified_shadow_profile_discovery(report_path)
        rebuilt = build_promotion_evidence(
            self.database,
            report,
            evaluation.assessments[0].evidence.grouping,
            provider,
        )

        self.assertEqual(
            evaluation.assessments[0].evidence.input_fingerprint,
            rebuilt.input_fingerprint,
        )
        self.assertEqual(evaluation.assessments[0].evidence.state, rebuilt.state)

    def test_sdk_adapter_reads_current_nouls_shape(self) -> None:
        class FakeClient:
            def system_one(self, *_args, **_kwargs):
                return SimpleNamespace(
                    nouls={
                        "same_principal_speaker": SimpleNamespace(noul=0.87)
                    },
                    model="jev-resolved",
                    usage=SimpleNamespace(input_tokens=21, output_tokens=1),
                )

        provider = object.__new__(TypeSafeSdkPromotionProvider)
        provider.model = "jev-requested"
        provider.model_digest = "jev-requested"
        provider.timeout_seconds = 45.0
        provider._Noul = lambda **kwargs: kwargs
        provider._client = FakeClient()

        judgment = provider.assess({"candidate_group": {"observation_ids": [1, 2]}})

        self.assertEqual(0.87, judgment.probability)
        self.assertEqual("jev-resolved", judgment.resolved_model_id)
        self.assertEqual(21, judgment.input_tokens)

    def test_source_level_name_claim_is_not_observation_evidence(self) -> None:
        report_path, signatures = self._two_member_report()
        self.database.add_speaker_name_claim(
            video_id=signatures[0].candidate.observation.video_id,
            observation_id=None,
            display_name="Source Level Name",
            normalized_name="source level name",
            claim_kind="source_attribution",
            channel="metadata",
            explicit_speaker_attribution=False,
            correlation_group_id="source-level",
            provenance_json="{}",
            artifact_path="source-level.json",
            claim_fingerprint="source-level-name-claim",
            extractor_version="test",
        )

        result = evaluate_profile_promotions(
            self.database,
            report_path,
            self.root / "judgments",
            FakeProvider(0.9),
        )

        self.assertEqual(1, len(result.assessments))
        for observation in result.assessments[0].evidence.state["observations"]:
            self.assertEqual([], observation["explicit_attributions"])

    def test_policy_change_reuses_raw_probability(self) -> None:
        report_path, _signatures = self._two_member_report()
        provider = FakeProvider(0.75)
        output_root = self.root / "judgments"

        conservative = evaluate_profile_promotions(
            self.database,
            report_path,
            output_root,
            provider,
            policy=PromotionProbabilityPolicy(contaminated_profile_cost=4.0),
        )
        permissive = evaluate_profile_promotions(
            self.database,
            report_path,
            output_root,
            provider,
            policy=PromotionProbabilityPolicy(contaminated_profile_cost=1.0),
        )

        self.assertEqual(1, provider.calls)
        self.assertFalse(conservative.assessments[0].qualifies)
        self.assertTrue(permissive.assessments[0].qualifies)
        self.assertEqual(1, permissive.cache_hits)

    def test_changed_jev_visible_evidence_creates_a_new_cache_entry(self) -> None:
        report_path, signatures = self._two_member_report()
        provider = FakeProvider(0.9)
        output_root = self.root / "judgments"
        first = evaluate_profile_promotions(
            self.database,
            report_path,
            output_root,
            provider,
        )

        observation = signatures[0].candidate.observation
        artifact = self.database.add_transcript_artifact(
            observation.video_id,
            TranscriptSourceKind.CAPTIONS,
            audio_path=None,
        )
        self.database.add_transcript_segment(
            observation.video_id,
            artifact.id,
            20.0,
            30.0,
            "My name is Pastor Evidence Change and I am preaching today.",
            TranscriptSegmentLabel.SERMON,
        )
        second = evaluate_profile_promotions(
            self.database,
            report_path,
            output_root,
            provider,
        )

        self.assertEqual(2, provider.calls)
        self.assertNotEqual(
            first.assessments[0].evidence.input_fingerprint,
            second.assessments[0].evidence.input_fingerprint,
        )
        self.assertNotEqual(
            first.assessments[0].artifact_path,
            second.assessments[0].artifact_path,
        )

    def test_tampered_cache_fails_closed_without_another_model_call(self) -> None:
        report_path, _signatures = self._two_member_report()
        provider = FakeProvider(0.9)
        first = evaluate_profile_promotions(
            self.database,
            report_path,
            self.root / "judgments",
            provider,
        )
        artifact_path = first.assessments[0].artifact_path
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        payload["probability"] = 0.01
        artifact_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "invalid or has been tampered"):
            evaluate_profile_promotions(
                self.database,
                report_path,
                self.root / "judgments",
                provider,
            )

        self.assertEqual(1, provider.calls)

    def test_failure_is_cached_without_repeat_call(self) -> None:
        report_path, _signatures = self._two_member_report()
        provider = FakeProvider(fail=True)
        output_root = self.root / "judgments"

        first = evaluate_profile_promotions(
            self.database,
            report_path,
            output_root,
            provider,
        )
        second = evaluate_profile_promotions(
            self.database,
            report_path,
            output_root,
            provider,
        )

        self.assertEqual(1, provider.calls)
        self.assertEqual(1, first.live_failures)
        self.assertEqual(1, second.cached_failures)
        self.assertEqual(0, second.model_calls)
        self.assertEqual("RuntimeError", second.assessments[0].error_type)

    def test_reviewed_difference_excludes_group_before_model_call(self) -> None:
        report_path, signatures = self._two_member_report()
        left, right = (item.candidate.observation for item in signatures)
        self.database.add_speaker_observation_difference_event(
            observation_a_id=left.id,
            observation_b_id=right.id,
            action="assert",
            reviewer="reviewer",
            reason="reviewed different",
            event_fingerprint="different-a-b",
        )
        report = __import__(
            "pastor_transcript_extractor.speaker_profile_discovery",
            fromlist=["load_verified_shadow_profile_discovery"],
        ).load_verified_shadow_profile_discovery(report_path)

        self.assertEqual((), build_promotion_groupings(self.database, report))

    def test_probability_candidate_applies_with_provenance_and_stays_blocked(
        self,
    ) -> None:
        report_path, _signatures = self._two_member_report()
        provider = FakeProvider(0.9)
        policy = PromotionProbabilityPolicy(
            version="test-probability-policy",
            contaminated_profile_cost=4.0,
            automatic_use_allowed=True,
        )
        evaluation = evaluate_profile_promotions(
            self.database,
            report_path,
            self.root / "judgments",
            provider,
            policy=policy,
        )
        plan = plan_discovery_promotions(
            self.database,
            report_path,
            probability_assessments=evaluation.assessments,
            probability_policy_version=policy.version,
        )

        self.assertEqual(1, len(plan.candidates))
        self.assertEqual("jev_probability", plan.candidates[0].promotion_basis)
        profile_id = apply_discovery_promotions(self.database, plan)[0]
        promotion = self.database.get_speaker_profile_discovery_promotion(profile_id)
        self.assertIsNotNone(promotion)
        assert promotion is not None
        self.assertEqual("jev_probability", promotion["promotion_basis"])
        self.assertEqual(0.9, promotion["promotion_probability"])
        self.assertEqual(
            evaluation.assessments[0].result_sha256,
            promotion["promotion_judgment_sha256"],
        )

        evidence = ReviewedSpeakerEvidence(
            qualifications={},
            qualification_conflicts={},
            pair_relations={},
            pair_conflicts={},
            review_event_count=0,
        )
        readiness = assess_profile_association_readiness(
            self.database,
            evidence,
        )[0]
        self.assertFalse(readiness.automatic_profile_ready)
        self.assertIn("discovery_candidate_unconfirmed", readiness.automatic_blockers)

        replay_assessments = evaluate_profile_promotions(
            self.database,
            report_path,
            self.root / "judgments",
            provider,
            policy=policy,
        ).assessments
        replay_plan = plan_discovery_promotions(
            self.database,
            report_path,
            probability_assessments=replay_assessments,
            probability_policy_version="new-utility-policy-with-same-judgment",
        )
        self.assertEqual((profile_id,), apply_discovery_promotions(self.database, replay_plan))
        self.assertEqual(1, provider.calls)
        replayed_promotion = self.database.get_speaker_profile_discovery_promotion(
            profile_id
        )
        assert replayed_promotion is not None
        self.assertEqual(
            "test-probability-policy",
            replayed_promotion["probability_policy_version"],
        )


if __name__ == "__main__":
    unittest.main()
