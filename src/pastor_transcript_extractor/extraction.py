from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pastor_transcript_extractor.config import AppPaths, build_video_artifact_paths
from pastor_transcript_extractor.disposition import build_final_disposition
from pastor_transcript_extractor.identity import record_shadow_identity_assessment
from pastor_transcript_extractor.local_llm import LocalLlmClient
from pastor_transcript_extractor.models import ExtractionResult, TranscriptArtifact, TranscriptSegment, TranscriptSegmentLabel, TranscriptSourceKind, VideoStatus
from pastor_transcript_extractor.sermon_detection import GuestSpeakerFlags, SermonWindowResult, detect_guest_speaker_flags, detect_sermon_window
from pastor_transcript_extractor.segmentation import SegmentDraft, segment_transcript
from pastor_transcript_extractor.sermon_classification import (
    BLOCK_BUILDER_VERSION,
    COARSE_DISCOVERY_VERSION,
    CONFIDENCE_POLICY_VERSION,
    FINE_COMPONENT_VERSION,
    HybridSermonResult,
    classify_sermon_content_adaptive,
)
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class ExtractionRunResult:
    extraction_result: ExtractionResult
    segments_path: Path
    proposed_text_path: Path
    proposed_json_path: Path
    segment_count: int


@dataclass(frozen=True, slots=True)
class ReclassificationRunResult:
    proposed_json_path: Path
    classification_path: Path
    confidence_tier: str
    retained_segment_count: int
    reused: bool
    disposition_status: str = "unknown"
    cache_hits: int = 0
    cache_misses: int = 0


def _record_identity_shadow_safely(
    database: Database,
    app_paths: AppPaths,
    *,
    video: Any,
    pastor: Any,
    extraction_result: ExtractionResult,
    content_disposition: dict[str, Any],
) -> None:
    """Keep shadow identity instrumentation from becoming a content-path dependency."""
    if (
        not isinstance(getattr(video, "id", None), int)
        or not isinstance(getattr(pastor, "id", None), int)
        or not isinstance(getattr(extraction_result, "id", None), int)
    ):
        return
    try:
        record_shadow_identity_assessment(
            database,
            app_paths,
            video=video,
            pastor=pastor,
            extraction_result=extraction_result,
            content_disposition=content_disposition,
        )
    except Exception as error:  # pragma: no cover - defensive production isolation
        warnings.warn(
            f"Shadow identity assessment failed for video {video.id}: {error}",
            RuntimeWarning,
            stacklevel=2,
        )


def _classify_with_fallback(
    drafts: list[SegmentDraft],
    detected_window: SermonWindowResult,
    *,
    classifier: str,
    llm_client: LocalLlmClient | None,
    prompt_version: str,
    cache_dir: Path | None = None,
    context_size: int = 4096,
    progress: Any | None = None,
) -> tuple[dict[str, Any], HybridSermonResult | None]:
    classification: dict[str, Any] = {
        "schema_version": 1,
        "method": "rule_based_v1",
        "model": None,
        "prompt_version": prompt_version,
        "confidence_tier": "medium" if detected_window.suspicious_boundary else "high",
        "retained_segment_indexes": detected_window.included_segment_indexes,
        "excluded_segment_indexes": detected_window.excluded_segment_indexes,
        "uncertain_block_ids": [],
        "warnings": list(detected_window.suspicious_boundary_reasons),
        "blocks": [],
        "classifications": [],
        "search": {
            "schema_version": 1,
            "algorithm_version": "rule_based_v1",
            "candidates": [],
            "selected_rank": None,
            "rule_baseline": {
                "start_seconds": detected_window.start_seconds,
                "end_seconds": detected_window.end_seconds,
                "confidence": detected_window.confidence,
            },
            "rule_baseline_source": "recomputed_rules",
            "rule_baseline_algorithm_version": detected_window.method,
            "manual_override_present": False,
        },
    }
    if classifier not in {"rules", "auto", "llm"}:
        raise ValueError(f"Unknown classifier mode: {classifier}")
    if classifier == "llm" and llm_client is None:
        raise ValueError("LLM classifier requested but no local LLM client is configured")
    if classifier not in {"auto", "llm"} or llm_client is None:
        return classification, None
    try:
        digest_method = getattr(llm_client, "model_digest", None)
        model_digest = digest_method() if callable(digest_method) else None
        hybrid_result = classify_sermon_content_adaptive(
            drafts,
            detected_window,
            llm_client,
            prompt_version=prompt_version,
            progress=progress,
            cache_dir=cache_dir,
            model_digest=model_digest,
            context_size=context_size,
            rule_baseline_source="recomputed_rules",
            rule_baseline_algorithm_version=detected_window.method,
            manual_override_present=False,
        )
    except Exception as error:
        if classifier == "llm":
            raise
        classification["method"] = "rule_based_fallback"
        classification["confidence_tier"] = "low"
        classification["warnings"].append(f"local LLM classification failed: {error}")
        return classification, None
    return hybrid_result.to_dict(), hybrid_result


def _classification_is_current(
    classification: object, *, model: str, prompt_version: str
) -> bool:
    return (
        isinstance(classification, dict)
        and classification.get("method") == "adaptive_llm_v3"
        and classification.get("block_builder_version") == BLOCK_BUILDER_VERSION
        and classification.get("coarse_discovery_version") == COARSE_DISCOVERY_VERSION
        and classification.get("fine_component_version") == FINE_COMPONENT_VERSION
        and classification.get("model") == model
        and classification.get("prompt_version") == prompt_version
        and classification.get("confidence_policy_version") == CONFIDENCE_POLICY_VERSION
    )


def _drafts_from_proposed_json(payload: dict[str, Any]) -> list[SegmentDraft]:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list):
        raise ValueError("Proposed extraction has no reusable transcript segments")
    drafts: list[SegmentDraft] = []
    for raw in raw_segments:
        if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
            raise ValueError("Proposed extraction contains an invalid transcript segment")
        try:
            label = TranscriptSegmentLabel(str(raw.get("label", "unknown")))
        except ValueError:
            label = TranscriptSegmentLabel.UNKNOWN
        drafts.append(
            SegmentDraft(
                start_seconds=float(raw["start_seconds"]) if isinstance(raw.get("start_seconds"), (int, float)) else None,
                end_seconds=float(raw["end_seconds"]) if isinstance(raw.get("end_seconds"), (int, float)) else None,
                text=str(raw["text"]),
                speaker_hint=str(raw["speaker_hint"]) if isinstance(raw.get("speaker_hint"), str) else None,
                label=label,
                confidence=float(raw["confidence"]) if isinstance(raw.get("confidence"), (int, float)) else None,
            )
        )
    return drafts


def _manual_override_window_result(
    drafts: list[SegmentDraft],
    detected_window: SermonWindowResult,
    override: dict[str, Any],
) -> SermonWindowResult:
    start = float(override["start_seconds"])
    end = float(override["end_seconds"])
    included = [
        index
        for index, draft in enumerate(drafts)
        if draft.start_seconds is not None
        and draft.end_seconds is not None
        and draft.end_seconds > start
        and draft.start_seconds < end
    ]
    included_set = set(included)
    timed = [
        index
        for index, draft in enumerate(drafts)
        if draft.start_seconds is not None and draft.end_seconds is not None
    ]
    return SermonWindowResult(
        start_seconds=start,
        end_seconds=end,
        confidence=1.0,
        reasons=["manual review override applied"],
        method="manual_override_v1",
        included_segment_indexes=included,
        excluded_segment_indexes=[index for index in timed if index not in included_set],
        suspicious_boundary=False,
        suspicious_boundary_reasons=[],
    )


def _baseline_window_payload(
    window: SermonWindowResult,
    *,
    manual_override_present: bool,
) -> dict[str, Any]:
    return {
        "start_seconds": window.start_seconds,
        "end_seconds": window.end_seconds,
        "confidence": window.confidence,
        "reasons": list(window.reasons),
        "method": window.method,
        "source": "override" if manual_override_present else "detected",
        "included_segment_indexes": list(window.included_segment_indexes),
        "excluded_segment_indexes": list(window.excluded_segment_indexes),
        "suspicious_boundary": window.suspicious_boundary,
        "suspicious_boundary_reasons": list(window.suspicious_boundary_reasons),
    }


def reclassify_video(
    database: Database,
    app_paths: AppPaths,
    video_id: int,
    *,
    llm_client: LocalLlmClient,
    prompt_version: str = "sermon-content-v1",
    force: bool = False,
    progress: Any | None = None,
    model_digest: str | None = None,
    context_size: int = 4096,
) -> ReclassificationRunResult:
    video = database.get_video_by_id(video_id)
    if video is None:
        raise ValueError(f"Unknown video id: {video_id}")
    pastor = database.get_pastor_by_id(video.pastor_id) if video.pastor_id is not None else None
    if pastor is None:
        raise ValueError(f"Video {video_id} is missing a linked pastor")
    latest_extraction = database.get_latest_extraction_result_for_video(video.id)
    if latest_extraction is None or not latest_extraction.proposed_json_path:
        raise ValueError(f"Video {video_id} has no proposed extraction to reclassify")
    proposed_json_path = Path(latest_extraction.proposed_json_path)
    payload = _load_json(proposed_json_path)
    if payload is None:
        raise ValueError(f"Video {video_id} has an invalid proposed JSON artifact")
    video_paths = build_video_artifact_paths(app_paths, pastor.slug, video.youtube_video_id)
    classification_path = video_paths.extracted / "llm-classification-v1.json"
    existing = payload.get("classification")
    if not force and _classification_is_current(
        existing, model=llm_client.model, prompt_version=prompt_version
    ):
        assert isinstance(existing, dict)
        disposition = build_final_disposition(
            existing,
            payload.get("sermon_window"),
            guest_speaker_suspected=payload.get("guest_speaker_suspected") is True,
        )
        if payload.get("final_disposition") != disposition or existing.get("final_disposition") != disposition:
            payload["final_disposition"] = disposition
            existing["final_disposition"] = disposition
            proposed_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            classification_path.write_text(json.dumps(existing, indent=2, sort_keys=True), encoding="utf-8")
        _record_identity_shadow_safely(
            database,
            app_paths,
            video=video,
            pastor=pastor,
            extraction_result=latest_extraction,
            content_disposition=disposition,
        )
        return ReclassificationRunResult(
            proposed_json_path,
            classification_path,
            str(existing.get("confidence_tier", "unknown")),
            len(existing.get("retained_segment_indexes", [])),
            True,
            str(disposition["status"]),
        )

    drafts = _drafts_from_proposed_json(payload)
    try:
        transcript_source = TranscriptSourceKind(str(payload.get("transcript_source")))
    except ValueError:
        transcript_source = None
    recomputed_window = detect_sermon_window(drafts, transcript_source=transcript_source)
    override_path = video_paths.review / "window_override.json"
    override, _ = _load_window_override(override_path)
    detected_window = (
        _manual_override_window_result(drafts, recomputed_window, override)
        if override is not None
        else recomputed_window
    )
    hybrid = classify_sermon_content_adaptive(
        drafts,
        detected_window,
        llm_client,
        prompt_version=prompt_version,
        progress=progress,
        cache_dir=video_paths.extracted / "inference-cache",
        model_digest=model_digest,
        context_size=context_size,
        rule_baseline_source="manual_override" if override is not None else "recomputed_rules",
        rule_baseline_algorithm_version=detected_window.method,
        manual_override_present=override is not None,
    )
    classification = hybrid.to_dict()
    payload["classification"] = classification

    existing_window = _baseline_window_payload(
        detected_window,
        manual_override_present=override is not None,
    )
    payload["sermon_window"] = existing_window
    if (
        override is None
        and isinstance(existing_window, dict)
        and hybrid.confidence_tier != "low"
        and hybrid.retained_segment_indexes
    ):
        retained = [drafts[index] for index in hybrid.retained_segment_indexes]
        starts = [draft.start_seconds for draft in retained if draft.start_seconds is not None]
        ends = [draft.end_seconds for draft in retained if draft.end_seconds is not None]
        existing_window.update(
            {
                "start_seconds": min(starts) if starts else existing_window.get("start_seconds"),
                "end_seconds": max(ends) if ends else existing_window.get("end_seconds"),
                "method": hybrid.method,
                "source": "hybrid_llm",
                "included_segment_indexes": hybrid.retained_segment_indexes,
                "excluded_segment_indexes": hybrid.excluded_segment_indexes,
                "suspicious_boundary": hybrid.confidence_tier != "high",
                "suspicious_boundary_reasons": hybrid.warnings,
            }
        )
    disposition = build_final_disposition(
        classification,
        existing_window,
        guest_speaker_suspected=payload.get("guest_speaker_suspected") is True,
    )
    classification["final_disposition"] = disposition
    payload["final_disposition"] = disposition
    proposed_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    classification_path.write_text(json.dumps(classification, indent=2, sort_keys=True), encoding="utf-8")
    _record_identity_shadow_safely(
        database,
        app_paths,
        video=video,
        pastor=pastor,
        extraction_result=latest_extraction,
        content_disposition=disposition,
    )
    return ReclassificationRunResult(
        proposed_json_path,
        classification_path,
        hybrid.confidence_tier,
        len(hybrid.retained_segment_indexes),
        False,
        str(disposition["status"]),
        int(classification.get("cache_stats", {}).get("hits", 0)),
        int(classification.get("cache_stats", {}).get("misses", 0)),
    )


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _read_text(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _load_window_override(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    payload = _load_json(path)
    if payload is None:
        return None, None if not path.exists() else "invalid override ignored: could not parse JSON object"
    start_seconds = payload.get("start_seconds")
    end_seconds = payload.get("end_seconds")
    if not isinstance(start_seconds, (int, float)) or not isinstance(end_seconds, (int, float)):
        return None, "invalid override ignored: start_seconds and end_seconds must be numbers"
    start = float(start_seconds)
    end = float(end_seconds)
    if end <= start:
        return None, "invalid override ignored: end_seconds must be greater than start_seconds"
    notes = payload.get("notes")
    updated_at = payload.get("updated_at")
    updated_by = payload.get("updated_by")
    if notes is not None and not isinstance(notes, str):
        return None, "invalid override ignored: notes must be a string when provided"
    if updated_at is not None and not isinstance(updated_at, str):
        return None, "invalid override ignored: updated_at must be a string when provided"
    if updated_by is not None and not isinstance(updated_by, str):
        return None, "invalid override ignored: updated_by must be a string when provided"
    return {
        "start_seconds": start,
        "end_seconds": end,
        "notes": notes,
        "updated_at": updated_at,
        "updated_by": updated_by,
    }, None


def _segment_to_storage(
    database: Database,
    video_id: int,
    artifact: TranscriptArtifact,
    draft: SegmentDraft,
) -> TranscriptSegment:
    return database.add_transcript_segment(
        video_id=video_id,
        artifact_id=artifact.id,
        start_seconds=draft.start_seconds,
        end_seconds=draft.end_seconds,
        text=draft.text,
        label=draft.label,
        speaker_hint=draft.speaker_hint,
        confidence=draft.confidence,
    )


def _format_timestamp(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    total_seconds = max(0, int(seconds))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes:02d}:{remaining_seconds:02d}"


def _transcript_duration(drafts: list[SegmentDraft]) -> float | None:
    timed_ends = [draft.end_seconds for draft in drafts if draft.end_seconds is not None]
    return max(timed_ends) if timed_ends else None


def _effective_sermon_window(
    detected_window: SermonWindowResult,
    override: dict[str, Any] | None,
    override_error: str | None,
) -> dict[str, Any]:
    reasons = list(detected_window.reasons)
    source = "detected"
    start_seconds = detected_window.start_seconds
    end_seconds = detected_window.end_seconds
    if override_error:
        reasons.append(override_error)
    if override is not None:
        source = "override"
        start_seconds = float(override["start_seconds"])
        end_seconds = float(override["end_seconds"])
        reasons = ["manual review override applied"]
        if override.get("notes"):
            reasons.append(str(override["notes"]))
    return {
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "confidence": detected_window.confidence,
        "reasons": reasons,
        "method": detected_window.method,
        "source": source,
        "included_segment_indexes": detected_window.included_segment_indexes,
        "excluded_segment_indexes": detected_window.excluded_segment_indexes,
        "suspicious_boundary": detected_window.suspicious_boundary,
        "suspicious_boundary_reasons": detected_window.suspicious_boundary_reasons,
    }


def _build_proposed_markdown(
    title: str,
    url: str,
    pastor_slug: str,
    transcript_source: TranscriptSourceKind,
    sermon_window: dict[str, Any],
    final_disposition: dict[str, Any],
    guest_flags: GuestSpeakerFlags,
    drafts: list[SegmentDraft],
) -> str:
    body = "\n\n".join(draft.text for draft in drafts)
    if not body.strip():
        body = "(no transcript text available)"

    duration = _transcript_duration(drafts)
    window_start = _format_timestamp(sermon_window.get("start_seconds"))
    window_end = _format_timestamp(sermon_window.get("end_seconds"))
    window_reasons = "; ".join(sermon_window.get("reasons", [])) or "none"
    lines = [
        f"# {title}",
        "",
        f"- Pastor: {pastor_slug}",
        f"- Source: {url}",
        f"- Transcript Source: {transcript_source.value}",
        f"- Duration: {_format_timestamp(duration)}" if duration is not None else "- Duration: unknown",
        f"- Likely Sermon Window: {window_start} - {window_end}",
        f"- Window Confidence: {sermon_window.get('confidence', 0.0):.2f}",
        f"- Window Source: {sermon_window.get('source', 'detected')}",
        f"- Window Reasons: {window_reasons}",
        f"- Final Disposition: {final_disposition.get('status', 'unknown')}",
        f"- Disposition Reasons: {'; '.join(final_disposition.get('reason_codes', [])) or 'none'}",
        f"- Suspicious Boundary: {'yes' if sermon_window.get('suspicious_boundary') else 'no'}",
        (
            f"- Suspicious Boundary Reasons: {'; '.join(sermon_window.get('suspicious_boundary_reasons', []))}"
            if sermon_window.get("suspicious_boundary_reasons")
            else "- Suspicious Boundary Reasons: none"
        ),
        f"- Guest Speaker Suspected: {'yes' if guest_flags.suspected else 'no'}",
        (
            f"- Guest Speaker Reasons: {'; '.join(guest_flags.reasons)}"
            if guest_flags.reasons
            else "- Guest Speaker Reasons: none"
        ),
        "",
        "## Proposed Transcript",
        "",
        body,
        "",
        "## Segment Notes",
        "",
    ]
    for draft in drafts:
        lines.append(
            f"- [{_format_timestamp(draft.start_seconds)} - {_format_timestamp(draft.end_seconds)}] "
            f"{draft.label.value}: {draft.text}"
        )
    lines.append("")
    return "\n".join(lines)


def extract_video(
    database: Database,
    app_paths: AppPaths,
    video_id: int,
    *,
    classifier: str = "rules",
    llm_client: LocalLlmClient | None = None,
    prompt_version: str = "sermon-content-v1",
    context_size: int = 4096,
    progress: Any | None = None,
) -> ExtractionRunResult:
    video = database.get_video_by_id(video_id)
    if video is None:
        raise ValueError(f"Unknown video id: {video_id}")

    pastor = database.get_pastor_by_id(video.pastor_id) if video.pastor_id is not None else None
    if pastor is None:
        raise ValueError(f"Video {video_id} is missing a linked pastor")

    transcript_artifacts = database.list_transcript_artifacts_for_video(video.id)
    if not transcript_artifacts:
        raise ValueError(f"Video {video_id} has no transcript artifact to extract from")
    transcript_artifact = next(
        (artifact for artifact in reversed(transcript_artifacts) if artifact.source_kind == TranscriptSourceKind.CAPTIONS),
        transcript_artifacts[-1],
    )

    video_paths = build_video_artifact_paths(app_paths, pastor.slug, video.youtube_video_id)
    video_paths.extracted.mkdir(parents=True, exist_ok=True)
    database.delete_transcript_segments_for_video(video.id)

    raw_json = _load_json(Path(transcript_artifact.raw_json_path) if transcript_artifact.raw_json_path else None)
    raw_text = _read_text(Path(transcript_artifact.raw_text_path) if transcript_artifact.raw_text_path else None)
    if not raw_text and raw_json is not None and isinstance(raw_json.get("text"), str):
        raw_text = str(raw_json["text"])

    drafts = segment_transcript(raw_text, raw_json)
    persisted_segments = [_segment_to_storage(database, video.id, transcript_artifact, draft) for draft in drafts]
    detected_window = detect_sermon_window(drafts, transcript_source=transcript_artifact.source_kind)
    classification, hybrid_result = _classify_with_fallback(
        drafts,
        detected_window,
        classifier=classifier,
        llm_client=llm_client,
        prompt_version=prompt_version,
        cache_dir=video_paths.extracted / "inference-cache",
        context_size=context_size,
        progress=progress,
    )
    override_path = video_paths.review / "window_override.json"
    override, override_error = _load_window_override(override_path)
    sermon_window = _effective_sermon_window(detected_window, override, override_error)
    if (
        hybrid_result is not None
        and override is None
        and hybrid_result.confidence_tier != "low"
        and hybrid_result.retained_segment_indexes
    ):
        retained_drafts = [drafts[index] for index in hybrid_result.retained_segment_indexes]
        timed_starts = [draft.start_seconds for draft in retained_drafts if draft.start_seconds is not None]
        timed_ends = [draft.end_seconds for draft in retained_drafts if draft.end_seconds is not None]
        sermon_window.update(
            {
                "start_seconds": min(timed_starts) if timed_starts else sermon_window["start_seconds"],
                "end_seconds": max(timed_ends) if timed_ends else sermon_window["end_seconds"],
                "method": hybrid_result.method,
                "source": "hybrid_llm",
                "included_segment_indexes": hybrid_result.retained_segment_indexes,
                "excluded_segment_indexes": hybrid_result.excluded_segment_indexes,
                "suspicious_boundary": hybrid_result.confidence_tier != "high",
                "suspicious_boundary_reasons": hybrid_result.warnings,
            }
        )
    guest_flags = detect_guest_speaker_flags(
        video_title=video.title,
        drafts=drafts,
        pastor_name=pastor.display_name,
        sermon_window=detected_window,
    )
    final_disposition = build_final_disposition(
        classification,
        sermon_window,
        guest_speaker_suspected=guest_flags.suspected,
    )
    classification["final_disposition"] = final_disposition

    proposed_text = _build_proposed_markdown(
        video.title,
        video.url,
        pastor.slug,
        transcript_artifact.source_kind,
        sermon_window,
        final_disposition,
        guest_flags,
        drafts,
    )
    proposed_text_path = video_paths.extracted / "proposed.md"
    proposed_json_path = video_paths.extracted / "proposed.json"
    segments_path = video_paths.extracted / "segments.json"
    classification_path = video_paths.extracted / "llm-classification-v1.json"

    proposed_text_path.write_text(proposed_text, encoding="utf-8")
    proposed_json = {
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "pastor_slug": pastor.slug,
        "source_url": video.url,
        "transcript_source": transcript_artifact.source_kind.value,
        "sermon_window": sermon_window,
        "classification": classification,
        "final_disposition": final_disposition,
        "guest_speaker_suspected": guest_flags.suspected,
        "guest_name_candidates": guest_flags.name_candidates,
        "guest_signal_reasons": guest_flags.reasons,
        "segment_count": len(persisted_segments),
        "segments": [
            {
                "start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds,
                "text": segment.text,
                "speaker_hint": segment.speaker_hint,
                "label": segment.label.value,
                "confidence": segment.confidence,
            }
            for segment in persisted_segments
        ],
    }
    proposed_json_path.write_text(json.dumps(proposed_json, indent=2, sort_keys=True), encoding="utf-8")
    segments_path.write_text(json.dumps(proposed_json["segments"], indent=2, sort_keys=True), encoding="utf-8")
    classification_path.write_text(json.dumps(classification, indent=2, sort_keys=True), encoding="utf-8")

    extraction_result = database.add_extraction_result(
        video_id=video.id,
        version=1,
        proposed_text_path=str(proposed_text_path),
        proposed_json_path=str(proposed_json_path),
    )
    database.update_video_status(video.id, VideoStatus.EXTRACTED)
    _record_identity_shadow_safely(
        database,
        app_paths,
        video=video,
        pastor=pastor,
        extraction_result=extraction_result,
        content_disposition=final_disposition,
    )
    return ExtractionRunResult(
        extraction_result=extraction_result,
        segments_path=segments_path,
        proposed_text_path=proposed_text_path,
        proposed_json_path=proposed_json_path,
        segment_count=len(persisted_segments),
    )
