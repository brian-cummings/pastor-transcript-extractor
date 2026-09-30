from __future__ import annotations

from pathlib import Path
from typing import Callable

import typer

from pastor_transcript_extractor.commands.apps import identity_app
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.workflows.identity.association import (
    ShadowAssociationRequest,
    validate_shadow_association_request,
)


DEFAULT_SPEAKER_MODEL_SHA256 = (
    "357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b"
)
ShadowAssociationInvoker = Callable[[ShadowAssociationRequest], tuple[Path, ...]]
_shadow_association_invoker: ShadowAssociationInvoker | None = None


def configure_shadow_association(invoker: ShadowAssociationInvoker) -> None:
    """Bind the decomposed association workflow at composition time."""
    global _shadow_association_invoker
    _shadow_association_invoker = invoker


@identity_app.command(
    "shadow-associate-speakers",
    help="Propose multi-exemplar profile matches without changing registry membership.",
)
def shadow_associate_speakers_command(
    youtube_video_id: str | None = typer.Option(
        None, "--youtube-video-id", help="Evaluate one YouTube video."
    ),
    all_eligible: bool = typer.Option(
        False,
        "--all-eligible",
        help="Evaluate every currently eligible unassigned sermon observation.",
    ),
    unattempted_only: bool = typer.Option(
        False,
        "--unattempted-only",
        help=(
            "With --all-eligible, evaluate only current observations with no "
            "persisted shadow-association attempt."
        ),
    ),
    neighborhood_profile_id: list[int] = typer.Option(
        [],
        "--neighborhood-profile-id",
        min=1,
        help=(
            "Replay only observations with persisted direct routing, comparison, "
            "proposal, or exemplar-exclusion evidence for this profile; repeatable."
        ),
    ),
    include_profiled: bool = typer.Option(
        False,
        "--include-profiled",
        help=(
            "Include already-profiled observations for boundary-evidence "
            "regeneration; profile membership remains unchanged."
        ),
    ),
    limit: int | None = typer.Option(
        None,
        min=1,
        help="Maximum candidates to evaluate when using --all-eligible.",
    ),
    plan_only: bool = typer.Option(
        False,
        "--plan-only",
        help="Report readiness and candidate coverage without acoustic execution.",
    ),
    minimum_profile_members: int = typer.Option(
        3,
        min=3,
        help="Distinct reviewed members required for shadow profile matching.",
    ),
    maximum_exemplars: int = typer.Option(
        3,
        min=2,
        help="Maximum independently recorded exemplars compared per profile.",
    ),
    minimum_same_exemplars: int = typer.Option(
        2,
        min=2,
        help="Same-speaker comparisons required to propose one profile.",
    ),
    maximum_global_profiles: int = typer.Option(
        1,
        min=1,
        help=(
            "Maximum cross-source acoustic fallback profiles when no "
            "same-source, explicit-name, or confirmation route exists."
        ),
    ),
    jobs: int = typer.Option(
        2,
        "--jobs",
        min=1,
        help="Concurrent acoustic preprocessing and comparison jobs.",
    ),
    model_path: Path | None = typer.Option(
        None,
        help="Local ONNX speaker-embedding model.",
    ),
    model_sha256: str = typer.Option(
        DEFAULT_SPEAKER_MODEL_SHA256,
        help="Required checksum for the local model.",
    ),
    policy_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/policies/"
            "campplus-development-candidate-v1.json"
        ),
        help="Pinned approved or experimental shadow decision policy.",
    ),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-pair drafts, reviews, and fixtures root.",
    ),
    cache_dir: Path | None = typer.Option(
        None,
        help="Ignored exact-span, embedding, and media-verification cache.",
    ),
    output_root: Path | None = typer.Option(
        None,
        help="Ignored versioned shadow-association artifacts.",
    ),
    base_dir: Path | None = typer.Option(
        None, help="Override app data directory."
    ),
) -> tuple[Path, ...]:
    if _shadow_association_invoker is None:
        raise RuntimeError("Shadow association workflow was not configured.")
    paths = build_paths(base_dir)
    request = ShadowAssociationRequest(
        youtube_video_id=youtube_video_id,
        all_eligible=all_eligible,
        unattempted_only=unattempted_only,
        neighborhood_profile_ids=tuple(neighborhood_profile_id),
        include_profiled=include_profiled,
        limit=limit,
        plan_only=plan_only,
        minimum_profile_members=minimum_profile_members,
        maximum_exemplars=maximum_exemplars,
        minimum_same_exemplars=minimum_same_exemplars,
        maximum_global_profiles=maximum_global_profiles,
        jobs=jobs,
        model_path=model_path or (
            paths.evaluation
            / "speaker-pairs/models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
        ),
        model_sha256=model_sha256,
        policy_path=policy_path,
        evaluation_root=evaluation_root,
        cache_dir=cache_dir or paths.evaluation / "speaker-pairs/cache",
        output_root=output_root or paths.evaluation / "speaker-associations/shadow-runs",
        base_dir=base_dir,
    )
    try:
        validate_shadow_association_request(request)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    return _shadow_association_invoker(request)
