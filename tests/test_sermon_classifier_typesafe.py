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
    TypeSafeBoundaryAnswer,
    TypeSafeBoundarySelection,
    TypeSafeBlockAnswer,
    TypeSafeBlockCache,
    TypeSafeFirstPassSermonClassifier,
    _boundary_candidates,
)
from pastor_transcript_extractor.sermon_classification import (
    TranscriptBlock,
    build_transcript_blocks,
)
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

    def select_boundary_candidate(self, title, edge, candidates):
        del title, edge
        self.calls += 1
        selected = next(
            (
                candidate
                for candidate in candidates
                if "CLOSING PRAYER" in candidate.before_text
            ),
            None,
        )
        choice = selected.candidate_id if selected is not None else "no_clear_boundary"
        return TypeSafeBoundarySelection(
            choice,
            {choice: 0.9},
            0.9,
            "jev-1.13.0",
        )

    def validate_boundary_candidate(self, title, edge, candidate):
        del title, edge
        self.calls += 1
        return TypeSafeBoundaryAnswer(
            0.9 if "CLOSING PRAYER" in candidate.before_text else 0.1,
            "jev-1.13.0",
        )


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

        self.assertEqual(SEARCH_ALGORITHM_VERSION, result.method)
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

    def test_refines_weak_end_inside_adjacent_mixed_block_and_caches_it(self) -> None:
        class MixedEdgeClient(FakeBlockClient):
            def assess_blocks(self, title, blocks):
                answers = super().assess_blocks(title, blocks)
                for block in blocks:
                    if "CLOSING PRAYER" not in block.text:
                        continue
                    probabilities = {role: 0.0 for role in ROLE_CHOICES}
                    probabilities["principal_sermon"] = 0.4
                    probabilities["administration_or_transition"] = 0.55
                    probabilities["unclear"] = 0.05
                    answers[block.block_id] = TypeSafeBlockAnswer(
                        "administration_or_transition",
                        probabilities,
                        0.4,
                        "jev-1.13.0",
                    )
                return answers

        transcript = drafts()
        transcript[30] = SegmentDraft(
            900.0,
            930.0,
            "CLOSING PRAYER in your name we pray amen",
            None,
            TranscriptSegmentLabel.UNKNOWN,
            0.5,
        )
        transcript[31] = SegmentDraft(
            930.0,
            960.0,
            "SERVICE ADMIN final hymn and luncheon",
            None,
            TranscriptSegmentLabel.UNKNOWN,
            0.5,
        )
        client = MixedEdgeClient()
        classifier = TypeSafeFirstPassSermonClassifier(
            model="jev-1.13.0", client=client
        )
        with tempfile.TemporaryDirectory() as tmp:
            first = classifier.classify_sermon(
                transcript,
                rule_window(),
                title="Worship Service",
                cache_dir=Path(tmp),
            )
            first_calls = client.calls
            second = classifier.classify_sermon(
                transcript,
                rule_window(),
                title="Worship Service",
                cache_dir=Path(tmp),
            )

        candidate = first.search["candidates"][0]
        refinement = candidate["boundary_recovery"]["end"]["segment_refinement"]
        self.assertEqual(930.0, candidate["end_seconds"])
        self.assertIn(30, first.retained_segment_indexes)
        self.assertNotIn(31, first.retained_segment_indexes)
        self.assertTrue(refinement["accepted"])
        self.assertEqual("high", first.confidence_tier)
        self.assertEqual(first_calls, client.calls)
        self.assertEqual(0, second.cache_stats["misses"])

    def test_boundary_candidates_can_move_inside_selected_or_into_outside_block(self) -> None:
        transcript = [
            SegmentDraft(
                float(index * 10),
                float((index + 1) * 10),
                f"segment {index}",
                None,
                TranscriptSegmentLabel.UNKNOWN,
                0.5,
            )
            for index in range(4)
        ]
        selected = TranscriptBlock(1, [0, 1], 0.0, 20.0, "selected")
        outside = TranscriptBlock(2, [2, 3], 20.0, 40.0, "outside")

        candidates = _boundary_candidates(
            transcript,
            edge="end",
            selected_indexes=[0, 1],
            neighborhood_blocks=[selected, outside],
        )

        by_boundary = {
            candidate.boundary_seconds: candidate.retained_segment_indexes
            for candidate in candidates
        }
        self.assertEqual((0,), by_boundary[10.0])
        self.assertEqual((0, 1, 2), by_boundary[30.0])

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
