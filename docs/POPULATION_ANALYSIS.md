# Deterministic Scripture population analysis

Iteration 2 is an analysis of the existing descriptive analysis. It freezes the exact
current profile-analysis runs in a population snapshot and evaluates whether the current
Scripture features are sufficiently populated, distinct, and stable to be considered for
later pastor comparison. It does not alter the profile feature schema or perform
similarity, ranking, fit assessment, or clustering.

## Commands

Build or idempotently reuse a snapshot from current active/provisional profiles with at
least three analyzed sermons:

```bash
pte analysis population-build \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Inspect the latest or a specific immutable snapshot:

```bash
pte analysis population-show \
  --base-dir /Users/briancummings/Documents/PastorSearchData

pte analysis population-show --snapshot-id SNAPSHOT_ID --json \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

`--bootstrap-samples` defaults to 200. Sampling is deterministically seeded from the
population analyzer version, profile ID, and exact profile-analysis run ID. Increasing
the sample count intentionally produces a different snapshot because it changes the
diagnostic policy.

## Immutable inputs and provenance

`population_analysis_snapshots` stores the analyzer version, required
`profile-scripture-usage@4` provenance, feature schema, eligibility policy, exact input
fingerprint, and complete JSON report. `population_analysis_snapshot_inputs` links every
included profile to its exact immutable profile-analysis run.

Only exact-current profile aggregates identified by the readiness layer participate.
The snapshot fingerprint includes the ordered profile/run pairs, analyzer versions,
feature schema, and policy. An unchanged invocation reuses the prior snapshot. A changed
profile membership, sermon analysis, profile aggregate, eligibility threshold, bootstrap
policy, or population analyzer version produces a new snapshot without mutating history.

## Diagnostics

For every deterministic Scripture feature except analysis coverage—which remains a
readiness diagnostic—the report records:

- observed and missing values;
- zero inflation;
- minimum, quartiles, median, mean, maximum, standard deviation, and median absolute
  deviation;
- robust profile outliers when at least eight values are observed;
- scale relative to the median feature standard deviation;
- high pairwise Pearson correlations (`|r| >= 0.90`, with at least ten shared
  profiles) as possible redundancy;
- correlation with sermon count;
- leave-one-sermon-out sensitivity;
- deterministic profile-level bootstrap intervals;
- between-profile variance and an explicitly labeled leave-one-out estimate of
  within-profile variance;
- early-versus-late sermon-half sensitivity when at least four dated sermons exist;
- leave-one-source-out sensitivity for profiles represented by multiple sources; and
- aggregate stability at minimum corpus depths of 3, 5, 8, and 10 sermons.

The report also reconstructs each feature from the profile's exact contributing sermon
measurements and Scripture evidence. `recomputation_parity_max_absolute_delta` exposes
disagreement between that reconstruction and the persisted profile vector. This is a
computational consistency check, not human validation.

Leave-one-out and bootstrap calculations are in-memory counterfactuals. They do not
create synthetic sermon or profile-analysis runs.

## Interpretation

Population analyzer `scripture-population-diagnostics@2` also records the reviewed
`benchmark-feature-schema@2` roles. It distinguishes strong correlations (`|r| >= 0.75`)
from high correlations (`|r| >= 0.90`). Outlier detection is suppressed for bounded or
zero-inflated measurements; other features use a conservative modified-Z/MAD rule.
Metadata coverage explicitly shows when date-split or multi-source diagnostics cannot be
interpreted.

Leave-one-out sensitivity is normalized by the feature's population interquartile range,
with standard deviation or range used only when the IQR is unavailable:

- `high`: median profile maximum change is no more than 0.25 population IQR;
- `moderate`: greater than 0.25 and no more than 0.75;
- `low`: greater than 0.75; and
- `not_evaluable`: the population has no usable scale or the feature is too sparse.

Snapshot `@1` recommendations were deterministic review prompts rather than schema
mutations. Snapshot `@2` adds reviewed-role outcomes:

- `retain`;
- `retain_core_minimum_5_sermons`;
- `retain_with_minimum_8_sermons`;
- `diagnostic_only_reviewed`;
- `use_only_via_canonical_composition`;
- `review_redundancy`;
- `require_larger_corpus_or_transform`;
- `move_to_diagnostic_only_or_transform`;
- `move_to_diagnostic_only_or_collect_more_profiles`; or
- `investigate_detector_or_require_larger_corpus`.

Compositional features naturally correlate, low-reference sermons can make canonical
shares unstable, source sensitivity requires genuinely multi-source profiles, and date
splits do not distinguish real pastoral change from topical or series selection. The
bootstrap measures uncertainty in the collected sermon sample, not error in Scripture
detection. Manual transcript inspection is not represented as completed by this report.

## Next decision

Review the population report and manually inspect surprising outliers or detector-driven
missingness. Only then should a reviewed comparison feature schema be frozen for
reference-pastor similarity. Description remains separate from similarity, and both
remain separate from an eventual church-fit rubric.
