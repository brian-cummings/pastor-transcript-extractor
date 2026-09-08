# Deterministic sermon structure and stylometry

`sermon-structure@2` is a descriptive analysis of already identified sermon content. It
does not assign preaching styles, topics, theological positions, quality, or church fit.
It consumes the current immutable `sermon-basics@4` run rather than detecting Scripture
again.

## Measurements

The initial transcript-stylometry family contains transcript tokens per minute, rolling 100-word
type-token ratio, first-person singular, first-person plural, and second-person token
rates, and question-mark-bearing segment rate. Token rate is not speaking rate because
overlapping caption text can inflate it. These names are intentionally literal:
pronoun counts do not establish pastoral warmth, and question marks do not establish
rhetorical skill.

The initial organization family divides the sermon into eight equal-token regions after
removing a small versioned stopword list. It records mean and minimum cosine similarity
between adjacent regions and opening-to-closing cosine. These are lexical continuity and
recurrence measurements, not inferred topics or narrative arcs.

The Scripture-organization family derives from existing accepted reference evidence. It
records the dominant book-chapter's share of chapter-specific references, its
first-to-last positional span, and returns to it after another chapter. The trace metric
retains the exact supporting Scripture evidence keys and Scripture analysis run.

Every feature has a persisted operational explanation. Missing evidence remains `null`;
it is not converted to zero. Some features are source-sensitive: ASR punctuation affects
question marks, transcript segmentation affects timing precision, and lexical measures
can reflect transcription conventions. They must undergo the same population
distribution, within-pastor stability, source-dependence, and redundancy analysis as the
Scripture features before entering comparison or dimensional reduction.

## Profile aggregation and provenance

`profile-sermon-structure@2` stores the mean, median, population standard deviation, and
observed sermon count for every feature, plus explicit missing-sermon IDs. Its preliminary
feature vector contains feature means only and is not automatically included in benchmark
distance, PCA, ranking, or clustering.

Sermon fingerprints cover canonical identified transcript content, the exact current
Scripture analysis run and fingerprint, analyzer/schema versions, tokenizer version, and
lexical-window version. Profile fingerprints cover resolved profile identity, effective
membership, exact sermon-structure run IDs, and analyzer/schema versions. Unchanged runs
are reused; source, Scripture evidence, membership, or analyzer changes create new runs.

## CLI

Run current deterministic Scripture analysis first, then structure analysis:

```bash
pte analysis run --profile-id 59 --base-dir /path/to/data
pte analysis structure-run --profile-id 59 --base-dir /path/to/data
pte analysis structure-show --profile-id 59 --base-dir /path/to/data
```

Inspect one sermon with its operational definitions and provenance:

```bash
pte analysis structure-show --youtube-video-id VIDEO_ID --base-dir /path/to/data
```

Only stable, nonredundant measurements may later feed exploratory PCA or factor analysis.
Semantic style and theology remain separate evidence-backed concerns.

## Corpus readiness and population diagnostics

Structure readiness independently reports current, missing, stale, and blocked sermon
runs plus current, missing, or stale profile aggregates. A sermon is blocked when its
identified transcript or exact current `sermon-basics@4` prerequisite is unavailable.
Dry-run backfill does not write analysis artifacts. Execution handles each unique sermon
independently, records failures without discarding completed runs, and then refreshes
profile summaries:

```bash
pte analysis structure-readiness --base-dir /path/to/data
pte analysis structure-backfill --minimum-sermons 3 --dry-run --base-dir /path/to/data
pte analysis structure-backfill --minimum-sermons 3 --base-dir /path/to/data
```

`structure-population-diagnostics@1` freezes exact current
`profile-sermon-structure@2` runs in the existing immutable population-snapshot model.
For every feature it reports distribution and missingness, median maximum
leave-one-sermon-out change in population-IQR units, between-profile and mean
within-profile variance, their ratio, and correlation with sermon count. Pairwise
correlations with absolute Pearson correlation at least 0.75 are listed. Transcript token
density and question-mark segment rate are always marked source-sensitive and
diagnostic-only. Pairwise correlations require at least ten profiles. The stability labels
use median maximum leave-one-out change of at most 0.15 population-IQR units for `high`
and at most 0.35 for `moderate`; these thresholds are persisted policy, not learned truth.
Date and multi-source coverage are reported so unavailable selection-bias checks remain
visible.

```bash
pte analysis structure-population-build \
  --minimum-sermons 3 --base-dir /path/to/data
pte analysis structure-population-show --base-dir /path/to/data
pte analysis structure-population-show --json --base-dir /path/to/data
```

Recommendations are advisory. This increment does not modify the benchmark feature
schema or perform PCA, ranking, or clustering. The next step is to run the backfill and
inspect the frozen population report. Features should advance only if they distinguish
pastors more than sermons within a pastor, remain stable when one sermon is removed, have
acceptable missingness, and are not redundant.
