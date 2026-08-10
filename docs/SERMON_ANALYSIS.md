# Sermon Analysis: First Increment

The analysis stage consumes the latest persisted extraction result and its
already-identified sermon window. It does not detect sermons, change their
boundaries, or perform speaker identity work.

The `sermon-basics` analyzer currently records these deterministic sermon-level
measurements:

- transcript word count;
- identified sermon-window duration;
- explicit Scripture reference mention count;
- distinct canonical passages and Bible books; and
- the sorted set of referenced books.

Scripture extraction deliberately favors precision. Version 2 recognizes
explicit numeric references such as `John 3:16`, `Romans 8:1-4`, and common
book abbreviations. It does not infer allusions, themes, quoted-but-unnamed
passages, or spoken-number forms. Each match is explicitly classified as a
high-confidence `explicit` reference; contextual-reference detection remains a
separate future class. Every recognized reference is persisted as a
separate evidence row containing the exact transcript match, canonical
reference, source segment index, character offsets, and timestamps when the
source segment supplies them.

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
total words, analyzed-sermon date range, explicit references per thousand words,
Old/New Testament distribution, top books, chapters repeated across sermons,
and reference placement by sermon quarter. Placement uses the source segment's
start timestamp and reports that precision in its diagnostics.

Zero-reference sermons are surfaced as a detection diagnostic. They are not
silently interpreted as evidence of low Scripture usage. The persisted
detection scope states that only explicit numeric references are currently
recognized and that contextual detection is not implemented.

`speaker_profile_analysis_runs` is an immutable materialized derivation. Its
fingerprint includes the canonical resolved profile, effective observation
membership, exact input sermon-analysis run IDs, schema version, and profile
analyzer version. `speaker_profile_analysis_inputs` preserves those exact run
links; derived aggregate values are stored separately in
`speaker_profile_analysis_measurements`. Unchanged inputs reuse the existing
run. Membership changes, newer sermon analyses, or a profile-analyzer version
change create a new run.

## Structural Scripture profile (Iteration 3)

Version 2 of `profile-scripture-usage` adds deterministic structural features
without changing the evidence path. It consumes the same immutable sermon
analysis runs and their explicit-reference evidence, and persists these
additional profile measurements:

- **Breadth:** distinct books and distinct book-chapters per ten explicit
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
- **Multi-verse use:** the share of explicit references whose stated range
  spans more than one verse.
- **Cross-sermon anchors:** the largest fraction of analyzed sermons citing the
  same book-chapter, requiring that chapter to occur in at least two sermons.
- **Across-sermon consistency:** mean pairwise cosine similarity of book-count
  distributions among reference-bearing sermons, and `1 / (1 + CV)` for
  per-sermon explicit-reference density.

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
sermons, explicit mention count, usable book-distribution pairs, and word-count
coverage. Because detection remains explicit-numeric-only, breadth,
concentration, emphasis, and consistency describe detected citations—not all
Scripture use. Sparse detection must be reviewed before interpreting those
features.

## Natural next increment

The next natural iteration should improve deterministic detection coverage
before adding semantic judgments: recognize syntax such as “the third chapter
of John” and “verse sixteen,” retain `explicit` versus `contextual` detection
classes, and validate precision/recall against a small reviewed transcript set.
Quoted-passage matching can follow once it has an explicit Bible-text source
and translation provenance. Structural features should then expose separate
explicit-only and expanded-coverage variants rather than silently changing
their meaning.
