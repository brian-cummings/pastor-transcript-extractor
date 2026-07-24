from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from pastor_transcript_extractor.config import build_paths, build_video_artifact_paths, ensure_directories
from pastor_transcript_extractor.caption_normalization import (
    NORMALIZER_VERSION,
    normalize_caption_fragments,
)
from pastor_transcript_extractor.extraction import (
    _baseline_window_payload,
    _classification_is_current,
    _classify_with_fallback,
    reclassify_video,
)
from pastor_transcript_extractor.local_llm import LocalLlmResponse
from pastor_transcript_extractor.models import TranscriptSegmentLabel
from pastor_transcript_extractor.recording_verifier import (
    POLICY_VERSION as RECORDING_VERIFIER_POLICY_VERSION,
)
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_classification import (
    BLOCK_BUILDER_VERSION,
    COARSE_DISCOVERY_VERSION,
    CONFIDENCE_POLICY_VERSION,
    CoarsePhase,
    ContentLabel,
    FINE_COMPONENT_VERSION,
    LONG_EDGE_EXPANSION_SECONDS,
    RawInferenceCache,
    TranscriptBlock,
    _candidate_strength,
    _adaptive_confidence_tier,
    _coarse_candidate_ranges,
    _joined_candidate,
    _long_recording_edge_expansion,
    _refine_retained_boundaries,
    build_transcript_blocks,
    classify_sermon_content,
    classify_sermon_content_adaptive,
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
        self.phases = iter([
            CoarsePhase.ADMINISTRATION,
            CoarsePhase.SERMON,
            CoarsePhase.SERMON,
        ])
        self.labels = iter([ContentLabel.ANNOUNCEMENTS, ContentLabel.SERMON, ContentLabel.SERMON])

    def generate_json(self, prompt: str, schema: dict[str, object]) -> LocalLlmResponse:
        del prompt
        properties = schema.get("properties", {})
        if isinstance(properties, dict) and "phase" in properties:
            content = {"phase": next(self.phases).value, "reason_code": "biblical_exposition"}
        elif isinstance(properties, dict) and "decision" in properties:
            content = {"decision": "sermon_biblical_exposition"}
        else:
            content = {"label": next(self.labels).value, "reason_code": "biblical_exposition"}
        raw = json.dumps(content)
        return LocalLlmResponse(content=content, raw_content=raw, model=self.model)


class BoundaryAwareLlmClient:
    model = "fake-boundary-model"

    def generate_json(self, prompt: str, schema: dict[str, object]) -> LocalLlmResponse:
        properties = schema.get("properties", {})
        if isinstance(properties, dict) and "phase" in properties:
            value = (
                CoarsePhase.SERMON.value
                if "COARSE_TARGET" in prompt
                else CoarsePhase.ADMINISTRATION.value
            )
            content = {"phase": value, "reason_code": "biblical_exposition"}
        elif isinstance(properties, dict) and "decision" in properties:
            content = {"decision": "sermon_biblical_exposition"}
        else:
            current = prompt.split("CURRENT BLOCK:\n", 1)[1].split("\n\nFOLLOWING CONTEXT:", 1)[0]
            value = ContentLabel.SERMON if "SUSTAINED" in current else ContentLabel.ANNOUNCEMENTS
            content = {"label": value.value, "reason_code": "biblical_exposition"}
        return LocalLlmResponse(content, json.dumps(content), self.model)


class AllSermonLlmClient:
    model = "fake-all-sermon-model"

    def generate_json(self, prompt: str, schema: dict[str, object]) -> LocalLlmResponse:
        del prompt
        properties = schema.get("properties", {})
        if isinstance(properties, dict) and "phase" in properties:
            content = {"phase": "sermon", "reason_code": "biblical_exposition"}
        elif isinstance(properties, dict) and "decision" in properties:
            content = {"decision": "sermon_biblical_exposition"}
        else:
            content = {"label": "sermon", "reason_code": "biblical_exposition"}
        return LocalLlmResponse(content, json.dumps(content), self.model)


class PrecisionPrimaryLlmClient:
    model = "fake-precision-primary-model"

    def __init__(self) -> None:
        self.primary_calls = 0
        self.rescue_calls = 0

    def generate_json(self, prompt: str, schema: dict[str, object]) -> LocalLlmResponse:
        del prompt
        properties = schema.get("properties", {})
        if isinstance(properties, dict) and "phase" in properties:
            self.primary_calls += 1
            content = {"phase": "sermon", "reason_code": "biblical_exposition"}
        elif isinstance(properties, dict) and "decision" in properties:
            self.rescue_calls += 1
            raise AssertionError("likelihood rescue must not run when primary finds a candidate")
        else:
            content = {"label": "sermon", "reason_code": "biblical_exposition"}
        return LocalLlmResponse(content, json.dumps(content), self.model)


class RecallRescueLlmClient:
    model = "fake-recall-rescue-model"

    def __init__(self) -> None:
        self.primary_calls = 0
        self.rescue_calls = 0

    def generate_json(self, prompt: str, schema: dict[str, object]) -> LocalLlmResponse:
        del prompt
        properties = schema.get("properties", {})
        if isinstance(properties, dict) and "phase" in properties:
            self.primary_calls += 1
            content = {"phase": "administration", "reason_code": "logistics_or_welcome"}
        elif isinstance(properties, dict) and "decision" in properties:
            self.rescue_calls += 1
            content = {"decision": "sermon_biblical_exposition"}
        else:
            content = {"label": "sermon", "reason_code": "biblical_exposition"}
        return LocalLlmResponse(content, json.dumps(content), self.model)


def draft(start: float, end: float, text: str) -> SegmentDraft:
    return SegmentDraft(start, end, text, None, TranscriptSegmentLabel.SERMON, 0.55)


class TranscriptBlockTests(unittest.TestCase):
    def test_prompt_normalizer_collapses_rolling_caption_overlap_with_provenance(self) -> None:
        normalized = normalize_caption_fragments([
            (4, "Father in heaven"),
            (5, "Father in heaven thank you"),
            (6, "thank you for grace"),
            (7, "for grace"),
        ])

        self.assertEqual("Father in heaven thank you for grace", normalized.text)
        self.assertEqual(NORMALIZER_VERSION, normalized.diagnostics["normalizer_version"])
        self.assertGreater(normalized.diagnostics["deduplication_ratio"], 0.0)
        self.assertEqual([4, 5, 6, 7], normalized.diagnostics["source_segment_indexes"])
        self.assertEqual(
            [4, 5, 6, 7],
            normalized.diagnostics["normalized_units"][0]["source_segment_indexes"],
        )

    def test_blocks_map_losslessly_to_timestamped_segments(self) -> None:
        drafts = [draft(index * 30.0, (index + 1) * 30.0, f"segment {index}") for index in range(7)]

        blocks = build_transcript_blocks(drafts, target_seconds=90.0)

        mapped = [index for block in blocks for index in block.segment_indexes]
        self.assertEqual(list(range(7)), mapped)
        self.assertEqual(len(mapped), len(set(mapped)))
        self.assertEqual("segment 0\nsegment 1\nsegment 2", blocks[0].text)
        self.assertEqual("segment 0\nsegment 1\nsegment 2", blocks[0].raw_text)
        self.assertEqual(NORMALIZER_VERSION, blocks[0].normalization["normalizer_version"])

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
            CoarsePhase.ADMINISTRATION,
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

    def test_title_without_sermon_word_outranks_a_slightly_longer_candidate(self) -> None:
        blocks = [
            TranscriptBlock(0, [0], 0.0, 1200.0, "Earlier religious program"),
            TranscriptBlock(1, [1], 1800.0, 2850.0, "Our title today is Celebrating Freedom"),
        ]

        generic = _candidate_strength((0.0, 1200.0), blocks)
        titled = _candidate_strength((1800.0, 2850.0), blocks)

        self.assertGreater(titled, generic)

    def test_long_continuity_expansion_to_recording_edge_requires_review(self) -> None:
        blocks = [
            TranscriptBlock(index, [index], index * 90.0, (index + 1) * 90.0, "teaching")
            for index in range(8)
        ]
        outcome = _long_recording_edge_expansion(
            {
                "start": {"status": "semantic_transition", "probed_block_ids": []},
                "end": {"status": "recording_edge", "probed_block_ids": list(range(8))},
            },
            blocks,
        )

        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(LONG_EDGE_EXPANSION_SECONDS, outcome["threshold_seconds"])
        self.assertEqual(720.0, outcome["expansions"][0]["duration_seconds"])

    def test_candidate_join_requires_explicit_allowed_gap_evidence(self) -> None:
        blocks = [
            TranscriptBlock(0, [0], 0.0, 300.0, "sermon one"),
            TranscriptBlock(1, [1], 300.0, 450.0, "speaker handoff"),
            TranscriptBlock(2, [2], 450.0, 750.0, "Turn in your Bibles as the sermon resumes"),
        ]
        left = {"start_seconds": 0.0, "end_seconds": 300.0, "coarse_support_block_ids": [0]}
        right = {"start_seconds": 450.0, "end_seconds": 750.0, "coarse_support_block_ids": [2]}
        allowed_audit = [
            SimpleNamespace(evidence="coarse:biblical_exposition"),
            SimpleNamespace(evidence="coarse:speaker_handoff"),
            SimpleNamespace(evidence="coarse:biblical_exposition"),
        ]
        blocked_audit = [
            SimpleNamespace(evidence="coarse:biblical_exposition"),
            SimpleNamespace(evidence="coarse:logistics_or_welcome"),
            SimpleNamespace(evidence="coarse:biblical_exposition"),
        ]

        joined = _joined_candidate(left, right, blocks, allowed_audit)

        self.assertIsNotNone(joined)
        assert joined is not None
        self.assertEqual(150.0, joined["join"]["gap_duration_seconds"])
        self.assertEqual(["speaker_handoff"], joined["join"]["reason_codes"])
        self.assertEqual(["turn in your bibles"], joined["join"]["continuity_cues"])
        self.assertIn("join_gap_duration_seconds", joined["score_components"])
        self.assertIsNone(_joined_candidate(left, right, blocks, blocked_audit))

        blocks[2] = TranscriptBlock(2, [2], 450.0, 750.0, "generic religious speech")
        self.assertIsNone(_joined_candidate(left, right, blocks, allowed_audit))

    def test_refinement_anchors_to_explicit_cue_without_asymmetric_tail_trim(self) -> None:
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

        retained, reasons, start_refinement = _refine_retained_boundaries(
            drafts, blocks, set(range(len(drafts)))
        )

        self.assertEqual({1, 2, 3, 4, 5}, retained)
        self.assertTrue(any("explicit sermon" in reason for reason in reasons))
        self.assertFalse(any("sustained music" in reason for reason in reasons))
        self.assertEqual(0.0, start_refinement["pre_anchor_extension_seconds"])

    def test_refinement_recovers_contiguous_sermon_setup_before_anchor(self) -> None:
        drafts = [
            draft(0.0, 60.0, "[music] [singing]"),
            draft(60.0, 120.0, "Our theme is leaving the old life behind in Jesus"),
            draft(120.0, 180.0, "Bible names reveal identity and God's calling"),
            draft(180.0, 240.0, "As we open God's word tonight let us pray"),
            draft(240.0, 300.0, "Genesis teaches us about Abram"),
        ]
        blocks = [
            TranscriptBlock(index, [index], item.start_seconds or 0.0, item.end_seconds or 0.0, item.text)
            for index, item in enumerate(drafts)
        ]

        retained, reasons, start_refinement = _refine_retained_boundaries(
            drafts, blocks, {1, 2, 3, 4}
        )

        self.assertEqual({1, 2, 3, 4}, retained)
        self.assertTrue(any("extended explicit sermon anchor" in reason for reason in reasons))
        self.assertEqual(120.0, start_refinement["pre_anchor_extension_seconds"])
        self.assertEqual("music", start_refinement["stopped_by"])

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

        retained, _, _ = _refine_retained_boundaries(drafts, blocks, {0, 1, 2})

        self.assertEqual({0, 1, 2}, retained)

    def test_refinement_does_not_treat_leading_music_as_a_trailing_transition(self) -> None:
        drafts = [
            draft(0.0, 90.0, "[music] [singing]"),
            draft(90.0, 180.0, "[music] [singing]"),
            draft(180.0, 270.0, "Sustained biblical exposition"),
            draft(270.0, 360.0, "The sermon continues"),
        ]
        blocks = [
            TranscriptBlock(index, [index], item.start_seconds or 0.0, item.end_seconds or 0.0, item.text)
            for index, item in enumerate(drafts)
        ]

        retained, reasons, _ = _refine_retained_boundaries(drafts, blocks, {0, 1, 2, 3})

        self.assertEqual({0, 1, 2, 3}, retained)
        self.assertFalse(any("trimmed candidate" in reason for reason in reasons))

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
    def test_primary_discovery_skips_likelihood_rescue_when_it_finds_a_candidate(self) -> None:
        drafts = [
            draft(index * 300.0, (index + 1) * 300.0, "sustained biblical exposition")
            for index in range(3)
        ]
        rule_window = SermonWindowResult(
            None, None, 0.0, [], "rule_based_v1", [], list(range(3)), False, []
        )
        client = PrecisionPrimaryLlmClient()

        result = classify_sermon_content_adaptive(drafts, rule_window, client).to_dict()

        self.assertEqual(3, client.primary_calls)
        self.assertEqual(0, client.rescue_calls)
        self.assertEqual("coarse_llm", result["search"]["candidates"][0]["source"])
        self.assertEqual(
            {
                "primary_version": "multiclass-phase-v1",
                "rescue_version": "sermon-likelihood-v1",
                "rescue_triggered": False,
                "selected_mode": "primary",
            },
            result["search"]["discovery"],
        )

    def test_likelihood_rescue_runs_only_when_primary_finds_no_candidate(self) -> None:
        drafts = [
            draft(index * 300.0, (index + 1) * 300.0, "sustained biblical exposition")
            for index in range(3)
        ]
        rule_window = SermonWindowResult(
            None, None, 0.0, [], "rule_based_v1", [], list(range(3)), False, []
        )
        client = RecallRescueLlmClient()

        result = classify_sermon_content_adaptive(drafts, rule_window, client).to_dict()

        self.assertEqual(3, client.primary_calls)
        self.assertEqual(3, client.rescue_calls)
        self.assertEqual(
            "coarse_likelihood_rescue", result["search"]["candidates"][0]["source"]
        )
        self.assertTrue(result["search"]["discovery"]["rescue_triggered"])
        self.assertEqual("likelihood_rescue", result["search"]["discovery"]["selected_mode"])

    def test_adaptive_search_splits_objective_noise_and_selects_stronger_component(self) -> None:
        drafts = [
            draft(index * 90.0, (index + 1) * 90.0, (
                "[music] [singing]" if index in {4, 5}
                else "sustained biblical teaching"
            ))
            for index in range(12)
        ]
        rule_window = SermonWindowResult(
            None, None, 0.0, [], "rule_based_v1", [], list(range(12)), False, []
        )

        result = classify_sermon_content_adaptive(
            drafts, rule_window, AllSermonLlmClient(), prompt_version="noise-split-v1"
        ).to_dict()

        self.assertEqual(list(range(6, 12)), result["retained_segment_indexes"])
        recovery = result["search"]["candidates"][0]["boundary_recovery"]
        self.assertEqual([4, 5], recovery["objective_separator_block_ids"])
        self.assertIn([0, 1, 2, 3], recovery["discarded_component_block_ids"])

    def test_adaptive_search_anchors_to_candidate_overlapping_fine_component(self) -> None:
        texts = ["administration" for _ in range(16)]
        texts[5] = "SUSTAINED disconnected teaching"
        texts[6] = "SUSTAINED disconnected teaching continues"
        texts[8] = "COARSE_TARGET SUSTAINED candidate sermon"
        texts[9] = "SUSTAINED candidate sermon continues"
        texts[10] = "SUSTAINED candidate sermon conclusion"
        drafts = [
            draft(index * 90.0, (index + 1) * 90.0, text)
            for index, text in enumerate(texts)
        ]
        rule_window = SermonWindowResult(
            None, None, 0.0, [], "rule_based_v1", [], list(range(16)), False, []
        )

        result = classify_sermon_content_adaptive(
            drafts, rule_window, BoundaryAwareLlmClient(), prompt_version="component-test-v1"
        ).to_dict()

        self.assertEqual([8, 9, 10], result["retained_segment_indexes"])
        candidate = result["search"]["candidates"][0]
        recovery = candidate["boundary_recovery"]
        self.assertEqual([8, 9, 10], recovery["anchored_component_block_ids"])
        self.assertIn([5, 6], recovery["discarded_component_block_ids"])
        self.assertFalse(recovery["start"]["initially_saturated"])
        self.assertTrue(recovery["end"]["initially_saturated"])
        self.assertTrue(recovery["end"]["probe_performed"])
        self.assertEqual("announcements", recovery["end"]["stopping_label"])

    def test_adaptive_search_probes_saturated_boundaries_until_semantic_transition(self) -> None:
        drafts = [
            draft(index * 90.0, (index + 1) * 90.0, (
                "opening transition" if index == 0
                else "closing transition" if index == 15
                else "COARSE_TARGET SUSTAINED exposition" if index == 8
                else "SUSTAINED exposition"
            ))
            for index in range(16)
        ]
        rule_window = SermonWindowResult(
            None, None, 0.0, [], "rule_based_v1", [], list(range(16)), False, []
        )

        result = classify_sermon_content_adaptive(
            drafts, rule_window, BoundaryAwareLlmClient(), prompt_version="boundary-test-v1"
        ).to_dict()

        self.assertEqual(list(range(1, 15)), result["retained_segment_indexes"])
        candidate = result["search"]["candidates"][0]
        recovery = candidate["boundary_recovery"]
        self.assertTrue(recovery["start"]["initially_saturated"])
        self.assertTrue(recovery["end"]["initially_saturated"])
        self.assertEqual("semantic_transition", recovery["start"]["status"])
        self.assertEqual("semantic_transition", recovery["end"]["status"])
        self.assertEqual([1, 0], recovery["start"]["probed_block_ids"])
        self.assertEqual([11, 12, 13, 14, 15], recovery["end"]["probed_block_ids"])
        self.assertEqual("announcements", recovery["start"]["stopping_label"])
        self.assertEqual("announcements", recovery["end"]["stopping_label"])
        self.assertEqual("active", recovery["mode"])

    def test_baseline_window_payload_replaces_stale_hybrid_state(self) -> None:
        recomputed = SermonWindowResult(
            None,
            None,
            0.15,
            ["no rule window"],
            "rule_based_v1",
            [],
            [0, 1],
            False,
            [],
        )

        payload = _baseline_window_payload(recomputed, manual_override_present=False)

        self.assertEqual("detected", payload["source"])
        self.assertEqual("rule_based_v1", payload["method"])
        self.assertIsNone(payload["start_seconds"])
        self.assertEqual([], payload["included_segment_indexes"])

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

    def test_shared_classification_service_uses_adaptive_search(self) -> None:
        drafts = [
            SegmentDraft(0.0, 600.0, "Welcome and announcements", None, TranscriptSegmentLabel.ANNOUNCEMENTS, 0.7),
            draft(600.0, 1200.0, "Our sermon title today is Grace"),
            draft(1200.0, 1800.0, "Sustained biblical exposition"),
        ]
        rule_window = SermonWindowResult(
            600.0, 1800.0, 0.8, [], "rule_based_v1", [1, 2], [0], False, []
        )

        classification, result = _classify_with_fallback(
            drafts,
            rule_window,
            classifier="llm",
            llm_client=FakeAdaptiveLlmClient(),
            prompt_version="test-v2",
        )

        self.assertIsNotNone(result)
        self.assertEqual("adaptive_llm_v3", classification["method"])
        self.assertEqual(1, classification["search"]["selected_rank"])
        candidate = classification["search"]["candidates"][0]
        self.assertEqual(candidate["score"], candidate["score_components"]["total_score"])
        self.assertIn("duration_seconds", candidate["score_components"])
        self.assertTrue(classification["confidence_reasons"])
        self.assertEqual(
            classification["confidence_tier"],
            classification["confidence_reasons"][-1]["tier"],
        )

    def test_classification_cache_key_includes_model_and_prompt(self) -> None:
        classification = {
            "method": "adaptive_llm_v3",
            "block_builder_version": BLOCK_BUILDER_VERSION,
            "coarse_discovery_version": COARSE_DISCOVERY_VERSION,
            "fine_component_version": FINE_COMPONENT_VERSION,
            "model": "fixture:4b",
            "prompt_version": "v1",
            "confidence_policy_version": CONFIDENCE_POLICY_VERSION,
            "recording_verifier_policy_version": RECORDING_VERIFIER_POLICY_VERSION,
            "recording_verification": {
                "source": "not_required",
                "decision": None,
            },
        }
        self.assertTrue(_classification_is_current(classification, model="fixture:4b", prompt_version="v1"))
        self.assertFalse(_classification_is_current(classification, model="other:4b", prompt_version="v1"))
        self.assertFalse(_classification_is_current(classification, model="fixture:4b", prompt_version="v2"))
        classification["confidence_policy_version"] = "hard_rule_overlap_v1"
        self.assertFalse(_classification_is_current(classification, model="fixture:4b", prompt_version="v1"))

    def test_adaptive_confidence_treats_rule_overlap_as_a_soft_penalty(self) -> None:
        self.assertEqual(
            "medium",
            _adaptive_confidence_tier(
                agreement=0.0,
                retained=True,
                uncertain=False,
                consistency_failed=False,
            ),
        )
        self.assertEqual(
            "high",
            _adaptive_confidence_tier(
                agreement=0.6,
                retained=True,
                uncertain=False,
                consistency_failed=False,
            ),
        )
        self.assertEqual(
            "low",
            _adaptive_confidence_tier(
                agreement=1.0,
                retained=True,
                uncertain=False,
                consistency_failed=True,
            ),
        )

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
            self.assertEqual("adaptive_llm_v3", updated["classification"]["method"])
            self.assertEqual("accepted_sermon", updated["final_disposition"]["status"])
            self.assertEqual(
                updated["final_disposition"],
                updated["classification"]["final_disposition"],
            )
            self.assertEqual(1, updated["classification"]["search"]["selected_rank"])
            self.assertEqual(1, updated["classification"]["search"]["candidates"][0]["rank"])
            self.assertTrue(updated["classification"]["search"]["candidates"][0]["coarse_support_block_ids"])
            first_baseline = updated["classification"]["search"]["rule_baseline"]
            first_agreement = next(
                reason["value"]
                for reason in updated["classification"]["confidence_reasons"]
                if reason["code"] == "rule_llm_agreement"
            )
            self.assertEqual("recomputed_rules", updated["classification"]["search"]["rule_baseline_source"])
            self.assertFalse(updated["classification"]["search"]["manual_override_present"])

            reclassify_video(
                database,
                paths,
                video.id,
                llm_client=FakeAdaptiveLlmClient(),
                prompt_version="v1",
                force=True,
            )
            repeated = json.loads(proposed_path.read_text(encoding="utf-8"))["classification"]
            repeated_agreement = next(
                reason["value"]
                for reason in repeated["confidence_reasons"]
                if reason["code"] == "rule_llm_agreement"
            )
            self.assertEqual(first_baseline, repeated["search"]["rule_baseline"])
            self.assertEqual(first_agreement, repeated_agreement)
            database.delete_transcript_segments_for_video.assert_not_called()

    def test_manual_override_is_authoritative_reclassification_baseline(self) -> None:
        drafts = [
            draft(0.0, 300.0, "opening"),
            draft(300.0, 600.0, "sermon"),
            draft(600.0, 900.0, "closing"),
        ]
        override_window = SermonWindowResult(
            300.0,
            600.0,
            1.0,
            ["manual review override applied"],
            "manual_override_v1",
            [1],
            [0, 2],
            False,
            [],
        )

        result = classify_sermon_content_adaptive(
            drafts,
            override_window,
            FakeAdaptiveLlmClient(),
            prompt_version="v1",
            rule_baseline_source="manual_override",
            rule_baseline_algorithm_version="manual_override_v1",
            manual_override_present=True,
        ).to_dict()

        self.assertEqual(
            {"start_seconds": 300.0, "end_seconds": 600.0, "confidence": 1.0},
            result["search"]["rule_baseline"],
        )
        self.assertEqual("manual_override", result["search"]["rule_baseline_source"])
        self.assertEqual("manual_override_v1", result["search"]["rule_baseline_algorithm_version"])
        self.assertTrue(result["search"]["manual_override_present"])


if __name__ == "__main__":
    unittest.main()
