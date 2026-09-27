from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class IdentityWorkflowRequest:
    """Validated command input for one guarded identity workflow run."""

    youtube_video_id: str | None
    all_extractions: bool
    plan_only: bool
    skip_discovery: bool
    apply_automatic: bool
    apply_confirmations: bool
    apply_promotions: bool
    apply_machine_canary: bool
    machine_assignment_policy_path: Path | None
    review_prewarm_limit: int
    base_dir: Path | None
    jobs: int
