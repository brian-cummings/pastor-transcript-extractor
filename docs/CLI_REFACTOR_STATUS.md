# CLI maintainability refactor status

This is the live execution record for `docs/CLI_REFACTOR_PLAN.md`. Keep it
current after every implementation slice so work can resume safely after
context compaction or a new session.

## Current state

- Status: in progress.
- Active milestone: Milestone 4 — separate catalog commands from acquisition
  workflows.
- Next action: extract the low-coupling pastor, organization, source, video,
  and source-ownership commands into a catalog command module; leave discovery,
  transcription, and sync orchestration in place for the workflow milestone.
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
