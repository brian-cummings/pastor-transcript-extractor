# Pastor profile implementation plan

**Current as of 2026-10-23.** The [product plan](PASTOR_PROFILE_PRODUCT_PLAN.md) defines the reader experience; this document is the active engineering sequence. [AGENTS.md](../AGENTS.md#reuse-and-responsibility-in-the-evidence-pipeline) governs evidence reuse and insertion points.

## Delivered baseline and closed implementation goal

**V8 is the current generated review profile.** Profile 318 uses recordings 3973 / 281 / 4589. The original milestones 1–3 and D1–D4 are implemented; subsequent refinements through D7 delivered a meaningful opening portrait. The old D1–D4 goal was marked **complete** on 2026-10-23. Brian’s “looking much better” feedback is recorded, while concrete wording acceptance and production admission remain separate.

| Deliverable | Current state |
|---|---|
| Opening assessment and at-a-glance | Delivered in V8, with seven authored provisional interpretations. |
| Evidence-to-description assembly and source navigation | Delivered; fourteen reviewed descriptions, 29 underlying reader descriptions and seven interpretive additions. |
| Supporting examples | Same 53 original selected example sets; interpretation uses the reviewed-point ledger rather than independently selecting measured examples. |
| Consequential-gap map | Delivered; eight gaps remain visible. Remedies are conditional on actual reuse and authorization. |
| General profile generator | Not demonstrated. Profile 318’s authored interpretations are example-specific. |
| Original goal | Complete. No active portability goal has been created. |

V8’s description fingerprint is `0b6f4d0cedaf64a0f4cfc2958c3101e8605823c5090e845a43fcbea2daed8545`; manifest `b1f0bd2b0830157196e722586daaed08aca87c84bc0fbc949d758685c2b928a5`. The 163-word opening and `portrait-review-v1.md/json` are saved under the app base in `evaluation/pastor-profile-description-v8/<manifest>/`. Review fingerprint: `48fb5acf6eefa9413158408977be65f09bb12a0d07b6032e97f240e9e490fe28`.

Generation/review made zero provider requests, metadata probes and database writes. Raw observations, original claims, bindings, fourteen explanatory points, examples and gaps match V7; original reader content/evidence is unchanged apart from version tags. Source/implementation hashes, seals and links pass. Latest focused checks: 123 profile tests and 8 plan tests. No visual browser layout review was performed. Implementation commits: `a90e213`, `a19078f`.

## Existing path and responsibilities

Processing order: **compatible category/leaf evidence → reviewed local meanings → recording/sample aggregation → reviewed portrait interpretation → supporting source blocks → optional held quotation**.

| Existing component | Responsibility |
|---|---|
| `profile_description.load/build` | Read eligible compatible saved evidence and retain source, measurement and missing-state provenance. |
| `profile_explanatory_descriptions` | Assemble exact reviewed style examples/local bindings, with voice, adoption, qualifications and proposal status. |
| `profile_presentation` and authored editorial inputs | Present descriptions, local accounts, concise table entries and evidence disclosures. Exact-point digests guard authored wording. |
| `profile_portrait` and `profile-portrait-authored-v1.json` | Seven authored cross-point warrants, limits and alternatives. Changed support withholds dependent interpretation. Hashes verify compatibility, not truth. |
| `profile_supporting_blocks` | Reuse eligible full-block examples for established point records. Portrait interpretations trace through those records. |
| Existing category-leaf/shared binding producer | Own missing support/refutation, speaker/adoption, conditions and related local semantic distinctions. The portrait cannot supply them. |

The current workflow is centered on the prepared profile 318 example. The generic rendering/validation helpers do not establish that an arbitrary second profile can be selected and populated by the current CLI. Exposing a bounded profile input, if needed, is part of the proposed portability work below; no unsupported second-profile command is advertised.

## Next proposed increment P1: one cached second-profile portability case

**Status: proposed, not implemented or executed.** This documentation update does not start another goal or authorize provider, collection or semantic expansion. Complete this bounded slice before considering general automatic synthesis or further model work.

### P1.1 Prepare one concrete case

Codex selects one different profile with existing reviewed membership, eligible canonical source text and compatible saved analytical evidence. Use its existing bounded recording set; do not collect sermons, invent a sample or run a corpus inventory/evaluation. Inspect only enough existing state to select this one case and establish exact compatibility. Brian is not assigned selection, JSON authoring or experimental design.

If no suitable case exists in the inspected scope, report the exact missing prerequisite and smallest remedy; do not replace the task with a new global inventory or an inference run. Do not call the case independent validation or a statistical benchmark.

### P1.2 Reuse the existing assembly path

Reuse current loaders/resolvers, observations, individual leaf/refinement/composed answers and compatible reviewed bindings. Trace source/context, question meaning, model/version, eligibility and admission status. A full-pack mismatch does not establish constituent absence.

Add only the narrow profile-selection/input plumbing required by this concrete case and wire it through `pte analysis`, reusing the existing loader, reader and artifact path. Keep profile 318 reproducible. Prepare the exact CLI command once the input and supported option actually exist; do not require standalone scripts or fabricate a currently runnable selector.

Never copy profile 318’s source hashes, reviewed propositions or portrait wording onto the new case. Reusable code/record shapes and evidence-responsibility rules may transfer; example-specific interpretations require their own support.

### P1.3 Produce a second readable profile with explicit authoring boundaries

Work backward from the portrait facets: theological center, preaching approach, sample emphases, pastoral posture, possible strengths and questions. Use only meanings supported by the available evidence. Describe topic attention as attention; do not upgrade it to belief.

Where compatible reviewed meanings support a broader interpretation, prepare the explicit warrant, limits, alternative explanation and source links. Mark any Codex-authored interpretation as manual reviewed work pending reader acceptance; do not present it as automatic discovery. Keep a count/list of authored inputs so the actual degree of automation is visible. Authored interpretation can connect established meanings but cannot reconstruct missing local semantics from raw passages or probabilities.

Missing facets remain unknown. Complete the best defensible readable profile instead of making completeness a prerequisite. Keep meaning-changing limits in the sentence and technical reasoning underneath. Sampling/selection bias must be visible where it affects the apparent center or posture.

### P1.4 Verify and deliver, without a new evaluation program

Deliver through `pte`: the second profile HTML/Markdown/JSON, supporting evidence, interpretation ledger, authoring disclosure and a concise consequential-gap report. Generated files belong under the configured app base. Use focused unit checks and one bounded artifact review, not large fixtures, reclassification or corpus evaluation.

Acceptance checks:

- Every substantive clause traces through the reviewed meaning to exact observations and source segments.
- No profile 318 wording or source identity is transplanted; missing/changed inputs cannot inherit its interpretation.
- Original evidence and measurement meanings remain unchanged; missing, unresolved, below-threshold and contrary findings stay distinct.
- Output is readable even where dimensions remain unknown; manual interpretation and automatic assembly are distinguishable.
- No provider calls, new measurements, collection, scoring/ranking, production activation or quotation execution occur.
- The existing profile 318 output remains reproducible; source/hash/link checks pass for both concrete cases.

The final report must distinguish **reused automatically**, **authored interpretation required**, and **missing upstream meaning**. For each consequential gap, name the blocked statement, inspected reuse outcomes, responsible producer, smallest remedy, acceptance check and authorization boundary. Generality is established only to the extent this case demonstrates it; two examples do not validate a ministry-wide assessment system.

**Exit:** one actual second profile plus a concrete account of the remaining repeatability gap, or an exact cached-evidence prerequisite that blocks it. No third case, model variant, broader collection or upstream semantic change follows automatically. Brian reviews the prepared result and any consequential proposal; Codex owns interpretation and recommendations.

## Holds and closed branches

The following remain held: new provider/model calls; new or broadened measurements; broader collection; production admission/activation; benchmark similarity/ranking; calibrated confidence and single pastor scores; ministry-wide stability; Ollama quotation execution. A quote illustrates a supported point and cannot repair missing analysis. The [segment/quotation policy](SEGMENT_EVIDENCE_PLAN.md) remains a foundational boundary, not a new execution queue.

TypeSafe automatic binding V1/V2, connected extraction and S1 Ollama editorial synthesis are completed unsuccessful experiments. Preserve raw responses, usage and semantic reviews. V2 synthesis passed structure but failed semantic review; no automatic retry, smaller-schema loop, model switch or fallback is active. Historical “Keep V5” instructions described those runs’ immediate outcome; V8 is now the current review product. The [synthesis status page](PASTOR_PROFILE_SYNTHESIS.md) is diagnostic history, not an active writing workflow.

## Current commands, ownership and history

Reproduce profile 318 or inspect compatibility without writes:

```bash
pte analysis structure-readiness --segment-view --description --json
pte analysis structure-readiness --segment-view --description --check-only --json
pte analysis structure-readiness --segment-plan --json
```

These commands do not run P1. Normally Brian executes dataset validation; a specific exception may authorize Codex, as it did for V6–V8. No standing permission for future model calls is inferred. All new workflows need a `pte` CLI tie-in, exact prepared inputs and Markdown/JSON review reports. Preserve unrelated working-tree changes and commit coherent work frequently.

The [pre-portability implementation snapshot](PASTOR_PROFILE_IMPLEMENTATION_PLAN.historical-before-portability-2026-10-23.md) preserves the full prior roadmap and completed increments. [Historical documentation index](PASTOR_PROFILE_HISTORY.md) identifies the exact snapshots. Archived commands are not active instructions. No cached results, receipts, source evidence or prior profile output has been deleted.
