from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class FixtureValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedFixture:
    path: Path
    video_id: str
    expected_spans: list[tuple[float, float]]
    allowed_interruptions: list[tuple[float, float]]
    ground_truth_version: int
    reviewed_by: str
    expected_outcome: str


def _validated_ranges(payload: dict[str, Any], field: str, *, required: bool) -> list[tuple[float, float]]:
    raw_ranges = payload.get(field)
    if not isinstance(raw_ranges, list) or (required and not raw_ranges):
        requirement = "a non-empty list" if required else "a list"
        raise FixtureValidationError(f"{field} must be {requirement}")
    ranges: list[tuple[float, float]] = []
    for index, raw in enumerate(raw_ranges):
        if not isinstance(raw, dict):
            raise FixtureValidationError(f"{field}[{index}] must be an object")
        start = raw.get("start_seconds")
        end = raw.get("end_seconds")
        if not isinstance(start, (int, float)) or isinstance(start, bool):
            raise FixtureValidationError(f"{field}[{index}].start_seconds must be a number")
        if not isinstance(end, (int, float)) or isinstance(end, bool):
            raise FixtureValidationError(f"{field}[{index}].end_seconds must be a number")
        start_value = float(start)
        end_value = float(end)
        if start_value < 0 or end_value < 0:
            raise FixtureValidationError(f"{field}[{index}] timestamps cannot be negative")
        if end_value <= start_value:
            raise FixtureValidationError(f"{field}[{index}] end_seconds must be greater than start_seconds")
        ranges.append((start_value, end_value))
    ranges.sort()
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] < previous[1]:
            raise FixtureValidationError(f"{field} contains overlapping ranges")
    return ranges


def validate_fixture_payload(payload: object, *, path: Path) -> ValidatedFixture:
    if not isinstance(payload, dict):
        raise FixtureValidationError("fixture must be a JSON object")
    video_id = payload.get("video_id")
    if not isinstance(video_id, str) or not video_id.strip():
        raise FixtureValidationError("video_id must be a non-empty string")
    version = payload.get("ground_truth_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise FixtureValidationError("ground_truth_version must be a positive integer")
    reviewed_by = payload.get("reviewed_by")
    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        raise FixtureValidationError("reviewed_by must be a non-empty string")

    expected_outcome = payload.get("expected_outcome")
    if expected_outcome not in {"sermon", "no_sermon"}:
        raise FixtureValidationError("expected_outcome must be 'sermon' or 'no_sermon'")
    expected = _validated_ranges(
        payload, "expected_spans", required=expected_outcome == "sermon"
    )
    interruptions = _validated_ranges(payload, "allowed_interruptions", required=False)
    if expected_outcome == "no_sermon":
        if expected:
            raise FixtureValidationError("no_sermon fixtures must have empty expected_spans")
        if interruptions:
            raise FixtureValidationError("no_sermon fixtures must have empty allowed_interruptions")
        return ValidatedFixture(
            path=path,
            video_id=video_id.strip(),
            expected_spans=[],
            allowed_interruptions=[],
            ground_truth_version=version,
            reviewed_by=reviewed_by.strip(),
            expected_outcome=expected_outcome,
        )
    sermon_start = expected[0][0]
    sermon_end = expected[-1][1]
    for interruption in interruptions:
        if interruption[0] < sermon_start or interruption[1] > sermon_end:
            raise FixtureValidationError("allowed_interruptions must fall inside the expected sermon envelope")
        if any(interruption[0] < end and interruption[1] > start for start, end in expected):
            raise FixtureValidationError("allowed_interruptions cannot overlap retained expected_spans")
    return ValidatedFixture(
        path=path,
        video_id=video_id.strip(),
        expected_spans=expected,
        allowed_interruptions=interruptions,
        ground_truth_version=version,
        reviewed_by=reviewed_by.strip(),
        expected_outcome=expected_outcome,
    )


def validate_fixture_directory(directory: Path) -> list[ValidatedFixture]:
    if not directory.exists() or not directory.is_dir():
        raise FixtureValidationError(f"fixture directory does not exist: {directory}")
    fixtures: list[ValidatedFixture] = []
    seen_ids: dict[str, Path] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise FixtureValidationError(f"{path}: invalid JSON: {error}") from error
        try:
            fixture = validate_fixture_payload(payload, path=path)
        except FixtureValidationError as error:
            raise FixtureValidationError(f"{path}: {error}") from error
        duplicate = seen_ids.get(fixture.video_id)
        if duplicate is not None:
            raise FixtureValidationError(
                f"duplicate video_id {fixture.video_id!r} in {duplicate} and {path}"
            )
        seen_ids[fixture.video_id] = path
        fixtures.append(fixture)
    if not fixtures:
        raise FixtureValidationError(f"fixture directory contains no JSON fixtures: {directory}")
    return fixtures
