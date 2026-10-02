from __future__ import annotations

from dataclasses import asdict
import json
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
    FINE_PARENT_CONTEXT_KEY,
    FINE_COMPONENT_VERSION,
    QUESTION_SET_VERSION,
    ROLE_CHOICES,
    SEARCH_ALGORITHM_VERSION,
    TypeSafeBoundaryAnswer,
    TypeSafeBoundarySelection,
    TypeSafeBlockAnswer,
    TypeSafeBlockCache,
    TypeSafeFirstPassSermonClassifier,
    TypeSafeRecordingGateAnswer,
    ROLE_PACK,
    TOPIC_PACK,
    TREATMENT_PACK,
    _boundary_candidates,
    _candidate_components,
    _edge_neighborhood,
    _hash,
    _semantic_analysis_artifact,
    _topic_analysis_artifact,
)
from pastor_transcript_extractor.sermon_semantic_dimensions import (
    SEMANTIC_ANALYSIS_QUESTION_VERSION,
    SEMANTIC_DIMENSIONS,
    semantic_question_inventory,
)
from pastor_transcript_extractor.sermon_classification import (
    TranscriptBlock,
    build_transcript_blocks,
)
from pastor_transcript_extractor.sermon_topics import (
    TOPIC_PACK_VERSION,
    TOPICS,
    build_topic_context,
    topic_pack_inventory,
    topic_question_inventory,
)
from pastor_transcript_extractor.sermon_detection import SermonWindowResult


class FakeBlockClient:
    def __init__(self) -> None:
        self.calls = 0
        self.block_ids: list[list[int]] = []
        self.gate_states: list[dict] = []
        self.recording_contexts: list[dict] = []
        self.requested_packs: list[frozenset[str]] = []

    def assess_recording_gate(self, state):
        self.gate_states.append(dict(state))
        self.calls += 1
        probabilities = {
            "target_worship_service_or_sermon": 0.97,
            "unclear": 0.03,
        }
        return TypeSafeRecordingGateAnswer(
            "target_worship_service_or_sermon",
            probabilities,
            0.95,
            "jev-1.13.0",
        )

    def assess_blocks(
        self,
        recording_context,
        blocks,
        *,
        collect_semantic_analysis=False,
        collect_topic_analysis=False,
        requested_packs=None,
        topic_contexts=None,
    ):
        self.recording_contexts.append(dict(recording_context))
        self.calls += 1
        self.block_ids.append([block.block_id for block in blocks])
        answers = {}
        packs = requested_packs or frozenset(
            {
                ROLE_PACK,
                *([TREATMENT_PACK] if collect_semantic_analysis else []),
                *([TOPIC_PACK] if collect_topic_analysis else []),
            }
        )
        self.requested_packs.append(frozenset(packs))
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
                (
                    {
                        dimension: (
                            0.8 if sermon and dimension == "exegetical_exposition" else 0.1
                        )
                        for dimension in SEMANTIC_DIMENSIONS
                    }
                    if TREATMENT_PACK in packs
                    else {}
                ),
                (
                    SEMANTIC_ANALYSIS_QUESTION_VERSION
                    if TREATMENT_PACK in packs
                    else None
                ),
                (
                    {
                        topic: {
                            "score": 3.0 if sermon and topic == "salvation_gospel" else 0.0,
                            "probabilities": {
                                "0": 0.0 if sermon and topic == "salvation_gospel" else 1.0,
                                "1": 0.0,
                                "2": 0.0,
                                "3": 1.0 if sermon and topic == "salvation_gospel" else 0.0,
                                "4": 0.0,
                            },
                            "confidence": 0.9,
                        }
                        for topic in TOPICS
                    }
                    if TOPIC_PACK in packs
                    else {}
                ),
                TOPIC_PACK_VERSION if TOPIC_PACK in packs else None,
                (
                    {
                        **topic_contexts[block.block_id].state_payload(),
                        "diagnostics": dict(topic_contexts[block.block_id].diagnostics),
                    }
                    if TOPIC_PACK in packs and topic_contexts
                    else {}
                ),
                {"request_key": f"request-{self.calls}"},
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
                recording_metadata={
                    "title": "Worship Service",
                    "description": "Weekly divine worship livestream",
                },
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
        self.assertEqual(
            "Weekly divine worship livestream",
            client.gate_states[0]["metadata"]["description"],
        )
        context = client.recording_contexts[0]
        self.assertTrue(context["deterministic_detection"]["window_found"])
        self.assertEqual(300.0, context["deterministic_detection"]["duration_seconds"])
        self.assertTrue(context["recording_outline"])
        fine_contexts = [
            item
            for item in client.recording_contexts
            if FINE_PARENT_CONTEXT_KEY in item
        ]
        self.assertTrue(fine_contexts)
        for fine_context in fine_contexts:
            parent_findings = fine_context[FINE_PARENT_CONTEXT_KEY]
            self.assertTrue(parent_findings)
            for finding in parent_findings.values():
                self.assertIn("advisory", finding["policy"].lower())
                self.assertTrue(finding["coarse_findings"])
                primary = [
                    item
                    for item in finding["coarse_findings"]
                    if item["primary_parent"]
                ]
                self.assertEqual(1, len(primary))
                self.assertIn(primary[0]["selected_role"], ROLE_CHOICES)
                self.assertIn("sermon_probability", primary[0])
                self.assertIn("candidate_component", primary[0])
        semantic = result.search["semantic_analysis"]
        self.assertEqual("observations_only", semantic["status"])
        self.assertEqual("none", semantic["policy_effect"])
        self.assertEqual(
            SEMANTIC_ANALYSIS_QUESTION_VERSION,
            semantic["question_version"],
        )
        self.assertEqual(list(SEMANTIC_DIMENSIONS), semantic["dimensions"])
        self.assertTrue(semantic["blocks"])
        self.assertTrue(
            any(item["within_selected_candidate"] for item in semantic["blocks"])
        )
        self.assertEqual(
            set(SEMANTIC_DIMENSIONS),
            set(semantic["blocks"][0]["probabilities"]),
        )

    def test_semantic_question_inventory_uses_shared_dimension_inventory(self) -> None:
        inventory = semantic_question_inventory(2)

        self.assertEqual(len(SEMANTIC_DIMENSIONS), len(inventory))
        self.assertEqual(
            set(SEMANTIC_DIMENSIONS),
            {item["dimension"] for item in inventory.values()},
        )
        self.assertTrue(
            all("`target_blocks[2].text`" in str(item["instructions"])
                for item in inventory.values())
        )

    def test_topic_inventory_has_twenty_independent_five_level_scores(self) -> None:
        inventory = topic_question_inventory(3)

        self.assertEqual(20, len(TOPICS))
        self.assertEqual(20, len(inventory))
        self.assertEqual(
            set(TOPICS), {item["topic"] for item in inventory.values()}
        )
        self.assertTrue(all(len(item["criteria"]) == 5 for item in inventory.values()))
        self.assertTrue(
            all(
                "`topic_blocks[3].target_text`" in str(item["instructions"])
                for item in inventory.values()
            )
        )
        domains = topic_pack_inventory()["domains"]
        self.assertEqual(4, len(domains))
        self.assertTrue(all(not domain["scored"] for domain in domains.values()))

    def test_topic_context_is_bounded_and_keeps_target_text_exact(self) -> None:
        transcript = [
            SegmentDraft(0.0, 10.0, "Earlier complete sentence. " * 40, None, TranscriptSegmentLabel.UNKNOWN, 0.5),
            SegmentDraft(10.0, 20.0, "Exact target text", None, TranscriptSegmentLabel.UNKNOWN, 0.5),
            SegmentDraft(20.0, 30.0, "Following complete sentence. " * 40, None, TranscriptSegmentLabel.UNKNOWN, 0.5),
        ]
        block = TranscriptBlock(7, [1], 10.0, 20.0, "Exact target text")

        context = build_topic_context(transcript, block)

        self.assertEqual("Exact target text", context.target_text)
        self.assertLessEqual(len(context.leading_context), 400)
        self.assertLessEqual(len(context.trailing_context), 400)
        self.assertEqual("topic-context-sentences-v1", context.diagnostics["policy_version"])
        self.assertLessEqual(
            context.diagnostics["leading"]["selected_sentence_units"], 2
        )
        self.assertLessEqual(
            context.diagnostics["trailing"]["selected_sentence_units"], 2
        )

    def test_topic_artifact_preserves_complete_scores_density_and_overlap(self) -> None:
        transcript = [
            SegmentDraft(0.0, 30.0, "[Music]", None, TranscriptSegmentLabel.MUSIC, 0.9),
            SegmentDraft(30.0, 60.0, "Grace saves us.", None, TranscriptSegmentLabel.UNKNOWN, 0.5),
        ]
        block = TranscriptBlock(2, [0, 1], 0.0, 60.0, "[Music]\nGrace saves us.")
        context = build_topic_context(transcript, block)
        answer = TypeSafeBlockAnswer(
            "principal_sermon",
            {"principal_sermon": 1.0},
            1.0,
            "jev-1.13.0",
            topic_scores={
                topic: {
                    "score": 2.0,
                    "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0, "3": 0.0, "4": 0.0},
                    "confidence": 1.0,
                }
                for topic in TOPICS
            },
            topic_question_version=TOPIC_PACK_VERSION,
            topic_context={
                **context.state_payload(),
                "diagnostics": dict(context.diagnostics),
            },
            request_provenance={
                TOPIC_PACK: {
                    "request_key": "request-1",
                    "question_count": 20,
                    "input_tokens": 10,
                    "output_tokens": 20,
                }
            },
        )

        artifact = _topic_analysis_artifact(
            [block],
            {block.block_id: answer},
            requested_model_id="jev-1.13.0",
            retained_segment_indexes={1},
            selected_start_seconds=30.0,
            selected_end_seconds=60.0,
        )

        self.assertEqual("observations_only", artifact["status"])
        self.assertEqual("none", artifact["policy_effect"])
        self.assertEqual(20, len(artifact["inventory"]["topics"]))
        observation = artifact["blocks"][0]
        self.assertEqual(set(TOPICS), set(observation["scores"]))
        self.assertTrue(observation["reliability"]["sparse"])
        self.assertEqual(30.0, observation["reliability"]["final_sermon_overlap_seconds"])
        self.assertEqual([1], observation["reliability"]["retained_source_segment_indexes"])
        self.assertEqual(1, len(artifact["provider_requests"]))

    def test_semantic_artifact_ignores_role_only_answers(self) -> None:
        block = TranscriptBlock(1, [3], 10.0, 20.0, "sermon text")
        answer = TypeSafeBlockAnswer(
            "principal_sermon",
            {"principal_sermon": 1.0},
            1.0,
            "jev-1.13.0",
        )

        artifact = _semantic_analysis_artifact([block], {1: answer})

        self.assertEqual("not_collected", artifact["status"])
        self.assertEqual([], artifact["blocks"])

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
            context = {"metadata": {"title": "Worship Service"}}
            cache.assess(client, context, blocks[:2])
            first_call_count = client.calls
            cache.assess(client, context, blocks)

        self.assertEqual(first_call_count + 1, client.calls)
        self.assertEqual(2, cache.hits)
        self.assertEqual(len(blocks), cache.misses)

    def test_semantic_question_pack_has_separate_cache_identity(self) -> None:
        client = FakeBlockClient()
        block = build_transcript_blocks(
            drafts(), target_seconds=300.0, max_chars=9000
        )[0]
        context = {"metadata": {"title": "Worship Service"}}
        with tempfile.TemporaryDirectory() as tmp:
            cache = TypeSafeBlockCache(Path(tmp), model="jev-1.13.0")
            role_only = cache.assess(client, context, [block])
            with_semantics = cache.assess(
                client,
                context,
                [block],
                collect_semantic_analysis=True,
            )
            calls_after_both = client.calls
            replay = cache.assess(
                client,
                context,
                [block],
                collect_semantic_analysis=True,
            )

        self.assertEqual({}, role_only[block.block_id].semantic_probabilities)
        self.assertEqual(
            set(SEMANTIC_DIMENSIONS),
            set(with_semantics[block.block_id].semantic_probabilities),
        )
        self.assertEqual(calls_after_both, client.calls)
        self.assertEqual(
            with_semantics[block.block_id].semantic_probabilities,
            replay[block.block_id].semantic_probabilities,
        )

    def test_missing_pack_planner_reuses_role_and_treatment_for_topic_addition(self) -> None:
        client = FakeBlockClient()
        block = build_transcript_blocks(
            drafts(), target_seconds=300.0, max_chars=9000
        )[0]
        context = {"metadata": {"title": "Worship Service"}}
        topic_context = {block.block_id: build_topic_context(drafts(), block)}
        with tempfile.TemporaryDirectory() as tmp:
            cache = TypeSafeBlockCache(Path(tmp), model="jev-1.13.0")
            cache.assess(
                client,
                context,
                [block],
                collect_semantic_analysis=True,
            )
            enriched = cache.assess(
                client,
                context,
                [block],
                collect_semantic_analysis=True,
                collect_topic_analysis=True,
                topic_contexts=topic_context,
            )
            calls_after_enrichment = client.calls
            replay = cache.assess(
                client,
                context,
                [block],
                collect_semantic_analysis=True,
                collect_topic_analysis=True,
                topic_contexts=topic_context,
            )

        self.assertEqual(frozenset({ROLE_PACK, TREATMENT_PACK}), client.requested_packs[0])
        self.assertEqual(frozenset({TOPIC_PACK}), client.requested_packs[1])
        self.assertEqual(calls_after_enrichment, client.calls)
        self.assertEqual(set(TOPICS), set(enriched[block.block_id].topic_scores))
        self.assertEqual(
            enriched[block.block_id].topic_scores,
            replay[block.block_id].topic_scores,
        )

    def test_legacy_combined_cache_is_migrated_without_provider_call(self) -> None:
        client = FakeBlockClient()
        block = build_transcript_blocks(
            drafts(), target_seconds=300.0, max_chars=9000
        )[0]
        context = {"metadata": {"title": "Worship Service"}}
        legacy_answer = TypeSafeBlockAnswer(
            "principal_sermon",
            {"principal_sermon": 0.95, "unclear": 0.05},
            0.9,
            "jev-1.13.0",
            {dimension: 0.25 for dimension in SEMANTIC_DIMENSIONS},
            SEMANTIC_ANALYSIS_QUESTION_VERSION,
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache = TypeSafeBlockCache(Path(tmp), model="jev-1.13.0")
            identity = cache._legacy_identity(
                context, block, include_semantic=True
            )
            path = cache.root / f"{_hash(identity)}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"identity": identity, "answer": asdict(legacy_answer)}),
                encoding="utf-8",
            )

            migrated = cache.assess(
                client,
                context,
                [block],
                collect_semantic_analysis=True,
            )

        self.assertEqual(0, client.calls)
        self.assertEqual("principal_sermon", migrated[block.block_id].choice)
        self.assertEqual(
            set(SEMANTIC_DIMENSIONS),
            set(migrated[block.block_id].semantic_probabilities),
        )
        self.assertEqual(0, cache.misses)

    def test_recording_gate_bypasses_localization_and_is_cached(self) -> None:
        class SabbathSchoolClient(FakeBlockClient):
            def __init__(self) -> None:
                super().__init__()
                self.block_calls = 0

            def assess_recording_gate(self, state):
                del state
                self.calls += 1
                return TypeSafeRecordingGateAnswer(
                    "religious_education_or_bible_class",
                    {
                        "religious_education_or_bible_class": 0.97,
                        "target_worship_service_or_sermon": 0.02,
                        "unclear": 0.01,
                    },
                    0.95,
                    "jev-1.13.0",
                )

            def assess_blocks(
                self, recording_context, blocks, *, collect_semantic_analysis=False, **kwargs
            ):
                self.block_calls += 1
                return super().assess_blocks(
                    recording_context,
                    blocks,
                    collect_semantic_analysis=collect_semantic_analysis,
                    **kwargs,
                )

        client = SabbathSchoolClient()
        classifier = TypeSafeFirstPassSermonClassifier(
            model="jev-1.13.0",
            client=client,
        )
        metadata = {
            "title": "Sabbath School Lesson",
            "description": "Quarterly lesson study",
        }
        with tempfile.TemporaryDirectory() as tmp:
            first = classifier.classify_sermon(
                drafts(),
                rule_window(),
                title=metadata["title"],
                recording_metadata=metadata,
                cache_dir=Path(tmp),
            )
            second = classifier.classify_sermon(
                drafts(),
                rule_window(),
                title=metadata["title"],
                recording_metadata=metadata,
                cache_dir=Path(tmp),
            )

        self.assertEqual(1, client.calls)
        self.assertEqual(0, client.block_calls)
        self.assertEqual([], first.retained_segment_indexes)
        gate = first.search["discovery"]["recording_gate"]
        self.assertEqual("bypass_non_target", gate["route"])
        self.assertEqual(0, second.cache_stats["misses"])

    def test_refines_weak_end_inside_adjacent_mixed_block_and_caches_it(self) -> None:
        class MixedEdgeClient(FakeBlockClient):
            def assess_blocks(
                self, title, blocks, *, collect_semantic_analysis=False, **kwargs
            ):
                answers = super().assess_blocks(
                    title,
                    blocks,
                    collect_semantic_analysis=collect_semantic_analysis,
                    **kwargs,
                )
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

    def test_refines_high_strength_edge_when_outside_block_is_mixed(self) -> None:
        class MixedOutsideClient(FakeBlockClient):
            def assess_blocks(
                self, title, blocks, *, collect_semantic_analysis=False, **kwargs
            ):
                answers = super().assess_blocks(
                    title,
                    blocks,
                    collect_semantic_analysis=collect_semantic_analysis,
                    **kwargs,
                )
                for block in blocks:
                    if "CLOSING PRAYER" not in block.text:
                        continue
                    probabilities = {role: 0.0 for role in ROLE_CHOICES}
                    probabilities["principal_sermon"] = 0.2
                    probabilities["administration_or_transition"] = 0.75
                    probabilities["unclear"] = 0.05
                    answers[block.block_id] = TypeSafeBlockAnswer(
                        "administration_or_transition",
                        probabilities,
                        0.6,
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
        classifier = TypeSafeFirstPassSermonClassifier(
            model="jev-1.13.0", client=MixedOutsideClient()
        )

        with tempfile.TemporaryDirectory() as tmp:
            result = classifier.classify_sermon(
                transcript,
                rule_window(),
                title="Worship Service",
                cache_dir=Path(tmp),
            )

        candidate = result.search["candidates"][0]
        edge = candidate["boundary_recovery"]["end"]
        self.assertEqual(0.2, edge["outside_probability"])
        self.assertEqual(930.0, candidate["end_seconds"])
        self.assertTrue(edge["segment_refinement"]["accepted"])

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

    def test_boundary_candidates_collapse_subsecond_caption_duplicates(self) -> None:
        transcript = [
            SegmentDraft(
                start,
                end,
                text,
                None,
                TranscriptSegmentLabel.UNKNOWN,
                0.5,
            )
            for start, end, text in [
                (0.0, 10.0, "complete caption phrase"),
                (10.0, 10.01, "repeated caption tail"),
                (10.01, 20.0, "new material"),
            ]
        ]
        block = TranscriptBlock(1, [0, 1, 2], 0.0, 20.0, "combined")

        candidates = _boundary_candidates(
            transcript,
            edge="end",
            selected_indexes=[0, 1],
            neighborhood_blocks=[block],
        )

        self.assertEqual([10.0], [item.boundary_seconds for item in candidates])

    def test_edge_neighborhood_uses_elapsed_time_not_two_block_limit(self) -> None:
        blocks = [
            TranscriptBlock(
                index, [index], index * 70.0, (index + 1) * 70.0, str(index)
            )
            for index in range(7)
        ]

        neighborhood = _edge_neighborhood(blocks, 1, edge="end")

        self.assertEqual([1, 2, 3, 4], [block.block_id for block in neighborhood])

    def test_candidate_components_bridge_one_locally_ambiguous_block(self) -> None:
        blocks = [
            TranscriptBlock(
                index, [index], index * 60.0, (index + 1) * 60.0, str(index)
            )
            for index in range(4)
        ]

        def answer(
            probability: float, choice: str = "principal_sermon"
        ) -> TypeSafeBlockAnswer:
            probabilities = {role: 0.0 for role in ROLE_CHOICES}
            probabilities["principal_sermon"] = probability
            probabilities["administration_or_transition"] = 1.0 - probability
            return TypeSafeBlockAnswer(choice, probabilities, 0.5, "jev-1.13.0")

        components = _candidate_components(
            blocks,
            {
                0: answer(0.9),
                1: answer(0.57),
                2: answer(0.95),
                3: answer(0.1, "administration_or_transition"),
            },
            threshold=0.66,
        )

        self.assertEqual(
            [[0, 1, 2]],
            [[block.block_id for block in item] for item in components],
        )

    def test_candidate_components_do_not_bridge_confident_nonsermon_block(self) -> None:
        blocks = [
            TranscriptBlock(
                index, [index], index * 60.0, (index + 1) * 60.0, str(index)
            )
            for index in range(3)
        ]
        answers = {}
        for index, probability in enumerate((0.9, 0.1, 0.95)):
            probabilities = {role: 0.0 for role in ROLE_CHOICES}
            probabilities["principal_sermon"] = probability
            probabilities["administration_or_transition"] = 1.0 - probability
            answers[index] = TypeSafeBlockAnswer(
                "principal_sermon" if probability >= 0.5 else "administration_or_transition",
                probabilities,
                0.9,
                "jev-1.13.0",
            )

        components = _candidate_components(blocks, answers, threshold=0.66)

        self.assertEqual(
            [[0], [2]],
            [[block.block_id for block in item] for item in components],
        )

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
