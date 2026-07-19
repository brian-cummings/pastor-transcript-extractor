from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from pastor_transcript_extractor.fixture_validation import validate_fixture_directory
from pastor_transcript_extractor.sermon_classification import (
    BLOCK_BUILDER_VERSION,
    COARSE_DISCOVERY_VERSION,
    CONFIDENCE_POLICY_VERSION,
    FINE_COMPONENT_VERSION,
    SEARCH_ALGORITHM_VERSION,
)


class BaselineValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedLocalizationBaseline:
    baseline_id: str
    fixture_count: int
    corpus_fingerprint: str


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_object(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise BaselineValidationError(f"{field} must be an object")
    return value


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BaselineValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _validate_implementation_versions(payload: dict[str, Any]) -> None:
    recorded = _required_object(payload, "implementation_versions")
    current = {
        "search_algorithm": SEARCH_ALGORITHM_VERSION,
        "block_builder": BLOCK_BUILDER_VERSION,
        "coarse_discovery": COARSE_DISCOVERY_VERSION,
        "fine_component": FINE_COMPONENT_VERSION,
        "confidence_policy": CONFIDENCE_POLICY_VERSION,
    }
    if recorded != current:
        raise BaselineValidationError(
            f"implementation version drift: expected {recorded!r}, current {current!r}"
        )


def validate_localization_baseline(
    manifest_path: Path,
    fixture_dir: Path,
) -> ValidatedLocalizationBaseline:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BaselineValidationError(f"{manifest_path}: invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise BaselineValidationError("baseline manifest must be a JSON object")
    if payload.get("schema_version") != 1:
        raise BaselineValidationError("schema_version must be 1")
    baseline_id = _required_string(payload, "baseline_id")
    _required_string(payload, "code_commit")
    _required_object(payload, "evaluation_run")
    _required_object(payload, "model_configuration")
    metrics = _required_object(payload, "metrics")
    for field in (
        "mean_sermon_recall",
        "worst_sermon_recall",
        "mean_contamination_ratio",
        "correct_top_candidate_rate",
        "catastrophic_omissions",
        "negative_accepted_dispositions",
        "negative_high_confidence_false_positives",
    ):
        if not isinstance(metrics.get(field), (int, float)) or isinstance(metrics.get(field), bool):
            raise BaselineValidationError(f"metrics.{field} must be numeric")
    _validate_implementation_versions(payload)

    corpus = _required_object(payload, "fixture_corpus")
    entries = corpus.get("fixtures")
    if not isinstance(entries, list) or not entries:
        raise BaselineValidationError("fixture_corpus.fixtures must be a non-empty list")
    expected_entries: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise BaselineValidationError(f"fixture_corpus.fixtures[{index}] must be an object")
        video_id = _required_string(entry, "video_id")
        fixture_hash = _required_string(entry, "fixture_hash")
        if video_id in seen_ids:
            raise BaselineValidationError(f"duplicate baseline video_id: {video_id}")
        seen_ids.add(video_id)
        expected_entries.append({"video_id": video_id, "fixture_hash": fixture_hash})
    expected_entries.sort(key=lambda item: item["video_id"])
    if entries != expected_entries:
        raise BaselineValidationError("fixture_corpus.fixtures must be sorted by video_id")
    if corpus.get("fixture_count") != len(expected_entries):
        raise BaselineValidationError("fixture_corpus.fixture_count does not match fixtures")
    expected_fingerprint = canonical_hash(expected_entries)
    if corpus.get("fingerprint") != expected_fingerprint:
        raise BaselineValidationError("fixture_corpus.fingerprint does not match fixture entries")

    fixtures = validate_fixture_directory(fixture_dir)
    actual_entries: list[dict[str, str]] = []
    for fixture in fixtures:
        fixture_payload = json.loads(fixture.path.read_text(encoding="utf-8"))
        actual_entries.append(
            {"video_id": fixture.video_id, "fixture_hash": canonical_hash(fixture_payload)}
        )
    actual_entries.sort(key=lambda item: item["video_id"])
    if actual_entries != expected_entries:
        expected_by_id = {item["video_id"]: item["fixture_hash"] for item in expected_entries}
        actual_by_id = {item["video_id"]: item["fixture_hash"] for item in actual_entries}
        missing = sorted(expected_by_id.keys() - actual_by_id.keys())
        added = sorted(actual_by_id.keys() - expected_by_id.keys())
        changed = sorted(
            video_id
            for video_id in expected_by_id.keys() & actual_by_id.keys()
            if expected_by_id[video_id] != actual_by_id[video_id]
        )
        raise BaselineValidationError(
            f"fixture corpus drift: missing={missing}, added={added}, changed={changed}"
        )
    return ValidatedLocalizationBaseline(
        baseline_id=baseline_id,
        fixture_count=len(actual_entries),
        corpus_fingerprint=expected_fingerprint,
    )
