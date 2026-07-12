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

- `pte run <url> --pastor <slug>`
- `pte review <pastor-slug>`
- `pte review-ground-truth <youtube-video-id>`
- `pte validate-fixtures [fixture-directory]`
- `./venv-shell`

## Ground-Truth Review

Create a detector-assisted draft and review it against the video and timestamped
transcript before writing a manually approved fixture:

```bash
pte review-ground-truth l6mZEQvArkE --reviewer "Brian Cummings" --open-video
pte validate-fixtures evaluation/fixtures
```

Unreviewed proposals are stored under `evaluation/drafts/`. Only explicitly
approved fixtures are written under `evaluation/fixtures/`; evaluator code must
never treat drafts as ground truth.

## Optional Local LLM Filtering

Extraction remains rule-based by default. To let `pte extract` use a locally
running Ollama model when available:

```bash
export PTE_LLM_ENABLED=1
export PTE_LLM_MODEL=gemma3:4b
pte doctor
pte extract --force
```

Classifier modes:

- `--classifier auto` uses Ollama when enabled and safely falls back to rules.
- `--classifier rules` never calls a local LLM.
- `--classifier llm` requires Ollama and fails visibly if classification fails.

The classifier labels contextual transcript blocks but never rewrites their
text. Results and raw structured responses are saved in each video's
`extracted/llm-classification-v1.json` artifact. Medium- and low-confidence
results are marked in the pastor review output.

## Commands

- `pte init`
- `pte add <url>`
- `pte status`
- `pte doctor`
- `pte discover`
- `pte fetch`
- `pte transcribe`
- `pte extract`
- `pte review <pastor-slug>`
- `pte video exclude <video-id>`
- `pte video unexclude <youtube-video-id>`
- `pte video excluded`
- `pte pastor add <slug> <display-name>`
- `pte pastor list`

## Planning Docs

- `docs/V1_SPEC.md`
- `docs/HANDOFF.md`
