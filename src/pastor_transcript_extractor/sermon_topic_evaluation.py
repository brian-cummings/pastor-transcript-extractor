"""Bounded evaluation for the reviewed TypeSafe sermon-topic behavior contract."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from pastor_transcript_extractor.sermon_classification import TranscriptBlock
from pastor_transcript_extractor.sermon_classifier_typesafe import (
    TOPIC_PACK,
    TypeSafeBlockCache,
    TypeSafeBlockClient,
)
from pastor_transcript_extractor.sermon_topics import (
    TOPIC_CONTEXT_POLICY_VERSION,
    TOPIC_PACK_VERSION,
    TOPICS,
    TopicBlockContext,
    topic_pack_digest,
)


TOPIC_BEHAVIOR_FIXTURE_SCHEMA_VERSION = 1
TOPIC_BEHAVIOR_EVALUATOR_VERSION = "typesafe-topic-behavior-evaluator-v1"
TOPIC_BEHAVIOR_REPORT_SCHEMA_VERSION = 1
DEFAULT_TOPIC_BEHAVIOR_FIXTURE = Path(
    "evaluation/sermon-topics/behavior-contract-v1.json"
)
REQUIRED_BEHAVIOR_TAGS = frozenset(
    {
        "prominence_absent",
        "prominence_incidental",
        "prominence_supporting",
        "prominence_substantial",
        "prominence_dominant",
        "overlap_jesus_salvation",
        "overlap_prophecy_adventist",
        "boundary_sin_discipleship",
        "boundary_mission_service",
        "boundary_ethics_public_life",
        "boundary_human_nature_creation",
        "sparse_caption",
        "performed_lyrics",
        "quotation",
        "negation",
        "rejected_alternative",
        "context_only_mention",
        "prodigal_illustration",
        "closing_prayer_sparse_gap",
        "spiritual_conflict_positive",
        "spiritual_conflict_exclusion",
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def load_topic_behavior_fixture(path: Path) -> dict[str, Any]:
    """Load and validate a frozen, specification-derived synthetic fixture."""
    path = path.expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read topic behavior fixture {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("Topic behavior fixture must be a JSON object")
    if payload.get("schema_version") != TOPIC_BEHAVIOR_FIXTURE_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported topic behavior fixture schema: "
            f"{payload.get('schema_version')}"
        )
    if payload.get("question_pack_version") != TOPIC_PACK_VERSION:
        raise ValueError(
            "Fixture question pack does not match current topic pack: "
            f"{payload.get('question_pack_version')} != {TOPIC_PACK_VERSION}"
        )
    fixture_id = payload.get("fixture_id")
    review = payload.get("review")
    if not isinstance(fixture_id, str) or not fixture_id.strip():
        raise ValueError("Topic behavior fixture requires fixture_id")
    if not isinstance(review, dict) or not all(
        isinstance(review.get(key), str) and review[key].strip()
        for key in ("status", "reviewer", "annotation_basis")
    ):
        raise ValueError("Topic behavior fixture requires explicit review provenance")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Topic behavior fixture requires cases")

    case_ids: set[str] = set()
    observed_tags: set[str] = set()
    for position, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"Topic behavior case {position} must be an object")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"Topic behavior case {position} requires case_id")
        if case_id in case_ids:
            raise ValueError(f"Duplicate topic behavior case id: {case_id}")
        case_ids.add(case_id)
        for key in ("label", "target_text", "reviewed_interpretation"):
            if not isinstance(case.get(key), str) or not case[key].strip():
                raise ValueError(f"Topic behavior case {case_id} requires {key}")
        for key in ("leading_context", "trailing_context"):
            if not isinstance(case.get(key, ""), str):
                raise ValueError(f"Topic behavior case {case_id} has invalid {key}")
        tags = case.get("tags")
        if not isinstance(tags, list) or not tags or not all(
            isinstance(tag, str) and tag.strip() for tag in tags
        ):
            raise ValueError(f"Topic behavior case {case_id} requires tags")
        observed_tags.update(tags)
        expectations = case.get("expectations")
        if not isinstance(expectations, dict) or not expectations:
            raise ValueError(f"Topic behavior case {case_id} requires expectations")
        unknown_topics = set(expectations) - set(TOPICS)
        if unknown_topics:
            raise ValueError(
                f"Topic behavior case {case_id} has unknown topics: "
                + ", ".join(sorted(unknown_topics))
            )
        for topic, expectation in expectations.items():
            if not isinstance(expectation, dict):
                raise ValueError(f"Case {case_id} expectation {topic} must be an object")
            minimum = _number(expectation.get("minimum_score"))
            maximum = _number(expectation.get("maximum_score"))
            rationale = expectation.get("rationale")
            if (
                minimum is None
                or maximum is None
                or not 0.0 <= minimum <= maximum <= 4.0
                or not isinstance(rationale, str)
                or not rationale.strip()
            ):
                raise ValueError(
                    f"Case {case_id} expectation {topic} requires a reviewed "
                    "0-4 score range and rationale"
                )

    declared_tags = payload.get("required_contract_tags")
    if not isinstance(declared_tags, list) or set(declared_tags) != REQUIRED_BEHAVIOR_TAGS:
        raise ValueError("Fixture required_contract_tags do not match the frozen contract")
    missing_tags = REQUIRED_BEHAVIOR_TAGS - observed_tags
    if missing_tags:
        raise ValueError(
            "Topic behavior fixture is missing contract coverage: "
            + ", ".join(sorted(missing_tags))
        )
    payload["fixture_path"] = str(path)
    payload["fixture_sha256"] = _sha256(
        {
            key: value
            for key, value in payload.items()
            if key not in {"fixture_path", "fixture_sha256"}
        }
    )
    return payload


def _blocks_and_contexts(
    fixture: Mapping[str, Any],
) -> tuple[list[TranscriptBlock], dict[int, TopicBlockContext]]:
    blocks: list[TranscriptBlock] = []
    contexts: dict[int, TopicBlockContext] = {}
    for position, case in enumerate(fixture["cases"]):
        block_id = position + 1
        start_seconds = float(position * 60)
        end_seconds = start_seconds + 60.0
        block = TranscriptBlock(
            block_id,
            [position],
            start_seconds,
            end_seconds,
            str(case["target_text"]),
        )
        blocks.append(block)
        contexts[block_id] = TopicBlockContext(
            str(case.get("leading_context", "")),
            str(case["target_text"]),
            str(case.get("trailing_context", "")),
            {
                "policy_version": TOPIC_CONTEXT_POLICY_VERSION,
                "source": "reviewed_behavior_fixture",
                "fixture_id": fixture["fixture_id"],
                "case_id": case["case_id"],
            },
        )
    return blocks, contexts


def _validated_score(
    *,
    case_id: str,
    topic: str,
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    score = _number(raw.get("score"))
    probabilities = raw.get("probabilities")
    if score is None or not 0.0 <= score <= 4.0 or not isinstance(probabilities, Mapping):
        raise ValueError(f"Case {case_id} has malformed {topic} Score")
    try:
        distribution = {
            str(level): float(probabilities[str(level)]) for level in range(5)
        }
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Case {case_id} has incomplete {topic} distribution") from error
    if any(not 0.0 <= probability <= 1.0 for probability in distribution.values()):
        raise ValueError(f"Case {case_id} has invalid {topic} probabilities")
    if not math.isclose(sum(distribution.values()), 1.0, abs_tol=0.01):
        raise ValueError(f"Case {case_id} {topic} probabilities do not sum to one")
    expected_score = sum(
        level * distribution[str(level)] for level in range(5)
    )
    if not math.isclose(score, expected_score, abs_tol=0.02):
        raise ValueError(
            f"Case {case_id} {topic} score is inconsistent with its distribution"
        )
    confidence = raw.get("confidence")
    confidence_number = _number(confidence)
    if confidence is not None and (
        confidence_number is None or not 0.0 <= confidence_number <= 1.0
    ):
        raise ValueError(f"Case {case_id} has invalid {topic} confidence")
    return {
        "score": round(score, 6),
        "probabilities": {
            level: round(probability, 6)
            for level, probability in distribution.items()
        },
        "confidence": (
            round(float(confidence), 6) if confidence is not None else None
        ),
    }


def evaluate_topic_behavior_fixture(
    fixture: Mapping[str, Any],
    *,
    cache_dir: Path,
    model: str,
    client: TypeSafeBlockClient,
) -> dict[str, Any]:
    """Evaluate reviewed ranges while preserving every raw Score distribution."""
    if not model.strip():
        raise ValueError("TypeSafe model id must not be blank")
    blocks, contexts = _blocks_and_contexts(fixture)
    cache = TypeSafeBlockCache(cache_dir.expanduser().resolve(), model=model)
    answers = cache.assess_packs(
        client,
        {
            "evaluation": "sermon_topic_behavior_contract",
            "fixture_id": fixture["fixture_id"],
        },
        blocks,
        requested_packs=frozenset({TOPIC_PACK}),
        topic_contexts=contexts,
    )
    input_identity = {
        "evaluator_version": TOPIC_BEHAVIOR_EVALUATOR_VERSION,
        "fixture_id": fixture["fixture_id"],
        "fixture_sha256": fixture["fixture_sha256"],
        "model": model,
        "question_pack_version": TOPIC_PACK_VERSION,
        "question_pack_digest": topic_pack_digest(),
    }
    cases: list[dict[str, Any]] = []
    passed_expectations = 0
    failed_expectations = 0
    request_keys: set[str] = set()
    resolved_models: set[str] = set()
    for position, case in enumerate(fixture["cases"]):
        block_id = position + 1
        answer = answers[block_id]
        if answer.topic_question_version != TOPIC_PACK_VERSION:
            raise ValueError(
                f"Case {case['case_id']} returned topic pack "
                f"{answer.topic_question_version!r}, expected {TOPIC_PACK_VERSION!r}"
            )
        resolved_models.add(answer.resolved_model_id)
        provenance = answer.request_provenance.get(TOPIC_PACK, {})
        if isinstance(provenance, Mapping) and provenance.get("request_key"):
            request_keys.add(str(provenance["request_key"]))
        if set(answer.topic_scores) != set(TOPICS):
            missing = set(TOPICS) - set(answer.topic_scores)
            extra = set(answer.topic_scores) - set(TOPICS)
            raise ValueError(
                f"Case {case['case_id']} topic inventory mismatch; "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )
        scores = {
            topic: _validated_score(
                case_id=str(case["case_id"]),
                topic=topic,
                raw=answer.topic_scores[topic],
            )
            for topic in TOPICS
        }
        checks = []
        for topic, expectation in case["expectations"].items():
            score = scores[topic]["score"]
            minimum = float(expectation["minimum_score"])
            maximum = float(expectation["maximum_score"])
            passed = minimum <= score <= maximum
            passed_expectations += int(passed)
            failed_expectations += int(not passed)
            checks.append(
                {
                    "topic": topic,
                    "minimum_score": minimum,
                    "maximum_score": maximum,
                    "observed_score": score,
                    "passed": passed,
                    "rationale": expectation["rationale"],
                }
            )
        cases.append(
            {
                "case_id": case["case_id"],
                "label": case["label"],
                "tags": list(case["tags"]),
                "reviewed_interpretation": case["reviewed_interpretation"],
                "context": contexts[block_id].state_payload(),
                "scores": scores,
                "checks": checks,
                "passed": all(check["passed"] for check in checks),
                "request_provenance": dict(provenance),
            }
        )
    report = {
        "schema_version": TOPIC_BEHAVIOR_REPORT_SCHEMA_VERSION,
        "evaluator_version": TOPIC_BEHAVIOR_EVALUATOR_VERSION,
        "input_fingerprint": _sha256(input_identity),
        "status": "passed" if failed_expectations == 0 else "failed",
        "interpretation_contract": {
            "score": "Probability-weighted position on ordered levels 0-4.",
            "confidence": (
                "Distribution concentration only; it is preserved but never used "
                "as correctness or as a pass threshold."
            ),
            "scope": (
                "Synthetic behavior contract only; this is not whole-sermon or "
                "pastor-level analytical validation."
            ),
        },
        "fixture": {
            "fixture_id": fixture["fixture_id"],
            "fixture_path": fixture["fixture_path"],
            "fixture_sha256": fixture["fixture_sha256"],
            "review": dict(fixture["review"]),
        },
        "model": {
            "requested": model,
            "resolved": sorted(resolved_models),
        },
        "question_pack": {
            "version": TOPIC_PACK_VERSION,
            "digest": topic_pack_digest(),
        },
        "cache_provenance": {
            "source_provider_request_count": len(request_keys),
            "source_provider_request_keys": sorted(request_keys),
        },
        "summary": {
            "case_count": len(cases),
            "passed_cases": sum(case["passed"] for case in cases),
            "failed_cases": sum(not case["passed"] for case in cases),
            "expectation_count": passed_expectations + failed_expectations,
            "passed_expectations": passed_expectations,
            "failed_expectations": failed_expectations,
        },
        "cases": cases,
    }
    report["result_fingerprint"] = _sha256(report)
    report["execution"] = {
        "cache_hits": cache.hits,
        "cache_misses": cache.misses,
        "provider_requests": cache.provider_requests,
    }
    return report


def render_topic_behavior_report(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    fixture = report["fixture"]
    lines = [
        f"# TypeSafe Topic Behavior: {fixture['fixture_id']}",
        "",
        f"- Status: `{report['status']}`",
        f"- Model: `{report['model']['requested']}`",
        f"- Topic pack: `{report['question_pack']['version']}`",
        f"- Cases: {summary['passed_cases']}/{summary['case_count']} passed",
        (
            "- Expectations: "
            f"{summary['passed_expectations']}/{summary['expectation_count']} passed"
        ),
        (
            "- Source provider requests: "
            f"{report['cache_provenance']['source_provider_request_count']}"
        ),
        f"- Input fingerprint: `{report['input_fingerprint']}`",
        "",
        "Confidence is shown as distribution concentration only. It is not used as "
        "a correctness score or pass threshold.",
        "",
    ]
    for case in report["cases"]:
        lines.extend(
            [
                f"## {'PASS' if case['passed'] else 'FAIL'} — {case['label']}",
                "",
                f"`{case['case_id']}` · {', '.join(case['tags'])}",
                "",
                case["reviewed_interpretation"],
                "",
                "| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for check in case["checks"]:
            score = case["scores"][check["topic"]]
            probabilities = score["probabilities"]
            confidence = score["confidence"]
            row = (
                f"| `{check['topic']}` | {check['minimum_score']:.2f}–"
                f"{check['maximum_score']:.2f} | {score['score']:.3f} | "
                + " | ".join(
                    f"{probabilities[str(level)]:.3f}" for level in range(5)
                )
            )
            row += f" | {confidence:.3f} | " if confidence is not None else " | n/a | "
            row += "pass |" if check["passed"] else "**fail** |"
            lines.append(row)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_topic_behavior_report(
    output_json_path: Path,
    report: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    output_json_path = output_json_path.expanduser().resolve()
    markdown_path = output_json_path.with_suffix(".md")
    persisted_report = {
        key: value for key, value in report.items() if key != "execution"
    }
    expected_json = (
        json.dumps(persisted_report, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )
    expected_markdown = render_topic_behavior_report(persisted_report)
    if output_json_path.exists() and markdown_path.exists():
        try:
            existing_json = output_json_path.read_text(encoding="utf-8")
            existing_markdown = markdown_path.read_text(encoding="utf-8")
            existing = json.loads(existing_json)
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing = existing_json = existing_markdown = None
        if (
            isinstance(existing, dict)
            and existing.get("result_fingerprint")
            == persisted_report.get("result_fingerprint")
            and existing_json == expected_json
            and existing_markdown == expected_markdown
        ):
            return output_json_path, markdown_path, True
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(expected_json, encoding="utf-8")
    markdown_path.write_text(expected_markdown, encoding="utf-8")
    return output_json_path, markdown_path, False


def default_topic_behavior_output_path(fixture_path: Path, model: str) -> Path:
    safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", model)
    return fixture_path.with_name(f"{fixture_path.stem}.{safe_model}.results.json")
