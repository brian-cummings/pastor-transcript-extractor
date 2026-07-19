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

## Source audio archive

Original compressed downloads and historical `downloaded.wav` files are not
inputs to acoustic comparison after a verified normalized artifact exists. PTE
can archive those eligible source artifacts while retaining normalized audio
locally:

```bash
pte media archive-sources \
  --archive-root /Volumes/home/SermonExtractorAudio \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The first invocation records the archive root as PTE's active destination.
Later invocations may omit `--archive-root`; they reuse the persisted path and
retry pending or failed entries. Inspect state without moving files with:

```bash
pte media archive-status \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Every eligible source artifact receives a persisted entry containing its local
path, archive path, SHA-256, byte size, and current status. Attempts are
append-only. If the destination is not mounted, PTE records
`destination_unavailable`, leaves the source untouched, and keeps the entry
pending for the next invocation.

Archival copies to a temporary file on the destination, verifies byte size and
SHA-256, atomically materializes the final archive path, and then replaces the
local source with a symlink. Normalized audio is never selected by this command.
The symlink preserves existing media-artifact and transcript provenance paths
when the NAS is mounted.

Before scanning eligibility or moving bytes, the command acquires an exclusive
archive lock and reports the configured destination, mount accessibility, a
create/fsync/delete write probe, persisted entry counts, free capacity versus
required bytes, and leftover PTE partial or local staging files. A failed mount,
write, or capacity check leaves sources untouched and records retryable outcomes.

## Replay guarantees

- Existing verified content is reused without redownload.
- Integrity verification includes SHA-256 and byte size. Coverage requires the
  artifact to reach the isolated sermon end, or to closely match the complete
  video duration when transcript timing extends past the real media endpoint;
  materially truncated files remain unresolved.
- Replaying migration or acquisition creates no duplicate rows.
- Existing audio bytes and modification times remain unchanged.
- An identical source or normalized file resolves to the same fingerprint.
- Changed content creates a new immutable artifact rather than overwriting the
  prior record.
- Normalization provenance includes the pinned local ffmpeg version.
- `proposed.json`, transcript artifacts, and sermon dispositions are untouched.
- Source archival never selects normalized comparison audio.
- A source is eligible only after its video has a verified normalized artifact.
