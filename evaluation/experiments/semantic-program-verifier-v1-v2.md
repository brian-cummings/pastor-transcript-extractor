# Semantic Program Verifier Experiment: v1 and v2

## Status

- Experiment date: 2026-07-17
- Final status: unsuccessful; not promoted
- Active production integration: none
- Localization baseline retained: commit `97a14f3`
- Production effect during experiment: diagnostic-only; verifier output never changed boundaries, confidence, or dispositions

The experiment tested whether `gemma3:4b` could distinguish a worship-service sermon from religious education, compound programs, devotionals, and non-sermon events after the localization pipeline had selected and refined a candidate.

The experiment answered that question negatively. Sparse global transcript samples with this model did not support safe semantic gating. The implementation was removed from active classification and evaluation code after the experiment.

## Motivation

The accepted localization pipeline reached:

- mean sermon recall: `0.9998604618712063`
- worst sermon recall: `0.9984650805832693`
- mean contamination ratio: `0.038762593789502614`
- correct top-candidate rate: `1.0`
- catastrophic omissions: `0`
- negative accepted dispositions: `0`

Remaining negative candidates were primarily semantic cases rather than localization failures, including Sabbath School, religious education, compound programs, and multiple short messages.

The verifier was tested as a possible future replacement for some of the safety work still performed by soft rule overlap. It was never allowed to perform that replacement during the experiment.

## Shared Experimental Design

Each eligible classification produced two independent diagnostic judgments:

1. `transcript_only`: no title or source metadata.
2. `metadata_assisted`: the same evidence plus the video title.

The input representation was deterministic and sampled:

- recording opening;
- candidate opening;
- candidate middle;
- candidate ending;
- recording ending;
- coarse phase distribution.

The output taxonomy was:

- `worship_sermon`
- `religious_education`
- `compound_program`
- `devotional`
- `non_sermon`
- `ambiguous`

The schema also requested reason codes, timestamped evidence, a metadata-used flag, and the verifier version. Successful inferences were cached separately for transcript-only and metadata-assisted variants using the existing model-digest and prompt-aware raw inference cache.

The verifier was explicitly prohibited from:

- modifying candidate boundaries;
- identifying speakers;
- changing confidence;
- changing final disposition;
- assigning fixture truth.

## Version 1: `semantic-program-v1`

### Policy

Version 1 asked the model to classify the overall program from the deterministic global samples. It distinguished sustained worship preaching from interactive lessons, compound programs, brief devotionals, and non-sermon events. It permitted up to four reason codes and four free-text evidence items.

### Evaluation run

- Run ID: `20260717T210401Z`
- JSON: `evaluation/results/20260717T210401Z/results.json`
- Report: `evaluation/results/20260717T210401Z/report.md`

### Operational result

- eligible transcript-only results completed: `3`
- transcript-only semantic negatives among sermon fixtures: `0` among completed outputs
- transcript-only semantic negatives among no-sermon fixtures: `3` among completed outputs
- metadata-assisted classification disagreements: `2`

This apparent precision was invalid because most eligible results failed validation:

- normal one-decimal timestamp rounding was rejected as outside an exact sample range;
- some outputs omitted evidence;
- verbose evidence exceeded Ollama's configured `num_predict=256`, producing truncated JSON.

Inspection of cached raw outputs showed that accepting the otherwise parseable classifications would have labeled approximately `6/11` sermon fixtures as semantic negatives. Version 1 therefore failed both operationally and substantively.

## Version 2: `semantic-program-v2`

### Changes from v1

Version 2 attempted a conservative asymmetric policy:

- semantic-negative labels required explicit program-structure evidence;
- weak or conflicting evidence was directed to `ambiguous`;
- sustained mostly one-way preaching was directed to `worship_sermon`;
- title metadata could not justify a semantic-negative label by itself;
- output was limited to three reason codes and two short evidence items;
- timestamp evidence allowed one second of rounding tolerance;
- missing evidence was measured rather than silently treated as a successful grounded result.

### Evaluation run

- Run ID: `20260717T213713Z`
- JSON: `evaluation/results/20260717T213713Z/results.json`
- Report: `evaluation/results/20260717T213713Z/report.md`

### Operational result

- eligible transcript-only results: `18/18`
- grounded transcript-only results: `18/18`
- metadata-assisted classification disagreements: `4/18`
- localization metrics: unchanged from the accepted baseline

Version 2 fixed the harness problems but failed the semantic safety test.

### Transcript-only confusion

| Frozen expected outcome | worship_sermon | religious_education | compound_program | Semantic negatives |
|---|---:|---:|---:|---:|
| sermon (11) | 7 | 3 | 1 | 4 |
| no_sermon with eligible candidate (7) | 5 | 2 | 0 | 2 |

- semantic-negative detection among eligible negatives: `2/7`
- false semantic rejection among sermons: `4/11`

### Metadata-assisted confusion

| Frozen expected outcome | worship_sermon | religious_education | compound_program | Semantic negatives |
|---|---:|---:|---:|---:|
| sermon (11) | 9 | 2 | 0 | 2 |
| no_sermon with eligible candidate (7) | 3 | 3 | 1 | 4 |

- semantic-negative detection among eligible negatives: `4/7`
- false semantic rejection among sermons: `2/11`

Metadata changed four classifications. Those changes happened to move `8vv9vdAVUc8` and `tad-oXefJMQ` toward their frozen positive outcomes and `jJDBYaE33gA` and `qny7TUqNkQU` toward their frozen negative outcomes. However, metadata-assisted output still falsely rejected two sermons and missed three eligible negatives. It was not safe for gating.

## Representative Unsupported Decisions

### `OBK7fBLTM6o` — sermon mislabeled as religious education

The verifier cited a prayer-meeting opening and a musical segment as evidence for `religious_education`. Those excerpts did not establish facilitated lesson structure, participant answers, or a class format. Both transcript-only and metadata-assisted variants rejected the positive fixture.

### `l6mZEQvArkE` — sermon mislabeled as religious education

The transcript-only output cited recording-opening camp-meeting and registration announcements. The candidate itself began with an explicit sermon title and prayer. Recording-edge administration improperly overrode candidate structure.

### `tad-oXefJMQ` — sermon mislabeled as a compound program

The transcript-only output cited sustained exposition about dominion and stewardship as evidence for `compound_program`. The evidence did not show independent short messages or speaker handoffs. Metadata changed the result to `worship_sermon`.

### `jq3AkCzvnE0` — negative mislabeled as a worship sermon

Both variants cited worship preparation and a detailed opening message, failing to recognize the broader compound-program problem represented by the frozen fixture.

### `qny7TUqNkQU` — unstable dependence on metadata

Transcript-only returned `worship_sermon`; metadata-assisted returned `compound_program`. The fixture contains student sermonettes and cannot supply one reliable principal sermon for the target workflow. The disagreement showed that the sparse transcript representation did not independently establish the program structure.

## Cached Evidence

Raw successful outputs remain under each video's existing extraction cache in the external data directory:

```text
/Users/briancummings/Documents/PastorSearchData/pastors/<pastor>/videos/<video>/extracted/inference-cache/semantic-transcript-only/
/Users/briancummings/Documents/PastorSearchData/pastors/<pastor>/videos/<video>/extracted/inference-cache/semantic-metadata-assisted/
```

These caches are experimental evidence only. The active classifier no longer reads or writes these namespaces.

## Conclusion

Neither verifier version met promotion requirements.

The failure was not merely malformed output or overly strict validation. Version 2 completed reliably with grounded timestamps and still showed:

- low semantic-negative recall;
- an unsafe sermon false-rejection rate;
- unsupported relationships between cited evidence and assigned labels;
- material title dependence.

No semantic output should influence production confidence or disposition. Soft rule overlap must remain in place because the no-rule-overlap ablation still promotes four negative fixtures to high confidence.

## Conditions for a Future Retry

A future semantic program classifier should be treated as a separate experiment and dataset. It should not be retried until there is:

- independent `recording_type` and `candidate_type` ground truth;
- a dedicated annotation guide;
- broader source-family coverage;
- fuller candidate context or hierarchical summaries;
- a stronger model than the tested 4B configuration;
- explicit conservative abstention;
- near-zero false semantic rejection on validation and held-out sermon fixtures.

Until then, semantic negatives remain `review_required`, and localization remains frozen at `97a14f3` unless new reviewed data exposes a repeated cross-family failure.
