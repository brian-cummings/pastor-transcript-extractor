# Existing pipeline evidence trace and cleanup plan

**Keep the existing minute-block pipeline.** The trace confirms a missing integration/handoff question; it does not establish a need to replace transcript segmentation or repeat semantic-contract research. The next design should address exact target nomination and bounded reporting/explanatory context within the existing pipeline. No new model or experiment is selected here.

This was a provider-free trace of the already selected **24 cases / three retired sources**, not corpus evaluation, reclassification, discovery matching or a semantic run. No model loaded and no provider requests occurred. Generated detail stays under the configured application base: [pipeline-trace-v1.json](/Users/briancummings/Documents/PastorSearchData/evaluation/evidence-pipeline-trace-v1/pipeline-trace-v1.json). Fingerprint: `3799f816a236ab5b32ce20748a3c5cb0e720d178343a4df52774e2e6a91629bb`.

## What actually exists

| Source | Persisted path | Saved blocks | Reconstructed current minute blocks | Persisted topic blocks / analysis runs |
|---|---|---:|---:|---:|
| 520 | Ollama gemma3:4b / adaptive_llm_v7 | 33 | 46 | 0 / 0 |
| 1094 | Jev 1.13 / typesafe_first_v10 | 53 | 49 | 0 / 0 |
| 951 | Ollama gemma3:4b / adaptive_llm_v7 | 59 | 69 | 0 / 0 |

The saved blocks include coarse and fine stages. The two Ollama artifacts include roughly 90-second fine blocks; the TypeSafe artifact uses an older 60-second builder. Historical block IDs can repeat between stages, so the trace preserves artifact ordinals as well as IDs/timestamps. They cannot be treated as uniform current minute-block outputs. The current deterministic reconstruction uses the actual `build_transcript_blocks` function with the TypeSafe path's 60-second/3,200-character settings, the full persisted transcript stream and caption normalization. It **does not** replay current coarse eligibility, sermon membership or topic routing. Existing classifications are not new current-model measurements.

All three reviewed canonical texts and normalized-unit source-index lineages were reproduced exactly from the saved extraction segments. Source **520 has a manifest discrepancy**: its row says local ASR, while the extraction and canonical source use captions. This finding is disclosed without modifying old manifests, sources, reference definitions or conclusions. Exact word-level timestamps are unavailable; span-to-time mappings conservatively use the contributing normalized units.

## What the blocks/context can expose

The trace tests only source-string availability under whitespace normalization. It does not repair expected text or semantic targets, assign voice/adoption, establish sufficiency or award discovery credit. Literal matches are recorded separately. Additional context required by source review may exist beyond this deliberately specified footprint.

| Adequate case | Route | One center block | Current short topic context | Whole immediate-neighbor diagnostic |
|---|---|---|---|---|
| CE-01 | G2 | no | yes | yes |
| CE-02 | G2 | yes | yes | yes |
| CE-03 | G2 | no | no | no |
| CE-04 | G2 | yes | yes | yes |
| CE-05 | G3_current | yes | yes | yes |
| CE-06 | G3_current | yes | yes | yes |
| CE-07 | G3_current | yes | yes | yes |
| CE-08 | G3_current | yes | yes | yes |
| CE-09 | G3_reported | yes | yes | yes |
| CE-10 | G3_reported | yes | yes | yes |
| CE-11 | G3_reported | no | no | no |
| CE-12 | G3_reported | no | no | no |

The center contains the footprint in **8/12**, and the existing short topic/role contexts in **9/12**. These are descriptive selected-case availability counts, **not recall or a PASS**. No new gate or denominator is introduced. The full-neighbor column is a source-only counterfactual, not an implemented/routed request.

Three instructive gaps remain:

- **CE-03, G2 taken/left:** the Biblical anchor is in the source neighborhood around 2756–2803 seconds; the destruction explanation appears around 2874–2919 seconds. The anchor's immediate-neighbor window does not contain the directed pair and required support together. A wider coarse block does, but that does not establish a valid exact pair or a bounded link-selection mechanism.
- **CE-11, reported Matt request:** the request is around 480–580 seconds, but Matt's identity is introduced around 376–426 seconds. A locally complete request is not enough to resolve the reported source. The trace does not turn it into current-preacher speech.
- **CE-12, reported Paul exhortation:** the act is around 453–483 seconds; Pauline letter attribution lies in a normalization unit around 336–421 seconds. Short context also misses the virtues antecedent in the selected best local view; whole immediate neighbors recover the virtues but still lack Paul identity. Citation/attribution carryover is a distinct contextual requirement.

These time ranges are conservative normalized-unit bounds, not precise utterance timestamps. Wider context can contain several valid acts and speakers; availability never certifies a clean target.

The existing context policies explain why the gaps matter. Role context is one sentence up to 400 characters from each adjacent block. Topic context is up to two sentence units/400 characters per side. Some existing leaf questions explicitly permit context only to clarify the center target, not independently establish a relationship. Reusing those questions unchanged cannot silently make a cross-block G2 pair into center-block evidence. New nomination transport/questions, if needed, must be versioned separately from the closed measurement/admission semantics.

## A minute is a target, not an invariant

Current deterministic reconstruction produces blocks longer than 60 seconds when a normalized source unit itself cannot be split by the builder: **2/46** on 520 (maximum 84.72 s), **2/49** on 1094 (68.4 s), and **20/69** on 951 (201.52 s). None exceeds 3,200 characters. CE-02 and CE-04's apparent center coverage, among others, includes an over-60-second block. This is a diagnostic of the existing substrate, not a repair proposal or grounds to rescore old experiments.

## Recommended next design

Use the existing minute block as a processing anchor. Its evidence nomination request should carry verified canonical source/segment mapping, a separately labeled bounded context envelope, and source-grounded links to earlier reporting/attribution or the other G2 role when needed. Record unresolved links as deferrals. A nominated utterance/pair can span blocks without altering the block IDs, timestamps or existing classification results.

The nomination stage should return exact source geometry, retain supporting block provenance and deduplicate overlapping observations. It must not inherit semantic authority from an extractor label or an old topic score. Existing downstream measurement/admission remains a separate validated boundary; A1's historical panel authority is not automatically extended.

TypeSafe position selection and Ollama generation are still alternatives for that narrow stage. **Do not select a replacement model or run the standalone oracle-context probe yet.** First specify this pipeline handoff and context-link policy, showing how it supplies the three demonstrated remote dependencies. That is a design task, not another model-comparison or collector-tuning experiment.

## Cleanup plan

Cleanup is planned, not executed. The inventory covers **93 files in nine proposal directories**, about 4,984,002 bytes. Several folders are referred to by later JSON/hash manifests. Moving/deleting them blindly would break audit verification. Some Python support modules are shared by surviving audits as well.

1. **Consolidate active navigation now.** The review-proposal index points here and labels historical work explicitly. Keep old frozen packet bytes unchanged.
2. **Close the OpenAI probe as unexecuted/superseded, then detach its execution path in a bounded cleanup change.** It has zero requests/receipts and no experimental verdict. Preserve its authorization/input history; do not call it FAIL. Retire `context_extraction_probe.py`, its adapter and execution tests after preserving a verifiable frozen snapshot. Keep validator ideas only if the new handoff needs them. A companion supersession decision should close the historical execution authorization before any executable cleanup; do not rewrite the old authorization.
3. **Retire V1/V1.1 collector runners and old fresh-discovery execution surfaces together.** Preserve their accepted failure decisions/audits and the shared source/serialization support still used by verifiers. Build a file/import/hash dependency manifest before deleting modules or unregistering CLI modes. No V1.2 or resurrection of the closed collector.
4. **Archive obsolete proposal prose and consider disposable external caches only after that dependency pass.** Prefer index/archive labels before physical moves. Keep raw receipts, frozen source/reference/results and accepted G1/G2/G3/V4/A1 history. Any tokenizer/MiniLM runtime deletion needs its own precise file/size/checksum manifest. Installed Ollama models and TypeSafe configuration are outside cleanup scope.

The three unrelated untracked `evaluation/evidence-supply-readiness-v2` files were left alone. They are a separate generated-artifact placement issue; do not incorporate or remove them incidentally. No dataset, cache, source, receipt or historical result was deleted, moved or rewritten in this work. No old experimental authorization is newly exercised by this review.

## Verification and CLI

**46 focused tests passed**, including the trace's whitespace/literal distinction, source coordinate checks, conservative timestamps, stage-disambiguated block identity, over-size visibility, configured-base output placement and read-only CLI verification, plus existing CLI/probe/proposal checks. The old frozen probe still verifies with its original fingerprint. All new generated outputs are outside the repository.

```bash
pte analysis structure-readiness --evidence-trace --check-only
```

The same command without `--check-only` reconstructs only this fixed three-source/24-case diagnostic and writes the base-directory report. It cannot call a provider, classify, select fresh sources, collect evidence or produce a pastor profile. The earlier exploratory `trace-v1.json` in that base-directory folder is retained as a preliminary diagnostic; the reviewed report is **`pipeline-trace-v1.json`** and has the fingerprint above.

[review-v1.json](review-v1.json) binds the interpretation, cleanup inventory and recommendations to the generated trace. G1 remains HOLD, retired collector failures and V4/A1 decisions remain unchanged; natural retrieval, general containment, review burden, economics, recurrence and projection remain unestablished.
