# Speaker Pair Experiment

This directory is an offline evaluation boundary for one question:

> Do two immutable principal-speaker observations contain the same person?

It is not a speaker registry, clustering system, or target-pastor policy. The
experiment never creates profiles, attaches observations, accepts name claims,
or changes sermon content artifacts.

## Evidence contract

Each comparison uses five deterministic 12-second spans from the interior of
each observation. The local cache records the exact mono 16 kHz PCM WAV,
its SHA-256, the observation fingerprint, extraction coordinates, model
SHA-256, backend version, and embedding. Replaying the same spans and model
produces a byte-identical result JSON.

Operational cache-hit information is deliberately excluded from result
artifacts because it would make replay hashes vary.

The outcomes are:

- `same_speaker`
- `different_speaker`
- `insufficient_evidence`
- `analysis_failed`

Unavailable observations/audio, too few usable spans, inconsistent voice
evidence, an ambiguous score, and the absence of an approved decision policy
are evidence insufficiency. Decoder, cache-integrity, or model execution errors
are analysis failures.

## Conservative decision policy

There is no built-in similarity threshold. Installing a model does not create
a decision policy. Without an explicitly approved, versioned policy JSON, a
successful analysis persists its distributions and returns
`insufficient_evidence: decision_policy_unavailable`.

An approved policy uses:

- minimum valid spans per observation;
- minimum within-observation median similarity;
- lower-decile and median thresholds for `same_speaker`;
- an upper-decile threshold for `different_speaker`;
- a wide region between those bands that always abstains.

No prediction becomes a profile exemplar or registry membership.

## Local model

The provisional backend is sherpa-onnx 1.13.1 with the English CAMPPlus
VoxCeleb 16 kHz model. Install the optional dependency with:

```bash
python -m pip install -e '.[acoustic-experiment]'
```

Place the model at:

```text
evaluation/speaker-pairs/models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx
```

Its required SHA-256 is:

```text
357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b
```

Model binaries, audio spans, embeddings, run results, and reports are ignored.
See the [sherpa-onnx speaker identification documentation](https://k2-fsa.github.io/sherpa/onnx/speaker-identification/index.html)
for the local runtime and model family.

## Running a diagnostic

```bash
pte identity compare-speakers VIDEO_A VIDEO_B \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The default output is `runs/VIDEO_A--VIDEO_B.json`. Pass an approved policy
with `--policy-path` only after a reviewed development set has established
conservative thresholds.

## Running the model bake-off

The bake-off command always validates fixtures, verifies model files and exact
runtime versions, audits partitions, and persists its deterministic plan before
acoustic execution:

```bash
pte identity run-speaker-model-bakeoff \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The default `development` scope includes legacy fixtures created before
partition assignment, but does not execute validation or held-out fixtures.
Use `--preflight-only` to stop after validation and planning. Validation and
held-out execution require an explicit `--evaluation-scope`; do not use
`held_out` during model or threshold selection.

Results are namespaced by the complete model execution fingerprint. Reruns
checksum-validate and reuse completed jobs, while missing jobs resume from the
same plan. Every result must replay the exact reviewed WAV hashes and explicitly
prohibit registry mutation. The report summarizes raw similarity separation but
does not select a model or create a decision policy.

The first development-derived CAMPPlus policy remains a non-approved experiment.
Replay it against cached development metrics with:

```bash
pte identity evaluate-speaker-policy-candidate
```

The policy artifact is bound to the exact development fixture fingerprint and
model execution. Changing either invalidates replay. This command cannot load
validation or held-out fixtures, approve the policy, enable registry mutation,
or make the production `compare-speakers` command accept it as an approved
decision policy.

## Ground truth

Titles, descriptions, channel assignment, and name claims may help select
candidates for review, but they are not pair labels. A human reviewer must
listen to the exact cached spans and approve each fixture. Every fixture pins:

- both observation fingerprints;
- at least two reviewed WAV SHA-256 values per observation;
- `same_speaker` or `different_speaker`;
- reviewer and review timestamp;
- variation tags such as `different_date`, `different_microphone`,
  `different_room`, and `varied_audio_quality`.

Drafts belong under ignored `drafts/`. Only approved fixtures belong under
`fixtures/`.

## Anonymous-profile interaction

Anonymous speaker profiles belong to the curated registry, not to this
evaluation directory. Their lifecycle is reviewer-driven and append-only:
profile creation, observation qualification, attachment/detachment, and
explicit different-speaker constraints all retain reviewer attribution and can
be replayed. Source family may bound a review session but never supplies
membership evidence. Acoustic predictions cannot create any of these events.

The existing review ledger is synchronized into registry state with:

```bash
pte identity sync-reviewed-speaker-evidence \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Consistent observation qualifications are reused. Approved `same_speaker`
reviews form connected components that create or join curated anonymous
profiles; approved `different_speaker` reviews create exact constraints.
Conflicts, missing observations, transitive contradictions, and components
that already span multiple profiles are reported and not guessed through.
Every derived mutation cites an original reviewer and review event, and replay
is idempotent. This is reviewed component materialization, not acoustic
clustering.

The pair workflow is also the sole human input for anonymous-speaker grouping:

```bash
pte identity review-next-speaker-pair \
  --reviewer REVIEWER_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Do not run a second profile-assignment listening workflow. The established
packet already supplies observation qualification and blinded pairwise
same/different evidence. The selector may nominate follow-up pairs using
reviewed same-speaker components or curated registry relations. After a review
session, `sync-reviewed-speaker-evidence` derives anonymous profiles and exact
different-speaker constraints from those approved pair reviews. Thus profiles
contain only observations connected by explicit same-speaker evidence, without
presenting intentionally different observations as one group.

The default `--selection-objective evaluation` retains the existing
coverage-balanced selector. Use `--selection-objective profile-growth` to keep
the identical blinded packet and adjudication while changing nomination
priority. Profile-growth mode favors reviewed-component frontiers, new component
seeds, and component bridges; it excludes already-connected components and any
candidate components separated by an explicit reviewed different constraint.
Source-family membership remains partition and queue context, never
same-speaker evidence.

Selector v8 in the default evaluation objective may use two explicit curated
relations to nominate an unseen pair:

- observations effectively attached to the same reviewed profile are strong
  positive candidates;
- an effective explicit different-speaker constraint nominates that exact
  negative pair.

These are nomination signals, not evaluation labels. The selected exact pair
and exact cached spans must still pass the blinded workflow below before a
fixture can be frozen. Separate profiles do not imply different speakers, and
source-family co-membership does not imply the same speaker.

## Review workflow

Preprocess the validation observations before a review session:

```bash
pte identity prepare-speaker-review-audio \
  --evaluation-scope validation \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

This performs the slow work without selecting pairs or creating drafts,
reviews, or fixtures. It full-hash verifies each source artifact, records a
local verification receipt tied to the file's path, size, inode, and
modification time, then prepares the same deterministic speech-qualified clips
used by review. Subsequent review commands reuse a receipt only while the
source file is unchanged and checksum-validate every cached clip. Media audit
continues to perform independent full-content verification. Use `--limit N`
for a short trial, and match `--evaluation-scope` to the review session.

Prepare and review a candidate pair with:

```bash
pte identity review-speaker-pair VIDEO_A VIDEO_B \
  --reviewer REVIEWER_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

For deterministic corpus expansion, let the selector nominate the next pair:

```bash
pte identity review-next-speaker-pair \
  --reviewer REVIEWER_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

After freezing a development policy candidate, collect validation fixtures
without changing its development fingerprint:

```bash
pte identity review-next-speaker-pair \
  --evaluation-scope validation \
  --reviewer REVIEWER_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The scoped selector admits only observations whose source families belong to
that partition, persists the requested scope, and still prohibits
cross-partition pairs. Held-out nomination requires an explicit
`--evaluation-scope held_out`; routine validation never accesses it.

It rotates through shared-attribution, contradicting-attribution, and
unattributed nomination strata; excludes drafted and reviewed pairs; favors
unused observations; and prepares audio only after selection. Attribution is
selection metadata only. It is hidden from the packet and never supplies the
fixture outcome or speaker-profile membership. Repeating the command advances
because the prior draft is part of the derived selection history.

The selector also derives frozen fixture outcome balance independently within
each requested evaluation partition. When `different_speaker` exceeds
`same_speaker` by at least two fixtures, it first tries a conservative
same-speaker anchor expansion: one member of a frozen, human-reviewed
`same_speaker` pair is compared with an unused observation only when both carry
the same exact grounded name attribution. Source-family or church membership
alone is never a same-likelihood signal. A candidate is excluded from this
same-seeking objective when it already has a reviewed `different_speaker`
constraint against any member of the reviewed-same component containing that
anchor. This component is derived only for fixture sampling. It does not create
a transitive fixture label, identity cluster, profile, or bypass independent
review of the nominated pair. If no qualified expansion exists, normal
diversity rotation continues with `same_likely_candidates_exhausted` recorded
in the selection reasons.

Automatic candidates must be current observations of accepted sermons. The
selector requires a readable latest extraction with a persisted top-level
`accepted_sermon` disposition, a valid current sermon window, an observation
from that extraction whose boundaries match the window, usable diagnostic
spans, and verified normalized media. Review-required, rejected, malformed,
unknown, and stale observations are excluded. Accepted manual sermon-window
overrides remain eligible when the current observation matches the override.
This eligibility gate does not alter pair ranking, stratum rotation, history,
or the blinded packet.

The command extracts the same deterministic spans used by diagnostics and
opens a local HTML packet. The packet labels the groups only as Observation A
and Observation B, randomizes their presentation deterministically, and hides
video IDs, titles, names, channels, and metadata. Candidate-selection metadata
may nominate a pair, but it is never shown as identity evidence in the packet.

Use `--prepare-only` to generate the packet without adjudicating it, or
`--no-open-packet` when reviewing the HTML separately.

Review has two gates:

1. Qualify each observation as `single`, `multiple`, `invalid`, or `cannot`.
   `single` means every retained clip contains one consistent principal
   speaker. The workflow currently rejects the entire observation rather than
   letting a reviewer silently discard an inconvenient clip.
2. If and only if both observations qualify, judge the pair as `same`,
   `different`, or `cannot`.

`different` is binary: the two observations do not contain the same principal
speaker. It does not ask the reviewer to select or name another profile.

Every submission is written under `reviews/<pair-id>/` as a content-addressed,
append-only event. An explicitly confirmed `same` or `different` review with
two qualified observations may create `fixtures/<pair-id>.json`. Indeterminate,
invalid, and unconfirmed reviews remain review evidence without becoming
recognition ground truth.

An existing fixture is never overwritten. A consistent re-review adds another
event and leaves the fixture unchanged. A conflicting re-review is also
preserved, flags `existing_conflict_preserved`, and requires later human
adjudication; it does not silently change evaluation truth.

```bash
pte identity validate-pair-fixtures evaluation/speaker-pairs/fixtures
pte identity evaluate-pair-results \
  --fixture-dir evaluation/speaker-pairs/fixtures \
  --result-dir evaluation/speaker-pairs/runs
```

The evaluator refuses span substitutions: result WAV hashes must exactly match
the reviewed fixture hashes. It reports false-same and false-different counts
separately from abstention and technical failure.

## Promotion gate

The immediate gate is zero observed false-same and false-different decisions.
That alone is not enough to claim high precision on a tiny sample. The default
promotion report also requires:

- at least 300 decisions of each outcome with zero observed errors;
- all required recording-condition variation tags;
- one pinned model and one approved policy;
- no missing/non-replayable results or technical failures.

With zero errors, the report includes the rule-of-three approximate 95% upper
error bound (`3 / decisions`). Three hundred decisions therefore support an
upper bound near 1% for each decision direction. Abstentions do not count as
errors, but they also do not help meet the decision-count gate.

Threshold selection must use a development split. The promotion gate must be
measured once on a held-out split containing unseen dates and, where possible,
unseen channels/rooms. Repeated tuning against the held-out split invalidates
it.
