from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.models import TranscriptSegmentLabel
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_detection import detect_sermon_window


POLICY_VERSION = "identity_boundary_review_v2"
SYNCHRONIZATION_VERSION = "identity_boundary_sync_v1"
DEFAULT_MAX_TRIM_SECONDS = 300.0
DEFAULT_MAX_TRIM_FRACTION = 0.20
DEFAULT_MIN_REMAINING_SECONDS = 600.0
DEFAULT_MIN_REMAINING_SEGMENTS = 3

AUTO_TRIM = "auto_trim"
REVIEW_REQUIRED = "review_required"
RETAIN_BOUNDARY = "retain_boundary"
NO_ACTION = "no_action"

_OPENING_ANCHORS = re.compile(
    r"\b(?:open|turn) (?:with me )?(?:(?:in|to) )?(?:your )?bibles?\b|"
    r"\b(?:our|my) (?:sermon |message )?(?:text|title) (?:this morning|today|tonight)\b|"
    r"\bthe word of (?:the )?lord\b",
    re.IGNORECASE,
)
_CLOSING_ANCHORS = re.compile(
    r"\b(?:as|in) (?:we |i )?conclude\b|\bthe point of (?:this|today(?:'s)?) message\b|"
    r"\bthis is the word of (?:the )?lord\b",
    re.IGNORECASE,
)
_PRAYER_OR_HANDOFF = re.compile(
    r"\b(?:let us|let's|would you) pray\b|\b(?:bow|close) your (?:heads|eyes)\b|"
    r"\b(?:heavenly|gracious) father\b|\b(?:welcome|thank) (?:pastor|reverend|dr\.? )\b",
    re.IGNORECASE,
)
_EXPOSITION = re.compile(
    r"\b(?:verse|chapter) \d+\b|\bthe (?:passage|text) (?:says|teaches)\b|"
    r"\bwhat (?:paul|jesus|the apostle|scripture) (?:says|means|teaches)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class IdentityBoundaryReviewResult:
    sermon_window: dict[str, Any]
    records: list[dict[str, Any]]


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _stable_fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _window_fingerprint(window: Mapping[str, Any]) -> str:
    return _stable_fingerprint({
        key: window.get(key)
        for key in (
            "start_seconds",
            "end_seconds",
            "source",
            "method",
            "included_segment_indexes",
            "excluded_segment_indexes",
        )
    })


def _segments_fingerprint(segments: Sequence[Mapping[str, Any]]) -> str:
    return _stable_fingerprint([
        {
            key: segment.get(key)
            for key in ("start_seconds", "end_seconds", "text", "label", "speaker_hint")
        }
        for segment in segments
    ])


def _evidence_fingerprint(evidence: Mapping[str, Any] | None) -> str:
    return _stable_fingerprint(evidence if isinstance(evidence, Mapping) else None)


def _span(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    start = _number(raw.get("start_seconds"))
    end = _number(raw.get("end_seconds"))
    if start is None or end is None or end <= start:
        return None
    # Copy only production acoustic provenance.  In particular, never carry
    # fixture expectations, reviewed boundaries, or contamination metrics.
    allowed = {
        "start_seconds",
        "end_seconds",
        "speaker_key",
        "relationship",
        "clip_sha256",
        "embedding_sha256",
        "confidence",
        "source_artifact_sha256",
    }
    return {key: raw[key] for key in allowed if key in raw}


def _spans(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [value for item in raw if (value := _span(item)) is not None]


def _segments_in_range(
    segments: Sequence[Mapping[str, Any]], start: float, end: float
) -> list[Mapping[str, Any]]:
    return [
        segment
        for segment in segments
        if (_number(segment.get("start_seconds")) or 0.0) < end
        and (_number(segment.get("end_seconds")) or 0.0) > start
    ]


def _text(segments: Sequence[Mapping[str, Any]]) -> str:
    return " ".join(
        str(segment.get("text", "")) for segment in segments
        if isinstance(segment.get("text"), str)
    )


def _transition_boundary(
    evidence: Mapping[str, Any], segments: Sequence[Mapping[str, Any]]
) -> tuple[float | None, dict[str, Any] | None]:
    raw = evidence.get("transcript_transition_evidence")
    if not isinstance(raw, Mapping):
        return None, None
    boundary = _number(raw.get("boundary_seconds"))
    if boundary is None:
        return None, None
    segment_boundaries = {
        value
        for segment in segments
        for value in (
            _number(segment.get("start_seconds")),
            _number(segment.get("end_seconds")),
        )
        if value is not None
    }
    if not any(abs(value - boundary) <= 1.0 for value in segment_boundaries):
        return None, dict(raw)
    return boundary, {
        key: raw[key]
        for key in (
            "boundary_seconds",
            "transition_kind",
            "confidence",
            "before_text_sha256",
            "after_text_sha256",
            "reason_codes",
        )
        if key in raw
    }


def _distributed_and_coherent(
    sermon_spans: Sequence[Mapping[str, Any]], start: float, end: float
) -> bool:
    if len(sermon_spans) < 3 or end <= start:
        return False
    midpoints = sorted(
        (float(span["start_seconds"]) + float(span["end_seconds"])) / 2.0
        for span in sermon_spans
        if start <= float(span["start_seconds"]) < float(span["end_seconds"]) <= end
    )
    if len(midpoints) < 3:
        return False
    speaker_keys = {
        str(span.get("speaker_key"))
        for span in sermon_spans
        if span.get("speaker_key")
    }
    if len(speaker_keys) != 1:
        return False
    duration = end - start
    return midpoints[0] <= start + duration * 0.35 and midpoints[-1] >= start + duration * 0.65


def _coherent_edge_transition(evidence: Mapping[str, Any], edge_spans: list[dict[str, Any]]) -> bool:
    speaker_keys = {
        str(span.get("speaker_key")) for span in edge_spans if span.get("speaker_key")
    }
    coherent_speaker = len(edge_spans) >= 2 and len(speaker_keys) == 1
    return coherent_speaker or evidence.get("coherent_transition_detected") is True


def _record_fingerprint(
    edge: str,
    evidence: Mapping[str, Any],
    evidence_root: Mapping[str, Any],
) -> str:
    normalized = {
        key: evidence.get(key)
        for key in (
            "edge",
            "materially_inconsistent",
            "coherent_transition_detected",
            "proposed_boundary",
            "supports_current_boundary",
            "protected_sermon_anchor",
            "removes_coherent_exposition",
            "allowed_interruption",
            "brief_pastoral_handoff",
        )
    }
    normalized["edge_speaker_spans"] = _spans(
        evidence.get("edge_speaker_spans")
        or evidence.get("immutable_speaker_evidence_spans")
    )
    transition = evidence.get("transcript_transition_evidence")
    normalized["transcript_transition_evidence"] = (
        {
            key: transition.get(key)
            for key in (
                "boundary_seconds",
                "transition_kind",
                "confidence",
                "before_text_sha256",
                "after_text_sha256",
                "reason_codes",
            )
        }
        if isinstance(transition, Mapping)
        else None
    )
    material = {
        "policy_version": POLICY_VERSION,
        "edge": edge,
        "evidence": normalized,
        "association_version": evidence_root.get("association_version"),
        "model_version": (
            evidence_root.get("model_fingerprint")
            or evidence_root.get("model_version")
        ),
        "automatic_use_allowed": evidence_root.get("automatic_use_allowed") is True,
        "speaker_evidence_artifact_sha256": evidence_root.get(
            "source_artifact_sha256"
        ),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def review_identity_boundaries(
    sermon_window: Mapping[str, Any],
    segments: Sequence[Mapping[str, Any]],
    identity_evidence: Mapping[str, Any] | None,
    *,
    existing_records: Sequence[Mapping[str, Any]] = (),
    max_trim_seconds: float = DEFAULT_MAX_TRIM_SECONDS,
    max_trim_fraction: float = DEFAULT_MAX_TRIM_FRACTION,
    min_remaining_seconds: float = DEFAULT_MIN_REMAINING_SECONDS,
    min_remaining_segments: int = DEFAULT_MIN_REMAINING_SEGMENTS,
) -> IdentityBoundaryReviewResult:
    """Conservatively apply production speaker evidence to inward edges only."""
    window = dict(sermon_window)
    original_start = _number(window.get("start_seconds"))
    original_end = _number(window.get("end_seconds"))
    if original_start is None or original_end is None or original_end <= original_start:
        return IdentityBoundaryReviewResult(window, [])
    evidence_root = identity_evidence if isinstance(identity_evidence, Mapping) else {}
    sermon_spans = _spans(evidence_root.get("sermon_speaker_spans"))
    edge_items = evidence_root.get("edges")
    edge_items = edge_items if isinstance(edge_items, Sequence) and not isinstance(edge_items, (str, bytes)) else ()
    evidence_by_edge = {
        str(item.get("edge")): item
        for item in edge_items
        if isinstance(item, Mapping) and item.get("edge") in {"start", "end"}
    }
    prior_by_fingerprint = {
        str(record.get("input_fingerprint")): dict(record)
        for record in existing_records
        if isinstance(record, Mapping) and record.get("input_fingerprint")
    }
    records: list[dict[str, Any]] = []

    for edge in ("start", "end"):
        before = {
            "start_seconds": _number(window.get("start_seconds")),
            "end_seconds": _number(window.get("end_seconds")),
        }
        evidence = evidence_by_edge.get(edge)
        if evidence is None:
            records.append({
                "schema_version": 1,
                "policy_version": POLICY_VERSION,
                "edge": edge,
                "boundary_before_review": before,
                "immutable_speaker_evidence_spans": [],
                "transcript_transition_evidence": None,
                "proposed_boundary": before["start_seconds" if edge == "start" else "end_seconds"],
                "decision": NO_ACTION,
                "reason_codes": ["identity_evidence_insufficient"],
                "boundary_after_review": before,
                "speaker_association_version": evidence_root.get("association_version"),
                "speaker_model_version": evidence_root.get("model_fingerprint") or evidence_root.get("model_version"),
            })
            continue

        fingerprint = _record_fingerprint(edge, evidence, evidence_root)
        prior = prior_by_fingerprint.get(fingerprint)
        if prior is not None and prior.get("boundary_after_review") == before:
            records.append(prior)
            continue

        edge_spans = _spans(evidence.get("edge_speaker_spans") or evidence.get("immutable_speaker_evidence_spans"))
        boundary, transition = _transition_boundary(evidence, segments)
        current = before["start_seconds" if edge == "start" else "end_seconds"]
        proposed = _number(evidence.get("proposed_boundary")) or boundary
        reasons: list[str] = []
        meaningful = bool(edge_spans) or evidence.get("materially_inconsistent") is True

        if evidence.get("supports_current_boundary") is True:
            decision = RETAIN_BOUNDARY
            reasons.append("speaker_evidence_supports_current_boundary")
        elif not meaningful:
            decision = NO_ACTION
            reasons.append("identity_evidence_insufficient")
        else:
            decision = AUTO_TRIM
            if evidence.get("materially_inconsistent") is not True:
                reasons.append("edge_inconsistency_not_material")
            if evidence_root.get("automatic_use_allowed") is not True:
                reasons.append("speaker_association_not_approved_for_automatic_use")
            if not _distributed_and_coherent(sermon_spans, original_start, original_end):
                reasons.append("coherent_distributed_sermon_speaker_not_established")
            if not _coherent_edge_transition(evidence, edge_spans):
                reasons.append("replacement_speaker_or_transition_not_coherent")
            if boundary is None or proposed is None or abs(proposed - boundary) > 1.0:
                reasons.append("defensible_transition_boundary_missing")
            inward = proposed is not None and current is not None and (
                proposed > current if edge == "start" else proposed < current
            )
            if not inward:
                reasons.append("outward_or_stationary_identity_adjustment_forbidden")

            proposed_value = proposed if proposed is not None else current
            trim_start = original_start if edge == "start" else proposed_value
            trim_end = proposed_value if edge == "start" else original_end
            removed = _segments_in_range(segments, trim_start, trim_end)
            removed_text = _text(removed)
            anchor = _OPENING_ANCHORS if edge == "start" else _CLOSING_ANCHORS
            if anchor.search(removed_text) or evidence.get("protected_sermon_anchor") is True:
                reasons.append("protected_sermon_anchor_present")
            if evidence.get("removes_coherent_exposition") is not False:
                reasons.append("coherent_exposition_would_be_removed")
            trim_duration = abs(float(proposed_value) - float(current)) if proposed_value is not None and current is not None else 0.0
            original_duration = original_end - original_start
            if trim_duration > max_trim_seconds or trim_duration / original_duration > max_trim_fraction:
                reasons.append("automatic_trim_limit_exceeded")
            next_start = float(proposed_value) if edge == "start" else float(before["start_seconds"])
            next_end = float(before["end_seconds"]) if edge == "start" else float(proposed_value)
            remaining = _segments_in_range(segments, next_start, next_end)
            if next_end - next_start < min_remaining_seconds or len(remaining) < min_remaining_segments:
                reasons.append("minimum_remaining_sermon_not_satisfied")
            interruption = evidence.get("allowed_interruption")
            handoff = evidence.get("brief_pastoral_handoff")
            if interruption is True or handoff is True:
                reasons.append("allowed_interruption_or_brief_handoff_protected")
            elif interruption is not False or handoff is not False:
                reasons.append("interruption_or_handoff_classification_uncertain")
            elif trim_duration <= 90.0 and _PRAYER_OR_HANDOFF.search(removed_text):
                reasons.append("possible_prayer_or_brief_handoff")
            if reasons:
                decision = REVIEW_REQUIRED

        if decision == AUTO_TRIM and proposed is not None:
            window[f"{edge}_seconds"] = float(proposed)
            window.setdefault("original_source", window.get("source"))
            window["source"] = "identity_boundary_review"
            window["identity_boundary_policy_version"] = POLICY_VERSION
            reasons = ["all_identity_boundary_guards_satisfied"]

        after = {
            "start_seconds": _number(window.get("start_seconds")),
            "end_seconds": _number(window.get("end_seconds")),
        }
        records.append({
            "schema_version": 1,
            "policy_version": POLICY_VERSION,
            "input_fingerprint": fingerprint,
            "edge": edge,
            "boundary_before_review": before,
            "immutable_speaker_evidence_spans": [*sermon_spans, *edge_spans],
            "transcript_transition_evidence": transition,
            "proposed_boundary": proposed,
            "decision": decision,
            "reason_codes": reasons,
            "boundary_after_review": after,
            "speaker_association_version": evidence_root.get("association_version"),
            "speaker_model_version": evidence_root.get("model_fingerprint") or evidence_root.get("model_version"),
            "speaker_evidence_artifact_sha256": evidence_root.get("source_artifact_sha256"),
        })

    if any(record.get("decision") == AUTO_TRIM for record in records):
        start = float(window["start_seconds"])
        end = float(window["end_seconds"])
        included = [
            index for index, segment in enumerate(segments)
            if (_number(segment.get("end_seconds")) or 0.0) > start
            and (_number(segment.get("start_seconds")) or 0.0) < end
        ]
        window["included_segment_indexes"] = included
        window["excluded_segment_indexes"] = [
            index for index in range(len(segments)) if index not in set(included)
        ]
    return IdentityBoundaryReviewResult(window, records)


def apply_identity_boundary_review(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Apply persisted production evidence and retain its causal records."""
    result = dict(payload)
    window = result.get("sermon_window")
    segments = result.get("segments")
    if not isinstance(window, Mapping) or not isinstance(segments, Sequence):
        return result
    typed_segments = [segment for segment in segments if isinstance(segment, Mapping)]
    evidence = (
        result.get("identity_boundary_evidence")
        if isinstance(result.get("identity_boundary_evidence"), Mapping)
        else None
    )
    prior = result.get("identity_boundary_review")
    if isinstance(prior, Mapping):
        synchronization = prior.get("synchronization")
        if (
            prior.get("policy_version") == POLICY_VERSION
            and isinstance(synchronization, Mapping)
            and synchronization.get("version") == SYNCHRONIZATION_VERSION
            and synchronization.get("output_window_fingerprint")
            == _window_fingerprint(window)
            and synchronization.get("segments_fingerprint")
            == _segments_fingerprint(typed_segments)
            and synchronization.get("evidence_fingerprint")
            == _evidence_fingerprint(evidence)
        ):
            return result
    prior_records = prior.get("records", ()) if isinstance(prior, Mapping) else ()
    input_window_fingerprint = _window_fingerprint(window)
    reviewed = review_identity_boundaries(
        window,
        typed_segments,
        evidence,
        existing_records=prior_records if isinstance(prior_records, Sequence) else (),
    )
    result["sermon_window"] = reviewed.sermon_window
    result["identity_boundary_review"] = {
        "schema_version": 1,
        "policy_version": POLICY_VERSION,
        "records": reviewed.records,
        "synchronization": {
            "version": SYNCHRONIZATION_VERSION,
            "input_window_fingerprint": input_window_fingerprint,
            "output_window_fingerprint": _window_fingerprint(reviewed.sermon_window),
            "segments_fingerprint": _segments_fingerprint(typed_segments),
            "evidence_fingerprint": _evidence_fingerprint(evidence),
        },
    }
    return result


def _segment_drafts(
    segments: Sequence[Mapping[str, Any]],
) -> list[SegmentDraft]:
    drafts: list[SegmentDraft] = []
    for segment in segments:
        try:
            label = TranscriptSegmentLabel(str(segment.get("label", "unknown")))
        except ValueError:
            label = TranscriptSegmentLabel.UNKNOWN
        drafts.append(
            SegmentDraft(
                start_seconds=_number(segment.get("start_seconds")),
                end_seconds=_number(segment.get("end_seconds")),
                text=str(segment.get("text", "")),
                speaker_hint=(
                    str(segment["speaker_hint"])
                    if isinstance(segment.get("speaker_hint"), str)
                    else None
                ),
                label=label,
                confidence=_number(segment.get("confidence")),
            )
        )
    return drafts


def _identity_guided_transition(
    *,
    edge: str,
    flagged_span: Mapping[str, Any],
    sermon_spans: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
    sermon_window: Mapping[str, Any],
) -> tuple[float, list[Mapping[str, Any]], list[Mapping[str, Any]]] | None:
    current_start = _number(sermon_window.get("start_seconds"))
    current_end = _number(sermon_window.get("end_seconds"))
    if current_start is None or current_end is None or current_end <= current_start:
        return None
    flagged_start = float(flagged_span["start_seconds"])
    flagged_end = float(flagged_span["end_seconds"])
    if edge == "start" and flagged_end <= current_start + 1.0:
        return None
    if edge == "end" and flagged_start >= current_end - 1.0:
        return None
    guide_starts = [
        float(span["start_seconds"])
        for span in sermon_spans
        if current_start <= float(span["start_seconds"]) < current_end
    ]
    guide_ends = [
        float(span["end_seconds"])
        for span in sermon_spans
        if current_start < float(span["end_seconds"]) <= current_end
    ]
    if len(guide_starts) < 3 or len(guide_ends) < 3:
        return None
    guide_start = min(guide_starts)
    guide_end = max(guide_ends)
    rerun = detect_sermon_window(
        _segment_drafts(segments),
        required_guide_start_seconds=guide_start,
        required_guide_end_seconds=guide_end,
    )
    proposed = rerun.start_seconds if edge == "start" else rerun.end_seconds
    if proposed is None:
        return None
    if edge == "start":
        if not current_start < proposed <= guide_start:
            return None
        if flagged_end > proposed + 1.0:
            return None
        removed = _segments_in_range(segments, current_start, proposed)
        retained = _segments_in_range(
            segments,
            proposed,
            min(current_end, proposed + 120.0),
        )
    else:
        if not guide_end <= proposed < current_end:
            return None
        if flagged_start < proposed - 1.0:
            return None
        removed = _segments_in_range(segments, proposed, current_end)
        retained = _segments_in_range(
            segments,
            max(current_start, proposed - 120.0),
            proposed,
        )
    removed_labels = {str(segment.get("label", "unknown")) for segment in removed}
    retained_labels = {str(segment.get("label", "unknown")) for segment in retained}
    removed_has_transition_content = bool(
        removed_labels
        & {
            TranscriptSegmentLabel.ANNOUNCEMENTS.value,
            TranscriptSegmentLabel.MUSIC.value,
            TranscriptSegmentLabel.OTHER.value,
            TranscriptSegmentLabel.PRAYER.value,
        }
    )
    retained_has_sermon_content = bool(
        retained_labels
        & {
            TranscriptSegmentLabel.SERMON.value,
            TranscriptSegmentLabel.READING.value,
        }
    )
    if not removed_has_transition_content or not retained_has_sermon_content:
        return None
    return float(proposed), removed, retained


def identity_boundary_evidence_from_association(
    report: Mapping[str, Any],
    segments: Sequence[Mapping[str, Any]],
    sermon_window: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Adapt a production association artifact into boundary-policy evidence."""
    flags = report.get("sermon_window_quality_flags")
    if not isinstance(flags, Sequence) or isinstance(flags, (str, bytes)):
        return None
    span_selection = report.get("span_selection")
    candidate_selection = (
        span_selection.get("candidate_selection")
        if isinstance(span_selection, Mapping)
        else None
    )
    candidate_selection = candidate_selection if isinstance(candidate_selection, Mapping) else {}
    sermon_spans = _spans(candidate_selection.get("coherent_sermon_speaker_spans"))
    current_window = sermon_window if isinstance(sermon_window, Mapping) else {}
    edges: list[dict[str, Any]] = []
    for flag in flags:
        if not isinstance(flag, Mapping) or flag.get("flag") != "speaker_inconsistent_edge":
            continue
        edge = flag.get("edge")
        flagged_span = _span(flag)
        if edge not in {"start", "end"} or flagged_span is None:
            continue
        reason_codes = [
            str(reason) for reason in flag.get("reason_codes", [])
            if isinstance(reason, str)
        ]
        guided = _identity_guided_transition(
            edge=str(edge),
            flagged_span=flagged_span,
            sermon_spans=sermon_spans,
            segments=segments,
            sermon_window=current_window,
        )
        if guided is None:
            continue
        boundary, removed_segments, retained_segments = guided
        removed_text = _text(removed_segments)
        edges.append({
            "edge": edge,
            "edge_speaker_spans": [flagged_span],
            "materially_inconsistent": "distributed_clip_inconsistent" in reason_codes,
            "coherent_transition_detected": (
                flag.get("coherent_transition_detected") is True
                or bool(retained_segments)
            ),
            "removes_coherent_exposition": (
                flag.get("removes_coherent_exposition")
                if isinstance(flag.get("removes_coherent_exposition"), bool)
                else bool(_EXPOSITION.search(removed_text))
            ),
            "allowed_interruption": (
                flag.get("allowed_interruption")
                if isinstance(flag.get("allowed_interruption"), bool)
                else any(str(segment.get("label")) == "prayer" for segment in removed_segments)
                or bool(_PRAYER_OR_HANDOFF.search(removed_text))
            ),
            "brief_pastoral_handoff": (
                flag.get("brief_pastoral_handoff")
                if isinstance(flag.get("brief_pastoral_handoff"), bool)
                else bool(re.search(r"\b(?:welcome|thank) (?:pastor|reverend|dr\.)\b", removed_text, re.IGNORECASE))
            ),
            "proposed_boundary": boundary,
            "transcript_transition_evidence": (
                {
                    "boundary_seconds": boundary,
                    "transition_kind": "identity_guided_sermon_window_redetection",
                    "confidence": "structural",
                    "before_text_sha256": hashlib.sha256(
                        (
                            _text(removed_segments)
                            if edge == "start"
                            else _text(retained_segments)
                        ).encode()
                    ).hexdigest(),
                    "after_text_sha256": hashlib.sha256(
                        (
                            _text(retained_segments)
                            if edge == "start"
                            else _text(removed_segments)
                        ).encode()
                    ).hexdigest(),
                    "reason_codes": [
                        *reason_codes,
                        "outermost_coherent_clips_used_as_guides",
                        "sermon_window_redetected_with_identity_guides",
                    ],
                }
            ),
        })
    return {
        "schema_version": 1,
        "association_version": report.get("association_version"),
        "model_fingerprint": report.get("model_fingerprint"),
        "automatic_use_allowed": (
            report.get("policy", {}).get("automatic_use_allowed") is True
            if isinstance(report.get("policy"), Mapping)
            else False
        ),
        "source_artifact_sha256": report.get("result_sha256"),
        "sermon_speaker_spans": sermon_spans,
        "edges": edges,
    }


def persist_association_boundary_evidence(
    proposed_json_path: Any, report: Mapping[str, Any]
) -> bool:
    """Persist association evidence beside extraction for final pipeline review."""
    from pathlib import Path

    path = Path(proposed_json_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
        return False
    current_window = (
        payload.get("sermon_window")
        if isinstance(payload.get("sermon_window"), Mapping)
        else {}
    )
    prior_evidence = payload.get("identity_boundary_evidence")
    prior_review = payload.get("identity_boundary_review")
    if (
        isinstance(prior_evidence, Mapping)
        and prior_evidence.get("source_artifact_sha256")
        == report.get("result_sha256")
        and isinstance(prior_review, Mapping)
        and prior_review.get("policy_version") == POLICY_VERSION
        and isinstance(prior_review.get("synchronization"), Mapping)
        and prior_review["synchronization"].get("version")
        == SYNCHRONIZATION_VERSION
        and prior_review["synchronization"].get("output_window_fingerprint")
        == _window_fingerprint(current_window)
        and prior_review["synchronization"].get("segments_fingerprint")
        == _segments_fingerprint([
            segment for segment in payload["segments"] if isinstance(segment, Mapping)
        ])
        and prior_review["synchronization"].get("evidence_fingerprint")
        == _evidence_fingerprint(prior_evidence)
    ):
        return True
    evidence = identity_boundary_evidence_from_association(
        report,
        [segment for segment in payload["segments"] if isinstance(segment, Mapping)],
        payload.get("sermon_window")
        if isinstance(payload.get("sermon_window"), Mapping)
        else None,
    )
    if evidence is None:
        payload.pop("identity_boundary_evidence", None)
    else:
        payload["identity_boundary_evidence"] = evidence
    payload = apply_identity_boundary_review(payload)
    # Association evidence can arrive after extraction originally derived the
    # disposition. Keep the effective disposition causally synchronized now,
    # so a review-required edge cannot continue through identity as accepted.
    from pastor_transcript_extractor.disposition import build_final_disposition

    payload["final_disposition"] = build_final_disposition(
        payload.get("classification"),
        payload.get("sermon_window"),
        guest_speaker_suspected=payload.get("guest_speaker_suspected") is True,
        recording_verification=payload.get("recording_verification"),
        identity_boundary_review=payload.get("identity_boundary_review"),
    )
    if isinstance(payload.get("classification"), dict):
        payload["classification"]["final_disposition"] = payload[
            "final_disposition"
        ]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return True
