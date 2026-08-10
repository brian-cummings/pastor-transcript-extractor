# Evidence-backed Sermon Style Analysis

This iteration introduces the first semantic analysis stage without assigning a
global sermon style or pastor score. The stage consumes already-identified
sermon transcript segments and the current deterministic Scripture analysis.
The model may only propose a style dimension and two source segment IDs.
Everything durable—timestamps, transcript text, duration, word count, and
Scripture corroboration—is reconstructed from persisted source data.

## Initial dimensions

- `exegetical_exposition`: explains the meaning, context, wording, structure,
  or implications of a biblical text. A quotation or reference without
  explanation is insufficient.
- `narrative_illustration`: recounts a concrete personal experience, observed
  event, or developed story to illuminate a sermon point. Passing examples and
  hypotheticals are insufficient.
- `doctrinal_argument`: develops a reasoned claim about Christian belief using
  premises, distinctions, support, consequences, or alternatives. A bare
  assertion is insufficient.
- `practical_application`: directs listeners toward a concrete action,
  practice, decision, relationship, or lived response. Generic encouragement
  is insufficient.

Dimensions are independent and may overlap on the same transcript span.

## Evidence and derivation layers

| Layer | Durable representation | Authority |
|---|---|---|
| Source transcript | Identified sermon segments with source indexes and timestamps | Extraction result |
| Deterministic observation | `sermon-basics@4` Scripture references and text alignments | Deterministic analyzer |
| Model proposal | Dimension plus start/end source segment IDs | Pinned model and prompt |
| Accepted semantic evidence | `semantic_style_evidence` with source-derived excerpt/timestamps and validation provenance | Deterministic validator |
| Derived sermon measurement | Counts, union duration, sermon coverage, sustained runs, and corroborated counts | Accepted evidence only |
| Profile aggregation | Frequency, duration coverage, sermon prevalence, consistency, and exact sermon-run support | Immutable style runs and effective profile membership |

Raw model quotations, timestamps, explanations, arbitrary labels, and invented
segment IDs are never persisted as analysis evidence. A SHA-256 of each raw
model response is retained for provenance without treating unsupported content
as evidence.

## Generation and deterministic validation

The block builder presents non-overlapping groups of timestamped sermon
segments, targeting at most 75 seconds or 3,600 characters. Previous and
following segments provide context but have no citable IDs. The JSON schema
restricts dimensions and restricts start/end IDs to the current block.

The grounding validator then independently requires:

- a recognized dimension and exact current-block segment IDs;
- source-order start/end boundaries;
- a unique contiguous span;
- source timestamps with positive duration no longer than 120 seconds; and
- at least ten source transcript words.

A second, versioned style acceptance policy requires observable structure
appropriate to the proposed dimension: textual/interpretive language for
exegesis, an event anchor and narrated action for illustration, both doctrinal
vocabulary and reasoning for doctrinal argument, and a concrete response cue
for application. These gates are intentionally conservative and are not
standalone classifiers; a span must first be proposed by the semantic model.

Accepted timestamps, excerpts, hashes, and word counts come from the source
segments. Invalid proposals contribute only to rejection diagnostics. The
complete run and all accepted evidence are inserted atomically, so an
interruption cannot expose a partial analysis run.

## Scripture corroboration

Style analysis requires the current `sermon-basics@4` run. Every accepted span
is checked for overlapping `scripture_reference` and
`scripture_text_alignment` evidence. Matching evidence keys and canonical
references are attached as corroboration. Corroboration is particularly useful
for explaining exegetical evidence, but it is never required: a preacher can
explain a text without a detected citation or close WEB alignment.

Scripture evidence does not create a semantic style span, and semantic evidence
does not modify deterministic reference or alignment counts.

## Sermon and profile measurements

For each sermon and dimension, `style_dimension_measurements` records:

- accepted evidence count;
- union duration and fraction of sermon duration;
- sustained runs and sustained duration, where evidence separated by no more
  than 15 seconds forms a run and a run of at least 60 seconds is sustained; and
- Scripture-corroborated evidence count.

Run diagnostics also record timestamped transcript coverage, block count,
proposal and rejection counts, model-response hashes, and full model, prompt,
block-builder, grounding-validator, and acceptance-policy provenance.

The immutable `profile-style-evidence` derivation aggregates exact style run
IDs for effective profile membership. For each dimension it records evidence
per sermon and per thousand words, total duration and duration coverage,
sermons-with-evidence fraction, mean sermon coverage, coverage consistency
(`1 / (1 + population CV)`), sustained-run count, and corroborated count.
Per-sermon supporting measurements and run IDs remain in
`sermon_style_support`. Missing sermon analyses remain explicit coverage gaps.
Mixed model or prompt configurations are rejected at aggregation time so an
interrupted model migration cannot silently produce an incomparable profile.

## Model and prompt provenance

The reviewed baseline uses:

- backend: local Ollama chat with JSON-schema output;
- model: `gemma3:4b`;
- model digest:
  `a2af6cc3eb7fa8be8504abaf9b04e88f17a119ec3f04a3addf55f92841195f5a`;
- temperature: `0`;
- prompt: `sermon-style-evidence-v2`;
- block builder: `nonoverlapping-75s-3600chars-v1`;
- grounding validator: `grounded-segment-spans-v1`; and
- style acceptance policy: `observable-dimension-gates-v1`.

The model name, exact digest, context size, temperature, prompt version and
template hash, block version, and validation versions participate in run
provenance and fingerprinting.

## Reviewed evaluation

`evaluation/sermon-style/reviewed-v1.json` contains twelve reviewed cases with
clear positives, overlaps, ambiguous cases, quotation-only and assertion-only
cases, passing examples, generic encouragement, and announcements. Run:

```bash
pte analysis evaluate-style evaluation/sermon-style/reviewed-v1.json
```

The pinned Gemma 3 4B baseline is stored in
`evaluation/sermon-style/gemma3-4b-v2-baseline.json`. It produced 9 true
positives, 0 false positives, and 1 false negative: **1.000 precision and 0.900
recall** overall, with all five negative controls passing. Exegesis, narrative,
and doctrine each measured 1.000 precision/recall on this small set. Practical
application measured 1.000 precision and 0.667 recall; the model abstained on
one clear imperative passage.

This is a small behavior-locking corpus, not a population estimate. The lexical
acceptance gates favor precision and will miss unfamiliar phrasing. Transcript
errors, segment boundaries, code-switching, subtle stories without explicit
event language, implicit doctrinal reasoning, and abstract application remain
important limitations. Non-overlapping inference blocks can miss evidence that
straddles a boundary, and duration is source-segment precision rather than
word-level timing.

## Running and inspecting

First ensure deterministic sermon analysis is current, then create semantic
evidence:

```bash
pte analysis run --profile-id PROFILE_ID --base-dir /path/to/data
pte analysis style-run --profile-id PROFILE_ID --base-dir /path/to/data
```

Inspect sermon evidence, including exact transcript spans and Scripture
corroboration:

```bash
pte analysis style-show --youtube-video-id VIDEO_ID --base-dir /path/to/data
pte analysis style-show --profile-id PROFILE_ID --base-dir /path/to/data
```

Materialize and later inspect the profile derivation:

```bash
pte analysis style-summarize-profile --profile-id PROFILE_ID --base-dir /path/to/data
pte analysis style-show-profile --profile-id PROFILE_ID --base-dir /path/to/data
```

## Idempotency and invalidation

The sermon fingerprint includes canonical sermon content, analyzer/schema
versions, the exact deterministic Scripture run and its fingerprint, model name
and digest, model configuration, prompt version and template hash, block
version, and validation versions. An unchanged fingerprint is checked before
any model request and reuses the prior complete run. Source, Scripture run,
model, prompt, chunking, validation, or analyzer changes create a new immutable
run.

The profile fingerprint includes resolved profile identity, effective
observation membership, exact style run IDs, schema version, and profile
analyzer version. New sermon runs or membership changes create a new derivation;
unchanged inputs reuse the existing result.

## Natural next increment

The next increment should add human adjudication and sampling for accepted and
rejected semantic evidence. Reviewed production decisions can expand the
evaluation corpus, expose per-model drift, and calibrate conservative acceptance
policies before the reusable semantic layer is applied to theology or sensitive
political and Christian-nationalism indicators.
