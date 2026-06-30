# Handoff Notes

## Current State

The workspace now has the first executable scaffold in place.

Implemented:

- Python package scaffold
- CLI entrypoint
- app data directory initialization
- SQLite initialization
- source persistence
- pastor persistence
- pastor-aware artifact path helpers
- YouTube source type detection
- `init`, `add`, `status`, `doctor`, `discover`, `fetch`, `transcribe`, and `run` command implementation
- `extract` command implementation
- `review` and `export` command implementation
- `pastor add` and `pastor list`
- `python -m pastor_transcript_extractor` entrypoint
- transcript artifact persistence
- caption fetching
- audio download/prep plus `whisper.cpp` runner

## Important Environment Constraint

The default app-data location under `~/.pastor-transcript-extractor` is not writable inside this sandbox. Use `--base-dir` for local validation runs here.

## Recommended Next Coding Pass

### Milestone 6: Workflow Refinement
1. Improve review UX and editor integration.
2. Tighten export naming and frontmatter once real sermon batches land.
3. Decide whether `run` should prefer captions-only mode or keep the current fetch-plus-ASR behavior.

Required config values:

- `whisper_cpp_bin`
- `whisper_model_path`
- `ffmpeg_bin`
- `yt_dlp_bin`

Recommended defaults:

- `whisper_cpp_bin = /Users/briancummings/code/whisper.cpp/build/bin/whisper-cli`
- `whisper_model_path = /Users/briancummings/code/whisper.cpp/models/ggml-medium.en.bin`
- `ffmpeg_bin = ffmpeg`
- `yt_dlp_bin = yt-dlp`

## Current Smoke-Test Notes

- `ffmpeg` resolves on this machine.
- `yt-dlp` is installed in the project venv.
- `pte doctor --base-dir .../.appdata` reports local tool status cleanly.
- `python -m pastor_transcript_extractor --help` works again.
- `pte fetch --help` is available.
- `pte transcribe --help` is available.
- `pte extract --help` is available.
- `pte review --help` is available.
- `pte export --help` is available.

## Open Decisions Left For Implementation

- config file format versus env-only configuration
- exact SQLite repository pattern
