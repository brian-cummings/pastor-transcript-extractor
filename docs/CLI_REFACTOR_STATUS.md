# CLI maintainability refactor status

This is the live execution record for `docs/CLI_REFACTOR_PLAN.md`. Keep it
current after every implementation slice so work can resume safely after
context compaction or a new session.

## Current state

- Status: in progress.
- Active milestone: Milestone 6 — split identity by capability.
- Next action: extract the identity run's association and machine-assignment
  orchestration into named stage functions, preserving checkpoint refresh,
  held-out exclusion, reconciliation order, and plan-only non-mutation.
- Dataset validation: not needed for the current milestone.

## Baseline observations

Recorded September 24, 2026:

- `src/pastor_transcript_extractor/cli.py`: 18,117 lines.
- Top-level imports: 94.
- Top-level functions: 221.
- Functions at least 50 lines: 83.
- Functions at least 100 lines: 40.
- Largest function: `shadow_associate_speakers_command`, 1,611 lines.
- Test modules importing `app`: 23.
- Approximate patches targeting `pastor_transcript_extractor.cli.*`: 348 across
  86 symbol names.

These metrics describe the starting architecture; they are not per-milestone
success targets.

## Working-tree boundary at plan creation

The following pre-existing changes were present before the refactor documents
were added and are outside this plan unless Brian explicitly brings them into
scope:

```text
 M src/pastor_transcript_extractor/cli.py
 M src/pastor_transcript_extractor/storage.py
 M tests/test_source_processing_enablement.py
?? evaluation/speaker-pairs/reviews/pair-208fd479915a3ead/
?? evaluation/speaker-pairs/reviews/pair-6103555f11804ae5/
?? evaluation/speaker-pairs/reviews/pair-a3f22fd3ef1753cc/
?? evaluation/speaker-pairs/reviews/pair-b09b6400364f4c1b/
```

Implementation must inspect overlapping diffs before editing and must preserve
these changes.

## Milestone checklist

- [x] 1. Freeze the CLI contract.
- [x] 2. Introduce the composition structure.
- [x] 3. Extract lower-coupling command groups.
  - [x] Benchmark.
  - [x] Analysis: content.
  - [x] Analysis: structure.
  - [x] Analysis: style.
  - [x] Media.
  - [x] Evaluation, fixtures, and diagnostics.
- [x] 4. Separate catalog commands from acquisition workflows.
- [x] 5. Extract the top-level pipeline.
- [ ] 6. Split identity by capability.
- [ ] 7. Decompose oversized identity workflows.
- [ ] 8. Replace incidental test seams.
- [ ] 9. Remove migration scaffolding and verify the final architecture.

## Decision log

### 2026-09-24 — Use repository-backed project memory

The plan and execution status are persisted separately. The plan holds stable
architecture, constraints, and acceptance criteria. This file holds changing
state, validation evidence, decisions, and the next exact action.

### 2026-09-24 — Preserve the public CLI throughout migration

`pastor_transcript_extractor.cli:app`, `main()`, and the `pte` entry point remain
stable. Command groups move in vertical slices with their tests.

### 2026-09-24 — Separate relocation from decomposition

Moving a large function to a new file does not count as improving its
maintainability. Lower-coupling command groups may move mostly intact first,
but oversized orchestration functions require named stages and typed
request/result boundaries.

### 2026-09-24 — Do not run dataset jobs during the refactor

Development validation is limited to focused unit tests and inexpensive static
checks. Brian receives exact commands for any later dataset validation.

## Completed slices

### 2026-09-24 — Milestone 1: frozen CLI contract

Added `tests/test_cli_contract.py` with exact command-topology assertions for
all root commands and all nine command groups, targeted root and benchmark help
assertions, a representative Typer validation failure, and package/installed
entry-point assertions.

No production code changed in this slice.

### 2026-09-24 — Milestone 2: command composition seam

Added the `pastor_transcript_extractor.commands` package and centralized the
nine Typer group instances plus their public attachment order in
`commands/apps.py`. The stable `cli.py` entry point now creates the root app and
attaches those shared groups before registering the existing commands.

No command implementation moved and the frozen topology, help surfaces, and
entry points remained unchanged.

### 2026-09-24 — Milestone 3.1: benchmark command extraction

Moved all eight benchmark commands and their private membership/database helper
from `cli.py` into `commands/benchmark.py`. The new module owns its Typer
decorators, benchmark-domain imports, database opening, and Rich rendering.
`cli.py` imports the module only to register the shared benchmark app.

No benchmark command functions were direct test imports or patch targets, so no
compatibility re-exports or patch shims were required. `cli.py` decreased from
18,117 baseline lines to 17,752 lines; the cohesive benchmark adapter is 388
lines.

### 2026-09-24 — Milestone 3.2a: content-analysis operations extraction

Moved analysis readiness/status, deterministic backfill, profile refresh,
population build/show, and sermon analysis execution into
`commands/analysis/content.py`. The module is 517 lines and owns six commands,
their rendering helpers, database opening, and scope selection.

The structure commands still use the shared `_analysis_videos` selector through
a temporary explicit import in `cli.py`. Move that selector into the analysis
common boundary when structure commands are extracted; do not leave the
temporary reverse dependency in the final architecture.

### 2026-09-24 — Milestone 3.2b: Scripture analysis command extraction

Moved sermon-analysis inspection, profile Scripture summaries, and the two
reviewed Scripture evaluator commands into `commands/analysis/scripture.py`.
The 465-line module owns five commands and their detailed Rich renderers. It
currently shares database opening and analysis scope selection through the
content module; Milestone 3.3 will move those helpers to a neutral analysis
common module.

The content-analysis checklist item is complete across `content.py` and
`scripture.py`. `cli.py` is now 16,834 lines, down 1,283 lines from baseline.

### 2026-09-24 — Milestone 3.3: structure analysis extraction

Moved all seven deterministic structure commands and their readiness/population
renderers into `commands/analysis/structure.py` (296 lines). Moved shared
database opening and video/profile scope selection into the neutral
`commands/analysis/common.py` (72 lines), removing the temporary dependency
from `cli.py` and `scripture.py` on `content.py` internals.

`cli.py` is now 16,558 lines, down 1,559 lines from baseline.

### 2026-09-24 — Milestone 3.4: style analysis extraction

Moved all seven semantic style commands and their sermon/profile renderers into
`commands/analysis/style.py` (462 lines). The module owns LLM-backed style
execution, inspection, profile summaries, review packet lifecycle, and the two
style evaluators. No analysis decorators remain in `cli.py`; all 25 commands are
registered by the four analysis capability modules.

`cli.py` is now 16,120 lines, down 1,997 lines from baseline.

### 2026-09-24 — Milestone 3.5a: media acquisition extraction

Moved media `backfill`, `ensure-audio`, and coverage `audit` into
`commands/media.py` (177 lines). Added `commands/common.py` as the neutral CLI
database-opening boundary for non-analysis command modules. Media artifact
functions still needed by top-level and identity workflows remain imported by
`cli.py`; only command-specific ownership moved.

`cli.py` is now 15,967 lines, down 2,150 lines from baseline.

### 2026-09-24 — Milestone 3.5b: media provenance extraction

Moved normalized-provenance audit and repair into
`commands/media_provenance.py` (276 lines). The extraction preserves the
all-video availability preflight before identity invalidation, append-only
review cleanup, optional audio-bound fingerprint regeneration, retry command
construction, and old-artifact preservation.

`cli.py` is now 15,718 lines, down 2,399 lines from baseline.

### 2026-09-25 — Milestone 3.5c: media archive extraction

Moved source and normalized archive, canonical-audio preparation, archive
status, and local-audio sweep commands into `commands/media_archive.py`.
The module now owns all ten media decorators and the command-only byte display
helper. The command contract stays registered through the shared `media_app`.
The canonical-audio CLI retry test now patches the owning module rather than
`cli.py`.

`cli.py` is now 15,255 lines, down 2,862 lines from baseline.

### 2026-09-25 — Milestone 3.6a: evaluation and fixture command extraction

Moved the five top-level fixture validation, source-family, and existing-output
evaluation commands into `commands/evaluation.py`. The root Typer app now has
one shared definition in `commands/apps.py`, while `cli.py:app` remains the
stable public object and attaches the existing group apps as before.

The extracted commands continue to use existing artifacts only; no corpus
classification or evaluation job was run during this slice.

### 2026-09-25 — Milestone 3.6b: diagnostic command extraction

Moved all five read-only diagnostics commands into `commands/diagnostics.py`:
single-video and systemic pipeline diagnostics, diagnostic comparison,
interaction diagnostics, and recording-verifier diagnostics. Their domain
imports and rendering now live with the commands, while top-level command names
and read-only behavior remain unchanged.

`cli.py` is now 14,240 lines, down 3,877 lines from baseline.

### 2026-09-25 — Milestone 4.1: initialization and source-ownership extraction

Moved the top-level `init` command plus source-ownership `migrate` and `audit`
commands into `commands/catalog.py`. The catalog adapter owns its database
initialization, savepoint migration, ownership audit rendering, and strict exit
semantics; `cli.py` retains only app assembly and unrelated workflows.

`cli.py` is now 14,157 lines, down 3,960 lines from baseline.

### 2026-09-25 — Milestone 4.2: organization catalog extraction

Moved organization creation, listing, review export, affiliation-claim listing,
and rejection commands into `commands/catalog.py`. The catalog module now owns
organization-specific persistence validation and Rich output.

### 2026-09-25 — Milestone 4.3: pastor catalog extraction

Moved pastor creation, listing, manual affiliation, and reviewed claim
attachment commands into `commands/catalog.py`. Promoted the reusable unknown-
pastor error constructor to `commands/common.py` so remaining workflows and the
catalog adapter share the same error text without importing `cli.py`.

`cli.py` is now 13,871 lines, down 4,246 lines from baseline.

### 2026-09-25 — Milestone 4.4: video and source-deletion extraction

Moved source deletion plus video listing, exclusion, unexclusion, and excluded-
video listing into `commands/catalog.py`, together with their artifact-tree
deletion helpers. `cli.py` temporarily re-exports `delete_source_service`
because the top-level replace-existing workflow still calls and patches that
seam; Milestone 5 will move the workflow and remove the compatibility import.

`cli.py` is now 13,647 lines, down 4,470 lines from baseline.

### 2026-09-25 — Milestone 4.5: source catalog extraction

Moved top-level source addition, source-group add/ownership/enablement/listing,
catalog status, and read-only source-processing reporting into
`commands/catalog.py`. The acquisition workflows retain temporary imports of
`add_source_service` and `delete_source_service`; these compatibility seams are
explicitly scheduled for removal with the pipeline workflow extraction.

The pre-existing recording-count enhancement was not included in this slice's
commit boundary; it is reapplied as an unstaged change in the new owner module.
No catalog group decorators remain in `cli.py`.

`cli.py` is now 13,243 lines, down 4,874 lines from baseline.

### 2026-09-25 — Milestone 4.6: source-discovery workflow extraction

Added `workflows/source_discovery.py` with a typed `DiscoveryRequest`, a
structured `DiscoveryServiceResult` containing selection and outcome counts,
and callback-based progress. The core workflow accepts explicit database,
paths, tool configuration, and discovery-function boundaries and imports no
Typer, Rich, or `cli.py`. The CLI retains a thin compatibility/rendering wrapper
while the top-level pipeline still patches that seam.

Corrected the Milestone 4 status: catalog command extraction was complete, but
the plan also requires discovery, caption, transcription, and imported-source
workflows before Milestone 4 can close.

`cli.py` is now 12,966 lines, down 5,151 lines from baseline.

### 2026-09-25 — Milestone 4.7: caption-acquisition workflow extraction

Added `workflows/caption_acquisition.py` with typed request/result objects,
explicit database, path, tool, fetcher, clock, sleeper, and progress boundaries,
plus named selection, request-scheduling, per-video acquisition, and queue
stages. The workflow imports no Typer, Rich, or `cli.py`; direct workflow tests
exercise its structured counts and retry behavior without a CLI runner.

The stable `cli.fetch_captions_service` symbol is now a thin rendering and
compatibility wrapper. It explicitly passes the existing CLI fetcher and clock
seams so pipeline and command tests retain their current patch behavior until
Milestone 5 removes that migration scaffolding. Rate-limit and authentication
stops retain the same exception identity through a compatibility re-export.

`cli.py` is now 12,804 lines, down 5,313 lines from baseline.

### 2026-09-26 — Milestone 4.8: transcription workflow extraction

Added `workflows/transcription.py` with typed request/result boundaries and
named selection, stale-recovery, claim, preparation, completion, bounded
pipeline, and one-retry stages. Added `workflows/transcription_events.py` as the
small presentation-neutral event contract for queue, stage, progress,
completion, and retry reporting. Neither workflow module imports Typer, Rich,
or `cli.py`.

The CLI now retains only a Rich event renderer and a thin compatibility
wrapper. Explicit preparation and completion dependencies preserve existing
`cli.prepare_transcription_input` and `cli.complete_transcription_video` patch
seams until Milestone 5, while direct workflow tests exercise structured
counts, progress events, and retry results without Typer or Rich.

`cli.py` is now 12,512 lines, down 5,605 lines from baseline.

### 2026-09-26 — Milestone 4.9: imported-source sync workflow extraction

Added `workflows/source_sync.py` with typed request/result and dependency
boundaries plus named source acquisition, extraction/registration, disk
admission, and asynchronous archive-coordination stages. The workflow imports
no Typer, Rich, or `cli.py`; configuration and disk-reserve failures are domain
errors translated by the thin CLI handler.

Existing CLI patch seams are passed explicitly through `SourceSyncDependencies`
until the top-level pipeline migration removes them. Direct workflow tests now
cover stage order, structured aggregate counts, and the pre-discovery disk
reserve stop without a CLI runner.

Milestone 4 is complete: catalog commands are separated from discovery,
caption, transcription, and imported-source synchronization workflows, and all
four workflows are callable without Typer or Rich.

`cli.py` is now 12,332 lines, down 5,785 lines from baseline.

### 2026-09-26 — Milestone 5.1: run media coordination extraction

Added `workflows/run_media.py` with typed request/result and dependency
boundaries plus named eligibility, audio assurance/retry, and source
archive/retry stages. The workflow imports no Typer, Rich, or `cli.py` and
returns audio and archive outcome counts.

`cli._ensure_and_archive_run_media` remains as a thin compatibility and console
adapter because current pipeline tests patch that symbol. Direct workflow tests
exercise structured results without CLI presentation, while existing tests
continue to verify unexpected per-video failures, one-pass audio retry, archive
retry, and the existing patch seams.

`cli.py` is now 12,225 lines, down 5,892 lines from baseline.

### 2026-09-26 — Milestone 5.2: offline audio-stage execution extraction

Added `workflows/audio_stage.py` with typed request/result and dependency
boundaries plus bounded staging, unexpected-worker recovery, one-pass retry,
manifest creation, offline resume-command rendering, and verified-scope caption
acquisition. The workflow imports no Typer, Rich, or `cli.py`.

The top-level pipeline still owns source-scope resolution temporarily, then
hands the selected video ids to the new workflow. Existing CLI patch seams for
the staging worker, manifest writer, and caption service remain explicit, and
direct workflow coverage verifies retry and structured manifest results.

`cli.py` is now 12,145 lines, down 5,972 lines from baseline.

### 2026-09-26 — Milestone 5.3: offline resume workflow extraction

Added `workflows/resume_pipeline.py` with typed request/result and dependency
boundaries for caption reconciliation, network-disabled transcription,
extraction, media assurance/archive, optional identity, and review refresh. The
workflow preserves the post-content order and imports no Typer, Rich, or
`cli.py`; manifest verification progress remains a CLI presentation concern.

The CLI passes its existing service symbols explicitly, preserving current
patch seams while the remaining scope-specific pipeline paths migrate. Direct
workflow coverage verifies offline transcription and the media → identity →
review ordering.

`cli.py` is now 12,082 lines, down 6,035 lines from baseline.

### 2026-09-26 — Milestone 5.4: offline catalog selection ownership

Moved newest-first, sermon-eligible, exclusion-aware offline catalog selection
into `workflows/audio_stage.py`. The CLI keeps the directly imported helper as
a thin compatibility adapter and explicitly passes its metadata-live-status
seam for existing tests.

`cli.py` is now 12,039 lines, down 6,078 lines from baseline.

### 2026-09-26 — Milestone 5.5: online pipeline extraction

Added `workflows/pipeline.py` with typed request, scope, result, dependency,
and event boundaries. Failed-only, selected-source, all-enabled-source, and
single-URL runs now share named validation, scope resolution, discovery,
transcript acquisition, extraction, media, identity, and review stages. The
workflow imports no Typer, Rich, or `cli.py`, and direct tests cover all-source
ordering, failed-only rebuild policy, URL replacement, and pre-mutation scope
validation.

The CLI injects its existing service symbols so current tests and external
callers can continue patching the compatibility seams during the remaining
top-level migration. Removed the four duplicated online branches from
`run_workflow_service`.

`cli.py` is now 11,764 lines, down 6,353 lines from baseline.

### 2026-09-26 — Milestone 5.6: offline audio scope extraction

Added typed audio-stage scope request, result, and dependency boundaries to
`workflows/audio_stage.py`. Source-id, all-enabled-source, and single-URL
selection now share workflow-owned validation, discovery or catalog-only
selection, replacement, and explained empty-scope handling. Direct tests cover
selected-source isolation and the no-enabled-source result.

The CLI now supplies its existing source/catalog seams and only renders scope
events before invoking audio staging. Removed its duplicate discovery-result
selector and 80 lines of scope policy.

`cli.py` is now 11,702 lines, down 6,415 lines from baseline.

### 2026-09-26 — Milestone 5.7: top-level run dispatch extraction

Added `workflows/run.py` with a single typed request/result boundary and named
online, audio-stage, and staged-resume dispatch paths. Cross-mode validation,
source-id canonicalization, resume verification sequencing, and construction
of the existing online/offline workflow requests now live outside the CLI.
Direct tests cover all three modes and prove invalid combinations stop before
any dependency is called.

`cli.run_workflow_service` is now a compatibility adapter: it constructs one
request, injects the existing patch seams, invokes one workflow, and renders
events. Resume manifest verification remains a narrow Rich progress adapter in
the CLI pending the command-module move.

`cli.py` is now 11,625 lines, down 6,492 lines from baseline.

### 2026-09-26 — Milestone 5.8: post-content identity policy extraction

Moved the integrated identity stage message and guarded automatic-run policy
into `workflows/pipeline.py` behind a typed request and explicit identity-runner
boundary. The CLI compatibility function now only injects the existing identity
service and renders its event. Direct coverage verifies the automatic,
all-extractions, non-plan policy and job forwarding.

`cli.py` is now 11,617 lines, down 6,500 lines from baseline.

### 2026-09-27 — Milestone 5.9: run command extraction

Moved the root `run` command, its Typer option surface, and its preflight
rendering into `commands/pipeline.py`. The handler now constructs one typed
`RunWorkflowRequest` and invokes one explicitly configured workflow boundary.
The two command-forwarding tests now patch the owning command module instead
of the incidental `cli.run_workflow_service` symbol.

`cli.py` retains narrow compatibility adapters for direct imports and legacy
patch seams, while workflow policy, mode dispatch, stage orchestration, and the
public command handler all have their target owners. Milestone 5 is complete.

`cli.py` is now 11,469 lines, down 6,648 lines from baseline.

### 2026-09-27 — Milestone 6.1: identity evaluation extraction

Added `commands/identity/evaluation.py` and moved the seven acoustic comparison,
observation-consistency, speaker-model bake-off, experimental-policy replay,
fixture validation, review-selection audit, and pair-result evaluation commands
with their bake-off validation helpers. The cohesive module is 679 lines and
owns its domain imports, read-only database opening, file validation, and Rich
rendering.

Added focused tests for evaluation partition policy and empty fixture-directory
validation. No acoustic model, fixture corpus, or evaluation job was run.

`cli.py` is now 10,854 lines, down 7,263 lines from baseline.

### 2026-09-27 — Milestone 6.2a: observation and pair review extraction

Added `commands/identity/review.py` and moved observation packet preparation,
exact speaker-pair adjudication, terminal normalization, prompt/rendering
helpers, and deferred reviewed-evidence sync command rendering. The module owns
its interactive Typer and Rich surface while keeping review-domain operations
in the existing plain modules.

Speaker-pair tests now import and patch the owning review module rather than
`cli.py`; all focused review and contract tests pass.

`cli.py` is now 10,420 lines, down 7,697 lines from baseline.

### 2026-09-27 — Milestone 6.2b: speaker-negative review extraction

Moved speaker-negative window audit and next-review commands plus their
formatting and continuous-fixture checks into `commands/identity/review.py`.
The module receives the existing sermon ground-truth reviewer through an
explicit composition-time callback, avoiding a reverse dependency on `cli.py`.
The focused correction-reuse test now patches that owning callback seam.

Interactive identity review extraction is complete across observation, pair,
and speaker-negative review paths.

`cli.py` is now 10,258 lines, down 7,859 lines from baseline.

### 2026-09-27 — Milestone 6.3a: core profile command extraction

Added `commands/identity/profiles.py` and moved reviewed-evidence sync, profile
transcript export, and read-only identity profile status into it. The module
owns database opening, profile/discovery status assembly, action guidance,
assignment summaries, and Rich rendering. Shared summary helpers remain as
temporary CLI compatibility seams for the still-unmoved identity workflow.

Focused tests verify dry-run sync does not open the database and canonical
profile redirects are rendered during export.

`cli.py` is now 9,873 lines, down 8,244 lines from baseline.

### 2026-09-27 — Milestone 6.3b: profile attribution and metadata extraction

Added `commands/identity/metadata.py` and moved reviewed profile attribution,
network metadata enrichment, cached Ollama profile-name analysis, and their
detailed renderers. The 641-line module owns interactive attribution I/O and
metadata command policy while reusing the review module's terminal adapter.

Focused tests prove enrichment plan mode does not construct network tools and
metadata-analysis plan mode does not construct the LLM client. Identity
metadata/profile command extraction is complete.

`cli.py` is now 9,267 lines, down 8,850 lines from baseline.

### 2026-09-27 — Milestone 6.4a: identity work coordination extraction

Moved association work planning/status, superseded-member review selection,
bounded association dispatch, and prerequisite repair into
`commands/identity/coordination.py` (338 lines). A composition-time callback
keeps the bounded dispatcher independent of the still-local shadow association
command while preserving per-observation failure isolation and durable work
events.

Added focused command tests for dry-run safety, isolated dispatch failure
recording, and the empty superseded-review queue. The frozen command topology
and all five moved help surfaces remain unchanged.

`cli.py` is now 8,978 lines, down 9,139 lines from baseline.

### 2026-09-27 — Milestone 6.4b: machine-assignment command extraction

Moved current-proposal reconciliation, machine-assignment status, and
append-only rollback commands into `commands/identity/assignments.py` (337
lines). Moved held-out fixture fingerprint selection into the neutral identity
command helper module so assignment planning and the remaining identity run
workflow share one implementation while the old CLI import remains compatible.

Added focused safety tests for dry-run reconciliation, plan-only rollback,
status validation, and held-out fixture exclusion. The existing machine
assignment persistence suite and all three moved help surfaces remain green.

`cli.py` is now 8,644 lines, down 9,473 lines from baseline.

### 2026-09-27 — Milestone 6.4c: identity coordination report extraction

Moved the `identity coordinate` command into the existing coordination module,
which is now 615 lines and remains within the planned module-size range. The
command reuses the composition-time shadow associator while retaining its
single-video execution restriction, read-only audit/replan flow, and explicit
zero-registry-mutation report.

Added focused validation tests for the exact-one-scope invariant and the ban on
corpus-wide shadow execution. The identity coordination domain tests and frozen
CLI contract remain green.

`cli.py` is now 8,387 lines, down 9,730 lines from baseline.

### 2026-09-27 — Milestone 6.5a: typed identity workflow command adapter

Moved the `identity run` Typer adapter into
`commands/identity/workflow.py` and introduced the immutable
`IdentityWorkflowRequest` boundary in `workflows/identity/run.py`. The command
now owns parsing and error translation while composition explicitly binds the
existing workflow service.

This slice does not claim the identity workflow decomposition: the 679-line
service remains in `cli.py` and is the next bounded task. Its decomposition
must name and test reviewed-evidence sync, association/assignment, discovery,
metadata attribution, coordination/review prewarm, and archival stages before
the service moves.

`cli.py` is now 8,309 lines, down 9,808 lines from baseline.

### 2026-09-27 — Milestone 6.5b: identity request validation stage

Added a pure workflow validation stage that checks scope, mutation-flag
compatibility, corpus-only apply gates, and resource limits before storage is
opened. It returns an immutable policy containing the three effective mutation
gates, replacing duplicated boolean derivation inside the orchestration
service.

Focused tests cover every mutation flag under plan-only mode, aggregate
automatic apply behavior, single-video restrictions, scope, and resource
limits. The module imports neither Typer nor Rich.

### 2026-09-27 — Milestone 6.5c: reviewed-evidence synchronization stage

Moved reviewed-evidence loading, writable-database initialization, and evidence
synchronization into a typed workflow stage result. Plan-only runs do not open
a writable database, execution preserves initialize-before-sync ordering, and
stage failures retain the existing `reviewed-evidence sync failed` context.

Migrated affected mocks to the workflow owner. The broader
`tests.test_identity_run` module is temporarily unimportable because unrelated
catalog WIP removed its expected `cli.validate_source_families` compatibility
symbol; no catalog or source-processing file was changed by this slice.

`cli.py` is now 8,297 lines, down 9,820 lines from baseline.

## Validation log

### 2026-09-24 — CLI contract baseline

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_benchmark tests.test_source_processing_enablement -q
Ran 29 tests in 1.994s — OK

git diff --check -- tests/test_cli_contract.py docs/CLI_REFACTOR_PLAN.md docs/CLI_REFACTOR_STATUS.md
PASS
```

### 2026-09-24 — Command composition seam

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_benchmark tests.test_source_processing_enablement -q
Ran 29 tests in 2.098s — OK

.venv/bin/python -m pastor_transcript_extractor --help
PASS

.venv/bin/pte --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-24 — Benchmark command extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py tests/test_benchmark.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_benchmark -q
Ran 26 tests in 1.559s — OK

.venv/bin/python -m pastor_transcript_extractor benchmark --help
PASS

.venv/bin/pte benchmark --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/benchmark.py src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-24 — Content-analysis operations extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py tests/test_analysis_readiness.py tests/test_population_analysis.py tests/test_sermon_analysis.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_analysis_readiness tests.test_population_analysis tests.test_sermon_analysis -q
Ran 34 tests in 6.561s — OK

.venv/bin/python -m pastor_transcript_extractor analysis --help
PASS

.venv/bin/pte analysis --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/analysis src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-24 — Scripture analysis command extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py tests/test_sermon_analysis.py tests/test_scripture_reference_detection.py tests/test_scripture_alignment.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_sermon_analysis tests.test_scripture_reference_detection tests.test_scripture_alignment -q
Ran 29 tests in 2.258s — OK

.venv/bin/python -m pastor_transcript_extractor analysis --help
PASS

.venv/bin/pte analysis --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/analysis/scripture.py src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-24 — Structure analysis extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py tests/test_sermon_analysis.py tests/test_structure_population_analysis.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_sermon_analysis tests.test_structure_population_analysis -q
Ran 21 tests in 3.513s — OK

.venv/bin/python -m pastor_transcript_extractor analysis --help
PASS

.venv/bin/pte analysis --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/analysis src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-24 — Style analysis extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py tests/test_style_analysis.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_style_analysis -q
Ran 15 tests in 1.461s — OK

.venv/bin/python -m pastor_transcript_extractor analysis --help
PASS

.venv/bin/pte analysis --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/analysis/style.py src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-24 — Media acquisition extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py tests/test_media_artifacts.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_media_artifacts -q
Ran 46 tests in 2.426s — OK

.venv/bin/python -m pastor_transcript_extractor media --help
PASS

.venv/bin/pte media --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/common.py src/pastor_transcript_extractor/commands/media.py src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-24 — Media provenance extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py tests/test_media_artifacts.py tests/test_identity.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_media_artifacts tests.test_identity -q
Ran 55 tests in 2.521s — OK

.venv/bin/python -m pastor_transcript_extractor media --help
PASS

.venv/bin/pte media --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/media_provenance.py src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-25 — Media archive extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py tests/test_canonical_audio_preparation.py tests/test_media_artifacts.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_canonical_audio_preparation tests.test_media_artifacts -q
Ran 58 tests in 1.819s — OK

.venv/bin/python -m pastor_transcript_extractor media --help
PASS

.venv/bin/pte media --help
PASS

git diff --check -- src/pastor_transcript_extractor/cli.py src/pastor_transcript_extractor/commands/media_archive.py src/pastor_transcript_extractor/commands/media_provenance.py tests/test_canonical_audio_preparation.py
PASS
```

### 2026-09-25 — Evaluation and fixture command extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_fixture_validation -q
Ran 24 tests in 0.399s — OK

.venv/bin/python -m pastor_transcript_extractor --help
PASS

.venv/bin/pte --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/apps.py src/pastor_transcript_extractor/commands/evaluation.py src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-25 — Diagnostic command extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract -q
Ran 6 tests in 0.222s — OK

.venv/bin/python -m pastor_transcript_extractor diagnose-system --help
PASS

.venv/bin/python -m pastor_transcript_extractor diagnose-compare --help
PASS

.venv/bin/python -m pastor_transcript_extractor diagnose-interaction --help
PASS

.venv/bin/python -m pastor_transcript_extractor diagnose-recording-verifier --help
PASS

.venv/bin/pte diagnose-system --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/diagnostics.py src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-25 — Initialization and source-ownership extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract -q
Ran 6 tests in 0.228s — OK

.venv/bin/python -m pastor_transcript_extractor init --help
PASS

.venv/bin/python -m pastor_transcript_extractor source-ownership migrate --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/catalog.py src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-25 — Organization catalog extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract -q
Ran 6 tests in 0.233s — OK

.venv/bin/python -m pastor_transcript_extractor organization --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/catalog.py src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-25 — Pastor catalog extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py tests/test_sources.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_sources.CliTests.test_pastor_add_and_add_source_flow -q
Ran 7 tests in 0.288s — OK

.venv/bin/python -m pastor_transcript_extractor pastor --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/catalog.py src/pastor_transcript_extractor/commands/common.py src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-25 — Video and source-deletion extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py tests/test_sources.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_sources.CliTests.test_video_list_shows_discovered_videos tests.test_sources.CliTests.test_video_list_filters_by_status tests.test_sources.CliTests.test_video_exclude_deletes_local_artifacts_and_persists_exclusion tests.test_sources.CliTests.test_run_replace_existing_deletes_source_before_pipeline -q
Ran 10 tests in 0.408s — OK

.venv/bin/python -m pastor_transcript_extractor video --help
PASS

.venv/bin/python -m pastor_transcript_extractor source delete --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/catalog.py src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-25 — Source catalog extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py tests/test_sources.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract tests.test_sources.CliTests.test_pastor_add_and_add_source_flow tests.test_sources.CliTests.test_run_replace_existing_deletes_source_before_pipeline -q
Ran 8 tests in 0.343s — OK

.venv/bin/python -m pastor_transcript_extractor source --help
PASS

.venv/bin/python -m pastor_transcript_extractor status --help
PASS

.venv/bin/python -m pastor_transcript_extractor source-processing-report --help
PASS

git diff --check -- src/pastor_transcript_extractor/commands/catalog.py src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-25 — Source-discovery workflow extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_cli_contract.py tests/test_sources.py
PASS

.venv/bin/python -m unittest tests.test_cli_contract plus eleven focused discovery tests
Ran 17 tests — OK

.venv/bin/python -m pastor_transcript_extractor discover --help
PASS

git diff --check -- src/pastor_transcript_extractor/workflows src/pastor_transcript_extractor/cli.py
PASS
```

### 2026-09-25 — Caption-acquisition workflow extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_caption_acquisition_workflow.py
PASS

.venv/bin/python -m unittest -q tests.test_caption_acquisition_workflow tests.test_cli_contract plus thirteen focused caption CLI tests
Ran 21 tests in 0.793s — OK

.venv/bin/python -m pastor_transcript_extractor fetch --help
PASS

git diff --check
PASS
```

### 2026-09-26 — Transcription workflow extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_transcription_workflow.py tests/test_cli_contract.py tests/test_sources.py tests/test_church_database_import.py
PASS

.venv/bin/python -m unittest -q tests.test_transcription_workflow tests.test_cli_contract tests.test_church_database_import plus eleven focused transcription CLI tests
Ran 33 tests in 1.845s — OK

.venv/bin/python -m pastor_transcript_extractor transcribe --help
PASS

git diff --check
PASS
```

### 2026-09-26 — Imported-source sync workflow extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_source_sync_workflow.py tests/test_church_database_import.py tests/test_cli_contract.py
PASS

.venv/bin/python -m unittest -q tests.test_source_sync_workflow tests.test_church_database_import tests.test_cli_contract
Ran 22 tests in 0.960s — OK

.venv/bin/python -m pastor_transcript_extractor sync-imported-sources --help
PASS

git diff --check
PASS
```

### 2026-09-26 — Run media coordination extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_run_media_workflow.py
PASS

.venv/bin/python -m unittest -q tests.test_run_media_workflow tests.test_cli_contract plus four focused run-media CLI tests
Ran 11 tests in 0.369s — OK

git diff --check
PASS
```

### 2026-09-26 — Offline audio-stage execution extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_audio_stage_workflow.py
PASS

.venv/bin/python -m unittest -q tests.test_audio_stage_workflow tests.test_cli_contract plus three focused audio-stage CLI tests
Ran 10 tests in 0.309s — OK

git diff --check
PASS
```

### 2026-09-26 — Offline resume workflow extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor tests/test_resume_pipeline_workflow.py
PASS

.venv/bin/python -m unittest -q tests.test_resume_pipeline_workflow tests.test_cli_contract plus four focused resume CLI tests
Ran 11 tests in 0.307s — OK

git diff --check
PASS
```

### 2026-09-26 — Offline catalog selection ownership

```text
.venv/bin/python -m unittest -q tests.test_sources.CliTests.test_skip_discovery_selects_newest_eligible_existing_videos_per_source tests.test_sources.CliTests.test_audio_stage_skip_discovery_never_contacts_source_feeds tests.test_cli_contract
Ran 8 tests in 0.324s — OK

.venv/bin/python -m compileall -q src/pastor_transcript_extractor
PASS

git diff --check
PASS
```

### 2026-09-26 — Online pipeline extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/workflows/pipeline.py src/pastor_transcript_extractor/cli.py tests/test_pipeline_workflow.py
PASS

.venv/bin/python -m unittest tests.test_pipeline_workflow plus sixteen focused run CLI tests
Ran 20 tests in 0.780s — OK

.venv/bin/python -m unittest tests.test_cli_contract tests.test_sources.CliTests.test_run_audio_stage_options_are_forwarded tests.test_resume_pipeline_workflow tests.test_audio_stage_workflow tests.test_run_media_workflow
Ran 10 tests in 0.366s — OK

git diff --check
PASS
```

### 2026-09-26 — Offline audio scope extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/workflows/audio_stage.py src/pastor_transcript_extractor/cli.py tests/test_audio_stage_workflow.py
PASS

.venv/bin/python -m unittest tests.test_audio_stage_workflow plus six focused audio-stage CLI tests and tests.test_cli_contract
Ran 15 tests — OK

git diff --check
PASS
```

### 2026-09-26 — Top-level run dispatch extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/workflows/run.py src/pastor_transcript_extractor/cli.py tests/test_run_workflow.py
PASS

.venv/bin/python -m unittest tests.test_run_workflow tests.test_pipeline_workflow tests.test_audio_stage_workflow tests.test_resume_pipeline_workflow plus ten focused run-mode CLI tests
Ran 22 tests in 0.139s — OK

.venv/bin/python -m unittest tests.test_cli_contract plus fourteen focused online and forwarding CLI tests
Ran 20 tests in 0.938s — OK

git diff --check
PASS
```

### 2026-09-26 — Post-content identity policy extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/workflows/pipeline.py src/pastor_transcript_extractor/cli.py tests/test_pipeline_workflow.py
PASS

.venv/bin/python -m unittest tests.test_pipeline_workflow plus three focused integrated-identity CLI tests
Ran 8 tests in 0.069s — OK

git diff --check
PASS
```

### 2026-09-27 — Run command extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/commands/pipeline.py src/pastor_transcript_extractor/cli.py tests/test_sources.py
PASS

.venv/bin/python -m unittest tests.test_run_workflow tests.test_pipeline_workflow tests.test_audio_stage_workflow tests.test_resume_pipeline_workflow tests.test_cli_contract plus twenty-four focused run CLI tests
Ran 44 tests in 0.902s — OK

git diff --check
PASS
```

### 2026-09-27 — Identity evaluation extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/commands/identity src/pastor_transcript_extractor/cli.py tests/test_identity_evaluation_commands.py
PASS

.venv/bin/python -m unittest tests.test_identity_evaluation_commands tests.test_cli_contract
Ran 9 tests in 0.261s — OK

.venv/bin/python -m pastor_transcript_extractor identity compare-speakers --help
PASS

.venv/bin/python -m pastor_transcript_extractor identity run-speaker-model-bakeoff --help
PASS

.venv/bin/python -m pastor_transcript_extractor identity validate-pair-fixtures --help
PASS

git diff --check
PASS
```

### 2026-09-27 — Observation and pair review extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/commands/identity/review.py src/pastor_transcript_extractor/cli.py tests/test_speaker_pair_review.py
PASS

.venv/bin/python -m unittest tests.test_speaker_pair_review tests.test_cli_contract tests.test_sources.CliTests.test_negative_window_review_reuses_existing_continuous_fixture
Ran 30 tests in 0.354s — OK

git diff --check
PASS
```

### 2026-09-27 — Speaker-negative review extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/commands/identity/review.py src/pastor_transcript_extractor/cli.py tests/test_sources.py
PASS

.venv/bin/python -m unittest tests.test_speaker_pair_review tests.test_cli_contract tests.test_sources.CliTests.test_negative_window_review_reuses_existing_continuous_fixture
Ran 30 tests in 0.352s — OK

git diff --check
PASS
```

### 2026-09-27 — Core profile command extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/commands/identity/profiles.py src/pastor_transcript_extractor/cli.py tests/test_identity_profile_commands.py
PASS

.venv/bin/python -m unittest tests.test_identity_profile_commands tests.test_cli_contract
Ran 8 tests in 0.228s — OK

.venv/bin/python -m pastor_transcript_extractor identity profile-status --help
PASS

.venv/bin/python -m pastor_transcript_extractor identity sync-reviewed-speaker-evidence --help
PASS

.venv/bin/python -m pastor_transcript_extractor identity export-profile --help
PASS

git diff --check
PASS
```

### 2026-09-27 — Profile attribution and metadata extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/commands/identity/metadata.py src/pastor_transcript_extractor/cli.py tests/test_identity_metadata_commands.py
PASS

.venv/bin/python -m unittest tests.test_identity_metadata_commands tests.test_identity_profile_commands tests.test_cli_contract
Ran 10 tests in 0.246s — OK

.venv/bin/python -m pastor_transcript_extractor identity review-profile-attribution --help
PASS

.venv/bin/python -m pastor_transcript_extractor identity enrich-metadata --help
PASS

.venv/bin/python -m pastor_transcript_extractor identity analyze-profile-metadata --help
PASS

git diff --check
PASS
```

### 2026-09-27 — Identity work coordination extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/commands/identity/coordination.py src/pastor_transcript_extractor/cli.py tests/test_identity_coordination_commands.py
PASS

.venv/bin/python -m unittest tests.test_identity_coordination_commands tests.test_cli_contract
Ran 9 tests in 0.244s — OK

.venv/bin/python -m pastor_transcript_extractor identity <moved-command> --help
PASS for association-work-plan, association-work-status,
review-next-superseded-profile-member, dispatch-associations, and
repair-association-prerequisites

git diff --check
PASS
```

### 2026-09-27 — Machine-assignment command extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/commands/identity/common.py src/pastor_transcript_extractor/commands/identity/assignments.py src/pastor_transcript_extractor/cli.py tests/test_identity_assignment_commands.py
PASS

.venv/bin/python -m unittest tests.test_identity_assignment_commands tests.test_speaker_machine_assignment tests.test_cli_contract
Ran 29 tests in 2.165s — OK

.venv/bin/python -m pastor_transcript_extractor identity <moved-command> --help
PASS for reconcile-current-proposals, machine-assignment-status, and
rollback-machine-assignments

git diff --check
PASS
```

### 2026-09-27 — Identity coordination report extraction

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/commands/identity/coordination.py src/pastor_transcript_extractor/cli.py tests/test_identity_coordination_commands.py
PASS

.venv/bin/python -m unittest tests.test_identity_coordination_commands tests.test_identity_coordination tests.test_cli_contract
Ran 31 tests in 0.254s — OK

.venv/bin/python -m pastor_transcript_extractor identity coordinate --help
PASS

git diff --check
PASS
```

### 2026-09-27 — Typed identity workflow command adapter

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/commands/identity/workflow.py src/pastor_transcript_extractor/workflows/identity src/pastor_transcript_extractor/cli.py tests/test_identity_workflow_commands.py
PASS

.venv/bin/python -m unittest tests.test_identity_workflow_commands tests.test_cli_contract
Ran 8 tests in 0.244s — OK

.venv/bin/python -m pastor_transcript_extractor identity run --help
PASS

git diff --check
PASS
```

### 2026-09-27 — Identity request validation stage

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/workflows/identity/run.py src/pastor_transcript_extractor/cli.py tests/test_identity_run_workflow.py
PASS

.venv/bin/python -m unittest tests.test_identity_run_workflow tests.test_identity_workflow_commands tests.test_cli_contract
Ran 12 tests in 0.238s — OK

git diff --check
PASS
```

### 2026-09-27 — Reviewed-evidence synchronization stage

```text
.venv/bin/python -m compileall -q src/pastor_transcript_extractor/workflows/identity/run.py src/pastor_transcript_extractor/cli.py tests/test_identity_run_workflow.py tests/test_identity_run.py tests/test_identity_stage_cache.py
PASS

.venv/bin/python -m unittest tests.test_identity_run_workflow tests.test_identity_workflow_commands tests.test_cli_contract
Ran 15 tests in 0.237s — OK

.venv/bin/python -m unittest tests.test_identity_stage_cache
Ran 7 tests in 0.665s — OK

.venv/bin/python -m unittest tests.test_identity_run.IdentityRunTests.test_identity_run_executes_full_ordered_workflow
NOT RUN: module import is blocked by the unrelated catalog WIP removing
`cli.validate_source_families`; the affected test patches were still migrated
and compile successfully.

git diff --check
PASS
```

## Known risks

- Existing tests rely heavily on `cli.py` import and patch locations. Every
  extraction must migrate its tests in the same slice.
- Temporary re-exports preserve direct imports but do not preserve patches of
  dependencies after ownership moves.
- Identity and pipeline workflows combine policy, persistence, progress, and
  recovery behavior; careless decomposition could change execution order or
  safety boundaries.
- Pre-existing edits overlap `cli.py`, so the relevant diff must be inspected
  before the first code change.

## Resume checklist

Before continuing:

1. Read `AGENTS.md` and `docs/CLI_REFACTOR_PLAN.md`.
2. Inspect this file for the active milestone and next action.
3. Run `git status --short` and inspect overlapping diffs.
4. Perform only the next bounded slice.
5. Run its focused checks and record the exact results here.
