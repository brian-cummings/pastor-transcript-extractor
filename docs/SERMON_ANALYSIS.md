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

Scripture extraction deliberately favors precision. Version 1 recognizes
explicit numeric references such as `John 3:16`, `Romans 8:1-4`, and common
book abbreviations. It does not infer allusions, themes, quoted-but-unnamed
passages, or spoken-number forms. Every recognized reference is persisted as a
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

## Natural next increment

The next small capability should add deterministic Scripture-usage structure:
reference density per thousand words, Old/New Testament distribution, and
reference sequence/repetition across sermon time. It can reuse the existing
run/measurement/evidence pattern without adding subjective interpretation;
quoted-passage matching can follow later once it has an explicit Bible-text
source and translation provenance.
