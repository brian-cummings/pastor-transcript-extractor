from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ShadowAssociationRequest:
    """Complete public input for one shadow-association operation."""

    youtube_video_id: str | None
    all_eligible: bool
    unattempted_only: bool
    neighborhood_profile_ids: tuple[int, ...]
    include_profiled: bool
    limit: int | None
    plan_only: bool
    minimum_profile_members: int
    maximum_exemplars: int
    minimum_same_exemplars: int
    maximum_global_profiles: int
    jobs: int
    model_path: Path
    model_sha256: str
    policy_path: Path
    evaluation_root: Path
    cache_dir: Path
    output_root: Path
    base_dir: Path | None


def validate_shadow_association_request(
    request: ShadowAssociationRequest,
) -> None:
    """Validate selection-mode invariants before any external access."""
    selection_modes = sum(
        (
            request.youtube_video_id is not None,
            request.all_eligible,
            bool(request.neighborhood_profile_ids),
        )
    )
    if selection_modes != 1:
        raise ValueError(
            "Pass exactly one of --youtube-video-id, --all-eligible, or "
            "--neighborhood-profile-id."
        )
    if request.unattempted_only and not request.all_eligible:
        raise ValueError("--unattempted-only requires --all-eligible.")
    if request.minimum_same_exemplars > request.maximum_exemplars:
        raise ValueError(
            "--minimum-same-exemplars cannot exceed --maximum-exemplars."
        )
