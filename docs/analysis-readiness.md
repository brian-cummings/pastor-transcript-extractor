# Analysis readiness and deterministic backfill

This iteration makes deterministic Scripture analysis operable across the corpus. It does
not add a new analysis dimension. Eligibility is profile-centric: a sermon is included
when it belongs to the effective membership of an `active` or `provisional` speaker
profile and its latest extraction contains identified sermon content. A profile does not
need a reviewed name or pastor binding.

No schema migration is required. Sermon runs, measurements, and evidence continue to use
`sermon_analysis_runs`, `sermon_analysis_measurements`, and
`sermon_analysis_evidence`; derived profile snapshots continue to use
`speaker_profile_analysis_runs`, their exact input-run links, and profile measurements.
Readiness is calculated from those durable records and current source fingerprints rather
than persisted as mutable status.

## Commands

Inspect readiness without changing the database:

```bash
pte analysis status --all-profiles \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Add `--json` for a machine-readable population snapshot. Preview the exact work list:

```bash
pte analysis backfill --all-attached --dry-run \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Run the deterministic sermon backfill and then refresh eligible profile aggregates:

```bash
pte analysis backfill --all-attached \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Refresh profile aggregates without running sermon analyzers:

```bash
pte analysis refresh-profiles --minimum-sermons 3 \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The large real-corpus backfill is intentionally an operator-run command, not part of the
test suite.

## Current, missing, and stale

A sermon is **current** only when an immutable `sermon-basics@4` run has the exact input
fingerprint calculated from the current identified sermon content, analyzer/schema
version, video identity, and versioned Bible artifact. It is **missing** when no prior
run exists, and **stale** when a prior run exists but none matches that fingerprint.
Unreadable or invalid identified source is reported as blocked while retaining its
missing/stale state.

A profile aggregate is current only when:

- every eligible effective-member sermon has a current run;
- the aggregate's membership fingerprint matches the exact effective observations;
- its input run IDs match the exact current sermon runs; and
- its profile analyzer and feature schema versions match.

Consequently source edits, analyzer changes, Bible-source changes, attachments,
detachments, redirects, and newly completed sermon runs all make dependent results stale
without mutating historical runs.

## Resumability and idempotency

Each sermon analysis is persisted atomically. The batch skips current fingerprints and
continues after ordinary per-sermon failures. Profile aggregates are refreshed once,
after the sermon pass, so an interruption cannot leave a profile summary pretending to
include only part of a newly completed batch. On interruption, completed sermon runs
remain durable; the next status/backfill invocation sees them as current and resumes the
remaining work. Repeating a completed invocation creates no new logical runs.

The readiness summary reports eligible/current/missing/stale/blocked sermons, coverage
percentage, aggregate states, and profile counts at 3, 5, 8, and 10 sermons. The initial
operational gate is at least 90% current sermon coverage and a current aggregate for
every profile with at least three eligible sermons, except profiles with an explicit
blocked input.

## Corpus snapshot at implementation

A read-only calculation against the September 5, 2026 database found 338 eligible
attached sermons: 7 current, 327 missing, and 4 stale (2.1% current coverage). Four of
those inputs were blocked by invalid or empty identified sermon windows; blocked is a
diagnostic subset of missing/stale, not a fourth mutually exclusive freshness state.
The corpus had 47 profiles at 3+ sermons, 24 at 5+, 12 at 8+, and 9 at 10+. Aggregate
state was 0 current, 1 stale, and 69 missing. The backfill therefore remains operator
work and the 90% success gate has not yet been reached.

## Next iteration

Once the backfill meets the gate, freeze the JSON readiness snapshot and perform the
analysis-of-analysis: feature distributions and missingness, zero inflation, redundancy,
within- versus between-pastor variance, leave-one-out sensitivity, bootstrap intervals,
and stability by sermon count. That empirical review should determine the feature schema
used later for reference-pastor comparison; it should not rank candidates or introduce
new semantic dimensions.
