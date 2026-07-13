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
- 12 manually reviewed fixtures are frozen: 6 positive and 6 negative
- evaluation is segment-based and produces JSON and Markdown reports
- failure reports show expected, missed, retained, and contaminating ranges with persisted label evidence
- conservative candidate joining can recover interrupted sermons
- explicit sermon-title cues can recover up to four minutes of contiguous sermon-like setup before the cue
- pre-title recovery persists its anchor, duration, reason, and stopping evidence
- 130 tests pass

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
Positive: OBK7fBLTM6o TyNvrFPC5AU fcZNzRYQOtA l6mZEQvArkE qny7TUqNkQU tad-oXefJMQ
Negative: jJDBYaE33gA NeceoWYZRmg NKNFh_xoDfU QIqMpJfY-fQ WaNsL05AX3A dTDAt941Gf8
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
| 82 | `qny7TUqNkQU` | sermon |
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

- `evaluation/results/20260713T132331Z/report.md`

Results:

- mean sermon recall: `0.979`
- worst sermon recall: `0.917`
- catastrophic omissions: `0`
- mean contamination ratio: `0.105`
- correct top-candidate rate: `1.000`
- high-confidence negative false positives: `0`

The pre-title recovery increment raised `fcZNzRYQOtA` recall from `0.891` to `1.000`, with contamination increasing by only `0.0006` absolute. Its persisted diagnostic records a `168.04`-second extension stopped by music.

When evaluating a behavior change, compare every positive fixture to the preceding accepted result. In addition to the main recall and negative-confidence gates, reject a positive fixture's contamination increase above `+0.02` absolute unless sermon recall materially improves.

## Test Workflow

This project uses the standard-library `unittest` runner; `pytest` is not installed in the existing virtual environment:

```bash
.venv/bin/python -m unittest discover -s tests -q
git diff --check
```

The expected count at this handoff is 130 tests.

## Remaining Defects

### `qny7TUqNkQU`

Candidate joining restored sermon recall to `1.000`, but contamination remains about `0.472`. The long student-participation interval is still classified as sermon content. The remaining problem is representing and adjudicating mixed discourse inside the selected region.

### `WaNsL05AX3A`

The Sabbath School fixture is now low confidence and baseline-protected, but the classifier still produces a sermon candidate because the schema does not explicitly represent interactive or facilitated Bible teaching.

## Recommended Next Increment

1. Extend fine structured output with evidence fields such as:
   - `interaction_mode`
   - `audience_turn_taking`
   - `lesson_material_references`
   - `multiple_sustained_speakers`
2. Persist these signals without initially changing retention or confidence.
3. Rerun the 12 frozen fixtures to establish an evidence-only baseline.
4. Add a confidence cap when strong interactive-teaching evidence is present.
5. Rerun the same fixtures unchanged.
6. Determine whether the same evidence can safely exclude the long `qny7TUqNkQU` interruption or whether interruption-aware retention needs a separate increment.

Do not compare a stronger model until the evidence schema and confidence behavior are stable. Model comparisons must keep fixtures, prompt, schema, block construction, ranking logic, and thresholds fixed so only the model changes.

## Recent Milestones

- `a2ea8f0 Recover sermon setup before explicit anchors`
- `4aa8fd7 Recompute stable rule baselines on reclassification`
- `0835616 Expand sermon evaluation fixtures`
- `190bae6 Join interrupted sermon candidates conservatively`
- `2f09652 Persist sermon classification diagnostics`
- `d9e954a Add extraction failure analysis reports`
- `1732f80 Add segment-based extraction evaluator`
- `8e3a45f Unify adaptive sermon classification`
