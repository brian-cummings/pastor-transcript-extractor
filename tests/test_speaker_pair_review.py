from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import termios
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pastor_transcript_extractor.cli import (
    _normalize_review_terminal_input,
    review_speaker_pair,
)
from pastor_transcript_extractor.models import SpeakerObservation
from pastor_transcript_extractor.speaker_pair_diagnostics import CachedSpan
from pastor_transcript_extractor.speaker_pair_diagnostics import select_diagnostic_spans
from pastor_transcript_extractor.speaker_pair_review import (
    ObservationQualification,
    PairJudgment,
    ReviewEvidenceMode,
    audit_review_selection_artifacts,
    create_review_draft,
    prepare_review_observation,
    submit_review,
)
from pastor_transcript_extractor.speaker_pair_selector import (
    selection_history_from_artifacts,
)


class FakeSpanCache:
    def __init__(
        self,
        root: Path,
        *,
        silent_starts: set[float] | None = None,
    ):
        self.root = root
        self.silent_starts = silent_starts or set()

    def prepare(self, *, observation, source_audio_path, span):
        key = f"{observation.input_fingerprint}-{span.start_seconds:.3f}"
        digest = hashlib.sha256(key.encode()).hexdigest()
        wav_path = self.root / f"{digest}.wav"
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        cache_hit = wav_path.exists()
        if not cache_hit:
            wav_path.write_bytes(key.encode())
        return CachedSpan(
            observation_fingerprint=observation.input_fingerprint,
            start_seconds=span.start_seconds,
            end_seconds=span.end_seconds,
            wav_path=str(wav_path),
            wav_sha256=digest,
            duration_seconds=span.end_seconds - span.start_seconds,
            rms_dbfs=-20.0,
            clipped_fraction=0.0,
            cache_hit=cache_hit,
            non_silent_fraction=(
                0.1 if span.start_seconds in self.silent_starts else 0.9
            ),
        )


def observation(fingerprint: str, identifier: int) -> SpeakerObservation:
    return SpeakerObservation(
        id=identifier,
        video_id=identifier,
        extraction_result_id=identifier,
        role="principal_speaker_candidate",
        multiplicity_state="unknown",
        start_seconds=100.0,
        end_seconds=1100.0,
        artifact_path="speaker-evidence.json",
        content_sha256="a" * 64,
        extractor_version="speaker_evidence_v1",
        input_fingerprint=fingerprint,
        created_at=datetime.now(timezone.utc),
    )


class SpeakerPairReviewTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.evaluation_root = self.root / "speaker-pairs"
        self.span_cache = FakeSpanCache(self.root / "cache")
        self.observation_a = observation("observation-a", 1)
        self.observation_b = observation("observation-b", 2)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_review_prompt_restores_enter_translation_on_tty(self):
        attributes = [termios.IGNCR | termios.INLCR, 0, 0, 0, 0, 0, []]
        stdin = SimpleNamespace(fileno=lambda: 42)
        with (
            patch("pastor_transcript_extractor.cli.sys.stdin", stdin),
            patch("pastor_transcript_extractor.cli.os.isatty", return_value=True),
            patch("termios.tcgetattr", return_value=attributes),
            patch("termios.tcsetattr") as set_attributes,
        ):
            _normalize_review_terminal_input()

        updated = set_attributes.call_args.args[2]
        self.assertTrue(updated[0] & termios.ICRNL)
        self.assertFalse(updated[0] & termios.IGNCR)
        self.assertFalse(updated[0] & termios.INLCR)

    def _draft(self):
        return create_review_draft(
            observation_a=self.observation_a,
            observation_b=self.observation_b,
            video_id_a="video-a",
            video_id_b="video-b",
            audio_path_a=Path("audio-a.wav"),
            audio_path_b=Path("audio-b.wav"),
            span_cache=self.span_cache,
            evaluation_root=self.evaluation_root,
        )

    def _submit(self, draft, **overrides):
        values = {
            "qualification_a": ObservationQualification.QUALIFIED_SINGLE_SPEAKER,
            "qualification_b": ObservationQualification.QUALIFIED_SINGLE_SPEAKER,
            "pair_judgment": PairJudgment.SAME_SPEAKER,
            "reviewer": "reviewer-1",
            "reviewed_at": "2026-07-15T12:00:00+00:00",
            "variation_tags": ["different_date", "different_microphone"],
            "notes": "Listened to every clip.",
            "approval_confirmed": True,
        }
        values.update(overrides)
        return submit_review(
            draft=draft.payload,
            evaluation_root=self.evaluation_root,
            **values,
        )

    def test_draft_and_blinded_packet_are_deterministic(self):
        first = self._draft()
        first_json = first.draft_path.read_bytes()
        first_html = first.packet_path.read_bytes()
        second = self._draft()
        reversed_draft = create_review_draft(
            observation_a=self.observation_b,
            observation_b=self.observation_a,
            video_id_a="video-b",
            video_id_b="video-a",
            audio_path_a=Path("audio-b.wav"),
            audio_path_b=Path("audio-a.wav"),
            span_cache=self.span_cache,
            evaluation_root=self.evaluation_root,
        )

        self.assertEqual(first.pair_id, second.pair_id)
        self.assertEqual(first.pair_id, reversed_draft.pair_id)
        self.assertEqual(first_json, second.draft_path.read_bytes())
        self.assertEqual(first.payload, reversed_draft.payload)
        self.assertEqual(first_html, second.packet_path.read_bytes())
        packet = first.packet_path.read_text(encoding="utf-8")
        self.assertNotIn("video-a", packet)
        self.assertNotIn("video-b", packet)
        self.assertNotIn("observation-a", packet)
        self.assertEqual(
            ReviewEvidenceMode.AUDIO_ONLY,
            first.payload["review_evidence_mode"],
        )
        self.assertIn("Observation A", packet)
        self.assertIn("Observation B", packet)
        self.assertEqual(5, len(first.payload["presentation"]["A"]["clips"]))
        self.assertEqual(5, len(first.payload["presentation"]["B"]["clips"]))
        self.assertEqual(
            "complete",
            first.payload["observations"]["source_a"]["clip_selection"][
                "selection_outcome"
            ],
        )

    def test_profile_review_packet_links_each_clip_to_youtube_timestamp(self):
        draft = create_review_draft(
            observation_a=self.observation_a,
            observation_b=self.observation_b,
            video_id_a="video-a",
            video_id_b="video-b",
            audio_path_a=Path("audio-a.wav"),
            audio_path_b=Path("audio-b.wav"),
            span_cache=self.span_cache,
            evaluation_root=self.evaluation_root,
            selection_manifest={
                "selection_goal": "profile-growth",
            },
        )

        packet = draft.packet_path.read_text(encoding="utf-8")
        self.assertEqual(
            ReviewEvidenceMode.AUDIO_PLUS_VISUAL,
            draft.payload["review_evidence_mode"],
        )
        self.assertFalse(
            draft.payload["blinding"]["packet_hides_video_ids"]
        )
        self.assertIn("watch?v=video-a&amp;t=", packet)
        self.assertIn("watch?v=video-b&amp;t=", packet)
        self.assertEqual(10, packet.count('class="source-link"'))
        self.assertIn("visual identity confirmation", packet)

        submission = self._submit(draft)
        event = json.loads(
            submission.event_path.read_text(encoding="utf-8")
        )
        self.assertEqual("identity_only", submission.fixture_status)
        self.assertTrue(event["identity_evidence_eligible"])
        self.assertFalse(event["fixture_eligible"])
        self.assertEqual("audio_plus_visual", event["review_evidence_mode"])
        self.assertIsNone(submission.fixture_path)

    def test_prepared_observation_is_reused_by_pair_review(self):
        prepared = prepare_review_observation(
            observation=self.observation_a,
            audio_path=Path("audio-a.wav"),
            span_cache=self.span_cache,
        )
        replayed = prepare_review_observation(
            observation=self.observation_a,
            audio_path=Path("audio-a.wav"),
            span_cache=self.span_cache,
        )
        draft = self._draft()
        source_a = draft.payload["observations"]["source_a"]

        self.assertEqual(
            [span.wav_sha256 for span in prepared.spans],
            [clip["wav_sha256"] for clip in source_a["clips"]],
        )
        self.assertTrue(all(span.cache_hit for span in replayed.spans))
        self.assertEqual("complete", replayed.clip_selection["selection_outcome"])

    def test_explicit_review_resumes_existing_automatic_selection_manifest(self):
        manifest = {
            "selector_version": "speaker_pair_selector_v2",
            "selection_origin": "automatic",
            "selection_stratum": "contradicting_attribution",
            "source_relation": "cross_source_family",
            "source_family_ids": {"a": "family-a", "b": "family-b"},
            "evaluation_partitions": {"a": "development", "b": "development"},
        }
        automatic = create_review_draft(
            observation_a=self.observation_a,
            observation_b=self.observation_b,
            video_id_a="video-a",
            video_id_b="video-b",
            audio_path_a=Path("audio-a.wav"),
            audio_path_b=Path("audio-b.wav"),
            span_cache=self.span_cache,
            evaluation_root=self.evaluation_root,
            selection_manifest=manifest,
        )

        resumed = create_review_draft(
            observation_a=self.observation_a,
            observation_b=self.observation_b,
            video_id_a="video-a",
            video_id_b="video-b",
            audio_path_a=Path("audio-a.wav"),
            audio_path_b=Path("audio-b.wav"),
            span_cache=self.span_cache,
            evaluation_root=self.evaluation_root,
        )

        self.assertEqual(automatic.payload, resumed.payload)
        self.assertEqual(
            automatic.payload["selection_manifest"],
            resumed.payload["selection_manifest"],
        )

    def test_selection_audit_detects_legacy_observation_substitution(self):
        audit_root = self.root / "selection-audit"
        create_review_draft(
            observation_a=self.observation_a,
            observation_b=self.observation_b,
            video_id_a="video-a",
            video_id_b="video-b",
            audio_path_a=Path("audio-a.wav"),
            audio_path_b=Path("audio-b.wav"),
            span_cache=self.span_cache,
            evaluation_root=audit_root,
            selection_manifest={
                "selection_origin": "automatic",
                "selection_goal": "profile-growth",
                "profile_growth_components": [
                    ["observation-a"],
                    ["selected-but-substituted"],
                ],
            },
        )

        audit = audit_review_selection_artifacts(audit_root)

        self.assertEqual(1, audit.legacy_checked_count)
        self.assertEqual(1, len(audit.issues))
        self.assertEqual(
            "legacy_profile_growth_pair_mismatch",
            audit.issues[0].reason_code,
        )

    def test_selection_audit_verifies_current_exact_fingerprints(self):
        audit_root = self.root / "exact-selection-audit"
        create_review_draft(
            observation_a=self.observation_a,
            observation_b=self.observation_b,
            video_id_a="video-a",
            video_id_b="video-b",
            audio_path_a=Path("audio-a.wav"),
            audio_path_b=Path("audio-b.wav"),
            span_cache=self.span_cache,
            evaluation_root=audit_root,
            selection_manifest={
                "selection_origin": "automatic",
                "selection_goal": "profile-growth",
                "selected_observation_fingerprints": {
                    "a": "observation-a",
                    "b": "observation-b",
                },
            },
        )

        audit = audit_review_selection_artifacts(audit_root)

        self.assertEqual(1, audit.exact_verified_count)
        self.assertEqual((), audit.issues)

    def test_majority_silence_uses_deterministic_replacement_spans(self):
        primary_starts = {
            span.start_seconds
            for span in select_diagnostic_spans(self.observation_a, count=5)
        }
        span_cache = FakeSpanCache(
            self.root / "silence-aware-cache",
            silent_starts=primary_starts,
        )

        draft = create_review_draft(
            observation_a=self.observation_a,
            observation_b=self.observation_b,
            video_id_a="video-a",
            video_id_b="video-b",
            audio_path_a=Path("audio-a.wav"),
            audio_path_b=Path("audio-b.wav"),
            span_cache=span_cache,
            evaluation_root=self.evaluation_root,
        )

        for observation_payload in draft.payload["observations"].values():
            selection = observation_payload["clip_selection"]
            self.assertEqual(5, selection["qualified_clip_count"])
            self.assertGreater(selection["prepared_clip_count"], 5)
            self.assertTrue(
                all(
                    clip["non_silent_fraction"] >= 0.4
                    for clip in observation_payload["clips"]
                )
            )
            self.assertIn(
                "majority_silence",
                {attempt["reason"] for attempt in selection["attempts"]},
            )

    def test_insufficient_activity_is_recorded_and_excluded_from_reselection(self):
        all_candidate_starts = {
            span.start_seconds
            for count in (5, 15)
            for span in select_diagnostic_spans(self.observation_a, count=count)
        }
        span_cache = FakeSpanCache(
            self.root / "silent-cache",
            silent_starts=all_candidate_starts,
        )
        manifest = {
            "selection_origin": "automatic",
            "selection_stratum": "unattributed",
        }

        with self.assertRaisesRegex(ValueError, "recorded selection rejection"):
            create_review_draft(
                observation_a=self.observation_a,
                observation_b=self.observation_b,
                video_id_a="video-a",
                video_id_b="video-b",
                audio_path_a=Path("audio-a.wav"),
                audio_path_b=Path("audio-b.wav"),
                span_cache=span_cache,
                evaluation_root=self.evaluation_root,
                selection_manifest=manifest,
            )

        paths = list((self.evaluation_root / "drafts").glob("*.rejected.*.json"))
        self.assertEqual(1, len(paths))
        rejection = json.loads(paths[0].read_text(encoding="utf-8"))
        self.assertEqual("insufficient_speech_activity", rejection["reason"])
        self.assertEqual(2, len(rejection["observations"]))
        history = selection_history_from_artifacts(
            drafts=[rejection],
            reviews=[],
            fixtures=[],
        )
        self.assertIn(
            frozenset(("observation-a", "observation-b")),
            history.excluded_pairs,
        )

    def test_partial_four_clip_packet_is_rejected_by_default(self):
        candidate_spans = []
        seen = set()
        for count in (5, 15):
            for span in select_diagnostic_spans(self.observation_a, count=count):
                key = (span.start_seconds, span.end_seconds)
                if key not in seen:
                    seen.add(key)
                    candidate_spans.append(span)
        silent_starts = {
            span.start_seconds
            for span in candidate_spans[4:]
        }
        span_cache = FakeSpanCache(
            self.root / "partial-cache",
            silent_starts=silent_starts,
        )

        with self.assertRaisesRegex(ValueError, "found 4 qualified clip"):
            create_review_draft(
                observation_a=self.observation_a,
                observation_b=self.observation_b,
                video_id_a="video-a",
                video_id_b="video-b",
                audio_path_a=Path("audio-a.wav"),
                audio_path_b=Path("audio-b.wav"),
                span_cache=span_cache,
                evaluation_root=self.evaluation_root,
            )

        rejection_path = next(
            (self.evaluation_root / "drafts").glob("*.rejected.*.json")
        )
        rejection = json.loads(rejection_path.read_text(encoding="utf-8"))
        failed = next(
            item
            for item in rejection["observations"].values()
            if item.get("clip_selection")
        )
        self.assertEqual(4, failed["clip_selection"]["qualified_clip_count"])
        self.assertEqual(5, failed["clip_selection"]["minimum_clip_count"])

    def test_qualified_explicit_review_creates_exact_frozen_fixture(self):
        manifest = {
            "selector_version": "speaker_pair_selector_v1",
            "selection_origin": "automatic",
            "selection_stratum": "shared_attribution",
            "corpus_snapshot_fingerprint": "f" * 64,
            "observation_prior_use": {"a": 3, "b": 7},
            "source_relation": "cross_source_family",
            "source_family_ids": {"a": "family-a", "b": "family-b"},
            "source_family_prior_use": {"a": 2, "b": 4},
            "evaluation_partitions": {
                "a": "development",
                "b": "development",
            },
            "reason_codes": ["both_observations_unused"],
        }
        draft = create_review_draft(
            observation_a=self.observation_a,
            observation_b=self.observation_b,
            video_id_a="video-a",
            video_id_b="video-b",
            audio_path_a=Path("audio-a.wav"),
            audio_path_b=Path("audio-b.wav"),
            span_cache=self.span_cache,
            evaluation_root=self.evaluation_root,
            selection_manifest=manifest,
        )
        result = self._submit(draft, pair_judgment=PairJudgment.DIFFERENT_SPEAKER)

        self.assertEqual("created", result.fixture_status)
        self.assertIsNotNone(result.fixture_path)
        fixture = json.loads(result.fixture_path.read_text(encoding="utf-8"))
        event = json.loads(result.event_path.read_text(encoding="utf-8"))
        self.assertEqual("different_speaker", fixture["expected_outcome"])
        self.assertEqual(event["review_event_id"], fixture["review_event_id"])
        self.assertEqual(5, len(fixture["observations"]["a"]["reviewed_spans"]))
        self.assertEqual(5, len(fixture["observations"]["b"]["reviewed_spans"]))
        self.assertNotIn("wav_path", fixture["observations"]["a"]["reviewed_spans"][0])
        self.assertEqual(
            0.9,
            fixture["observations"]["a"]["reviewed_spans"][0][
                "non_silent_fraction"
            ],
        )
        self.assertIn("clip_quality", event)
        self.assertTrue(event["identity_evidence_eligible"])
        self.assertTrue(event["fixture_eligible"])
        self.assertEqual("audio_only", event["review_evidence_mode"])
        canonical_prior_use = {"source_a": 3, "source_b": 7}
        expected_prior_use = {
            "a": canonical_prior_use[draft.payload["presentation"]["A"]["source_key"]],
            "b": canonical_prior_use[draft.payload["presentation"]["B"]["source_key"]],
        }
        canonical_families = {
            "source_a": "family-a",
            "source_b": "family-b",
        }
        expected_families = {
            "a": canonical_families[
                draft.payload["presentation"]["A"]["source_key"]
            ],
            "b": canonical_families[
                draft.payload["presentation"]["B"]["source_key"]
            ],
        }
        self.assertEqual(expected_prior_use, event["selection_manifest"]["observation_prior_use"])
        self.assertEqual(event["selection_manifest"], fixture["selection_manifest"])
        self.assertEqual({"a": 3, "b": 7}, manifest["observation_prior_use"])
        self.assertEqual("development", fixture["evaluation_partition"])
        self.assertEqual(
            expected_families,
            fixture["selection_manifest"]["source_family_ids"],
        )
        self.assertNotIn("expected_outcome", manifest)
        packet = draft.packet_path.read_text(encoding="utf-8")
        self.assertNotIn("shared_attribution", packet)
        self.assertNotIn("selector_version", packet)

    def test_unqualified_or_indeterminate_review_remains_append_only_without_fixture(self):
        draft = self._draft()
        result = self._submit(
            draft,
            qualification_a=ObservationQualification.MULTIPLE_SPEAKERS,
            pair_judgment=PairJudgment.CANNOT_DETERMINE,
            approval_confirmed=False,
        )

        self.assertEqual("not_eligible", result.fixture_status)
        self.assertIsNone(result.fixture_path)
        self.assertTrue(result.event_path.exists())
        self.assertFalse((self.evaluation_root / "fixtures").exists())

    def test_unqualified_observation_cannot_receive_binary_pair_label(self):
        draft = self._draft()
        with self.assertRaisesRegex(ValueError, "requires cannot_determine"):
            self._submit(
                draft,
                qualification_b=ObservationQualification.INVALID_AUDIO,
                pair_judgment=PairJudgment.DIFFERENT_SPEAKER,
            )

    def test_rereview_never_overwrites_existing_fixture(self):
        draft = self._draft()
        original = self._submit(draft)
        original_bytes = original.fixture_path.read_bytes()
        consistent = self._submit(
            draft,
            reviewer="reviewer-2",
            reviewed_at="2026-07-16T12:00:00+00:00",
        )
        conflict = self._submit(
            draft,
            reviewer="reviewer-3",
            reviewed_at="2026-07-17T12:00:00+00:00",
            pair_judgment=PairJudgment.DIFFERENT_SPEAKER,
        )

        self.assertEqual("existing_consistent", consistent.fixture_status)
        self.assertEqual("existing_conflict_preserved", conflict.fixture_status)
        self.assertEqual(original_bytes, original.fixture_path.read_bytes())
        events = list((self.evaluation_root / "reviews" / draft.pair_id).glob("*.json"))
        self.assertEqual(3, len(events))

    def test_draft_tampering_is_rejected(self):
        draft = self._draft()
        tampered = json.loads(json.dumps(draft.payload))
        tampered["presentation"]["A"]["clips"].pop()

        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            submit_review(
                draft=tampered,
                qualification_a=ObservationQualification.CANNOT_DETERMINE,
                qualification_b=ObservationQualification.CANNOT_DETERMINE,
                pair_judgment=PairJudgment.CANNOT_DETERMINE,
                reviewer="reviewer",
                reviewed_at="2026-07-15T12:00:00+00:00",
                variation_tags=[],
                notes="",
                approval_confirmed=False,
                evaluation_root=self.evaluation_root,
            )

    def test_eligible_review_defaults_fixture_approval_to_yes(self):
        draft = SimpleNamespace(
            packet_path=self.evaluation_root / "drafts" / "pair.html",
            payload={"pair_id": "pair"},
        )
        database = SimpleNamespace(
            get_video_by_youtube_id=lambda value: SimpleNamespace(id=value),
            get_latest_speaker_observation_for_video=lambda _video_id: self.observation_a,
        )
        submission = SimpleNamespace(
            event_path=self.evaluation_root / "reviews" / "event.json",
            fixture_path=None,
            fixture_status="not_eligible",
        )
        with (
            patch(
                "pastor_transcript_extractor.cli.build_paths",
                return_value=SimpleNamespace(database=self.root / "database.sqlite3"),
            ),
            patch("pastor_transcript_extractor.cli.Path.exists", return_value=True),
            patch("pastor_transcript_extractor.cli.Database", return_value=database),
            patch(
                "pastor_transcript_extractor.cli.resolve_normalized_audio_path",
                return_value=self.root / "audio.wav",
            ),
            patch("pastor_transcript_extractor.cli.create_review_draft", return_value=draft),
            patch(
                "pastor_transcript_extractor.cli.typer.prompt",
                side_effect=["single", "single", "same", "", ""],
            ),
            patch(
                "pastor_transcript_extractor.cli.typer.confirm",
                return_value=False,
            ) as confirm,
            patch(
                "pastor_transcript_extractor.cli.submit_review",
                return_value=submission,
            ),
        ):
            review_speaker_pair(
                "video-a",
                "video-b",
                reviewer="reviewer-1",
                evaluation_root=self.evaluation_root,
                cache_dir=self.root / "cache",
                open_packet=False,
                prepare_only=False,
                base_dir=self.root,
                selection_manifest_json=None,
                observation_fingerprint_a=None,
                observation_fingerprint_b=None,
            )

        confirm.assert_called_once_with(
            "Freeze this exact-span binary judgment as an approved acoustic fixture?",
            default=True,
        )

    def test_automatic_review_uses_exact_selected_observations(self):
        exact_a = replace(self.observation_a, video_id=101)
        exact_b = replace(self.observation_b, video_id=202)
        stale_a = replace(
            self.observation_a,
            id=99,
            video_id=101,
            input_fingerprint="newer-but-not-selected",
        )
        videos = {
            "video-a": SimpleNamespace(id=101),
            "video-b": SimpleNamespace(id=202),
        }
        exact = {
            exact_a.input_fingerprint: exact_a,
            exact_b.input_fingerprint: exact_b,
        }
        database = SimpleNamespace(
            get_video_by_youtube_id=lambda value: videos.get(value),
            get_speaker_observation_by_fingerprint=lambda value: exact.get(
                value
            ),
            get_latest_speaker_observation_for_video=lambda _video_id: stale_a,
        )
        draft = SimpleNamespace(
            packet_path=self.evaluation_root / "drafts" / "pair.html",
            payload={
                "pair_id": "pair",
                "review_evidence_mode": "audio_plus_visual",
            },
        )
        manifest = {
            "selection_origin": "automatic",
            "selection_goal": "profile-growth",
            "selected_observation_fingerprints": {
                "a": exact_a.input_fingerprint,
                "b": exact_b.input_fingerprint,
            },
        }
        with (
            patch(
                "pastor_transcript_extractor.cli.build_paths",
                return_value=SimpleNamespace(
                    database=self.root / "database.sqlite3"
                ),
            ),
            patch(
                "pastor_transcript_extractor.cli.Path.exists",
                return_value=True,
            ),
            patch(
                "pastor_transcript_extractor.cli.Database",
                return_value=database,
            ),
            patch(
                "pastor_transcript_extractor.cli.resolve_normalized_audio_path",
                return_value=self.root / "audio.wav",
            ),
            patch(
                "pastor_transcript_extractor.cli.create_review_draft",
                return_value=draft,
            ) as create,
        ):
            review_speaker_pair(
                "video-a",
                "video-b",
                reviewer="reviewer-1",
                evaluation_root=self.evaluation_root,
                cache_dir=self.root / "cache",
                open_packet=False,
                prepare_only=True,
                base_dir=self.root,
                selection_manifest_json=json.dumps(manifest),
                observation_fingerprint_a=exact_a.input_fingerprint,
                observation_fingerprint_b=exact_b.input_fingerprint,
            )

        self.assertIs(exact_a, create.call_args.kwargs["observation_a"])
        self.assertIs(exact_b, create.call_args.kwargs["observation_b"])


if __name__ == "__main__":
    unittest.main()
