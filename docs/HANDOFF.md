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
- the evaluator replays current, no-overlap, and soft-overlap confidence policies without changing production artifacts
- extraction and reclassification persist an explicit final disposition separately from diagnostic candidates
- rejected videos never fall back to a full-transcript excerpt in pastor review exports
- the offline interaction harness uses stable current-excerpt line IDs for grounded evidence
- 149 tests pass

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
export PTE_LLM_ENABLED=1
export PTE_LLM_MODEL=gemma3:4b
pte doctor --base-dir /Users/briancummings/Documents/PastorSearchData
```

`pte doctor` should report Ollama connectivity, the installed model, and structured output as ready.

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

The latest validated 12-fixture report is:

- `evaluation/results/20260714T133247Z/report.md`

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

The evaluator replays three policies from persisted evidence:

- `current`: production confidence, where rule overlap below `0.5` forces low
- `no_rule_overlap`: confidence from retained content, uncertainty, and central consistency only
- `soft_rule_overlap`: the same evidence, with low overlap downgrading an otherwise-high result by one tier but never forcing low

The frozen fixtures produced:

| Policy | Positive H/M/L | Negative H/M/L | High-confidence negative false positives |
|---|---:|---:|---:|
| current | 0/1/4 | 0/0/7 | 0 |
| no rule overlap | 5/0/0 | 2/0/5 | 2 (`WaNsL05AX3A`, `qny7TUqNkQU`) |
| soft rule overlap | 1/4/0 | 0/2/5 | 0 |

This supports retaining rule overlap as a soft diagnostic penalty. Removing it entirely makes both the Sabbath School and ambiguous multi-speaker negatives falsely high; the soft policy moves all positive fixtures out of low confidence without making any negative high. This is evaluation evidence only: production confidence behavior has not yet changed.

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

The expected count at this handoff is 149 tests.

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
4. Adopt soft rule overlap only after the disposition-aware benchmark confirms that no negative receives `accepted_sermon`.

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
