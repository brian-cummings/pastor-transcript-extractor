# V1 Specification

## Goal

Build a local Python CLI that extracts pastor-only sermon transcripts from YouTube sources and exports approved Markdown files.

## Current Implementation Baseline

Already scaffolded:

- package structure
- CLI entrypoint
- SQLite initialization
- source type detection
- `init`, `add`, `status`, `doctor`, `discover`, `fetch`, `transcribe`, `extract`, `review`, `export`, and `run` commands
- transcript segmentation and heuristic extraction
- review and export commands
- `pastor add` / `pastor list`
- caption fetching

Verified local transcription dependency:

- `whisper.cpp` binary at `/Users/briancummings/code/whisper.cpp/build/bin/whisper-cli`
- model at `/Users/briancummings/code/whisper.cpp/models/ggml-medium.en.bin`

## Primary Success Criteria

- Can queue a YouTube video, playlist, or channel
- Can discover individual videos
- Can acquire transcript text from captions or local ASR
- Can produce a proposed pastor-only transcript using chunk labeling
- Can support manual review before export
- Can export one Markdown file per approved sermon

## Constraints

- Must run locally
- Must not require paid cloud AI APIs
- Must preserve raw transcript artifacts
- Must support offline use once dependencies and models are installed
- Must handle a few hundred sermons without becoming operationally fragile

## Processing States

- `queued`
- `discovered`
- `transcript_fetched`
- `transcribed_local`
- `extracted`
- `needs_review`
- `approved`
- `exported`
- `failed`

## Next Implementation Sequence

The core pipeline is implemented. Remaining work is workflow refinement and hardening.

### 1. Workflow Refinement
Harden the current pipeline by improving:

- rerun behavior
- caption source selection
- review editor integration
- export naming/frontmatter

## Command Behavior

### `init`
Initializes app directories and SQLite.

### `add <url>`
Adds a source record.

Required flags:

- `--pastor <slug>`

Accepted source types:

- video URL
- playlist URL
- channel URL

Output:

- source id
- linked pastor
- normalized source type
- queued status

### `status`
Shows summary counts and queued sources.

### `doctor`
Validates:

- configured `whisper.cpp` binary
- configured model path
- `yt-dlp` availability
- `ffmpeg` availability
- app data directory access

### `discover`
Target behavior:

- direct video URLs become one video item
- playlist URLs expand to all items
- channel URLs expand to uploads or filtered recent items
- duplicate video ids are ignored
- discovered videos are persisted with `discovered` status

### `transcribe --missing-only`
Target behavior:

- download or use prepared audio
- run local `whisper.cpp`
- persist transcript artifacts
- set status to `transcribed_local`

### `extract`
Target behavior:

- chunk transcript into reviewable segments
- assign provisional labels
- merge likely sermon segments
- store extraction result separately from raw transcript
- mark item `needs_review`

### `review <video-id>`
Required capabilities:

- show metadata
- show chunk list with timestamps, labels, and preview text
- allow keep/drop operations
- allow manual boundary correction
- allow opening cleaned text in `$EDITOR`
- approve result when user confirms

### `export [video-id]`
Rules:

- only exports approved items
- one file per sermon
- deterministic file naming
- preserve metadata header/frontmatter

### `run <url>`
Target end state:

- `add`
- `discover`
- `fetch` or direct transcription fallback
- `extract`

Should stop before approval/export.

## Proposed Modules

### `cli`
Typer entrypoints and command wiring.

### `config`
Application config, paths, tool discovery, defaults.

### `storage`
SQLite schema management, repositories, artifact path helpers.

### `sources`
URL classification, source normalization, YouTube discovery.

### `media`
`yt-dlp` and `ffmpeg` subprocess wrappers.

### `transcription`
Transcript acquisition backends.

Initial backends:

- captions fetch backend
- `whisper.cpp` backend

### `segmentation`
Transcript chunking and normalization.

### `extraction`
Heuristic label assignment and sermon transcript assembly.

### `review`
Terminal review workflow and editor integration.

### `export`
Markdown writer.

## Data Model

### `Source`

- `id`
- `pastor_id`
- `url`
- `source_type` (`video`, `playlist`, `channel`)
- `added_at`
- `notes`

### `Video`

- `id`
- `youtube_video_id`
- `source_id`
- `pastor_id`
- `title`
- `url`
- `channel_name`
- `published_at`
- `duration_seconds`
- `status`
- `failure_reason`

### `TranscriptArtifact`

- `id`
- `video_id`
- `source_kind` (`captions`, `local_asr`)
- `raw_json_path`
- `raw_text_path`
- `audio_path`
- `created_at`

### `TranscriptSegment`

- `id`
- `video_id`
- `artifact_id`
- `start_seconds`
- `end_seconds`
- `text`
- `speaker_hint` nullable
- `label` (`unknown`, `sermon`, `music`, `announcements`, `prayer`, `reading`, `other`)
- `confidence` nullable

### `ExtractionResult`

- `id`
- `video_id`
- `version`
- `proposed_text_path`
- `notes`
- `created_at`

### `ReviewResult`

- `id`
- `video_id`
- `extraction_result_id`
- `approved_text_path`
- `reviewed_at`
- `review_notes`

## Artifact Layout

Artifacts should remain separable by concern:

- database
- raw source metadata
- downloaded media
- raw transcript JSON/text
- extracted transcript
- approved transcript
- logs
