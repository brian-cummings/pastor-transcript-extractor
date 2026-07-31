from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedSpeakerEvidence,
)
from pastor_transcript_extractor.speaker_pair_diagnostics import DecisionPolicy
from pastor_transcript_extractor.speaker_profile_discovery import (
    DiscoveryCandidate,
    DiscoverySignature,
    evaluate_shadow_profile_discovery,
    nominate_discovery_pairs,
    write_shadow_profile_discovery,
)
from pastor_transcript_extractor.speaker_profile_promotion import (
    apply_candidate_confirmations,
    apply_discovery_promotions,
    plan_candidate_confirmations,
    plan_discovery_promotions,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    SHADOW_ASSOCIATION_VERSION,
    ShadowPolicySpec,
    assess_profile_association_readiness,
)
from pastor_transcript_extractor.storage import Database


class SpeakerProfilePromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = build_paths(self.root / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.source = self.database.add_source(
            "https://www.youtube.com/@promotion",
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

    def _empty_evidence(self) -> ReviewedSpeakerEvidence:
        return ReviewedSpeakerEvidence(
            qualifications={},
            qualification_conflicts={},
            pair_relations={},
            pair_conflicts={},
            review_event_count=0,
        )

    def test_discovery_seed_is_shadow_ready_then_independent_match_confirms_it(
        self,
    ) -> None:
        observations = [self._observation(key) for key in ("a", "b", "c")]
        signatures = tuple(
            DiscoverySignature(
                candidate=DiscoveryCandidate(
                    observation=observation,
                    audio_path=Path(f"{observation.input_fingerprint}.wav"),
                    source_id=self.source.id,
                ),
                centroid=(1.0, 0.0),
                span_evidence=(),
                consistency_metrics={"weakest_clip_coherence": 0.9},
                signature_sha256=f"signature-{observation.input_fingerprint}",
            )
            for observation in observations
        )
        report = evaluate_shadow_profile_discovery(
            signatures=signatures,
            nominations=nominate_discovery_pairs(
                signatures,
                nearest_neighbors=2,
            ),
            compare=lambda *_args: {
                "outcome": "same_speaker",
                "reason": "test_same",
            },
            policy_spec=self._policy(),
            model_fingerprint="model",
        )
        report_path = write_shadow_profile_discovery(
            self.root / "discoveries",
            report,
        )

        promotion_plan = plan_discovery_promotions(
            self.database,
            report_path,
        )
        profile_id = apply_discovery_promotions(
            self.database,
            promotion_plan,
        )[0]

        readiness = assess_profile_association_readiness(
            self.database,
            self._empty_evidence(),
        )[0]
        self.assertEqual(profile_id, readiness.profile_id)
        self.assertTrue(readiness.shadow_ready)
        self.assertFalse(readiness.automatic_profile_ready)
        self.assertIn(
            "discovery_candidate_unconfirmed",
            readiness.automatic_blockers,
        )

        candidate = self._observation("d")
        association = {
            "schema_version": 1,
            "association_version": SHADOW_ASSOCIATION_VERSION,
            "artifact_kind": "speaker_profile_shadow_association",
            "shadow_mode": True,
            "registry_mutation_allowed": False,
            "automatic_assignment_allowed": False,
            "candidate": {
                "observation_id": candidate.id,
                "video_id": candidate.video_id,
                "input_fingerprint": candidate.input_fingerprint,
                "normalized_names": [],
            },
            "span_selection": {
                "version": "transcript_grounded_sermon_spans_v1",
            },
            "outcome": "proposed_match",
            "proposed_profile_id": profile_id,
            "profiles": [
                {
                    "profile_id": profile_id,
                    "meets_multi_exemplar_match": True,
                }
            ],
        }
        association["result_sha256"] = _sha256(association)
        association_path = self.root / "association.json"
        association_path.write_text(
            json.dumps(association),
            encoding="utf-8",
        )

        confirmation_plan = plan_candidate_confirmations(
            self.database,
            [association_path],
        )
        self.assertEqual(1, len(confirmation_plan.candidates))
        apply_candidate_confirmations(self.database, confirmation_plan)

        confirmed = assess_profile_association_readiness(
            self.database,
            self._empty_evidence(),
        )[0]
        self.assertTrue(confirmed.shadow_ready)
        self.assertTrue(confirmed.automatic_profile_ready)
        self.assertEqual(
            [profile_id],
            self.database.list_effective_profile_ids_for_observation(
                candidate.id
            ),
        )

    def test_tampered_discovery_artifact_is_rejected(self) -> None:
        path = self.root / "tampered.json"
        path.write_text(
            json.dumps(
                {
                    "artifact_kind": "speaker_profile_shadow_discovery",
                    "result_sha256": "0" * 64,
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "checksum"):
            plan_discovery_promotions(self.database, path)

    def test_stale_association_is_ignored_instead_of_reported_invalid(
        self,
    ) -> None:
        report = {
            "artifact_kind": "speaker_profile_shadow_association",
            "association_version": "speaker_shadow_association_v1",
            "outcome": "insufficient_evidence",
        }
        report["result_sha256"] = _sha256(report)
        path = self.root / "stale.json"
        path.write_text(json.dumps(report), encoding="utf-8")

        plan = plan_candidate_confirmations(self.database, [path])

        self.assertEqual((), plan.candidates)
        self.assertEqual((), plan.skipped)
        self.assertEqual(
            {"stale_association_version": 1},
            plan.ignored_counts,
        )


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
