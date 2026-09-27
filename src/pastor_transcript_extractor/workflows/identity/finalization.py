from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Sequence

from pastor_transcript_extractor.config import AppPaths
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class ActionableReviewAudioPreparation:
    requested: int
    prepared: int
    already_cached: int
    excluded: int
    failed: int
    ready_fingerprints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CoordinationStageRequest:
    """Inputs for the final read-only identity coordination report."""

    youtube_video_id: str | None
    all_extractions: bool
    discovery_report: Path | None
    discovery_root: Path
    model_sha256: str
    base_dir: Path | None


@dataclass(frozen=True, slots=True)
class ReviewPrewarmStageResult:
    """One terminal review-audio prewarm outcome."""

    status: str
    preparation: ActionableReviewAudioPreparation | None = None
    error: str | None = None


def run_coordination_stage(
    request: CoordinationStageRequest,
    *,
    coordinator: Callable[..., object],
) -> object:
    """Write the final shadow-only coordination report with pinned inputs."""
    return coordinator(
        youtube_video_id=request.youtube_video_id,
        all_extractions=request.all_extractions,
        execute_shadow=False,
        discovery_report=request.discovery_report,
        discovery_root=request.discovery_root,
        model_path=Path(
            "evaluation/speaker-pairs/models/"
            "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
        ),
        model_sha256=request.model_sha256,
        policy_path=Path(
            "evaluation/speaker-pairs/policies/"
            "campplus-development-candidate-v1.json"
        ),
        evaluation_root=Path("evaluation/speaker-pairs"),
        cache_dir=Path("evaluation/speaker-pairs/cache"),
        association_root=Path("evaluation/speaker-associations/shadow-runs"),
        output_root=None,
        base_dir=request.base_dir,
    )


def run_review_prewarm_stage(
    database_path: Path,
    paths: AppPaths,
    *,
    plan_only: bool,
    all_extractions: bool,
    limit: int,
    discovery_report: Path | None,
    association_reports: Sequence[Path],
    automatic_profile_ready_ids: frozenset[int],
    prewarmer: Callable[..., ActionableReviewAudioPreparation],
) -> ReviewPrewarmStageResult:
    """Prepare actionable review audio only for an executing corpus run."""
    if plan_only:
        return ReviewPrewarmStageResult("plan_only")
    if not all_extractions:
        return ReviewPrewarmStageResult("deferred")
    if not limit:
        return ReviewPrewarmStageResult("disabled")
    try:
        preparation = prewarmer(
            Database(database_path, readonly=True),
            paths,
            discovery_report=discovery_report,
            association_reports=tuple(association_reports),
            limit=limit,
            automatic_profile_ready_ids=automatic_profile_ready_ids,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return ReviewPrewarmStageResult(
            "failed", error=f"{type(error).__name__}: {error}"
        )
    return ReviewPrewarmStageResult("executed", preparation=preparation)
