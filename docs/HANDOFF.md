# Handoff Notes

## Current State

The sermon-isolation pipeline now has a safe production architecture and a frozen evaluation foundation.

Implemented:

- normal extraction and reclassification share adaptive V3 classification
- raw Ollama inference is cached by transcript, prompt, model, schema, and block context
- candidate ranking, score components, confidence reasons, model identity, and refinement reasons are persisted
- low-confidence classifications preserve the protected rule/manual baseline
- ground-truth review supports positive and negative fixtures
- seven manually reviewed fixtures are frozen
- evaluation is segment-based and produces JSON and Markdown reports
- failure reports show expected, missed, retained, and contaminating ranges with persisted label evidence
- conservative candidate joining can recover interrupted sermons
- joins require approved gap evidence and an explicit sermon-resumption cue
- 125 tests pass

## Current Benchmark

The latest seven-fixture report is:

- `evaluation/results/20260713T022657Z/report.md`

Results:

- mean sermon recall: `0.972`
- worst sermon recall: `0.917`
- catastrophic omissions: `0`
- mean contamination ratio: `0.199`
- correct top-candidate rate: `1.000`
- high-confidence negative false positives: `1`

Candidate discovery and assembly are now working well enough to expose the remaining taxonomy and confidence defects.

## Remaining Defects

### `qny7TUqNkQU`

Candidate joining restored sermon recall from `0.242` to `1.000`, but contamination remains `0.458`.

The long student-participation interval is still classified as sermon content. The remaining problem is no longer candidate discovery; it is representing and adjudicating mixed discourse inside the selected region.

### `WaNsL05AX3A`

The Sabbath School fixture remains a high-confidence false positive.

All refined blocks are classified as sermon/biblical exposition because the current schema does not represent interactive or facilitated Bible teaching. Confidence is over-weighting rule/LLM agreement and sustained religious discourse.

## Recommended Next Increment

1. Extend fine structured output with evidence fields such as:
   - `interaction_mode`
   - `audience_turn_taking`
   - `lesson_material_references`
   - `multiple_sustained_speakers`
2. Persist these signals without initially changing retention or confidence.
3. Rerun the seven frozen fixtures to establish an evidence-only baseline.
4. Add a confidence cap when strong interactive-teaching evidence is present.
5. Rerun the same fixtures unchanged.
6. Determine whether the same evidence can safely exclude the long `qny7TUqNkQU` interruption or whether interruption-aware retention needs a separate increment.

Do not compare a stronger model until the evidence schema and confidence behavior are stable. Model comparisons must keep fixtures, prompt, schema, block construction, ranking logic, and thresholds fixed so only the model changes.

## Recent Milestones

- `190bae6 Join interrupted sermon candidates conservatively`
- `2f09652 Persist sermon classification diagnostics`
- `d9e954a Add extraction failure analysis reports`
- `1732f80 Add segment-based extraction evaluator`
- `8e3a45f Unify adaptive sermon classification`
