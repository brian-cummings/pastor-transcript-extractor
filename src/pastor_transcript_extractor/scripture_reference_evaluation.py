from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path

from pastor_transcript_extractor.sermon_analysis import (
    detect_scripture_references_in_texts,
)


@dataclass(frozen=True, slots=True)
class DetectionMetrics:
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
class ScriptureDetectionEvaluation:
    corpus_version: str
    case_count: int
    passed_case_count: int
    overall: DetectionMetrics
    by_class: dict[str, DetectionMetrics]
    method_detection_counts: dict[str, int]
    failures: tuple[dict[str, object], ...]


def _key(item: dict[str, object]) -> tuple[str, str]:
    reference = item.get("canonical_reference")
    detection_class = item.get("detection_class")
    if not isinstance(reference, str) or detection_class not in {"explicit", "contextual"}:
        raise ValueError("Each expected reference needs canonical_reference and detection_class")
    return reference, str(detection_class)


def evaluate_scripture_detector(fixture_path: Path) -> ScriptureDetectionEvaluation:
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read reviewed Scripture fixture {fixture_path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Reviewed Scripture fixture must use schema_version 1")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Reviewed Scripture fixture has no cases")

    totals = Counter[str]()
    class_totals: dict[str, Counter[str]] = {
        "explicit": Counter(),
        "contextual": Counter(),
    }
    method_counts: Counter[str] = Counter()
    failures: list[dict[str, object]] = []
    passed = 0
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("Every reviewed Scripture case needs an id")
        segments = case.get("segments")
        expected = case.get("expected")
        if (
            not isinstance(segments, list)
            or not all(isinstance(text, str) for text in segments)
            or not isinstance(expected, list)
            or not all(isinstance(item, dict) for item in expected)
        ):
            raise ValueError(f"Invalid reviewed Scripture case: {case['id']}")
        detected = detect_scripture_references_in_texts(segments)
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
        for detection_class in ("explicit", "contextual"):
            class_totals[detection_class]["tp"] += sum(
                count for (_, kind), count in intersection.items() if kind == detection_class
            )
            class_totals[detection_class]["fp"] += sum(
                count for (_, kind), count in extras.items() if kind == detection_class
            )
            class_totals[detection_class]["fn"] += sum(
                count for (_, kind), count in missing.items() if kind == detection_class
            )
        for item in detected:
            method = item.get("detection_method")
            if isinstance(method, str):
                method_counts[method] += 1
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

    def metrics(counter: Counter[str]) -> DetectionMetrics:
        return DetectionMetrics(
            true_positive=counter["tp"],
            false_positive=counter["fp"],
            false_negative=counter["fn"],
            true_negative_cases=counter["tn_cases"],
        )

    return ScriptureDetectionEvaluation(
        corpus_version=str(payload.get("corpus_version", "unknown")),
        case_count=len(cases),
        passed_case_count=passed,
        overall=metrics(totals),
        by_class={key: metrics(value) for key, value in class_totals.items()},
        method_detection_counts=dict(sorted(method_counts.items())),
        failures=tuple(failures),
    )
