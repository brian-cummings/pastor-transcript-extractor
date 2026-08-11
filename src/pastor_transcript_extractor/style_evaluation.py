from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path

from pastor_transcript_extractor.local_llm import LocalLlmClient
from pastor_transcript_extractor.semantic_evidence import (
    SemanticBlock,
    SemanticSegment,
)
from pastor_transcript_extractor.style_analysis import (
    STYLE_DIMENSIONS,
    STYLE_OUTPUT_TOKEN_BUDGET,
    STYLE_PROMPT_VERSION,
    style_proposal_schema,
    style_prompt,
    validate_style_proposals,
)


@dataclass(frozen=True, slots=True)
class StyleMetrics:
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
class StyleEvaluationResult:
    corpus_version: str
    model: str
    model_digest: str
    prompt_version: str
    case_count: int
    passed_case_count: int
    overall: StyleMetrics
    by_dimension: dict[str, StyleMetrics]
    rejected_proposal_count: int
    failures: tuple[dict[str, object], ...]


def evaluate_style_model(
    fixture_path: Path,
    client: LocalLlmClient,
    *,
    model_digest: str,
    prompt_version: str = STYLE_PROMPT_VERSION,
) -> StyleEvaluationResult:
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read reviewed style fixture {fixture_path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Reviewed style fixture must use schema_version 1")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Reviewed style fixture has no cases")

    totals: Counter[str] = Counter()
    dimension_totals = {dimension: Counter[str]() for dimension in STYLE_DIMENSIONS}
    failures: list[dict[str, object]] = []
    passed = 0
    rejected = 0
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("Every reviewed style case needs an id")
        texts = case.get("segments")
        expected = case.get("expected_dimensions")
        if (
            not isinstance(texts, list)
            or not texts
            or not all(isinstance(text, str) for text in texts)
            or not isinstance(expected, list)
            or not all(dimension in STYLE_DIMENSIONS for dimension in expected)
        ):
            raise ValueError(f"Invalid reviewed style case: {case['id']}")
        segments = tuple(
            SemanticSegment(index, text, index * 20.0, (index + 1) * 20.0)
            for index, text in enumerate(texts)
        )
        block = SemanticBlock(0, segments)
        response = client.generate_json(
            style_prompt(block, None, None, prompt_version=prompt_version),
            style_proposal_schema(block),
            max_tokens=STYLE_OUTPUT_TOKEN_BUDGET,
        )
        validation = validate_style_proposals(response.content, block)
        rejected += sum(validation.rejection_counts.values())
        detected_set = {proposal.dimension for proposal in validation.accepted}
        expected_set = set(expected)
        intersection = expected_set & detected_set
        extras = detected_set - expected_set
        missing = expected_set - detected_set
        totals["tp"] += len(intersection)
        totals["fp"] += len(extras)
        totals["fn"] += len(missing)
        if not expected_set and not detected_set:
            totals["tn_cases"] += 1
        for dimension in STYLE_DIMENSIONS:
            if dimension in intersection:
                dimension_totals[dimension]["tp"] += 1
            if dimension in extras:
                dimension_totals[dimension]["fp"] += 1
            if dimension in missing:
                dimension_totals[dimension]["fn"] += 1
        if expected_set == detected_set:
            passed += 1
        else:
            failures.append(
                {
                    "case_id": case["id"],
                    "expected": sorted(expected_set),
                    "detected": sorted(detected_set),
                }
            )

    def metrics(counter: Counter[str]) -> StyleMetrics:
        return StyleMetrics(
            true_positive=counter["tp"],
            false_positive=counter["fp"],
            false_negative=counter["fn"],
            true_negative_cases=counter["tn_cases"],
        )

    return StyleEvaluationResult(
        corpus_version=str(payload.get("corpus_version", "unknown")),
        model=client.model,
        model_digest=model_digest,
        prompt_version=prompt_version,
        case_count=len(cases),
        passed_case_count=passed,
        overall=metrics(totals),
        by_dimension={
            key: metrics(value) for key, value in dimension_totals.items()
        },
        rejected_proposal_count=rejected,
        failures=tuple(failures),
    )
