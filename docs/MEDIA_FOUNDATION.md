# Media Foundation

Audio is a first-class artifact independent of transcript provenance. Captions
can avoid local ASR, but every isolated sermon ultimately requires verified
audio before speaker identity can be assessed.

## Conditional workflow

The workflow is not a single linear pipeline:

```text
captions available:   captions → isolate sermon → ensure audio → acoustic work
captions unavailable: ensure audio → local ASR → isolate sermon → acoustic work
```

This increment implements the media foundation and explicit shadow-operated
audio acquisition. It does not add acquisition to the latency-sensitive `run`
command, qualify acoustic observations, compare registry profiles, or alter
content dispositions.

## Persistent concepts

`media_artifacts` contains immutable source and normalized audio records. Each
record stores:

- video and optional parent-media relationship;
- `source_audio` or `normalized_audio` kind;
- original-download, derived, or reconstructed provenance;
- path, SHA-256, byte size, duration, format, sample rate, and channels;
- acquisition tool and version;
- content-derived input fingerprint and immutable manifest.

Newly acquired native compressed source audio and normalized mono 16 kHz audio
use content-addressed names. Existing local-ASR files are
not moved or rewritten. Their records and manifests explicitly use
`reconstructed_existing` and
`reconstructed_without_original_tool_snapshot`; they are not represented as
equivalent to an original yt-dlp snapshot.

`media_acquisition_attempts` is an append-only, idempotent record of the request
outcome:

- `verified`
- `unavailable`
- `failed`

Media unavailability is not an identity state. Downstream identity assessment
will represent its consequence as insufficient evidence with a media reason.
It never changes sermon content artifacts.

## Commands

Register historical audio without moving files:

```bash
pte media backfill \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Audit every valid isolated sermon without downloading anything:

```bash
pte media audit \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Ensure one sermon has verified normalized audio:

```bash
pte media ensure-audio \
  --video-id DATABASE_VIDEO_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Explicitly process every eligible sermon, optionally in bounded batches:

```bash
pte media ensure-audio \
  --all-eligible \
  --limit 10 \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The ensure service first migrates and verifies existing audio. It downloads
only when no valid normalized artifact is available, and it never invokes
Whisper or creates a transcript artifact.

## Replay guarantees

- Existing verified content is reused without redownload.
- Integrity verification includes SHA-256, byte size, and coverage through the
  isolated sermon end; truncated historical files remain unresolved.
- Replaying migration or acquisition creates no duplicate rows.
- Existing audio bytes and modification times remain unchanged.
- An identical source or normalized file resolves to the same fingerprint.
- Changed content creates a new immutable artifact rather than overwriting the
  prior record.
- Normalization provenance includes the pinned local ffmpeg version.
- `proposed.json`, transcript artifacts, and sermon dispositions are untouched.
