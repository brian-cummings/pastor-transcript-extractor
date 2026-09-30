from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping

from pastor_transcript_extractor.application import ExtractionBatchResult
from pastor_transcript_extractor.config import AppPaths
from pastor_transcript_extractor.models import VideoStatus
from pastor_transcript_extractor.storage import Database


PipelineEvent = str | object
PipelineEventCallback = Callable[[PipelineEvent], None]
PipelineOperation = Callable[..., object]


class PipelineScope(str, Enum):
    FAILED = "failed"
    SOURCES = "sources"
    ALL = "all"
    URL = "url"


@dataclass(frozen=True, slots=True)
class PipelineRequest:
    url: str | None = None
    pastor: str | None = None
    all_sources: bool = False
    failed_only: bool = False
    replace_existing: bool = False
    limit: int | None = 26
    all_videos: bool = False
    captions_only: bool = False
    transcribe_missing: bool = True
    jobs: int = 2
    classifier: str = "auto"
    llm_model: str | None = None
    recording_verifier_backend: str = "ollama"
    recording_verifier_model: str | None = None
    skip_review: bool = False
    run_identity: bool = False
    base_dir: Path | None = None
    source_ids: tuple[int, ...] = ()
    cookies_from_browser: str | None = None
    cookies: Path | None = None


@dataclass(frozen=True, slots=True)
class PipelineResult:
    scope: PipelineScope
    video_ids: frozenset[int]
    extraction: ExtractionBatchResult | None = None
    review_batch_count: int = 0
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineDependencies:
    get_database: PipelineOperation
    build_paths: PipelineOperation
    add_source: PipelineOperation
    delete_source: PipelineOperation
    discover: PipelineOperation
    fetch_captions: PipelineOperation
    transcribe: PipelineOperation
    extract: PipelineOperation
    ensure_media: PipelineOperation
    run_identity: PipelineOperation
    prepare_reviews: PipelineOperation


@dataclass(frozen=True, slots=True)
class PostContentIdentityRequest:
    base_dir: Path | None = None
    jobs: int = 2


def run_post_content_identity(
    request: PostContentIdentityRequest,
    *,
    event_callback: Callable[[str], None] | None = None,
    identity_runner: PipelineOperation,
) -> object:
    """Apply the guarded identity policy after content and media stages."""
    if event_callback is not None:
        event_callback(
            "Run identity stage: refreshing reviewed evidence, profile "
            "associations, anonymous discovery, and coordination."
        )
    return identity_runner(
        youtube_video_id=None,
        all_extractions=True,
        plan_only=False,
        skip_discovery=False,
        apply_automatic=True,
        apply_confirmations=False,
        apply_promotions=False,
        base_dir=request.base_dir,
        jobs=request.jobs,
    )


@dataclass(frozen=True, slots=True)
class _ResolvedScope:
    kind: PipelineScope
    database: Database
    source_ids: tuple[int, ...] = ()
    source_id: int | None = None
    video_ids: frozenset[int] = frozenset()
    pastor_slugs: tuple[str, ...] = ()
    skip_reason: str | None = None


def validate_pipeline_request(request: PipelineRequest) -> PipelineScope:
    """Validate mutually exclusive online scopes before any pipeline mutation."""
    if request.failed_only:
        if request.url is not None:
            raise ValueError("Do not pass a URL when using --failed-only.")
        if request.pastor is not None:
            raise ValueError("Do not pass --pastor when using --failed-only.")
        if request.all_sources:
            raise ValueError("Use either --all or --failed-only, not both.")
        if request.source_ids:
            raise ValueError("Use either --source-id or --failed-only, not both.")
        if request.replace_existing:
            raise ValueError("--replace-existing is not valid with --failed-only.")
        return PipelineScope.FAILED

    if request.source_ids:
        if request.url is not None:
            raise ValueError("Do not pass a URL when using --source-id.")
        if request.pastor is not None:
            raise ValueError("Do not pass --pastor when using --source-id.")
        if request.all_sources:
            raise ValueError("Use either --all or --source-id, not both.")
        if request.replace_existing:
            raise ValueError("--replace-existing is only valid for URL runs.")
        return PipelineScope.SOURCES

    if request.all_sources:
        if request.url is not None:
            raise ValueError(
                "Do not pass a URL when using --all. Run either a global sync or "
                "a single-source workflow."
            )
        if request.pastor is not None:
            raise ValueError("Do not pass --pastor when using --all.")
        if request.replace_existing:
            raise ValueError(
                "--replace-existing is only valid for single-source runs."
            )
        return PipelineScope.ALL

    if request.url is None:
        raise ValueError(
            "A URL is required unless you use --all, --source-id, or --failed-only."
        )
    if request.pastor is None:
        raise ValueError("--pastor is required unless you use --all.")
    return PipelineScope.URL


def _pastor_slugs_for_videos(
    database: Database,
    video_ids: frozenset[int],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                pastor.slug
                for video_id in video_ids
                for video in [database.get_video_by_id(video_id)]
                if video is not None and video.pastor_id is not None
                for pastor in [database.get_pastor_by_id(video.pastor_id)]
                if pastor is not None
            }
        )
    )


def _selected_discovery_video_ids(
    discovery: object,
    source_ids: tuple[int, ...],
) -> frozenset[int]:
    selected_by_source = getattr(discovery, "selected_video_ids_by_source", {})
    if not isinstance(selected_by_source, Mapping):
        return frozenset()
    return frozenset(
        video_id
        for source_id in source_ids
        for video_id in selected_by_source.get(source_id, ())
    )


def _resolve_scope(
    request: PipelineRequest,
    kind: PipelineScope,
    dependencies: PipelineDependencies,
    emit: PipelineEventCallback,
) -> _ResolvedScope:
    database = dependencies.get_database(request.base_dir)
    if kind is PipelineScope.FAILED:
        failed_videos = [
            video
            for video in database.list_videos()
            if video.status is VideoStatus.FAILED
        ]
        video_ids = frozenset(video.id for video in failed_videos)
        if not video_ids:
            reason = "No failed videos to reprocess."
            emit(reason)
            return _ResolvedScope(kind, database, skip_reason=reason)
        emit(f"Reprocessing {len(video_ids)} failed video(s) systemwide.")
        pastor_slugs = tuple(
            sorted(
                {
                    pastor.slug
                    for video in failed_videos
                    if video.pastor_id is not None
                    for pastor in [database.get_pastor_by_id(video.pastor_id)]
                    if pastor is not None
                }
            )
        )
        return _ResolvedScope(
            kind,
            database,
            video_ids=video_ids,
            pastor_slugs=pastor_slugs,
        )

    if kind is PipelineScope.SOURCES:
        unknown = [
            source_id
            for source_id in request.source_ids
            if database.get_source_by_id(source_id) is None
        ]
        if unknown:
            raise ValueError("Unknown source id(s): " + ", ".join(map(str, unknown)))
        emit(
            f"Running {len(request.source_ids)} selected source(s): "
            f"{', '.join(map(str, request.source_ids))}."
        )
        return _ResolvedScope(kind, database, source_ids=request.source_ids)

    if kind is PipelineScope.ALL:
        enabled_sources = database.list_processing_enabled_sources()
        if not enabled_sources:
            reason = "No processing-enabled sources configured."
            emit(reason)
            return _ResolvedScope(kind, database, skip_reason=reason)
        source_ids = tuple(source.id for source in enabled_sources)
        disabled_count = len(database.list_sources()) - len(enabled_sources)
        emit(
            f"Running all {len(enabled_sources)} processing-enabled source(s); "
            f"skipping {disabled_count} disabled source(s)."
        )
        return _ResolvedScope(kind, database, source_ids=source_ids)

    if request.replace_existing:
        existing_source = database.get_source_by_url(request.url)
        if existing_source is not None:
            dependencies.delete_source(
                source_id=existing_source.id,
                force=True,
                base_dir=request.base_dir,
            )
            database = dependencies.get_database(request.base_dir)
    dependencies.add_source(
        url=request.url,
        pastor=request.pastor,
        notes=None,
        base_dir=request.base_dir,
    )
    source = database.get_source_by_url(request.url)
    source_id = source.id if source is not None else None
    return _ResolvedScope(
        kind,
        database,
        source_ids=(source_id,) if source_id is not None else (),
        source_id=source_id,
        pastor_slugs=(request.pastor,) if request.pastor is not None else (),
    )


def _discover_recordings(
    request: PipelineRequest,
    scope: _ResolvedScope,
    dependencies: PipelineDependencies,
) -> _ResolvedScope:
    if scope.kind is PipelineScope.FAILED:
        return scope
    if scope.kind is PipelineScope.SOURCES:
        video_ids: set[int] = set()
        for source_id in scope.source_ids:
            discovery = dependencies.discover(
                limit=request.limit,
                all_videos=request.all_videos,
                source_id=source_id,
                base_dir=request.base_dir,
            )
            video_ids.update(_selected_discovery_video_ids(discovery, (source_id,)))
        selected = frozenset(video_ids)
    else:
        discovery = dependencies.discover(
            limit=request.limit,
            all_videos=request.all_videos,
            source_id=scope.source_id,
            base_dir=request.base_dir,
        )
        selected = _selected_discovery_video_ids(discovery, scope.source_ids)
    pastor_slugs = scope.pastor_slugs
    if (
        not request.skip_review
        and scope.kind in {PipelineScope.SOURCES, PipelineScope.ALL}
    ):
        pastor_slugs = _pastor_slugs_for_videos(scope.database, selected)
    return _ResolvedScope(
        scope.kind,
        scope.database,
        source_ids=scope.source_ids,
        source_id=scope.source_id,
        video_ids=selected,
        pastor_slugs=pastor_slugs,
    )


def _acquire_transcripts(
    request: PipelineRequest,
    scope: _ResolvedScope,
    dependencies: PipelineDependencies,
) -> None:
    caption_options: dict[str, object] = {}
    if request.cookies_from_browser is not None:
        caption_options["cookies_from_browser"] = request.cookies_from_browser
    if request.cookies is not None:
        caption_options["cookies"] = request.cookies
    fetch_options: dict[str, object] = {
        "base_dir": request.base_dir,
        "video_ids": set(scope.video_ids),
        **caption_options,
    }
    if scope.kind is PipelineScope.URL:
        fetch_options["source_id"] = scope.source_id
    dependencies.fetch_captions(**fetch_options)
    if request.captions_only:
        return
    transcribe_options: dict[str, object] = {
        "missing_only": (
            scope.kind is PipelineScope.FAILED or request.transcribe_missing
        ),
        "captions_missing_only": request.transcribe_missing,
        "jobs": request.jobs,
        "base_dir": request.base_dir,
        "video_ids": set(scope.video_ids),
    }
    if scope.kind is PipelineScope.URL:
        transcribe_options["source_id"] = scope.source_id
    dependencies.transcribe(**transcribe_options)


def _extract_sermons(
    request: PipelineRequest,
    scope: _ResolvedScope,
    app_paths: AppPaths,
    dependencies: PipelineDependencies,
    emit: PipelineEventCallback,
) -> ExtractionBatchResult:
    extract_options: dict[str, object] = {
        "video_ids": set(scope.video_ids),
        "classifier": request.classifier,
        "llm_model": request.llm_model,
        "recording_verifier_backend": request.recording_verifier_backend,
        "recording_verifier_model": request.recording_verifier_model,
        "event_callback": lambda message: emit(str(message)),
        "progress_callback": lambda stage, current, total: emit(
            f"  {stage} block {current}/{total}"
        ),
    }
    if scope.kind is PipelineScope.FAILED:
        extract_options["missing_only"] = True
        extract_options["workers"] = request.jobs
    if scope.kind is PipelineScope.URL:
        extract_options["source_id"] = scope.source_id
    extraction = dependencies.extract(scope.database, app_paths, **extract_options)
    emit(
        f"Extracted {extraction.processed} video(s); skipped {extraction.skipped}; "
        f"failed {extraction.failed}."
    )
    return extraction


def _prepare_reviews(
    request: PipelineRequest,
    scope: _ResolvedScope,
    app_paths: AppPaths,
    dependencies: PipelineDependencies,
    emit: PipelineEventCallback,
) -> int:
    if request.skip_review:
        return 0
    count = 0
    for pastor_slug in scope.pastor_slugs:
        options: dict[str, object] = {
            "pastor_slug": pastor_slug,
            "classifier": request.classifier,
            "llm_model": request.llm_model,
            "event_callback": lambda message: emit(str(message)),
        }
        if scope.kind is PipelineScope.ALL:
            options["video_ids"] = set(scope.video_ids)
        batch = dependencies.prepare_reviews(scope.database, app_paths, **options)
        emit(batch)
        count += 1
    return count


def run_pipeline(
    request: PipelineRequest,
    *,
    event_callback: PipelineEventCallback | None = None,
    dependencies: PipelineDependencies,
) -> PipelineResult:
    """Run one online content scope through explicit, ordered pipeline stages."""
    def emit(event: PipelineEvent) -> None:
        if event_callback is not None:
            event_callback(event)

    kind = validate_pipeline_request(request)
    scope = _resolve_scope(request, kind, dependencies, emit)
    if scope.skip_reason is not None:
        return PipelineResult(kind, frozenset(), skip_reason=scope.skip_reason)
    scope = _discover_recordings(request, scope, dependencies)
    _acquire_transcripts(request, scope, dependencies)
    app_paths = dependencies.build_paths(request.base_dir, remember=True)
    extraction = _extract_sermons(
        request,
        scope,
        app_paths,
        dependencies,
        emit,
    )
    dependencies.ensure_media(
        scope.database,
        app_paths,
        video_ids=set(scope.video_ids),
    )
    if request.run_identity:
        dependencies.run_identity(request.base_dir, jobs=request.jobs)
    review_count = _prepare_reviews(
        request,
        scope,
        app_paths,
        dependencies,
        emit,
    )
    return PipelineResult(
        scope=kind,
        video_ids=scope.video_ids,
        extraction=extraction,
        review_batch_count=review_count,
    )
