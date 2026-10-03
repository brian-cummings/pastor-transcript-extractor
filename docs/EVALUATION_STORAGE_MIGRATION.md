# Evaluation storage migration

Generated evaluation and runtime artifacts belong under the configured application-data
directory at `<base-dir>/evaluation/`. The repository's `evaluation/` tree remains the
home of reviewed and reproducibility inputs.

## Path classification

Repository-owned inputs remain in Git:

- `fixtures/`, `baselines/`, `experiments/`, and `source-families.json`
- reviewed scripture, alignment, and sermon-style evidence
- speaker-pair policies, fixtures, reviews, observation reviews, and revocations
- speaker-association policies and source-family definitions
- README and other documentation files

The migration moves only these explicitly enumerated generated prefixes:

- `drafts/`, `results/`, `diagnostics/`, and `interaction-diagnostics/`
- `recording-verifier/` and `recording-verifier-typesafe/`
- `sermon-topics/cache/`
- `speaker-pairs/{cache,drafts,models,reports,runs}/`
- `speaker-associations/shadow-runs/`
- `speaker-profile-discovery/{shadow-runs,promotion-judgments}/`
- `source-profile-consolidation/runs/`
- `identity-leverage/`

Anything not on that generated list stays in the checkout. The list is shared by path
resolution and migration planning, preventing a whole-tree move.

## References and checksums

Legacy relative or absolute `evaluation/...` references pass through the central
artifact-path resolver. Generated paths resolve beneath the active `AppPaths.evaluation`
root; repository-owned paths continue to resolve in the checkout. New database path
values are stored relative to the configured evaluation root when possible.

Immutable JSON is moved byte-for-byte and is not rewritten. This preserves Jev
`result_sha256` values, cache input fingerprints, event fingerprints, and other content
hashes. The content-addressed promotion-judgment directory and filename are unchanged.
Only four explicitly named SQLite fields are eligible for conversion to portable paths,
and all selected row updates occur in one transaction after file migration succeeds.

## Safe migration

Dry-run is the default:

```console
pte migrate-evaluation-storage \
  --base-dir /Users/briancummings/Documents/PastorSearchData \
  --repo-root /Users/briancummings/code/pastor-transcript-extractor \
  --verify
```

The command writes `evaluation/migration-manifest.json` beneath the application-data
root. It lists every source and destination, byte count, identical destination,
collision, rejected symlink, and enumerated database change. Non-identical collisions
or symlinks are fatal. Same-filesystem files use atomic rename. Cross-filesystem files
are copied to a temporary destination, streamed through SHA-256 verification, renamed
atomically, and only then removed at the source.

After reviewing a clean dry-run, apply with:

```console
pte migrate-evaluation-storage \
  --apply --verify \
  --base-dir /Users/briancummings/Documents/PastorSearchData \
  --repo-root /Users/briancummings/code/pastor-transcript-extractor
```

Repeated execution is safe. An interrupted cross-filesystem copy leaves the source in
place and removes its temporary destination. A later run treats byte-identical completed
destinations as already migrated and removes only the redundant legacy source. For
recovery, keep the manifest, rerun the dry-run, resolve only reported conflicts, and run
`--apply --verify` again. No repository-owned directory is removed by the command.
Before the first database update, apply mode also creates
`app.db.pre-evaluation-migration.bak` without overwriting an existing backup. If the
migration must be abandoned after file movement, use the manifest to reverse completed
source/destination moves, then restore that backup while the application is stopped.

Verify the migrated tree and replay the latest Jev cache without permitting inference:

```console
pte migrate-evaluation-storage --dry-run --verify \
  --base-dir /Users/briancummings/Documents/PastorSearchData \
  --repo-root /Users/briancummings/code/pastor-transcript-extractor

pte identity evaluate-profile-promotions --cache-only --details \
  --base-dir /Users/briancummings/Documents/PastorSearchData \
  --discovery-report /Users/briancummings/Documents/PastorSearchData/evaluation/speaker-profile-discovery/shadow-runs/d5d4162d87cb0907/d5d4162d87cb09078f0628d569e5d04a590fea3f861d6eddf687235ced525aa1.json
```

The first command should report zero planned and remaining legacy files. The second
prints the same grouping IDs and observation IDs with `model_calls=0`; `--cache-only`
never constructs the TypeSafe provider and reports any missing cache entries instead.
