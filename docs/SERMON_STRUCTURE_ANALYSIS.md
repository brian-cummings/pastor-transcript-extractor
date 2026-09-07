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

The next increment should add readiness/backfill reporting and a population diagnostic
snapshot for these preliminary features. Only stable, nonredundant measurements should
then feed exploratory PCA or factor analysis. Semantic style and theology remain separate
evidence-backed concerns.
