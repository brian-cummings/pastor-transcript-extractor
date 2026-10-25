# Evaluation storage migration

Generated evaluation, runtime and full source-backed review artifacts belong under
the configured application-data directory at `<base-dir>/evaluation/`. Human review
does not make transcript text, identity metadata or a corpus inventory suitable for
publication in Git. Contracts, synthetic fixtures, policies and implementation
documentation remain repository inputs.

## Path classification

Repository-owned inputs remain in Git:

- `fixtures/`, `baselines/`, `experiments/`, and `source-families.json`
- reviewed scripture, alignment, and sermon-style evidence
- speaker-pair policies, fixtures, reviews, observation reviews, and revocations
- speaker-association policies and source-family definitions
- design/contract documentation and decisions outside the private evidence rules

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

In addition, `PRIVATE_EVIDENCE_PATTERNS` in `evaluation_storage.py` explicitly selects:

- sermon-topic generated JSON and Markdown (the authored `behavior-contract-v1.json` stays)
- G1/G2/G3 feasibility results and versioned response caches
- readiness execution artifacts, ledgers, receipts and source audits
- observed-profile consumer outputs
- review proposal source snapshots, inputs, references, census files, source audits,
  source oracles, source validations and their evidence-bearing Markdown companions
- the collector V3 design data and geometry report, G1/G2/G3 prepared case data,
  profile-evidence packet and pastor-contract registry exports
- generated JSON snapshots and exports in `docs/analytical-review/`

The rules cover future versions of the selected artifact families and are mirrored
in `.gitignore`; a focused test checks that the ignore list stays aligned. They
include all nine unique files in the large-artifact review. This is an explicit
storage policy, not a rule that every JSON file or reviewed artifact is disposable.
Synthetic probes, schemas, authored question contracts, ordinary design documents
and reviewed speaker regression inputs are retained.

Private `evaluation/...` files retain their relative path beneath `<base-dir>/evaluation/`.
Private `docs/...` packets move beneath `<base-dir>/evaluation/review-packets/docs/...`,
preserving their namespace rather than flattening them into evaluation results.

## Static publication audit

Add `--audit-repository` to the migration dry run to produce
`<base-dir>/evaluation/repository-storage-audit.json` and `.md`. The audit examines
tracked JSON, Markdown and tabular working files, reporting file paths, sizes and
counts of local-user paths, named-person cues, source text fields, identity fields
and source identifiers. It does not copy names, quotations or field values into the
report. It neither opens the application database nor performs inference.

`migrate` rows follow the explicit policy. `review_retained_source` rows can include
legitimate fixtures, historical plans, author attribution and documentation examples;
they are disclosed for review, not automatically deleted or anonymized. Pattern
matching is not exhaustive name detection or a privacy clearance. The audit examines
current working files, not historical Git blobs or current index contents.

## References and checksums

Legacy relative or absolute `evaluation/...` references pass through the central
artifact-path resolver. Generated paths resolve beneath the active `AppPaths.evaluation`
root; repository-owned paths continue to resolve in the checkout. New database path
values are stored relative to the configured evaluation root when possible.

Immutable evidence is moved byte-for-byte and is not rewritten. This preserves Jev
`result_sha256` values, cache input fingerprints, event fingerprints, and other content
hashes. The content-addressed promotion-judgment directory and filename are unchanged.
Only four explicitly named SQLite fields are eligible for conversion to portable paths,
and all selected row updates occur in one transaction after file migration succeeds.

Private review artifacts leave local, ignored **file symlinks** at their legacy paths.
This preserves direct reads and writes by older code without keeping payload bytes
inside the repository. Repeated migration recognizes only an exact link to the
policy-selected destination; arbitrary links and changed destinations are rejected.
An interrupted move with a missing link is recovered on the next apply. Existing
generated cache/run categories retain their original move-without-links behavior.

Review CLI boundaries route recognized output defaults directly into the selected
base directory, even before migration. Recognized inputs prefer migrated evidence and
can read unmigrated packets; explicit custom paths remain explicit overrides. Commands
that previously lacked a base-directory option now expose `--base-dir` where needed.

Compatibility links preserve file access, not every historical execution assumption.
Some frozen verifiers resolve paths and require them to remain physically inside the
repository (for example `evidence_supply_revision.validate_packet` and
`collector_retrieval_audit_v1_1.verify`). Those checks can reject relocated packets.
Their source-code pins and authorization decisions are deliberately not rewritten or
relaxed. Migration SHA-256 checks verify custody of the relocated bytes; they do not
confer pipeline acceptance or authorize replay. A future need to run one of those
closed workflows requires a bounded storage-aware consumer change and its own
compatibility/authority check, not a resealed historical packet.

## Safe migration

Dry-run is the default:

```console
pte migrate-evaluation-storage \
  --base-dir /Users/briancummings/Documents/PastorSearchData \
  --repo-root /Users/briancummings/code/pastor-transcript-extractor \
  --verify --audit-repository --untrack
```

The command writes `evaluation/migration-manifest.json` beneath the application-data
root, with a Markdown companion. It lists every source and destination, byte count,
SHA-256, compatibility-link action, identical destination,
collision, rejected symlink, and enumerated database change. Non-identical collisions
or symlinks are fatal. Same-filesystem files use atomic rename. Cross-filesystem files
are copied to a temporary destination, streamed through SHA-256 verification, renamed
atomically, and only then removed at the source.

After reviewing a clean dry-run, apply and untrack the migrated files with:

```console
pte migrate-evaluation-storage \
  --apply --verify --untrack \
  --base-dir /Users/briancummings/Documents/PastorSearchData \
  --repo-root /Users/briancummings/code/pastor-transcript-extractor
```

`--untrack` selects only tracked paths in the migration plan. It refuses selected
staged changes before moving anything, verifies destination bytes before index removal,
and preserves unrelated staged work. Without `--untrack`, the index is unchanged;
ignore rules alone do not protect files that Git already tracks. Neither mode commits,
pushes, deletes old Git blobs or rewrites history. Review staged removals before
committing. Cleaning unpublished history is a separate publishing step.

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
