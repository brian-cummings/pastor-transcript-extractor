# Minute-block handoff — implementation and source-only preparation review

**Provider-free implementation and preparation are complete. No inference or admission was performed.** The real minute-block path now has canonical source/center mapping, bounded context construction, strict untrusted nomination validation, duplicate/conflict preservation and a data-only prospective measurement mapping. All generated materialization data are under the configured application base directory.

The preparation produced **19/24 prepared slots**, **13 distinct contexts** and **14 distinct G2/G3 family/context bindings**. **Five slots defer**, all on source 951, because their anchors lie wholly outside its saved retained-segment membership. This is a substantive upstream membership limitation, not a model or context-planning failure. Nine of the twelve adequate diagnostic slots prepare; these counts do not establish discovery recall, semantics or a pass against the retired probe's criteria.

Input fingerprint: `cf57f22066a32a18c26165fe3ea239271d52627cd3531679c78df7fc49b5a769`.

Generated preparation: [preparation-v1.json](/Users/briancummings/Documents/PastorSearchData/evaluation/minute-evidence-handoff-v1/cf57f22066a32a18c26165fe3ea239271d52627cd3531679c78df7fc49b5a769/preparation-v1.json).

## Implemented behavior

- Reconstruct each canonical snapshot from the persisted caption segments using the exact normalization policy. Verify source text hash, unit coordinates, source segment identities and timestamp bounds. Source 520's ASR/caption manifest discrepancy remains disclosed; the verified extraction is captions.
- Match the full center text and unit membership exactly. No first-substring selection, whitespace/fuzzy correction or ambiguous source ownership can establish a center mapping. Blocks outside reviewed main-source bounds, with partial/absent retained membership, incomplete unit provenance or mismatched text/timing defer.
- Plan one contiguous canonical envelope centered on the existing block with nominal 120-second padding on each side. Preserve the whole anchor and cap at 6,000 characters by trimming optional context only. Record budget/whitespace/unit-boundary cuts, earlier/later source and **context completeness unestablished**. Oversized anchors defer without truncation or automatic expansion.
- Bind fixture identities to source proof, center, context, task family, routing/question version and prospective provider lock. These are **preparation bindings, not executable model requests**: model digest/prompt/token budgets remain unresolved and provider-cache reuse is disabled.
- Validate exact absolute canonical role coordinates, field inventories, G2 nonoverlap, G3 role shape, declared dependencies, provenance supports, source/request bindings, four-nomination limit and verified center intersection. Context-only targets are rejected. A G2 pair/G3 utterance may cross a block boundary while preserving center ownership.
- Deduplicate exact geometry without merging current/reported hypotheses. Preserve all originating contexts and conflicts, assigning deterministic ownership after literal validation. Every record remains untrusted with `usable_evidence=false`.
- Produce only a **BLOCKED_ADAPTER_AND_REVIEW_REQUIRED** data mapping: exact roles/envelope and origin bindings. Extractor provenance hypotheses are not promoted into measurement state; no question/interpreter, Measurement, LocalEvidence, review witness, consumer or admission path is invoked.

Literal validation cannot detect a condition the model omitted without declaring, resolve a true speaker or attest adoption. Tests deliberately retain that limitation. No qualification, source or semantic contract is silently repaired.

## All prepared slots

The 24 slots are the old trace-selected diagnostic locators, **not naturally discovered opportunities**. No alternative anchor is chosen to rescue a deferral. Clipped counterparts now locate the same minute context as their parents; they are not clipped-context controls in this implementation. Wider contexts may contain additional valid events. No old denominator, raw-error count, 10/12 criterion or authority is transferred.

| Slot | Route | Trace anchor | Status | Context characters | Reviewed diagnostic footprint inside |
|---|---|---:|---|---:|---|
| CE-01 | G2 | 9 | prepared_context_only | 5673 | yes |
| CE-02 | G2 | 43 | prepared_context_only | 5995 | yes |
| CE-03 | G2 | 48 | deferred | — | — |
| CE-04 | G2 | 18 | prepared_context_only | 4170 | yes |
| CE-05 | G3_current | 64 | deferred | — | — |
| CE-06 | G3_current | 22 | prepared_context_only | 4470 | yes |
| CE-07 | G3_current | 59 | deferred | — | — |
| CE-08 | G3_current | 6 | prepared_context_only | 5802 | yes |
| CE-09 | G3_reported | 17 | prepared_context_only | 5992 | yes |
| CE-10 | G3_reported | 21 | prepared_context_only | 5999 | yes |
| CE-11 | G3_reported | 8 | prepared_context_only | 5999 | yes |
| CE-12 | G3_reported | 9 | prepared_context_only | 5673 | yes |
| CE-13 | G2 | 9 | prepared_context_only | 5673 | yes |
| CE-14 | G2 | 18 | prepared_context_only | 4170 | yes |
| CE-15 | G3_current | 22 | prepared_context_only | 4470 | yes |
| CE-16 | G3_current | 59 | deferred | — | — |
| CE-17 | G3_reported | 17 | prepared_context_only | 5992 | yes |
| CE-18 | G3_reported | 8 | prepared_context_only | 5999 | yes |
| CE-19 | G2 | 15 | prepared_context_only | 5998 | yes |
| CE-20 | G2 | 11 | prepared_context_only | 3641 | yes |
| CE-21 | G3_current | 4 | prepared_context_only | 5989 | yes |
| CE-22 | G3_current | 1 | prepared_context_only | 3928 | yes |
| CE-23 | G3_reported | 12 | prepared_context_only | 4970 | yes |
| CE-24 | G3_current | 65 | deferred | — | — |

All 19 prepared contexts contain their diagnostic focal/support footprints under canonical geometry; this is not a semantic completeness finding. Contexts range from 3641 to 5999 characters. The CE-11 reporting-identity example prepares as [4059,10058) after optional whitespace trimming, and CE-12 as [5592,11265). CE-03 defers on saved membership before context planning, even though its source-only arithmetic was representable in the proposal.

## The upstream membership conflict

All five deferred anchors are wholly absent from source 951's saved retained membership:

| Slot | Kind | Anchor | Conservative anchor seconds | Retained / anchor segments |
|---|---|---:|---|---:|
| CE-03 | adequate | 48 | 2756.32–2810.72 | 0 / 42 |
| CE-05 | adequate | 64 | 3742.72–3800.16 | 0 / 45 |
| CE-07 | adequate | 59 | 3481.04–3557.68 | 0 / 72 |
| CE-16 | clipped | 59 | 3481.04–3557.68 | 0 / 72 |
| CE-24 | control | 65 | 3800.16–3843.28 | 0 / 36 |

The saved adaptive/Ollama sermon window ends at **2608.4 seconds**. The frozen source-only review explicitly restored the continuous later sermon because that old end stopped mid-sermon reported conversation; it also removed an earlier children-story/host section. Those are separate artifacts with different authority and scope: a source-study main interval is not automatically persisted production membership.

The adapter correctly preserves that distinction and does not override saved retained indices with the larger reviewed interval. It also does not label genuinely present source text as an extraction failure. The three adequate slots affected are CE-03, CE-05 and CE-07; CE-16 is a related diagnostic locator and CE-24 a control locator. Historical source/reference/classification artifacts are unchanged.

**Recommendation before any model run:** specify the precedence and binding between an explicitly reviewed source-window correction and persisted retained membership. Use these five existing slots to show the result, preserve the original extraction and review, and make any prospective effective-membership overlay explicit and fingerprint-bound. Do not silently widen the sermon, reclassify it, tune the collector or treat the old study review as automatic production authorization. This is the upstream handoff issue Brian identified, now evidenced by the actual adapter.

## Backend and execution holds

Preparation reads only local configuration: configured `gemma3:4b`, context setting 4096. It performs no Ollama metadata/health lookup, model loading, tokenizer acquisition or inference. There is no provider executor, locked digest, prompt, API payload, token/output/runtime budget or runnable nomination queue. The 6,000-character cap is not a token-cap guarantee; a later separately approved run packet must account for the full request and output reserve against the actual configured model limits.

No Jev calls, .80 threshold/question changes, automatic provenance, A1 authority transfer, fresh-source selection, collector reopening, collection activation, 790-item audit, recurrence/economics or projection/comparison/scoring is authorized or executed. The OpenAI probe remains superseded and blocked.

## Verification and review commands

**67 focused tests passed.** They cover exact source mapping, repeated text, missing retention, normalization/timing mismatch, oversized anchors, optional-only context trimming, context-only nomination rejection, cross-block G2 geometry, declared qualification dependencies, unsupported provenance, four-item limits, duplicate/conflicting source hypotheses, cache identity changes and data-only authority stripping. Historical CLI/proposal and probe-retirement checks also pass. Provider calls: **zero**.

```bash
pte analysis structure-readiness --check-handoff --json
pte analysis collector-retrieval-design --context-extraction-probe --check-only
```

`--prepare-handoff` materializes only this fixed provider-free diagnostic into the configured base directory. `--handoff-proposal --check-only` verifies the original proposal using Git `ac4ed19` for the two explicitly authorized implementation overlays (CLI and review index). It does not reinterpret the original proposal's historical authorization fields. [authorization-v1.json](authorization-v1.json) records the current implementation permission separately.

[review-v1.json](review-v1.json) and [preparation-manifest-v1.json](preparation-manifest-v1.json) bind this review to the generated preparation. The unrelated untracked V2 evaluation files and external model/data caches are untouched. No broad cleanup or dataset deletion was performed.
