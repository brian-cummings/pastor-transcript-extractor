# CLI maintainability refactor plan

Prepared September 24, 2026 from an inspection of
`src/pastor_transcript_extractor/cli.py` and its test consumers. This document
is the source of truth for the refactor. Update
`docs/CLI_REFACTOR_STATUS.md` after every completed implementation slice.

## Objective

Turn `cli.py` into a small composition root while preserving the existing CLI
surface and moving orchestration into independently testable workflows.

The refactor should improve both human maintainability and AI readability:

- a reader can locate a command by capability without searching one giant file;
- Typer parsing, workflow policy, persistence, and Rich rendering have distinct
  ownership;
- large workflows expose named stages, typed inputs, typed results, and explicit
  side-effect boundaries;
- tests patch or fake the component that owns the behavior instead of relying on
  incidental globals in `cli.py`;
- each migration milestone is small enough to understand and validate in one
  development loop.

## Starting point

The initial inspection found:

- `cli.py` is 18,117 lines;
- it contains 94 top-level imports, 221 top-level functions, and 3 classes;
- 83 functions are at least 50 lines and 40 are at least 100 lines;
- the largest function, `shadow_associate_speakers_command`, is 1,611 lines;
- 23 test modules import the root `app`;
- tests directly import more than 30 additional CLI symbols;
- tests contain roughly 348 patches across 86 `pastor_transcript_extractor.cli.*`
  names.

The test coupling means a wholesale file move is unsafe. Commands and tests
must migrate together in bounded vertical slices.

## Target architecture

```text
src/pastor_transcript_extractor/
├── cli.py                         # app assembly, compatibility exports, main
├── commands/
│   ├── __init__.py
│   ├── common.py                  # narrow CLI-only error/output helpers
│   ├── evaluation.py
│   ├── benchmark.py
│   ├── media.py
│   ├── catalog.py                 # pastor, organization, source, video
│   ├── pipeline.py
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── content.py
│   │   ├── structure.py
│   │   └── style.py
│   └── identity/
│       ├── __init__.py
│       ├── evaluation.py
│       ├── review.py
│       ├── profiles.py
│       ├── association.py
│       ├── coordination.py
│       └── workflow.py
├── workflows/
│   ├── __init__.py
│   ├── source_discovery.py
│   ├── caption_acquisition.py
│   ├── transcription.py
│   ├── source_sync.py
│   ├── pipeline.py
│   └── identity/
│       ├── __init__.py
│       ├── run.py
│       ├── review_audio.py
│       ├── profile_discovery.py
│       └── association.py
└── presentation/
    ├── __init__.py
    ├── console.py
    ├── progress.py
    └── tables.py
```

This is a responsibility map, not a requirement to create every file in
advance. Add a module only when behavior is migrated into it.

## Architectural rules

### Commands

A command handler should normally:

1. accept and validate Typer-level input;
2. construct a typed workflow request;
3. invoke one application workflow;
4. render its structured result;
5. translate expected domain/application errors into CLI errors.

Command functions should generally remain below 40 lines, excluding declarative
Typer parameter definitions where extracting those definitions would obscure
the public interface.

### Workflows

Workflow modules must not import Typer or Rich. They own application-level
sequencing and return typed results instead of printing. Large workflows should
be decomposed into intention-revealing stages rather than moved intact.

Dependencies should be explicit and narrow. Prefer boundaries such as database
factory, media acquisition, clock/sleeper, filesystem, and event reporting.
Do not introduce a generic service locator or inject every internal function.

### Presentation

Presentation modules own Rich tables, progress output, and human-readable
summaries. They consume workflow result objects and must not make domain
decisions.

### Compatibility

Keep `pastor_transcript_extractor.cli:app`, `main()`, and the `pte` entry point
stable throughout the migration. Temporary symbol re-exports are acceptable
for direct imports, but do not pretend that re-exporting preserves mock-patch
semantics: tests that patch moved dependencies must migrate to the owning
module in the same slice.

### Readability limits

- Prefer cohesive modules below roughly 500–700 lines.
- Prefer workflow stage functions below roughly 80 lines.
- Use typed dataclasses for nontrivial requests and results.
- Record invariants, mutation behavior, and retry/idempotency expectations at
  workflow boundaries.
- Avoid generic `utils.py` modules.
- Mirror the production capability structure in focused tests.

These are review signals, not mechanical rules. A clear exception is preferable
to artificial fragmentation.

## Milestones

### 1. Freeze the CLI contract

Add `tests/test_cli_contract.py` covering:

- root command names;
- subcommand names for every registered Typer group;
- representative root and group `--help` output;
- representative validation failures and exit codes;
- importability of `pastor_transcript_extractor.cli:app` and the package entry
  point.

Do not snapshot entire help screens if targeted assertions provide a less
brittle contract.

Acceptance criteria:

- existing focused CLI tests still pass;
- the new contract test passes;
- no production behavior changes.

### 2. Introduce the composition structure

Create `commands/` and a minimal app-assembly pattern. Keep `cli.py` as the
stable public entry point. Add only narrow common CLI helpers proven necessary
by the first extraction.

Acceptance criteria:

- all existing command names and nesting remain unchanged;
- `python -m pastor_transcript_extractor --help` and the installed `pte` entry
  point still resolve the same root app;
- no workflow module imports `cli.py`.

### 3. Extract lower-coupling command groups

Move one group per implementation slice, in this order:

1. benchmark commands;
2. analysis commands, split by content, structure, and style;
3. media commands;
4. evaluation, fixture, and diagnostic commands.

For each slice, move its decorators, CLI validation, and rendering; update the
relevant tests and patches at the same time; then run the focused tests plus
the CLI contract test before proceeding.

Acceptance criteria:

- the owning command module is cohesive and independently readable;
- no copied implementation remains in `cli.py`;
- CLI behavior and exit semantics remain unchanged;
- direct compatibility exports are documented and temporary.

### 4. Separate catalog commands from acquisition workflows

Move pastor, organization, source, video, and source-ownership commands into
the catalog command area. Extract plain workflows for discovery, caption
acquisition, transcription, and imported-source synchronization.

Introduce typed request/result objects where a service currently accepts a
large option list or prints results directly. Represent progress with narrow
events or callbacks rather than a global console.

Acceptance criteria:

- catalog CRUD commands are thin wrappers;
- discovery, caption, transcription, and synchronization services can be
  tested without Typer;
- source-processing behavior and defaults are unchanged.

### 5. Extract the top-level pipeline

Move `discover_sources_service`, `fetch_captions_service`,
`transcribe_videos_service`, `run_workflow_service`, post-content identity, and
media archival coordination out of `cli.py`.

Decompose the top-level run into named stages:

1. validate request;
2. resolve sources;
3. discover recordings;
4. acquire transcripts;
5. extract sermons;
6. run identity when requested;
7. prepare review output;
8. archive media when requested.

The extraction must not change policy, retry behavior, defaults, or ordering.

Acceptance criteria:

- the top-level Typer command constructs one request, invokes one workflow, and
  renders one result;
- stage results retain enough evidence to explain skips and failures;
- pipeline tests no longer require patching unrelated CLI globals.

### 6. Split identity by capability

Migrate identity code in this order:

1. evaluation and fixture commands;
2. interactive review commands;
3. metadata and profile commands;
4. coordination and machine-assignment commands;
5. the identity workflow;
6. shadow association.

Moving a large function unchanged is not completion. Each large identity path
must receive a separately reviewable decomposition plan as it is reached.

Acceptance criteria:

- identity command modules follow user-visible capabilities;
- interactive input/output is separated from policy and persistence;
- identity orchestration is callable without Typer or Rich.

### 7. Decompose oversized identity workflows

Refactor `shadow_associate_speakers_command` into stages resembling:

1. select observations;
2. plan profile routes;
3. prepare profile exemplars;
4. evaluate acoustic associations;
5. decide admissions under the pinned policy;
6. persist artifacts and evidence;
7. build a structured result.

Apply the same approach to `review_next_speaker_pair`,
`shadow_discover_profiles_command`, `consolidate_source_profiles_command`, and
`run_identity_workflow_service`.

Typed stage results must preserve reason codes, provenance, abstentions, and
partial-failure evidence. The refactor must not weaken the existing shadow-only
and human-review safety boundaries.

### 8. Replace incidental test seams

As code moves, replace patches of `cli.Database`, `cli.time.sleep`,
`cli.console.print`, and similar incidental bindings with explicit boundary
fakes or patches at the actual owning module.

Keep two distinct test levels:

- command tests verify parsing, error translation, and rendering;
- workflow tests verify decisions, persistence calls, ordering, and results.

Acceptance criteria:

- tests fail for behavioral regressions rather than import-location changes;
- dependency containers, where used, represent external boundaries rather than
  becoming service locators.

### 9. Remove migration scaffolding

After all consumers use the new ownership boundaries:

- remove temporary re-exports from `cli.py`;
- verify `__main__.py` and the project script entry point;
- add a lightweight import-boundary test preventing workflow imports of Typer,
  Rich, or `cli.py`;
- document any intentional size-limit exceptions;
- update this plan with the final architecture and close the status log.

Final acceptance criteria:

- `cli.py` is under approximately 200 lines and is only a composition root;
- command handlers contain no substantial business orchestration;
- workflows are independently testable and presentation-independent;
- the focused and full inexpensive unit-test suites pass;
- no command names, options, defaults, or documented safety boundaries changed
  unintentionally.

## Validation policy

During development, run focused unit tests and inexpensive static checks only.
Typical per-slice validation is:

```bash
.venv/bin/python -m compileall -q src/pastor_transcript_extractor
.venv/bin/python -m unittest tests.test_cli_contract tests.test_benchmark -q
```

Replace the second module with the focused test modules for the slice. Run the
full inexpensive unit-test suite only at phase boundaries when appropriate.

Do not run large fixture or corpus reclassification/evaluation jobs, acoustic
corpus jobs, or long-running progress monitors. When dataset validation becomes
useful, prepare the exact command, inputs, and expected evidence for Brian to
run and review.

## Scope controls

This refactor does not authorize:

- changes to classification, identity, association, archival, or review policy;
- command renames or option/default changes;
- database schema changes unless a later separately approved design requires
  them;
- broad formatting or unrelated cleanup;
- edits to unrelated working-tree changes;
- dataset reclassification or evaluation runs.

If an extraction exposes a likely behavioral bug, record it in the status log
and propose a separate bounded fix rather than silently changing behavior.

## Working protocol

At the start of each implementation turn:

1. read `AGENTS.md`;
2. read this plan and `docs/CLI_REFACTOR_STATUS.md`;
3. inspect `git status` and the relevant diff;
4. confirm the active milestone and exact next action;
5. preserve unrelated user changes.

At the end of every implementation slice:

1. run the planned focused validation;
2. repair failures before advancing;
3. update the status file with changed files, results, decisions, and the exact
   next action;
4. report any required user-run dataset command without executing it.
