from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Iterable

from pastor_transcript_extractor.speaker_review_invalidation import (
    filter_active_pair_artifacts,
    load_review_revocations,
)
from pastor_transcript_extractor.storage import Database


NEGATIVE_QUALIFICATIONS = frozenset(("multiple_speakers", "invalid_audio"))
BROAD_WINDOW_SECONDS = 40.0 * 60.0
RECORDING_EDGE_SECONDS = 5.0 * 60.0


@dataclass(frozen=True, slots=True)
class SpeakerNegativeWindowRecord:
    youtube_video_id: str
    observation_fingerprint: str
    qualifications: tuple[str, ...]
    reviewed_at: str | None
    reviewed_start_seconds: float
    reviewed_end_seconds: float
    reviewed_duration_seconds: float
    current_observation_fingerprint: str | None
    current_start_seconds: float | None
    current_end_seconds: float | None
    current_duration_seconds: float | None
    video_duration_seconds: float | None
    currently_selected: bool
    actionable: bool
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SpeakerNegativeWindowAudit:
    records: tuple[SpeakerNegativeWindowRecord, ...]

    @property
    def actionable(self) -> tuple[SpeakerNegativeWindowRecord, ...]:
        return tuple(record for record in self.records if record.actionable)

    def to_dict(self) -> dict[str, object]:
        return {
            "counts": {
                "negative_observations": len(self.records),
                "actionable": len(self.actionable),
                "stale": sum(not record.currently_selected for record in self.records),
                "broad_actionable": sum(
                    record.actionable and "broad_window" in record.reason_codes
                    for record in self.records
                ),
            },
            "records": [record.to_dict() for record in self.records],
        }


def audit_speaker_negative_windows(
    database: Database,
    evaluation_root: Path,
) -> SpeakerNegativeWindowAudit:
    """Derive a read-only recovery queue from active immutable pair reviews."""
    root = evaluation_root.expanduser().resolve()
    revocations = load_review_revocations(root)
    drafts = filter_active_pair_artifacts(
        _load_objects(sorted((root / "drafts").glob("*.json"))), revocations
    )
    reviews = filter_active_pair_artifacts(
        _load_objects(sorted((root / "reviews").glob("*/*.json"))), revocations
    )
    drafts_by_pair = {
        str(draft["pair_id"]): draft for draft in drafts if draft.get("pair_id")
    }
    negative_by_fingerprint: dict[str, dict[str, Any]] = {}
    for review in reviews:
        draft = drafts_by_pair.get(str(review.get("pair_id", "")))
        if draft is None:
            continue
        qualifications = review.get("qualification")
        presentation = draft.get("presentation")
        observations = draft.get("observations")
        if not all(isinstance(value, dict) for value in (qualifications, presentation, observations)):
            continue
        for label in ("A", "B"):
            qualification = qualifications.get(label)
            if qualification not in NEGATIVE_QUALIFICATIONS:
                continue
            side = presentation.get(label)
            if not isinstance(side, dict):
                continue
            snapshot = observations.get(side.get("source_key"))
            if not isinstance(snapshot, dict):
                continue
            fingerprint = snapshot.get("input_fingerprint")
            youtube_video_id = snapshot.get("youtube_video_id")
            if not isinstance(fingerprint, str) or not isinstance(youtube_video_id, str):
                continue
            state = negative_by_fingerprint.setdefault(
                fingerprint,
                {
                    "youtube_video_id": youtube_video_id,
                    "snapshot": snapshot,
                    "qualifications": set(),
                    "reviewed_at": None,
                },
            )
            state["qualifications"].add(str(qualification))
            reviewed_at = review.get("reviewed_at")
            if isinstance(reviewed_at, str) and (
                state["reviewed_at"] is None or reviewed_at > state["reviewed_at"]
            ):
                state["reviewed_at"] = reviewed_at

    # Manual registry qualifications are append-only evidence too. Most are
    # projected from pair reviews, but include any standalone negative action
    # so the audit agrees with registry totals instead of silently omitting it.
    for observation in database.list_speaker_observations():
        action = database.get_effective_observation_review_action(observation.id)
        if action not in {"multiple_speakers", "invalid"}:
            continue
        if observation.input_fingerprint in negative_by_fingerprint:
            continue
        video = database.get_video_by_id(observation.video_id)
        if video is None:
            continue
        negative_by_fingerprint[observation.input_fingerprint] = {
            "youtube_video_id": video.youtube_video_id,
            "snapshot": {
                "input_fingerprint": observation.input_fingerprint,
                "youtube_video_id": video.youtube_video_id,
                "observation_window": {
                    "start_seconds": observation.start_seconds,
                    "end_seconds": observation.end_seconds,
                },
            },
            "qualifications": {
                "invalid_audio" if action == "invalid" else action
            },
            "reviewed_at": None,
        }

    for state in negative_by_fingerprint.values():
        state["evaluation_root"] = root

    records = [
        _build_record(database, fingerprint=fingerprint, state=state)
        for fingerprint, state in negative_by_fingerprint.items()
    ]
    records.sort(key=_record_priority)
    return SpeakerNegativeWindowAudit(tuple(records))


def _build_record(
    database: Database,
    *,
    fingerprint: str,
    state: dict[str, Any],
) -> SpeakerNegativeWindowRecord:
    youtube_video_id = str(state["youtube_video_id"])
    video = database.get_video_by_youtube_id(youtube_video_id)
    reviewed_observation = database.get_speaker_observation_by_fingerprint(fingerprint)
    snapshot_window = state["snapshot"].get("observation_window")
    snapshot_window = snapshot_window if isinstance(snapshot_window, dict) else {}
    reviewed_start = _number(snapshot_window.get("start_seconds"))
    reviewed_end = _number(snapshot_window.get("end_seconds"))
    if reviewed_observation is not None:
        reviewed_start = reviewed_observation.start_seconds
        reviewed_end = reviewed_observation.end_seconds
    if reviewed_start is None or reviewed_end is None or reviewed_end <= reviewed_start:
        raise ValueError(
            f"negative review snapshot has no valid observation window: {fingerprint}"
        )

    current_fingerprint: str | None = None
    current_start: float | None = None
    current_end: float | None = None
    if video is not None:
        extraction = database.get_latest_extraction_result_for_video(video.id)
        if extraction is not None and extraction.proposed_json_path:
            payload = _load_object(Path(extraction.proposed_json_path))
            window = payload.get("sermon_window")
            if isinstance(window, dict):
                current_start = _number(window.get("start_seconds"))
                current_end = _number(window.get("end_seconds"))
            if (
                current_start is not None
                and current_end is not None
                and current_end > current_start
            ):
                current = database.get_speaker_observation_for_extraction_window(
                    video.id,
                    extraction.id,
                    start_seconds=current_start,
                    end_seconds=current_end,
                )
                current_fingerprint = current.input_fingerprint if current else None

    currently_selected = current_fingerprint == fingerprint
    reviewed_duration = reviewed_end - reviewed_start
    video_duration = (
        float(video.duration_seconds)
        if video is not None and video.duration_seconds is not None
        else None
    )
    reasons = list(sorted(state["qualifications"]))
    if not currently_selected:
        reasons.append("stale_observation")
    if reviewed_duration > BROAD_WINDOW_SECONDS:
        reasons.append("broad_window")
    if reviewed_start <= RECORDING_EDGE_SECONDS:
        reasons.append("begins_near_recording_start")
    if (
        video_duration is not None
        and video_duration - reviewed_end <= RECORDING_EDGE_SECONDS
    ):
        reasons.append("ends_near_recording_end")
    fixture_state = _ground_truth_fixture_state(
        state.get("evaluation_root"),
        youtube_video_id=youtube_video_id,
        current_start=current_start,
        current_end=current_end,
    )
    if fixture_state is not None:
        reasons.append(fixture_state)
    actionable = currently_selected and fixture_state not in {
        "ground_truth_window_confirmed",
        "ground_truth_no_sermon",
        "ground_truth_complex_sermon",
    }
    return SpeakerNegativeWindowRecord(
        youtube_video_id=youtube_video_id,
        observation_fingerprint=fingerprint,
        qualifications=tuple(sorted(state["qualifications"])),
        reviewed_at=state["reviewed_at"],
        reviewed_start_seconds=reviewed_start,
        reviewed_end_seconds=reviewed_end,
        reviewed_duration_seconds=reviewed_duration,
        current_observation_fingerprint=current_fingerprint,
        current_start_seconds=current_start,
        current_end_seconds=current_end,
        current_duration_seconds=(
            current_end - current_start
            if current_start is not None and current_end is not None
            else None
        ),
        video_duration_seconds=video_duration,
        currently_selected=currently_selected,
        actionable=actionable,
        reason_codes=tuple(reasons),
    )


def _record_priority(record: SpeakerNegativeWindowRecord) -> tuple[object, ...]:
    return (
        0 if record.actionable else 1,
        0 if "approved_fixture_pending_apply" in record.reason_codes else 1,
        0 if "broad_window" in record.reason_codes else 1,
        0 if "begins_near_recording_start" in record.reason_codes else 1,
        -record.reviewed_duration_seconds,
        record.youtube_video_id,
        record.observation_fingerprint,
    )


def _load_objects(paths: Iterable[Path]) -> list[dict[str, Any]]:
    return [_load_object(path) for path in paths]


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _ground_truth_fixture_state(
    evaluation_root: object,
    *,
    youtube_video_id: str,
    current_start: float | None,
    current_end: float | None,
) -> str | None:
    if not isinstance(evaluation_root, Path):
        return None
    fixture_path = evaluation_root.parent / "fixtures" / f"{youtube_video_id}.json"
    if not fixture_path.exists():
        return None
    fixture = _load_object(fixture_path)
    if fixture.get("expected_outcome") == "no_sermon":
        return "ground_truth_no_sermon"
    spans = fixture.get("expected_spans")
    if (
        fixture.get("expected_outcome") != "sermon"
        or not isinstance(spans, list)
        or len(spans) != 1
        or fixture.get("allowed_interruptions") != []
        or not isinstance(spans[0], dict)
    ):
        return "ground_truth_complex_sermon"
    fixture_start = _number(spans[0].get("start_seconds"))
    fixture_end = _number(spans[0].get("end_seconds"))
    if fixture_start is None or fixture_end is None:
        return "ground_truth_complex_sermon"
    if (
        current_start is not None
        and current_end is not None
        and abs(fixture_start - current_start) <= 0.001
        and abs(fixture_end - current_end) <= 0.001
    ):
        return "ground_truth_window_confirmed"
    return "approved_fixture_pending_apply"
