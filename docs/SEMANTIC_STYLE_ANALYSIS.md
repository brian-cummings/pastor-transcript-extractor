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
| Model proposal | Dimension, full candidate-run boundaries, and smaller support boundaries | Pinned model and prompt |
| Accepted supporting evidence | `semantic_style_evidence` with a compact source-grounded excerpt that proves the category | Deterministic validator |
| Candidate representative run | `semantic_style_run` with source-grounded boundaries and links to its supporting evidence | Accepted model proposal plus conservative continuation merging |
| Derived sermon measurement | Separate accepted-evidence and candidate-run counts, durations, and coverage | Immutable evidence and run records |
| Profile aggregation | Separate lower-bound evidence density and unreviewed candidate-run measurements | Immutable style analyses and effective profile membership |

Raw model quotations, timestamps, explanations, arbitrary labels, and invented
segment IDs are never persisted as analysis evidence. A SHA-256 of each raw
model response is retained for provenance without treating unsupported content
as evidence.

## Generation and deterministic validation

The block builder presents non-overlapping groups of timestamped sermon
segments, targeting at most 75 seconds or 3,600 characters. Previous and
following segments provide context but have no citable IDs. The JSON schema
restricts dimensions and restricts start/end IDs to the current block.

For every proposed category, the model must return a compact supporting span and
the full contiguous style run inside the current block. The grounding validator
then independently validates both spans and requires:

- a recognized dimension and exact current-block segment IDs;
- source-order start/end boundaries;
- a unique contiguous span;
- source timestamps with positive duration no longer than 120 seconds; and
- at least ten source transcript words.

The support span must be contained by the proposed run. The observable lexical
acceptance gate is applied only to the compact support span; it cannot validate
invented or expanded run text. Duplicate proposals for the same dimension in a
block are rejected.

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

## Supporting evidence versus style runs

Supporting evidence answers: **what compact transcript excerpt makes this
classification defensible?** It remains a conservative lower bound and is
stored as `semantic_style_evidence`.

A candidate style run answers: **over what complete contiguous interval does
this semantic mode remain active?** It is stored separately as
`semantic_style_run` and links to one or more supporting-evidence keys. Runs in
adjacent inference blocks merge only when the earlier run reaches its block's
last segment, the later run begins at its block's first segment, the blocks are
consecutive, and the timestamp gap is no more than 15 seconds. This permits
explicit continuation without merging across an unclassified transition.

Candidate boundaries remain `unreviewed` until the full-sermon workflow below
has established their quality. They are not silently promoted to reviewed fact.

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
- `accepted_evidence_duration_seconds` and
  `accepted_evidence_coverage_fraction`, explicitly lower-bound measurements;
- candidate representative run count, duration, coverage, and boundary status;
  and
- Scripture-corroborated evidence count.

Run diagnostics also record timestamped transcript coverage, block count,
proposal and rejection counts, model-response hashes, and full model, prompt,
block-builder, grounding-validator, and acceptance-policy provenance.

The immutable `profile-style-evidence` derivation aggregates exact style analysis
IDs for effective profile membership. For each dimension it records evidence
per sermon and per thousand words, accepted evidence duration and coverage,
sermons-with-evidence fraction, lower-bound coverage consistency
(`1 / (1 + population CV)`), candidate-run duration and coverage, candidate-run
boundary status, and corroborated count.
Per-sermon supporting measurements and run IDs remain in
`sermon_style_support`. Missing sermon analyses remain explicit coverage gaps.
Mixed model or prompt configurations are rejected at aggregation time so an
interrupted model migration cannot silently produce an incomparable profile.

## Model and prompt provenance

The category-only reviewed baseline for analyzer version 2 used:

- backend: local Ollama chat with JSON-schema output;
- model: `gemma3:4b`;
- model digest:
  `a2af6cc3eb7fa8be8504abaf9b04e88f17a119ec3f04a3addf55f92841195f5a`;
- temperature: `0`;
- output budget: `384` tokens;
- prompt: `sermon-style-evidence-v3`;
- block builder: `nonoverlapping-75s-3600chars-v1`;
- grounding validator: `grounded-segment-spans-v1`; and
- style acceptance policy: `observable-dimension-gates-v1`.

Analyzer version 3 uses prompt `sermon-style-runs-v1`, output budget `512`, the
two-span proposal schema, and continuation policy
`boundary-touching-continuation-v1`. The model name, exact digest, context size, temperature, prompt version and
template hash, block version, and validation versions participate in run
provenance and fingerprinting.

## Reviewed evaluation

`evaluation/sermon-style/reviewed-v2.json` contains twelve reviewed cases with
clear positives, overlaps, ambiguous cases, quotation-only and assertion-only
cases, passing examples, generic encouragement, and announcements. Run:

```bash
pte analysis evaluate-style evaluation/sermon-style/reviewed-v2.json
```

The current pinned Gemma 3 4B baseline is stored in
`evaluation/sermon-style/gemma3-4b-v3-baseline.json`. It produced 11 true
positives, 0 false positives, and 0 false negatives: **1.000 precision and 1.000
recall** on this small corpus, with all five negative controls passing. Version
2 explicitly records that a close textual explanation may also advance a
doctrinal implication. The prior prompt-v2/corpus-v1 result remains stored as a
historical baseline rather than being overwritten.

This is a small category behavior-locking corpus, not a population or boundary
estimate. The lexical
acceptance gates favor precision and will miss unfamiliar phrasing. Transcript
errors, segment boundaries, code-switching, subtle stories without explicit
event language, implicit doctrinal reasoning, and abstract application remain
important limitations. Non-overlapping inference blocks can miss evidence that
straddles a boundary, and duration is source-segment precision rather than
word-level timing.

## Full-sermon adjudication and boundary evaluation

Create one review packet per selected sermon. Version 3 runs expose their
candidate representative runs directly; for version 2 runs, each accepted
exemplar is deliberately presented as a `legacy_accepted_evidence_span`
candidate so its suspected undersizing can be reviewed without rerunning the
model first:

```bash
pte analysis style-review-create \
  --youtube-video-id VIDEO_ID \
  --output evaluation/sermon-style/full-sermon/VIDEO_ID.draft.json \
  --base-dir /path/to/data
```

The command writes an editable JSON draft and a Markdown inspection view. The
view contains the complete timestamped sermon with inline annotations for
accepted support, candidate runs, explicit/contextual references, and Bible-text
alignments. The JSON retains exact analysis run IDs and input fingerprints.

For every candidate run, replace `unreviewed` with one of:

- `correct_representative_boundaries`;
- `correct_but_undersized`, with corrected segment boundaries;
- `correct_but_oversized`, with corrected segment boundaries; or
- `incorrect_category`.

Add every entirely missed run to `missed_style_runs`. Sustained Scripture
engagement is deliberately visible for finding possible missed exegetical runs,
but reading or aligning with Scripture is not itself adjudicated as exegesis.
If a candidate has the wrong category but the same interval supports another
dimension, mark the candidate incorrect and add the correct run as missed; this
keeps false-positive and false-negative accounting explicit.
Finalize and evaluate with:

```bash
pte analysis style-review-finalize VIDEO_ID.draft.json \
  --reviewer REVIEWER --output VIDEO_ID.reviewed.json

pte analysis evaluate-style-boundaries \
  VIDEO_A.reviewed.json VIDEO_B.reviewed.json VIDEO_C.reviewed.json
```

Boundary evaluation reports run precision/recall, reviewed-duration recovery,
accepted-duration precision, and duration intersection-over-union, overall and
per dimension. These distinguish missed categories from correct categories with
incomplete boundaries.

The initial Profile 59 inspection found 35 high-confidence doctrinal excerpts
but only 6 exegetical excerpts despite extensive deterministic Scripture
engagement. That is evidence of lower-bound/exemplar behavior and motivated the
two-span contract; it is not a completed boundary gold standard. No finalized
full-sermon packets have yet been reviewed, so candidate-run duration and
coverage remain explicitly **unreviewed and unsuitable for substantive
profile-level interpretation**. The CLI marks them with an asterisk and labels
the older values as accepted evidence duration/coverage.

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
model, output budget, prompt, chunking, validation, or analyzer changes create a
new immutable run.

The profile fingerprint includes resolved profile identity, effective
observation membership, exact style run IDs, schema version, and profile
analyzer version. New sermon runs or membership changes create a new derivation;
unchanged inputs reuse the existing result.

## Natural next increment

The next increment should finalize two or three full-sermon packets, examine the
per-dimension boundary errors, and pin a reviewed boundary baseline. Only if
reviewed-duration recovery and accepted-duration precision are adequate should
candidate-run coverage be promoted to representative profile coverage. The same
review should determine whether remaining misses require better semantic
detection or only boundary refinement.
