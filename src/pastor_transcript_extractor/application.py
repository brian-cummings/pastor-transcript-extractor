from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from pastor_transcript_extractor.config import AppPaths, LlmConfig, build_llm_config
from pastor_transcript_extractor.exporting import PastorReviewMarkdownResult, export_pastor_review_markdown
from pastor_transcript_extractor.extraction import extract_video
from pastor_transcript_extractor.local_llm import LocalLlmClient, OllamaClient
from pastor_transcript_extractor.models import VideoStatus
from pastor_transcript_extractor.storage import Database


EventCallback = Callable[[str], None]
ProgressCallback = Callable[[str, int, int], None]


@dataclass(frozen=True, slots=True)
class ExtractionBatchResult:
    processed: int
    skipped: int
    failed: int


@dataclass(frozen=True, slots=True)
class PastorReviewResult:
    pastor_slug: str
    prepared: ExtractionBatchResult
    export: PastorReviewMarkdownResult


@dataclass(frozen=True, slots=True)
class ReviewBatchResult:
    pastors: tuple[PastorReviewResult, ...]

    @property
    def prepared(self) -> int:
        return sum(result.prepared.processed for result in self.pastors)

    @property
    def failed(self) -> int:
        return sum(result.prepared.failed for result in self.pastors)


def _emit(callback: EventCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _build_classifier_client(
    classifier: str,
    llm_model: str | None,
) -> tuple[LlmConfig, LocalLlmClient | None]:
    if classifier not in {"auto", "rules", "llm"}:
        raise ValueError("Classifier must be one of: auto, rules, llm")
    llm_config = build_llm_config()
    if llm_model is not None:
        llm_config = replace(llm_config, model=llm_model)
    client = (
        OllamaClient(llm_config)
        if classifier == "llm" or (classifier == "auto" and llm_config.enabled)
        else None
    )
    return llm_config, client


def _classifier_summary(classifier: str, llm_config: LlmConfig, llm_client: LocalLlmClient | None) -> str:
    if classifier == "rules":
        return "Classifier: rules (Ollama will not be called)."
    if llm_client is None:
        return "Classifier: auto -> rules (Ollama disabled by PTE_LLM_ENABLED)."
    fallback = "rules fallback enabled" if classifier == "auto" else "strict; no rules fallback"
    return f"Classifier: {classifier} -> Ollama {llm_config.model} ({fallback})."


def extract_batch(
    database: Database,
    paths: AppPaths,
    *,
    missing_only: bool = False,
    force: bool = False,
    source_id: int | None = None,
    pastor_id: int | None = None,
    video_ids: set[int] | None = None,
    classifier: str = "auto",
    llm_model: str | None = None,
    event_callback: EventCallback | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ExtractionBatchResult:
    """Extract eligible videos through the single adaptive production path."""
    llm_config, llm_client = _build_classifier_client(classifier, llm_model)
    _emit(event_callback, _classifier_summary(classifier, llm_config, llm_client))
    videos = database.list_videos()
    if source_id is not None:
        videos = [video for video in videos if video.source_id == source_id]
    if pastor_id is not None:
        videos = [video for video in videos if video.pastor_id == pastor_id]
    if video_ids is not None:
        videos = [video for video in videos if video.id in video_ids]

    processed = 0
    skipped = 0
    failed = 0
    for video in videos:
        if video.pastor_id is None:
            skipped += 1
            continue
        latest_artifact = database.get_latest_transcript_artifact_for_video(video.id)
        if latest_artifact is None:
            skipped += 1
            continue
        latest_extraction = database.get_latest_extraction_result_for_video(video.id)
        if missing_only and latest_extraction is not None and not force:
            skipped += 1
            continue
        if (
            not force
            and latest_extraction is not None
            and video.status in {VideoStatus.EXTRACTED, VideoStatus.EXPORTED}
        ):
            skipped += 1
            continue

        _emit(event_callback, f"Extracting video #{video.id}: {video.title}")
        try:
            extract_video(
                database,
                paths,
                video.id,
                classifier=classifier,
                llm_client=llm_client,
                prompt_version=llm_config.prompt_version,
                context_size=llm_config.context_size,
                progress=progress_callback,
            )
        except Exception as error:
            database.update_video_status(video.id, VideoStatus.FAILED, str(error))
            _emit(event_callback, f"ERROR: Failed to extract video #{video.id}: {error}")
            failed += 1
            continue
        _emit(event_callback, f"Extracted video #{video.id}")
        processed += 1

    return ExtractionBatchResult(processed=processed, skipped=skipped, failed=failed)


def prepare_review_exports(
    database: Database,
    paths: AppPaths,
    *,
    pastor_slug: str | None = None,
    all_pastors: bool = False,
    classifier: str = "auto",
    llm_model: str | None = None,
    event_callback: EventCallback | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ReviewBatchResult:
    """Adaptively prepare missing extractions and build disposition-aware exports."""
    if all_pastors and pastor_slug is not None:
        raise ValueError("Do not pass a pastor slug when building all pastor reviews")
    if not all_pastors and pastor_slug is None:
        raise ValueError("A pastor slug is required unless all_pastors is true")

    if all_pastors:
        pastors = database.list_pastors()
    else:
        pastor = database.get_pastor_by_slug(str(pastor_slug))
        if pastor is None:
            raise ValueError(f"Unknown pastor slug: {pastor_slug}")
        pastors = [pastor]

    results: list[PastorReviewResult] = []
    for pastor in pastors:
        prepared = extract_batch(
            database,
            paths,
            missing_only=True,
            pastor_id=pastor.id,
            classifier=classifier,
            llm_model=llm_model,
            event_callback=event_callback,
            progress_callback=progress_callback,
        )
        exported = export_pastor_review_markdown(database, paths, pastor.slug)
        results.append(PastorReviewResult(pastor.slug, prepared, exported))
    return ReviewBatchResult(tuple(results))
