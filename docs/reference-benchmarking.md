# Reference panels and benchmark snapshots

Reference panels are reviewed analytical selections of speaker profiles. They are not
attributes of pastors, sources, videos, or analyses: those records continue through the
ordinary acquisition, identity, sermon-analysis, and profile-analysis pipelines. A
profile becomes a reference only when a reviewer appends an `attach` membership event;
a later `detach` event removes it from effective membership without deleting history.
Profiles may belong to more than one panel, and redirects are resolved when a snapshot
is built.

Snapshot analyzer `reference-panel-snapshot@3` accepts immutable
`profile-scripture-usage@4` runs and materializes reviewed
`benchmark-feature-schema@2`. The comparison representation contains four core features
usable for exploratory comparison at five sermons, eight depth-sensitive features that
must abstain below eight sermons, and a smoothed centered-log-ratio representation of the
ten canonical divisions. The canonical composition is one feature family rather than ten
independently weighted claims.

Coverage, zero-reference exceptions, saturated alignment-presence, redundant raw
breadth/concentration measurements, raw canonical shares, corpus size, missing-analysis
counts, and structural coverage remain diagnostics outside the vector. Semantic style,
theology, politics, Christian nationalism, and embeddings remain explicitly excluded.
The complete role assignment and minimum-depth policy are persisted with every snapshot.

Eligibility policy `scripture-reference-eligibility@2` requires, by default, at least
five analyzed sermons, 10,000 sermon words, 80% analysis coverage, the four core
features, and the canonical composition. Depth-sensitive values remain present for
traceability but later comparison must abstain from using them below eight sermons.
Other comparison-eligible values may remain
missing and carry explicit missingness. CLI build flags can adjust the numeric thresholds; the complete policy is
persisted. Every member remains visible. Missing analysis, insufficient corpus or
coverage, incompatible schema, and missing features are recorded as exclusion reasons,
and missing feature values remain JSON `null` rather than becoming zero.

Depth-sensitive panel statistics use only reference profiles with at least eight analyzed
sermons. Each immutable snapshot stores its panel, effective reviewed and redirect-resolved
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

pte benchmark compare \
  --profile-id 59 \
  --panel prominent-pastors-v1

pte benchmark compare \
  --profile-id 59 \
  --panel prominent-pastors-v1 \
  --snapshot-id 3 \
  --json
```

## Nearest-reference comparison

Comparison analyzer `scripture-reference-comparison@1` compares the candidate's current
immutable `profile-scripture-usage@4` run with an exact panel snapshot. It is descriptive
Scripture-use similarity only: the nearest reference is not necessarily close, distances
are not probabilities, and the result is neither overall preaching similarity nor church
fit.

Candidates with five through seven analyzed sermons receive a core comparison. Candidates
with at least eight receive a full comparison, and references lacking eight sermons are
excluded from that full ranking. An ineligible candidate, an empty compatible panel, or
insufficient normalization evidence produces an explicit, persisted abstention.

`robust-panel-mad-family-balanced@1` divides each raw feature difference by `1.4826 * MAD`
from the frozen panel. When MAD is zero but the observed range is nonzero, the range is the
documented fallback; a constant feature contributes nothing. Standardized feature
differences are capped at 5 so one extreme cannot dominate. Distances are root-mean-square
within each of three feature families and then root-mean-square with equal weight across
the available families:

- core Scripture measurements,
- canonical composition,
- depth-sensitive structure for full comparisons.

This makes the ten-coordinate canonical composition one family rather than ten votes.
The durable result preserves raw candidate/reference values, raw differences,
normalization scales and methods, standardized differences, family distances, exclusions,
coverage diagnostics, nearest/second-nearest distance separation, the exact candidate
analysis run, and exact panel snapshot. Ranking separation is a descriptive margin, not a
confidence estimate.

Comparison runs are immutable and fingerprinted by resolved candidate identity, exact
candidate analysis run, exact panel snapshot, analyzer version, feature schema, result
schema, and normalization policy. An unchanged command reuses the prior run. A changed
candidate analysis or rebuilt panel snapshot creates a new run naturally.

Clustering, learned weights, semantic style, uncertainty calibration, and church-fit
assessment remain outside this slice. The next validation step is to populate a reviewed
panel and compare known pastors whose similarities and differences can be inspected by a
human reviewer before treating the distance space as meaningful.
