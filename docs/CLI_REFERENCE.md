# PTE CLI Reference

This file is generated from the registered CLI and its help metadata.
Regenerate it with `pte docs cli --output docs/CLI_REFERENCE.md`.

# `pte`

Pastor Transcript Extractor CLI

## Usage

```console
pte [OPTIONS] COMMAND [ARGS]...
```

## Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--install-completion` | Install completion for the current shell. | no | — |
| `--show-completion` | Show completion for the current shell, to copy it or customize the installation. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte init`

Initialize the app data directory and SQLite database.

### Usage

```console
pte init [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte add`

Add a YouTube video, playlist, or channel source for a pastor.

### Usage

```console
pte add [OPTIONS] URL
```

### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `URL` | YouTube video, playlist, or channel URL.  [required] | yes | — |

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--pastor TEXT` | Pastor slug to associate with this source.  [required] | yes | — |
| `--notes TEXT` | Optional notes for this source. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte status`

Show database counts and queued sources.

### Usage

```console
pte status [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte source-processing-report`

Write read-only per-source processing reports as Markdown and JSON.

### Usage

```console
pte source-processing-report [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--database PATH` | Explicit application database path; defaults to the configured app database. | no | — |
| `--markdown PATH` | Markdown report output path.  [default: source_processing_report.md] | no | source_processing_report.md |
| `--json PATH` | JSON report output path.  [default: source_processing_report.json] | no | source_processing_report.json |
| `--base-dir PATH` | Override app data directory when --database is not supplied. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte import-church-db`

Import complete pastor/channel pairs from church-youtube-finder with stable provenance.

### Usage

```console
pte import-church-db [OPTIONS] CHURCH_DATABASE
```

### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `CHURCH_DATABASE` | Path to the church-youtube-finder SQLite database.  [required] | yes | — |

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--dry-run` | Report changes without importing records. | no | False |
| `--show-all / --no-show-all` | Show unchanged records in addition to changes and conflicts.  [default: no-show-all] | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte migrate-evaluation-storage`

Safely move generated evaluation artifacts into application data.

### Usage

```console
pte migrate-evaluation-storage [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--apply / --dry-run` | Apply the migration; dry-run is the default.  [default: dry-run] | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--repo-root PATH` | Repository containing legacy evaluation artifacts.  [default: /Users/briancummings/code/pastor-transcript-extractor] | no | /Users/briancummings/code/pastor-transcript-extractor |
| `--verify` | Verify destination sizes after every move and report remaining legacy files. | no | False |
| `--manifest PATH` | Manifest destination; defaults beneath the configured evaluation root. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte diagnose`

Build a read-only sermon-isolation trace and human diagnostic views.

### Usage

```console
pte diagnose [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--video-id INTEGER` | Database video id to diagnose.  [required] | yes | — |
| `--fixture PATH` | Optional reviewed fixture JSON for actual recall and contamination measurements. | no | — |
| `--output-dir PATH` | Output directory; defaults to the video's immutable artifact namespace. | no | — |
| `--identity-feedback-root PATH` | Existing identity shadow artifacts containing association outcomes and sermon-edge advisories. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte diagnose-system`

Diagnose all existing extraction outcomes without reclassifying the corpus.

### Usage

```console
pte diagnose-system [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--fixture-dir PATH` | Reviewed fixture directory to diagnose from existing artifacts.  [default: evaluation/fixtures] | no | evaluation/fixtures |
| `--output-root PATH` | Generated systemic diagnostic root. | no | — |
| `--identity-feedback-root PATH` | Existing identity shadow artifacts containing association outcomes and sermon-edge advisories. | no | — |
| `--speaker-evidence-root PATH` | Reviewed speaker evidence used to reconstruct current profile topology.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--all-existing / --fixtures-only` | Include every latest extraction artifact; matching fixtures add reviewed quality evidence.  [default: all-existing] | no | True |
| `--verbose` | Embed complete traces and write per-video diagnostic files. The default systemic JSON keeps only comparison-ready trace projections. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte diagnose-compare`

Compare two existing systemic diagnostic reports without reclassifying.

### Usage

```console
pte diagnose-compare [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--before PATH` | Earlier system-diagnostics.json.  [required] | yes | — |
| `--after PATH` | Later system-diagnostics.json.  [required] | yes | — |
| `--output-root PATH` | Generated comparison root. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte diagnose-interaction`

Compare local models on deduplicated interaction evidence without changing production artifacts.

### Usage

```console
pte diagnose-interaction [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--model TEXT` | Ollama model to compare; repeat for multiple models. | no | — |
| `--output-root PATH` | Generated diagnostic result root. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte diagnose-recording-verifier`

Test one recording-level sermon decision on a non-held-out fixture partition.

### Usage

```console
pte diagnose-recording-verifier [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--model TEXT` | Ollama model to test.  [default: gemma3:12b] | no | gemma3:12b |
| `--partition TEXT` | Fixture partition to test. Use development while tuning.  [default: development] | no | development |
| `--confirm-frozen-policy` | Required to unseal the held-out partition for final validation. | no | False |
| `--fixture-dir PATH` | Approved fixture directory.  [default: evaluation/fixtures] | no | evaluation/fixtures |
| `--output-root PATH` | Generated diagnostic result root. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte doctor`

Validate local tool paths and app data directories.

### Usage

```console
pte doctor [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte validate-fixtures`

Validate manually reviewed sermon evaluation fixtures.

### Usage

```console
pte validate-fixtures [OPTIONS] [FIXTURE_DIR]
```

### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `[FIXTURE_DIR]` | Directory containing manually reviewed fixture JSON files.  [default: evaluation/fixtures] | no | evaluation/fixtures |

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

## `pte validate-baseline`

Validate a frozen sermon-localization baseline and its exact fixture corpus.

### Usage

```console
pte validate-baseline [OPTIONS] [MANIFEST]
```

### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `[MANIFEST]` | Frozen localization baseline manifest.  [default: evaluation/baselines/sermon-localization-v1.json] | no | evaluation/baselines/sermon-localization-v1.json |

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--fixture-dir PATH` | Directory containing the baseline fixture corpus.  [default: evaluation/fixtures] | no | evaluation/fixtures |
| `--help` | Show this message and exit. | no | — |

## `pte validate-source-families`

Validate source-family coverage and family-level evaluation partitions.

### Usage

```console
pte validate-source-families [OPTIONS] [REGISTRY_PATH]
```

### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `[REGISTRY_PATH]` | Source-family registry JSON.  [default: evaluation/source-families.json] | no | evaluation/source-families.json |

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--fixture-dir PATH` | Fixture corpus whose source-family coverage should be checked.  [default: evaluation/fixtures] | no | evaluation/fixtures |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte sync-source-families`

Deterministically register new database sources for evaluation partitioning.

### Usage

```console
pte sync-source-families [OPTIONS] [REGISTRY_PATH]
```

### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `[REGISTRY_PATH]` | Source-family registry JSON to extend without changing existing assignments.  [default: evaluation/source-families.json] | no | evaluation/source-families.json |

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--dry-run` | Report additions without writing. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte evaluate`

Evaluate existing production classification artifacts against frozen fixtures.

### Usage

```console
pte evaluate [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--fixture-dir PATH` | Approved fixture directory.  [default: evaluation/fixtures] | no | evaluation/fixtures |
| `--results-dir PATH` | Generated result root. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte extract`

Chunk transcript artifacts into reviewable segments and proposed Markdown.

### Usage

```console
pte extract [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--missing-only` | Only extract videos without a proposed Markdown artifact. | no | False |
| `--force` | Rebuild extraction artifacts even when a video is already marked extracted or exported. | no | False |
| `--source-id INTEGER` | Only extract videos from a specific source id. | no | — |
| `--classifier TEXT` | Content classifier: auto, rules, llm, or typesafe.  [default: typesafe] | no | typesafe |
| `--llm-model TEXT` | Override the configured local Ollama model. | no | — |
| `--recording-verifier-backend TEXT` | Ambiguous-recording verifier: ollama, typesafe, or none.  [default: typesafe] | no | typesafe |
| `--recording-verifier-model TEXT` | Verifier model override; TypeSafe defaults to jev-1.13.0. | no | — |
| `--jobs INTEGER RANGE` | Concurrent video extraction jobs.  [default: 2; x>=1] | no | 2 |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte apply-fixture-correction`

Apply one approved continuous sermon fixture to its production window and speaker observation.

### Usage

```console
pte apply-fixture-correction [OPTIONS] YOUTUBE_VIDEO_ID
```

### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `YOUTUBE_VIDEO_ID` | YouTube video ID whose approved fixture supplies the correction.  [required] | yes | — |

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--fixture-dir PATH` | Directory containing <youtube-video-id>.json fixtures.  [default: evaluation/fixtures] | no | evaluation/fixtures |
| `--llm-model TEXT` | Override the configured local Ollama classification model. | no | — |
| `--recording-verifier-backend TEXT` | Ambiguous-recording verifier: ollama, typesafe, or none.  [default: typesafe] | no | typesafe |
| `--recording-verifier-model TEXT` | Verifier model override; TypeSafe defaults to jev-1.13.0. | no | — |
| `--inference-cache-root PATH` | Use a separate per-video inference cache root. | no | — |
| `--recording-verifier-cache-root PATH` | Use a shared recording-verifier cache root. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte run`

Run intake, extraction, audio assurance, source archival, and disposition-aware pastor review export.

### Usage

```console
pte run [OPTIONS] [URL]
```

### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `[URL]` | YouTube video, playlist, or channel URL. | no | — |

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--pastor TEXT` | Pastor slug to associate with this source. | no | — |
| `--all` | Run the full workflow for every processing-enabled source. This does not remove the per-source discovery limit; use --all-videos for that. | no | False |
| `--source-id INTEGER` | Run one or more existing source ids; repeat this option for each source. | no | — |
| `--failed-only` | Reprocess only failed videos systemwide without rebuilding successful artifacts. | no | False |
| `--replace-existing` | Replace a matching source first. | no | False |
| `--limit INTEGER RANGE` | Videos per source; defaults to 26.  [default: 26; x>=1] | no | 26 |
| `--all-videos` | Process all discovered videos. | no | False |
| `--captions-only` | Do not run local transcription. | no | False |
| `--transcribe-missing / --no-transcribe-missing` | Only transcribe caption misses by default.  [default: transcribe-missing] | no | True |
| `--jobs INTEGER RANGE` | Concurrent transcription jobs.  [default: 2; x>=1] | no | 2 |
| `--classifier TEXT` | Content classifier: auto, rules, llm, or typesafe.  [default: typesafe] | no | typesafe |
| `--llm-model TEXT` | Override the configured local Ollama model. | no | — |
| `--recording-verifier-backend TEXT` | Ambiguous-recording verifier: ollama, typesafe, or none.  [default: typesafe] | no | typesafe |
| `--recording-verifier-model TEXT` | Verifier model override; TypeSafe defaults to jev-1.13.0. | no | — |
| `--skip-review` | Skip writing review exports after extraction and media maintenance. | no | False |
| `--identity, --run-identity` | After content processing, run the guarded automatic identity workflow and synchronize boundary feedback before review export. | no | False |
| `--stage-audio-only, --stage-offline-inputs` | Discover or select the requested scope, download immutable source audio and available captions, write a resume manifest, and stop. | no | False |
| `--skip-discovery` | With --stage-offline-inputs, select eligible videos already in the catalog without contacting source feeds. | no | False |
| `--resume-stage FILE` | Process exactly the videos in a verified audio-stage manifest without network downloads. | no | — |
| `--acquire-captions` | With --resume-stage, fetch available captions for the verified manifest scope before offline-only local transcription. | no | False |
| `--cookies-from-browser TEXT` | Use an explicit browser profile for authenticated YouTube caption requests, for example chrome or 'chrome:Profile 1'. | no | — |
| `--cookies FILE` | Use an explicit Netscape-format cookie file for YouTube captions. | no | — |
| `--download-jobs INTEGER RANGE` | Concurrent source-audio downloads during --stage-audio-only.  [default: 2; x>=1] | no | 2 |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte reclassify`

Rerun classification using existing extraction segments.

### Usage

```console
pte reclassify [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--video-id INTEGER` | Reclassify one database video id. | no | — |
| `--source-id INTEGER` | Reclassify extracted videos from one source id. | no | — |
| `--review-required` | Reclassify videos whose latest extraction has a persisted review_required final disposition. | no | False |
| `--all` | Reclassify every database video with reusable extraction segments. | no | False |
| `--fixture-dir PATH` | Reclassify every approved fixture in this directory. | no | — |
| `--llm-model TEXT` | Override the configured local Ollama model. | no | — |
| `--recording-verifier-backend TEXT` | Ambiguous-recording verifier: ollama, typesafe, or none.  [default: typesafe] | no | typesafe |
| `--recording-verifier-model TEXT` | Verifier model override; TypeSafe defaults to jev-1.13.0. | no | — |
| `--jobs INTEGER RANGE` | Concurrent video classification jobs.  [default: 2; x>=1] | no | 2 |
| `--inference-cache-root PATH` | Use a separate per-video inference cache root, primarily for controlled comparisons. | no | — |
| `--recording-verifier-cache-root PATH` | Use a shared recording-verifier cache root. | no | — |
| `--force` | Rerun even when model and prompt versions match. | no | False |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte review`

Build or refresh the pastor-scoped Markdown review file from extracted videos.

### Usage

```console
pte review [OPTIONS] [PASTOR]
```

### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `[PASTOR]` | Pastor slug whose extracted videos should be assembled into review Markdown. | no | — |

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--all` | Build a combined review across all pastors. | no | False |
| `--edit` | Open the generated review Markdown in an editor. | no | False |
| `--classifier TEXT` | Content classifier for missing extractions: auto, rules, llm, or typesafe.  [default: typesafe] | no | typesafe |
| `--llm-model TEXT` | Override the configured local Ollama model. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte discover`

Discover videos from queued sources with yt-dlp metadata.

### Usage

```console
pte discover [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--limit INTEGER RANGE` | Only persist the first N discovered videos per source. Defaults to 26.  [default: 26; x>=1] | no | 26 |
| `--all` | Persist all discovered videos for each source. | no | False |
| `--source-id INTEGER` | Only discover videos for a specific source id. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte transcribe`

Download or prepare local ASR transcripts for discovered videos.

### Usage

```console
pte transcribe [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--missing-only` | Only transcribe videos without a local ASR artifact. | no | False |
| `--captions-missing-only / --all-eligible` | By default, only transcribe videos that do not already have a captions artifact. Use --all-eligible to transcribe all eligible videos.  [default: captions-missing-only] | no | True |
| `--jobs INTEGER RANGE` | Number of videos to transcribe concurrently. Defaults to 2.  [default: 2; x>=1] | no | 2 |
| `--source-id INTEGER` | Only transcribe videos from a specific source id. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte fetch`

Fetch YouTube captions when available and persist them as transcript artifacts.

### Usage

```console
pte fetch [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--source-id INTEGER` | Only fetch captions for videos from a specific source id. | no | — |
| `--cookies-from-browser TEXT` | Pass an explicit browser profile to yt-dlp for YouTube authentication. | no | — |
| `--cookies FILE` | Pass an explicit Netscape-format cookie file to yt-dlp. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte sync-imported-sources`

Acquire recent transcripts and fallback audio for provenance-imported sources.

### Usage

```console
pte sync-imported-sources [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--provider TEXT` | Import provider to synchronize.  [default: church-youtube-finder] | no | church-youtube-finder |
| `--latest INTEGER RANGE` | Newest videos to retain per imported source.  [default: 6; x>=1] | no | 6 |
| `--jobs INTEGER RANGE` | Concurrent local ASR and video extraction jobs.  [default: 2; x>=1] | no | 2 |
| `--download-jobs INTEGER RANGE` | Concurrent audio download and normalization workers.  [default: 2; x>=1] | no | 2 |
| `--all-audio` | Download and locally transcribe every eligible video, including captioned videos. | no | False |
| `--extract / --no-extract` | Also create missing sermon extraction proposals for synchronized sources.  [default: no-extract] | no | False |
| `--archive-sources / --no-archive-sources` | Register audio and queue verified source files to a background archive worker at the configured destination. Requires --extract.  [default: no-archive-sources] | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte review-ground-truth`

Review and approve sermon ground truth without treating detector output as truth.

### Usage

```console
pte review-ground-truth [OPTIONS] YOUTUBE_VIDEO_ID
```

### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `YOUTUBE_VIDEO_ID` | YouTube video ID already present in the database.  [required] | yes | — |

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--reviewer TEXT` | Human reviewer name or stable reviewer identifier. | no | — |
| `--evaluation-dir PATH` | Root containing drafts/ and fixtures/.  [default: evaluation] | no | evaluation |
| `--open-video` | Open the YouTube start link in a browser. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte review-next-ground-truth`

Deterministically nominate and review the next sermon-segment fixture.

### Usage

```console
pte review-next-ground-truth [OPTIONS]
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--reviewer TEXT` | Human reviewer name or stable identifier. | no | — |
| `--evaluation-dir PATH` | Root containing drafts/ and fixtures/.  [default: evaluation] | no | evaluation |
| `--source-family-registry PATH` | Frozen source-family registry used for partition-safe nomination.  [default: evaluation/source-families.json] | no | evaluation/source-families.json |
| `--open-video / --no-open-video` | Open the selected video.  [default: open-video] | no | True |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte pastor`

Manage pastors.

### Usage

```console
pte pastor [OPTIONS] COMMAND [ARGS]...
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte pastor add`

Create a pastor profile and folder namespace.

#### Usage

```console
pte pastor add [OPTIONS] SLUG DISPLAY_NAME
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `SLUG` | Slug for this pastor, used in folder paths.  [required] | yes | — |
| `DISPLAY_NAME` | Human-readable pastor name.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--notes TEXT` | Optional notes for this pastor. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte pastor list`

List configured pastors.

#### Usage

```console
pte pastor list [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte pastor affiliate`

Record a reviewed or manually grounded organization affiliation.

#### Usage

```console
pte pastor affiliate [OPTIONS] PASTOR ORGANIZATION
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `PASTOR` | Pastor slug.  [required] | yes | — |
| `ORGANIZATION` | Organization slug.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--role TEXT` | Role held at the organization.  [default: pastor] | no | pastor |
| `--from TEXT` | Inclusive start date in YYYY-MM-DD format. | no | — |
| `--to TEXT` | Exclusive end date in YYYY-MM-DD format. | no | — |
| `--status TEXT` | Temporal status: current, former, bounded, or unknown. | no | — |
| `--notes TEXT` | Optional affiliation notes. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte pastor affiliate-claim`

Explicitly attach an imported affiliation claim to a selected pastor.

#### Usage

```console
pte pastor affiliate-claim [OPTIONS] PASTOR CLAIM_ID
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `PASTOR` | Existing curated pastor slug.  [required] | yes | — |
| `CLAIM_ID` | Imported affiliation claim id.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--reviewer TEXT` | Reviewer name.  [required] | yes | — |
| `--reason TEXT` | Grounded reason for the attachment.  [required] | yes | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte organization`

Manage publishing organizations.

### Usage

```console
pte organization [OPTIONS] COMMAND [ARGS]...
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte organization add`

Create a publishing organization.

#### Usage

```console
pte organization add [OPTIONS] SLUG DISPLAY_NAME
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `SLUG` | Stable organization slug.  [required] | yes | — |
| `DISPLAY_NAME` | Human-readable organization name.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--type TEXT` | Organization type, such as church, conference, ministry, school, or network.  [default: church] | no | church |
| `--notes TEXT` | Optional organization notes. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte organization list`

List publishing organizations.

#### Usage

```console
pte organization list [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte organization review`

Build a publisher-scoped review without asserting speaker identity.

#### Usage

```console
pte organization review [OPTIONS] ORGANIZATION
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `ORGANIZATION` | Organization slug.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte organization claims`

List imported affiliation claims without linking people by name.

#### Usage

```console
pte organization claims [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--organization TEXT` | Only show claims for one organization slug. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte organization reject-affiliation-claim`

Append a reviewed rejection without creating or linking a person.

#### Usage

```console
pte organization reject-affiliation-claim [OPTIONS] CLAIM_ID
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `CLAIM_ID` | Affiliation claim id.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--reviewer TEXT` | Reviewer name.  [required] | yes | — |
| `--reason TEXT` | Reason for rejection.  [required] | yes | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte source`

Manage queued sources.

### Usage

```console
pte source [OPTIONS] COMMAND [ARGS]...
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte source add`

Add a source with an optional publisher and optional target pastor.

#### Usage

```console
pte source add [OPTIONS] URL
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `URL` | YouTube video, playlist, or channel URL.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--organization TEXT` | Publishing organization slug; omit when unknown. | no | — |
| `--target-pastor TEXT` | Optional pastor query target; this is not source ownership. | no | — |
| `--notes TEXT` | Optional source notes. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte source set-organization`

Attach or correct a source's current publishing organization.

#### Usage

```console
pte source set-organization [OPTIONS] SOURCE_ID ORGANIZATION
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `SOURCE_ID` | Source id to update.  [required] | yes | — |
| `ORGANIZATION` | Publishing organization slug.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--reason TEXT` | Audit reason for the association.  [default: Manual publisher correction] | no | Manual publisher correction |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte source clear-organization`

Mark a source's current publishing organization as unknown.

#### Usage

```console
pte source clear-organization [OPTIONS] SOURCE_ID
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `SOURCE_ID` | Source id to update.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--reason TEXT` | Audit reason for clearing the association.  [default: Manual publisher correction] | no | Manual publisher correction |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte source disable`

Exclude a source from all-source processing such as `pte run --all`.

#### Usage

```console
pte source disable [OPTIONS] SOURCE_ID
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `SOURCE_ID` | Source id to disable.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte source enable`

Include a source in all-source processing such as `pte run --all`.

#### Usage

```console
pte source enable [OPTIONS] SOURCE_ID
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `SOURCE_ID` | Source id to enable.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte source list`

List configured sources and downloaded recording counts.

#### Usage

```console
pte source list [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--include-queued` | Count queued catalog entries in addition to downloaded recordings. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte source delete`

Delete a source and optionally all dependent videos and artifacts.

#### Usage

```console
pte source delete [OPTIONS] SOURCE_ID
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `SOURCE_ID` | Source id to delete.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--force` | Delete dependent videos and all related artifacts. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte video`

Manage discovered videos.

### Usage

```console
pte video [OPTIONS] COMMAND [ARGS]...
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte video list`

List discovered videos.

#### Usage

```console
pte video list [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--pastor TEXT` | Filter by pastor slug. | no | — |
| `--organization TEXT` | Filter by publishing organization slug. | no | — |
| `--source-id INTEGER` | Filter by source id. | no | — |
| `--status [queued|discovered|transcript_fetched|transcribing_local|transcribed_local|extracted|needs_review|approved|exported|failed]` | Filter by video status. | no | — |
| `--limit INTEGER RANGE` | Maximum number of videos to show.  [default: 50; x>=1] | no | 50 |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte video exclude`

Delete a video's local artifacts and prevent it from being rediscovered.

#### Usage

```console
pte video exclude [OPTIONS] VIDEO_ID
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `VIDEO_ID` | Video id to exclude.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--notes TEXT` | Optional exclusion notes. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte video unexclude`

Allow an excluded YouTube video to be rediscovered again.

#### Usage

```console
pte video unexclude [OPTIONS] YOUTUBE_VIDEO_ID
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `YOUTUBE_VIDEO_ID` | YouTube video id to remove from the exclusion list.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte video excluded`

List excluded YouTube videos.

#### Usage

```console
pte video excluded [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--pastor TEXT` | Filter by pastor slug. | no | — |
| `--limit INTEGER RANGE` | Maximum number of excluded videos to show.  [default: 50; x>=1] | no | 50 |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte identity`

Manage speaker identity shadow artifacts.

### Usage

```console
pte identity [OPTIONS] COMMAND [ARGS]...
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte identity compare-speakers`

Run a read-only, abstention-first acoustic comparison of two speaker observations.

#### Usage

```console
pte identity compare-speakers [OPTIONS] VIDEO_A VIDEO_B
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `VIDEO_A` | First YouTube video ID.  [required] | yes | — |
| `VIDEO_B` | Second YouTube video ID.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--model-path PATH` | Local ONNX speaker-embedding model. | no | — |
| `--model-sha256 TEXT` | Required checksum for the local model.  [default: 357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b] | no | 357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b |
| `--cache-dir PATH` | Ignored cache for exact WAV spans and embeddings. | no | — |
| `--output-path PATH` | Result JSON path; defaults to the ignored speaker-pair run directory. | no | — |
| `--policy-path PATH` | Explicitly approved decision policy; without one the comparison always abstains. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity evaluate-observation-consistency`

Plan or run threshold-free within-observation acoustic calibration against human qualification labels.

#### Usage

```console
pte identity evaluate-observation-consistency [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--evaluation-root PATH` | Speaker-pair drafts and review events root.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--model-path PATH` | Local ONNX speaker-embedding model. | no | — |
| `--model-sha256 TEXT` | Required checksum for the local model.  [default: 357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b] | no | 357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b |
| `--cache-dir PATH` | Ignored embedding cache. | no | — |
| `--output-path PATH` | Threshold-free calibration report. | no | — |
| `--execute` | Run acoustic embeddings; without this flag only print the plan. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity run-speaker-model-bakeoff`

Preflight and execute the resumable exact-span speaker-model bake-off.

#### Usage

```console
pte identity run-speaker-model-bakeoff [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--fixture-dir PATH` | Approved exact-span speaker-pair fixtures.  [default: evaluation/speaker-pairs/fixtures] | no | evaluation/speaker-pairs/fixtures |
| `--manifest-path PATH` | Experimental candidate model manifest.  [default: evaluation/speaker-pairs/bakeoff-models.json] | no | evaluation/speaker-pairs/bakeoff-models.json |
| `--result-root PATH` | Model-fingerprint-qualified deterministic result root. | no | — |
| `--cache-dir PATH` | Ignored exact-span and embedding cache. | no | — |
| `--preflight-path PATH` | Persisted preflight and execution plan. | no | — |
| `--report-path PATH` | Threshold-free model comparison report. | no | — |
| `--preflight-only` | Validate and persist the plan without running acoustic models. | no | False |
| `--evaluation-scope TEXT` | Fixture partition to execute: development, validation, held_out, or all. Development also includes legacy unassigned fixtures.  [default: development] | no | development |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity evaluate-speaker-policy-candidate`

Replay a non-approved policy on development bake-off metrics only.

#### Usage

```console
pte identity evaluate-speaker-policy-candidate [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--policy-path PATH` | Development-derived experimental policy candidate.  [default: evaluation/speaker-pairs/policies/campplus-development-candidate-v1.json] | no | evaluation/speaker-pairs/policies/campplus-development-candidate-v1.json |
| `--fixture-dir PATH` | Approved exact-span speaker-pair fixtures.  [default: evaluation/speaker-pairs/fixtures] | no | evaluation/speaker-pairs/fixtures |
| `--manifest-path PATH` | Experimental candidate model manifest.  [default: evaluation/speaker-pairs/bakeoff-models.json] | no | evaluation/speaker-pairs/bakeoff-models.json |
| `--result-root PATH` | Existing model-fingerprint-qualified bake-off results. | no | — |
| `--report-path PATH` | Development-only experimental policy report. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity validate-pair-fixtures`

Validate explicitly reviewed same/different-speaker evaluation fixtures.

#### Usage

```console
pte identity validate-pair-fixtures [OPTIONS] [FIXTURE_DIR]
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `[FIXTURE_DIR]` | [default: evaluation/speaker-pairs/fixtures] | no | evaluation/speaker-pairs/fixtures |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte identity audit-speaker-review-selection`

Verify automatic review drafts used the exact observations selected.

#### Usage

```console
pte identity audit-speaker-review-selection [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--evaluation-root PATH` | Speaker-pair drafts and review events root.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--help` | Show this message and exit. | no | — |

### `pte identity evaluate-pair-results`

Measure pairwise errors and abstention against exact reviewed audio spans.

#### Usage

```console
pte identity evaluate-pair-results [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--fixture-dir PATH` | [default: evaluation/speaker-pairs/fixtures] | no | evaluation/speaker-pairs/fixtures |
| `--result-dir PATH` | — | no | — |
| `--output-path PATH` | — | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity review-observation`

Present one observation's clips with exact YouTube URLs and timestamps.

#### Usage

```console
pte identity review-observation [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--youtube-video-id TEXT` | Review one YouTube video observation. | no | — |
| `--observation-fingerprint TEXT` | Review one exact immutable observation instead of selecting the latest. | no | — |
| `--all-affected` | Prepare packets for the exact observations invalidated by provenance repair. | no | False |
| `--evaluation-root PATH` | Review packet root.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--cache-dir PATH` | Provenance-bound clip cache. | no | — |
| `--open-packet / --no-open-packet` | Open each local HTML packet.  [default: open-packet] | no | True |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity review-speaker-pair`

Prepare and adjudicate an exact-span speaker-pair review.

#### Usage

```console
pte identity review-speaker-pair [OPTIONS] VIDEO_A VIDEO_B
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `VIDEO_A` | First candidate YouTube video ID.  [required] | yes | — |
| `VIDEO_B` | Second candidate YouTube video ID.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--reviewer TEXT` | Stable human reviewer identifier. | no | — |
| `--evaluation-root PATH` | Speaker-pair drafts, reviews, and fixtures root.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--cache-dir PATH` | Ignored exact-span audio cache. | no | — |
| `--open-packet / --no-open-packet` | Open the local HTML review packet.  [default: open-packet] | no | True |
| `--prepare-only` | Create the packet without prompting for adjudication. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity audit-speaker-negative-windows`

Read-only audit of exact observations reviewed as multiple-speaker or invalid audio.

#### Usage

```console
pte identity audit-speaker-negative-windows [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--evaluation-root PATH` | Speaker-pair artifact root.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--json` | Print the complete machine-readable audit. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity review-next-speaker-negative-window`

Review the next current sermon window implicated by a negative speaker qualification.

#### Usage

```console
pte identity review-next-speaker-negative-window [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--reviewer TEXT` | Human reviewer name or stable reviewer identifier. | no | — |
| `--evaluation-root PATH` | Speaker-pair artifact root.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--ground-truth-root PATH` | Root containing sermon drafts/ and fixtures/.  [default: evaluation] | no | evaluation |
| `--open-video / --no-open-video` | Open the selected YouTube window.  [default: open-video] | no | True |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity evaluate-profile-promotions`

Evaluate discovery groupings with cached Jev promotion probabilities.

#### Usage

```console
pte identity evaluate-profile-promotions [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--discovery-report FILE` | Completed shadow profile-discovery JSON artifact.  [required] | yes | — |
| `--model TEXT` | Pinned TypeSafe/Jev model.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--output-root PATH` | Content-addressed Jev judgment cache and artifact root. | no | — |
| `--successful-profile-value FLOAT RANGE` | Utility of a correct reversible provisional profile.  [default: 1.0; x>=0.0] | no | 1.0 |
| `--contaminated-profile-cost FLOAT RANGE` | Utility cost of a contaminated provisional profile.  [default: 3.0; x>=0.0] | no | 3.0 |
| `--details` | Show each grouping, probability, utility, cache state, and artifact. | no | False |
| `--plan-only` | List candidate groupings without TypeSafe calls or artifact writes. | no | False |
| `--cache-only` | Replay matching cached judgments without creating a provider or making model calls. | no | False |
| `--model-digest TEXT` | Cached model digest; inferred when the cache contains exactly one for --model. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity sync-reviewed-speaker-evidence`

Replay confirmed pair reviews into curated anonymous registry state.

#### Usage

```console
pte identity sync-reviewed-speaker-evidence [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--evaluation-root PATH` | Speaker-pair drafts, reviews, and fixtures root.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--dry-run` | Derive and report reviewed evidence without registry mutations. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity export-profile`

Export the reviewed sermon transcript collection for a speaker profile.

#### Usage

```console
pte identity export-profile [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--profile-id INTEGER` | Speaker profile id; redirects are resolved to the canonical profile.  [required] | yes | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity profile-status`

Report the reviewed identity pipeline and what each profile needs next.

#### Usage

```console
pte identity profile-status [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--evaluation-root PATH` | Speaker-pair drafts, reviews, and fixtures root.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--discovery-root PATH` | Shadow profile-discovery reports to include in status. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity review-profile-attribution`

Present an unnamed profile's backing videos and record its reviewed name.

#### Usage

```console
pte identity review-profile-attribution [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--reviewer TEXT` | Stable human reviewer identifier.  [required] | yes | — |
| `--profile-id INTEGER` | Exact canonical profile; default selects the largest unnamed profile. | no | — |
| `--all-proposals` | Review every current non-deferred metadata name proposal. | no | False |
| `--all-anonymous-profiles` | Review every current non-deferred, reviewable anonymous profile. | no | False |
| `--source-pastor-candidate` | Review the largest unnamed single-source profile whose configured source pastor is not yet represented on that source. | no | False |
| `--plan-only` | Show the review queue without opening packets or writing review events. | no | False |
| `--representative-videos INTEGER RANGE` | Maximum backing videos shown in the review packet.  [default: 6; x>=1] | no | 6 |
| `--open-packet / --no-open-packet` | Open the local HTML packet containing timestamped videos.  [default: open-packet] | no | True |
| `--cache-dir PATH` | Persisted identity clip-selection cache used for timestamps. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity enrich-metadata`

Fetch full yt-dlp metadata only when a video's latest snapshot has no description.

#### Usage

```console
pte identity enrich-metadata [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--video-id INTEGER` | Enrich one video by numeric database id. | no | — |
| `--profile-id INTEGER` | Enrich videos attached to one speaker profile. | no | — |
| `--all-anonymous-profiles` | Enrich all current canonical anonymous profiles. | no | False |
| `--plan-only` | Show the selected and eligible counts without network requests or writes. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity analyze-profile-metadata`

Run cached, grounded metadata-name attribution for unnamed profiles.

#### Usage

```console
pte identity analyze-profile-metadata [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--all, --all-anonymous-profiles` | Analyze every current unnamed canonical profile. | no | False |
| `--profile-id INTEGER` | Analyze one exact canonical profile. | no | — |
| `--model TEXT` | Override the selected backend's model. | no | — |
| `--backend TEXT` | Attribution backend: ollama or typesafe.  [default: ollama] | no | ollama |
| `--details` | Show names, evidence excerpts, failures, and artifact paths. | no | False |
| `--plan-only` | Show eligible profiles without model calls or artifact writes. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity association-work-plan`

Plan current accepted-sermon identity work without writing artifacts.

#### Usage

```console
pte identity association-work-plan [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--details` | — | no | False |
| `--association-root PATH` | — | no | — |
| `--base-dir PATH` | — | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity association-work-status`

Summarize unique-video identity work and durable blocker reason codes.

#### Usage

```console
pte identity association-work-status [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--details` | — | no | False |
| `--association-root PATH` | — | no | — |
| `--base-dir PATH` | — | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity review-next-superseded-profile-member`

Review one current replacement against a current profile exemplar to restore acoustic profile coverage.

#### Usage

```console
pte identity review-next-superseded-profile-member [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--reviewer TEXT` | Stable human reviewer identifier. | no | — |
| `--prepare-only` | — | no | False |
| `--open-packet / --no-open-packet` | [default: open-packet] | no | True |
| `--evaluation-root PATH` | [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--cache-dir PATH` | — | no | — |
| `--base-dir PATH` | — | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity dispatch-associations`

Run a bounded, restart-safe batch of current unattempted associations.

#### Usage

```console
pte identity dispatch-associations [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--limit INTEGER RANGE` | [default: 25; x>=1] | no | 25 |
| `--dry-run` | — | no | False |
| `--jobs INTEGER RANGE` | [default: 2; x>=1] | no | 2 |
| `--retry-failed-only` | Retry persisted technical failures without retrying policy-terminal outcomes. | no | False |
| `--association-root PATH` | — | no | — |
| `--base-dir PATH` | — | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity repair-association-prerequisites`

Repair current technical prerequisites from existing local artifacts only.

#### Usage

```console
pte identity repair-association-prerequisites [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--limit INTEGER RANGE` | [default: 25; x>=1] | no | 25 |
| `--dry-run` | — | no | False |
| `--association-root PATH` | — | no | — |
| `--base-dir PATH` | — | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity coordinate`

Plan or execute the non-mutating identity workflow for current extractions.

#### Usage

```console
pte identity coordinate [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--youtube-video-id TEXT` | Coordinate one newly extracted YouTube video. | no | — |
| `--all` | Build a read-only coordination report for all latest extractions. | no | False |
| `--execute-shadow` | Run missing shadow association for the requested video; never apply registry mutations. | no | False |
| `--discovery-report FILE` | Optional discovery artifact to include in promotion planning. | no | — |
| `--discovery-root PATH` | Discovery artifacts used to avoid redundant batch work. | no | — |
| `--model-path PATH` | Local ONNX speaker-embedding model. | no | — |
| `--model-sha256 TEXT` | Required checksum for the local model.  [default: 357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b] | no | 357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b |
| `--policy-path PATH` | Pinned shadow decision policy.  [default: evaluation/speaker-pairs/policies/campplus-development-candidate-v1.json] | no | evaluation/speaker-pairs/policies/campplus-development-candidate-v1.json |
| `--evaluation-root PATH` | Speaker-pair review and fixture root.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--cache-dir PATH` | Ignored acoustic and media-verification cache. | no | — |
| `--association-root PATH` | Versioned shadow-association artifact root. | no | — |
| `--output-root PATH` | Coordination report directory; defaults under application logs. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity reconcile-current-proposals`

Reconcile stale assignment evidence and plan every current proposal.

#### Usage

```console
pte identity reconcile-current-proposals [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--dry-run` | — | no | False |
| `--activate-canary` | — | no | False |
| `--machine-assignment-policy PATH` | [default: evaluation/speaker-associations/policies/machine-assignment-human-on-loop-v1.json] | no | evaluation/speaker-associations/policies/machine-assignment-human-on-loop-v1.json |
| `--association-root PATH` | — | no | — |
| `--base-dir PATH` | — | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity machine-assignment-status`

Report reversible machine evidence and provisional assignment state.

#### Usage

```console
pte identity machine-assignment-status [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--details` | List the current sermon-level associations and evidence paths. | no | False |
| `--profile-id INTEGER` | Only show current associations for this canonical profile. | no | — |
| `--state TEXT` | Only show active, awaiting_activation, blocked_policy, confirmed, or revoked associations. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity rollback-machine-assignments`

Plan or append revocations for one machine policy fingerprint.

#### Usage

```console
pte identity rollback-machine-assignments [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--policy-fingerprint TEXT` | Exact machine evidence policy fingerprint to revoke.  [required] | yes | — |
| `--apply` | Append rollback events; otherwise print the plan only. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity backfill`

Create missing shadow identity and neutral speaker artifacts without reclassification.

#### Usage

```console
pte identity backfill [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--video-id INTEGER` | Only backfill one database video id. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity run`

Sync reviewed evidence, then run backfill, shadow association, discovery, final coordination, and eligible normalized archival.

#### Usage

```console
pte identity run [OPTIONS] [YOUTUBE_VIDEO_ID]
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `[YOUTUBE_VIDEO_ID]` | One YouTube video ID; omit when using --all. | no | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--all` | Run across all current extractions and include corpus discovery. | no | False |
| `--plan-only` | Show all stages without acoustic execution or registry mutation. | no | False |
| `--skip-discovery` | Skip corpus profile discovery during an --all run. | no | False |
| `--apply-automatic` | Apply validated confirmations, promotions, and policy-gated human-on-loop provisional assignments. Requires --all. | no | False |
| `--apply-confirmations` | Apply validated independent provisional-profile confirmations. | no | False |
| `--apply-promotions` | Promote verified discovery components into provisional profiles. | no | False |
| `--evaluate-profile-promotions / --no-evaluate-profile-promotions` | Evaluate bounded discovery groupings with Jev and include current cached positive-utility judgments in the promotion plan.  [default: evaluate-profile-promotions] | no | True |
| `--promotion-model TEXT` | Pinned TypeSafe/Jev model for profile-promotion judgments.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--promotion-judgment-root PATH` | Content-addressed Jev promotion-judgment cache root. | no | — |
| `--promotion-successful-profile-value FLOAT RANGE` | Utility of a correct reversible provisional profile.  [default: 1.0; x>=0.0] | no | 1.0 |
| `--promotion-contaminated-profile-cost FLOAT RANGE` | Utility cost of a contaminated provisional profile.  [default: 3.0; x>=0.0] | no | 3.0 |
| `--apply-machine-canary` | Activate only eligible reversible machine assignments without also applying profile confirmations or promotions. Requires --all. | no | False |
| `--machine-assignment-policy PATH` | Use a versioned machine-assignment policy artifact. The default checked-in policy is shadow-only. | no | — |
| `--review-prewarm-limit INTEGER RANGE` | Precompute exact clips for this many current actionable review observations during an --all run; use 0 to disable.  [default: 24; x>=0] | no | 24 |
| `--jobs INTEGER RANGE` | Concurrent acoustic comparison jobs; registry mutations and artifact aggregation remain serialized.  [default: 2; x>=1] | no | 2 |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity shadow-associate-speakers`

Propose multi-exemplar profile matches without changing registry membership.

#### Usage

```console
pte identity shadow-associate-speakers [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--youtube-video-id TEXT` | Evaluate one YouTube video. | no | — |
| `--all-eligible` | Evaluate every currently eligible unassigned sermon observation. | no | False |
| `--unattempted-only` | With --all-eligible, evaluate only current observations with no persisted shadow-association attempt. | no | False |
| `--neighborhood-profile-id INTEGER RANGE` | Replay only observations with persisted direct routing, comparison, proposal, or exemplar-exclusion evidence for this profile; repeatable.  [x>=1] | no | — |
| `--include-profiled` | Include already-profiled observations for boundary-evidence regeneration; profile membership remains unchanged. | no | False |
| `--limit INTEGER RANGE` | Maximum candidates to evaluate when using --all-eligible.  [x>=1] | no | — |
| `--plan-only` | Report readiness and candidate coverage without acoustic execution. | no | False |
| `--minimum-profile-members INTEGER RANGE` | Distinct reviewed members required for shadow profile matching.  [default: 3; x>=3] | no | 3 |
| `--maximum-exemplars INTEGER RANGE` | Maximum independently recorded exemplars compared per profile.  [default: 3; x>=2] | no | 3 |
| `--minimum-same-exemplars INTEGER RANGE` | Same-speaker comparisons required to propose one profile.  [default: 2; x>=2] | no | 2 |
| `--maximum-global-profiles INTEGER RANGE` | Maximum cross-source acoustic fallback profiles when no same-source, explicit-name, or confirmation route exists.  [default: 1; x>=1] | no | 1 |
| `--jobs INTEGER RANGE` | Concurrent acoustic preprocessing and comparison jobs.  [default: 2; x>=1] | no | 2 |
| `--model-path PATH` | Local ONNX speaker-embedding model. | no | — |
| `--model-sha256 TEXT` | Required checksum for the local model.  [default: 357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b] | no | 357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b |
| `--policy-path PATH` | Pinned approved or experimental shadow decision policy.  [default: evaluation/speaker-pairs/policies/campplus-development-candidate-v1.json] | no | evaluation/speaker-pairs/policies/campplus-development-candidate-v1.json |
| `--evaluation-root PATH` | Speaker-pair drafts, reviews, and fixtures root.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--cache-dir PATH` | Ignored exact-span, embedding, and media-verification cache. | no | — |
| `--output-root PATH` | Ignored versioned shadow-association artifacts. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity association-audit`

Verify that every latest extraction has a terminal association-coverage state.

#### Usage

```console
pte identity association-audit [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--association-root PATH` | Versioned speaker-association attempt artifacts.  [default: evaluation/speaker-associations/shadow-runs] | no | evaluation/speaker-associations/shadow-runs |
| `--cache-dir PATH` | Media-verification cache used for current eligibility checks.  [default: evaluation/speaker-pairs/cache] | no | evaluation/speaker-pairs/cache |
| `--policy-path PATH` | Require association attempts produced with this exact policy artifact.  [default: evaluation/speaker-pairs/policies/campplus-development-candidate-v1.json] | no | evaluation/speaker-pairs/policies/campplus-development-candidate-v1.json |
| `--required-model-fingerprint TEXT` | Optionally require one exact acoustic model fingerprint. | no | — |
| `--output-root PATH` | Audit artifact directory; defaults under the application logs directory. | no | — |
| `--strict / --allow-gaps` | Exit nonzero when any latest extraction is unaccounted.  [default: strict] | no | True |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity consolidate-source-profiles`

Plan or human-approve complete-link consolidation of anonymous profiles sharing a source.

#### Usage

```console
pte identity consolidate-source-profiles [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--source-id INTEGER RANGE` | Source whose anonymous profiles should be compared.  [x>=1] | no | — |
| `--list-sources` | List sources with eligible anonymous profile cohorts. | no | False |
| `--all-eligible` | Process each currently eligible source cohort in turn, instead of selecting one source. | no | False |
| `--minimum-profiles INTEGER RANGE` | Minimum eligible profile count shown by --list-sources.  [default: 2; x>=1] | no | 2 |
| `--plan-only` | Inventory the source cohort without acoustic execution or writes. | no | False |
| `--apply` | Prompt for one human approval per complete-link cohort and merge it. | no | False |
| `--reviewer TEXT` | Stable reviewer identifier; required with --apply. | no | — |
| `--exemplars-per-profile INTEGER RANGE` | Independent recording exemplars compared for each profile.  [default: 3; 2<=x<=5] | no | 3 |
| `--jobs INTEGER RANGE` | [default: 2; x>=1] | no | 2 |
| `--open-packet / --no-open-packet` | Open the weakest-edge review packet before an apply prompt.  [default: open-packet] | no | True |
| `--model-path PATH` | [default: evaluation/speaker-pairs/models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx] | no | evaluation/speaker-pairs/models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx |
| `--model-sha256 TEXT` | [default: 357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b] | no | 357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b |
| `--policy-path PATH` | [default: evaluation/speaker-pairs/policies/campplus-development-candidate-v1.json] | no | evaluation/speaker-pairs/policies/campplus-development-candidate-v1.json |
| `--evaluation-root PATH` | [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--cache-dir PATH` | [default: evaluation/speaker-pairs/cache] | no | evaluation/speaker-pairs/cache |
| `--output-root PATH` | [default: evaluation/source-profile-consolidation/runs] | no | evaluation/source-profile-consolidation/runs |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity shadow-discover-profiles`

Discover provisional anonymous profiles among unassigned observations.

#### Usage

```console
pte identity shadow-discover-profiles [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--plan-only` | Report candidate coverage without acoustic execution. | no | False |
| `--limit INTEGER RANGE` | Maximum eligible observations to include.  [x>=1] | no | — |
| `--nearest-neighbors INTEGER RANGE` | Centroid-nearest observations nominated per candidate.  [default: 8; x>=2] | no | 8 |
| `--maximum-pairs INTEGER RANGE` | Optional global cap on nominated acoustic comparisons.  [x>=1] | no | — |
| `--closure-candidates-per-same-pair INTEGER RANGE` | Likely third observations tested against both endpoints of each same-speaker seed pair.  [default: 8; x>=0] | no | 8 |
| `--source-complete-link-limit INTEGER RANGE` | Source groups at or below this size receive complete pair retrieval coverage; source is never identity evidence.  [default: 12; x>=2] | no | 12 |
| `--source-nearest-neighbors INTEGER RANGE` | Per-observation source-local quota for larger source groups.  [default: 4; x>=1] | no | 4 |
| `--borderline-deferred-minimum FLOAT RANGE` | Inclusive lower score for guarded deferred closure.  [default: 0.5; 0.0<=x<=1.0] | no | 0.5 |
| `--borderline-deferred-maximum FLOAT RANGE` | Exclusive upper score for guarded deferred closure.  [default: 0.6; 0.0<=x<=1.0] | no | 0.6 |
| `--borderline-deferred-candidates-per-same-pair INTEGER RANGE` | Borderline-deferred third candidates compared acoustically with both endpoints of a strong same-speaker seed.  [default: 4; x>=0] | no | 4 |
| `--staged-review-candidates-per-component INTEGER RANGE` | Strong third candidates with two ambiguous seed edges retained per blocked component for staged blinded review.  [default: 2; x>=0] | no | 2 |
| `--staged-review-maximum-same-boundary-distance FLOAT RANGE` | Maximum acoustic distance from the same-speaker boundary for a staged human-review candidate; this does not change pair decision thresholds.  [default: 0.15; 0.0<=x<=1.0] | no | 0.15 |
| `--jobs INTEGER RANGE` | Concurrent acoustic pair-comparison jobs.  [default: 2; x>=1] | no | 2 |
| `--minimum-component-members INTEGER RANGE` | Distinct recordings required for a provisional profile proposal.  [default: 3; x>=3] | no | 3 |
| `--consistency-report PATH` | Optional threshold-free observation-consistency report. | no | — |
| `--minimum-consistency-score FLOAT RANGE` | Require a scored observation at or above this calibrated value.  [-1.0<=x<=1.0] | no | — |
| `--consistency-policy PATH` | Versioned policy that tiers freshly computed discovery consistency scores.  [default: evaluation/speaker-pairs/policies/observation-consistency-discovery-v1.json] | no | evaluation/speaker-pairs/policies/observation-consistency-discovery-v1.json |
| `--include-deferred` | Deprecated unsafe diagnostic override; deferred observations now remain outside global discovery. | no | False |
| `--model-path PATH` | Local ONNX speaker-embedding model.  [default: evaluation/speaker-pairs/models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx] | no | evaluation/speaker-pairs/models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx |
| `--model-sha256 TEXT` | Required checksum for the local model.  [default: 357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b] | no | 357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b |
| `--policy-path PATH` | Pinned approved or experimental shadow decision policy.  [default: evaluation/speaker-pairs/policies/campplus-development-candidate-v1.json] | no | evaluation/speaker-pairs/policies/campplus-development-candidate-v1.json |
| `--evaluation-root PATH` | Reviewed pair evidence used as explicit discovery constraints.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--cache-dir PATH` | Ignored exact-span, embedding, and media-verification cache.  [default: evaluation/speaker-pairs/cache] | no | evaluation/speaker-pairs/cache |
| `--output-root PATH` | Ignored versioned shadow profile-discovery artifacts.  [default: evaluation/speaker-profile-discovery/shadow-runs] | no | evaluation/speaker-profile-discovery/shadow-runs |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity promote-discovered-profiles`

Promote verified discovery components into reversible provisional profiles.

#### Usage

```console
pte identity promote-discovered-profiles [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--discovery-report FILE` | Completed shadow profile-discovery JSON artifact.  [required] | yes | — |
| `--apply` | Create provisional profiles and attach their seed observations. | no | False |
| `--include-probability-judgments / --no-probability-judgments` | Include current cached Jev judgments with positive promotion utility.  [default: include-probability-judgments] | no | True |
| `--promotion-model TEXT` | Pinned model identity used by the cached Jev judgments.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--promotion-judgment-root PATH` | Content-addressed Jev promotion-judgment cache root.  [default: evaluation/speaker-profile-discovery/promotion-judgments] | no | evaluation/speaker-profile-discovery/promotion-judgments |
| `--successful-profile-value FLOAT RANGE` | Utility of a correct reversible provisional profile.  [default: 1.0; x>=0.0] | no | 1.0 |
| `--contaminated-profile-cost FLOAT RANGE` | Utility cost of a contaminated provisional profile.  [default: 3.0; x>=0.0] | no | 3.0 |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity confirm-discovered-profiles`

Attach independent proposed matches to provisional discovery profiles.

#### Usage

```console
pte identity confirm-discovered-profiles [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--input-root PATH` | Versioned shadow-association artifact root.  [default: evaluation/speaker-associations/shadow-runs] | no | evaluation/speaker-associations/shadow-runs |
| `--apply` | Attach validated confirmations to their provisional profiles. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity profile-leverage-snapshot`

Persist an observed before/after profile-state experiment without changing membership.

#### Usage

```console
pte identity profile-leverage-snapshot [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--profile-id INTEGER RANGE` | Affected profile id; repeat for a duplicate-profile group.  [x>=1; required] | yes | — |
| `--decision-kind TEXT` | duplicate_profile_cleanup, readiness_promotion, exemplar_media_fix, prospective_confirmation, or sermon_review.  [required] | yes | — |
| `--baseline PATH` | Prior snapshot to compare after the decision and neighborhood replay. | no | — |
| `--profile-level-decisions INTEGER RANGE` | [default: 0; x>=0] | no | 0 |
| `--sermon-level-reviews INTEGER RANGE` | [default: 0; x>=0] | no | 0 |
| `--prospective-correct INTEGER RANGE` | [default: 0; x>=0] | no | 0 |
| `--prospective-incorrect INTEGER RANGE` | [default: 0; x>=0] | no | 0 |
| `--association-root PATH` | Existing shadow-association artifacts.  [default: evaluation/speaker-associations/shadow-runs] | no | evaluation/speaker-associations/shadow-runs |
| `--output-root PATH` | Ignored profile-leverage experiment artifacts.  [default: evaluation/identity-leverage] | no | evaluation/identity-leverage |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity shadow-association-status`

Measure saved shadow proposals against later reviewed registry state.

#### Usage

```console
pte identity shadow-association-status [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--input-root PATH` | Versioned shadow-association artifact root.  [default: evaluation/speaker-associations/shadow-runs] | no | evaluation/speaker-associations/shadow-runs |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity detach-speaker-observation`

Append a reviewed detachment without deleting membership history.

#### Usage

```console
pte identity detach-speaker-observation [OPTIONS] YOUTUBE_VIDEO_ID
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `YOUTUBE_VIDEO_ID` | Observation's YouTube video ID.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--profile-id INTEGER` | Anonymous profile to detach.  [required] | yes | — |
| `--reviewer TEXT` | Stable human reviewer identifier.  [required] | yes | — |
| `--reason TEXT` | Review reason for the detachment.  [required] | yes | — |
| `--review-event-key TEXT` | Optional stable key for explicit idempotent replay. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity record-speaker-difference`

Record or clear an explicitly reviewed different-speaker constraint.

#### Usage

```console
pte identity record-speaker-difference [OPTIONS] VIDEO_A VIDEO_B
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `VIDEO_A` | First reviewed YouTube video ID.  [required] | yes | — |
| `VIDEO_B` | Second reviewed YouTube video ID.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--reviewer TEXT` | Stable human reviewer identifier.  [required] | yes | — |
| `--reason TEXT` | Evidence-backed review reason.  [required] | yes | — |
| `--different / --clear` | Assert or clear the effective constraint without deleting history.  [default: different] | no | True |
| `--review-event-key TEXT` | Optional stable key for explicit idempotent replay. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity prepare-speaker-review-audio`

Prewarm deterministic speech-qualified clips without creating review drafts.

#### Usage

```console
pte identity prepare-speaker-review-audio [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--evaluation-scope TEXT` | Prepare observations from validation, development, held_out, or all families.  [default: validation] | no | validation |
| `--limit INTEGER RANGE` | Prepare at most this many observations; default prepares the full scope.  [x>=1] | no | — |
| `--cache-dir PATH` | Ignored exact-span audio cache shared with pair review.  [default: evaluation/speaker-pairs/cache] | no | evaluation/speaker-pairs/cache |
| `--source-family-registry PATH` | Frozen source-family registry used for partition scoping.  [default: evaluation/source-families.json] | no | evaluation/source-families.json |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity prepare-actionable-review-audio`

Precompute exact clips for current automation-readiness and profile-growth nominations without creating drafts.

#### Usage

```console
pte identity prepare-actionable-review-audio [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--limit INTEGER RANGE` | Maximum unique nominated observations to prepare.  [default: 24; x>=1] | no | 24 |
| `--cache-dir PATH` | Ignored exact-span audio cache shared with pair review.  [default: evaluation/speaker-pairs/cache] | no | evaluation/speaker-pairs/cache |
| `--discovery-root PATH` | Discovery artifacts used to prioritize review observations.  [default: evaluation/speaker-profile-discovery/shadow-runs] | no | evaluation/speaker-profile-discovery/shadow-runs |
| `--association-root PATH` | Association artifacts used to prioritize review observations.  [default: evaluation/speaker-associations/shadow-runs] | no | evaluation/speaker-associations/shadow-runs |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte identity review-next-speaker-pair`

Deterministically nominate and adjudicate the next unseen speaker pair.

#### Usage

```console
pte identity review-next-speaker-pair [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--reviewer TEXT` | Stable human reviewer identifier. | no | — |
| `--evaluation-root PATH` | Speaker-pair drafts, reviews, and fixtures root.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--cache-dir PATH` | Ignored exact-span audio cache.  [default: evaluation/speaker-pairs/cache] | no | evaluation/speaker-pairs/cache |
| `--source-family-registry PATH` | Frozen source-family registry used for partition-safe pair nomination.  [default: evaluation/source-families.json] | no | evaluation/source-families.json |
| `--open-packet / --no-open-packet` | Open the local HTML review packet.  [default: open-packet] | no | True |
| `--prepare-only` | Create the selected packet without prompting for adjudication. | no | False |
| `--evaluation-scope TEXT` | Nominate only from all, development, validation, or held_out source families.  [default: all] | no | all |
| `--selection-objective [evaluation|profile-growth|automation-readiness]` | Use evaluation for the tuned fixture selector or profile-growth for reviewed component expansion; automation-readiness first reviews immediate and staged discovery frontiers, then resolves overlaps and reinforces profiles.  [default: evaluation] | no | evaluation |
| `--profile-id INTEGER RANGE` | Constrain profile-growth nomination to a specific canonical speaker profile.  [x>=1] | no | — |
| `--discovery-report FILE` | Optional exact discovery artifact for automation-readiness or profile-growth acoustic ranking. | no | — |
| `--discovery-root PATH` | Discovery artifacts used by automation-readiness nomination.  [default: evaluation/speaker-profile-discovery/shadow-runs] | no | evaluation/speaker-profile-discovery/shadow-runs |
| `--association-root PATH` | Shadow-association artifacts used for contextual profile-match confirmation nominations.  [default: evaluation/speaker-associations/shadow-runs] | no | evaluation/speaker-associations/shadow-runs |
| `--observation-consistency-report PATH` | Optional threshold-free consistency scores used only for balanced nomination ranking.  [default: evaluation/speaker-pairs/runs/observation-consistency-v1.json] | no | evaluation/speaker-pairs/runs/observation-consistency-v1.json |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte media`

Manage transcript-independent local media artifacts.

### Usage

```console
pte media [OPTIONS] COMMAND [ARGS]...
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte media backfill`

Register existing audio as reconstructed immutable media artifacts without moving files.

#### Usage

```console
pte media backfill [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--video-id INTEGER` | Only migrate one database video id. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte media ensure-audio`

Ensure isolated sermons have verified audio without running local ASR.

#### Usage

```console
pte media ensure-audio [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--video-id INTEGER` | Only process one database video id. | no | — |
| `--all-eligible` | Process unresolved videos with a valid isolated sermon window. | no | False |
| `--limit INTEGER RANGE` | Maximum eligible videos to process.  [x>=1] | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte media audit`

Report isolated-sermon audio coverage without downloading or modifying media.

#### Usage

```console
pte media audit [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte media archive-sources`

Archive comparison-independent source audio and replace local files with verified symlinks.

#### Usage

```console
pte media archive-sources [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--archive-root PATH` | NAS archive root. Supplying it records and activates the destination for later retries. | no | — |
| `--dry-run` | Record eligible entries and show destinations without copying or replacing files. | no | False |
| `--limit INTEGER RANGE` | Maximum eligible source artifacts to process.  [x>=1] | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte media prepare-canonical-audio`

Prepare current canonical speaker clips without running comparisons.

#### Usage

```console
pte media prepare-canonical-audio [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--dry-run` | — | no | False |
| `--limit INTEGER RANGE` | [x>=1] | no | — |
| `--youtube-video-id TEXT` | — | no | — |
| `--all-eligible` | — | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte media archive-normalized`

Archive eligible normalized audio after canonical speaker inputs are prepared.

#### Usage

```console
pte media archive-normalized [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--archive-root PATH` | — | no | — |
| `--dry-run` | — | no | False |
| `--limit INTEGER RANGE` | [x>=1] | no | — |
| `--youtube-video-id TEXT` | — | no | — |
| `--all-eligible` | — | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte media archive-status`

Report source and normalized archive state and normalized eligibility.

#### Usage

```console
pte media archive-status [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte media sweep-audio`

Audit physical local audio and optionally replace byte-identical archived duplicates with symlinks. Dry-run is the default.

#### Usage

```console
pte media sweep-audio [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--apply` | Replace only byte-identical, checksum-verified archived duplicates with symlinks. Unmatched files are never removed. | no | False |
| `--report PATH` | Write the complete machine-readable audit as JSON. | no | — |
| `--verbose` | Print every retained file in addition to reclaimable files. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte media audit-normalized-provenance`

Read-only audit of derived and reconstructed normalized-audio conflicts.

#### Usage

```console
pte media audit-normalized-provenance [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--json` | Emit the complete machine-readable report. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte media repair-normalized-provenance`

Re-normalize affected audio from verified immutable source artifacts.

#### Usage

```console
pte media repair-normalized-provenance [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--all-affected` | Repair every video identified by the audit. | no | False |
| `--youtube-video-id TEXT` | Repair one affected YouTube video. | no | — |
| `--evaluation-root PATH` | Speaker-review artifacts to revoke when they used affected audio.  [default: evaluation/speaker-pairs] | no | evaluation/speaker-pairs |
| `--reviewer TEXT` | Reviewer or system actor recorded on append-only cleanup events.  [default: normalized-provenance-repair] | no | normalized-provenance-repair |
| `--regenerate-fingerprints` | Append audio-bound speaker observations using the repaired normalized-audio SHA-256. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte analysis`

Analyze already-identified sermon content.

### Usage

```console
pte analysis [OPTIONS] COMMAND [ARGS]...
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte analysis status`

Report deterministic analysis readiness by profile.

#### Usage

```console
pte analysis status [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--all-profiles` | Include all active and provisional profiles. | no | False |
| `--json` | Emit machine-readable JSON. | no | False |
| `--analyzer-version TEXT` | Required sermon analyzer version.  [default: 4] | no | 4 |
| `--profile-analyzer-version TEXT` | Required profile analyzer version.  [default: 4] | no | 4 |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis backfill`

Run a resumable deterministic sermon-analysis backfill.

#### Usage

```console
pte analysis backfill [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--all-attached` | Analyze eligible sermons attached to active/provisional profiles. | no | False |
| `--dry-run` | Show the exact plan without writes. | no | False |
| `--minimum-sermons INTEGER RANGE` | Minimum profile depth for aggregate refresh.  [default: 3; x>=1] | no | 3 |
| `--analyzer-version TEXT` | Sermon analyzer version to run.  [default: 4] | no | 4 |
| `--profile-analyzer-version TEXT` | Profile analyzer version to build.  [default: 4] | no | 4 |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis refresh-profiles`

Refresh stale deterministic profile aggregates only.

#### Usage

```console
pte analysis refresh-profiles [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--minimum-sermons INTEGER RANGE` | Minimum eligible sermons per profile.  [default: 3; x>=1] | no | 3 |
| `--analyzer-version TEXT` | Required sermon analyzer version.  [default: 4] | no | 4 |
| `--profile-analyzer-version TEXT` | Profile analyzer version to build.  [default: 4] | no | 4 |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis population-build`

Freeze current profile runs and build deterministic population diagnostics.

#### Usage

```console
pte analysis population-build [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--minimum-sermons INTEGER RANGE` | Minimum current sermons per profile.  [default: 3; x>=2] | no | 3 |
| `--bootstrap-samples INTEGER RANGE` | Deterministic resamples per profile.  [default: 200; x>=20] | no | 200 |
| `--analyzer-version TEXT` | Population diagnostic implementation version.  [default: scripture-population-diagnostics@3] | no | scripture-population-diagnostics@3 |
| `--json` | Emit the complete report as JSON. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis population-show`

Inspect a persisted population diagnostic snapshot.

#### Usage

```console
pte analysis population-show [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--snapshot-id INTEGER` | Default: latest. | no | — |
| `--json` | Emit the complete report as JSON. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis run`

Analyze one identified sermon or a speaker profile's attached sermons.

#### Usage

```console
pte analysis run [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--video-id INTEGER` | Database video id. | no | — |
| `--youtube-video-id TEXT` | YouTube video id. | no | — |
| `--profile-id INTEGER` | Canonical speaker profile id; selects effectively attached sermons. | no | — |
| `--pastor TEXT` | Compatibility alias resolved through the pastor's speaker-profile binding. | no | — |
| `--analyzer-version TEXT` | Version recorded in provenance; change this when analyzer behavior changes.  [default: 4] | no | 4 |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis topic-review`

Build or reuse a bounded review packet from cached TypeSafe topic observations.

#### Usage

```console
pte analysis topic-review [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--video-id INTEGER` | Database video id. | no | — |
| `--youtube-video-id TEXT` | YouTube video id. | no | — |
| `--output PATH` | JSON output path; defaults beside the video's extraction artifacts. | no | — |
| `--prospective` | Use the deterministic prospective sampler even when named regression cases exist. | no | False |
| `--maximum-cases INTEGER RANGE` | Maximum cases selected in prospective mode.  [default: 8; 1<=x<=20] | no | 8 |
| `--whole-sermon` | Include every cached topic block for whole-sermon analytical review. | no | False |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis topic-review-draft`

Create a protected adjudication draft for a cached topic review packet.

#### Usage

```console
pte analysis topic-review-draft [OPTIONS] PACKET
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `PACKET` | Topic review packet JSON file.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--output PATH` | Draft JSON path; defaults beside the source packet. | no | — |
| `--proposal PATH` | Optional fingerprint-bound proposal used to prefill review corrections. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis topic-review-finalize`

Validate and freeze a topic review separately from cached evidence.

#### Usage

```console
pte analysis topic-review-finalize [OPTIONS] DRAFT
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `DRAFT` | Topic review adjudication draft JSON.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--reviewer TEXT` | Reviewer identity.  [required] | yes | — |
| `--output PATH` | Final reviewed JSON path; defaults beside the draft. | no | — |
| `--accept-as-reviewed` | Confirm all required checks after inspecting the source packet. | no | False |
| `--help` | Show this message and exit. | no | — |

### `pte analysis topic-summarize-profile`

Materialize an exploratory equal-sermon profile from cached TypeSafe topic projections.

#### Usage

```console
pte analysis topic-summarize-profile [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--profile-id INTEGER` | Speaker profile id.  [required] | yes | — |
| `--analyzer-version TEXT` | Topic profile analyzer version.  [default: 1] | no | 1 |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis topic-show-profile`

Inspect the latest materialized exploratory TypeSafe topic profile.

#### Usage

```console
pte analysis topic-show-profile [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--profile-id INTEGER` | Speaker profile id.  [required] | yes | — |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis topic-stability-readiness`

Audit reviewed identity, cached topic projections, and Stage 4 series/period strata without inference or writes.

#### Usage

```console
pte analysis topic-stability-readiness [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Frozen topic cohort JSON with series and period metadata.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis evaluate-topic-stability`

Write cached Stage 4 equal-sermon, series, and period repeatability diagnostics after readiness passes.

#### Usage

```console
pte analysis evaluate-topic-stability [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Frozen topic cohort JSON with series and period metadata.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--output PATH` | Fingerprint-bound JSON report path; Markdown is written beside it.  [default: evaluation/sermon-topics/stage4-topic-stability-v1.json] | no | evaluation/sermon-topics/stage4-topic-stability-v1.json |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-routing-review`

Write a provider-free calibration packet for the conditional salvation leaf route.

#### Usage

```console
pte analysis salvation-routing-review [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying cached broad observations.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-routing-calibration-v3.json] | no | evaluation/sermon-topics/salvation-routing-calibration-v3.json |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-relationships-review`

Evaluate a bounded, independently cached salvation relationship leaf sample.

#### Usage

```console
pte analysis salvation-relationships-review [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying cached broad observations.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-relationships-review-v3.json] | no | evaluation/sermon-topics/salvation-relationships-review-v3.json |
| `--model TEXT` | Pinned TypeSafe model id used for the leaf judgments.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--timeout-seconds FLOAT RANGE` | Timeout for each uncached TypeSafe request.  [default: 45.0; x>=1.0] | no | 45.0 |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-obedience-calibration`

Evaluate a final cache-first sample for obedience as consequence or evidence.

#### Usage

```console
pte analysis salvation-obedience-calibration [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying cached broad observations.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-obedience-consequence-calibration-v1.json] | no | evaluation/sermon-topics/salvation-obedience-consequence-calibration-v1.json |
| `--model TEXT` | Pinned TypeSafe model id used for the leaf judgments.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--timeout-seconds FLOAT RANGE` | Timeout for each uncached TypeSafe request.  [default: 45.0; x>=1.0] | no | 45.0 |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-semantic-calibration`

Evaluate revised salvation leaf semantics on regressions and fresh held-out boundaries, plus a cached assurance search.

#### Usage

```console
pte analysis salvation-semantic-calibration [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying routed blocks and reviewed v2 evidence.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-semantic-calibration-v1.json] | no | evaluation/sermon-topics/salvation-semantic-calibration-v1.json |
| `--model TEXT` | Pinned TypeSafe model id used for revised leaf judgments.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--timeout-seconds FLOAT RANGE` | Timeout for each uncached TypeSafe request.  [default: 45.0; x>=1.0] | no | 45.0 |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-final-calibration`

Run the bounded faith-recall and repentance-ordering acceptance check.

#### Usage

```console
pte analysis salvation-final-calibration [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying routed blocks and reviewed v2 evidence.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-final-calibration-v1.json] | no | evaluation/sermon-topics/salvation-final-calibration-v1.json |
| `--model TEXT` | Pinned TypeSafe model id used for revised leaf judgments.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--timeout-seconds FLOAT RANGE` | Timeout for each uncached TypeSafe request.  [default: 45.0; x>=1.0] | no | 45.0 |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-v5-calibration`

Evaluate four revised salvation questions on reviewed and held-out cases.

#### Usage

```console
pte analysis salvation-v5-calibration [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying routed blocks and v4 evidence.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--boundary-review PATH` | Reviewed four-leaf v4 boundary packet.  [default: evaluation/sermon-topics/salvation-boundary-recalibration-v1.json] | no | evaluation/sermon-topics/salvation-boundary-recalibration-v1.json |
| `--collection-review PATH` | Reviewed ordinary-classification packet used to exclude prior cases.  [default: evaluation/sermon-topics/salvation-collected-observations-review-v2.json] | no | evaluation/sermon-topics/salvation-collected-observations-review-v2.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-v5-calibration-v1.json] | no | evaluation/sermon-topics/salvation-v5-calibration-v1.json |
| `--model TEXT` | Pinned TypeSafe model id used for revised leaf judgments.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--timeout-seconds FLOAT RANGE` | Timeout for each uncached TypeSafe request.  [default: 45.0; x>=1.0] | no | 45.0 |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-v5-threshold-review`

Build the provider-free final threshold review from cached v5 judgments.

#### Usage

```console
pte analysis salvation-v5-threshold-review [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--input PATH` | Reviewed v5 calibration packet.  [default: evaluation/sermon-topics/salvation-v5-calibration-v1.json] | no | evaluation/sermon-topics/salvation-v5-calibration-v1.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-v5-threshold-review-v1.json] | no | evaluation/sermon-topics/salvation-v5-threshold-review-v1.json |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-v6-repentance-calibration`

Run the bounded v6 repentance-entry regression and held-out check.

#### Usage

```console
pte analysis salvation-v6-repentance-calibration [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying routed evidence.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--final-check PATH` | Reviewed final collection boundary check.  [default: evaluation/sermon-topics/salvation-final-collection-check-v1.json] | no | evaluation/sermon-topics/salvation-final-collection-check-v1.json |
| `--v5-calibration PATH` | Reviewed v5 semantic calibration used to exclude prior cases.  [default: evaluation/sermon-topics/salvation-v5-calibration-v1.json] | no | evaluation/sermon-topics/salvation-v5-calibration-v1.json |
| `--collection-review PATH` | Reviewed ordinary-classification packet used to exclude prior cases.  [default: evaluation/sermon-topics/salvation-collected-observations-review-v2.json] | no | evaluation/sermon-topics/salvation-collected-observations-review-v2.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-v6-repentance-calibration-v1.json] | no | evaluation/sermon-topics/salvation-v6-repentance-calibration-v1.json |
| `--model TEXT` | Pinned TypeSafe model id used for revised leaf judgments.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--timeout-seconds FLOAT RANGE` | Timeout for each uncached TypeSafe request.  [default: 45.0; x>=1.0] | no | 45.0 |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-v7-repentance-calibration`

Run the final bounded observational repentance calibration.

#### Usage

```console
pte analysis salvation-v7-repentance-calibration [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying routed evidence.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--v6-calibration PATH` | Reviewed v6 repentance packet supplying regressions and exclusions.  [default: evaluation/sermon-topics/salvation-v6-repentance-calibration-v1.json] | no | evaluation/sermon-topics/salvation-v6-repentance-calibration-v1.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-v7-repentance-calibration-v1.json] | no | evaluation/sermon-topics/salvation-v7-repentance-calibration-v1.json |
| `--model TEXT` | Pinned TypeSafe model id used for revised leaf judgments.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--timeout-seconds FLOAT RANGE` | Timeout for each uncached TypeSafe request.  [default: 45.0; x>=1.0] | no | 45.0 |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-v8-conversion-calibration`

Run the bounded v8 saving-state-transition conversion calibration.

#### Usage

```console
pte analysis salvation-v8-conversion-calibration [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying routed v7 evidence.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--conversion-review PATH` | Reviewed conversion-only packet supplying regressions and exclusions.  [default: evaluation/sermon-topics/salvation-conversion-recalibration-v1.json] | no | evaluation/sermon-topics/salvation-conversion-recalibration-v1.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-v8-conversion-calibration-v1.json] | no | evaluation/sermon-topics/salvation-v8-conversion-calibration-v1.json |
| `--model TEXT` | Pinned TypeSafe model id used for revised leaf judgments.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--timeout-seconds FLOAT RANGE` | Timeout for each uncached TypeSafe request.  [default: 45.0; x>=1.0] | no | 45.0 |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-final-boundary-calibration`

Run the final bounded atonement, judgment, consequence, and transcript review.

#### Usage

```console
pte analysis salvation-final-boundary-calibration [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying routed V8 evidence.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--collection-review PATH` | Reviewed V8 ordinary-classification boundary packet.  [default: evaluation/sermon-topics/salvation-collected-observations-review-v2.json] | no | evaluation/sermon-topics/salvation-collected-observations-review-v2.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-final-boundary-calibration-v1.json] | no | evaluation/sermon-topics/salvation-final-boundary-calibration-v1.json |
| `--model TEXT` | Pinned TypeSafe model id used for revised consequence judgments.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--timeout-seconds FLOAT RANGE` | Timeout for each uncached TypeSafe request.  [default: 45.0; x>=1.0] | no | 45.0 |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-observation-threshold-review`

Build a provider-free boundary review for the salvation leaf collection threshold.

#### Usage

```console
pte analysis salvation-observation-threshold-review [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--input PATH` | Reviewed salvation relationship packet; repeat for each packet.  [default: evaluation/sermon-topics/salvation-relationships-review-v2.json, evaluation/sermon-topics/salvation-relationships-review-v3.json] | no | evaluation/sermon-topics/salvation-relationships-review-v2.json, evaluation/sermon-topics/salvation-relationships-review-v3.json |
| `--candidate-threshold FLOAT RANGE` | Proposed probability boundary for affirmative leaf observations.  [default: 0.7; 0.01<=x<=0.99] | no | 0.7 |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-observation-threshold-review-v1.json] | no | evaluation/sermon-topics/salvation-observation-threshold-review-v1.json |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-observation-boundaries-review`

Build a provider-free focused review for per-relationship salvation leaf boundaries.

#### Usage

```console
pte analysis salvation-observation-boundaries-review [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--input PATH` | Reviewed salvation relationship packet; repeat for each packet.  [default: evaluation/sermon-topics/salvation-relationships-review-v2.json, evaluation/sermon-topics/salvation-relationships-review-v3.json] | no | evaluation/sermon-topics/salvation-relationships-review-v2.json, evaluation/sermon-topics/salvation-relationships-review-v3.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-observation-boundaries-review-v1.json] | no | evaluation/sermon-topics/salvation-observation-boundaries-review-v1.json |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-collected-observations-review`

Build a provider-free boundary review from collected salvation observations.

#### Usage

```console
pte analysis salvation-collected-observations-review [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying ordinary classification artifacts.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-collected-observations-review-v2.json] | no | evaluation/sermon-topics/salvation-collected-observations-review-v2.json |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-conversion-recalibration`

Build the provider-free conversion-only boundary ordering check.

#### Usage

```console
pte analysis salvation-conversion-recalibration [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying ordinary classification artifacts.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--prior-review PATH` | Reviewed current collected-observation packet.  [default: evaluation/sermon-topics/salvation-collected-observations-review-v2.json] | no | evaluation/sermon-topics/salvation-collected-observations-review-v2.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-conversion-recalibration-v1.json] | no | evaluation/sermon-topics/salvation-conversion-recalibration-v1.json |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-final-collection-check`

Build the provider-free final check for four localized leaf boundaries.

#### Usage

```console
pte analysis salvation-final-collection-check [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying ordinary classification artifacts.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--prior-review PATH` | Reviewed ordinary-classification boundary packet.  [default: evaluation/sermon-topics/salvation-collected-observations-review-v2.json] | no | evaluation/sermon-topics/salvation-collected-observations-review-v2.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-final-collection-check-v1.json] | no | evaluation/sermon-topics/salvation-final-collection-check-v1.json |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-collection-recalibration`

Build a provider-free follow-up for the four unsettled salvation leaves.

#### Usage

```console
pte analysis salvation-collection-recalibration [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying ordinary classification artifacts.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--prior-review PATH` | Reviewed ordinary-classification boundary packet.  [default: evaluation/sermon-topics/salvation-collected-observations-review-v2.json] | no | evaluation/sermon-topics/salvation-collected-observations-review-v2.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-collection-recalibration-v1.json] | no | evaluation/sermon-topics/salvation-collection-recalibration-v1.json |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis salvation-boundary-recalibration`

Build a provider-free focused review for four disputed salvation leaves.

#### Usage

```console
pte analysis salvation-boundary-recalibration [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--cohort PATH` | Ready frozen topic cohort supplying ordinary classification artifacts.  [default: /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json] | no | /Users/briancummings/code/pastor-transcript-extractor/evaluation/sermon-topics/stage4-stability-cohort-v1.json |
| `--prior-review PATH` | Reviewed ordinary-classification boundary packet.  [default: evaluation/sermon-topics/salvation-collected-observations-review-v2.json] | no | evaluation/sermon-topics/salvation-collected-observations-review-v2.json |
| `--output PATH` | Fingerprint-bound JSON packet path; Markdown is written beside it.  [default: evaluation/sermon-topics/salvation-boundary-recalibration-v1.json] | no | evaluation/sermon-topics/salvation-boundary-recalibration-v1.json |
| `--base-dir PATH` | Application-data directory containing app.db; pass the directory, not the database file. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis evaluate-topic-behavior`

Run or validate the bounded synthetic TypeSafe topic behavior contract.

#### Usage

```console
pte analysis evaluate-topic-behavior [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--fixture PATH` | Frozen synthetic topic fixture JSON.  [default: evaluation/sermon-topics/behavior-contract-v1.json] | no | evaluation/sermon-topics/behavior-contract-v1.json |
| `--model TEXT` | Pinned TypeSafe model id.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--cache-dir PATH` | Content-addressed answer cache; defaults beside the fixture. | no | — |
| `--output PATH` | Result JSON path; Markdown is written beside it. | no | — |
| `--timeout-seconds FLOAT RANGE` | Provider timeout for an uncached request.  [default: 45.0; x>=1.0] | no | 45.0 |
| `--validate-only` | Validate frozen coverage without calling TypeSafe or writing results. | no | False |
| `--help` | Show this message and exit. | no | — |

### `pte analysis show`

Inspect persisted sermon measurements and Scripture evidence.

#### Usage

```console
pte analysis show [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--video-id INTEGER` | Database video id. | no | — |
| `--youtube-video-id TEXT` | YouTube video id. | no | — |
| `--profile-id INTEGER` | Canonical speaker profile id; selects effectively attached sermons. | no | — |
| `--pastor TEXT` | Compatibility alias resolved through the pastor's speaker-profile binding. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis summarize-profile`

Materialize a deterministic Scripture-usage summary for a speaker profile.

#### Usage

```console
pte analysis summarize-profile [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--profile-id INTEGER` | Speaker profile id.  [required] | yes | — |
| `--analyzer-version TEXT` | Profile analyzer version recorded in provenance.  [default: 4] | no | 4 |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis show-profile`

Inspect the latest materialized Scripture summary for a speaker profile.

#### Usage

```console
pte analysis show-profile [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--profile-id INTEGER` | Speaker profile id.  [required] | yes | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis evaluate-scripture-detector`

Evaluate explicit and contextual detection against the reviewed fixture.

#### Usage

```console
pte analysis evaluate-scripture-detector [OPTIONS] [FIXTURE]
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `[FIXTURE]` | Reviewed Scripture-reference evaluation fixture.  [default: evaluation/scripture-references/contextual-v1.json] | no | evaluation/scripture-references/contextual-v1.json |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte analysis evaluate-scripture-alignment`

Evaluate conservative Bible-text alignment against the reviewed fixture.

#### Usage

```console
pte analysis evaluate-scripture-alignment [OPTIONS] [FIXTURE]
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `[FIXTURE]` | Reviewed Scripture-text alignment evaluation fixture.  [default: evaluation/scripture-alignments/reviewed-v1.json] | no | evaluation/scripture-alignments/reviewed-v1.json |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte analysis structure-run`

Measure deterministic transcript stylometry and sermon organization.

#### Usage

```console
pte analysis structure-run [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--video-id INTEGER` | — | no | — |
| `--youtube-video-id TEXT` | — | no | — |
| `--profile-id INTEGER` | — | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis structure-show`

Inspect deterministic structure measurements.

#### Usage

```console
pte analysis structure-show [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--youtube-video-id TEXT` | — | no | — |
| `--profile-id INTEGER` | — | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis structure-readiness`

Report structure analysis readiness.

#### Usage

```console
pte analysis structure-readiness [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--json` | — | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis structure-backfill`

Safely backfill current deterministic structure runs and profile summaries.

#### Usage

```console
pte analysis structure-backfill [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--minimum-sermons INTEGER RANGE` | [default: 3; x>=1] | no | 3 |
| `--dry-run` | — | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis structure-population-build`

Freeze structure population diagnostics.

#### Usage

```console
pte analysis structure-population-build [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--minimum-sermons INTEGER RANGE` | [default: 3; x>=2] | no | 3 |
| `--json` | — | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis structure-population-show`

Inspect a structure population snapshot.

#### Usage

```console
pte analysis structure-population-show [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--snapshot-id INTEGER` | — | no | — |
| `--json` | — | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis style-run`

Generate validated style support and candidate runs for a sermon or profile.

#### Usage

```console
pte analysis style-run [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--video-id INTEGER` | Database video id. | no | — |
| `--youtube-video-id TEXT` | YouTube video id. | no | — |
| `--profile-id INTEGER` | Speaker profile id. | no | — |
| `--pastor TEXT` | Compatibility profile alias. | no | — |
| `--model TEXT` | Override configured Ollama model. | no | — |
| `--analyzer-version TEXT` | Semantic analyzer version.  [default: 3] | no | 3 |
| `--prompt-version TEXT` | Semantic prompt version.  [default: sermon-style-runs-v1] | no | sermon-style-runs-v1 |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis style-show`

Inspect persisted semantic style evidence and measurements.

#### Usage

```console
pte analysis style-show [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--video-id INTEGER` | Database video id. | no | — |
| `--youtube-video-id TEXT` | YouTube video id. | no | — |
| `--profile-id INTEGER` | Speaker profile id. | no | — |
| `--pastor TEXT` | Compatibility profile alias. | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis style-summarize-profile`

Materialize a profile summary from accepted sermon style evidence.

#### Usage

```console
pte analysis style-summarize-profile [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--profile-id INTEGER` | Speaker profile id.  [required] | yes | — |
| `--analyzer-version TEXT` | Style profile analyzer version.  [default: 4] | no | 4 |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis style-show-profile`

Inspect the latest materialized style profile.

#### Usage

```console
pte analysis style-show-profile [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--profile-id INTEGER` | Speaker profile id.  [required] | yes | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis style-review-create`

Create a full-sermon style-run adjudication packet.

#### Usage

```console
pte analysis style-review-create [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--youtube-video-id TEXT` | YouTube video id.  [required] | yes | — |
| `--output PATH` | Review draft JSON path.  [required] | yes | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis style-review-finalize`

Validate an edited style review draft and mark it reviewed.

#### Usage

```console
pte analysis style-review-finalize [OPTIONS] DRAFT
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `DRAFT` | Edited review draft JSON.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--output PATH` | Final reviewed JSON path.  [required] | yes | — |
| `--reviewer TEXT` | Reviewer identity.  [required] | yes | — |
| `--help` | Show this message and exit. | no | — |

### `pte analysis evaluate-style-boundaries`

Evaluate run detection and boundaries from full-sermon reviewed packets.

#### Usage

```console
pte analysis evaluate-style-boundaries [OPTIONS] REVIEWS...
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `REVIEWS...` | Reviewed style packet JSON files.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte analysis evaluate-style`

Evaluate the configured semantic style model on reviewed cases.

#### Usage

```console
pte analysis evaluate-style [OPTIONS] [FIXTURE]
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `[FIXTURE]` | Reviewed style fixture.  [default: evaluation/sermon-style/reviewed-v2.json] | no | evaluation/sermon-style/reviewed-v2.json |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--model TEXT` | Override configured Ollama model. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte source-ownership`

Migrate and audit source ownership data.

### Usage

```console
pte source-ownership [OPTIONS] COMMAND [ARGS]...
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte source-ownership migrate`

Apply or preview the replayable source-ownership migration.

#### Usage

```console
pte source-ownership migrate [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--dry-run` | Run the migration and audit inside a rolled-back savepoint. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte source-ownership audit`

Validate organization, target-context, and artifact-namespace projections.

#### Usage

```console
pte source-ownership audit [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--strict` | Exit unsuccessfully when any ownership invariant fails. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte benchmark`

Manage reviewed profile reference panels.

### Usage

```console
pte benchmark [OPTIONS] COMMAND [ARGS]...
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte benchmark recording-verifier-typesafe`

Run the shadow-only TypeSafe/Jev recording-verifier benchmark.

#### Usage

```console
pte benchmark recording-verifier-typesafe [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--model TEXT` | Exact versioned TypeSafe model ID.  [default: jev-1.13.0] | no | jev-1.13.0 |
| `--partition TEXT` | Fixture partition; repeat to include more than one.  [default: development, legacy] | no | development, legacy |
| `--output-dir PATH` | Directory for timestamped shadow reports and cache.  [required] | yes | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--fixture-dir PATH` | Reviewed fixture directory (read only).  [default: evaluation/fixtures] | no | evaluation/fixtures |
| `--confirm-frozen-policy` | Required before accessing held_out fixtures. | no | False |
| `--cost-rate-version TEXT` | Version label for supplied token prices.  [default: typesafe-jev-rate-unconfigured-v1] | no | typesafe-jev-rate-unconfigured-v1 |
| `--input-usd-per-million FLOAT RANGE` | Optional input-token price in USD per million.  [x>=0] | no | — |
| `--output-usd-per-million FLOAT RANGE` | Optional output-token price in USD per million.  [x>=0] | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte benchmark create`

Create an idempotent named reference panel.

#### Usage

```console
pte benchmark create [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--key TEXT` | Stable lowercase panel key.  [required] | yes | — |
| `--name TEXT` | Panel display name.  [required] | yes | — |
| `--description TEXT` | Panel purpose.  [required] | yes | — |
| `--provenance TEXT` | How this analytical selection originated.  [default: manual-review] | no | manual-review |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte benchmark add-profile`

Append a reviewed profile attachment event.

#### Usage

```console
pte benchmark add-profile [OPTIONS] PANEL_KEY
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `PANEL_KEY` | Reference panel key.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--profile-id INTEGER` | Speaker profile id.  [required] | yes | — |
| `--reviewer TEXT` | Reviewer name.  [required] | yes | — |
| `--reason TEXT` | Selection rationale.  [required] | yes | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte benchmark remove-profile`

Append a reviewed profile detachment event.

#### Usage

```console
pte benchmark remove-profile [OPTIONS] PANEL_KEY
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `PANEL_KEY` | Reference panel key.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--profile-id INTEGER` | Speaker profile id.  [required] | yes | — |
| `--reviewer TEXT` | Reviewer name.  [required] | yes | — |
| `--reason TEXT` | Removal rationale.  [required] | yes | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte benchmark list`

List named reference panels.

#### Usage

```console
pte benchmark list [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte benchmark show`

Inspect panel metadata and effective membership.

#### Usage

```console
pte benchmark show [OPTIONS] PANEL_KEY
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `PANEL_KEY` | Reference panel key.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte benchmark build`

Build or reuse an immutable panel snapshot.

#### Usage

```console
pte benchmark build [OPTIONS] PANEL_KEY
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `PANEL_KEY` | Reference panel key.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--min-analyzed-sermons INTEGER` | [default: 5] | no | 5 |
| `--min-total-words INTEGER` | [default: 10000] | no | 10000 |
| `--min-coverage FLOAT` | [default: 0.8] | no | 0.8 |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte benchmark show-snapshot`

Inspect the latest immutable panel snapshot.

#### Usage

```console
pte benchmark show-snapshot [OPTIONS] PANEL_KEY
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `PANEL_KEY` | Reference panel key.  [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--json` | Emit stable JSON and feature matrix. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte benchmark compare`

Compare one profile with an immutable Scripture reference-panel snapshot.

#### Usage

```console
pte benchmark compare [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--profile-id INTEGER` | Candidate speaker profile.  [required] | yes | — |
| `--panel TEXT` | Reference panel key.  [required] | yes | — |
| `--snapshot-id INTEGER` | Use an exact panel snapshot instead of the latest. | no | — |
| `--comparison-level TEXT` | Fixed experimental scope: core or full.  [default: core] | no | core |
| `--historical-references` | Explicitly pin historical reference inputs; requires --snapshot-id. | no | False |
| `--limit INTEGER RANGE` | Nearest references to show.  [default: 5; x>=1] | no | 5 |
| `--json` | Emit the durable result JSON. | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte storage`

Compact, verify, and restore generated storage.

### Usage

```console
pte storage [OPTIONS] COMMAND [ARGS]...
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte storage compact`

Apply explicit retention: discard old diagnostics and archive cache candidates.

#### Usage

```console
pte storage compact [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--apply / --dry-run` | Apply; dry-run is default.  [default: dry-run] | no | False |
| `--archive-root PATH` | Artifact archive root. By default, reuse the configured media archive destination beneath evaluation-storage/. | no | — |
| `--keep-diagnostic-runs INTEGER RANGE` | [default: 3; x>=1] | no | 3 |
| `--repo-root PATH` | [default: /Users/briancummings/code/pastor-transcript-extractor] | no | /Users/briancummings/code/pastor-transcript-extractor |
| `--manifest PATH` | — | no | — |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

### `pte storage verify`

Verify a self-describing storage archive and every member hash.

#### Usage

```console
pte storage verify [OPTIONS] ARCHIVE
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `ARCHIVE` | [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte storage restore`

Plan or restore every member of a verified storage archive.

#### Usage

```console
pte storage restore [OPTIONS] ARCHIVE
```

#### Arguments

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `ARCHIVE` | [required] | yes | — |

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--apply / --dry-run` | [default: dry-run] | no | False |
| `--base-dir PATH` | Override app data directory. | no | — |
| `--help` | Show this message and exit. | no | — |

## `pte docs`

Generate documentation from the CLI definition.

### Usage

```console
pte docs [OPTIONS] COMMAND [ARGS]...
```

### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `--help` | Show this message and exit. | no | — |

### `pte docs cli`

Generate a consolidated Markdown reference for the complete CLI.

#### Usage

```console
pte docs cli [OPTIONS]
```

#### Options

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `-o, --output PATH` | Destination Markdown file.  [default: docs/CLI_REFERENCE.md] | no | docs/CLI_REFERENCE.md |
| `--help` | Show this message and exit. | no | — |
