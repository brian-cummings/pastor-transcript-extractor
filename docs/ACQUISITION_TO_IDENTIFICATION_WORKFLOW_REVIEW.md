# Acquisition-to-Identification Workflow Review

## Executive summary

> Implementation update: the critical targetless-observation break identified in
> this review has since been fixed in the current workspace. Valid sermon
> extractions now create neutral speaker observations even when no pastor is
> preselected. The remaining production association and workflow-state findings
> still apply. A strict `pte identity association-audit` command now also writes
> a versioned coverage ledger and fails when an extraction or current observation
> is not accounted for.

The repository has strong individual components for YouTube acquisition, transcript
creation, sermon localization, evidence preservation, and conservative speaker
comparison. It does **not yet have one continuous production workflow** that takes a
newly acquired video through sermon detection, speaker identification, and durable
profile association.

The primary workflow break is structural:

1. `import-church-db` creates organizations, organization-owned sources, and
   unreviewed pastor affiliation claims, but intentionally does not create pastors,
   configured speaker profiles, or source target policies.
2. `sync-imported-sources` discovers, transcribes, and optionally extracts videos
   from those sources with `video.pastor_id = NULL`.
3. Extraction can localize the sermon without a pastor, but
   `_record_identity_shadow_safely` returns immediately when there is no pastor.
4. No `speaker_observation`, neutral name claim, or identity assessment is therefore
   created for the preferred bulk-import workflow.
5. Even where speaker observations do exist, acoustic association is a separate,
   manually invoked, non-mutating shadow experiment. Durable profile membership
   still comes only from reviewed pair evidence plus another explicit synchronization
   command.

As a result, the system can currently do either of these well:

- acquire and classify organization-owned recordings without identifying the
  speaker; or
- evaluate speaker identity for videos that were already assigned a target pastor.

It cannot yet start with an organization-owned video and independently determine
which known or new speaker profile delivered the sermon.

The recommended direction is to make sermon-speaker observations fully
identity-neutral, give each processing concern its own state, and introduce a
versioned association service that can automatically attach only high-confidence
matches while routing the small ambiguous remainder to a single actionable review
queue.

## Scope and method

This review traced the implemented paths rather than only the documented target
design. The principal entry points and modules reviewed were:

- acquisition and orchestration:
  `church_database_import.py`, `discovery.py`, `media.py`, `transcription.py`,
  `media_artifacts.py`, and the `sync-imported-sources`, `run`, `discover`, `fetch`,
  and `transcribe` commands in `cli.py`;
- sermon localization:
  `application.py`, `extraction.py`, `segmentation.py`, `sermon_detection.py`,
  `sermon_classification.py`, `recording_verifier.py`, and `disposition.py`;
- speaker identity and profiles:
  `identity.py`, `identity_attribution.py`, `speaker_registry.py`,
  `speaker_pair_selector.py`, `speaker_pair_review.py`,
  `reviewed_speaker_evidence.py`, `speaker_profile_status.py`, and
  `speaker_shadow_association.py`;
- persistence and output:
  `storage.py`, `source_ownership.py`, `artifact_namespace.py`, and `exporting.py`;
- the workflow descriptions in `README.md`, `docs/V1_SPEC.md`, and
  `docs/HANDOFF.md`.

No corpus reclassification or evaluation job was run.

## The implemented workflow today

| Stage | Preferred bulk path | Output | Automatic continuation |
|---|---|---|---|
| Seed sources | `import-church-db` | Organization, source, provenance snapshot, unreviewed pastor affiliation claim | Yes, into source sync |
| Discover | `sync-imported-sources` → `discover_sources_service` | Globally unique video row and flat-playlist metadata snapshot | Yes |
| Acquire transcript | Caption fetch, then local ASR fallback | Caption or local-ASR transcript artifact | Yes |
| Detect sermon | Optional `--extract` | Segments, proposed sermon window, classification, disposition | Yes |
| Create speaker observation | Side effect of extraction | Observation, name claims, shadow assessment | **No for imported videos without a target pastor** |
| Build reviewed profiles | `review-next-speaker-pair`, then `sync-reviewed-speaker-evidence` | Reviewed anonymous profile membership and name evidence | Manual, multi-command |
| Match a new observation | `shadow-associate-speakers` | Non-mutating proposal artifact | Manual and shadow-only |
| Associate to profile | No production automatic association path | Append-only membership event | Human-reviewed evidence only |
| Produce final sermon | Pastor review Markdown | Review-oriented aggregate file | Does not approve a sermon or establish speaker identity |

There is also a legacy `pte run URL --pastor SLUG` path. It assumes the requested
pastor before acquisition, assigns that pastor as a target context to every video
from the source, and can consequently produce identity shadow artifacts. This is
useful for a targeted search but is the inverse of the desired workflow: the target
identity is supplied first rather than discovered from the recording.

## Findings

### 1. Critical: imported acquisition bypasses speaker observation creation

`church_database_import._import_record` inserts imported sources with
`pastor_id = NULL`. That is a deliberate and sensible ownership decision: the
publisher is not necessarily the speaker.

The downstream identity implementation, however, still requires the old target
pastor:

- `extraction.extract_video` allows a null pastor and successfully creates a sermon
  proposal;
- `_record_identity_shadow_safely` exits unless the video, pastor, and extraction
  result all have integer IDs;
- `speaker_registry.persist_neutral_speaker_evidence` also requires a `Pastor` and
  creates or retrieves that pastor's configured profile as part of supposedly
  neutral evidence persistence.

The result is counterintuitive: organization-neutral acquisition works, and
speaker-neutral schema exists, but neutral observations are not actually emitted
unless a target identity has already been selected.

**Impact:** the most scalable intake command never feeds the identity backlog.

**Recommendation:** split observation creation from target projection.
`persist_speaker_observation` should require only the video, accepted/reviewable
sermon window, transcript, and media. Target-specific attribution should be a
separate optional projection. Imported pastor affiliation claims may contribute
name candidates and organization context, but must not be required to create the
observation.

### 2. Critical: profile matching has no production mutation path

The identity subsystem is intentionally conservative:

- pair comparison abstains without an approved policy;
- reviewed pair evidence must be collected manually;
- `sync-reviewed-speaker-evidence` must be run separately to materialize reviewed
  profiles;
- `shadow-associate-speakers` can propose a profile but explicitly cannot change
  registry membership;
- `shadow-discover-profiles` can now propose complete-link anonymous components,
  and a separate plan/apply command can promote verified components into
  reversible provisional profiles;
- a second plan/apply command can attach a current multi-exemplar proposal from
  an independent recording as provisional-profile confirmation;
- acoustic-driven registry mutation remains unapproved.

These are good safety properties for model development, but they mean the user goal
cannot be met by orchestration alone. There is no command or service that evaluates
a new observation against eligible profiles and records a reversible production
association under an approved policy.

**Impact:** every durable association ultimately depends on human-reviewed pair
work, and the number of comparisons grows with the corpus.

**Recommendation:** add a versioned `associate_observation` production service with
three outcomes:

- `associated`: attach to exactly one eligible reviewed profile when multiple
  independent exemplars agree and all conflict guards pass;
- `provisional_new_profile`: create a reversible unnamed provisional profile only
  under a separately approved clustering policy with sufficient redundant support;
- `review_required`: emit one compact review task with the best candidates and the
  specific blocking evidence.

Keep merges, naming, contradictory attribution, and low-margin matches manual. Make
all automatic membership events append-only and reversible, with model, policy,
exemplar, audio-span, and score provenance.

> Implementation update: the controlled bootstrap loop now exists.
> `shadow-discover-profiles` builds a bounded nearest-neighbor acoustic graph
> among unassigned observations and emits a provisional component only for at
> least three distinct recordings with complete-link same-speaker support and
> no difference, attribution, or unresolved-edge blocker.
> `promote-discovered-profiles --apply` creates a reversible provisional seed
> with full artifact provenance, while `confirm-discovered-profiles --apply`
> requires a later current multi-exemplar match from an independent recording.
> Global automatic growth remains gated on model and policy approval.

### 3. Critical: the single `videos.status` field conflates unrelated concerns

`VideoStatus` mixes acquisition, transcription, extraction, review, and export:
`discovered`, `transcript_fetched`, `transcribing_local`, `transcribed_local`,
`extracted`, `needs_review`, `approved`, `exported`, and `failed`.

In practice:

- extraction always sets `EXTRACTED`, even when the final disposition is
  `review_required` or rejected;
- generating a pastor review file sets every included video to `EXPORTED`,
  including rejected and review-required recordings;
- identity has its own assessments, but their state is not reflected in the video
  status;
- one failure string is reused by several stages;
- `NEEDS_REVIEW` and `APPROVED` exist in the enum and schema story but are not part
  of the normal review export path.

**Impact:** a video shown as `exported` may have no approved sermon and no identified
speaker. Operators cannot ask one reliable question such as “which new sermons are
waiting only on identity?”

**Recommendation:** replace the single workflow status with independently derived
stage state:

- acquisition: `pending / available / unavailable / retryable_failure`;
- transcript: `pending / captions / local_asr / retryable_failure`;
- content: `accepted_sermon / rejected_no_sermon / review_required`;
- observation: `not_applicable / ready / invalid / review_required`;
- identity: `associated / provisional / review_required / conflict`;
- delivery: `pending / delivered / superseded`.

Store immutable attempts and current materialized state per stage. A top-level
summary may be derived, but should never overwrite the underlying outcomes.

### 4. High: “review export” is treated as final export without a review action

`export_pastor_review_markdown` creates a useful aggregate review document, but
`_build_review_sections_for_videos` marks every included video `EXPORTED` while
writing it. There is no ordinary CLI flow that:

- accepts or corrects the proposed sermon window;
- records a `ReviewResult`;
- transitions a specific sermon to approved;
- writes a final, speaker-associated sermon artifact.

The `review_results` table and `APPROVED` status exist, while the V1 specification
describes an interactive approval flow, but current CLI review commands mainly
generate aggregate Markdown or evaluation fixtures.

**Impact:** output generation looks like workflow completion even though it is only
review preparation.

**Recommendation:** distinguish:

- `review queue export`: read-only presentation of unresolved cases;
- `content decision`: accept, reject, or adjust a sermon window and persist the
  decision;
- `identity decision`: accept, reject, or correct the profile association;
- `delivery export`: write only a sermon with satisfied content and identity
  policies.

For high-confidence cases, content and identity policy decisions can be automatic
review events. Human action should be needed only when a policy abstains.

### 5. High: no-caption results are not cached

`fetch_captions_service` skips only when a caption artifact already exists.
`NoCaptionsAvailableError` increments an in-memory count and leaves no durable
attempt record. On the next `run --all` or imported-source sync, the system requests
captions for the same video again—even if a local-ASR artifact already exists.

Generic caption failures are stored only by changing the shared video status to
`FAILED`; a later transcription can recover, but the failure is not classified with
a retry schedule.

**Impact:** repeated network work, noisy logs, avoidable rate-limit exposure, and no
distinction between permanent absence and transient failure.

**Recommendation:** persist caption acquisition attempts with:

- outcome (`available`, `not_offered`, `video_unavailable`, `transient_failure`);
- language and manual/automatic kind;
- yt-dlp version and request fingerprint;
- attempted time and `retry_after`;
- source metadata version.

Do not retry a stable “not offered” result unless metadata changes, the retry TTL
expires, or the operator forces it.

### 6. High: local ASR can be acquired but then ignored for sermon extraction

`extract_video` explicitly prefers the newest captions artifact whenever any
caption artifact exists, even if `--all-audio` created a newer local-ASR transcript.
There is no transcript quality score or arbitration record.

This makes `--all-audio` counterintuitive:

- the system pays the download and ASR cost for every video;
- normalized audio is useful for future speaker analysis;
- sermon localization still uses captions unconditionally.

Caption quality can vary substantially due to repetition, timing, language, and
automatic-caption errors. Conversely, local ASR is not automatically better.

**Recommendation:** add transcript candidate evaluation and select deliberately
using measurable signals: timestamp coverage, non-speech/repetition rate, language,
segment continuity, token density, and ASR completeness. Persist the chosen
artifact and reasons. Allow separate choices for sermon localization and acoustic
span preparation. Avoid local ASR when captions pass quality thresholds unless
audio is independently required for speaker matching.

### 7. High: `--no-transcribe-missing` does the opposite of what it appears to do

In `run_workflow_service`:

- the default `transcribe_missing=True` runs local ASR only for caption misses;
- setting `--no-transcribe-missing` enters the `elif` branch and calls
  `transcribe_videos_service(... captions_missing_only=False)`.

That second call transcribes all otherwise eligible recordings, including those
with captions. The option sounds like it disables fallback transcription, but it
actually expands transcription.

**Impact:** an operator trying to reduce work can unexpectedly trigger audio
download and ASR across captioned videos.

**Recommendation:** replace the two booleans with one explicit enum:
`--transcription-policy captions-only|fallback-asr|all-audio`. Keep
`fallback-asr` as the default and make each policy’s acquisition, extraction, and
speaker-audio behavior explicit.

### 8. High: video uniqueness loses multi-source provenance and target contexts

`videos.youtube_video_id` is globally unique and each video has one `source_id`.
Discovery builds a global set of existing YouTube IDs and skips duplicates before
calling `add_video`. Although `add_video` can return an existing row on a uniqueness
collision, that branch does not add a relationship to the newly encountered source
or copy that source's target policies.

**Impact:** a video appearing in two playlists/channels belongs permanently to the
first source that discovered it. Later publisher provenance, source-specific
selection, and target context can be lost.

**Recommendation:** make the YouTube item a canonical `recording` and add a
many-to-many `recording_sources` table containing discovery timestamp, source
metadata snapshot, position, and source-specific target context. Artifact storage
should remain canonical per recording.

### 9. High: manual source URLs are not canonicalized before uniqueness checks

Manual `add_source_service` validates the source type but stores the URL exactly as
provided. `sources.url` is unique only by exact string. The church importer has
strong channel identity and canonicalization logic, but ordinary source creation
does not use it.

Equivalent channel forms such as a handle, channel ID, `/videos`, `/streams`, or a
trailing-slash variant can therefore create duplicate sources. The legacy `run`
path also uses exact URL equality for `--replace-existing`.

**Recommendation:** resolve every source to an immutable platform identity before
upsert. Store entered URL as provenance, canonical URL for display, and
`source_identity_key` for uniqueness. Reuse the importer’s channel-key semantics in
all source entry paths.

### 10. High: discovery metadata is write-once for existing videos

Discovery persists a metadata snapshot only when a video is new. Existing video
rows are skipped globally and their title, duration, publication time, channel
name, availability, and raw metadata are not refreshed.

Flat-playlist results may omit duration or timestamps, and metadata can become more
complete after a livestream ends. The latest-window calculation and disk
reservation depend on these fields.

**Impact:** incomplete first-seen metadata can persist indefinitely, affect
recency ordering and capacity estimation, and deprive attribution logic of later
title/description evidence.

**Recommendation:** upsert discovery appearances and version metadata snapshots for
existing recordings. Refresh missing or mutable fields under an explicit policy,
while preserving every raw snapshot and its extractor version.

### 11. Medium: imported affiliation claims do not form an actionable identity bridge

The importer correctly treats pastor names as unreviewed provenance claims rather
than fact. However, the normal synchronization path does not turn those claims into
an identity task. A reviewer must separately inspect organization claims, create or
select a pastor, attach the affiliation, and then still establish speaker profile
membership through pair reviews.

**Impact:** high-value context exists in the database but is operationally
disconnected from the observation-to-profile funnel.

**Recommendation:** automatically create a reconciliation task when an imported
name cannot be safely resolved. Safe deterministic normalization may link an exact
unique existing person as a *candidate*, not as observed speaker truth. Use current
temporal affiliation only to prioritize candidate profiles for acoustic comparison;
never use it as sufficient identity evidence.

### 12. Medium: human identity work is fragmented across several commands

The documented loop is:

1. inspect `profile-status`;
2. run `review-next-speaker-pair`;
3. repeat pair review;
4. run `sync-reviewed-speaker-evidence`;
5. inspect status again;
6. run shadow association separately.

The review itself can require audio preparation, visual confirmation, observation
qualification, and a binary pair judgment. The synchronization step is easy to
forget, so a completed human judgment may not affect profile state until another
command is run.

**Recommendation:** provide one `pte work-next` queue across content, observation,
identity, and affiliation exceptions. When a review is submitted, materialize its
append-only consequences transactionally in the same operation. Background or
batch recomputation may remain separate internally, but should not require an
operator to remember a second command.

### 13. Medium: pairwise review is a development/evaluation workflow, not a scalable intake workflow

The speaker-pair subsystem is careful and auditable, but its fixture balancing,
evaluation partitions, review packets, and explicit same/different judgments are
optimized for model validation. Applying that loop to every new production video
does not scale.

**Recommendation:** keep pair review for calibration, edge cases, and profile
bootstrapping. For routine intake, compare a new observation to a bounded set of
candidate profiles selected by reviewed acoustic centroids/exemplars and safe
organization/time context. Ask the human one direct question only when necessary:
“Is this speaker profile A, profile B, or neither?” Record the answer as the same
append-only evidence primitives.

### 14. Medium: processing is incremental by artifact presence, not by input fingerprint

Several stages skip work if an artifact exists or a broad status matches.
Classification has notably better versioned caches, but acquisition, caption
selection, transcript choice, and ordinary extraction orchestration do not expose
one consistent stale-input model.

Examples:

- caption artifacts are accepted without checking source/tool policy freshness;
- discovery does not refresh existing metadata;
- extraction `missing_only` treats any extraction as sufficient even if the chosen
  transcript policy changes;
- review files overwrite a fixed `review.md` and `review.json`.

**Recommendation:** define an input fingerprint for every stage. A stage is current
only when its output fingerprint matches its input artifact hashes, tool/model
versions, and policy version. Keep immutable run records and a pointer to the
effective result.

### 15. Medium: failures and dead ends are not presented as an actionable queue

`status` reports table counts and configured sources, while `video list` can filter
one broad video status. It does not summarize:

- sources whose discovery failed;
- stable caption misses versus retryable caption failures;
- videos with no transcript;
- accepted sermons without observations;
- observations without profiles;
- profile conflicts;
- review-required content;
- eligible automatic associations blocked only by policy.

Some discovery failures exist only in console output because sources have no
discovery-attempt ledger or status.

**Recommendation:** add `pte queue status` and `pte queue retry` backed by stage
attempts. Show counts, oldest age, reason groups, and exact next action. A scheduled
run should return nonzero only for pipeline-level operational failure, not ordinary
abstentions or rejected non-sermons.

### 16. Medium: acquisition concurrency stops at the source boundary

`sync-imported-sources` processes imported sources sequentially. Caption requests
are serial within each source. Download and transcription pools operate only after
that source’s captions complete. Archival overlaps in one background worker, which
is useful, but large source sets still spend considerable time in sequential
network-bound discovery and caption work.

**Recommendation:** use a bounded global work queue:

- low-concurrency discovery per source;
- moderate caption-fetch concurrency with platform-aware throttling;
- download workers gated by disk reservation;
- ASR workers gated by CPU/memory;
- one archive queue;
- extraction workers independent of later sources.

Keep per-source latest-window selection, but do not make the whole source a
pipeline barrier.

### 17. Medium: fixed review files erase run history at the presentation layer

Pastor and organization review exports overwrite `review.md` and `review.json`.
Underlying extraction artifacts are preserved, but it is difficult to compare what
entered or left the operational review list between runs.

**Recommendation:** write a content-addressed or timestamped review manifest, then
update a `latest` pointer/file. Include disposition, content decision ID, observation
ID, identity decision ID, and delivery eligibility for every recording.

### 18. Low: source and pastor terminology still leaks legacy assumptions

The repository has made a sound distinction between publisher ownership and query
identity, but the main CLI still advertises `add` as “Add ... source for a pastor,”
and `run` requires `--pastor` for a single source. Artifact paths and compatibility
fields also retain pastor-scoped concepts.

**Impact:** operators are encouraged to bind an entire publisher source to one
speaker even though guest speakers, former pastors, and multi-speaker programs are
expected.

**Recommendation:** make `organization/source → recording → sermon observation →
speaker profile` the primary vocabulary. Retain pastor-targeted search as an
explicit query mode, not the default ownership model.

## What is already strong

The recommended changes should preserve these existing strengths:

- immutable/video-specific artifact namespaces and versioned metadata snapshots;
- local-first acquisition and ASR;
- caption-first cost avoidance;
- conservative sermon disposition with explicit `review_required` and rejection
  reasons;
- guest-speaker safeguards that prevent a content boundary override from silently
  becoming an identity decision;
- append-only reviewed speaker membership, name, redirect, and difference events;
- exact audio span hashing and model/policy provenance;
- abstention-first acoustic evaluation;
- independent content and identity concepts;
- archive verification and disk-reserve admission.

The central opportunity is not to replace these components, but to connect them
with identity-neutral observations and explicit stage orchestration.

## Recommended target workflow

### Automatic path

1. Resolve a source to an immutable channel identity and upsert its organization.
2. Discover new recording appearances and refresh metadata snapshots.
3. Persist acquisition attempts; reuse stable caption misses and verified media.
4. Select the best transcript candidate using a versioned quality policy.
5. Classify the recording and localize the sermon.
6. If no sermon exists, record `rejected_no_sermon` and stop successfully.
7. If content is unresolved, create one content-review task and stop that branch.
8. For an accepted sermon, always create an identity-neutral principal-speaker
   observation and speech-qualified acoustic spans.
9. Extract grounded, neutral name claims from metadata and spoken introductions.
10. Select a bounded set of eligible profiles using reviewed acoustic exemplars;
    use organization and temporal affiliation only to prioritize candidates.
11. Apply an approved multi-exemplar association policy.
12. Attach a unique, conflict-free match with a reversible automatic membership
    event; otherwise create one identity-review task.
13. Resolve the profile’s reviewed name and pastor/person link.
14. Emit the final sermon artifact only when content and identity delivery policies
    are satisfied.

### Human exception path

A single work queue should present only one unresolved decision at a time:

- correct sermon boundaries or reject the recording;
- confirm that the sermon contains one principal speaker;
- choose among the top profile candidates or “new/unknown speaker”;
- reconcile a conflicting imported name or organization affiliation;
- adjudicate an explicit attribution conflict.

Submitting the decision should immediately update the append-only evidence ledger,
recompute association state, and continue the recording automatically.

## Prioritized implementation plan

### Phase 0: make the pipeline truthful

1. Introduce independent content, observation, identity, and delivery states.
2. Stop marking review-file entries as `EXPORTED`.
3. Add an actionable backlog/status query.
4. Persist caption and discovery attempts, including stable negative outcomes.

This phase improves correctness and operability without enabling automatic identity
mutation.

### Phase 1: close the imported-workflow break

1. Refactor neutral observation and claim persistence to accept `pastor=None`.
2. Create observations for every accepted or reviewable sermon window.
3. Backfill observations for existing imported extractions without reclassifying.
4. Create reconciliation tasks from imported affiliation claims and grounded name
   claims.
5. Ensure organization/source ownership remains context, never speaker proof.

After this phase, every eligible imported sermon reaches the identity backlog.

### Phase 2: reduce acquisition waste

1. Canonicalize every source by immutable identity.
2. Add many-to-many recording/source appearances.
3. Refresh metadata snapshots for existing recordings.
4. Add transcript quality arbitration.
5. Replace source-at-a-time synchronization with bounded stage queues.

### Phase 3: productionize conservative association

1. Freeze and approve an acoustic model and decision policy using the existing
   evaluation framework.
2. Add profile candidate retrieval and multi-exemplar scoring.
3. Validate the implemented shadow anonymous-component discovery against
   reviewed outcomes and calibrated observation-consistency scores.
4. Validate the implemented reversible provisional promotion and independent
   confirmation loop against reviewed outcomes.
5. Approve automatic membership only for unique, high-confidence,
   conflict-free matches after the model/policy gate passes.
6. Keep new-profile creation more conservative than profile growth.
7. Keep naming, merging, and conflicting evidence manual.
8. Measure automatic coverage, error rate, abstention rate, and later-overturned
   decisions continuously.

### Phase 4: unify human review and delivery

1. Add a single transactional `work-next` experience.
2. Materialize reviewed evidence immediately on submission.
3. Produce immutable final sermon records linked to content decision, observation,
   profile, person/pastor, organization, and source provenance.
4. Export only delivery-eligible sermons.

## Suggested acceptance criteria

The end-to-end workflow should be considered complete when:

- every newly discovered recording has an explicit terminal or retryable state at
  each stage;
- a stable caption miss is not requested on every synchronization;
- imported organization-owned videos create speaker observations without a
  preselected pastor;
- high-confidence non-sermons terminate without human work;
- high-confidence sermons with a unique approved profile match are associated and
  delivered without human work;
- no source affiliation, title name, or target query alone can establish speaker
  identity;
- every automatic association is reversible and fully reproducible from stored
  artifacts and policy versions;
- ambiguous cases appear in one queue with one clear next action;
- a review export never changes a content or delivery state merely by being
  generated;
- the operator can answer, from one status command, how many recordings are
  complete, retrying, rejected, awaiting content review, awaiting identity review,
  or blocked by conflict.

## Bottom line

The repository is closer to the goal at the component level than it appears: the
sermon detector, evidence model, reviewed profile registry, and acoustic evaluation
foundation already exist. The limiting factor is the orchestration contract.

The first change should not be a more aggressive recognition model. It should be
to create an identity-neutral speaker observation for every eligible imported
sermon and to represent content, identity, and delivery as separate states. Once
that data reliably reaches the identity pipeline, the existing shadow association
work can be promoted—under an approved, reversible policy—from an experiment into
the limited-intervention production path.
