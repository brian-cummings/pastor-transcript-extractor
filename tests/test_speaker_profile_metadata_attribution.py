from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.local_llm import LocalLlmResponse
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
                "proposed_name": "Curt DeWitt",
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
            self.root / "failed-closed",
            client,
            model_digest="digest-1",
        )

        self.assertEqual(0, run.insufficient_evidence)
        self.assertEqual(1, run.failed)
        self.assertEqual((), run.results)

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
