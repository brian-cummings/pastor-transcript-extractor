from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_profile_metadata_attribution_typesafe import (
    ProfileNameCandidate,
    TypeSafeNameJudgment,
    _aggregate,
    run_typesafe_profile_metadata_attribution,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
)
from pastor_transcript_extractor.storage import Database


def occurrence(
    occurrence_id: str,
    name: str,
    video_id: str,
) -> ProfileNameCandidate:
    text = f"Message by Pastor {name}"
    start = text.index(name)
    return ProfileNameCandidate(
        occurrence_id,
        name,
        " ".join(part.strip(".").lower() for part in name.split()),
        video_id,
        "video.title",
        text,
        start,
        start + len(name),
        text,
    )


def judgment(
    choice: str,
    *,
    confidence: float = 0.95,
    speaker_probability: float | None = None,
) -> TypeSafeNameJudgment:
    speaker = (
        speaker_probability
        if speaker_probability is not None
        else 0.95
        if choice == "sermon_speaker"
        else 0.02
    )
    remainder = 1.0 - speaker
    probabilities = {
        "sermon_speaker": speaker,
        "other_person": remainder if choice == "other_person" else 0.0,
        "ambiguous": remainder if choice != "other_person" else 0.0,
    }
    return TypeSafeNameJudgment(choice, probabilities, confidence, "jev-1.13.0")


class AggregationPolicyTests(unittest.TestCase):
    def test_two_independent_speaker_credits_propose_exact_name(self) -> None:
        items = (
            occurrence("a", "Curt DeWitt", "v1"),
            occurrence("b", "Curt DeWitt", "v2"),
        )
        result, _ = _aggregate(
            items,
            {"a": judgment("sermon_speaker"), "b": judgment("sermon_speaker")},
            confidence_threshold=0.7,
            speaker_probability_threshold=0.7,
            model_failed=False,
        )
        self.assertEqual("propose_name", result["decision"])
        self.assertEqual("Curt DeWitt", result["proposed_name"])
        self.assertEqual(2, result["supporting_recording_count"])

    def test_repeated_non_speaker_mentions_are_not_support(self) -> None:
        items = (
            occurrence("a", "Curt DeWitt", "v1"),
            occurrence("b", "Curt DeWitt", "v2"),
        )
        result, _ = _aggregate(
            items,
            {"a": judgment("other_person"), "b": judgment("other_person")},
            confidence_threshold=0.7,
            speaker_probability_threshold=0.7,
            model_failed=False,
        )
        self.assertEqual("insufficient_evidence", result["decision"])
        self.assertEqual("no_speaker_credit", result["reason_codes"][0])

    def test_competing_grounded_candidates_conflict(self) -> None:
        items = (
            occurrence("a", "Curt DeWitt", "v1"),
            occurrence("b", "Curt DeWitt", "v2"),
            occurrence("c", "Jane Smith", "v1"),
            occurrence("d", "Jane Smith", "v2"),
        )
        result, _ = _aggregate(
            items,
            {
                item.occurrence_id: judgment("sermon_speaker")
                for item in items
            },
            confidence_threshold=0.7,
            speaker_probability_threshold=0.7,
            model_failed=False,
        )
        self.assertEqual("conflicting_evidence", result["decision"])
        self.assertEqual({"Curt DeWitt", "Jane Smith"}, set(result["conflicting_names"]))

    def test_one_supporting_recording_is_insufficient_profile_77_shape(self) -> None:
        item = occurrence("a", "Curt DeWitt", "v1")
        result, _ = _aggregate(
            (item,),
            {"a": judgment("sermon_speaker")},
            confidence_threshold=0.7,
            speaker_probability_threshold=0.7,
            model_failed=False,
        )
        self.assertEqual("insufficient_evidence", result["decision"])
        self.assertEqual("single_recording_only", result["reason_codes"][0])

    def test_low_confidence_choice_abstains(self) -> None:
        items = (
            occurrence("a", "Curt DeWitt", "v1"),
            occurrence("b", "Curt DeWitt", "v2"),
        )
        answers = {
            item.occurrence_id: judgment("sermon_speaker", confidence=0.4)
            for item in items
        }
        result, abstentions = _aggregate(
            items,
            answers,
            confidence_threshold=0.7,
            speaker_probability_threshold=0.7,
            model_failed=False,
        )
        self.assertEqual("insufficient_evidence", result["decision"])
        self.assertEqual(2, abstentions)

    def test_no_candidates_needs_no_model_judgment(self) -> None:
        result, abstentions = _aggregate(
            (),
            {},
            confidence_threshold=0.7,
            speaker_probability_threshold=0.7,
            model_failed=False,
        )
        self.assertEqual("no_extracted_candidates", result["reason_codes"][0])
        self.assertEqual(0, abstentions)

    def test_middle_initial_display_variants_merge(self) -> None:
        items = (
            occurrence("a", "Curt A. DeWitt", "v1"),
            occurrence("b", "Curt DeWitt", "v2"),
        )
        result, _ = _aggregate(
            items,
            {
                item.occurrence_id: judgment("sermon_speaker")
                for item in items
            },
            confidence_threshold=0.7,
            speaker_probability_threshold=0.7,
            model_failed=False,
        )
        self.assertEqual("propose_name", result["decision"])
        self.assertIn(result["proposed_name"], {"Curt A. DeWitt", "Curt DeWitt"})

    def test_provider_failure_overrides_partial_cached_support(self) -> None:
        items = (
            occurrence("a", "Curt DeWitt", "v1"),
            occurrence("b", "Curt DeWitt", "v2"),
        )
        result, _ = _aggregate(
            items,
            {
                item.occurrence_id: judgment("sermon_speaker")
                for item in items
            },
            confidence_threshold=0.7,
            speaker_probability_threshold=0.7,
            model_failed=True,
        )
        self.assertEqual("insufficient_evidence", result["decision"])
        self.assertEqual("model_unavailable", result["reason_codes"][0])


class FakeProvider:
    model = "jev-1.13.0"
    model_digest = "jev-1.13.0"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def classify(self, candidates):
        self.calls += 1
        if self.fail:
            raise RuntimeError("truncated or unavailable response")
        return {
            item.occurrence_id: judgment("sermon_speaker")
            for item in candidates
        }


class TypeSafeAttributionIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        paths = build_paths(self.root / "app")
        ensure_directories(paths)
        self.database = Database(paths.database)
        self.database.initialize()
        source = self.database.add_source(
            "https://www.youtube.com/@typesafe-metadata",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="same speaker",
            review_event_key="typesafe-profile",
        )
        titles = (
            "Message by Pastor Curt DeWitt",
            "Sermon by Pastor Curt DeWitt",
        )
        for index, title in enumerate(titles, start=1):
            video = self.database.add_video(
                source_id=source.id,
                pastor_id=None,
                youtube_video_id=f"jev-{index}",
                title=title,
                url=f"https://youtube.test/jev-{index}",
                status=VideoStatus.EXTRACTED,
            )
            extraction = self.database.add_extraction_result(
                video_id=video.id,
                version=1,
                proposed_text_path=f"jev-{index}.md",
                proposed_json_path=f"jev-{index}.json",
            )
            observation = self.database.add_speaker_observation(
                video_id=video.id,
                extraction_result_id=extraction.id,
                role="principal_speaker_candidate",
                multiplicity_state="unknown",
                start_seconds=10.0,
                end_seconds=100.0,
                artifact_path=f"jev-{index}.speaker.json",
                content_sha256=f"content-{index}",
                extractor_version="speaker_evidence_v2",
                input_fingerprint=f"fingerprint-{index}",
            )
            attach_reviewed_observation(
                self.database,
                profile_id=profile.id,
                observation_id=observation.id,
                reviewer="reviewer",
                reason="same speaker",
                review_event_key=f"attach-{index}",
            )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_cache_reuse_makes_zero_duplicate_requests(self) -> None:
        provider = FakeProvider()
        output = self.root / "attribution"
        first = run_typesafe_profile_metadata_attribution(self.database, output, provider)
        replay = run_typesafe_profile_metadata_attribution(self.database, output, provider)
        self.assertEqual(1, first.proposed)
        self.assertEqual(1, provider.calls)
        self.assertEqual(0, replay.model_calls)
        self.assertGreaterEqual(replay.cache_hits, 1)

    def test_unavailable_response_fails_closed_profile_78_shape(self) -> None:
        provider = FakeProvider(fail=True)
        run = run_typesafe_profile_metadata_attribution(
            self.database,
            self.root / "failed",
            provider,
        )
        self.assertEqual(0, run.proposed)
        self.assertEqual(1, run.insufficient_evidence)
        self.assertEqual(1, run.failed)
        self.assertEqual("model_unavailable", run.results[0].reason_codes[0])


if __name__ == "__main__":
    unittest.main()
