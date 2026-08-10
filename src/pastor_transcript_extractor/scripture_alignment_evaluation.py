from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path

from pastor_transcript_extractor.scripture_alignment import (
    AlignmentSegment,
    ReferenceAnchor,
    bible_source_provenance,
    detect_scripture_alignments,
)
from pastor_transcript_extractor.sermon_analysis import (
    detect_scripture_references_in_texts,
)


@dataclass(frozen=True, slots=True)
class AlignmentMetrics:
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative_cases: int

    @property
    def precision(self) -> float:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else 1.0

    @property
    def recall(self) -> float:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else 1.0


@dataclass(frozen=True, slots=True)
class ScriptureAlignmentEvaluation:
    corpus_version: str
    case_count: int
    passed_case_count: int
    overall: AlignmentMetrics
    by_class: dict[str, AlignmentMetrics]
    bible_source: dict[str, object]
    failures: tuple[dict[str, object], ...]


def _key(item: dict[str, object]) -> tuple[str, str]:
    reference = item.get("canonical_reference")
    alignment_class = item.get("alignment_class")
    if not isinstance(reference, str) or alignment_class not in {
        "anchored",
        "independent",
    }:
        raise ValueError(
            "Each expected alignment needs canonical_reference and alignment_class"
        )
    return reference, str(alignment_class)


def evaluate_scripture_alignment(fixture_path: Path) -> ScriptureAlignmentEvaluation:
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read reviewed alignment fixture {fixture_path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Reviewed Scripture alignment fixture must use schema_version 1")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Reviewed Scripture alignment fixture has no cases")

    totals = Counter[str]()
    class_totals = {"anchored": Counter[str](), "independent": Counter[str]()}
    failures: list[dict[str, object]] = []
    passed = 0
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("Every reviewed alignment case needs an id")
        texts = case.get("segments")
        expected = case.get("expected")
        if (
            not isinstance(texts, list)
            or not all(isinstance(text, str) for text in texts)
            or not isinstance(expected, list)
            or not all(isinstance(item, dict) for item in expected)
        ):
            raise ValueError(f"Invalid reviewed alignment case: {case['id']}")
        references = detect_scripture_references_in_texts(texts)
        anchors = [
            ReferenceAnchor(
                segment_index=int(item["segment_index"]),
                book=str(item["book"]),
                chapter=(int(item["chapter"]) if item["chapter"] is not None else None),
                verse_start=(
                    int(item["verse_start"])
                    if item["verse_start"] is not None
                    else None
                ),
                verse_end=(
                    int(item["verse_end"]) if item["verse_end"] is not None else None
                ),
                canonical_reference=str(item["canonical_reference"]),
                detection_class=str(item["detection_class"]),
            )
            for item in references
        ]
        detected = detect_scripture_alignments(
            [AlignmentSegment(index=index, text=text) for index, text in enumerate(texts)],
            anchors,
        )
        expected_counter = Counter(_key(item) for item in expected)
        detected_counter = Counter(_key(item) for item in detected)
        intersection = expected_counter & detected_counter
        extras = detected_counter - expected_counter
        missing = expected_counter - detected_counter
        totals["tp"] += sum(intersection.values())
        totals["fp"] += sum(extras.values())
        totals["fn"] += sum(missing.values())
        if not expected_counter and not detected_counter:
            totals["tn_cases"] += 1
        for alignment_class in ("anchored", "independent"):
            class_totals[alignment_class]["tp"] += sum(
                count
                for (_, kind), count in intersection.items()
                if kind == alignment_class
            )
            class_totals[alignment_class]["fp"] += sum(
                count for (_, kind), count in extras.items() if kind == alignment_class
            )
            class_totals[alignment_class]["fn"] += sum(
                count for (_, kind), count in missing.items() if kind == alignment_class
            )
        if expected_counter == detected_counter:
            passed += 1
        else:
            failures.append(
                {
                    "case_id": case["id"],
                    "expected": sorted(expected_counter.elements()),
                    "detected": sorted(detected_counter.elements()),
                }
            )

    def metrics(counter: Counter[str]) -> AlignmentMetrics:
        return AlignmentMetrics(
            true_positive=counter["tp"],
            false_positive=counter["fp"],
            false_negative=counter["fn"],
            true_negative_cases=counter["tn_cases"],
        )

    return ScriptureAlignmentEvaluation(
        corpus_version=str(payload.get("corpus_version", "unknown")),
        case_count=len(cases),
        passed_case_count=passed,
        overall=metrics(totals),
        by_class={key: metrics(value) for key, value in class_totals.items()},
        bible_source=bible_source_provenance(),
        failures=tuple(failures),
    )
