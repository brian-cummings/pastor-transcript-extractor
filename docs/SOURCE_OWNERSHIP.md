# Source Ownership

PTE separates publishing ownership from pastor search and recognition context.

The durable publishing chain is:

```text
Organization -> Source -> Video -> Speaker Observation
                                         |
                              reviewed attachment
                                         v
                              Speaker Profile <-> Pastor
```

A pastor's relationship with an organization is recorded independently as a
temporal affiliation. A source or video does not become owned by a pastor when
that pastor is selected as a processing target.

## Current migration boundary

- `sources.organization_id` is the current publisher association and may be
  null when the publisher is unknown.
- `source_organization_events` preserves append-only attachment and correction
  evidence.
- Church-database records create organizations, exact external snapshots,
  source import links, and unreviewed affiliation claims.
- Imported pastor names do not create pastors, speaker profiles, affiliations,
  or speaker-profile membership.
- `source_target_policies` and `video_target_contexts` represent pastor query
  and compatibility context.
- Legacy `sources.pastor_id` and `videos.pastor_id` remain temporarily as the
  primary-target projection required by the production extraction pipeline.
- Every video has an immutable artifact namespace. Existing videos retain
  `pastors/<legacy-slug>/videos/<youtube-id>`; targetless videos use
  `artifacts/videos/<youtube-id>`.
- Existing artifact files and `proposed.json` are never moved or rewritten by
  the ownership migration.

Discovery, caption fetching, transcription, extraction, reclassification, media
registration, and archival can operate without a target pastor. For targetless
videos, content artifacts remain video-scoped, target-relative guest-speaker
flags are left unset, and shadow identity assessment is skipped until a target
pastor is explicitly selected. Pastor review remains a downstream projection
through explicit video target contexts.

## Manual workflows

```bash
pte organization add sample-church "Sample Church" --type church

pte source add \
  'https://www.youtube.com/@samplechurch' \
  --organization sample-church

pte source add \
  'https://www.youtube.com/@conference' \
  --organization sample-conference \
  --target-pastor pastor-a

pte source add 'https://www.youtube.com/@unknownpublisher'
pte source set-organization 12 sample-church
pte source clear-organization 12

pte pastor affiliate pastor-a sample-church \
  --role "Senior Pastor" \
  --from 2024-01-01 \
  --status current

pte organization claims --organization sample-church
pte pastor affiliate-claim pastor-a 27 \
  --reviewer "Brian Cummings" \
  --reason "Verified against the external church record"
```

The legacy command remains supported:

```bash
pte add 'https://www.youtube.com/@samplechurch' --pastor pastor-a
```

Here `--pastor` creates a target policy; it does not identify the source's
publisher. Prefer `pte source add --target-pastor` in new scripts.

Publisher and target review projections are intentionally separate:

```bash
pte organization review sample-church
pte review pastor-a
```

The organization review selects videos through source publishing membership.
The pastor review selects videos through explicit target contexts. Reviewed
speaker-profile attachment can identify Pastor A in a video published by
Organization B without changing either source ownership or video identity.

## Church database import

An imported external church identity is reconciled through
`(provider, external_entity_key)`. A YouTube source is reconciled through its
immutable channel key. Each distinct imported fingerprint appends an exact JSON
snapshot.

A changed pastor name appends a new affiliation claim. It does not merge,
rename, or create a person. A changed channel identity is retained as a
snapshot and reported as a conflict requiring manual reconciliation.

Imported claims can only become canonical affiliations through an explicit
`pastor affiliate-claim` review event that names an existing pastor ID/slug.
The claim's name is displayed to the reviewer but is never used as the merge
key. Rejections are also append-only:

```bash
pte organization reject-affiliation-claim 27 \
  --reviewer "Brian Cummings" \
  --reason "External record named a different person"
```

## Production-copy validation

Do not begin with the production database. Make a SQLite backup and validate
the copy:

```bash
PROD_ROOT=/Users/briancummings/Documents/PastorSearchData
VALIDATION_ROOT=/tmp/pte-source-ownership-validation

mkdir -p "$VALIDATION_ROOT"
sqlite3 "$PROD_ROOT/app.db" ".backup '$VALIDATION_ROOT/app.db'"

pte source-ownership migrate \
  --dry-run \
  --base-dir "$VALIDATION_ROOT"

pte source-ownership migrate \
  --base-dir "$VALIDATION_ROOT"

pte source-ownership audit \
  --strict \
  --base-dir "$VALIDATION_ROOT"
```

The migration changes database schema and projections only. It does not invoke
discovery, transcription, extraction, classification, or evaluation.

Focused implementation checks:

```bash
.venv/bin/python -m unittest -q \
  tests.test_source_ownership \
  tests.test_church_database_import \
  tests.test_sources \
  tests.test_identity \
  tests.test_speaker_registry \
  tests.test_media_artifacts \
  tests.test_application

.venv/bin/python -m compileall -q src tests
```

No corpus reclassification or evaluation is required for this migration.
