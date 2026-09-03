from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.local_llm import LocalLlmError, LocalLlmResponse
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_profile_attribution import (
    list_unnamed_profile_attribution_candidates,
)
from pastor_transcript_extractor.speaker_profile_metadata_attribution import (
    load_profile_metadata_attributions,
    profile_metadata_candidate_profile_ids,
    run_profile_metadata_attribution,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
)
from pastor_transcript_extractor.storage import Database


class FakeMetadataClient:
    model = "fixture-metadata:1"

    def __init__(self, content: dict[str, object]) -> None:
        self.content = content
        self.calls = 0

    def generate_json(
        self,
        prompt: str,
        schema: dict[str, object],
        *,
        max_tokens: int = 256,
    ) -> LocalLlmResponse:
        del prompt, schema, max_tokens
        self.calls += 1
        return LocalLlmResponse(
            self.content,
            json.dumps(self.content),
            self.model,
        )


class FailingMetadataClient:
    model = "fixture-metadata:1"

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, *_args, **_kwargs) -> LocalLlmResponse:
        self.calls += 1
        raise LocalLlmError("temporary outage")


class ProfileMetadataAttributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        paths = build_paths(self.root / "app")
        ensure_directories(paths)
        self.database = Database(paths.database)
        self.database.initialize()
        self.source = self.database.add_source(
            "https://www.youtube.com/@metadata-profile",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        self.profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="same speaker",
            review_event_key="metadata-profile",
        )
        self.observations = [
            self._observation(
                "curt-a",
                'Sabbath Service, "The Worthy Worm" Pastor Curt DeWitt',
            ),
            self._observation(
                "curt-b",
                'Sabbath Service, "My Journey" Pastor Curt DeWitt',
            ),
            self._observation("curt-c", "Worship Service"),
        ]
        for observation in self.observations:
            attach_reviewed_observation(
                self.database,
                profile_id=self.profile.id,
                observation_id=observation.id,
                reviewer="reviewer",
                reason="same speaker",
                review_event_key=f"attach-{observation.id}",
            )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _observation(self, key: str, title: str):
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=None,
            youtube_video_id=key,
            title=title,
            url=f"https://www.youtube.com/watch?v={key}",
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
            extractor_version="speaker_evidence_v2",
            input_fingerprint=f"fingerprint-{key}",
        )

    def test_consistent_name_is_proposed_once_and_replayed(self) -> None:
        client = FakeMetadataClient(
            {
                "decision": "propose_name",
                "proposed_name": "Pastor Curt DeWitt",
                "reason_codes": [
                    "consistent_speaker_credit",
                    "repeated_name_across_recordings",
                ],
                "evidence": [
                    {
                        "youtube_video_id": "curt-a",
                        "field_path": "video.title",
                        "exact_excerpt": "Pastor Curt DeWitt",
                    },
                    {
                        "youtube_video_id": "curt-b",
                        "field_path": "video.title",
                        "exact_excerpt": "Pastor Curt DeWitt",
                    },
                ],
                "conflicting_names": [],
            }
        )
        output = self.root / "metadata-attribution"

        first = run_profile_metadata_attribution(
            self.database,
            output,
            client,
            model_digest="digest-1",
        )
        replay = run_profile_metadata_attribution(
            self.database,
            output,
            client,
            model_digest="digest-1",
        )

        self.assertEqual(1, first.proposed)
        self.assertEqual(2, first.results[0].supporting_recording_count)
        self.assertEqual("human_confirmation_available", first.results[0].routing)
        self.assertEqual(1, client.calls)
        self.assertEqual(1, replay.cache_hits)
        self.assertEqual(0, replay.model_calls)
        attempt_path = first.results[0].artifact_path.with_suffix(
            ".attempt.json"
        )
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        self.assertEqual("validated", attempt["status"])
        self.assertEqual("propose_name", attempt["response"]["decision"])
        self.assertEqual(
            "Curt DeWitt",
            attempt["validated_result"]["proposed_name"],
        )
        loaded = load_profile_metadata_attributions(output)
        self.assertEqual(
            "Curt DeWitt",
            loaded[first.results[0].membership_fingerprint].proposed_name,
        )
        review_candidate = list_unnamed_profile_attribution_candidates(
            self.database,
            metadata_attributions=loaded,
        )[0]
        self.assertEqual(
            "Curt DeWitt",
            review_candidate.metadata_attribution.proposed_name,
        )

    def test_unverifiable_single_recording_proposal_fails_closed(self) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE videos SET title = ? WHERE id = ?",
                ("Worship Service", self.observations[1].video_id),
            )
        client = FakeMetadataClient(
            {
                "decision": "propose_name",
                "proposed_name": "Curt DeWitt",
                "reason_codes": ["consistent_speaker_credit"],
                "evidence": [
                    {
                        "youtube_video_id": "curt-a",
                        "field_path": "video.title",
                        "exact_excerpt": "Pastor Curt DeWitt",
                    }
                ],
                "conflicting_names": [],
            }
        )

        output = self.root / "failed-closed"
        run = run_profile_metadata_attribution(
            self.database,
            output,
            client,
            model_digest="digest-1",
        )
        replay = run_profile_metadata_attribution(
            self.database,
            output,
            client,
            model_digest="digest-1",
        )

        self.assertEqual(0, run.insufficient_evidence)
        self.assertEqual(1, run.failed)
        self.assertEqual((), run.results)
        self.assertEqual(1, len(run.failures))
        self.assertTrue(run.failures[0].artifact_path.is_file())
        failed_attempt = json.loads(
            run.failures[0].artifact_path.read_text(encoding="utf-8")
        )
        self.assertTrue(failed_attempt["cacheable"])
        self.assertEqual("failed", failed_attempt["status"])
        self.assertEqual("ValueError", failed_attempt["error"]["type"])
        self.assertTrue(failed_attempt["input_fields"])
        self.assertEqual(1, replay.failed)
        self.assertEqual(1, replay.cache_hits)
        self.assertEqual(0, replay.model_calls)
        self.assertEqual(1, client.calls)

    def test_non_pastor_honorific_is_preserved(self) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE videos SET title = ? WHERE id IN (?, ?)",
                (
                    "Message by Doctor Curt DeWitt",
                    self.observations[0].video_id,
                    self.observations[1].video_id,
                ),
            )
        client = FakeMetadataClient(
            {
                "decision": "propose_name",
                "proposed_name": "Doctor Curt DeWitt",
                "reason_codes": ["consistent_speaker_credit"],
                "evidence": [],
                "conflicting_names": [],
            }
        )

        run = run_profile_metadata_attribution(
            self.database,
            self.root / "doctor-honorific",
            client,
            model_digest="digest-1",
        )

        self.assertEqual(1, run.proposed)
        self.assertEqual(
            "Doctor Curt DeWitt",
            run.results[0].proposed_name,
        )
        self.assertEqual("curt dewitt", run.results[0].normalized_name)

    def test_name_is_grounded_despite_nonverbatim_excerpt_and_middle_initial(
        self,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE videos SET title = ? WHERE id IN (?, ?)",
                (
                    "Message with Pastor Curt A. DeWitt",
                    self.observations[0].video_id,
                    self.observations[1].video_id,
                ),
            )
        client = FakeMetadataClient(
            {
                "decision": "propose_name",
                "proposed_name": "Curt DeWitt",
                "reason_codes": ["consistent_speaker_credit"],
                "evidence": [
                    {
                        "youtube_video_id": "curt-a",
                        "field_path": "video.title",
                        "exact_excerpt": "Pastor Curt DeWitt",
                    }
                ],
                "conflicting_names": [],
            }
        )

        run = run_profile_metadata_attribution(
            self.database,
            self.root / "normalized-grounding",
            client,
            model_digest="digest-1",
        )

        self.assertEqual(1, run.proposed)
        self.assertEqual(0, run.failed)
        self.assertEqual(2, run.results[0].supporting_recording_count)
        self.assertTrue(
            all(
                "Curt A. DeWitt" in item.exact_excerpt
                for item in run.results[0].evidence
            )
        )

    def test_insufficient_evidence_is_cached_for_human_review(self) -> None:
        client = FakeMetadataClient(
            {
                "decision": "insufficient_evidence",
                "proposed_name": "",
                "reason_codes": ["no_speaker_credit"],
                "evidence": [],
                "conflicting_names": [],
            }
        )

        run = run_profile_metadata_attribution(
            self.database,
            self.root / "insufficient",
            client,
            model_digest="digest-1",
        )

        self.assertEqual(1, run.insufficient_evidence)
        self.assertEqual(0, run.failed)
        self.assertEqual("human_review_required", run.results[0].routing)

    def test_transient_model_failure_is_recorded_but_not_cached(self) -> None:
        client = FailingMetadataClient()
        output = self.root / "transient"

        first = run_profile_metadata_attribution(
            self.database,
            output,
            client,
            model_digest="digest-1",
        )
        replay = run_profile_metadata_attribution(
            self.database,
            output,
            client,
            model_digest="digest-1",
        )

        self.assertEqual(1, first.failed)
        self.assertEqual(1, replay.failed)
        self.assertEqual(0, replay.cache_hits)
        self.assertEqual(2, client.calls)
        attempt = json.loads(
            replay.failures[0].artifact_path.read_text(encoding="utf-8")
        )
        self.assertFalse(attempt["cacheable"])

    def test_program_name_cannot_be_proposed_as_a_person(self) -> None:
        client = FakeMetadataClient(
            {
                "decision": "propose_name",
                "proposed_name": "Sabbath Service",
                "reason_codes": ["repeated_name_across_recordings"],
                "evidence": [
                    {
                        "youtube_video_id": "curt-a",
                        "field_path": "video.title",
                        "exact_excerpt": "Sabbath Service",
                    },
                    {
                        "youtube_video_id": "curt-b",
                        "field_path": "video.title",
                        "exact_excerpt": "Sabbath Service",
                    },
                ],
                "conflicting_names": [],
            }
        )

        run = run_profile_metadata_attribution(
            self.database,
            self.root / "program-name",
            client,
            model_digest="digest-1",
        )

        self.assertEqual(1, run.failed)
        self.assertEqual(0, run.proposed)

    def test_hallucinated_conflicts_cannot_be_persisted(self) -> None:
        client = FakeMetadataClient(
            {
                "decision": "conflicting_evidence",
                "proposed_name": "",
                "reason_codes": ["multiple_candidate_names"],
                "evidence": [
                    {
                        "youtube_video_id": "curt-c",
                        "field_path": "video.title",
                        "exact_excerpt": "Worship Service",
                    }
                ],
                "conflicting_names": ["Pastor NAME", "Unknown"],
            }
        )

        run = run_profile_metadata_attribution(
            self.database,
            self.root / "hallucinated-conflict",
            client,
            model_digest="digest-1",
        )

        self.assertEqual(0, run.failed)
        self.assertEqual(0, run.conflicting_evidence)
        self.assertEqual(1, run.insufficient_evidence)
        self.assertEqual((), run.results[0].conflicting_names)

    def test_single_repeated_name_mislabeled_as_conflict_is_proposed(self) -> None:
        client = FakeMetadataClient(
            {
                "decision": "conflicting_evidence",
                "proposed_name": "",
                "reason_codes": ["multiple_candidate_names"],
                "evidence": [
                    {
                        "youtube_video_id": "curt-a",
                        "field_path": "video.title",
                        "exact_excerpt": "Pastor Curt DeWitt",
                    }
                ],
                "conflicting_names": ["Curt DeWitt", "Curt DeWitt"],
            }
        )

        run = run_profile_metadata_attribution(
            self.database,
            self.root / "single-false-conflict",
            client,
            model_digest="digest-1",
        )

        self.assertEqual(1, run.proposed)
        self.assertEqual("Curt DeWitt", run.results[0].proposed_name)
        self.assertEqual(2, run.results[0].supporting_recording_count)

    def test_repeated_program_phrases_are_not_conflicting_people(self) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE videos SET title = ? WHERE id = ?",
                (
                    "World Cups: Hurtling to the End - Last Day Events Today",
                    self.observations[0].video_id,
                ),
            )
            connection.execute(
                "UPDATE videos SET title = ? WHERE id = ?",
                (
                    "Revival: Hurtling to the End - Last Day Events Today",
                    self.observations[1].video_id,
                ),
            )
        client = FakeMetadataClient(
            {
                "decision": "conflicting_evidence",
                "proposed_name": "",
                "reason_codes": ["multiple_candidate_names"],
                "evidence": [],
                "conflicting_names": [
                    "Hurtling to the End",
                    "Last Day Events Today",
                ],
            }
        )

        run = run_profile_metadata_attribution(
            self.database,
            self.root / "program-phrase-conflict",
            client,
            model_digest="digest-1",
        )

        self.assertEqual(1, run.insufficient_evidence)
        self.assertEqual(0, run.conflicting_evidence)
        self.assertEqual((), run.results[0].conflicting_names)

    def test_existing_explicit_claim_removes_profile_from_model_queue(self) -> None:
        observation = self.observations[0]
        self.database.add_speaker_name_claim(
            video_id=observation.video_id,
            observation_id=observation.id,
            display_name="Curt DeWitt",
            normalized_name="curt dewitt",
            claim_kind="explicit_speaker_attribution",
            channel="metadata",
            explicit_speaker_attribution=True,
            correlation_group_id="curt-dewitt",
            provenance_json="{}",
            artifact_path="claim.json",
            claim_fingerprint="claim-curt-dewitt",
            extractor_version="speaker_evidence_v2",
        )

        self.assertEqual(
            (),
            profile_metadata_candidate_profile_ids(self.database),
        )


if __name__ == "__main__":
    unittest.main()
