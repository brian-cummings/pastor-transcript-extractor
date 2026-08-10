# Sermon Analysis: First Increment

The analysis stage consumes the latest persisted extraction result and its
already-identified sermon window. It does not detect sermons, change their
boundaries, or perform speaker identity work.

The `sermon-basics` analyzer currently records these deterministic sermon-level
measurements:

- transcript word count;
- identified sermon-window duration;
- total, explicit, and contextual Scripture reference mention counts;
- distinct canonical passages and Bible books; and
- the sorted set of referenced books.

Scripture extraction deliberately favors precision. Version 3 preserves
high-confidence `explicit` numeric references such as `John 3:16` and
`Romans 8:1-4`, while adding a separate `contextual` class. Every recognized
reference is persisted as a
separate evidence row containing the exact transcript match, canonical
reference, source segment index, character offsets, and timestamps when the
source segment supplies them.

Supported contextual forms are:

- book plus chapter in digits or number words (`Romans 8`, `John chapter three`);
- ordinal chapter before the book (`the third chapter of John`);
- spoken verse or verse range attached to that form (`Daniel chapter seven,
  verses thirteen through fourteen`);
- strongly cued book-only references (`the book of Romans`, `open your Bible to
  Isaiah`, `read from Psalms`, `our passage is in Ephesians`); and
- numeric or spoken `verse`/`verses` continuations resolved from a book-chapter
  anchor earlier in the same segment or the immediately preceding segment.

Grammar-bound book, chapter, and verse forms are recorded with high confidence.
Immediate continuation resolution is medium confidence and records the source
anchor's canonical reference and segment. Contextual matching never replaces or
duplicates an overlapping explicit match.

Important unsupported cases include colloquial number pairs such as “John three
sixteen,” ordinal inference such as “the next verse,” uncued bare book names,
allusions, and quotations without a named reference. Invalid chapter numbers,
unanchored verse language, and ambiguous ordinary uses of names such as John,
Mark, Acts, or Romans are rejected.

## Running and inspecting analysis

Analyze one sermon by YouTube id or database video id:

```bash
pte analysis run --youtube-video-id VIDEO_ID --base-dir /path/to/app-data
pte analysis run --video-id DATABASE_ID --base-dir /path/to/app-data
```

Analyze every sermon effectively attached to a canonical speaker profile:

```bash
pte analysis run --profile-id PROFILE_ID --base-dir /path/to/app-data
```

Inspect the latest results with the same scope options:

```bash
pte analysis show --youtube-video-id VIDEO_ID --base-dir /path/to/app-data
pte analysis show --profile-id PROFILE_ID --base-dir /path/to/app-data
```

Profile scope follows effective `profile_observation_events` membership and
resolves retired profiles through profile redirects. This makes reviewed
speaker evidence—not source targeting or a filesystem slug—the aggregation
authority. `--pastor PASTOR_SLUG` remains a compatibility alias, but it first
resolves the pastor through `pastor_speaker_bindings` and then uses the same
profile-membership path. An unbound pastor cannot supply an analysis scope.

## Persistence, idempotency, and versioning

`sermon_analysis_runs` stores run provenance: the video and extraction result,
analyzer key and version, source kind and path, a canonical sermon-content
SHA-256, the idempotency fingerprint, and creation time.
`sermon_analysis_measurements` stores derived values. Source matches live
separately in `sermon_analysis_evidence` so measurements are not confused with
their support.

The input fingerprint combines the video, analyzer key/version, analysis schema
version, and canonical hash of the selected sermon content. A unique SQLite
constraint makes the same analyzer version over unchanged content reuse the
existing complete run. Computation happens before persistence, and each run,
its measurements, and its evidence are inserted in one transaction, so an
interruption cannot leave a visible partial run. Changed sermon content creates
a new run. When analyzer behavior changes, increment the code's default version;
during development it can be exercised explicitly:

```bash
pte analysis run --youtube-video-id VIDEO_ID --analyzer-version 2 \
  --base-dir /path/to/app-data
```

Prior runs remain available in SQLite for provenance rather than being
overwritten.

Runs remain sermon-scoped rather than copying `profile_id` into their identity.
Profile membership is an independently reviewed, reversible relationship, so
the CLI projects existing sermon analyses through current profile membership.
Moving an observation between profiles therefore neither duplicates nor
invalidates the deterministic analysis of its sermon.

## Materialized profile Scripture summaries

After current sermon analysis exists for the profile's attached observations,
materialize and inspect its aggregate Scripture usage:

```bash
pte analysis summarize-profile --profile-id PROFILE_ID --base-dir /path/to/app-data
pte analysis show-profile --profile-id PROFILE_ID --base-dir /path/to/app-data
```

The profile summary records coverage (attached, analyzed, and missing sermons),
total words, analyzed-sermon date range, accepted references per thousand words,
Old/New Testament distribution, top books, chapters repeated across sermons,
and reference placement by sermon quarter. Placement uses the source segment's
start timestamp and reports that precision in its diagnostics.

Zero-reference sermons are surfaced as a detection diagnostic. They are not
silently interpreted as evidence of low Scripture usage. The persisted
detection scope and method/confidence counts keep explicit and contextual
coverage visible separately.

`speaker_profile_analysis_runs` is an immutable materialized derivation. Its
fingerprint includes the canonical resolved profile, effective observation
membership, exact input sermon-analysis run IDs, schema version, and profile
analyzer version. `speaker_profile_analysis_inputs` preserves those exact run
links; derived aggregate values are stored separately in
`speaker_profile_analysis_measurements`. Unchanged inputs reuse the existing
run. Membership changes, newer sermon analyses, or a profile-analyzer version
change create a new run.

## Structural Scripture profile (Iteration 3)

Version 2 of `profile-scripture-usage` introduced deterministic structural
features without changing the evidence path. Version 3 regenerates those same
features from accepted explicit and contextual evidence; it does not create a
parallel metric family. It consumes immutable sermon analysis runs and persists
these
additional profile measurements:

- **Breadth:** distinct books and distinct book-chapters per ten accepted
  reference mentions.
- **Concentration:** book-level Herfindahl-Hirschman concentration and its
  inverse, the effective book count.
- **Canonical emphasis:** continuous mention shares for Pentateuch, historical
  books, wisdom/poetry, major prophets, minor prophets, Gospels, Acts, Pauline
  epistles, general epistles, and Revelation, plus the existing OT/NT shares.
- **Sustained versus dispersed use:** the share of mentions belonging to a
  book-chapter cited at least twice within the same sermon. This is a citation
  clustering measurement, not a claim that the preacher performed sustained
  exposition.
- **Multi-verse use:** the share of accepted references whose stated range
  spans more than one verse.
- **Cross-sermon anchors:** the largest fraction of analyzed sermons citing the
  same book-chapter, requiring that chapter to occur in at least two sermons.
- **Across-sermon consistency:** mean pairwise cosine similarity of book-count
  distributions among reference-bearing sermons, and `1 / (1 + CV)` for
  per-sermon accepted-reference density.

`sermon_scripture_structure` records the supporting values for each contributing
sermon: its exact sermon-analysis run, word and reference counts, density,
distinct books/chapters, top-chapter share, and book/chapter count maps.
Repeated anchors include their contributing video and sermon-analysis run IDs.
`structural_feature_explanations` persists the formulas beside the measurements.

### Deterministic feature vector

`deterministic_profile_feature_vector` stores a versioned, fixed-order list of
continuous values and the same values keyed by name. It includes coverage,
reference density, breadth, concentration, canonical division shares,
sustained/multi-verse ratios, anchor coverage, and consistency. This is a stable
representation for later comparison or clustering, but this iteration performs
neither.

Undefined measurements are stored as `null`, never silently coerced to a
preaching characteristic. Examples include concentration with no detected
references and pairwise consistency with fewer than two reference-bearing
sermons. `structural_coverage_diagnostics` reports analyzed and zero-reference
sermons, total/explicit/contextual mention counts, usable book-distribution
pairs, and word-count coverage. Breadth, concentration, emphasis, and
consistency still describe detected references—not all Scripture use. Sparse
detection must be reviewed before interpreting those features.

## Reviewed detector evaluation (Iteration 4)

The frozen fixture at
`evaluation/scripture-references/contextual-v1.json` contains 25 reviewed cases:
explicit citations, contextual chapter/verse forms, cued book-only references,
immediate continuations, ambiguous biblical language, and negative controls.
Run it with:

```bash
pte analysis evaluate-scripture-detector \
  evaluation/scripture-references/contextual-v1.json
```

Current fixture results are 16 true positives, 0 false positives, and 2 false
negatives: **1.000 precision** and **0.889 recall** overall. Explicit detection
remains **1.000 precision / 1.000 recall**. Contextual detection is **1.000
precision / 0.875 recall**. All ten negative-control cases pass. The two visible
misses are the intentionally unsupported “John three sixteen” form and “the
next verse” ordinal inference. This is a small behavior-locking corpus, not a
claim of population-level accuracy; it should grow through reviewed production
misses before broader recall claims are made.

The sermon analyzer version is now `3`; its fingerprint therefore creates new
runs over unchanged transcripts while retaining version-2 explicit-only runs.
The profile analyzer version is also `3` and selects exact version-3 sermon
inputs. Profile reference totals, zero-reference coverage, canonical emphasis,
and the existing structural vector are regenerated from the union of accepted
explicit and contextual evidence. Separate explicit/contextual counts and
method/confidence distributions show exactly how much coverage expansion came
from the new detector. No production profile-coverage delta is claimed until
the profile corpus is rerun and inspected.

## Natural next increment

The next natural iteration is deterministic quoted-passage alignment against a
versioned Bible-text source with translation provenance. It should nominate
unnamed quotations conservatively, retain text similarity and source spans as
evidence, and expand the reviewed corpus before contributing to structural
features. Semantic pastor-style, theology, politics, embeddings, and clustering
remain out of scope until detector coverage is better characterized.
