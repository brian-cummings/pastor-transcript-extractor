from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from pastor_transcript_extractor.workflows.identity import association_preparation
from pastor_transcript_extractor.workflows.identity.association_preparation import (
    TranscriptGroundedSpanProvider,
    prepare_association_exemplars,
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


if __name__ == "__main__":
    unittest.main()
