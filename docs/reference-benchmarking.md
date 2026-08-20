# Reference panels and benchmark snapshots

Reference panels are reviewed analytical selections of speaker profiles. They are not
attributes of pastors, sources, videos, or analyses: those records continue through the
ordinary acquisition, identity, sermon-analysis, and profile-analysis pipelines. A
profile becomes a reference only when a reviewer appends an `attach` membership event;
a later `detach` event removes it from effective membership without deleting history.
Profiles may belong to more than one panel, and redirects are resolved when a snapshot
is built.

The first snapshot format accepts only immutable `profile-scripture-usage@4` runs and
the deterministic profile feature-vector schema `@2`. Its comparison vector contains
the ordered Scripture-usage features except `analysis_coverage_fraction`. Coverage,
corpus size, missing-analysis counts, and structural coverage remain diagnostics outside
the vector. Semantic style coverage, theology, politics, Christian nationalism, and
embeddings are explicitly excluded. These assignments are recorded as
`benchmark-feature-families@1` so later methods can change feature families deliberately.

Eligibility policy `scripture-reference-eligibility@1` requires, by default, at least
three analyzed sermons, 10,000 sermon words, 80% analysis coverage, and a small stable
required subset (zero-reference fraction, reference density, book breadth, book
concentration, and Old Testament share). Other comparison-eligible values may remain
missing and carry explicit missingness. CLI build flags can adjust the numeric thresholds; the complete policy is
persisted. Every member remains visible. Missing analysis, insufficient corpus or
coverage, incompatible schema, and missing features are recorded as exclusion reasons,
and missing feature values remain JSON `null` rather than becoming zero.

Each immutable snapshot stores its panel, effective reviewed and redirect-resolved
membership, frozen profile display labels, exact profile-analysis run IDs, analyzer and
schema versions, ordered feature names, raw values, diagnostics, policy, feature-family
assignments, and per-feature eligible count, missing count, median, median absolute
deviation, minimum, and maximum. The profile-analysis run retains the exact sermon-run
inputs. Snapshot rows and members are committed in one SQLite transaction.

The input fingerprint covers panel metadata, reviewed and resolved membership, frozen
labels, selected run IDs, feature schema and families, coverage/eligibility policy,
panel statistics, and snapshot analyzer version. An unchanged build reuses its snapshot;
any covered input change creates a new one.

```bash
pte benchmark create \
  --key prominent-pastors-v1 \
  --name "Prominent pastors reference panel" \
  --description "Reviewed named profiles used as comparison anchors"

pte benchmark add-profile prominent-pastors-v1 \
  --profile-id 142 --reviewer "Brian Cummings" \
  --reason "Selected as a prominent comparison reference"

pte benchmark remove-profile prominent-pastors-v1 \
  --profile-id 142 --reviewer "Brian Cummings" \
  --reason "Removed from the reference panel"

pte benchmark list
pte benchmark show prominent-pastors-v1
pte benchmark build prominent-pastors-v1
pte benchmark show-snapshot prominent-pastors-v1
pte benchmark show-snapshot prominent-pastors-v1 --json
```

The JSON feature matrix is ready for a later transparent nearest-reference comparison:
rows retain stable profile identity, label, run provenance, ordered raw values, explicit
missingness, and separate coverage. The natural next increment is
`pte benchmark compare --profile-id PROFILE_ID --panel PANEL_KEY`, using raw differences
or a documented robust standardization based on the persisted median and MAD. Clustering,
learned weights, resampling, and semantic features are intentionally not part of this
slice.
