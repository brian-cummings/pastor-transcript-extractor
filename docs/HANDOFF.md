# Handoff Notes

## Current State

The sermon-isolation pipeline has a safe production path and a frozen evaluation set.

Implemented:

- normal extraction and reclassification share adaptive V3 classification
- raw Ollama inference is cached by transcript, prompt, model, schema, and block context
- candidate ranking, score components, confidence reasons, model identity, and refinement reasons are persisted
- low-confidence classifications preserve the protected rule/manual baseline
- forced reclassification recomputes the rule-only baseline instead of reusing a prior hybrid result
- corpus-wide `reclassify --all` propagation selects reusable extraction artifacts, skips ineligible videos, and retains cache-based resumability
- ambiguous classifications use a production 4B-to-12B cascade: 4B localizes blocks and 12B verifies the recording type
- recording verification is persisted with prompt `recording-sermon-verifier-v2` and policy `recording-sermon-verifier-policy-v3`
- deterministic title decisions handle explicit classes, school programs, graduations, concerts, and technical tests before 12B inference
- guest-speaker concerns and invalid verifier evidence remain protected rather than being automatically accepted
- ground-truth review supports positive and negative fixtures
- 44 manually reviewed fixtures are frozen: 23 positive and 21 negative
- evaluation is segment-based and produces JSON and Markdown reports
- failure reports show expected, missed, retained, and contaminating ranges with persisted label evidence
- conservative candidate joining can recover interrupted sermons
- explicit sermon-title cues can recover up to four minutes of contiguous sermon-like setup before the cue
- candidate ranking recognizes the explicit phrase `our title today`, even when the word `sermon` is omitted
- pre-title recovery persists its anchor, duration, reason, and stopping evidence
- production confidence uses versioned soft rule overlap; the evaluator also replays the legacy hard-veto and no-overlap policies
- fine-label continuity that expands more than ten minutes to a recording edge caps confidence at medium and requires review
- extraction and reclassification persist an explicit final disposition separately from diagnostic candidates
- rejected videos never fall back to a full-transcript excerpt in pastor review exports
- `extract`, review preparation, and `run` share one adaptive extraction batch service
- Typer commands delegate to plain service functions with ordinary Python defaults
- `run` writes disposition-aware `review.md` and `review.json` exports by default
- the offline interaction harness uses stable current-excerpt line IDs for grounded evidence
- identity increment 1 persists content-addressed metadata snapshots, context-only evidence ledgers, and shadow assessments
- identity and content decisions are composed by an independent, versioned coordinator; shadow results do not gate exports
- manual sermon-window overrides are authoritative for content boundaries only and no longer suppress guest-speaker review
- identity increment 2 extracts exact metadata and spoken-attribution evidence with correlation grouping
- grounded attribution remains shadow-only and never uses sermon topic, style, or theology
- identity increment 3 separates neutral speaker observations, claims, profiles, and target-policy projection
- valid targetless sermon extractions now create identity-neutral principal-speaker observations and grounded claims; configured pastor profiles and target-specific assessments remain optional projections
- strict association coverage audits account for every latest extraction, require current-policy attempts for eligible unassigned observations, preserve explicit blockers, and exit nonzero on missing, stale, or retry-required cases
- profile membership and naming require explicit review events; clustering and acoustic-driven registry matching remain unimplemented
- acoustic increment 4 adds a read-only, local pairwise speaker diagnostic with exact cached audio spans and pinned model provenance
- acoustic outcomes remain non-gating; no default threshold exists and uncalibrated comparisons abstain
- reviewed pair fixtures pin observation fingerprints and exact WAV hashes; evaluation separates recognition errors, abstention, and analysis failure
- an evidence-mode pair-review workflow qualifies each observation before a
  binary same/different judgment; acoustic evaluation stays blind while
  profile-oriented review may use timestamped video
- review submissions are append-only; indeterminate reviews never become fixtures and re-reviews never overwrite frozen truth
- anonymous speaker grouping now has reviewer-attributed, append-only profile creation, observation disposition, membership, and different-speaker events
- reviewed same-profile memberships and explicit different constraints can nominate pair candidates, but exact spans still require independent pair review before fixture creation
- media foundation separates immutable source/normalized audio from transcript artifacts
- caption-backed isolated sermons can acquire verified audio without invoking local ASR
- historical local-ASR audio migrates as reconstructed provenance without file modification
- media acquisition outcomes distinguish verified, unavailable, and failed; they remain non-gating for sermon content
- universal acquisition is an explicit shadow command and has not been inserted into the stable `run` workflow
- no acoustic prediction mutates profiles, memberships, name claims, target policy, or sermon artifacts
- 284 tests pass

## Transcript-Independent Media

Audio is now modeled independently from transcript artifacts. The architecture,
provenance rules, commands, and replay guarantees are documented in
`docs/MEDIA_FOUNDATION.md`.

Register historical audio without moving or rewriting it:

```bash
pte media backfill \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Measure current isolated-sermon coverage without downloading:

```bash
pte media audit \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Acquire audio explicitly, without ASR, for one video or a bounded universal
batch:

```bash
pte media ensure-audio --video-id DATABASE_VIDEO_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData

pte media ensure-audio --all-eligible --limit 10 \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The existing `run` workflow remains unchanged. Media acquisition failures are
persisted separately and do not alter `proposed.json`, extraction metrics,
content dispositions, profiles, memberships, or name claims.

### Production media verification (2026-07-16)

The historical backfill examined 183 videos and produced 78 reconstructed media
artifacts plus 39 initial acquisition outcomes. An immediate full replay
created zero artifacts and zero outcomes. The reviewed `qwsZHo-S87A` sentinel
retained identical `proposed.json` and normalized-audio SHA-256 values and an
identical audio modification time.

Two caption-backed sermons then exercised the real no-ASR acquisition path.
Both replayed without redownload. The final sentinel retained native WebM source
audio (15,559,845 bytes) and derived mono 16 kHz WAV audio (39,911,758 bytes),
with yt-dlp and ffmpeg versions persisted. Transcript count remained 178 and
speaker profile, observation, and claim counts remained 7, 135, and 32.
The post-migration sermon evaluator processed 13 available fixtures with zero
missing artifacts; all 12 fixtures from the preceding accepted benchmark had
exactly unchanged per-fixture result payloads. The additional fixture was new
ground truth, not a media-induced classification change.

Universal acquisition subsequently produced media artifacts for every isolated
sermon. Transient yt-dlp HTTP 403 failures remained append-only history and
succeeded on later retries. Six hash-valid, full-length artifacts initially
appeared as `corrupt` because final transcript segments extended between 2 and
28 seconds past the independently recorded video duration. Coverage validation
now accepts an artifact that either reaches the sermon endpoint directly or
closely matches the full video duration when the sermon endpoint reaches or
overshoots it. It still rejects audio that is materially shorter than both.
This policy correction changed no media bytes, sermon artifacts, or identity
state.

Current coverage is:

```text
isolated sermons  135
verified audio    135
unavailable         0
failed              0
corrupt             0
missing             0
```

All currently isolated sermons now have verified audio. Replaying
`pte media ensure-audio --all-eligible` skips them; no reacquisition is needed.

Source-audio archival is tracked as a first-class retryable workflow. The
active production destination is `/Volumes/home/SermonExtractorAudio`. A dry
run registered 135 eligible source artifacts totaling 36.95 GiB; all remain
pending for the operator-run archive. PTE stores deterministic source and NAS
paths, checksums, byte sizes, current entry state, and append-only attempts.
Unavailable destinations leave entries pending. Run:

```bash
pte media archive-sources \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The destination argument is omitted because it is already persisted. Inspect
progress or retry state with `pte media archive-status --base-dir ...`.

## Anonymous Speaker Grouping

The registry now exposes the narrow manual lifecycle needed by the pair
experiment without introducing an acoustic cluster or naming workflow. New
append-only event tables record:

- reviewer-attributed anonymous-profile creation;
- observation qualification, unresolved, multiple-speaker, or invalid review;
- a separate reversible deferral when a qualified observation remains ungrouped;
- reversible profile attachment/detachment;
- reversible, explicit different-speaker constraints between two observations.

Effective membership and constraints replay from the latest event for each
exact relationship. Repeating an operation with the same event key reuses the
existing event; reusing a key with different content fails. An observation
cannot be attached to a second effective profile until its existing membership
is explicitly detached. Profile creation and every review mutation retain the
reviewer and reason.

Existing pair-review work is the initial registry evidence, not work to repeat.
Inspect the current funnel and profile backlog at any time with:

```bash
pte identity profile-status \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

`profile-status` is read-only. It reports registry observations by effective
qualification, reviewed pair relations and components, canonical and retired
profiles, profile members, attached name claims, configured-identity links,
and the reviewed single-speaker observations that remain ungrouped. It also
loads the newest valid artifact under
`evaluation/speaker-profile-discovery/shadow-runs` and reports unpromoted
`shadow-candidate` components separately from candidates already promoted into
the registry. Blocked and stale discovery components are counted but are not
presented as canonical profiles. Use `--discovery-root` when discovery reports
live somewhere else. The per-profile table deliberately shows raw evidence
dimensions—member
observations, distinct recordings, distinct source records, attribution/link
state, and attributed frontier candidates—instead of assigning an unsupported
maturity score. A source count describes recording coverage only; source or
source-family membership is never identity evidence.

The reported states mean:

- `anonymous`: reviewed voice membership exists but no consistent explicit
  name is present;
- `attributed`: the reviewed component has a consistent explicit name but is
  not linked to a configured pastor;
- `attribution-pending`: consistent name claims or their configured-identity
  link have not yet been materialized by reviewed-evidence sync;
- `linked`: attribution has reconciled the reviewed voice component to a
  configured pastor identity;
- `merge-candidate`: the same explicit attribution spans separate profiles and
  needs an exact-span bridge comparison;
- `attribution-conflict`: conflicting names or a reviewed different-speaker
  constraint requires adjudication.

For an `anonymous` or unnamed `provisional` profile whose metadata and spoken
attribution did not produce a name, use the compact reviewed fallback:

```bash
pte identity review-profile-attribution \
  --reviewer REVIEWER_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The command selects the largest unnamed profile by default; `--profile-id`
targets one explicitly. Its local HTML packet presents representative member
videos at the stored sermon timestamps. The terminal prompt records which video
backs the identification, the entered name, reviewer, and reason. Approval
creates an immutable manual name claim plus an append-only profile attachment.
If the normalized name uniquely matches a configured pastor and that identity
is not already linked elsewhere, its placeholder redirects to the voice
profile. An unmatched name remains attributed but unlinked. Multiple configured
matches, an existing different identity link, or conflicting profile names do
not merge automatically.

The “next need” column and final action list describe how to mature each
profile. They do not imply that every unreviewed registry observation is
currently eligible for nomination: the pair selector separately rejects stale,
non-accepted, malformed, or otherwise unusable observations.

Synchronize reviewed work explicitly with:

```bash
pte identity sync-reviewed-speaker-evidence \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The sync joins append-only review events to their immutable drafts, reuses
consistent per-observation qualifications, and derives confirmed same/different
relations only from approved binary pair reviews. Confirmed same edges form
reviewed connected components. A component creates one deterministic anonymous
profile or joins its one existing profile. When a newly confirmed same-speaker
bridge connects multiple reviewed profiles, synchronization consolidates them
through append-only membership moves and profile redirects. An already linked
profile remains canonical; otherwise a reviewed-anonymous profile is preferred
over a provisional discovery profile, followed by the lowest stable profile ID.
Only reviewed-anonymous and provisional discovery profiles participate, and
multiple configured identities block the merge. Confirmed different edges
create exact observation constraints.
Qualification conflicts, pair conflicts, transitive same/different
contradictions, missing observations, incompatible redirects, and manual
qualification overrides block affected mutations. Replay adds no duplicate
events. Use `--dry-run` to inspect the derivation without applying reviewed
evidence.

After component materialization, the same sync conservatively reconciles
observation-scoped explicit attribution claims. A reviewed component with one
consistent normalized name receives append-only claim attachments. When that
name uniquely matches a configured pastor identity, the configured placeholder
profile redirects to the reviewed anonymous voice component; voice memberships
remain on the reviewed component and are never copied from attribution alone.
One attribution spanning multiple reviewed profiles is reported as a pending
merge candidate because profile separation is not different-speaker evidence.
If an effective different-speaker constraint crosses those profiles, it becomes
a true attribution conflict instead. Multiple names inside one component,
multiple configured matches, a manual claim decision, an incompatible
redirect, or direct membership on the configured placeholder also blocks the
affected identity link and is reported as a conflict.

Continue identity review through the existing pair workflow:

```bash
pte identity review-next-speaker-pair \
  --reviewer REVIEWER_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

This remains the only human speaker-identity adjudication interface. It asks
the reviewer to qualify both observations and, when both contain one consistent
principal speaker, make the same `same`/`different` judgment. Evaluation
packets remain audio-only and blind. Profile-growth and automation-readiness
packets add a YouTube link beside every exact clip timestamp so the reviewer
can visually confirm identity; selection relations are still not shown.

Review events record `audio_only` or `audio_plus_visual` evidence mode.
Approved binary judgments in either mode are eligible for identity replay.
Only approved `audio_only` judgments are eligible to become acoustic
evaluation fixtures. Reviews written before this separation remain
backward-compatible as audio-only evidence. The observations themselves remain
reusable in other identity comparisons; only an exact visually reviewed pair
is excluded from later blind evaluation.

Automatic review handoff carries both selected immutable observation
fingerprints into packet preparation and records them in the selection
manifest. Packet creation verifies that each fingerprint still belongs to its
selected video and refuses substitution by a different latest observation.
Inspect historical and current automatic drafts with:

```bash
pte identity audit-speaker-review-selection
```

The audit is read-only. Current manifests are checked against their exact
selected pair; compatible legacy profile-growth manifests are checked by
requiring both reviewed fingerprints to appear in their recorded target
components. Older manifests without enough provenance are reported as
unverifiable rather than guessed.

Run `sync-reviewed-speaker-evidence` after a review session to materialize all
approved pair judgments into anonymous profiles and exact different-speaker
constraints. There is no separate single-observation grouping review: profile
membership is derived from the same pair evidence rather than asking the
reviewer to repeat the recognition task.

The default `--selection-objective evaluation` preserves the tuned fixture
selector. To spend the same pairwise review effort on profile creation and
growth instead, use:

```bash
pte identity review-next-speaker-pair \
  --selection-objective profile-growth \
  --reviewer REVIEWER_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Profile-growth nomination prioritizes a shared-attribution bridge between
separate reviewed profiles when it can resolve an attribution split. It then
favors compatible frontiers for blocked components with fewer than three
members, new component seeds, further expansion of mature components, and
other component bridges. Prior profile-growth selections rotate
otherwise-equivalent targets so one large linked profile cannot monopolize the
queue. Shared explicit attribution is a nomination signal, not identity truth.
Pairs already connected by reviewed same evidence or blocked by a reviewed
different constraint anywhere across the two components are excluded. The
exact audio clips and qualification prompts remain unchanged; the
profile-oriented packet also exposes timestamped source-video links.

Observation suitability is now a separate shadow-calibration concern. Existing
`qualified_single_speaker`, `multiple_speakers`, and `invalid_audio` decisions
can be deduplicated and inspected without acoustic execution:

```bash
pte identity evaluate-observation-consistency
```

Brian may explicitly run the acoustic calibration with `--execute`. It reuses
the exact reviewed clips and embedding cache to measure weakest-clip coherence,
pairwise spread, and the strongest two-cluster split. The resulting ignored
report is threshold-free, cannot qualify observations, and cannot mutate the
registry. If present, its scores are used only for nomination ranking.
Profile-growth uses a two-exploitation/one-exploration cadence so known good
evidence improves review yield without exhausting the qualified backlog or
preventing discovery of new observations.

The normal operator loop is therefore:

1. Run `profile-status` to see the funnel and highest-value unmet needs.
2. Run `review-next-speaker-pair --selection-objective profile-growth`; keep
   making the same single/multiple/invalid qualification and pairwise
   same/different decision, using source-video links when visual confirmation
   is useful.
3. Run `sync-reviewed-speaker-evidence` to replay confirmed evidence into
   profiles, claims, redirects, and different-speaker constraints.
4. Run `profile-status` again to see which profiles grew and what remains.

The executable identity-layer orchestrator uses the same positional/`--all`
scope convention as top-level `pte run`:

```bash
caffeinate pte identity run --all \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

For one recording, pass its YouTube ID positionally. `--plan-only` runs the
coverage and eligibility stages without acoustic execution or mutation. An
executing corpus run performs backfill, all-eligible shadow association,
provisional-confirmation planning, shadow discovery, promotion planning, and a
final coordination audit. It does not silently cross registry safety gates:
validated confirmations and provisional promotions require
`--apply-confirmations` and `--apply-promotions`; reviewed pair judgments,
naming, conflicts, and model/policy approval remain separate. Use
`--skip-discovery` for an association-only corpus pass.

A profile is first created when a confirmed same-speaker pair forms a reviewed
component. Later confirmed same-speaker frontier comparisons add observations;
bridge comparisons can merge reviewed-anonymous components and provisional
discovery profiles. An established linked profile remains canonical when its
provisional counterpart is consolidated. Explicit observation-scoped
attribution can name that voice component, and a unique configured-name match
can link it to an attributed pastor profile. Naming and source context alone
never establish speaker identity.

### Shadow Association of New Sermons

The first non-mutating corpus association layer is now implemented. Profile
readiness is deliberately split:

- **shadow-ready** requires at least three reviewed members from three distinct
  recordings, complete member observations, no internal reviewed
  different-speaker constraint, and no conflicting explicit attribution;
- **automatic-profile-ready** additionally requires the reviewed same-speaker
  graph to be connected with no bridge edge, so membership has redundant human
  support instead of depending on one transitive link.

These are profile gates only. The independent model/policy promotion gate must
also pass before automatic registry mutation can be considered.
`profile-status` reports both readiness counts and each profile's state.

Build missing redundant profile evidence through the same exact-span workflow:

```bash
pte identity review-next-speaker-pair \
  --selection-objective automation-readiness \
  --reviewer REVIEWER_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

This objective first loads the newest verified discovery artifact and selects
an unresolved exclusive-member edge when one judgment can collapse overlapping
complete-link components into a larger profile candidate. It records the
discovery result hash, affected components, members, and number of observations
unlocked in the ordinary pair-selection manifest. Undersized two-recording
components are not nominated merely for being small; they wait for a third
recording.

If no discovery overlap needs resolution, the objective selects an unseen
internal comparison whose added edge would remove one or more bridge
dependencies from a reviewed profile graph. Already bridge-free profiles are
skipped. If no useful reinforcement remains, it falls back to normal
profile-growth selection. It never tells the reviewer that the observations
are currently grouped and never assumes that grouping is correct; timestamped
source-video links are available for confirmation.

Discovery loads approved pair reviews directly as explicit constraints before
registry synchronization. A reviewed `same` answer can supply the missing edge
that turns overlapping cliques into one promotable complete-link component; a
reviewed `different` answer prevents that unsafe merge. Both constraint sets
are included in the discovery artifact fingerprint. Run discovery again after
submitting a discovery-resolution review, then plan promotion from the new
artifact.

Inspect corpus and profile eligibility without acoustic execution:

```bash
pte identity shadow-associate-speakers \
  --all-eligible \
  --plan-only \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Execute the shadow matcher with `--all-eligible`, or use
`--youtube-video-id VIDEO_ID` for one sermon. It compares an eligible,
unassigned observation against up to three eligible exemplars per shadow-ready
profile. Candidates and exemplars use the same five transcript-grounded
sermon-speech spans as profile discovery; legacy artifacts from the earlier
non-speech-grounded sampler do not satisfy the strict association audit. A
proposal requires at least two same-speaker decisions, no
different-speaker result, no technical failure, exactly one matching profile,
and no conflicting explicit attribution. Reviewed different-speaker
constraints override acoustic output.

Versioned artifacts are written below the ignored
`evaluation/speaker-associations/shadow-runs/` directory. They retain the
candidate and exemplar fingerprints, full pair results, model fingerprint,
policy hash and state, profile readiness, outcome, and deterministic result
hash. Outcomes are `proposed_match`, `no_match`, `ambiguous`,
`conflicting_attribution`, `insufficient_evidence`, or `analysis_failed`.
Every artifact explicitly prohibits registry mutation and automatic
assignment. The current default policy remains an experimental development
candidate and is usable only for shadow measurement.

Measure saved proposals against registry evidence reviewed later with:

```bash
pte identity shadow-association-status \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The read-only replay separates confirmed, contradicted, and pending proposals
and reports abstentions that were later resolved. Pending proposals do not
count toward precision.

### Shadow Anonymous Profile Discovery

The profile matcher cannot bootstrap a new voice identity because it requires
existing profile exemplars. The separate discovery pass compares eligible,
unassigned observations with one another:

```bash
pte identity shadow-discover-profiles \
  --plan-only \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Omit `--plan-only` to compute deterministic five-span signatures. Each 12-second
span must overlap meaningful sermon-labeled transcript text; repetitive,
non-sermon, and transcript-empty regions are excluded. The same spans are reused
for pair decisions. Every signature is also scored with the versioned
`observation-consistency-discovery-v1` policy. Its experimental `0.60`
`weakest_clip_coherence` boundary was selected from 92 reviewed observations:
it retained 72 of 74 reviewed single-speaker examples and rejected 15 of 18
reviewed multiple-speaker or invalid examples. This is a nomination-efficiency
calibration, not speaker qualification or identity evidence.

By default, global discovery nominates up to eight centroid-nearest observations
only among the `strong` tier. It also adds bounded source-local retrieval among
strong observations: source groups of at most 12 receive complete pair coverage,
while larger groups receive four source-local nearest neighbors per observation.
The optional `--maximum-pairs` cap applies only to the global nearest-neighbor
path, so it cannot silently remove small-group complete-link coverage. Source
membership is retrieval provenance only and never supplies identity evidence.
The limits are configurable with `--source-complete-link-limit` and
`--source-nearest-neighbors`.

Below-threshold signatures remain fully recorded as `deferred` and never enter
global or source-local discovery. The former `--include-deferred` diagnostic
override is rejected. A narrow guarded closure path may consider scores in
`[0.50, 0.60)` as third candidates for an existing strong same-speaker seed. It
compares each candidate acoustically with both seed endpoints and admits both
identity edges atomically only when both comparisons return `same_speaker` and
no reviewed difference exists. A failed or single matching edge remains
diagnostic and cannot grow a profile.

This prevents inconsistent observations from consuming the normal discovery
budget without permanently deleting or disqualifying them.
Pair results still pass through the pinned abstention-first policy before
same-speaker components are built. Each initial same-speaker edge then opens a
bounded closure frontier: by default, up to eight likely third observations are
ranked by their joint acoustic proximity to both endpoints and compared with
each endpoint. Candidates sharing either seed source are tried first as a
retrieval optimization only. Source membership is recorded as context and never
counts as identity evidence or a same-speaker result. The
`--closure-candidates-per-same-pair` option controls this bounded second phase;
zero disables it.

A provisional profile candidate requires at
least three distinct recordings and a complete-link same-speaker graph. Any
missing/abstaining required edge, reviewed
different-speaker constraint, or conflicting explicit name blocks the component.
The result is a content-addressed artifact under the ignored
`evaluation/speaker-profile-discovery/shadow-runs/` tree. It never creates a
registry profile or membership by itself. The report records the calibration
artifact hash, threshold, policy status, score and tier for every signature;
separate global, source-local, strong closure, and borderline-deferred pair
counts; every retrieval reason and source context; and each deferred attempt's
score, seed, endpoint comparisons, and atomic admission outcome. Discovery
artifacts use the v6 contract; v2-v5 artifacts remain readable.

Ambiguous comparisons in the acoustic near-same band are tested hypothetically
against the complete-link rules. When one reviewed judgment could complete a
currently blocked component, the artifact records an actionable review frontier
ranked by distance from the same-speaker boundary. `automation-readiness` selects
these frontiers before older overlap-resolution work, but still creates the
normal blinded packet and visual-confirmation step. Only the approved review
judgment becomes durable identity evidence. `profile-status` reports how many
blocked components have an actionable frontier and names that review as the next
action.

When a strong third candidate has two `ambiguous_similarity` links to a strong
two-recording seed, neither edge can complete the triangle alone. The v6 staged
frontier retains at most two such candidates per blocked component, ranks bundles
by their weaker link, and exposes only that bottleneck for the first blinded
review. A reviewed different-speaker judgment eliminates the bundle. A reviewed
same-speaker judgment does not create a profile; after reviewed-evidence sync and
a new discovery run, the remaining ambiguous link becomes an immediate frontier.
Only two reviewed same-speaker judgments can satisfy complete-link. Missing,
different-speaker, internally inconsistent, deferred, or conflicting-name
candidates never enter this staged path. The staged metadata has
`identity_evidence=false` and cannot create registry evidence.

The artifact now has an explicit, reversible promotion boundary.
`identity promote-discovered-profiles --discovery-report <path>` validates the
checksum, current discovery and transcript-grounding versions, complete-link
outcome, live observation fingerprints, distinct recordings, current
membership, and reviewed difference constraints. `--apply` creates a stable
`provisional` discovery profile, records artifact/seed provenance, and attaches
the seed observations. The profile is shadow-usable immediately but carries
`discovery_candidate_unconfirmed` as an automatic-readiness blocker.

After a new shadow-association run,
`identity confirm-discovered-profiles` validates proposed matches directed at
discovery profiles. `--apply` accepts only current transcript-grounded,
multi-exemplar proposals from a recording outside the seed component, attaches
that observation, and records the association artifact as confirmation. This
clears the profile-level confirmation blocker. It does not approve the
experimental acoustic policy or enable automatic mutation globally.

`identity coordinate` is the first non-mutating orchestration boundary. With
`--youtube-video-id`, it audits one current extraction and emits exactly one
workflow state and next action. `--execute-shadow` runs association only when
that extraction is missing a current attempt, then re-audits and writes a
content-addressed report below `logs/identity-coordination/`. With `--all`, it
builds a read-only corpus action inventory. The coordinator recognizes content
terminal, content review, explicit blocker, associated, association-required,
profile-proposal, discovery-batch, identity-conflict, and provisional-confirmation
states. It indexes the newest current discovery artifact to distinguish newly
eligible observations from observations already evaluated without a cluster,
signature failures, blocked components, and promotable components. Already
evaluated observations wait for new evidence rather than causing redundant
discovery runs. It cannot apply registry mutations, and corpus discovery remains
a separate scheduled batch.

The older optional `--consistency-report` and `--minimum-consistency-score`
arguments remain available for exact replay of legacy externally-scored runs.
They should not be used for normal corpus discovery because those reports cover
only already-reviewed fingerprints. Current discovery computes and tiers every
new signature directly. The consistency policy remains an experimental shadow
policy: it cannot qualify observations, create profiles, or mutate the registry.

### Future Automatic Anonymous Profile Assembly

The shadow discovery layer now produces evidence-backed anonymous component
proposals without a human deciding every pair, but pair-policy promotion and
durable profile mutation remain separate gates. The current acoustic promotion
contract requires at least 300 non-abstaining decisions in each direction, zero
observed false-same and false-different decisions, complete recording variation
coverage, one pinned model and approved policy, no missing results or technical
failures, and one untouched held-out evaluation. Passing that gate permits
consideration of automatic pair decisions; it does not by itself permit profile
creation, growth, or merging. With zero errors in 300 decisions, the
rule-of-three approximate 95% upper error bound is still about 1%, and one
false-same edge can contaminate an entire transitive component.

The intended progression is:

1. Keep automatic evidence limited to pair nomination while reviewed coverage
   grows.
2. Use the implemented versioned shadow-association and shadow-discovery layers
   to measure multi-exemplar profile matches and complete-link anonymous
   components with complete model, policy, span, and input provenance. Shadow
   proposals do not write registry events.
3. Measure component-level false merges, splits, contradiction rates, and
   stability across dates, rooms, microphones, channels, and source families.
   Source-family membership remains context only and never identity evidence.
4. Use the explicit plan/apply boundary to promote verified shadow components
   to reversible provisional unnamed profiles. Promotion requires at least
   three observations from independent recordings,
   complete-link same-speaker support, no reviewed or predicted different edge,
   no conflicting attribution, and no unresolved required comparison.
5. Consider conservative automatic growth only when a new observation agrees
   with multiple independent members of an existing provisional profile.
   A single machine same-speaker edge never creates, grows, or merges a durable
   profile.
6. Keep profile-to-profile merges, configured-pastor reconciliation, naming,
   attribution conflicts, and any reviewed-evidence contradiction behind
   explicit human pair review.

Any future automatic registry mutation requires a separately approved,
versioned component policy, an append-only machine-evidence ledger, reversible
events, shadow replay demonstrating stability, and an explicit rollback path.
Until the global model/policy conditions are promoted, discovery profiles and
their confirmed growth remain provisional evidence and cannot authorize
unattended registry mutation.

Detach without deleting history:

```bash
pte identity detach-speaker-observation YOUTUBE_ID \
  --profile-id PROFILE_ID \
  --reviewer REVIEWER_ID \
  --reason "REVIEWED CORRECTION" \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Record a different-speaker constraint only after the reviewer has actually
established it:

```bash
pte identity record-speaker-difference VIDEO_A VIDEO_B \
  --reviewer REVIEWER_ID \
  --reason "REVIEWED EXACT-SPAN COMPARISON" \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Pass `--clear` to reverse its effective state while preserving history.
Separate profiles never imply a different-speaker constraint.

## Acoustic Pair Experiment

The next recognition question is intentionally limited to whether two reviewed
principal-speaker observations contain the same person. The implementation and
evaluation contract are documented in
`evaluation/speaker-pairs/README.md`.

Automatic pair nomination now inherits sermon-classification safety.
`review-next-speaker-pair` admits only observations tied to the readable latest
extraction when its persisted top-level disposition is `accepted_sermon` and
the observation boundaries match the current valid sermon window. It also
requires usable diagnostic spans and hash-verified normalized media.
Review-required, rejected, malformed, unknown, and stale observations are
excluded. Accepted manual window overrides remain eligible when their current
observation matches the override. This is derived at selection time and adds no
database migration or lifecycle state.

Selector v11 in the default evaluation objective first checks for unreviewed
pairs nominated by explicit curated
relations. Two observations reviewed into the same effective profile may
nominate a positive pair; an explicit effective different-speaker constraint
may nominate its exact negative pair. Neither relation supplies an expected
outcome, and both still pass through the blinded, exact-span pair review before
a fixture can be frozen. Merely belonging to different profiles supplies no
negative evidence.

The evaluation objective also derives partition-scoped frozen-fixture outcome
counts. When
`different_speaker` exceeds `same_speaker` by at least two, it may nominate a
same-likely pair by expanding a frozen reviewed-same anchor toward an unused
observation only when both have the same exact grounded name attribution.
Church or source-family context is never sufficient. One-sided name evidence
is represented as `partial_attribution`, and exhaustion of the grounded
same-likely pool is explicit in the selection reasons. Reviewed different
constraints against any member of the reviewed-same component block only that
same-seeking expansion. The component is selection metadata only: no
transitive fixture label, identity cluster, profile, or registry membership is
created.

Grounded attribution v3 recognizes `Sis`/`Sister` title credits, including the
previously missed `Sis Lillie Hill - ...` case. Materialize the new append-only
claims with:

```bash
pte identity backfill \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

This does not reclassify sermon content or rewrite extraction artifacts.

The provisional local backend is sherpa-onnx 1.13.1 with an English CAMPPlus
ONNX model whose SHA-256 is pinned by the CLI. Model files and all generated
audio/embedding caches are ignored. There is no production dependency on this
optional package.

Run a read-only diagnostic with:

```bash
pte identity compare-speakers VIDEO_A VIDEO_B \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Without an explicitly approved policy, the expected result is
`insufficient_evidence: decision_policy_unavailable` with raw within- and
cross-observation similarity distributions preserved. This is deliberate.

The first real sentinel used the two videos whose titles attribute Samuel
Bulgin (`qwsZHo-S87A` and `wVw7LzIICRE`). It replayed byte-identically from
cache, but the within/cross distributions were not clean enough to treat the
title attribution as acoustic ground truth. No threshold or reviewed fixture
was created from it. Registry counts before and after were identical:

```text
speaker_profiles                  7
speaker_observations            135
profile_observation_events        0
speaker_name_claims              32
profile_name_claim_events         0
speaker_profile_redirect_events   0
```

Before any policy can be promoted, humans must review exact cached spans for a
stratified same/different fixture set spanning dates, microphones, rooms, and
audio quality. The evaluator defaults to a demanding evidence gate: zero
observed errors and at least 300 decisions in each direction, which corresponds
to an approximate rule-of-three 95% upper error bound near 1%.

Create a blinded listening packet and submit a review with:

```bash
pte identity review-speaker-pair VIDEO_A VIDEO_B \
  --reviewer REVIEWER_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The packet hides source identity and requires both observations to qualify as
one consistent principal speaker before accepting `same` or `different`.
`different` remains a binary pair judgment, not a selection from known speaker
profiles. All submissions are content-addressed review events. An existing
fixture is immutable; consistent and conflicting re-reviews are preserved
without overwriting it.

## Local Evaluation Environment

The current real application data is intentionally outside this repository:

```text
/Users/briancummings/Documents/PastorSearchData
```

Do not replace this path with the temporary doctor-test directory. Pass it explicitly with `--base-dir`.

Activate the existing environment and enable Ollama:

```bash
cd /Users/briancummings/code/pastor-transcript-extractor
./venv-shell
export PTE_LLM_MODEL=gemma3:4b
pte doctor --base-dir /Users/briancummings/Documents/PastorSearchData
```

`pte doctor` should report Ollama connectivity, the installed model, and structured output as ready.

## Normal End-to-End Workflow

The normal single-source command now runs through pastor review export.
`--classifier auto` tries Ollama with Gemma 3 4B by default and safely falls
back to rules when Ollama is unavailable. No enable flag is required. Set
`PTE_LLM_ENABLED=0` or pass `--classifier rules` only to opt out deliberately.

```bash
export PTE_LLM_MODEL=gemma3:4b

pte run 'YOUTUBE_URL' \
  --pastor PASTOR_SLUG \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The generated files are:

```text
/Users/briancummings/Documents/PastorSearchData/pastors/PASTOR_SLUG/exports/review.md
/Users/briancummings/Documents/PastorSearchData/pastors/PASTOR_SLUG/exports/review.json
```

Run every configured source with the same adaptive extraction and per-pastor
review behavior:

```bash
pte run --all \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

To intentionally stop after extraction:

```bash
pte run 'YOUTUBE_URL' \
  --pastor PASTOR_SLUG \
  --skip-review \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The standalone entry points use the same extraction service:

```bash
pte extract --classifier auto \
  --base-dir /Users/briancummings/Documents/PastorSearchData
pte review PASTOR_SLUG --classifier auto \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Classifier behavior: `rules` never calls Ollama, `auto` tries it by default and
falls back safely, and `llm` reports an extraction failure when Ollama is
unavailable. An unchanged forced extraction reuses the raw
inference cache keyed by transcript, prompt, model digest, schema, and context.

## Repeatable Classification Workflow

List videos first because `pte reclassify --video-id` expects the database's numeric video ID, not the YouTube ID:

```bash
pte video list --limit 250 --base-dir /Users/briancummings/Documents/PastorSearchData
```

Reclassify one existing extraction without retranscribing it:

```bash
pte reclassify \
  --video-id 46 \
  --force \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Reclassify every extracted video belonging to one source:

```bash
pte reclassify \
  --source-id SOURCE_ID \
  --force \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Use `--force` for algorithm, prompt, or adjudication experiments. This path reuses existing timestamped transcript segments and raw inference cache entries; it does not download or transcribe the video again. The command reports cache hits and misses. An unchanged second pass should normally have zero misses.

Every new or refreshed artifact also persists `final_disposition` at the top
level and inside the classification audit:

- `accepted_sermon`: high-confidence effective window or authoritative manual override
- `review_required`: plausible candidate, medium/low confidence, or guest-speaker concern
- `rejected_no_sermon`: no effective window and no diagnostic candidate
- `rejected_ambiguous_speakers`: reserved for grounded multi-speaker ambiguity evidence

Candidates remain in the search audit regardless of disposition. Pastor review
exports include content only from the effective window; rejected results and
candidate-only review results never fall back to the complete transcript.

The classification audit for each video is written to:

```text
<base-dir>/pastors/<pastor-slug>/videos/<youtube-id>/extracted/llm-classification-v1.json
```

## Frozen Fixture Regression

The current fixtures are under `evaluation/fixtures/`. Validate their schema before evaluation:

```bash
pte validate-fixtures evaluation/fixtures
```

The fixture files themselves are the authoritative list of YouTube IDs and expected outcomes. To reproduce the current full rerun with two concurrent classification jobs:

```bash
pte reclassify \
  --fixture-dir evaluation/fixtures \
  --force \
  --jobs 2 \
  --recording-verifier-model gemma3:12b \
  --recording-verifier-cache-root evaluation/recording-verifier/cache \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Then evaluate the frozen fixtures:

```bash
pte evaluate \
  --fixture-dir evaluation/fixtures \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

After accepting the fixture regression, propagate the classifier across the
existing corpus:

```bash
caffeinate pte reclassify \
  --all \
  --force \
  --jobs 2 \
  --recording-verifier-model gemma3:12b \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The corpus run inspects every database video, processes only readable proposed
artifacts with timestamped segments, and counts missing or invalid artifacts as
skipped. Completed raw inference is cached per video, so an interrupted forced
run can reuse successful block inference when restarted. The summary reports
reclassified, reused, skipped, and failed counts.

Each run creates timestamped files under `evaluation/results/<timestamp>/`:

- `results.json` for machine-readable regression comparison
- `report.md` for human inspection
- per-video failure-analysis reports where applicable

Do not edit or derive fixtures from detected boundaries. Only manually reviewed files in `evaluation/fixtures/` are ground truth; `evaluation/drafts/` remains unreviewed detector output.

## Current Benchmark

The accepted pre-verifier 44-fixture localization report is:

- `evaluation/results/20260722T215614Z/report.md`

Results:

- mean sermon recall: `0.992`
- worst sermon recall: `0.9012345679012346`
- catastrophic omissions: `0`
- mean contamination ratio: `0.101`
- correct top-candidate rate: `1.000`
- high-confidence negative false positives: `0`
- negative `accepted_sermon` dispositions: `0`
- automatic coverage before recording verification: `15/44` (`0.341`)
- automatic accuracy before recording verification: `15/15` (`1.000`)

### Recording-level verifier promotion

The frozen `gemma3:12b` verifier was evaluated only on fixtures whose existing
4B result required review. It uses the recording title plus the recording
opening and candidate opening, midpoint, and ending. The frozen results were:

| Partition | Correct automatic decisions | Unresolved | Errors |
|---|---:|---:|---:|
| development | 9/9 | 1 | 0 |
| legacy | 15/15 | 2 | 0 |
| held-out | 2/2 | 0 | 0 |

The held-out run is
`evaluation/recording-verifier/20260723T211301Z/report.md`. Across the 29
previously review-required fixtures, the verifier resolves 26 with zero known
automatic errors. Combined with the 15 existing automatic outcomes, projected
coverage is 41/44 (`0.932`) before guest-speaker safeguards. The remaining
three cases stay unresolved.

The pre-title recovery increment raised `fcZNzRYQOtA` recall from `0.891` to `1.000`, with contamination increasing by only `0.0006` absolute. Its persisted diagnostic records a `168.04`-second extension stopped by music.

When evaluating a behavior change, compare every positive fixture to the preceding accepted result. In addition to the main recall and negative-confidence gates, reject a positive fixture's contamination increase above `+0.02` absolute unless sermon recall materially improves.

### Confidence ablation result

The evaluator replays four policies from persisted evidence:

- `current`: production `soft_rule_overlap_v2`, including the long recording-edge expansion cap
- `legacy_hard_rule_overlap`: the former policy, where rule overlap below `0.5` forced low
- `no_rule_overlap`: confidence from retained content, uncertainty, and central consistency only
- `soft_rule_overlap`: the same evidence, with low overlap downgrading an otherwise-high result by one tier but never forcing low

The frozen fixtures produced:

| Policy | Positive H/M/L | Negative H/M/L | High-confidence negative false positives |
|---|---:|---:|---:|
| current | 6/11/6 | 0/8/13 | 0 |
| legacy hard overlap | 2/4/17 | 0/1/20 | 0 |
| no rule overlap | 17/0/6 | 8/0/13 | 8 |
| soft rule overlap | 6/11/6 | 1/7/13 | 1 (`jWGOaKtwPT4`) |

Production uses the supported soft policy plus the recording-edge expansion cap. Every negative remains medium or low and none receives `accepted_sermon`. Removing overlap entirely makes eight negatives falsely high; replaying soft overlap without the new edge cap leaves `jWGOaKtwPT4` falsely high. Classification artifacts persist `confidence_policy_version`, so older results are invalidated without invalidating raw inference cache entries.

### Interaction-evidence experiment (not shipped)

An evidence-only interaction classifier was tested with `gemma3:4b` on three sentinels:

- `WaNsL05AX3A`: Sabbath School negative
- `qny7TUqNkQU`: ambiguous chaplain-and-students program; reject the whole video
- `l6mZEQvArkE`: normal single-preacher sermon

The first schema asked directly for interaction mode, audience turn-taking, lesson references, and multiple sustained speakers. It failed badly: the model classified 21 of 22 normal-sermon blocks as facilitated group discussion. Repeated overlapping YouTube caption lines, rhetorical questions, and quoted biblical dialogue were interpreted as speaker changes.

A grounded second schema required exact current-block evidence and normalized unsupported positive claims. It produced these candidate-level mode counts:

| Fixture | Available blocks | Sermon monologue | Mixed/unclear | Grounded positive interaction signals |
|---|---:|---:|---:|---|
| `l6mZEQvArkE` | 16/22 | 10 | 6 | none |
| `qny7TUqNkQU` | 24/33 | 7 | 17 | none |
| `WaNsL05AX3A` | 21/30 | 2 | 19 | multiple speakers in 1 block only |

Although monologue density differed, the requested explicit signals did not reliably survive grounding. The extra diagnostic call also roughly doubled fine-pass latency. The implementation was removed, the three production artifacts were restored from cached production inference, and the frozen benchmark remained unchanged.

Do not reintroduce these fields into production confidence with the current transcript representation and `gemma3:4b`. Any future attempt should first address overlapping-caption duplication and should run as an offline sentinel experiment before modifying persisted production schema.

## Test Workflow

This project uses the standard-library `unittest` runner; `pytest` is not installed in the existing virtual environment:

```bash
.venv/bin/python -m unittest discover -s tests -q
git diff --check
```

Codex should run focused unit tests while developing; Brian runs the complete
suite and dataset validation commands.

## Identity Increment 1

The first pastor-recognition increment is intentionally non-recognizing and
non-gating. It establishes the persistence and policy seams needed by later
metadata, clustering, and voice-verification work without modifying sermon
isolation artifacts.

New SQLite tables:

- `metadata_artifacts`
- `identity_evidence`
- `identity_assessments`

New per-video artifacts are written under `identity/`. Discovery metadata is
content-addressed and immutable. Existing videos receive a normalized database
backfill when their first shadow assessment is created. The initial evidence
ledger records source assignment as `context_only` / `prior_only`; it never
confirms the assigned pastor as speaker. Every initial assessment therefore has
state `profile_unavailable` and recommends review.

The decision coordinator persists both a proposed identity-aware outcome and an
effective outcome. In shadow mode, the effective outcome remains the existing
content disposition, so review exports continue to use the stable production
path. Extraction and unchanged reclassification inputs generate identity
assessments idempotently through a content-derived fingerprint.

Use the dedicated backfill path for historical extractions. It reads the latest
`proposed.json`, creates identity-only artifacts, and does not invoke the local
LLM or rewrite extraction output:

```bash
pte identity backfill --base-dir /Users/briancummings/Documents/PastorSearchData
```

Production migration verification on 2026-07-15:

- first backfill: 178 created, 5 skipped, 0 failed
- replay: 0 created, 178 reused, 5 skipped, 0 failed
- all 12 frozen videos: `profile_unavailable`, shadow mode, `database_backfill` provenance
- all 12 pre-migration `proposed.json` SHA-256 hashes remained unchanged
- all 36 frozen identity artifact hashes remained unchanged across replay
- evaluator metrics remained identical to the accepted benchmark

## Identity Increment 2

The second identity increment adds deterministic, grounded attribution
extraction without acoustic dependencies. It reads titles plus any available raw
descriptions and chapter titles, and scans exact transcript segments around the
sermon handoff. If no effective sermon window exists, it scans for the same
strict handoff patterns across the transcript so compound programs can still
surface explicit speaker introductions.

Supported shadow outcomes:

- `explicit_guest_attribution`
- `explicit_target_attribution`
- `metadata_target_match`
- `metadata_non_target_match`
- `spoken_introduction_target`
- `spoken_introduction_guest`
- `conflicting_attribution`
- `no_attribution_evidence`

Every metadata observation includes the metadata artifact id/hash, source kind,
field path, exact excerpt, and match offsets. Every spoken observation includes
a stable segment line ID such as `S000883`, segment index, timestamps, exact
excerpt, and match offsets. Overlapping caption repetitions are collapsed.
Credits repeated across title, description, chapters, or transcript use a shared
person-scoped correlation group and count as one independent attribution source.

The assessment remains `profile_unavailable`, recommends review, and runs in
shadow mode regardless of attribution outcome. Explicit target evidence supports
the target hypothesis; explicit guest evidence contradicts it; non-explicit
non-target metadata matches remain context-only. A name appearing in a prayer,
sermon example, memorial title, topic, style, or theology never becomes an
explicit speaker attribution without grounded credit syntax.

Production shadow verification of the final matcher on 2026-07-15:

- first v3 backfill: 178 created, 5 skipped, 0 failed
- replay: 0 created, 178 reused, 5 skipped, 0 failed
- outcomes: 148 no evidence, 18 metadata target matches, 11 metadata non-target matches, 16 explicit target attributions, 10 explicit guest attributions, 1 spoken guest introduction
- all 178 v3 assessments remained `profile_unavailable`, review-only, and shadow-mode
- all 356 v3 identity artifacts retained aggregate SHA-256 `7ebccd80420a7640172f3b3cc38696cd7c10c575bc6c462572a59121297aa2f8` across replay
- all 12 frozen `proposed.json` hashes remained unchanged
- sermon evaluation metrics remained identical to the accepted benchmark

An earlier v2 diagnostic pass remains in the append-only audit history. The
final v3 matcher prevents a nearby non-credit mention (for example, “thanks to
Andrew Korp”) from inheriting another named person's speaker credit.

## Identity Architecture Decision

Identity is now speaker-centered rather than target-centered. The permanent
vocabulary distinguishes four concepts:

- an **observation** is one occurrence of a principal-speaker candidate in an isolated sermon
- a **cluster** is a versioned, disposable hypothesis produced by a future matching experiment
- a **profile** is a durable, curated speaker identity
- a **name claim** is grounded evidence associating a name with an observation or profile

The requested pastor remains a configured query identity. Target/non-target and
guest-speaker results are downstream policy projections, not properties stored
on neutral observations or claims.

Safety invariants:

- predictions never become profile exemplars automatically
- clusters never become profiles automatically
- metadata names never name acoustic profiles automatically
- profile membership and name attachment require explicit review events
- merges use append-only redirects and can be cleared by a later event
- fragmentation is preferred to false merging
- identity remains shadow-only and cannot modify sermon isolation or exports

## Identity Increment 3

Increment 3 implements only the neutral registry substrate. It does not extract
audio, compute embeddings, compare voices, create clusters, or attach any sermon
to a profile automatically.

New additive tables:

- `speaker_profiles`
- `pastor_speaker_bindings`
- `speaker_observations`
- `speaker_name_claims`
- `profile_observation_events`
- `profile_name_claim_events`
- `speaker_profile_redirect_events`

Configured pastors seed named but `unprofiled` identities. This records the
requested person without asserting that any video contains that person's voice.
A `principal_speaker_candidate` observation is created only when the persisted
extraction has a valid sermon window; its multiplicity remains `unknown`.
Attribution claims can remain video-scoped when no valid speaker observation can
honestly be created. Exact metadata and transcript provenance is retained.

The minimal curated operations are create profile, attach or detach a reviewed
observation, attach or reject a reviewed name claim, create a merge redirect,
and clear a redirect. Each operation is append-only and keyed for idempotent
replay. A sophisticated split workflow is intentionally deferred.

Neutral claims are projected through `speaker_registry_shadow_v1` into the same
eight target-centered attribution outcomes from Increment 2. Assessment creation
fails safely if that compatibility projection diverges. Identity state remains
`profile_unavailable`; the coordinator continues to preserve the existing
content disposition.

Production shadow verification on 2026-07-15:

- pre-migration SQLite backup: `/tmp/PastorSearchData-pre-identity-increment3.db`
- first v4 backfill: 178 created, 5 skipped, 0 failed
- replay: 0 created, 178 reused, 5 skipped, 0 failed
- registry substrate: 7 configured profiles, 7 bindings, 135 valid-window observations, and 32 grounded name claims
- all 7 configured profiles remain `unprofiled`
- membership events: 0; name-review events: 0; redirects: 0
- v3-only compatibility outcomes: 0; v4-only compatibility outcomes: 0
- all 178 v4 assessments remain `profile_unavailable`, review-only, and shadow-mode
- all 534 Increment 3 artifacts retained aggregate SHA-256 `de59fe41e5cbff85690bb20e88be197737622eee7be2359856aa1341fb17d4b2` across replay
- all existing `proposed.json` files retained aggregate SHA-256 `67a86ee366391f3ab399b2341f04eaa09dfe94c9259d0bded35a4c83e336af50`
- the then-frozen 12-fixture sermon metrics remained identical to that benchmark

The next acoustic increment should answer only: “Do these two independently
isolated sermons contain the same principal speaker?” It should run offline and
must not name speakers, mutate profiles, or gate production.

## Remaining Defects

### `qny7TUqNkQU`

This fixture was changed to `no_sermon` in ground-truth version 2. Its title identifies a chaplain and students, and manual review found student sermonettes between presumed primary sermons. Production still produces a low-confidence diagnostic candidate, but its disposition is `review_required`, never `accepted_sermon`.

### `WaNsL05AX3A`

The Sabbath School fixture is medium confidence and `review_required`. The classifier still produces a sermon candidate because the schema does not explicitly represent interactive or facilitated Bible teaching.

## Recommended Next Increment

The offline harness is now implemented as `pte diagnose-interaction`. It:

- reads the selected production candidate but never writes production artifacts
- creates fixed 180-second excerpts
- removes repeated and incrementally growing adjacent caption lines
- applies one shared prompt and schema to every model
- requires exact current-excerpt evidence for positive signals
- records raw responses, validation failures, malformed output, and per-block evidence
- caches successful inference by model digest, prompt, schema, and excerpt

The first `gemma3:4b` run is under `evaluation/interaction-diagnostics/20260713T194751Z/`. It failed the sentinel test:

| Fixture | Valid blocks | Result |
|---|---:|---|
| `WaNsL05AX3A` | 3/15 | all mixed/unclear; no grounded interaction signals |
| `l6mZEQvArkE` | 1/12 | mixed/unclear; no grounded interaction signals |
| `qny7TUqNkQU` | 4/17 | all mixed/unclear; no grounded interaction signals |

There were three malformed inference responses. Most other blocks claimed facilitated discussion without the required audience-turn and speaker evidence. Deduplication alone therefore does not make Gemma 3 4B viable for this distinction.

The first `gemma3:12b` comparison is under `evaluation/interaction-diagnostics/20260713T211300Z/`. Its raw mode labels were materially better:

| Fixture | Raw facilitated-group blocks | Raw audience-turn blocks | Exact-evidence-valid blocks |
|---|---:|---:|---:|
| `WaNsL05AX3A` | 14/15 | 15/15 | 0/15 |
| `l6mZEQvArkE` | 3/12 | 5/12 | 7/12 |
| `qny7TUqNkQU` | 11/17 | 13/17 | 2/17 |

The model separated both negative compound/interactive programs from the normal sermon at the aggregate raw-label level, which is the relevant policy after `qny7TUqNkQU` became negative. It was not production-ready: it frequently paraphrased, joined, or reformatted evidence instead of returning an exact excerpt, so nearly all positive interaction claims failed grounding.

The line-ID follow-up is under `evaluation/interaction-diagnostics/20260714T133117Z/` and used `interaction-diagnostic-line-evidence-v3`. Its schema constrained evidence to actual current-block IDs such as `L001`; a 180-second Ollama timeout was required for 12B.

| Fixture | Valid blocks | Group discussion | Audience turns | Multiple speakers | Consistency warnings |
|---|---:|---:|---:|---:|---:|
| `WaNsL05AX3A` | 12/15 | 10 | 10 | 0 | 10 |
| `l6mZEQvArkE` | 11/12 | 0 | 2 | 0 | 0 |
| `qny7TUqNkQU` | 13/17 | 8 | 3 | 1 | 8 |

The raw mode distribution separates both negatives from the normal sermon, but the production evidence gate still fails. Every negative `facilitated_group_discussion` result lacked the required combination of grounded audience-turn and multiple-speaker evidence. The qny ambiguity signal in particular is mostly an unsupported aggregate judgment, not transcript-grounded speaker evidence. Six of 44 calls also failed inference despite the longer timeout. Production artifacts were not modified.

Next:

1. Do not add transcript-only interaction evidence to production confidence and do not replace the production 4B model with 12B.
2. Use the new explicit disposition as the safety boundary: candidate-only and ambiguous results remain `review_required` and never fall back to a full transcript in review exports.
3. If automatic rejection of ambiguous programs is still required, run the next experiment on speaker-turn structure or diarization rather than another prompt/schema iteration.

Speaker diarization or voice recognition may ultimately be required for reliable multiple-speaker evidence. Do not infer speaker identity or turn-taking from duplicated caption text alone.

## Recent Milestones

- `45817c4 Promote expanded sermon evaluation baseline`
- `501394a Add reviewed sermon evaluation fixtures`
- `6d1e84b Improve sermon candidate identification`
- confidence ablation evaluator: current vs no-overlap vs soft-overlap
- `a2ea8f0 Recover sermon setup before explicit anchors`
- `4aa8fd7 Recompute stable rule baselines on reclassification`
- `0835616 Expand sermon evaluation fixtures`
- `190bae6 Join interrupted sermon candidates conservatively`
- `2f09652 Persist sermon classification diagnostics`
- `d9e954a Add extraction failure analysis reports`
- `1732f80 Add segment-based extraction evaluator`
- `8e3a45f Unify adaptive sermon classification`
