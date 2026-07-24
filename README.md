# Pastor Transcript Extractor

Local-first Python CLI for extracting pastor-only sermon transcripts from YouTube videos, playlists, and channels.

## Current Status

This workspace now has the main pipeline scaffold in place:

- Python package structure
- CLI entrypoint
- app data directory initialization
- SQLite initialization
- source URL classification
- source persistence in SQLite
- pastor entity persistence
- pastor-aware artifact path helpers
- transcript segmentation and heuristic extraction
- optional local-LLM sermon-content classification with rule-based fallback
- pastor-scoped Markdown review generation
- caption fetching
- exclusion-aware incremental reruns
- versioned discovery metadata snapshots for future identity evidence
- shadow-mode identity evidence ledgers and assessments
- identity-neutral speaker observations, name claims, and curated profile registry contracts
- independent content/identity decision coordination without export gating
- `init`, `add`, `status`, `doctor`, `discover`, `fetch`, `transcribe`, `extract`, `review`, and `run` command implementation
- `pastor add` and `pastor list`

## V1 Goal

Given one or more YouTube sources, produce pastor-scoped Markdown review files that can be curated by excluding non-sermon videos and regenerating.

## Stack

- Python 3.11+
- Typer
- Rich
- SQLite
- Planned next dependencies: `yt-dlp`, `ffmpeg`, `whisper.cpp`

## Default Local Tooling

The scaffold defaults to:

- `whisper_cpp_bin`: `/Users/briancummings/code/whisper.cpp/build/bin/whisper-cli`
- `whisper_model_path`: `/Users/briancummings/code/whisper.cpp/models/ggml-medium.en.bin`
- `ffmpeg_bin`: `ffmpeg`
- `yt_dlp_bin`: `yt-dlp`

Installed in the project venv:

- `yt-dlp`

## Quick Start

```bash
cd /Users/briancummings/code/pastor-transcript-extractor
/opt/homebrew/bin/python3.11 -m venv .venv
./venv-shell
pip install -e .
pte pastor add sample-church "Sample Church"
pte init
pte add 'https://www.youtube.com/watch?v=abc123' --pastor sample-church
pte status
pte doctor
```

If you prefer to use `python3` directly, update your shell `PATH` so it resolves to Python 3.11 first.

If you already have `.venv` created and just want a shell with it activated, run:

```bash
./venv-shell
```

## App Data

By default the CLI stores local data under:

- `~/.pastor-transcript-extractor/app.db`
- `~/.pastor-transcript-extractor/artifacts`
- `~/.pastor-transcript-extractor/exports`
- `~/.pastor-transcript-extractor/logs`

You can override the data directory with `--base-dir`.

## Workflows

- `pte run <url> --pastor <slug>` runs discovery, caption fetch, optional local
  transcription, adaptive extraction, and pastor review export.
- `pte run --all` performs the same workflow for every configured source and
  writes one review per pastor.
- `pte run <url> --pastor <slug> --skip-review` intentionally stops after
  extraction.
- `pte review <pastor-slug>`
- `pte review-ground-truth <youtube-video-id>`
- `pte review-next-ground-truth --reviewer "Reviewer Name"`
- `pte validate-fixtures [fixture-directory]`
- `pte evaluate [--fixture-dir PATH] [--results-dir PATH] [--base-dir PATH]`
- `./venv-shell`

## Church Database Import

Import complete pastor/channel pairs directly from the local
`church-youtube-finder` database. The source database is opened read-only. PTE
stores a namespaced church key and imported-record fingerprint so later runs can
report new, unchanged, reused, or conflicting records. Import eligibility
requires a resolved `youtube_channel_key`; immutable channel keys—not handles or
URL spellings—are used to match existing PTE sources.

Preview an import:

```bash
pte import-church-db \
  /Users/briancummings/Documents/church-youtube-finder/churches.db \
  --dry-run \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Apply it by removing `--dry-run`, then acquire the six newest videos from every
source captured by that provider:

```bash
pte sync-imported-sources \
  --latest 6 \
  --all-audio \
  --download-jobs 2 \
  --jobs 2 \
  --extract \
  --archive-sources \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

By default, synchronization fetches captions and downloads audio for local ASR
only when captions are unavailable. Add `--all-audio` to acquire and transcribe
audio for every eligible video. Add `--extract` when the synchronized recordings
should immediately become sermon-fixture candidates. `--archive-sources` requires
`--extract` and an archive destination previously configured with `pte media
archive-sources --archive-root PATH`. Synchronization uses separate download /
normalization and transcription worker pools, then queues verified source audio
to one background NAS archive worker while processing continues. Before
admitting each transcription batch, PTE reserves disk from the discovered video
durations and requires projected local
free space to remain at least 20%; it waits for pending archival when that can
restore the reserve. Source audio is archive-safe when its normalized copy covers
the isolated sermon or independently matches the complete recording. The
normalized processing copy remains local, and archive failures remain retryable.
If a separate `pte media archive-sources` process already holds the archive lock,
the sync archive worker stays pending and retries until that process finishes;
download admission can continue while the disk reservation remains safe.
The `--latest` window is preserved through captions, local ASR, extraction,
registration, and archival; older videos already attached to a reused source are
not pulled into downstream work merely because `--all-audio` is enabled.
Imported assignment changes are reported as conflicts and are never silently
overwritten.

## Ground-Truth Review

Create a detector-assisted draft and review it against the video and timestamped
transcript before writing a manually approved fixture:

```bash
pte review-ground-truth l6mZEQvArkE --reviewer "Brian Cummings" --open-video
pte sync-source-families evaluation/source-families.json --base-dir /path/to/app-data
pte review-next-ground-truth --reviewer "Brian Cummings" --base-dir /path/to/app-data
pte validate-fixtures evaluation/fixtures
pte validate-source-families evaluation/source-families.json --base-dir /path/to/app-data
pte evaluate --base-dir /path/to/app-data
```

Unreviewed proposals are stored under `evaluation/drafts/`. Only explicitly
approved fixtures are written under `evaluation/fixtures/`; evaluator code must
never treat drafts as ground truth.

`review-next-ground-truth` deterministically rotates through boundary-risk,
no-candidate, and standard-candidate proposal strata. It excludes videos that
already have a draft or fixture, keeps whole source families in their frozen
evaluation partition, and favors underrepresented source families, recording
conditions, and objective diagnostic signals. Signals include rule/LLM
disagreement, rescue or fallback activation, continuity expansion,
fragmentation, close candidate scores, recording-edge proximity, low transcript
coverage, and extreme caption deduplication. Proposal strata and signals are
selection hints only: they never assign `sermon`, `no_sermon`, or approved
boundaries. Selection provenance is retained in the draft and approved fixture,
including when an interrupted automatic draft is resumed manually. Add new
sources with `sync-source-families` before they can be nominated. Existing
family assignments are preserved; new channel identities receive deterministic
family-level partitions.

## Reclassification and Regression Evaluation

Use `reclassify` to rerun adaptive sermon detection against existing timestamped
transcript segments. It does not download or transcribe the video again. The
`--video-id` value is the numeric database ID shown by `pte video list`, not the
YouTube video ID.

```bash
./venv-shell
export PTE_LLM_MODEL=gemma3:4b

pte doctor --base-dir /path/to/app-data
pte video list --limit 250 --base-dir /path/to/app-data
pte reclassify --video-id 46 --force --base-dir /path/to/app-data
pte reclassify --source-id 3 --force --base-dir /path/to/app-data
```

Use `--force` while testing algorithm, prompt, or adjudication changes. Raw LLM
responses are cached separately from ranking and adjudication, so an unchanged
second pass should normally report zero cache misses.

Production classification is a cascade: `gemma3:4b` localizes sermon-like
blocks, then `gemma3:12b` verifies only recordings that would otherwise require
review. Explicit Bible Class, Sabbath School, graduation, concert, technical
test, and named student-program titles can be resolved by a versioned
high-precision title policy without calling 12B. Invalid or contradictory
verifier evidence remains unresolved, and guest-speaker safeguards still take
precedence.

Run the frozen regression set after reclassifying its videos:

```bash
pte reclassify \
  --fixture-dir evaluation/fixtures \
  --force \
  --jobs 2 \
  --recording-verifier-model gemma3:12b \
  --recording-verifier-cache-root evaluation/recording-verifier/cache \
  --base-dir /path/to/app-data

pte validate-fixtures evaluation/fixtures
pte evaluate --base-dir /path/to/app-data
```

After the fixture evaluation is accepted, propagate the classifier to every
video with reusable extraction segments. On macOS, `caffeinate` keeps the run
active while two videos are classified concurrently:

```bash
caffeinate pte reclassify \
  --all \
  --force \
  --jobs 2 \
  --recording-verifier-model gemma3:12b \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Corpus-wide reclassification skips videos without a readable `proposed.json`
containing timestamped segments. Completed inference remains resumable through
the per-video raw inference and recording-verifier caches. Each video persists
`recording-verification-v1.json` alongside `llm-classification-v1.json`, and the
final summary reports reclassified, reused, skipped, and failed counts.

Evaluation creates `results.json`, a human-readable `report.md`, and relevant
failure-analysis files under `evaluation/results/<timestamp>/`. Metrics are
computed against original transcript segments rather than timestamp overlap
alone. The report also replays persisted confidence evidence under the current,
no-rule-overlap, and soft-rule-overlap policies without changing production
artifacts. Never promote generated drafts or detector boundaries to ground truth;
only manually approved files under `evaluation/fixtures/` are authoritative.

For the current local data path, frozen fixture list, accepted benchmark, and
exact comparison gates, see `docs/HANDOFF.md`.

Run the repository tests with the standard-library runner:

```bash
.venv/bin/python -m unittest discover -s tests -q
```

## Offline Interaction Diagnostics

Compare models on fixed, deduplicated excerpts from the Sabbath School, normal-sermon,
and multi-speaker sermon sentinels without changing database records or production
extraction artifacts:

```bash
pte diagnose-interaction \
  --model gemma3:4b \
  --model gemma3:12b \
  --base-dir /path/to/app-data
```

The constrained 12B diagnostic may require a longer request timeout:

```bash
PTE_LLM_TIMEOUT_SECONDS=180 pte diagnose-interaction \
  --model gemma3:12b \
  --base-dir /path/to/app-data
```

Raw structured responses, stable current-excerpt evidence line IDs, validation failures, and a Markdown
comparison report are written under `evaluation/interaction-diagnostics/`. Inference
is cached by model digest, prompt, schema, and deduplicated excerpt.

## Optional Local LLM Filtering

The normal extraction path defaults to `--classifier auto`. Ollama is enabled by
default with the production Gemma 3 4B model, and auto safely falls back to
rules when Ollama is unavailable. No enable flag is required for `pte extract`,
`pte review`, or `pte run`:

```bash
export PTE_LLM_MODEL=gemma3:4b
pte doctor
pte extract --force
pte review sample-church
pte run 'https://www.youtube.com/watch?v=abc123' --pastor sample-church
```

Classifier modes:

- `--classifier auto` tries Ollama by default and safely falls back to rules.
- `--classifier rules` never calls a local LLM.
- `--classifier llm` requires Ollama and fails visibly if classification fails.

Set `PTE_LLM_ENABLED=0` only when you want `auto` to skip Ollama globally. For
an individual command, prefer the explicit `--classifier rules` opt-out.

`pte extract`, review preparation, and the extraction stage inside `pte run`
all call the same adaptive extraction batch service. Review preparation never
silently switches to rules-only extraction.

## End-to-End CLI

Run one source and produce both `review.md` and `review.json` under the pastor's
exports directory:

```bash
export PTE_LLM_MODEL=gemma3:4b
pte run 'https://www.youtube.com/watch?v=abc123' \
  --pastor sample-church \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Run all configured sources with the same extraction and review behavior:

```bash
pte run --all \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

To stop after extraction without creating or refreshing review exports:

```bash
pte run 'https://www.youtube.com/watch?v=abc123' \
  --pastor sample-church \
  --skip-review \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The classifier labels contextual transcript blocks but never rewrites their
text. Results and raw structured responses are saved in each video's
`extracted/llm-classification-v1.json` artifact. Extraction also persists a
final disposition: `accepted_sermon`, `review_required`, `rejected_no_sermon`,
or `rejected_ambiguous_speakers`. Diagnostic candidates remain auditable, but
rejected videos do not fall back to the full transcript in pastor review output.
Production confidence uses soft rule overlap: low rule/LLM agreement can reduce
an otherwise-high result to medium, but cannot force it to low by itself.
Uncertainty, empty retention, and central-consistency failures remain safety caps.
Fine-label continuity that expands for more than ten minutes to a recording edge
also requires review instead of producing an automatic high-confidence acceptance.

## Pastor Identity Shadow Mode

Pastor recognition is being added as an independent identity-assurance layer.
The current increment records source metadata, a context-only evidence ledger,
and a `profile_unavailable` identity assessment under each video's `identity/`
directory. These assessments run in shadow mode: they show that identity would
require review, but do not change existing extraction or review exports.

Source-to-pastor assignment is explicitly recorded as an expectation, not proof
that the assigned pastor delivered the sermon. Manual sermon-window overrides
apply only to content boundaries and do not suppress guest-speaker concerns.

Automatic speaker-pair nomination is limited to current, accepted sermon
observations. `pte identity review-next-speaker-pair` requires a readable latest
extraction whose top-level disposition is `accepted_sermon`, an observation
from that extraction with boundaries matching its current sermon window,
usable diagnostic spans, and verified normalized media. Review-required,
rejected, malformed, and stale observations are excluded conservatively.
Explicit `review-speaker-pair` requests remain a manual workflow.

Backfill shadow identity artifacts for existing extractions without invoking
classification or rewriting sermon artifacts:

```bash
pte identity backfill --base-dir /path/to/app-data
```

The grounded-attribution shadow pass extracts only exact names from title,
description, chapter, introduction, and handoff evidence. Metadata observations
retain their artifact hash, source kind, field path, and exact excerpt. Spoken
observations retain a stable transcript segment line ID, timestamp range, and
exact excerpt. Repeated credits for the same person share one correlation group
and count as one independent attribution source.

Attribution outcomes are diagnostic only: they do not promote the identity
state beyond `profile_unavailable`, alter the coordinator's effective status,
or use sermon topic, style, or theology as evidence.

The neutral registry separates speaker observations, disposable future cluster
hypotheses, curated profiles, and grounded name claims. Configured pastors are
created as named but unprofiled query identities. Sermon observations and names
are never attached to profiles automatically; membership, naming, and merge
redirects require append-only review events. No acoustic recognition or
clustering backend is active.

## Commands

- `pte init`
- `pte add <url>`
- `pte status`
- `pte doctor`
- `pte discover`
- `pte fetch`
- `pte transcribe`
- `pte extract`
- `pte reclassify --video-id <database-id>`
- `pte reclassify --source-id <source-id>`
- `pte review <pastor-slug>`
- `pte review-ground-truth <youtube-video-id>`
- `pte validate-fixtures evaluation/fixtures`
- `pte evaluate --base-dir <app-data>`
- `pte diagnose-interaction --model <ollama-model>`
- `pte run <url> --pastor <pastor-slug>`
- `pte run --all`
- `pte run <url> --pastor <pastor-slug> --skip-review`
- `pte video exclude <video-id>`
- `pte video unexclude <youtube-video-id>`
- `pte video excluded`
- `pte pastor add <slug> <display-name>`
- `pte pastor list`

## Planning Docs

- `docs/V1_SPEC.md`
- `docs/HANDOFF.md`
- `evaluation/speaker-pairs/README.md` for the offline, abstention-first acoustic pair experiment
- `docs/MEDIA_FOUNDATION.md` for transcript-independent audio acquisition and migration

Archive comparison-independent source audio to a recorded NAS destination:

```bash
pte media archive-sources \
  --archive-root /Volumes/home/SermonExtractorAudio \
  --base-dir /Users/briancummings/Documents/PastorSearchData

pte media archive-status \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

If the NAS is unavailable, PTE records the failed attempt and retries pending
entries the next time `archive-sources` is run.
