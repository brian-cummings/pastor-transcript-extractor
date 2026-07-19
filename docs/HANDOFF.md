# Handoff Notes

## Current State

The sermon-isolation pipeline has a safe production path and a frozen evaluation set.

Implemented:

- normal extraction and reclassification share adaptive V3 classification
- raw Ollama inference is cached by transcript, prompt, model, schema, and block context
- candidate ranking, score components, confidence reasons, model identity, and refinement reasons are persisted
- low-confidence classifications preserve the protected rule/manual baseline
- forced reclassification recomputes the rule-only baseline instead of reusing a prior hybrid result
- ground-truth review supports positive and negative fixtures
- 12 manually reviewed fixtures are frozen: 5 positive and 7 negative
- evaluation is segment-based and produces JSON and Markdown reports
- failure reports show expected, missed, retained, and contaminating ranges with persisted label evidence
- conservative candidate joining can recover interrupted sermons
- explicit sermon-title cues can recover up to four minutes of contiguous sermon-like setup before the cue
- pre-title recovery persists its anchor, duration, reason, and stopping evidence
- production confidence uses versioned soft rule overlap; the evaluator also replays the legacy hard-veto and no-overlap policies
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
- profile membership and naming require explicit review events; clustering and acoustic-driven registry matching remain unimplemented
- acoustic increment 4 adds a read-only, local pairwise speaker diagnostic with exact cached audio spans and pinned model provenance
- acoustic outcomes remain non-gating; no default threshold exists and uncalibrated comparisons abstain
- reviewed pair fixtures pin observation fingerprints and exact WAV hashes; evaluation separates recognition errors, abstention, and analysis failure
- a blinded pair-review workflow now qualifies each observation before allowing a binary same/different judgment
- review submissions are append-only; indeterminate reviews never become fixtures and re-reviews never overwrite frozen truth
- media foundation separates immutable source/normalized audio from transcript artifacts
- caption-backed isolated sermons can acquire verified audio without invoking local ASR
- historical local-ASR audio migrates as reconstructed provenance without file modification
- media acquisition outcomes distinguish verified, unavailable, and failed; they remain non-gating for sermon content
- universal acquisition is an explicit shadow command and has not been inserted into the stable `run` workflow
- no acoustic prediction mutates profiles, memberships, name claims, target policy, or sermon artifacts
- 251 tests pass

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

## Acoustic Pair Experiment

The next recognition question is intentionally limited to whether two reviewed
principal-speaker observations contain the same person. The implementation and
evaluation contract are documented in
`evaluation/speaker-pairs/README.md`.

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

The frozen YouTube IDs are:

```text
Positive: OBK7fBLTM6o TyNvrFPC5AU fcZNzRYQOtA l6mZEQvArkE tad-oXefJMQ
Negative: jJDBYaE33gA NeceoWYZRmg NKNFh_xoDfU QIqMpJfY-fQ WaNsL05AX3A dTDAt941Gf8 qny7TUqNkQU
```

At the time of this handoff, their local numeric database IDs are:

| Database ID | YouTube ID | Expected outcome |
|---:|---|---|
| 46 | `fcZNzRYQOtA` | sermon |
| 50 | `l6mZEQvArkE` | sermon |
| 57 | `jJDBYaE33gA` | no sermon |
| 71 | `NeceoWYZRmg` | no sermon |
| 78 | `OBK7fBLTM6o` | sermon |
| 81 | `tad-oXefJMQ` | sermon |
| 82 | `qny7TUqNkQU` | no sermon (ambiguous speakers) |
| 85 | `NKNFh_xoDfU` | no sermon |
| 89 | `QIqMpJfY-fQ` | no sermon |
| 148 | `WaNsL05AX3A` | no sermon |
| 185 | `dTDAt941Gf8` | no sermon |
| 188 | `TyNvrFPC5AU` | sermon |

Verify those mappings with `pte video list` before relying on them in another database. To reproduce the current full rerun:

```bash
for id in 46 50 57 71 78 81 82 85 89 148 185 188; do
  pte reclassify \
    --video-id "$id" \
    --force \
    --base-dir /Users/briancummings/Documents/PastorSearchData || exit 1
done
```

Then evaluate the frozen fixtures:

```bash
pte evaluate --base-dir /Users/briancummings/Documents/PastorSearchData
```

Each run creates timestamped files under `evaluation/results/<timestamp>/`:

- `results.json` for machine-readable regression comparison
- `report.md` for human inspection
- per-video failure-analysis reports where applicable

Do not edit or derive fixtures from detected boundaries. Only manually reviewed files in `evaluation/fixtures/` are ground truth; `evaluation/drafts/` remains unreviewed detector output.

## Current Benchmark

The latest validated 12-fixture report, rerun after the final identity increment
2 production shadow backfill, is:

- `evaluation/results/20260715T173039Z/report.md`

Results:

- mean sermon recall: `0.975`
- worst sermon recall: `0.917`
- catastrophic omissions: `0`
- mean contamination ratio: `0.032`
- correct top-candidate rate: `1.000`
- high-confidence negative false positives: `0`
- negative `accepted_sermon` dispositions: `0`

The pre-title recovery increment raised `fcZNzRYQOtA` recall from `0.891` to `1.000`, with contamination increasing by only `0.0006` absolute. Its persisted diagnostic records a `168.04`-second extension stopped by music.

When evaluating a behavior change, compare every positive fixture to the preceding accepted result. In addition to the main recall and negative-confidence gates, reject a positive fixture's contamination increase above `+0.02` absolute unless sermon recall materially improves.

### Confidence ablation result

The evaluator replays four policies from persisted evidence:

- `current`: production `soft_rule_overlap_v1`
- `legacy_hard_rule_overlap`: the former policy, where rule overlap below `0.5` forced low
- `no_rule_overlap`: confidence from retained content, uncertainty, and central consistency only
- `soft_rule_overlap`: the same evidence, with low overlap downgrading an otherwise-high result by one tier but never forcing low

The frozen fixtures produced:

| Policy | Positive H/M/L | Negative H/M/L | High-confidence negative false positives |
|---|---:|---:|---:|
| current | 1/4/0 | 0/2/5 | 0 |
| legacy hard overlap | 0/1/4 | 0/0/7 | 0 |
| no rule overlap | 5/0/0 | 2/0/5 | 2 (`WaNsL05AX3A`, `qny7TUqNkQU`) |
| soft rule overlap | 1/4/0 | 0/2/5 | 0 |

Production now uses the supported soft policy. All five positive fixtures are high or medium, while every negative remains medium or low and none receives `accepted_sermon`. Removing overlap entirely still makes both the Sabbath School and ambiguous multi-speaker negatives falsely high. Classification artifacts persist `confidence_policy_version`, so old hard-veto results are invalidated without invalidating raw inference cache entries.

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

The expected count at this handoff is 185 tests.

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
- the frozen 12-fixture sermon metrics remain identical to the accepted benchmark

The next acoustic increment should answer only: “Do these two independently
isolated sermons contain the same principal speaker?” It should run offline and
must not name speakers, mutate profiles, or gate production.

## Remaining Defects

### `qny7TUqNkQU`

This fixture was changed to `no_sermon` in ground-truth version 2. Its title identifies a chaplain and students, and manual review found student sermonettes between presumed primary sermons. Because the retained speech cannot be attributed confidently to the targeted pastor, policy now rejects the entire compound program rather than attempting to isolate individual speakers from transcript text.

### `WaNsL05AX3A`

The Sabbath School fixture is now low confidence and baseline-protected, but the classifier still produces a sermon candidate because the schema does not explicitly represent interactive or facilitated Bible teaching.

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

- confidence ablation evaluator: current vs no-overlap vs soft-overlap
- `a2ea8f0 Recover sermon setup before explicit anchors`
- `4aa8fd7 Recompute stable rule baselines on reclassification`
- `0835616 Expand sermon evaluation fixtures`
- `190bae6 Join interrupted sermon candidates conservatively`
- `2f09652 Persist sermon classification diagnostics`
- `d9e954a Add extraction failure analysis reports`
- `1732f80 Add segment-based extraction evaluator`
- `8e3a45f Unify adaptive sermon classification`
