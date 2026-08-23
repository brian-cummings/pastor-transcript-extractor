# Pastor Transcript Extractor

Reference panels and immutable Scripture-usage benchmark snapshots are documented in
[`docs/reference-benchmarking.md`](docs/reference-benchmarking.md).

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
- publishing organization persistence and external provenance
- temporal pastor-to-organization affiliations
- explicit source/video target contexts independent of publisher ownership
- immutable per-video artifact namespaces
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

- `yt-dlp` with its default EJS challenge-solver dependencies

YouTube extraction also requires a supported JavaScript runtime. PTE detects
Deno, Node, or QuickJS automatically (in that order). Override the detected
runtime when needed with, for example:

```bash
export PTE_YT_DLP_JS_RUNTIMES="node:/opt/homebrew/bin/node"
```

Run `pte doctor` to verify both the runtime and EJS solver before processing
videos.

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

Generate the read-only per-source processing report from the configured app
database:

```bash
pte source-processing-report \
  --markdown source_processing_report.md \
  --json source_processing_report.json
```

To report from an explicit database instead, use `--database`:

```bash
pte source-processing-report \
  --database /Users/briancummings/Documents/PastorSearchData/app.db \
  --markdown source_processing_report.md \
  --json source_processing_report.json
```

## Workflows

- `pte run <url> --pastor <slug>` runs discovery, caption fetch, optional local
  transcription, adaptive extraction, isolated-sermon audio assurance, configured
  source archival, and pastor review export.
- `pte run --all` performs the same workflow for every processing-enabled
  source and writes one review per pastor. Sources disabled with
  `pte source disable` are excluded. `--all` selects sources; it does not mean
  every cataloged video or unlimited discovery. By default, each enabled source
  contributes its newest 26 eligible discovered videos to that run.
- `pte run --all --all-videos` removes the per-source discovery limit for every
  processing-enabled source.
- `pte source disable <source-id>` excludes a source from all-source processing;
  `pte source enable <source-id>` restores it. An explicit
  `pte run --source-id <source-id>` remains an intentional override.
- `pte run --source-id 12 --source-id 19` performs the workflow for exactly the
  listed existing sources. Repeat `--source-id` for each source.
- `pte run --failed-only` retries failed videos across all sources while
  preserving successful transcript and extraction artifacts.
- `pte run --all --stage-offline-inputs` downloads immutable source audio and
  available captions, then writes a checksum-pinned manifest for a later offline
  `--resume-stage` run. `--stage-audio-only` remains an alias.
- `pte run <url> --pastor <slug> --skip-review` skips review export after
  extraction, audio assurance, and configured source archival.
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
Videos with a known duration below the universal sermon minimum, along with
scheduled future events, are bypassed before the per-source discovery limit is
applied, so they do not consume download slots. The same policy prevents caption
acquisition, local ASR, extraction, and reclassification of already-discovered
ineligible videos. Unknown durations remain eligible unless the publication
timestamp is in the future. The default is 12 minutes; configure it once for
every workflow:

```bash
export PTE_MIN_SERMON_DURATION_SECONDS=720
```

Imported channel-identity or publisher-association conflicts are never silently
overwritten.

Imported church identities now create publishing organizations and source
associations. Imported pastor names are retained as provenance-grounded,
unreviewed affiliation claims; they do not automatically create pastor records,
speaker profiles, affiliations, or speaker membership. A changed pastor name
appends evidence, while a changed resolved channel identity remains a manual
reconciliation conflict.

## Organizations and source ownership

Publishing ownership is independent of pastor query context:

```bash
pte organization add sample-church "Sample Church" --type church
pte source add 'https://www.youtube.com/@samplechurch' --organization sample-church
pte source add 'https://www.youtube.com/@unknownpublisher'
pte source set-organization 12 sample-church
pte pastor affiliate pastor-a sample-church --role "Senior Pastor" --status current
```

The legacy `pte add URL --pastor SLUG` workflow remains supported. Its pastor is
now an explicit target-policy compatibility projection, not the source's
publisher. See [docs/SOURCE_OWNERSHIP.md](docs/SOURCE_OWNERSHIP.md) for the
schema semantics, migration audit, and production-copy validation commands.

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

An approved fixture does not change production artifacts by itself. For a
reviewed positive fixture containing one continuous sermon span, explicitly
promote its timestamps through the production and speaker-evidence pipeline:

```bash
pte review-ground-truth YOUTUBE_VIDEO_ID \
  --reviewer "Brian Cummings" \
  --open-video \
  --base-dir /path/to/app-data

caffeinate pte apply-fixture-correction YOUTUBE_VIDEO_ID \
  --fixture-dir evaluation/fixtures \
  --base-dir /path/to/app-data
```

`apply-fixture-correction` validates the exact fixture, writes an auditable
`review/window_override.json`, force-reclassifies only that existing extraction
using cached inference where possible, and persists a speaker observation whose
window and fingerprint match the corrected extraction. It reports the previous
and current fingerprints plus automatic pair-selection eligibility. Historical
observations remain immutable and become stale automatically. The command fails
closed for negative fixtures, multiple retained spans, or allowed interruptions,
because those cases cannot be represented faithfully by one observation window.

Speaker reviews marked `multiple_speakers` or `invalid_audio` remain attached
to their exact immutable observation window; they do not reject every future
window from the same recording. Audit current negative windows without changing
data, then review the highest-priority current window:

```bash
pte identity audit-speaker-negative-windows \
  --base-dir /Users/briancummings/Documents/PastorSearchData

pte identity review-next-speaker-negative-window \
  --reviewer "Brian Cummings" \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The queue prioritizes broad and recording-edge windows, excludes observations
already superseded by a corrected extraction, and prints the exact
`apply-fixture-correction` command after a continuous sermon fixture is approved.
Repeat review and correction until the audit reports no actionable windows, then
run `pte identity run --base-dir ...` to refresh identity candidates.

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

Run a selected group of configured sources:

```bash
pte run --source-id 12 --source-id 19 \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Stage network-dependent inputs while on a fast connection, then process exactly
that batch offline. Staging downloads immutable source audio, reuses the existing
caption acquisition to persist any available YouTube captions, and stops before
normalization, Whisper, extraction, review, and archival. The resume command
verifies every staged audio artifact and disables network download fallback:

```bash
pte run --all \
  --stage-offline-inputs \
  --download-jobs 6 \
  --base-dir /Users/briancummings/Documents/PastorSearchData

# Use the exact manifest path printed by the staging command.
pte run \
  --resume-stage /Users/briancummings/Documents/PastorSearchData/logs/audio-stages/STAGE_FINGERPRINT.json \
  --acquire-captions \
  --jobs 2 \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Use `--acquire-captions` when the resume machine is online. It runs the existing
caption acquisition over the exact verified manifest scope before local ASR, so
Whisper only handles remaining caption misses. Large caption batches wait five
seconds between requests and retry infrequent YouTube 429 responses with bounded
backoff. Repeated rate limiting stops cleanly; rerunning later skips captions
already persisted. Omit the option for a fully offline run.

The legacy `--stage-audio-only` spelling remains an alias. The same staging
option works with a URL plus `--pastor`, or with one or more `--source-id`
values. Re-running staging reuses verified source and caption artifacts and only
downloads missing inputs.

To complete extraction and media maintenance without creating or refreshing
review exports:

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

Extraction now creates an identity-neutral principal-speaker observation for
every valid sermon window, including organization-owned imported videos that
have no preselected pastor. Those targetless observations retain grounded name
claims and can enter speaker-pair/profile workflows without creating a pastor
profile or treating publisher context as identity proof. When a pastor target is
present, the existing target-specific shadow assessment is added as a separate
compatibility projection.

Video target context is explicitly recorded as an expectation, not proof that
the requested pastor delivered the sermon. Publishing organization and pastor
affiliation are not identity proof. Manual sermon-window overrides apply only
to content boundaries and do not suppress guest-speaker concerns.

Automatic speaker-pair nomination is limited to current, accepted sermon
observations. `pte identity review-next-speaker-pair` requires a readable latest
extraction whose top-level disposition is `accepted_sermon`, an observation
from that extraction with boundaries matching its current sermon window,
usable diagnostic spans, and verified normalized media. Review-required,
rejected, malformed, and stale observations are excluded conservatively.
Explicit `review-speaker-pair` requests remain a manual workflow.

Prewarm deterministic review clips and unchanged-file media-verification
receipts before a validation review session:

```bash
pte identity prepare-speaker-review-audio \
  --evaluation-scope validation \
  --base-dir /path/to/app-data
```

This cache-only operation creates no pair drafts, reviews, fixtures, registry
memberships, or identity claims.

To prepare the observations most likely to be selected for profile growth or
automation-readiness review, use the selector-aware bounded prewarmer:

```bash
pte identity prepare-actionable-review-audio \
  --limit 24 \
  --base-dir /path/to/app-data
```

It prioritizes current association confirmations, discovery frontiers, and
acoustic growth nominations, then prepares the exact activity-qualified clips
used by blinded review. It creates no draft and does not consume a nomination.

Backfill neutral speaker observations and, where a pastor target exists, shadow
identity artifacts for existing extractions without invoking classification or
rewriting sermon artifacts:

```bash
pte identity backfill --base-dir /path/to/app-data
```

Audit end-to-end association coverage after backfill or association runs:

```bash
pte identity association-audit \
  --base-dir /path/to/app-data
```

The audit writes an immutable, content-addressed report under
`logs/association-audits/` and exits nonzero unless every latest extraction is
accounted for. Accepted sermons must have a current observation that is already
profiled, has a valid association attempt from the required policy, or has an
explicit blocker such as unavailable verified media. Rejected and
review-required content is recorded as content-terminal. Failed attempts,
missing/stale observations, stale-policy attempts, and eligible observations
without an attempt are gaps. Invalid association artifacts also fail strict
mode. Association attempts produced by the legacy non-speech-grounded sampler
are stale; current attempts must use the versioned transcript-grounded span
contract. Accepted observations without enough meaningful sermon-labeled text
are recorded as an explicit blocker. Use `--allow-gaps` only when collecting a
baseline report.

Current transcript-grounded sampling oversamples up to fifteen distributed
sermon-speech candidates, measures speech activity relative to the recording,
and embeds five qualified clips. Distribution remains primary. Only when those
five are internally inconsistent may a fallback replace up to two outliers
from the remaining qualified candidates, minimizing lost temporal coverage and
using no target-profile evidence. If no coherent repair exists, normal policy
abstention remains in force. This prevents quiet recordings and low-activity
sermon edges from being mislabeled as unusable acoustic evidence without
silently selecting clips to fit a profile.
When a coherent repair replaces a clip within the first or last 10% of the
sermon window, the association artifact and CLI record a
`speaker_inconsistent_edge` sermon-window quality flag with the exact span.
The flag is diagnostic and can nominate boundary review; it never changes the
window, disposition, or profile membership automatically.

Coordinate the shadow identity state for one new extraction:

```bash
pte identity coordinate \
  --youtube-video-id YOUTUBE_ID \
  --base-dir /path/to/app-data
```

This read-only mode combines strict association coverage, current proposal
state, provisional confirmation opportunities, and the next required action
into one content-addressed report under `logs/identity-coordination/`. Add
`--execute-shadow` to run a missing association for that one extraction before
reconciling the report. It never promotes components, confirms memberships, or
performs any other registry mutation. Use `--all` for a read-only corpus-wide
action inventory. The coordinator loads the newest current discovery artifact so
previously evaluated observations wait for new evidence instead of repeatedly
requesting the same batch. Only observations absent from that artifact request
discovery. Anonymous profile discovery remains a separately scheduled batch
because a single extraction cannot establish a three-recording component.

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
redirects require append-only review events. A shadow profile-discovery backend
can now propose conservative anonymous components, but it cannot mutate the
registry.

Inspect profile-discovery coverage without acoustic execution:

```bash
pte identity shadow-discover-profiles \
  --plan-only \
  --base-dir /path/to/app-data
```

Execute the shadow discovery pass by omitting `--plan-only`. It prepares one
deterministic acoustic signature per eligible unassigned observation from five
distributed 12-second spans grounded in meaningful sermon-labeled transcript
text. The same exact spans are reused in every pair decision. It then nominates a
bounded strong-only global nearest-neighbor graph plus source-local retrieval.
Small source groups receive complete pair coverage; large source groups use a
per-observation quota. Source is recorded as retrieval context and never counts
as identity evidence. A guarded `[0.50, 0.60)` deferred closure may test a third
candidate only against an existing strong same-speaker seed, and both endpoint
comparisons must acoustically agree before either identity edge is admitted. It
applies the pinned pair policy and proposes a
provisional anonymous profile only for a complete-link same-speaker component
with at least three distinct recordings. Non-speech/repetitive transcript
regions, reviewed different-speaker constraints, unresolved required
comparisons, and conflicting explicit names block or exclude evidence.
Versioned artifacts are written below
`evaluation/speaker-profile-discovery/shadow-runs/`; registry mutations remain
zero. Artifacts report global, source-local, strong closure, and guarded deferred
counts separately and expose near-same ambiguous edges for blinded review.
One-edge frontiers are reviewed first. Strong candidates with two ambiguous seed
links enter a bounded staged frontier: the weaker bottleneck is reviewed first,
and only a durable same-speaker judgment plus a new discovery run can expose the
companion edge. Staged review is additionally capped at `0.15` distance from the
same-speaker boundary; farther ambiguous results remain recorded as non-actionable
instead of consuming human review. This review-efficiency limit does not change
the acoustic same/different thresholds. `profile-status` reports immediate,
staged, and distant-only component counts, and `automation-readiness` prioritizes
only the actionable visual-confirmation reviews.
A calibrated observation-consistency report can be supplied with
`--consistency-report` and `--minimum-consistency-score`.

Verified components enter a reversible candidate loop with
`pte identity promote-discovered-profiles --discovery-report <artifact>`.
Without `--apply` it reports the exact qualifying components. With `--apply`,
it creates stable provisional profiles and attaches their complete-link seed
observations. Those profiles participate in subsequent shadow association but
remain automatic-blocked until `pte identity confirm-discovered-profiles`
accepts a current multi-exemplar proposal from an independent recording.
While confirmation is pending, a provisional discovery profile remains
source-local or attribution-routed instead of becoming a global comparison
target. Confirmation work therefore avoids comparing every unrelated sermon
against every newly promoted profile.
Confirmation is also plan-only unless `--apply` is passed; acoustic
model/policy approval remains a separate gate.

Reviewed two-recording profiles may participate as `review_ready` comparison
targets before they are shadow-ready when source-local or attribution routing
supports the comparison. A resulting proposal can nominate the ordinary
blinded human pair workflow, but cannot create a machine assignment; automatic
assignment still requires the stronger automatic-profile-ready gate.
Conservative leading title credits such as `Andy Crosby - Genuine Conversion`
are derived at selection time as attribution hints. They do not rewrite speaker
observations and may route review, but never establish profile membership or an
expected pair answer.

Configured pastor profiles with no reviewed observations are bootstrapped only
through `profile-growth` human review. Two source-local title matches, or one
title match plus cached same-speaker acoustic support, may nominate a blinded
pair. A full configured name or an honorific plus its source-local surname
(`Pastor Baciu`) is a nomination hint only. It is not persisted as attribution,
does not attach either observation, and cannot determine the review answer.

When explicit attribution places a provisional discovery profile beside an
established profile for the same configured pastor, normal `profile-growth`
review nominates a cross-profile bridge. A confirmed same-speaker judgment lets
reviewed-evidence sync move the provisional members into the established linked
profile and retire the discovery profile with an append-only redirect. The
linked profile is preserved as canonical; multiple configured identities and
reviewed different-speaker constraints block consolidation.

## Commands

- `pte init`
- `pte add <url> --pastor <pastor-slug>` (legacy target compatibility)
- `pte organization add <slug> <display-name>`
- `pte organization list`
- `pte organization review <slug>`
- `pte source add <url> [--organization <slug>] [--target-pastor <slug>]`
- `pte source set-organization <source-id> <organization-slug>`
- `pte source clear-organization <source-id>`
- `pte pastor affiliate <pastor-slug> <organization-slug>`
- `pte organization claims [--organization <slug>]`
- `pte pastor affiliate-claim <pastor-slug> <claim-id>`
- `pte organization reject-affiliation-claim <claim-id>`
- `pte source-ownership migrate [--dry-run]`
- `pte source-ownership audit --strict`
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
- `pte run <url> --pastor <pastor-slug> --identity`
- `pte run --all`
- `pte run --source-id <id> --source-id <id>`
- `pte run <url> --pastor <pastor-slug> --skip-review`
- `pte video exclude <video-id>`
- `pte video unexclude <youtube-video-id>`
- `pte video excluded`
- `pte pastor add <slug> <display-name>`
- `pte pastor list`
- `pte identity profile-status --base-dir <app-data>`
- `pte identity association-audit --base-dir <app-data>`
- `pte identity coordinate --all --base-dir <app-data>`
- `pte identity coordinate --youtube-video-id <id> --execute-shadow --base-dir <app-data>`
- `pte identity shadow-discover-profiles --plan-only --base-dir <app-data>`
- `pte identity review-next-speaker-pair --selection-objective profile-growth`
- `pte identity review-next-speaker-pair --selection-objective automation-readiness`
- `pte identity sync-reviewed-speaker-evidence --base-dir <app-data>`
- `pte identity shadow-associate-speakers --all-eligible --plan-only`
- `pte identity shadow-association-status --base-dir <app-data>`
- `pte identity machine-assignment-status --base-dir <app-data>`
- `pte identity rollback-machine-assignments --policy-fingerprint <sha256>`

`automation-readiness` reuses the normal blinded pair-review packet. It first
selects an exact candidate-to-profile edge from a current multi-exemplar shadow
association proposal when available, then an immediate near-same edge that can
complete a blocked component, then
a staged bottleneck edge from a strong two-ambiguity bundle, then a decisive
unresolved overlap edge. It finally falls back to reviewed-profile reinforcement
and positive-evidence profile growth. Profile growth first requires either an
explicit attribution shared across reviewed components or an exact,
provenance-bound cached same-speaker acoustic ranking. When those signals are
exhausted, its human-review-only exploratory tier may nominate an unreviewed
`strong_strong` pair that the model classified as `insufficient_evidence` due
to ambiguous similarity. Merely lacking a known different-speaker constraint—and
merely sharing a source—is still not enough. Automation-readiness does not use
the exploratory tier. The selection manifest records the discovery artifact,
stage, companion edge, and downstream observations unlocked; undersized
two-recording seeds without a qualified frontier wait instead of consuming human
review. The next discovery run consumes the approved pair judgment directly as
a fingerprinted same/different constraint, allowing the answer to resolve or
safely block the affected component before registry synchronization.

Automatic nomination also binds packet preparation to the selector's exact
immutable observation fingerprints. The review command fails closed if either
fingerprint no longer belongs to the selected video, preventing a newer
observation for the same recording from silently replacing the nominated
evidence. Reviewed and drafted exclusions likewise apply to the exact immutable
fingerprint pair, not permanently to the two videos: if sermon reclassification
creates replacement observations, their new pair may be reviewed while the old
pair remains excluded. Video reuse is still counted and deprioritized by the
normal ranking policy. Audit current and legacy selection provenance without
mutation with `pte identity audit-speaker-review-selection`.

`profile-growth` has a precision-first nomination tier when a verified
discovery artifact contains an unreviewed `strong_strong` pair in the pinned
same-speaker band. It ranks otherwise-valid growth pairs by acoustic margin and
centroid similarity. Only after positive-evidence candidates are exhausted, a
second tier ranks provenance-bound `ambiguous_similarity` results for blinded
human review only while they remain within 0.15 of the pinned same-speaker
boundary. Their acoustic outcome remains `insufficient_evidence`; they do
not receive an expected answer or become profile membership. Every cached result
is recorded in the selection manifest as `review_ranking_only`; it is not
identity evidence, cannot attach observations, and cannot replace the blinded
human judgment. Reviewed different-speaker constraints and component safety
checks remain authoritative.

When a current shadow association cannot match an observation to an existing
profile, profile growth can also nominate its nearest unassociated discovery
neighbor. Source-local neighbors rank before global neighbors, and both
observations must still be unprofiled, reviewable, and free of reviewed
different-speaker conflicts. This is a bootstrap route for speakers whose
profiles do not exist yet, not a relaxed machine match: the acoustic result is
selection provenance only and remains hidden from the blinded packet. An
approved `same` judgment creates or joins the anonymous reviewed component; a
later reviewed bridge to an existing profile consolidates memberships through
the normal canonical-profile and redirect workflow. An approved `different`
judgment blocks that merge.

Exploratory rankings are also bound to the reviewed constraints captured by the
discovery artifact. After a new same/different judgment involving its
observations, rerun `pte identity run --all` before further exploratory review.
This lets discovery use a new same-speaker seed for closure retrieval instead of
walking down stale, increasingly distant comparisons.

`pte identity run` writes the shadow-association artifacts consumed by these
confirmation nominations. Content-oriented `pte run` can refresh the complete
identity workflow after extraction with `--identity`; this is explicit because
it launches a corpus acoustic pass. Association scores and expected outcomes
remain absent from the listening packet and never become durable identity
evidence without the approved blinded review.

Corpus association uses staged profile routing. Every same-source or explicit
name route is retained first, then cached observation centroids select up to
three additional global profiles for detailed multi-exemplar comparison. This
keeps cross-source guest and pastor matches possible without comparing every
candidate to every mature profile. A shortlisted proposal triggers a second
exhaustive validation pass before it is persisted; abstentions avoid that cost
and flow to nearest-unassociated review. The artifact records the route,
complete profile count, priority targets, shortlist, and whether the comparison
was exhaustive. As a fail-closed defense, any non-exhaustive proposal cannot
create machine-assignment evidence or automatically confirm a discovery
profile. Legacy exhaustive artifacts remain replayable.

Shadow association precomputes the complete content-addressed input fingerprint
before detailed profile comparison. If the candidate, accepted observation,
normalized media, selected spans, routing, profile exemplars, reviewed
constraints, model, and policy are unchanged, the existing verified artifact is
replayed and the acoustic comparisons are skipped. Re-running the consolidated
identity workflow is therefore idempotent at the association stage.

Aggregate association reports also seed a verified content-addressed cache of
individual candidate-to-exemplar diagnostics. Profile promotion or confirmation
may legitimately change routing and invalidate an aggregate report, but
unchanged acoustic edges are replayed independently; only comparisons against
new or changed exemplars execute. The first run after this cache is introduced
primes it from checksum-verified historical association artifacts. The routing
summary reports pair-cache hits and misses so incremental work is visible.

`pte identity profile-status` uses authoritative registered media metadata for
its read-only inventory; it does not stat or hash every local or SMB audio
artifact. Commands that select, compare, or consume audio continue to verify
the actual media bytes and fail closed when they are unavailable or corrupt.

The same run now projects qualifying current proposals into a separate,
append-only machine-evidence ledger. It requires a current accepted-sermon
observation, an automatic-profile-ready target, a unique multi-exemplar match,
no conflicting attribution or reviewed difference, and excludes held-out
fixture observations. The checked-in policy is shadow-only: it records
replayable evidence but creates neither reviewed membership nor an active
provisional assignment. `machine-assignment-status` reports evidence, active,
confirmed, revoked, and circuit-breaker state by exact policy fingerprint.
Historical association files are not bulk-imported: only artifacts produced or
reused by the current identity invocation can enter the ledger.

When grounded attribution leaves a reviewed voice profile unnamed, run
`pte identity review-profile-attribution --reviewer REVIEWER_ID`. The command
selects the largest unnamed canonical profile (or accepts `--profile-id`), opens
an HTML packet with representative member videos at their sermon timestamps,
and prompts for the backing video and speaker name. Approval creates and
attaches an append-only manual attribution claim. An exact unique configured
pastor-name match links its placeholder identity to the voice profile; unmatched
names remain attributed but unlinked, and existing links are never merged from
name similarity alone.

Run the complete identity layer independently with the same scope convention as
top-level `pte run`:

```bash
pte identity run YOUTUBE_VIDEO_ID --base-dir /path/to/app-data
pte identity run --all --base-dir /path/to/app-data
pte identity run --all --apply-automatic --base-dir /path/to/app-data
pte identity run --all --plan-only --base-dir /path/to/app-data
```

Execution first synchronizes already-reviewed speaker evidence, then chains
neutral-artifact backfill, shadow association, validated confirmation planning,
corpus discovery for `--all`, provisional-promotion planning, and a final
coordination audit. An executing `--all` run then prewarms exact review clips
for up to 24 actionable observations before normalized archival. Set
`--review-prewarm-limit 0` to disable this bounded stage or choose another
limit. Discovery and association remain shadow computations.
`--apply-automatic` applies validated confirmations and promotions and activates
eligible reversible human-on-loop assignments to automatic-ready profiles. The
older `--apply-confirmations`, `--apply-promotions`, and
`--apply-machine-canary` switches remain available for granular control. Human
pair review, profile attribution, conflicts, and policy changes are never
inferred by the runner. Use `--skip-discovery` when only association
reconciliation is wanted.

Provisional machine assignment is the human-on-loop path for sermons uniquely
matched to an automatic-ready profile. The checked-in policy pins the allowed
association-policy hash and model fingerprint, requires two agreeing exemplars,
rejects attribution conflicts, caps active assignments, and leaves every
assignment reversible. Activate it with the consolidated workflow:

```bash
pte identity run --all \
  --apply-automatic \
  --base-dir /path/to/app-data
```

Active provisional assignments remain outside reviewed profile membership and
cannot become acoustic exemplars. Automatic-ready profile proposals no longer
consume the normal blinded pair-review queue. Operators can inspect active and
evidence-only assignments with `machine-assignment-status`; stale or rejected
sermon observations are revoked conservatively, and reviewed contradictions
trip the exact policy fingerprint. Rollback is plan-only unless `--apply` is
passed. A different policy can still be supplied explicitly with
`--machine-assignment-policy`.

## Planning Docs

- `docs/V1_SPEC.md`
- `docs/HANDOFF.md`
- `evaluation/speaker-pairs/README.md` for the offline, abstention-first acoustic pair experiment
- `evaluation/speaker-associations/README.md` for non-mutating profile association
- `evaluation/speaker-profile-discovery/README.md` for non-mutating anonymous profile discovery
- `docs/MEDIA_FOUNDATION.md` for transcript-independent audio acquisition and migration
- `docs/SOURCE_OWNERSHIP.md` for publisher ownership, target contexts, and migration validation
- `docs/SERMON_ANALYSIS.md` for deterministic sermon measurements and Scripture evidence

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

After archival, audit remaining physical audio and safely replace only
byte-identical, checksum-verified archived duplicates with symlinks:

```bash
pte media sweep-audio \
  --report /tmp/pte-audio-sweep.json \
  --base-dir /Users/briancummings/Documents/PastorSearchData

pte media sweep-audio --apply \
  --report /tmp/pte-audio-sweep-applied.json \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The first command is read-only. Apply mode leaves unmatched, failed, pending,
and unverified files untouched. See `docs/MEDIA_FOUNDATION.md` for the complete
safety and offline semantics.

Prepare canonical speaker inputs explicitly, without requiring pair comparison,
discovery, or human review:

```bash
pte media prepare-canonical-audio --all-eligible --dry-run \
  --base-dir /Users/briancummings/Documents/PastorSearchData

pte media prepare-canonical-audio --all-eligible \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Preparation binds the authoritative normalized SHA-256 to the exact current
observation fingerprint, sermon window, and clip policy. It is idempotent and
is also performed automatically before normalized archival by
`pte identity run` and top-level `pte run --identity`/`--run-identity`.
