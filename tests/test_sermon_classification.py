from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from pastor_transcript_extractor.config import build_paths, build_video_artifact_paths, ensure_directories
from pastor_transcript_extractor.extraction import (
    _classification_is_current,
    _classify_with_fallback,
    reclassify_video,
)
from pastor_transcript_extractor.local_llm import LocalLlmResponse
from pastor_transcript_extractor.models import TranscriptSegmentLabel
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_classification import (
    CoarsePhase,
    ContentLabel,
    RawInferenceCache,
    TranscriptBlock,
    _candidate_strength,
    _coarse_candidate_ranges,
    _refine_retained_boundaries,
    build_transcript_blocks,
    classify_sermon_content,
)
from pastor_transcript_extractor.sermon_detection import SermonWindowResult


class FakeLlmClient:
    model = "fake-sermon-model"

    def __init__(self, labels: list[ContentLabel]) -> None:
        self.labels = iter(labels)

    def generate_json(self, prompt: str, schema: dict[str, object]) -> LocalLlmResponse:
        del prompt, schema
        label = next(self.labels)
        raw = f'{{"label":"{label.value}","reason_code":"insufficient_context"}}'
        return LocalLlmResponse(
            content={"label": label.value, "reason_code": "insufficient_context"},
            raw_content=raw,
            model=self.model,
        )


class FailingLlmClient:
    model = "broken-model"

    def generate_json(self, prompt: str, schema: dict[str, object]) -> LocalLlmResponse:
        del prompt, schema
        raise RuntimeError("offline")


class FakeAdaptiveLlmClient:
    model = "fake-sermon-model"

    def __init__(self) -> None:
        self.phases = iter(["administration", "sermon", "sermon"])
        self.labels = iter([ContentLabel.ANNOUNCEMENTS, ContentLabel.SERMON, ContentLabel.SERMON])

    def generate_json(self, prompt: str, schema: dict[str, object]) -> LocalLlmResponse:
        del prompt
        properties = schema.get("properties", {})
        if isinstance(properties, dict) and "phase" in properties:
            content = {"phase": next(self.phases), "reason_code": "biblical_exposition"}
        else:
            content = {"label": next(self.labels).value, "reason_code": "biblical_exposition"}
        raw = json.dumps(content)
        return LocalLlmResponse(content=content, raw_content=raw, model=self.model)


def draft(start: float, end: float, text: str) -> SegmentDraft:
    return SegmentDraft(start, end, text, None, TranscriptSegmentLabel.SERMON, 0.55)


class TranscriptBlockTests(unittest.TestCase):
    def test_blocks_map_losslessly_to_timestamped_segments(self) -> None:
        drafts = [draft(index * 30.0, (index + 1) * 30.0, f"segment {index}") for index in range(7)]

        blocks = build_transcript_blocks(drafts, target_seconds=90.0)

        mapped = [index for block in blocks for index in block.segment_indexes]
        self.assertEqual(list(range(7)), mapped)
        self.assertEqual(len(mapped), len(set(mapped)))
        self.assertEqual("segment 0\nsegment 1\nsegment 2", blocks[0].text)

    def test_untimestamped_segments_are_not_fabricated(self) -> None:
        drafts = [SegmentDraft(None, None, "plain text", None, TranscriptSegmentLabel.SERMON, 0.55)]
        self.assertEqual([], build_transcript_blocks(drafts))

    def test_coarse_candidates_bridge_one_uncertain_interruption(self) -> None:
        blocks = [
            TranscriptBlock(index, [index], index * 300.0, (index + 1) * 300.0, str(index))
            for index in range(5)
        ]
        phases = [
            CoarsePhase.ADMINISTRATION,
            CoarsePhase.SERMON,
            CoarsePhase.UNCERTAIN,
            CoarsePhase.SERMON,
            CoarsePhase.WORSHIP,
        ]

        self.assertEqual([(300.0, 1200.0)], _coarse_candidate_ranges(blocks, phases))

    def test_explicit_sermon_start_cue_outranks_a_longer_generic_candidate(self) -> None:
        blocks = [
            TranscriptBlock(0, [0], 0.0, 900.0, "General religious language"),
            TranscriptBlock(1, [1], 1200.0, 1500.0, "Our sermon title today is Grace"),
        ]

        generic = _candidate_strength((0.0, 900.0), blocks)
        explicit = _candidate_strength((1200.0, 1500.0), blocks)

        self.assertGreater(explicit, generic)

    def test_refinement_anchors_to_explicit_cue_and_trims_sustained_music_tail(self) -> None:
        drafts = [
            draft(0.0, 90.0, "Welcome and register for VBS"),
            draft(90.0, 180.0, "Our sermon title today is Grace"),
            draft(180.0, 270.0, "The passage teaches us about Jesus"),
            draft(270.0, 360.0, "More biblical exposition"),
            draft(900.0, 990.0, "[music] [singing]"),
            draft(990.0, 1080.0, "[music] [singing]"),
        ]
        blocks = [
            TranscriptBlock(index, [index], item.start_seconds or 0.0, item.end_seconds or 0.0, item.text)
            for index, item in enumerate(drafts)
        ]

        retained, reasons = _refine_retained_boundaries(
            drafts, blocks, set(range(len(drafts)))
        )

        self.assertEqual({1, 2, 3}, retained)
        self.assertTrue(any("explicit sermon" in reason for reason in reasons))
        self.assertTrue(any("sustained music" in reason for reason in reasons))

    def test_refinement_does_not_trim_single_music_interruption(self) -> None:
        drafts = [
            draft(0.0, 90.0, "Our sermon title today is Grace"),
            draft(700.0, 790.0, "[music] [singing]"),
            draft(790.0, 880.0, "The sermon continues with the passage"),
        ]
        blocks = [
            TranscriptBlock(index, [index], item.start_seconds or 0.0, item.end_seconds or 0.0, item.text)
            for index, item in enumerate(drafts)
        ]

        retained, _ = _refine_retained_boundaries(drafts, blocks, {0, 1, 2})

        self.assertEqual({0, 1, 2}, retained)

    def test_raw_inference_cache_separates_namespaces_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = RawInferenceCache(
                Path(tmp),
                transcript_hash="transcript",
                prompt_version="v1",
                model_name="fake-sermon-model",
                model_digest="digest",
                context_size=4096,
            )
            client = FakeLlmClient([ContentLabel.SERMON, ContentLabel.SERMON, ContentLabel.SERMON])
            block = TranscriptBlock(1, [10, 11], 0.0, 90.0, "current")
            previous = TranscriptBlock(0, [8, 9], -90.0, 0.0, "previous")
            changed_previous = TranscriptBlock(0, [8, 9], -90.0, 0.0, "changed")
            schema = {"type": "object"}

            first = cache.generate("fine", client, "prompt", schema, block, previous)
            second = cache.generate("fine", client, "prompt", schema, block, previous)
            cache.generate("fine", client, "prompt", schema, block, changed_previous)
            cache.generate("coarse", client, "prompt", schema, block)

            self.assertEqual(first.content, second.content)
            self.assertEqual(1, cache.hits)
            self.assertEqual(3, cache.misses)
            self.assertTrue((Path(tmp) / "fine").is_dir())
            self.assertTrue((Path(tmp) / "coarse").is_dir())


class HybridClassificationTests(unittest.TestCase):
    def test_retains_only_sermon_related_labels(self) -> None:
        drafts = [draft(index * 120.0, (index + 1) * 120.0, f"block {index}") for index in range(4)]
        rule_window = SermonWindowResult(
            start_seconds=120.0,
            end_seconds=360.0,
            confidence=0.8,
            reasons=[],
            method="rule_based_v1",
            included_segment_indexes=[1, 2],
            excluded_segment_indexes=[0, 3],
            suspicious_boundary=False,
            suspicious_boundary_reasons=[],
        )
        client = FakeLlmClient(
            [ContentLabel.ANNOUNCEMENTS, ContentLabel.SERMON, ContentLabel.SERMON_PRAYER, ContentLabel.CLOSING_SERVICE]
        )

        result = classify_sermon_content(drafts, rule_window, client)

        self.assertEqual([1, 2], result.retained_segment_indexes)
        self.assertEqual([0, 3], result.excluded_segment_indexes)
        self.assertEqual("high", result.confidence_tier)

    def test_uncertain_block_favors_recall_inside_rule_window(self) -> None:
        drafts = [draft(0.0, 120.0, "opening"), draft(120.0, 240.0, "possible sermon")]
        rule_window = SermonWindowResult(
            start_seconds=120.0,
            end_seconds=240.0,
            confidence=0.6,
            reasons=[],
            method="rule_based_v1",
            included_segment_indexes=[1],
            excluded_segment_indexes=[0],
            suspicious_boundary=True,
            suspicious_boundary_reasons=[],
        )

        result = classify_sermon_content(
            drafts,
            rule_window,
            FakeLlmClient([ContentLabel.ANNOUNCEMENTS, ContentLabel.UNCERTAIN]),
        )

        self.assertEqual([1], result.retained_segment_indexes)
        self.assertEqual([1], result.uncertain_block_ids)
        self.assertEqual("medium", result.confidence_tier)

    def test_auto_mode_falls_back_and_marks_low_confidence(self) -> None:
        drafts = [draft(0.0, 120.0, "sermon")]
        rule_window = SermonWindowResult(
            0.0, 120.0, 0.8, [], "rule_based_v1", [0], [], False, []
        )

        classification, hybrid = _classify_with_fallback(
            drafts,
            rule_window,
            classifier="auto",
            llm_client=FailingLlmClient(),
            prompt_version="test-v1",
        )

        self.assertIsNone(hybrid)
        self.assertEqual("rule_based_fallback", classification["method"])
        self.assertEqual("low", classification["confidence_tier"])
        self.assertIn("offline", classification["warnings"][0])

    def test_strict_llm_mode_propagates_failure(self) -> None:
        drafts = [draft(0.0, 120.0, "sermon")]
        rule_window = SermonWindowResult(
            0.0, 120.0, 0.8, [], "rule_based_v1", [0], [], False, []
        )

        with self.assertRaisesRegex(RuntimeError, "offline"):
            _classify_with_fallback(
                drafts,
                rule_window,
                classifier="llm",
                llm_client=FailingLlmClient(),
                prompt_version="test-v1",
            )

    def test_classification_cache_key_includes_model_and_prompt(self) -> None:
        classification = {
            "method": "adaptive_llm_v3",
            "model": "fixture:4b",
            "prompt_version": "v1",
        }
        self.assertTrue(_classification_is_current(classification, model="fixture:4b", prompt_version="v1"))
        self.assertFalse(_classification_is_current(classification, model="other:4b", prompt_version="v1"))
        self.assertFalse(_classification_is_current(classification, model="fixture:4b", prompt_version="v2"))

    def test_reclassify_updates_only_existing_extraction_artifacts_and_reuses_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_paths(Path(tmp))
            ensure_directories(paths)
            video = SimpleNamespace(id=7, pastor_id=3, youtube_video_id="abc123", title="Fixture")
            pastor = SimpleNamespace(id=3, slug="fixture-pastor")
            video_paths = build_video_artifact_paths(paths, pastor.slug, video.youtube_video_id)
            video_paths.extracted.mkdir(parents=True, exist_ok=True)
            proposed_path = video_paths.extracted / "proposed.json"
            proposed_path.write_text(
                json.dumps(
                    {
                        "transcript_source": "captions",
                        "sermon_window": {
                            "start_seconds": 0.0,
                            "end_seconds": 1800.0,
                            "source": "detected",
                            "included_segment_indexes": [1, 2],
                            "excluded_segment_indexes": [],
                        },
                        "segments": [
                            {"start_seconds": 0.0, "end_seconds": 600.0, "text": "Welcome and announcements", "label": "announcements"},
                            {"start_seconds": 600.0, "end_seconds": 1200.0, "text": "Turn in your Bibles to Romans", "label": "sermon"},
                            {"start_seconds": 1200.0, "end_seconds": 1800.0, "text": "The passage teaches us about grace", "label": "sermon"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            database = MagicMock()
            database.get_video_by_id.return_value = video
            database.get_pastor_by_id.return_value = pastor
            database.get_latest_extraction_result_for_video.return_value = SimpleNamespace(
                proposed_json_path=str(proposed_path)
            )
            client = FakeAdaptiveLlmClient()

            first = reclassify_video(
                database, paths, video.id, llm_client=client, prompt_version="v1"
            )
            second = reclassify_video(
                database, paths, video.id, llm_client=client, prompt_version="v1"
            )

            self.assertFalse(first.reused)
            self.assertTrue(second.reused)
            self.assertEqual(2, first.retained_segment_count)
            updated = json.loads(proposed_path.read_text(encoding="utf-8"))
            self.assertEqual([1, 2], updated["classification"]["retained_segment_indexes"])
            self.assertEqual("hybrid_llm", updated["sermon_window"]["source"])
            database.delete_transcript_segments_for_video.assert_not_called()


if __name__ == "__main__":
    unittest.main()
