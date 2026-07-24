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

## Review workflow

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

It rotates through shared-attribution, contradicting-attribution, and
unattributed nomination strata; excludes drafted and reviewed pairs; favors
unused observations; and prepares audio only after selection. Attribution is
selection metadata only. It is hidden from the packet and never supplies the
fixture outcome or speaker-profile membership. Repeating the command advances
because the prior draft is part of the derived selection history.

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
