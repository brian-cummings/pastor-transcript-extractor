from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath

from pastor_transcript_extractor.config import AppPaths, evaluation_root_for


# Only these repository-relative prefixes are generated. Everything else below
# evaluation/ is treated as source-controlled input by default.
GENERATED_EVALUATION_PREFIXES: tuple[PurePosixPath, ...] = tuple(
    PurePosixPath(value)
    for value in (
        "drafts",
        "results",
        "diagnostics",
        "interaction-diagnostics",
        "recording-verifier",
        "recording-verifier-typesafe",
        "sermon-topics/cache",
        "speaker-pairs/cache",
        "speaker-pairs/drafts",
        "speaker-pairs/models",
        "speaker-pairs/reports",
        "speaker-pairs/runs",
        "speaker-associations/shadow-runs",
        "speaker-profile-discovery/shadow-runs",
        "speaker-profile-discovery/promotion-judgments",
        "source-profile-consolidation/runs",
        "identity-leverage",
    )
)

# Source-backed review artifacts are private data even after human acceptance.
# Keep contracts, policies and decisions separate from their full evidence.
# Patterns are repository-relative and also generate the ignore-policy section.
PRIVATE_EVIDENCE_PATTERNS: tuple[str, ...] = (
    "evaluation/sermon-topics/*.json",
    "evaluation/sermon-topics/*.md",
    "evaluation/sermon-topics/source-material-probe-cache/**",
    "evaluation/g*-*/cache-v*/**",
    "evaluation/g*-*/feasibility-v*.results.*",
    "evaluation/evidence-supply-readiness-v*/**",
    "evaluation/observed-profile-consumer-v*/**",
    "docs/review-proposals/*/sources/**",
    "docs/review-proposals/*/input-*.json",
    "docs/review-proposals/*/input-*.md",
    "docs/review-proposals/*/references-*.json",
    "docs/review-proposals/*/census-*.json",
    "docs/review-proposals/*/source-audit-*.json",
    "docs/review-proposals/*/source-audit-*.md",
    "docs/review-proposals/*/source-review-*.json",
    "docs/review-proposals/*/source-oracle-*.json",
    "docs/review-proposals/*/source-validation-*.json",
    "docs/review-proposals/*/audit-v*.json",
    "docs/review-proposals/*/audit-v*.md",
    "docs/review-proposals/*/development-source-audit-*.json",
    "docs/review-proposals/*/DEVELOPMENT-SOURCE-AUDIT.md",
    "docs/review-proposals/*/SOURCE_REVIEW.md",
    "docs/review-proposals/*/SOURCE-ORACLE-REVIEW.md",
    "docs/review-proposals/*/context-exhibits-*.json",
    "docs/review-proposals/evidence-supply-readiness-v*/cases.md",
    "docs/review-proposals/evidence-supply-readiness-v*/CASES.md",
    "docs/review-proposals/evidence-supply-readiness-v1/REVIEW.md",
    "docs/review-proposals/evidence-supply-collector-v3/design-v3.json",
    "docs/review-proposals/evidence-supply-collector-v3/GEOMETRY_REVIEW.md",
    "docs/review-proposals/profile-evidence-v1/packet-v1.json",
    "docs/review-proposals/profile-evidence-v1/CASES.md",
    "docs/review-proposals/pastor-contracts-v1/registry-v1.json",
    "docs/review-proposals/pastor-contracts-v1/REGISTRY.md",
    "docs/review-proposals/g1-binding-v1/cases-v1.json",
    "docs/review-proposals/g1-binding-v1/CASES.md",
    "docs/review-proposals/g2-g3-v1/cases-v1.json",
    "docs/review-proposals/g2-g3-v1/CASES.md",
    "docs/analytical-review/*.json",
)
PRIVATE_EVIDENCE_EXCEPTIONS = frozenset({
    "evaluation/sermon-topics/behavior-contract-v1.json",
})


def repository_relative_path(path: Path | str, *, repo_root: Path) -> Path | None:
    """Normalize lexically, without following managed compatibility links."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    for repository in (Path(os.path.abspath(repo_root)), repo_root.resolve()):
        try:
            return Path(os.path.abspath(candidate)).relative_to(repository)
        except ValueError:
            continue
    return None


def private_evidence_relative_path(path: Path | str, *, repo_root: Path) -> Path | None:
    relative = repository_relative_path(path, repo_root=repo_root)
    if relative is None or relative.as_posix() in PRIVATE_EVIDENCE_EXCEPTIONS:
        return None
    pure = PurePosixPath(relative.as_posix())
    def matches(pattern: str) -> bool:
        if pattern.endswith("/**"):
            return any(parent.match(pattern[:-3]) for parent in (pure, *pure.parents))
        return pure.match(pattern)
    if any(matches(pattern) for pattern in PRIVATE_EVIDENCE_PATTERNS):
        return relative
    return None


def private_evidence_destination(relative: Path, *, evaluation_root: Path) -> Path:
    # Preserve the original namespace to avoid collisions with evaluation/.
    if relative.parts[0] == "evaluation":
        return evaluation_root / Path(*relative.parts[1:])
    return evaluation_root / "review-packets" / relative


@dataclass(frozen=True, slots=True)
class EvaluationPaths:
    root: Path

    @property
    def speaker_pairs(self) -> Path:
        return self.root / "speaker-pairs"

    @property
    def speaker_pair_cache(self) -> Path:
        return self.speaker_pairs / "cache"

    @property
    def association_runs(self) -> Path:
        return self.root / "speaker-associations" / "shadow-runs"

    @property
    def discovery_runs(self) -> Path:
        return self.root / "speaker-profile-discovery" / "shadow-runs"

    @property
    def promotion_judgments(self) -> Path:
        return self.root / "speaker-profile-discovery" / "promotion-judgments"

    @property
    def diagnostics(self) -> Path:
        return self.root / "diagnostics"

    @property
    def identity_leverage(self) -> Path:
        return self.root / "identity-leverage"


def build_evaluation_paths(paths: AppPaths) -> EvaluationPaths:
    return EvaluationPaths(root=paths.evaluation)


def generated_relative_path(path: Path | str, *, repo_root: Path) -> Path | None:
    """Return the path below legacy evaluation/ when it is generated."""
    private = private_evidence_relative_path(path, repo_root=repo_root)
    if private is not None:
        destination = private_evidence_destination(private, evaluation_root=Path("evaluation"))
        return destination.relative_to("evaluation")
    candidate = Path(path).expanduser()
    legacy_root = (repo_root / "evaluation").resolve()
    if not candidate.is_absolute():
        parts = candidate.parts
        if parts and parts[0] == "evaluation":
            candidate = repo_root / candidate
        else:
            return None
    try:
        relative = candidate.resolve(strict=False).relative_to(legacy_root)
    except ValueError:
        return None
    pure = PurePosixPath(relative.as_posix())
    if any(pure == prefix or prefix in pure.parents for prefix in GENERATED_EVALUATION_PREFIXES):
        return Path(relative)
    return None


def resolve_artifact_path(
    value: Path | str,
    *,
    paths: AppPaths,
    repo_root: Path,
) -> Path:
    """Resolve portable and legacy generated-artifact references centrally."""
    candidate = Path(value).expanduser()
    relative = generated_relative_path(candidate, repo_root=repo_root)
    if relative is not None:
        relocated = paths.evaluation / relative
        legacy = candidate if candidate.is_absolute() else repo_root / candidate
        # Prefer the relocated object, but permit pre-migration reads.
        if relocated.exists() or not legacy.exists():
            return relocated.resolve(strict=False)
        return legacy.resolve(strict=False)
    if not candidate.is_absolute():
        if candidate.parts and candidate.parts[0] in {"evaluation", "docs"}:
            return (repo_root / candidate).resolve(strict=False)
        # New persisted references are relative to the configured evaluation root.
        return (paths.evaluation / candidate).resolve(strict=False)
    return candidate.resolve(strict=False)


def portable_artifact_path(path: Path, *, paths: AppPaths) -> str:
    """Persist a path relative to evaluation/ when possible."""
    resolved = path.expanduser().resolve(strict=False)
    try:
        return resolved.relative_to(paths.evaluation.resolve(strict=False)).as_posix()
    except ValueError:
        return str(resolved)


def resolve_database_artifact_path(
    value: Path | str,
    *,
    database_path: Path,
    repo_root: Path | None = None,
) -> Path:
    from pastor_transcript_extractor.config import build_paths

    return resolve_artifact_path(
        value,
        paths=build_paths(database_path.expanduser().resolve().parent),
        repo_root=(repo_root or Path.cwd()).expanduser().resolve(),
    )


def portable_database_artifact_path(path: Path, *, database_path: Path) -> str:
    from pastor_transcript_extractor.config import build_paths

    return portable_artifact_path(
        path,
        paths=build_paths(database_path.expanduser().resolve().parent),
    )


def runtime_default(
    explicit: Path | None,
    *,
    paths: AppPaths,
    relative: str,
) -> Path:
    """Honor an explicit CLI path; otherwise use the configured evaluation tree."""
    return explicit.expanduser().resolve() if explicit is not None else paths.evaluation / relative


def runtime_option(
    value: Path | None,
    *,
    paths: AppPaths,
    relative: str,
    repo_root: Path | None = None,
) -> Path:
    """Translate a legacy generated CLI default while preserving real overrides."""
    evaluation_root = evaluation_root_for(paths)
    if value is None:
        return evaluation_root / relative
    candidate = value.expanduser()
    repository = (repo_root or Path.cwd()).expanduser().resolve()
    legacy = repository / "evaluation" / relative
    if candidate == Path("evaluation") / relative:
        return evaluation_root / relative
    if candidate.resolve(strict=False) == legacy.resolve(strict=False):
        return evaluation_root / relative
    return candidate.resolve(strict=False)
