from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from pastor_transcript_extractor.fixture_validation import (
    FixtureValidationError,
    validate_fixture_payload,
)


@dataclass(frozen=True, slots=True)
class FixtureWindowCorrection:
    fixture_path: Path
    video_id: str
    start_seconds: float
    end_seconds: float
    ground_truth_version: int
    reviewed_by: str

    def override_payload(self) -> dict[str, object]:
        return {
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "notes": (
                "Applied from approved fixture "
                f"{self.fixture_path.name} ground_truth_version="
                f"{self.ground_truth_version}."
            ),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": self.reviewed_by,
        }


def load_fixture_window_correction(
    fixture_dir: Path,
    youtube_video_id: str,
) -> FixtureWindowCorrection:
    """Load one approved fixture that can be represented by a window override."""
    root = fixture_dir.expanduser().resolve()
    fixture_path = (root / f"{youtube_video_id}.json").resolve()
    if fixture_path.parent != root:
        raise FixtureValidationError("video ID resolves outside the fixture directory")
    if not fixture_path.exists():
        raise FixtureValidationError(f"fixture does not exist: {fixture_path}")
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FixtureValidationError(
            f"{fixture_path}: invalid JSON: {error}"
        ) from error
    fixture = validate_fixture_payload(payload, path=fixture_path)
    if fixture.video_id != youtube_video_id:
        raise FixtureValidationError(
            f"fixture video_id {fixture.video_id!r} does not match "
            f"requested video {youtube_video_id!r}"
        )
    if fixture.expected_outcome != "sermon":
        raise FixtureValidationError(
            "only positive sermon fixtures can correct an observation window"
        )
    if len(fixture.expected_spans) != 1:
        raise FixtureValidationError(
            "fixture correction requires exactly one continuous expected span"
        )
    if fixture.allowed_interruptions:
        raise FixtureValidationError(
            "fixture correction cannot represent allowed interruptions in a "
            "single observation window"
        )
    start_seconds, end_seconds = fixture.expected_spans[0]
    return FixtureWindowCorrection(
        fixture_path=fixture_path,
        video_id=fixture.video_id,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        ground_truth_version=fixture.ground_truth_version,
        reviewed_by=fixture.reviewed_by,
    )


def persist_fixture_window_override(
    correction: FixtureWindowCorrection,
    override_path: Path,
) -> None:
    """Atomically persist the fixture-derived production override."""
    override_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = override_path.with_name(f".{override_path.name}.tmp")
    temporary_path.write_text(
        json.dumps(correction.override_payload(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary_path.replace(override_path)
