# CLI maintainability refactor status

This is the live execution record for `docs/CLI_REFACTOR_PLAN.md`. Keep it
current after every implementation slice so work can resume safely after
context compaction or a new session.

## Current state

- Status: in progress.
- Active milestone: Milestone 2 — introduce the composition structure.
- Next action: create the minimal `commands/` package and root app-assembly
  pattern without moving behavior yet, then prove the frozen command topology
  and entry points are unchanged.
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
- [ ] 2. Introduce the composition structure.
- [ ] 3. Extract lower-coupling command groups.
  - [ ] Benchmark.
  - [ ] Analysis: content.
  - [ ] Analysis: structure.
  - [ ] Analysis: style.
  - [ ] Media.
  - [ ] Evaluation, fixtures, and diagnostics.
- [ ] 4. Separate catalog commands from acquisition workflows.
- [ ] 5. Extract the top-level pipeline.
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
