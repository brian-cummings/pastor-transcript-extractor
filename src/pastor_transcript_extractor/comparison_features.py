from __future__ import annotations

import math
from typing import Mapping

from pastor_transcript_extractor.profile_analysis import CANONICAL_DIVISIONS


BENCHMARK_FEATURE_SCHEMA_VERSION = "benchmark-feature-schema@3"
FEATURE_ROLE_POLICY_VERSION = "scripture-feature-roles@2"
CANONICAL_TRANSFORM_VERSION = "canonical-division-clr@1"
CANONICAL_SMOOTHING_MENTIONS = 0.5

# Experimental sample measurements; depth eligibility is not validation.
CORE_FEATURE_NAMES = (
    "references_per_1000_words",
    "scripture_text_engagement_fraction",
    "multi_verse_reference_ratio",
    "cross_sermon_anchor_coverage",
)

# Additional experimental measurements; the eight-sermon policy is unvalidated.
DEPTH_SENSITIVE_FEATURE_NAMES = (
    "chapter_breadth_per_10_references",
    "effective_book_count",
    "aligned_passage_concentration_hhi",
    "sustained_chapter_reference_ratio",
    "mean_pairwise_book_distribution_cosine",
    "reference_density_consistency",
)

CANONICAL_COMPOSITION_FEATURE_NAMES = tuple(
    f"canonical_division_clr_{division}" for division in CANONICAL_DIVISIONS
)

COMPARISON_FEATURE_NAMES = (
    *CORE_FEATURE_NAMES,
    *DEPTH_SENSITIVE_FEATURE_NAMES,
    *CANONICAL_COMPOSITION_FEATURE_NAMES,
)

RAW_CANONICAL_SHARE_FEATURE_NAMES = tuple(
    f"{division}_share" for division in CANONICAL_DIVISIONS
)

DIAGNOSTIC_ONLY_FEATURE_NAMES = (
    "anchored_text_alignment_fraction",
    "mean_scripture_text_alignment_score",
    "analysis_coverage_fraction",
    "zero_detected_reference_sermon_fraction",
    "sermons_with_text_alignment_fraction",
    "book_breadth_per_10_references",
    "book_concentration_hhi",
    "old_testament_share",
    *RAW_CANONICAL_SHARE_FEATURE_NAMES,
)

FEATURE_ROLE_ASSIGNMENTS = {
    "version": FEATURE_ROLE_POLICY_VERSION,
    "schema_version": BENCHMARK_FEATURE_SCHEMA_VERSION,
    "validation_status": "unvalidated",
    "certified_comparison_features": [],
    "depth_thresholds_are_exploratory": True,
    "measurement_labels": {
        "scripture_text_engagement_fraction": "Detected Bible-text span fraction",
    },
    "minimum_sermons": {
        "core": 5,
        "canonical_composition": 5,
        "depth_sensitive": 8,
    },
    "core": list(CORE_FEATURE_NAMES),
    "depth_sensitive": list(DEPTH_SENSITIVE_FEATURE_NAMES),
    "canonical_composition": {
        "feature_names": list(CANONICAL_COMPOSITION_FEATURE_NAMES),
        "source_divisions": list(CANONICAL_DIVISIONS),
        "transform": CANONICAL_TRANSFORM_VERSION,
        "additive_smoothing_mentions": CANONICAL_SMOOTHING_MENTIONS,
        "distance_semantics": "one_compositional_family_not_ten_independent_weights",
    },
    "diagnostic_only": list(DIAGNOSTIC_ONLY_FEATURE_NAMES),
    "excluded_future_families": [
        "semantic-style-run-coverage",
        "theology",
        "politics",
        "christian-nationalism",
        "embeddings",
    ],
}


def canonical_division_clr(
    division_emphasis: Mapping[str, object],
) -> dict[str, float] | None:
    """Return a smoothed centered-log-ratio composition from mention counts."""
    counts: list[float] = []
    for division in CANONICAL_DIVISIONS:
        item = division_emphasis.get(division)
        if not isinstance(item, Mapping):
            return None
        mentions = item.get("mentions")
        if not isinstance(mentions, (int, float)) or isinstance(mentions, bool):
            return None
        if mentions < 0:
            return None
        counts.append(float(mentions) + CANONICAL_SMOOTHING_MENTIONS)
    log_counts = [math.log(value) for value in counts]
    center = sum(log_counts) / len(log_counts)
    return {
        feature_name: round(value - center, 6)
        for feature_name, value in zip(
            CANONICAL_COMPOSITION_FEATURE_NAMES, log_counts, strict=True
        )
    }
