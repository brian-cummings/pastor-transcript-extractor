from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pastor_transcript_extractor.media_artifacts import MediaVerificationCache
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    load_reviewed_speaker_evidence,
)
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    AudioSpanCache,
    EmbeddingCache,
    PairDiagnosticCache,
    SherpaOnnxEmbeddingBackend,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    ActivityQualifiedSelectionCache,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    ProfileAssociationReadiness,
    ShadowPolicySpec,
    assess_profile_association_readiness,
    load_shadow_policy,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.workflows.identity.association import (
    ShadowAssociationRequest,
)


@dataclass(frozen=True, slots=True)
class ShadowAssociationSetup:
    database: Database
    cache_root: Path
    verification_cache: MediaVerificationCache
    span_cache: AudioSpanCache
    activity_selection_cache: ActivityQualifiedSelectionCache
    policy_spec: ShadowPolicySpec
    readiness: tuple[ProfileAssociationReadiness, ...]
    backend: Any | None
    embedding_cache: EmbeddingCache | None
    pair_diagnostic_cache: PairDiagnosticCache | None


def initialize_shadow_association(
    request: ShadowAssociationRequest,
    *,
    database_path: Path,
    pair_cache_progress: Callable[[str, int], None] | None = None,
) -> ShadowAssociationSetup:
    """Open association resources while preserving plan-only boundaries."""
    database = Database(database_path, readonly=True)
    cache_root = request.cache_dir.expanduser().resolve()
    verification_cache = MediaVerificationCache(
        cache_root / "media-verification"
    )
    span_cache = AudioSpanCache(cache_root)
    evidence = load_reviewed_speaker_evidence(
        request.evaluation_root.expanduser().resolve()
    )
    policy_spec = load_shadow_policy(request.policy_path)
    readiness = tuple(
        assess_profile_association_readiness(
            database,
            evidence,
            minimum_members=request.minimum_profile_members,
        )
    )
    backend = None
    embedding_cache = None
    pair_diagnostic_cache = None
    if not request.plan_only:
        backend = SherpaOnnxEmbeddingBackend(
            request.model_path.expanduser().resolve(),
            expected_sha256=request.model_sha256,
        )
        embedding_cache = EmbeddingCache(cache_root)
        pair_diagnostic_cache = PairDiagnosticCache(cache_root)
        pair_cache_root = cache_root / "pair-diagnostics"
        if not pair_cache_root.is_dir() or not next(
            pair_cache_root.glob("*.json"), None
        ):
            reports = tuple(
                request.output_root.expanduser().resolve().glob("*/*.json")
            )
            if pair_cache_progress is not None:
                pair_cache_progress("starting", len(reports))
            pair_diagnostic_cache.prime_from_shadow_associations(reports)
            if pair_cache_progress is not None:
                pair_cache_progress("complete", pair_diagnostic_cache.primed)
    return ShadowAssociationSetup(
        database=database,
        cache_root=cache_root,
        verification_cache=verification_cache,
        span_cache=span_cache,
        activity_selection_cache=ActivityQualifiedSelectionCache(cache_root),
        policy_spec=policy_spec,
        readiness=readiness,
        backend=backend,
        embedding_cache=embedding_cache,
        pair_diagnostic_cache=pair_diagnostic_cache,
    )
