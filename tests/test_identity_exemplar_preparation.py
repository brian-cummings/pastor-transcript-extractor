from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.identity_exemplar_preparation import (
    ExemplarPreparationStateCache,
    exemplar_failure_policy,
)


class ExemplarPreparationStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = ExemplarPreparationStateCache(Path(self.temporary.name))
        self.evidence = {
            "observation_fingerprint": "observation-a",
            "media_sha256": "a" * 64,
            "span_selection_version": "spans-v1",
        }

    def _record(self, **overrides):
        values = {
            "profile_id": 107,
            "observation_id": 11,
            "observation_fingerprint": "observation-a",
            "video_id": 21,
            "youtube_video_id": "youtube-a",
            "evidence": self.evidence,
            "stage": "media_verification",
            "outcome": "blocked",
            "reason_code": "archived_media_unavailable",
        }
        values.update(overrides)
        return self.cache.record(**values)

    def test_deterministic_failure_is_idempotent_until_evidence_changes(self):
        first = self._record()
        second = self._record()

        self.assertEqual(first, second)
        self.assertEqual(1, len(self.cache.latest_states()))
        self.assertEqual(
            first,
            self.cache.unchanged_deterministic_failure(
                profile_id=107,
                observation_fingerprint="observation-a",
                evidence_fingerprint=first.evidence_fingerprint,
            ),
        )
        changed_fingerprint = self.cache.evidence_fingerprint(
            {**self.evidence, "media_sha256": "b" * 64}
        )
        self.assertIsNone(
            self.cache.unchanged_deterministic_failure(
                profile_id=107,
                observation_fingerprint="observation-a",
                evidence_fingerprint=changed_fingerprint,
            )
        )

    def test_automatic_media_repair_is_attempted_once_per_evidence(self):
        state = self._record()

        self.assertEqual((state,), self.cache.pending_automatic_repairs())
        self.cache.record_repair_attempt(
            state,
            outcome="deferred",
            detail="archive unavailable",
        )

        self.assertEqual((), self.cache.pending_automatic_repairs())

    def test_activity_failure_requires_human_review(self):
        state = self._record(
            stage="activity_span_selection",
            reason_code="too_few_activity_qualified_spans",
        )

        self.assertEqual("human_review_required", state.retry_policy)
        self.assertEqual("review_exemplar_spans", state.repair_action)
        self.assertFalse(state.automatic_retry_allowed)
        self.assertEqual((), self.cache.pending_automatic_repairs())

    def test_transient_failure_remains_retryable_without_evidence_change(self):
        state = self._record(
            stage="activity_span_selection",
            reason_code="temporary decoder failure",
        )

        self.assertEqual("each_run", state.retry_policy)
        self.assertIsNone(
            self.cache.unchanged_deterministic_failure(
                profile_id=107,
                observation_fingerprint="observation-a",
                evidence_fingerprint=state.evidence_fingerprint,
            )
        )

    def test_failure_policy_does_not_relax_acoustic_guards(self):
        self.assertEqual(
            (
                "when_evidence_changes",
                "regenerate_extraction",
                False,
            ),
            exemplar_failure_policy(
                "transcript_span_selection",
                "speech_grounded_spans_unavailable",
            ),
        )


if __name__ == "__main__":
    unittest.main()
