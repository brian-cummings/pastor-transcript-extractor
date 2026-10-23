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
| Original goal | Complete. The separately authorized P1 case is now delivered; reader acceptance remains pending. |

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

The default workflow remains profile 318/V8. The bounded selector below adds exactly one prepared case through the same assembly, leaf-reuse inspection, reviewed-point validation, portrait-warrant validator, supporting-block selection and HTML/Markdown reader. It does not enable arbitrary-profile selection.

## Completed P1: one cached second-profile portability case

**Status: delivered and artifact-reviewed, 2026-10-23; Brian reader acceptance pending.** Brian explicitly authorized Codex to select, prepare and execute this provider-free case. P1 stops here; no third case or upstream semantic experiment is active.

### P1.1 Prepared case and reuse

Profile **130**, recordings **1037 / 350 / 4430**, was selected from the existing twelve-source inventory by remaining eligible-block coverage after excluding 318. Current reviewed ownership, eligible canonical sources, topic question/model identities, treatment targets, salvation routing/policy and frozen observation thresholds pass. The other twelve effective profile members are outside this sample.

The existing assembler reuses 154 topic blocks, 154 treatment blocks and 47 routed salvation blocks. Independent exact-path checks also find **36 saved answers / 220 raw leaf observations** across nine listener/public-life/source-material packs on four blocks of recording 4430, including individual/refinement forms. Same-question dependence, original question meaning, request provenance and unadmitted status remain in the ledger. Full-pack absence was not treated as constituent absence. Exact-current Scripture runs are unavailable for all three recordings. The curated reviewed binding packet fails exact source/inventory/membership compatibility and supplies zero bindings; no remapping is attempted. Other G1/G2/G3 result stores were not inventoried, and global absence is not asserted.

### P1.2 Narrow CLI integration

`profile_portability.py` pins profile 130 and its three prepared recording IDs. The existing inventory builder can read only those IDs and fails if any becomes incompatible or changes ownership. `pte analysis structure-readiness --segment-view --description --profile-id 130` uses that path; other explicit IDs fail. Omit the selector for unchanged profile 318. No collector, provider, cache refill, new semantic contract or production projection was added.

The source-controlled `data/profile-portability-130-v1.json` contains **four manually authored style descriptions and three cross-point interpretations**. The existing exact-source and full-point-digest guards withhold changed support. The opening connects a repertoire of textual comparison, contrasting accounts, anecdote and application; its possible benefit and review question remain explicitly interpretive. This is manual authoring by Codex pending Brian’s acceptance, not automatic discovery.

The apparent adopted theological center and pastoral posture are visibly unknown. Authored style descriptions do not create proposition, voice, adoption, polarity, recipient or qualification bindings. Topic summaries retain attention-only meaning. Missing/below-threshold/unrouted/unresolved states remain distinct.

### P1.3 Delivered artifacts and review

```bash
pte analysis structure-readiness --segment-view --description --profile-id 130 --json
pte analysis structure-readiness --segment-view --description --profile-id 130 --check-only --json
```

Final artifacts are under the configured app base in:

`evaluation/pastor-profile-portability-p1/b71806632436ea3eff9f5df37d10edd3ca232ca2875ea7de76d79673efe97a67/`

- `index.html`, `profile-p1.md`, `description-p1.json`: actual readable profile, evidence, exact source identities and authoring ledger.
- `review-p1.md/json`: automatic reuse, manual interpretation and consequential gaps.
- `consequential-gaps-p1.md/json`: compact gap table plus full inspected paths, missing fields, producer, smallest remedy, acceptance and authorization boundaries.
- `artifact-review-p1.md/json`: saved artifact and manual warrant review. Fingerprint `ec6b65a03804628ee74f670026c83a92bd38c415b3cb89f905e49566ea79feb9`.

Description fingerprint: `f33f0ab5d9eff2144f129986aa89fa9b008b4138b3908a76d061e00f1a778e40`.

The case has 20 reader claims, four explanatory points, three portrait interpretations and 34 selected full-block example sets. Artifact checks pass for seals, current source/implementation hashes, claim-to-observation links, exact interpretation supports, 2,090 unique HTML targets and 1,297 internal links, plus Markdown navigation. Manual review confirms the warrants stay within the reviewed style meanings. No browser layout inspection was performed. An initial render exposed fallback machine topic labels; one display-label/grammar and gap-summary repair was rendered for this same case. Both immutable artifact directories remain preserved; original observations, style points and portrait warrants match exactly between them. No new evidence generation or experiment followed.

Profile 318 still resolves to V8 description fingerprint `0b6f4d0cedaf64a0f4cfc2958c3101e8605823c5090e845a43fcbea2daed8545`; its original manifest and artifacts are unchanged. Focused verification: 29 profile/inventory/portability tests and 10 plan tests; no corpus evaluation. Implementation commits: `32ec7c0`, `9e547cf`.

### P1.4 Consequential recommendation and exit

Deliver this partial profile for Brian’s concrete review. Do not require a complete theological portrait to deliver supported style and emphasis. The highest-impact missing statement is an apparent adopted center: exact compatible local proposition/voice/adoption/conditions are absent from the supplied reviewed packet. The smallest conditional remedy is one bounded reading at the existing upstream theological/shared binding producer for a specific center-relevant proposition, reusing compatible saved evidence first. Pastoral posture similarly needs an act/recipient/voice/adoption binding; raw listener answers and application examples are insufficient. Neither remedy is authorized automatically, and other G1/G2/G3 stores remain an explicit uninspected reuse path before any new judgment.

Sampling, dominant style, Scripture argument, accepted identity, comparison and short quotations retain their separate precise gaps and boundaries. Automatic assembly now works for this second bounded case, but useful local descriptions and cross-point warrants still require manual authoring. Two examples do not establish a general generator, independent validation, calibration or ministry-wide stability.

**Exit met:** one actual second profile and its consequential-gap report. Stop after this case; Brian reviews the prepared result. No provider/model calls, new measurements, broader collection, production admission, ranking or quotation execution occurred.

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

These default commands preserve profile 318. The explicit profile 130 commands above reproduce P1. Normally Brian executes dataset validation; a specific exception may authorize Codex, as it did for V6–V8. No standing permission for future model calls is inferred. All new workflows need a `pte` CLI tie-in, exact prepared inputs and Markdown/JSON review reports. Preserve unrelated working-tree changes and commit coherent work frequently.

The [pre-portability implementation snapshot](PASTOR_PROFILE_IMPLEMENTATION_PLAN.historical-before-portability-2026-10-23.md) preserves the full prior roadmap and completed increments. [Historical documentation index](PASTOR_PROFILE_HISTORY.md) identifies the exact snapshots. Archived commands are not active instructions. No cached results, receipts, source evidence or prior profile output has been deleted.
