# Storage compaction

`pte storage compact` is the single operator workflow for generated evaluation storage.
It keeps media archival and evaluation retention as separate policies while sharing the
configured archive destination and application archive lock.

## Current policy

The first policy is intentionally conservative:

- retain the three newest timestamped systemic diagnostic runs locally;
- irreversibly discard older diagnostic runs because they are derived and unreferenced;
- retain every speaker-span WAV pinned anywhere in reviewed evidence or pending drafts;
- archive only unreferenced `speaker_span_v1` WAV/manifest pairs;
- leave `speaker_span_v2`, canonical audio, embeddings, pair diagnostics, association
  runs, and discovery runs unchanged.

Speaker-span archives are byte-preserving. Each bundle contains an embedded manifest with
the original evaluation-relative path, size, and SHA-256 of every member. ZIP CRC is not
treated as sufficient verification: PTE streams and verifies every member SHA-256 before
removing a local source.

## Plan and apply

Dry-run is the default:

```console
pte storage compact \
  --base-dir /Users/briancummings/Documents/PastorSearchData \
  --repo-root /Users/briancummings/code/pastor-transcript-extractor
```

Unless `--archive-root` is supplied, the command reuses the active media archive
destination beneath `evaluation-storage/`. The dry-run writes
`<base-dir>/evaluation/storage-manifests/compact-plan.json` and changes no candidate
files.

After reviewing that manifest:

```console
pte storage compact --apply \
  --base-dir /Users/briancummings/Documents/PastorSearchData \
  --repo-root /Users/briancummings/code/pastor-transcript-extractor
```

Every unit declares either `discard_local` or `archive_verify_remove_local`. Diagnostics
use the former; superseded speaker-span cache pairs use the latter. Before either action,
PTE checks that source size and modification time still match the reviewed plan. For
archive units, apply also performs a write/fsync/delete destination probe, checks
conservative free-space requirements, hashes sources, writes a partial bundle, verifies
every archived member, and publishes the bundle atomically before removal. A failed unit
leaves its local sources in place. Unsafe symlinks, malformed legacy manifests, missing
WAV pairs, path escapes, or archive collisions block cleanup instead of being guessed
through.

Rerunning is safe. Already-discarded diagnostic files are absent from the next plan. A
verified existing archive is reused when it contains the same member
bytes. An interrupted run after archive publication can remove its remaining covered
sources on the next invocation. New legacy-cache batches receive content-derived archive
unit names rather than colliding with an earlier batch.

## Verification and restore

Verify an archive independently:

```console
pte storage verify \
  /archive/evaluation-storage/speaker-pairs/unreferenced-speaker-span-v1-HASH.zip
```

Plan a restore, then apply it:

```console
pte storage restore \
  /archive/evaluation-storage/speaker-pairs/unreferenced-speaker-span-v1-HASH.zip \
  --base-dir /Users/briancummings/Documents/PastorSearchData

pte storage restore --apply \
  /archive/evaluation-storage/speaker-pairs/unreferenced-speaker-span-v1-HASH.zip \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Restore never overwrites a different local file. Byte-identical existing members are
reported as already present. New members are streamed to a temporary file, fsynced,
SHA-256 verified, and atomically published.

## Extending retention

Association, discovery, current speaker-span, embedding, and pair-diagnostic cleanup
remain excluded until their database and artifact reachability rules are implemented and
tested. New policies should add roots and reasons to the same plan rather than introduce
another cleanup command. Authoritative reviews, fixtures, observation reviews,
revocations, and policies are permanent roots and must never be age-pruned.
