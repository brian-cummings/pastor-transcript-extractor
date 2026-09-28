from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.models import TranscriptSegmentLabel
from pastor_transcript_extractor.extraction import (
    WINDOW_ARBITRATION_POLICY_VERSION,
    _arbitrate_hybrid_window,
    _classification_is_current,
)
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_classifier_typesafe import (
    BLOCK_BUILDER_VERSION,
    COARSE_DISCOVERY_VERSION,
    FINE_COMPONENT_VERSION,
    QUESTION_SET_VERSION,
    ROLE_CHOICES,
    SEARCH_ALGORITHM_VERSION,
    TypeSafeBlockAnswer,
    TypeSafeBlockCache,
    TypeSafeFirstPassSermonClassifier,
)
from pastor_transcript_extractor.sermon_classification import build_transcript_blocks
from pastor_transcript_extractor.sermon_detection import SermonWindowResult


class FakeBlockClient:
    def __init__(self) -> None:
        self.calls = 0
        self.block_ids: list[list[int]] = []

    def assess_blocks(self, title, blocks):
        del title
        self.calls += 1
        self.block_ids.append([block.block_id for block in blocks])
        answers = {}
        for block in blocks:
            sermon = "SERMON" in block.text
            choice = "principal_sermon" if sermon else "administration_or_transition"
            probabilities = {role: 0.0 for role in ROLE_CHOICES}
            probabilities[choice] = 0.95
            probabilities["unclear"] = 0.05
            answers[block.block_id] = TypeSafeBlockAnswer(
                choice,
                probabilities,
                0.9,
                "jev-1.13.0",
            )
        return answers


def drafts() -> list[SegmentDraft]:
    result = []
    for index in range(40):
        text = "SERMON sustained biblical exposition" if 10 <= index < 30 else "SERVICE announcements"
        result.append(
            SegmentDraft(
                index * 30.0,
                (index + 1) * 30.0,
                text,
                None,
                TranscriptSegmentLabel.UNKNOWN,
                0.5,
            )
        )
    return result


def rule_window() -> SermonWindowResult:
    return SermonWindowResult(
        0.0,
        300.0,
        0.8,
        ["fixture"],
        "rule_based_v1",
        list(range(10)),
        list(range(10, 40)),
        False,
        [],
    )


class TypeSafeFirstPassTests(unittest.TestCase):
    def test_finds_span_not_limited_to_rule_window(self) -> None:
        client = FakeBlockClient()
        classifier = TypeSafeFirstPassSermonClassifier(
            model="jev-1.13.0",
            client=client,
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = classifier.classify_sermon(
                drafts(),
                rule_window(),
                title="Worship Service",
                cache_dir=Path(tmp),
            )

        self.assertEqual("typesafe_first_v1", result.method)
        self.assertEqual("high", result.confidence_tier)
        self.assertEqual(list(range(10, 30)), result.retained_segment_indexes)
        candidate = result.search["candidates"][0]
        self.assertEqual(300.0, candidate["start_seconds"])
        self.assertEqual(900.0, candidate["end_seconds"])
        self.assertEqual("typesafe_first", candidate["source"])
        self.assertGreaterEqual(
            candidate["boundary_recovery"]["start"]["transition_strength"],
            0.72,
        )

    def test_item_cache_prevents_duplicate_jev_requests(self) -> None:
        client = FakeBlockClient()
        classifier = TypeSafeFirstPassSermonClassifier(
            model="jev-1.13.0",
            client=client,
        )
        with tempfile.TemporaryDirectory() as tmp:
            first = classifier.classify_sermon(
                drafts(), rule_window(), title="Worship Service", cache_dir=Path(tmp)
            )
            first_call_count = client.calls
            second = classifier.classify_sermon(
                drafts(), rule_window(), title="Worship Service", cache_dir=Path(tmp)
            )

        self.assertGreater(first_call_count, 0)
        self.assertEqual(first_call_count, client.calls)
        self.assertGreater(first.cache_stats["misses"], 0)
        self.assertEqual(0, second.cache_stats["misses"])
        self.assertEqual(first.cache_stats["misses"], second.cache_stats["hits"])

    def test_item_cache_survives_changed_batch_composition(self) -> None:
        client = FakeBlockClient()
        blocks = build_transcript_blocks(
            drafts(), target_seconds=300.0, max_chars=9000
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache = TypeSafeBlockCache(Path(tmp), model="jev-1.13.0")
            cache.assess(client, "Worship Service", blocks[:2])
            first_call_count = client.calls
            cache.assess(client, "Worship Service", blocks)

        self.assertEqual(first_call_count + 1, client.calls)
        self.assertEqual(2, cache.hits)
        self.assertEqual(len(blocks), cache.misses)

    def test_currentness_tracks_typesafe_first_versions(self) -> None:
        classification = {
            "method": SEARCH_ALGORITHM_VERSION,
            "block_builder_version": BLOCK_BUILDER_VERSION,
            "coarse_discovery_version": COARSE_DISCOVERY_VERSION,
            "fine_component_version": FINE_COMPONENT_VERSION,
            "model": "jev-1.13.0",
            "prompt_version": QUESTION_SET_VERSION,
            "confidence_policy_version": "typesafe-boundary-confidence-v1",
            "window_arbitration_policy_version": WINDOW_ARBITRATION_POLICY_VERSION,
            "recording_verification": {"source": "not_required", "reason_codes": []},
        }

        self.assertTrue(
            _classification_is_current(
                classification,
                model="jev-1.13.0",
                prompt_version=QUESTION_SET_VERSION,
                method=SEARCH_ALGORITHM_VERSION,
                block_builder_version=BLOCK_BUILDER_VERSION,
                coarse_discovery_version=COARSE_DISCOVERY_VERSION,
                fine_component_version=FINE_COMPONENT_VERSION,
                confidence_policy_version="typesafe-boundary-confidence-v1",
            )
        )

    def test_typesafe_local_edges_resolve_rule_disagreement(self) -> None:
        client = FakeBlockClient()
        classifier = TypeSafeFirstPassSermonClassifier(
            model="jev-1.13.0", client=client
        )
        transcript = drafts()
        with tempfile.TemporaryDirectory() as tmp:
            result = classifier.classify_sermon(
                transcript,
                rule_window(),
                title="Worship Service",
                cache_dir=Path(tmp),
            )
        window = {
            "source": "detected",
            "method": "rule_based_v1",
            "start_seconds": 0.0,
            "end_seconds": 300.0,
            "confidence": 0.8,
            "included_segment_indexes": list(range(10)),
            "excluded_segment_indexes": list(range(10, 40)),
            "suspicious_boundary": False,
            "suspicious_boundary_reasons": [],
        }

        arbitration = _arbitrate_hybrid_window(
            window,
            transcript,
            result,
            recording_sermon_confirmed=True,
            recording_single_sustained_message=True,
        )

        self.assertEqual((300.0, 900.0), (window["start_seconds"], window["end_seconds"]))
        self.assertEqual("adaptive_selected", arbitration["decision"])
        self.assertFalse(arbitration["unresolved_material_edge_disagreement"])
        self.assertTrue(
            all(
                edge.get("resolution")
                == "adaptive_boundary_has_typesafe_local_transition"
                for edge in arbitration["edge_decisions"]
            )
        )


if __name__ == "__main__":
    unittest.main()
