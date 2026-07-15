from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import html
import json
from pathlib import Path
import random
from typing import Any, Sequence

from pastor_transcript_extractor.models import SpeakerObservation
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    AudioSpanCache,
    CachedSpan,
    select_diagnostic_spans,
    validate_reviewed_pair_fixture,
)


REVIEW_WORKFLOW_VERSION = "speaker_pair_review_v1"


class ObservationQualification(StrEnum):
    QUALIFIED_SINGLE_SPEAKER = "qualified_single_speaker"
    MULTIPLE_SPEAKERS = "multiple_speakers"
    INVALID_AUDIO = "invalid_audio"
    CANNOT_DETERMINE = "cannot_determine"


class PairJudgment(StrEnum):
    SAME_SPEAKER = "same_speaker"
    DIFFERENT_SPEAKER = "different_speaker"
    CANNOT_DETERMINE = "cannot_determine"


@dataclass(frozen=True, slots=True)
class ReviewDraft:
    pair_id: str
    draft_path: Path
    packet_path: Path
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReviewSubmission:
    event_path: Path
    fixture_path: Path | None
    fixture_status: str


def create_review_draft(
    *,
    observation_a: SpeakerObservation,
    observation_b: SpeakerObservation,
    video_id_a: str,
    video_id_b: str,
    audio_path_a: Path,
    audio_path_b: Path,
    span_cache: AudioSpanCache,
    evaluation_root: Path,
    span_count: int = 5,
    span_duration_seconds: float = 12.0,
) -> ReviewDraft:
    if observation_a.input_fingerprint == observation_b.input_fingerprint:
        raise ValueError("a pair review requires two distinct observations")
    ordered_inputs = sorted(
        (
            (observation_a.input_fingerprint, video_id_a, observation_a, audio_path_a),
            (observation_b.input_fingerprint, video_id_b, observation_b, audio_path_b),
        ),
        key=lambda value: value[0],
    )
    source_observations = {
        "source_a": ordered_inputs[0][1:],
        "source_b": ordered_inputs[1][1:],
    }
    canonical_fingerprints = [value[0] for value in ordered_inputs]
    pair_id = f"pair-{_sha256_json(canonical_fingerprints)[:16]}"
    presentation_sources = ["source_a", "source_b"]
    rng = random.Random(pair_id)
    rng.shuffle(presentation_sources)

    observations: dict[str, Any] = {}
    presentation: dict[str, Any] = {}
    for source_key, (video_id, observation, audio_path) in source_observations.items():
        specs = select_diagnostic_spans(
            observation,
            count=span_count,
            duration_seconds=span_duration_seconds,
        )
        if not specs:
            raise ValueError(f"observation {observation.input_fingerprint} is too short for review")
        spans = [
            span_cache.prepare(
                observation=observation,
                source_audio_path=audio_path,
                span=span,
            )
            for span in specs
        ]
        observations[source_key] = {
            "youtube_video_id": video_id,
            "input_fingerprint": observation.input_fingerprint,
            "observation_window": {
                "start_seconds": observation.start_seconds,
                "end_seconds": observation.end_seconds,
            },
            "clips": [_draft_clip(span) for span in spans],
        }

    for label, source_key in zip(("A", "B"), presentation_sources):
        clips = list(observations[source_key]["clips"])
        rng.shuffle(clips)
        presentation[label] = {
            "source_key": source_key,
            "clips": [clip["wav_sha256"] for clip in clips],
        }

    stable_payload = {
        "schema_version": 1,
        "workflow_version": REVIEW_WORKFLOW_VERSION,
        "review_status": "draft",
        "pair_id": pair_id,
        "blinding": {
            "packet_hides_video_ids": True,
            "packet_hides_titles_names_and_channels": True,
            "presentation_order_deterministic": True,
        },
        "observations": observations,
        "presentation": presentation,
    }
    draft_id = _sha256_json(stable_payload)
    payload = {**stable_payload, "draft_id": draft_id}
    draft_path = evaluation_root / "drafts" / f"{pair_id}.json"
    packet_path = evaluation_root / "drafts" / f"{pair_id}.html"
    _write_json_idempotent(draft_path, payload)
    packet = _review_packet(payload)
    _write_text_idempotent(packet_path, packet)
    return ReviewDraft(pair_id, draft_path, packet_path, payload)


def submit_review(
    *,
    draft: dict[str, Any],
    qualification_a: ObservationQualification,
    qualification_b: ObservationQualification,
    pair_judgment: PairJudgment,
    reviewer: str,
    reviewed_at: str | None,
    variation_tags: Sequence[str],
    notes: str,
    approval_confirmed: bool,
    evaluation_root: Path,
) -> ReviewSubmission:
    _validate_draft(draft)
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    qualified = (
        qualification_a == ObservationQualification.QUALIFIED_SINGLE_SPEAKER
        and qualification_b == ObservationQualification.QUALIFIED_SINGLE_SPEAKER
    )
    if not qualified and pair_judgment != PairJudgment.CANNOT_DETERMINE:
        raise ValueError("an unqualified observation requires cannot_determine pair judgment")
    normalized_tags = sorted({tag.strip() for tag in variation_tags if tag.strip()})
    reviewed_at_value = reviewed_at or datetime.now(timezone.utc).isoformat()
    event_without_id = {
        "schema_version": 1,
        "workflow_version": REVIEW_WORKFLOW_VERSION,
        "event_kind": "speaker_pair_human_review",
        "pair_id": draft["pair_id"],
        "draft_id": draft["draft_id"],
        "reviewer": reviewer,
        "reviewed_at": reviewed_at_value,
        "qualification": {
            "A": qualification_a,
            "B": qualification_b,
        },
        "pair_judgment": pair_judgment,
        "variation_tags": normalized_tags,
        "notes": notes.strip(),
        "approval_confirmed": approval_confirmed,
        "fixture_eligible": (
            qualified
            and pair_judgment in {PairJudgment.SAME_SPEAKER, PairJudgment.DIFFERENT_SPEAKER}
            and approval_confirmed
        ),
    }
    event_id = _sha256_json(event_without_id)
    event = {**event_without_id, "review_event_id": event_id}
    event_path = (
        evaluation_root / "reviews" / draft["pair_id"] / f"{event_id}.json"
    )
    _write_json_idempotent(event_path, event)

    if not event["fixture_eligible"]:
        return ReviewSubmission(event_path, None, "not_eligible")

    fixture = _fixture_from_review(draft, event)
    validate_reviewed_pair_fixture(fixture)
    fixture_path = evaluation_root / "fixtures" / f"{draft['pair_id']}.json"
    if not fixture_path.exists():
        _write_json_idempotent(fixture_path, fixture)
        return ReviewSubmission(event_path, fixture_path, "created")

    existing = json.loads(fixture_path.read_text(encoding="utf-8"))
    validate_reviewed_pair_fixture(existing)
    same_evidence = _fixture_evidence_identity(existing) == _fixture_evidence_identity(fixture)
    same_judgment = existing.get("expected_outcome") == fixture["expected_outcome"]
    if same_evidence and same_judgment:
        return ReviewSubmission(event_path, fixture_path, "existing_consistent")
    return ReviewSubmission(event_path, fixture_path, "existing_conflict_preserved")


def _fixture_from_review(draft: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for label, fixture_side in (("A", "a"), ("B", "b")):
        source_key = draft["presentation"][label]["source_key"]
        source = draft["observations"][source_key]
        observations[fixture_side] = {
            "youtube_video_id": source["youtube_video_id"],
            "input_fingerprint": source["input_fingerprint"],
            "reviewed_spans": [
                {
                    "start_seconds": clip["start_seconds"],
                    "end_seconds": clip["end_seconds"],
                    "wav_sha256": clip["wav_sha256"],
                }
                for clip in source["clips"]
            ],
        }
    return {
        "schema_version": 1,
        "workflow_version": REVIEW_WORKFLOW_VERSION,
        "pair_id": draft["pair_id"],
        "review_status": "approved",
        "reviewer": event["reviewer"],
        "reviewed_at": event["reviewed_at"],
        "review_event_id": event["review_event_id"],
        "expected_outcome": event["pair_judgment"],
        "variation_tags": event["variation_tags"],
        "notes": event["notes"],
        "qualification": event["qualification"],
        "observations": observations,
    }


def _review_packet(draft: dict[str, Any]) -> str:
    clips_by_hash = {
        clip["wav_sha256"]: clip
        for observation in draft["observations"].values()
        for clip in observation["clips"]
    }
    groups: list[str] = []
    for label in ("A", "B"):
        players: list[str] = []
        for index, clip_hash in enumerate(draft["presentation"][label]["clips"], start=1):
            clip = clips_by_hash[clip_hash]
            source = Path(clip["wav_path"]).expanduser().resolve().as_uri()
            players.append(
                f'<li><span>Clip {index}</span><audio controls preload="metadata" '
                f'src="{html.escape(source, quote=True)}"></audio></li>'
            )
        groups.append(
            f'<section><h2>Observation {label}</h2><ol>{"".join(players)}</ol></section>'
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Blinded speaker pair review</title>
  <style>
    body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 920px; margin: 2rem auto; padding: 0 1rem; }}
    section {{ border: 1px solid #ccc; border-radius: 8px; margin: 1rem 0; padding: 1rem; }}
    li {{ margin: .8rem 0; display: grid; grid-template-columns: 6rem 1fr; align-items: center; }}
    audio {{ width: 100%; }}
    .warning {{ background: #fff4d6; border-left: 4px solid #b77900; padding: .8rem; }}
  </style>
</head>
<body>
  <h1>Blinded speaker pair review</h1>
  <p class="warning">Judge only the voices in these clips. Names, titles, channels, and metadata are intentionally hidden.</p>
  <p>First decide whether every clip in each observation contains one consistent principal speaker. Compare A and B only if both observations qualify.</p>
  {''.join(groups)}
</body>
</html>
"""


def _draft_clip(span: CachedSpan) -> dict[str, Any]:
    return {
        "start_seconds": span.start_seconds,
        "end_seconds": span.end_seconds,
        "wav_path": span.wav_path,
        "wav_sha256": span.wav_sha256,
        "duration_seconds": span.duration_seconds,
        "rms_dbfs": span.rms_dbfs,
        "clipped_fraction": span.clipped_fraction,
    }


def _fixture_evidence_identity(fixture: dict[str, Any]) -> object:
    return {
        side: {
            "input_fingerprint": fixture["observations"][side]["input_fingerprint"],
            "wav_sha256": [
                span["wav_sha256"] for span in fixture["observations"][side]["reviewed_spans"]
            ],
        }
        for side in ("a", "b")
    }


def _validate_draft(draft: dict[str, Any]) -> None:
    if draft.get("schema_version") != 1 or draft.get("review_status") != "draft":
        raise ValueError("invalid speaker-pair review draft")
    stable = {key: value for key, value in draft.items() if key != "draft_id"}
    if draft.get("draft_id") != _sha256_json(stable):
        raise ValueError("speaker-pair review draft fingerprint mismatch")
    for label in ("A", "B"):
        source_key = draft.get("presentation", {}).get(label, {}).get("source_key")
        if source_key not in draft.get("observations", {}):
            raise ValueError(f"draft presentation {label} has no source observation")
        hashes = draft["presentation"][label].get("clips")
        available = {
            clip["wav_sha256"] for clip in draft["observations"][source_key].get("clips", [])
        }
        if not isinstance(hashes, list) or len(hashes) < 2 or set(hashes) != available:
            raise ValueError(f"draft presentation {label} does not preserve exact clips")


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_json_idempotent(path: Path, payload: object) -> None:
    _write_text_idempotent(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text_idempotent(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"refusing to overwrite changed review artifact: {path}")
        return
    path.write_text(content, encoding="utf-8")
